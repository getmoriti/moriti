"""The mediation service: ``mediate()`` behind a small HTTP API, for gateways that can only call HTTP."""

from moriti.http.service import build_app, main

__all__ = ["build_app", "main"]
