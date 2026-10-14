"""
Shared pieces for gateway adapters.

Two things every adapter needs and none should reinvent: the deployment
vocabulary (one agent, one bound purpose) and the recursive mediation of a
tool result. No privacy semantics live here either; everything below hands
values to ``PrivacyPlane.mediate()`` and shapes what comes back.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from moriti import Destination, LegalBasis, PrivacyPlane, RequestContext, Retention
from moriti._config import reject_unknown_keys

logger = logging.getLogger("moriti.adapters")

WITHHELD_UNSTRUCTURED = {
    "moriti": "unstructured tool output withheld by privacy policy",
    "reason": "only structured (JSON) results can be field-mediated",
}


class DeploymentConfig(BaseModel):
    """One agent, one purpose, bound at provisioning time.

    The same vocabulary as the proxy's deployment YAML, so a single file can
    configure the proxy, the ContextForge plugin and the ADK plugin alike.
    The proxy's ``downstream`` block is accepted and ignored. Any other key this model does
    not define is an error, so a misspelt key cannot silently drop a protection.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _no_unknown_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "downstream"}  # the proxy's block; not ours
        return reject_unknown_keys(data, cls.model_fields, "deployment")

    #: Agent identity this deployment serves.
    agent: str
    #: The purpose bound here. The agent cannot declare or change it.
    purpose: str
    #: Policy pack name under moriti/policies/.
    policy: str
    principal: str | None = None
    principal_role: str | None = None
    destination: Destination = Destination.INTERNAL_MODEL
    retention: Retention = Retention.EPHEMERAL
    jurisdiction: str | None = None
    legal_basis: LegalBasis | None = None
    consent_scopes: list[str] = Field(default_factory=list)
    #: Tools the agent may call. Empty = all tools.
    allowed_tools: list[str] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str | Path) -> DeploymentConfig:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls.model_validate(_policy_beside(data, Path(path)))

    def context(
        self, tool: str, *, principal: str | None = None, data_subject: str | None = None
    ) -> RequestContext:
        """A request context built from the deployment. Nothing in it came from the agent."""
        return RequestContext(
            agent=self.agent,
            principal=principal or self.principal,
            principal_role=self.principal_role,
            data_subject=data_subject,
            purpose=self.purpose,
            tool=tool,
            destination=self.destination,
            retention=self.retention,
            jurisdiction=self.jurisdiction,
            legal_basis=self.legal_basis,
            consent_scopes=list(self.consent_scopes),
        )

    def tool_allowed(self, name: str) -> bool:
        return not self.allowed_tools or name in self.allowed_tools


def _policy_beside(data: Any, deployment_path: Path) -> Any:
    """`policy: ./my_pack.yaml` in a deployment file means next to that file, wherever it is loaded from."""
    if isinstance(data, dict) and isinstance(data.get("policy"), str):
        candidate = deployment_path.parent / data["policy"]
        if data["policy"].endswith((".yaml", ".yml")) and not Path(data["policy"]).is_absolute() and candidate.exists():
            data = {**data, "policy": str(candidate)}
    return data


def infer_subject(arguments: dict[str, Any]) -> str | None:
    """Best-effort data-subject reference from a tool's arguments, for the audit trail only."""
    for key in ("name", "employee", "employee_id", "customer_id", "id"):
        if key in arguments:
            return str(arguments[key])
    return None


def mediate_value(plane: PrivacyPlane, value: Any, ctx: RequestContext, withheld: list[str]) -> Any:
    """Every dict is a record and gets mediated; lists are mediated element-wise; scalars pass."""
    if isinstance(value, dict):
        outcome = plane.mediate(value, ctx)
        withheld.extend(outcome.withheld)
        return outcome.data
    if isinstance(value, list):
        return [mediate_value(plane, v, ctx, withheld) for v in value]
    return value


def mediate_text(plane: PrivacyPlane, text: str, ctx: RequestContext, withheld: list[str]) -> str:
    """JSON text is mediated as data. Free text cannot be field-mediated and is withheld: fail closed."""
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Non-JSON text result withheld (%d chars)", len(text))
        return json.dumps(WITHHELD_UNSTRUCTURED)
    return json.dumps(mediate_value(plane, value, ctx, withheld))
