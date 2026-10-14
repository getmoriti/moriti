"""
moriti as Microsoft Agent Framework *function middleware*.

How it fits Agent Framework
---------------------------
Every tool call passes through the agent's function middleware as
``process(context, call_next)``. Before ``call_next()`` the middleware sees the
function and its arguments; after it, ``context.result`` is what the model
will receive, and the middleware may replace it. Refusing a call is an
exception, ``MiddlewareTermination``, which carries the result the model gets
instead. Those two moves are the whole integration: allowlist before,
per-field mediation after.

Where purpose comes from
------------------------
The deployment config, at construction. Not the model, not the arguments,
not the session. The same deployment files as the proxy.

Failure posture
---------------
Closed. Dicts, lists and JSON text are mediated; pydantic models are dumped
and mediated; scalars pass; anything else, and any mediation error, becomes
a refusal, never the unmediated result.

What the framework actually hands over
--------------------------------------
After ``call_next()`` the result of a real tool is ``list[Content]``: the
framework has already turned the function's return value into content items.
Text items are the tool's output (JSON text for a dict) and are mediated like
any JSON text. A result with any other kind of content (an image, a file, a
URI) cannot be field-mediated and is refused whole.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent_framework import Content, FunctionInvocationContext, FunctionMiddleware, MiddlewareTermination

from moriti import PrivacyPlane
from moriti.adapters.common import DeploymentConfig, infer_subject, mediate_text, mediate_value

logger = logging.getLogger("moriti.agentframework")


def _refusal(reason: str) -> dict[str, Any]:
    return {"moriti": "refused", "reason": reason}


class MoritiFunctionMiddleware(FunctionMiddleware):
    """Allowlists tools before they run and rewrites every result under a bound purpose."""

    def __init__(self, deployment: DeploymentConfig | dict[str, Any]) -> None:
        super().__init__()
        self.deployment = (
            deployment if isinstance(deployment, DeploymentConfig) else DeploymentConfig(**deployment)
        )
        self.plane = PrivacyPlane.from_policy(self.deployment.policy)
        logger.info(
            "moriti Agent Framework middleware up: agent=%s purpose=%s policy=%s",
            self.deployment.agent, self.deployment.purpose, self.plane.policy.name,
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> MoritiFunctionMiddleware:
        """Build from a deployment file. The proxy's deployment files work unchanged."""
        return cls(DeploymentConfig.from_yaml(path))

    async def process(self, context: FunctionInvocationContext, call_next) -> None:
        name = str(getattr(context.function, "name", ""))
        if not self.deployment.tool_allowed(name):
            logger.warning("Tool %r refused for agent %r: not in the deployment allowlist", name, self.deployment.agent)
            raise MiddlewareTermination(
                f"Tool {name!r} is not permitted for agent {self.deployment.agent!r}",
                result=_refusal(f"Tool {name!r} is not permitted for agent {self.deployment.agent!r}"),
            )

        await call_next()

        arguments: Any = context.arguments
        if hasattr(arguments, "model_dump"):
            arguments = arguments.model_dump()
        ctx = self.deployment.context(
            name,
            principal=_user_of(context.session),
            data_subject=infer_subject(arguments if isinstance(arguments, dict) else {}),
        )
        withheld: list[str] = []
        try:
            context.result = self._mediate(context.result, ctx, withheld)
        except Exception:
            logger.exception("Mediation failed for %r; failing closed", name)
            context.result = _refusal("Privacy mediation failed; response withheld")
            return
        logger.info(
            "mediated %s for agent=%s purpose=%s: withheld=%s",
            name, self.deployment.agent, self.deployment.purpose, sorted(set(withheld)),
        )

    def _mediate(self, value: Any, ctx, withheld: list[str]) -> Any:
        if isinstance(value, Content):
            value = [value]
        if isinstance(value, list) and value and all(isinstance(item, Content) for item in value):
            # What a real tool returns: the framework's content items. Text is the tool's output.
            if not all(item.type == "text" and isinstance(item.text, str) for item in value):
                return _refusal("Tool result could not be field-mediated; response withheld")
            return [Content.from_text(text=mediate_text(self.plane, item.text, ctx, withheld)) for item in value]
        if isinstance(value, list) and any(isinstance(item, Content) for item in value):
            return _refusal("Tool result could not be field-mediated; response withheld")
        if hasattr(value, "model_dump"):
            value = value.model_dump()
        if isinstance(value, (dict, list)):
            return mediate_value(self.plane, value, ctx, withheld)
        if isinstance(value, str):
            return mediate_text(self.plane, value, ctx, withheld)
        if value is None or isinstance(value, (bool, int, float)):
            return value  # nothing personal can hide in a scalar
        return _refusal("Tool result could not be field-mediated; response withheld")


def _user_of(session: Any) -> str | None:
    user = getattr(session, "user_id", None)
    return str(user) if user else None
