"""
Console entry points.

The proxy and the HTTP service each need an optional dependency. The commands
import their implementation lazily so that a missing extra produces an
instruction rather than a traceback.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable


def _run(module: str, command: str, extra: str) -> None:
    try:
        main: Callable[[], object] = importlib.import_module(module).main
    except ImportError as exc:
        missing = (exc.name or "").split(".")[0]
        if not missing or missing == "moriti":
            raise  # a real bug in moriti itself: show the traceback
        print(
            f"{command} needs a dependency that is not installed: {missing}.\n"
            f"Install it with: pip install 'moriti[{extra}]'",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    raise SystemExit(main())


def proxy() -> None:
    """``moriti-proxy``: the MCP privacy proxy."""
    _run("moriti.mcp.proxy", "moriti-proxy", "mcp")


def serve() -> None:
    """``moriti-serve``: the mediation service for HTTP-only gateways."""
    _run("moriti.http.service", "moriti-serve", "serve")
