"""
Small guards shared by the configuration models.

A privacy runtime that quietly ignores a misspelt key quietly drops the
protection that key stood for: ``allowed_tool`` instead of ``allowed_tools``
would leave every tool reachable. Unknown keys are therefore an error.
"""

from __future__ import annotations

import difflib
import ipaddress
import logging
from collections.abc import Iterable
from typing import Any


def reject_unknown_keys(data: Any, allowed: Iterable[str], where: str) -> Any:
    """Raise ``ValueError`` naming each unknown key, with a spelling hint when there is a near match."""
    if not isinstance(data, dict):
        return data
    known = sorted(allowed)
    unknown = sorted(set(data) - set(known))
    if not unknown:
        return data
    parts = []
    for key in unknown:
        near = difflib.get_close_matches(str(key), known, n=1)
        parts.append(f"{key!r}" + (f" (did you mean {near[0]!r}?)" if near else ""))
    raise ValueError(
        f"{where}: unknown key {', '.join(parts)}. "
        "A misspelt key would silently drop a protection, so it is refused."
    )


def warn_if_exposed(host: str, component: str, logger: logging.Logger) -> None:
    """The HTTP fronts have no authentication of their own. Say so when they are not on loopback."""
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        logger.warning(
            "%s is listening on %s and has no authentication of its own. Anything that can reach this "
            "address can call it. Keep it on loopback or a private network, or put it behind a gateway "
            "that authenticates callers.",
            component, host,
        )
