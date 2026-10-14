"""
Audit / evidence events.

This is an evidence layer, and that framing drives the shape: the point is not
debugging output but a record that can answer, after
the fact, *why* an agent was permitted to use particular personal data. So each
event carries the policy name and version, the assigned purpose, and the reason
each decision was reached -- including which guard restricted it.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from moriti.context import RequestContext
from moriti.policy import FieldDecision, Policy

logger = logging.getLogger(__name__)


class AuditEvent(BaseModel):
    event_id: str
    timestamp: str
    agent: str
    principal: str | None = None
    data_subject: str | None = None
    resource: str | None = None
    fields_requested: list[str]
    purpose: str
    tool: str | None = None
    destination: str
    retention: str
    jurisdiction: str | None = None
    legal_basis: str | None = None
    policy: str
    decisions: dict[str, str]
    obligations: dict[str, list[str]] = Field(default_factory=dict)
    reasons: dict[str, str] = Field(default_factory=dict)
    restricted_by: dict[str, list[str]] = Field(default_factory=dict)
    #: The rule that proposed each decision. A field decided by the policy default has no entry.
    matched_rule: dict[str, str] = Field(default_factory=dict)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.model_dump(exclude_none=True), indent=indent)


def build_event(
    ctx: RequestContext,
    decisions: list[FieldDecision],
    policy: Policy,
    timestamp: datetime | None = None,
) -> AuditEvent:
    stamp = (timestamp or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    return AuditEvent(
        event_id=str(uuid.uuid4()),
        timestamp=stamp,
        agent=ctx.agent,
        principal=ctx.principal,
        data_subject=ctx.data_subject,
        resource=ctx.resource,
        fields_requested=list(ctx.requested_fields),
        purpose=ctx.purpose,
        tool=ctx.tool,
        destination=ctx.destination.value,
        retention=ctx.retention.value,
        jurisdiction=ctx.jurisdiction,
        legal_basis=ctx.legal_basis.value if ctx.legal_basis else None,
        policy=f"{policy.name}_v{policy.version}",
        decisions={d.field: d.decision.value for d in decisions},
        obligations={d.field: [o.value for o in d.obligations] for d in decisions if d.obligations},
        reasons={d.field: d.reason for d in decisions},
        restricted_by={d.field: d.restricted_by for d in decisions if d.restricted_by},
        matched_rule={d.field: d.matched_rule for d in decisions if d.matched_rule},
    )


_sink: Callable[[AuditEvent], None] | None = None


def set_sink(sink: Callable[[AuditEvent], None] | None) -> None:
    """Send audit events to `sink` instead of the application log; None restores the log.

        from moriti import audit
        audit.set_sink(siem.send)

    The event never contains a protected value, so a sink may forward it as is. A sink
    that raises does not block the response (the result was already mediated): the
    failure is logged and the event falls back to the log, so it is not lost.
    """
    global _sink
    _sink = sink


def emit(event: AuditEvent) -> AuditEvent:
    """Deliver the event to the registered sink, or write it to the application log.

    Deliberately a single seam: an append-only store or an external SIEM is one
    `set_sink` call away.
    """
    if _sink is not None:
        try:
            _sink(event)
            return event
        except Exception:
            logger.error("Audit sink failed for event %s; writing it to the log instead", event.event_id)
    logger.info("privacy.audit %s", event.to_json(indent=None))
    return event
