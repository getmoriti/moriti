"""
moriti as a Google ADK plugin.

How it fits ADK
---------------
ADK fires ``after_tool_callback(tool, tool_args, tool_context, result)`` after
every tool returns, and the dict the callback returns *replaces* the result
the agent sees. That is the response-path interception point: the plugin
hands the result to ``PrivacyPlane.mediate()`` under a purpose bound in the
deployment config, and the agent receives only what policy released.

``before_tool_callback`` enforces the deployment's tool allowlist. Returning a
dict there short-circuits the call, so a disallowed tool is never invoked.

Where purpose comes from
------------------------
The deployment config, at construction. Not the model, not the tool
arguments, not the session. An agent that could declare its own purpose
would declare whichever one unlocks the data.

Failure posture
---------------
Closed. If mediation raises, or a result cannot be handed back as a dict,
the agent gets a refusal, never the unmediated result.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from moriti import PrivacyPlane
from moriti.adapters.common import DeploymentConfig, infer_subject, mediate_value

logger = logging.getLogger("moriti.adk")


class MoritiPlugin(BasePlugin):
    """Rewrites every tool result under a deployment-bound privacy policy."""

    def __init__(self, deployment: DeploymentConfig | dict[str, Any], *, name: str = "moriti") -> None:
        super().__init__(name=name)
        self.deployment = (
            deployment if isinstance(deployment, DeploymentConfig) else DeploymentConfig(**deployment)
        )
        self.plane = PrivacyPlane.from_policy(self.deployment.policy)
        logger.info(
            "moriti ADK plugin up: agent=%s purpose=%s policy=%s",
            self.deployment.agent, self.deployment.purpose, self.plane.policy.name,
        )

    @classmethod
    def from_yaml(cls, path: str | Path, *, name: str = "moriti") -> MoritiPlugin:
        """Build from a deployment file. The proxy's deployment files work unchanged."""
        return cls(DeploymentConfig.from_yaml(path), name=name)

    # -- hooks --------------------------------------------------------------------

    async def before_tool_callback(
        self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext
    ) -> dict[str, Any] | None:
        if self.deployment.tool_allowed(tool.name):
            return None
        logger.warning("Tool %r refused for agent %r: not in the deployment allowlist", tool.name, self.deployment.agent)
        return _refusal(f"Tool {tool.name!r} is not permitted for agent {self.deployment.agent!r}")

    async def after_tool_callback(
        self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext, result: dict[str, Any]
    ) -> dict[str, Any] | None:
        ctx = self.deployment.context(
            tool.name, principal=_user_of(tool_context), data_subject=infer_subject(tool_args or {})
        )
        withheld: list[str] = []
        try:
            rewritten = mediate_value(self.plane, result, ctx, withheld)
        except Exception:
            logger.exception("Mediation failed for %r; failing closed", tool.name)
            return _refusal("Privacy mediation failed; response withheld")
        if not isinstance(rewritten, dict):
            # ADK hands tool results to the model as dicts; anything else cannot go back safely.
            return _refusal("Tool result could not be field-mediated; response withheld")
        logger.info(
            "mediated %s for agent=%s purpose=%s: withheld=%s",
            tool.name, self.deployment.agent, self.deployment.purpose, sorted(set(withheld)),
        )
        return rewritten


def _user_of(tool_context: Any) -> str | None:
    """The session's user, if the context carries one. Informational; never a policy input by itself."""
    session = getattr(tool_context, "session", None)
    user = getattr(session, "user_id", None)
    return str(user) if user else None


def _refusal(reason: str) -> dict[str, Any]:
    return {"moriti": "refused", "reason": reason}
