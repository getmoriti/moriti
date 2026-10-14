"""
Applies control-plane decisions to real values.

The policy engine says *what* should happen to each field; this module carries
it out with the stateless primitives in `moriti.masking`. Everything fails
closed: an enforcement error yields the redaction placeholder, never the value,
and nothing here ever logs a value (see masking.py for why that is absolute).

Tokenisation is pluggable. The default is deterministic one-way
pseudonymisation, which needs no infrastructure; an organisation with a real
vault registers it once:

    from moriti import enforcement
    enforcement.set_tokeniser(vault.tokenise, vault.detokenise)

DETOKENISE decisions are refused (redacted) until a reversible tokeniser is
registered -- an open-source runtime must not pretend it can reverse a hash.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from moriti.decisions import Decision
from moriti.masking import (
    APPROVAL_PLACEHOLDER,
    REDACTION_PLACEHOLDER,
    masker_for,
    pseudonymise,
)
from moriti.policy import FieldDecision

logger = logging.getLogger(__name__)

_tokenise: Callable[[Any], str] = pseudonymise
_detokenise: Callable[[Any], str] | None = None


def set_tokeniser(
    tokenise: Callable[[Any], str],
    detokenise: Callable[[Any], str] | None = None,
) -> None:
    """Replace the default one-way pseudonymiser with a vault's functions."""
    global _tokenise, _detokenise
    _tokenise = tokenise
    _detokenise = detokenise


def _apply_one(field: str, value: Any, decision: Decision) -> tuple[bool, Any]:
    """Returns (include_in_output, value). DENY and FILTER drop the key entirely."""
    if decision is Decision.ALLOW:
        return True, value
    if decision in (Decision.DENY, Decision.FILTER):
        return False, None
    if decision is Decision.REDACT:
        return True, REDACTION_PLACEHOLDER
    if decision is Decision.REQUIRE_APPROVAL:
        return True, APPROVAL_PLACEHOLDER

    try:
        if decision is Decision.MASK:
            return True, masker_for(field)(value)
        if decision is Decision.TOKENISE:
            return True, _tokenise(value)
        if decision is Decision.DETOKENISE:
            if _detokenise is None:
                logger.warning(
                    "DETOKENISE on %r refused: no reversible tokeniser registered", field
                )
                return True, REDACTION_PLACEHOLDER
            return True, _detokenise(value)
    except Exception:
        logger.error("Enforcement of %s on %r failed; redacting", decision.value, field)
        return True, REDACTION_PLACEHOLDER

    return True, REDACTION_PLACEHOLDER


def enforce(record: dict[str, Any], decisions: list[FieldDecision]) -> dict[str, Any]:
    """Produce the record the agent is actually allowed to receive.

    Denied fields are omitted rather than nulled -- a null still discloses that
    the field exists and was withheld, which for some fields is itself a leak.
    Redaction is for when the caller must *see* that something was withheld.
    """
    output: dict[str, Any] = {}
    for fd in decisions:
        if fd.field not in record:
            continue
        include, value = _apply_one(fd.field, record[fd.field], fd.decision)
        if include:
            output[fd.field] = value
    return output
