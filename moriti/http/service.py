"""
The mediation service.

Some gateways cannot run Python in the data path: Azure API Management, Kong,
Cloudflare, an Envoy filter. They can call HTTP. This service puts
``PrivacyPlane.mediate()`` behind one endpoint so such a gateway can hand it a
tool result and substitute what comes back.

    moriti-serve deployments/hr_assistant.yaml deployments/payroll_agent.yaml --http 127.0.0.1:8770

    POST /mediate/<deployment>        {"tool": "get_employee", "arguments": {...}, "result": <any JSON>}
                                   -> {"result": <rewritten>, "withheld": [...], "agent": ..., "purpose": ..., "policy": ...}
    POST /mediate                     the same, when exactly one deployment is loaded
    GET  /deployments                 what is loaded, and the purpose bound to each
    GET  /healthz

One deployment per policy boundary, named by its file. Purpose is bound in
the file; nothing in a request can change it. The service holds no data and
keeps no state: it is safe to run several behind a load balancer.

Failure posture
---------------
Closed, and gateway-friendly: a mediation error returns HTTP 200 with a
refusal in ``result`` and ``"error": "mediation_failed"``, because a 5xx
tempts a gateway policy into passing the original response through. Malformed
requests are 400; an unknown deployment is 404.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from moriti import PrivacyPlane
from moriti._config import warn_if_exposed
from moriti.adapters.common import DeploymentConfig, infer_subject, mediate_text, mediate_value

logger = logging.getLogger("moriti.http")


def _refusal(reason: str) -> dict[str, Any]:
    return {"moriti": "refused", "reason": reason}


class Mediator:
    """One loaded deployment: its config and its policy."""

    def __init__(self, name: str, deployment: DeploymentConfig) -> None:
        self.name = name
        self.deployment = deployment
        self.plane = PrivacyPlane.from_policy(deployment.policy)

    @property
    def policy_id(self) -> str:
        return f"{self.plane.policy.name}_v{self.plane.policy.version}"

    def mediate(self, tool: str, arguments: dict[str, Any], result: Any) -> dict[str, Any]:
        ctx = self.deployment.context(tool, data_subject=infer_subject(arguments))
        withheld: list[str] = []
        try:
            if isinstance(result, (dict, list)):
                rewritten = mediate_value(self.plane, result, ctx, withheld)
            elif isinstance(result, str):
                rewritten = mediate_text(self.plane, result, ctx, withheld)
            else:
                rewritten = result  # scalars carry nothing personal
        except Exception:
            logger.exception("Mediation failed for %r in %r; failing closed", tool, self.name)
            return {"result": _refusal("Privacy mediation failed; response withheld"), "withheld": [],
                    "error": "mediation_failed", **self._who()}
        logger.info("mediated %s via %s: withheld=%s", tool, self.name, sorted(set(withheld)))
        return {"result": rewritten, "withheld": sorted(set(withheld)), **self._who()}

    def _who(self) -> dict[str, Any]:
        return {"deployment": self.name, "agent": self.deployment.agent,
                "purpose": self.deployment.purpose, "policy": self.policy_id}


def build_app(deployments: dict[str, DeploymentConfig]) -> Starlette:
    if not deployments:
        raise ValueError("at least one deployment is required")
    mediators = {name: Mediator(name, cfg) for name, cfg in deployments.items()}

    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "deployments": sorted(mediators)})

    async def list_deployments(_request: Request) -> JSONResponse:
        return JSONResponse({"deployments": [m._who() for m in mediators.values()]})

    async def mediate(request: Request) -> JSONResponse:
        name = request.path_params.get("name")
        if name is None:
            if len(mediators) != 1:
                return JSONResponse({"error": "several deployments are loaded; POST /mediate/<deployment>",
                                     "deployments": sorted(mediators)}, status_code=400)
            name = next(iter(mediators))
        mediator = mediators.get(name)
        if mediator is None:
            return JSONResponse({"error": f"unknown deployment {name!r}", "deployments": sorted(mediators)}, status_code=404)
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse({"error": "body must be JSON"}, status_code=400)
        if not isinstance(body, dict) or "result" not in body:
            return JSONResponse({"error": 'body must be an object with "tool", "arguments" and "result"'}, status_code=400)
        tool = str(body.get("tool") or "unknown")
        arguments = body.get("arguments") if isinstance(body.get("arguments"), dict) else {}
        return JSONResponse(mediator.mediate(tool, arguments, body["result"]))

    return Starlette(routes=[
        Route("/healthz", healthz),
        Route("/deployments", list_deployments),
        Route("/mediate", mediate, methods=["POST"]),
        Route("/mediate/{name}", mediate, methods=["POST"]),
    ])


def load_deployments(paths: list[str]) -> dict[str, DeploymentConfig]:
    """Each file becomes one deployment, named by its stem."""
    out: dict[str, DeploymentConfig] = {}
    for raw in paths:
        path = Path(raw)
        if path.stem in out:
            raise SystemExit(f"two deployments named {path.stem!r}; rename one file")
        out[path.stem] = DeploymentConfig.from_yaml(path)
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="moriti-serve", description="mediate() behind HTTP, for gateways that can only call HTTP.")
    parser.add_argument("deployments", nargs="+", help="deployment YAML files; each is served as /mediate/<file stem>")
    parser.add_argument("--http", metavar="HOST:PORT", default="127.0.0.1:8770")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")

    import uvicorn

    host, _, port = args.http.rpartition(":")
    warn_if_exposed(host, "moriti mediation service", logger)
    app = build_app(load_deployments(args.deployments))
    logger.info("moriti mediation service listening on http://%s:%s (deployments: %s)", host, port, ", ".join(Path(p).stem for p in args.deployments))
    uvicorn.run(app, host=host, port=int(port), log_level="warning")
