"""
moriti as a ContextForge (cpex) ``tool_post_invoke`` plugin.

How it fits the gateway
-----------------------
ContextForge calls ``tool_post_invoke(payload, context)`` after a tool runs.
``payload.result`` is the tool's MCP ``CallToolResult`` dumped to a dict
(``content[]``, ``structuredContent``, ``isError``). Returning
``modified_payload`` with a rewritten ``result`` makes the gateway rebuild the
response the agent receives from *our* result -- the gateway's own hook
policy lists ``result`` as writable for this hook, so the rewrite survives.
Returning ``continue_processing=False`` plus a ``PluginViolation`` turns the
call into an MCP error instead.

Where purpose comes from
------------------------
The gateway knows who the user is and which tenant/server the call belongs
to. It has no concept of *purpose*. So purpose is bound here, in the plugin's
``config`` block, at provisioning time -- one plugin instance per deployment,
scoped with ``conditions`` -- exactly as the standalone proxy does. The agent
never declares it and cannot vary it.

Failure posture
---------------
Closed. Non-JSON text is withheld rather than passed through; an engine error
becomes a violation and the result is replaced with a refusal, never the
unmediated payload. The replacement matters: in cpex's ``transform`` mode a
violation is suppressed and the pipeline continues, so a violation alone would
let the original result through. Binary/resource content blocks are dropped --
this adapter mediates structured results only.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from cpex.framework import Plugin, PluginContext
from cpex.framework.hooks.tools import ToolPostInvokePayload, ToolPostInvokeResult
from cpex.framework.models import PluginConfig, PluginViolation
from pydantic import ValidationError

from moriti import PrivacyPlane, RequestContext
from moriti.adapters.common import DeploymentConfig

logger = logging.getLogger("moriti.contextforge")

VIOLATION_CODE = "MORITI_MEDIATION_FAILED"

WITHHELD_UNSTRUCTURED = {
    "moriti": "unstructured tool output withheld by privacy policy",
    "reason": "only structured (JSON) results can be field-mediated by this plugin",
}


class MoritiPrivacyPlugin(Plugin):
    """Rewrites every tool result under a deployment-bound privacy policy."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        try:
            self.deployment = DeploymentConfig(**(config.config or {}))
        except ValidationError as exc:
            raise ValueError(
                f"moriti plugin {config.name!r}: invalid config block -- {exc}"
            ) from exc
        self.plane = PrivacyPlane.from_policy(self.deployment.policy)
        logger.info(
            "moriti plugin up: agent=%s purpose=%s policy=%s",
            self.deployment.agent, self.deployment.purpose, self.plane.policy.name,
        )

    # -- hook -----------------------------------------------------------------

    async def tool_post_invoke(
        self, payload: ToolPostInvokePayload, context: PluginContext
    ) -> ToolPostInvokeResult:
        # The gateway probes hooks with an empty result to build retry policy;
        # there is nothing to mediate, so let it through untouched.
        if not payload.result:
            return ToolPostInvokeResult(continue_processing=True)

        ctx = self._context(payload.name, _user_of(context))
        try:
            rewritten, withheld = self._mediate_result(payload.result, ctx)
        except Exception:
            logger.exception("Mediation failed for %r; failing closed", payload.name)
            # Two moves, because the gateway's plugin mode decides which one it honours:
            # in `sequential` mode the violation blocks the call; in `transform` mode
            # cpex suppresses a denial and carries on with whatever payload it has. The
            # refusal in `modified_payload` is therefore what keeps the original result
            # from going out.
            return ToolPostInvokeResult(
                continue_processing=False,
                modified_payload=ToolPostInvokePayload(
                    name=payload.name, result=_refusal_result(payload.result)
                ),
                violation=PluginViolation(
                    reason="Privacy mediation failed; response withheld",
                    description=(
                        "moriti could not evaluate this tool result under the "
                        "deployment's privacy policy, so it was not released."
                    ),
                    code=VIOLATION_CODE,
                    details={"tool": payload.name, "agent": self.deployment.agent},
                ),
            )

        logger.info(
            "mediated %s for agent=%s purpose=%s: withheld=%s",
            payload.name, self.deployment.agent, self.deployment.purpose, sorted(set(withheld)),
        )
        return ToolPostInvokeResult(
            continue_processing=True,
            modified_payload=ToolPostInvokePayload(name=payload.name, result=rewritten),
            metadata={
                "moriti": {
                    "agent": self.deployment.agent,
                    "purpose": self.deployment.purpose,
                    "policy": f"{self.plane.policy.name}_v{self.plane.policy.version}",
                    "withheld": sorted(set(withheld)),
                }
            },
        )

    # -- context ----------------------------------------------------------------

    def _context(self, tool: str, user: str | None) -> RequestContext:
        """Built from deployment config plus the gateway-authenticated user. Nothing from the tool."""
        d = self.deployment
        return RequestContext(
            agent=d.agent,
            principal=user or d.principal,
            principal_role=d.principal_role,
            purpose=d.purpose,
            tool=tool,
            destination=d.destination,
            retention=d.retention,
            jurisdiction=d.jurisdiction,
            legal_basis=d.legal_basis,
            consent_scopes=list(d.consent_scopes),
        )

    # -- mediation --------------------------------------------------------------

    def _mediate_result(self, result: Any, ctx: RequestContext) -> tuple[Any, list[str]]:
        """Return (rewritten result in the same shape, names of withheld fields)."""
        withheld: list[str] = []

        if isinstance(result, dict) and isinstance(result.get("content"), list):
            # MCP CallToolResult shape. Rewrite each text block; drop anything
            # we cannot field-mediate (images, embedded resources).
            content_out = []
            for block in result["content"]:
                if isinstance(block, dict) and block.get("type") == "text" and "text" in block:
                    content_out.append({**block, "text": self._mediate_text(block["text"], ctx, withheld)})
                else:
                    logger.warning("Dropping non-text content block of type %r", _type_of(block))
            out: dict[str, Any] = {**result, "content": content_out}
            for key in ("structuredContent", "structured_content"):
                if isinstance(result.get(key), (dict, list)):
                    out[key] = self._mediate_value(result[key], ctx, withheld)
            return out, withheld

        if isinstance(result, (dict, list)):
            return self._mediate_value(result, ctx, withheld), withheld

        if isinstance(result, str):
            return self._mediate_text(result, ctx, withheld), withheld

        # Numbers, booleans, None: nothing personal can hide in a scalar.
        return result, withheld

    def _mediate_text(self, text: str, ctx: RequestContext, withheld: list[str]) -> str:
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            # Free text cannot be field-mediated. Fail closed rather than let a
            # stringified record slip past policy.
            logger.warning("Non-JSON text result withheld (%d chars)", len(text))
            return json.dumps(WITHHELD_UNSTRUCTURED)
        return json.dumps(self._mediate_value(value, ctx, withheld))

    def _mediate_value(self, value: Any, ctx: RequestContext, withheld: list[str]) -> Any:
        """Every dict is a record and gets mediated; lists are mediated element-wise."""
        if isinstance(value, dict):
            outcome = self.plane.mediate(value, ctx)
            withheld.extend(outcome.withheld)
            return outcome.data
        if isinstance(value, list):
            return [self._mediate_value(v, ctx, withheld) for v in value]
        return value


def _refusal_result(original: Any) -> Any:
    """What the agent receives when mediation fails, in the same shape as the result it replaces."""
    refusal = {"moriti": "refused", "reason": "Privacy mediation failed; response withheld"}
    if isinstance(original, dict) and isinstance(original.get("content"), list):
        return {"content": [{"type": "text", "text": json.dumps(refusal)}], "isError": True}
    return refusal


def _user_of(context: PluginContext) -> str | None:
    """The gateway-authenticated user, if the context carries one."""
    global_context = getattr(context, "global_context", None)
    user = getattr(global_context, "user", None)
    return str(user) if user else None


def _type_of(block: Any) -> Any:
    return block.get("type") if isinstance(block, dict) else type(block).__name__
