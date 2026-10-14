"""
Masking primitives for the moriti runtime.

Every function here is pure and stateless: no vault, no lookup tables, no
persistence. Two properties are load-bearing and must survive any edit:

  * **No value ever reaches a log.** Error paths log nothing, or log only the
    field's presence -- a masking library that logs what it failed to mask has
    exfiltrated the very thing it exists to protect.
  * **Failure closes.** When a value cannot be masked as requested, the caller
    gets the redaction placeholder, never the original.

`pseudonymise` is the stateless stand-in for vault tokenisation: deterministic
(equal inputs give equal tokens, so joins still work) but one-way. A reversible
vault can be plugged into enforcement via `set_tokeniser`.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)
_warned_unkeyed = False

REDACTION_PLACEHOLDER = "[REDACTED BY PRIVACY POLICY]"
APPROVAL_PLACEHOLDER = "[WITHHELD PENDING APPROVAL]"


def pseudonymise(value: Any) -> str:
    """Deterministic token, truncated to the input's length (min 8).

    With ``MORITI_TOKEN_KEY`` set it is HMAC-SHA256 under that key, so a token cannot be
    reversed by hashing guesses without the key. Without a key it is a plain SHA-256: stable,
    but a low-entropy value (an ID number, an account number) can be recovered by trying every
    candidate, so it is a placeholder for development. Register a vault-backed tokeniser, or
    set the key, before relying on tokens to hide such values.
    """
    global _warned_unkeyed
    s = str(value)
    if not s:
        return REDACTION_PLACEHOLDER
    key = os.environ.get("MORITI_TOKEN_KEY", "")
    if key:
        digest = hmac.new(key.encode("utf-8"), s.encode("utf-8"), hashlib.sha256).hexdigest()
    else:
        if not _warned_unkeyed:
            _warned_unkeyed = True
            logger.warning(
                "MORITI_TOKEN_KEY is not set: tokens are unkeyed SHA-256 and low-entropy values can be "
                "recovered by guessing. Set a key, or register a vault-backed tokeniser."
            )
        digest = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return digest[: max(8, min(len(s), len(digest)))]


def mask_value(value: Any) -> str:
    """Generic mask: everything hidden but the last four characters."""
    s = str(value)
    if len(s) <= 4:
        return "X" * len(s)
    return "X" * (len(s) - 4) + s[-4:]


def mask_name(value: Any) -> str:
    """First character survives: 'Sarah' -> 'SXXXX'."""
    s = str(value)
    if not s:
        return REDACTION_PLACEHOLDER
    return s[0] + "X" * (len(s) - 1)


def mask_text(value: Any) -> str:
    return mask_name(value)


def mask_email(value: Any) -> str:
    """Local part masked after its first character; domain kept: 'sXXXX@example.com'."""
    s = str(value)
    if "@" not in s:
        return mask_value(s)
    local, domain = s.split("@", 1)
    if not local:
        return mask_value(s)
    return local[0] + "X" * (len(local) - 1) + "@" + domain


def mask_phone_number(value: Any) -> str:
    """Last four digits survive; a leading +CC country code stays visible."""
    s = str(value)
    if len(s) <= 4:
        return "X" * len(s)
    if s.startswith("+") and len(s) > 7:
        return s[:3] + "X" * (len(s) - 7) + s[-4:]
    return "X" * (len(s) - 4) + s[-4:]


def mask_address(value: Any) -> str:
    """Each comma-separated part keeps its first character."""
    s = str(value)
    if not s:
        return REDACTION_PLACEHOLDER
    parts = [p.strip() for p in s.split(",")]
    return ", ".join(p[0] + "X" * (len(p) - 1) if p else p for p in parts)


def mask_date(value: Any) -> str:
    """Day and month hidden, two-digit year kept: '01/03/1990' -> 'XX/XX/90'."""
    s = str(value)
    for sep in ("/", "-", ".", " "):
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 3:
                masked = [
                    p[-2:] if len(p) == 4 and p.isdigit() else "X" * len(p)
                    for p in parts
                ]
                return sep.join(masked)
    if len(s) == 8 and s.isdigit():
        return "XXXXXX" + s[-2:]
    return "X" * len(s)


def mask_amount(value: Any) -> str:
    """Magnitude hidden entirely -- an amount's length is itself informative."""
    return "[AMOUNT]"


_DISPATCH: list[tuple[tuple[str, ...], Callable[[Any], str]]] = [
    (("email",), mask_email),
    (("phone", "mobile", "cell", "telephone"), mask_phone_number),
    (("name", "surname", "firstname", "lastname"), mask_name),
    (("address", "street", "suburb"), mask_address),
    (("date", "dob", "birth"), mask_date),
    (("salary", "income", "amount", "balance", "price"), mask_amount),
]


def masker_for(field: str) -> Callable[[Any], str]:
    """The most faithful masker for a field, judged by its name."""
    lowered = field.lower()
    for needles, func in _DISPATCH:
        if any(n in lowered for n in needles):
            return func
    return mask_value
