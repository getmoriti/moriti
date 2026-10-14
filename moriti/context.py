"""
The request context the privacy control plane reasons over.

Traditional IAM evaluates (subject, resource, action). Purpose limitation cannot
be expressed in that triple: the same subject reading the same field is lawful
for one purpose and unlawful for another. This model carries the extra axes the
decision actually depends on -- purpose, data subject, destination, legal basis,
consent and retention -- so a policy can distinguish those two cases.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Destination(str, Enum):
    """Where the data is headed once released. Drives residency and external-transfer rules."""

    INTERNAL_SYSTEM = "internal_system"
    INTERNAL_MODEL = "internal_model"
    EXTERNAL_MODEL = "external_model"
    THIRD_PARTY_API = "third_party_api"
    AGENT_MEMORY = "agent_memory"
    ANOTHER_AGENT = "another_agent"
    HUMAN_UI = "human_ui"

    @property
    def is_external(self) -> bool:
        return self in {Destination.EXTERNAL_MODEL, Destination.THIRD_PARTY_API}


class Retention(str, Enum):
    """How long the caller intends to hold the data."""

    EPHEMERAL = "ephemeral"          # this turn only
    SESSION = "session"              # duration of the conversation
    LONG_TERM_MEMORY = "long_term_memory"
    PERSISTENT = "persistent"        # written to a database


class LegalBasis(str, Enum):
    """POPIA / GDPR style grounds for processing."""

    CONSENT = "consent"
    CONTRACT = "contract"
    LEGAL_OBLIGATION = "legal_obligation"
    LEGITIMATE_INTEREST = "legitimate_interest"
    VITAL_INTEREST = "vital_interest"
    PUBLIC_INTEREST = "public_interest"


class RequestContext(BaseModel):
    """A single evaluated data access."""

    # WHO
    agent: str = Field(..., description="Identity of the calling agent, e.g. 'hr_assistant'")
    principal: str | None = Field(None, description="Human on whose behalf the agent acts")
    principal_role: str | None = Field(None, description="That human's role, e.g. 'hr_admin'")

    # WHAT
    data_subject: str | None = Field(None, description="Whose personal data this is")
    resource: str | None = Field(None, description="Logical record, e.g. 'employee_profile'")
    requested_fields: list[str] = Field(default_factory=list)

    # WHY
    purpose: str = Field(..., description="Assigned purpose, e.g. 'employee_directory_lookup'")
    task: str | None = None

    # HOW
    tool: str | None = Field(None, description="Tool or MCP method being invoked")

    # WHERE
    destination: Destination = Destination.INTERNAL_SYSTEM
    jurisdiction: str | None = Field(None, description="ISO country code, e.g. 'ZA'")

    # FOR HOW LONG
    retention: Retention = Retention.EPHEMERAL

    # LEGAL / POLICY CONTEXT
    legal_basis: LegalBasis | None = None
    consent_scopes: list[str] = Field(
        default_factory=list,
        description="Purposes the data subject actually consented to",
    )

    def consent_covers(self, purpose: str) -> bool:
        """True if the assigned purpose falls inside the data subject's consent."""
        return purpose in self.consent_scopes
