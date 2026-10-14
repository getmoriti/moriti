"""
The facade: one call that evaluates, enforces and produces evidence.

This is the interception point. Today it is called explicitly; the same
`mediate()` is what an MCP proxy or API gateway would call on the response
path, which is how the control plane stops being an agent-callable utility
and starts being something an agent cannot route around.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from moriti.audit import AuditEvent, build_event, emit
from moriti.context import RequestContext
from moriti.enforcement import enforce
from moriti.policy import FieldDecision, Policy, PolicyEngine

logger = logging.getLogger(__name__)


class MediationResult(BaseModel):
    """What the agent gets, plus why."""

    data: dict[str, Any] = Field(default_factory=dict)
    decisions: list[FieldDecision] = Field(default_factory=list)
    audit: AuditEvent | None = None

    @property
    def withheld(self) -> list[str]:
        return [d.field for d in self.decisions if not d.decision.releases_value]

    def explain(self) -> str:
        """Human-readable rationale, for demos and for privacy reviewers."""
        lines = []
        for d in self.decisions:
            head = f"  {d.field}: {d.decision.value.upper()}"
            if d.restricted_by:
                head += f"  (restricted by {', '.join(d.restricted_by)})"
            lines.append(head)
            lines.append(f"      {d.reason}")
            if d.obligations:
                lines.append(f"      obligations: {', '.join(o.value for o in d.obligations)}")
        return "\n".join(lines)


class PrivacyPlane:
    """Mediates access to a record under a policy."""

    def __init__(self, policy: Policy):
        self.policy = policy
        self.engine = PolicyEngine(policy)

    @classmethod
    def from_policy(cls, ref: str) -> PrivacyPlane:
        """A plane for one policy: a file path, a name in $MORITI_POLICY_PATH, or a bundled pack name."""
        return cls(Policy.load(ref))

    def decide(self, ctx: RequestContext) -> list[FieldDecision]:
        """Evaluate without touching data -- useful for pre-flight tool-call checks."""
        return self.engine.evaluate(ctx)

    def mediate(
        self,
        record: dict[str, Any],
        ctx: RequestContext,
        audit: bool = True,
    ) -> MediationResult:
        """Evaluate the request, enforce the outcome, and record the evidence.

        If `ctx.requested_fields` is empty the whole record is treated as
        requested, so wrapping an existing tool response requires no changes at
        the call site.
        """
        if not ctx.requested_fields:
            ctx = ctx.model_copy(update={"requested_fields": list(record.keys())})

        decisions = self.engine.evaluate(ctx)
        data = enforce(record, decisions)
        event = None
        if audit:
            event = emit(build_event(ctx, decisions, self.policy))
        return MediationResult(data=data, decisions=decisions, audit=event)
