"""
Enforcement decisions and obligations for the moriti privacy control plane.

A single flat decision vocabulary would mix two different kinds of thing:

  - what happens to the *value right now*   (allow, deny, mask, tokenise, ...)
  - what the caller must *do afterwards*    (don't store it, delete after task,
                                             don't send it externally, ...)

Conflating them makes policy unexpressible: "allow the bank account, but never
let it reach an external model and drop it when the task ends" is one access
decision plus two obligations. So Decision and Obligation are separate here,
and a composite verb such as "allow ephemerally" decomposes into a pair.
"""

from __future__ import annotations

from enum import Enum


class Decision(str, Enum):
    """What the control plane does to a field's value in this response."""

    ALLOW = "allow"
    DENY = "deny"
    MASK = "mask"
    REDACT = "redact"
    TOKENISE = "tokenise"
    DETOKENISE = "detokenise"
    FILTER = "filter"
    REQUIRE_APPROVAL = "require_approval"

    @property
    def releases_value(self) -> bool:
        """True if the caller ends up with usable data for this field."""
        return self in {Decision.ALLOW, Decision.DETOKENISE, Decision.TOKENISE}


class Obligation(str, Enum):
    """Constraints that travel with a released value."""

    DO_NOT_STORE = "do_not_store"
    DO_NOT_SEND_EXTERNALLY = "do_not_send_externally"
    DELETE_AFTER_TASK = "delete_after_task"
    EPHEMERAL_ONLY = "ephemeral_only"
    NO_LONG_TERM_MEMORY = "no_long_term_memory"
    LOG = "log"


#: Composite shorthand verbs, expressed as (Decision, [Obligation]).
COMPOSITE_DECISIONS = {
    "allow_ephemerally": (Decision.ALLOW, [Obligation.EPHEMERAL_ONLY,
                                           Obligation.NO_LONG_TERM_MEMORY]),
    "log_and_allow": (Decision.ALLOW, [Obligation.LOG]),
    "log_and_block": (Decision.DENY, [Obligation.LOG]),
    "do_not_store": (Decision.ALLOW, [Obligation.DO_NOT_STORE]),
    "do_not_send_externally": (Decision.ALLOW, [Obligation.DO_NOT_SEND_EXTERNALLY]),
    "delete_after_task": (Decision.ALLOW, [Obligation.DELETE_AFTER_TASK]),
}


def parse_decision(raw: str) -> tuple[Decision, list[Obligation]]:
    """Resolve a policy's decision string into a decision plus obligations."""
    key = raw.strip().lower()
    if key in COMPOSITE_DECISIONS:
        decision, obligations = COMPOSITE_DECISIONS[key]
        return decision, list(obligations)
    return Decision(key), []
