"""
moriti as a Strands Agents hook provider.

How it fits Strands
-------------------
Strands fires ``BeforeToolCallEvent`` and ``AfterToolCallEvent`` around every
tool call. A hook may set ``cancel_tool`` on the before event, in which case
the tool never runs and the model receives that message, and may replace
``result`` on the after event, which is what the model then sees. Those two
writable fields are the whole integration: allowlist before, per-field
mediation after.

Where purpose comes from
------------------------
The deployment config, at construction. Not the model, not the tool input,
not the invocation state. The same deployment files as the proxy.

Failure posture
---------------
Closed. Text blocks are mediated as JSON or withheld; ``json`` blocks are
mediated as data; images and documents are dropped. If mediation raises, the
result becomes an error carrying a refusal, never the unmediated content.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import AfterToolCallEvent, BeforeToolCallEvent

from moriti import PrivacyPlane
from moriti.adapters.common import DeploymentConfig, infer_subject, mediate_text, mediate_value

logger = logging.getLogger("moriti.strands")


class MoritiHooks(HookProvider):
    """Allowlists tools before they run and rewrites every tool result under a bound purpose."""

    def __init__(self, deployment: DeploymentConfig | dict[str, Any]) -> None:
        self.deployment = (
            deployment if isinstance(deployment, DeploymentConfig) else DeploymentConfig(**deployment)
        )
        self.plane = PrivacyPlane.from_policy(self.deployment.policy)
        logger.info(
            "moriti Strands hooks up: agent=%s purpose=%s policy=%s",
            self.deployment.agent, self.deployment.purpose, self.plane.policy.name,
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> MoritiHooks:
        """Build from a deployment file. The proxy's deployment files work unchanged."""
        return cls(DeploymentConfig.from_yaml(path))

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool_call)
        registry.add_callback(AfterToolCallEvent, self.after_tool_call)

    # -- hooks --------------------------------------------------------------------

    def before_tool_call(self, event: BeforeToolCallEvent) -> None:
        name = str(event.tool_use.get("name", ""))
        if self.deployment.tool_allowed(name):
            return
        logger.warning("Tool %r refused for agent %r: not in the deployment allowlist", name, self.deployment.agent)
        event.cancel_tool = f"Tool {name!r} is not permitted for agent {self.deployment.agent!r}"

    def after_tool_call(self, event: AfterToolCallEvent) -> None:
        name = str(event.tool_use.get("name", ""))
        arguments = event.tool_use.get("input")
        ctx = self.deployment.context(name, data_subject=infer_subject(arguments if isinstance(arguments, dict) else {}))
        result = event.result
        withheld: list[str] = []
        try:
            content = []
            for block in result.get("content", []):
                if "json" in block:
                    content.append({"json": mediate_value(self.plane, block["json"], ctx, withheld)})
                elif "text" in block:
                    content.append({"text": mediate_text(self.plane, block["text"], ctx, withheld)})
                else:
                    logger.warning("Dropping non-text content block %s from %r", sorted(block), name)
            event.result = {**result, "content": content}
        except Exception:
            logger.exception("Mediation failed for %r; failing closed", name)
            event.result = {
                "toolUseId": result.get("toolUseId", ""),
                "status": "error",
                "content": [{"text": json.dumps({"moriti": "refused", "reason": "Privacy mediation failed; response withheld"})}],
            }
            return
        logger.info(
            "mediated %s for agent=%s purpose=%s: withheld=%s",
            name, self.deployment.agent, self.deployment.purpose, sorted(set(withheld)),
        )
