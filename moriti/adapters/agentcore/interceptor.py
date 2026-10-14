"""
moriti as an Amazon Bedrock AgentCore Gateway *response interceptor*.

How it fits AgentCore
---------------------
AgentCore Gateway lets a Lambda function run after a target responds and
before the gateway returns the response to the agent. The gateway hands the
function an event carrying the original request and the target's response,
and uses whatever ``transformedGatewayResponse`` the function returns. That
is the response-path interception point. AgentCore's own controls decide
*who may call which tool* (Cedar policy) and *which value types look
sensitive* (Guardrails); this interceptor decides, per field, whether the
data should be used for the deployment's purpose.

Event shapes (from the AgentCore developer guide)
-------------------------------------------------
MCP targets::

    {"interceptorInputVersion": "1.0",
     "mcp": {"gatewayRequest":  {"body": {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                          "params": {"name": "get_employee", "arguments": {...}}}},
             "gatewayResponse": {"statusCode": 200, "isStreamingResponse": false,
                                 "body": {"jsonrpc": "2.0", "id": 1,
                                          "result": {"content": [{"type": "text", "text": "..."}]}}}}}

    -> {"interceptorOutputVersion": "1.0",
        "mcp": {"transformedGatewayResponse": {"statusCode": 200, "body": <rewritten JSON-RPC message>}}}

HTTP targets carry ``event["http"]["gatewayResponse"]`` with a base64 body.
JSON bodies are mediated as data; anything else is withheld.

Where purpose comes from
------------------------
The deployment config, loaded once at cold start from ``MORITI_DEPLOYMENT``
(a YAML file bundled with the function) or ``MORITI_DEPLOYMENT_JSON``. One
interceptor per deployment. Nothing in the event can change it.

Failure posture
---------------
Closed. Only ``tools/call`` results and JSON HTTP bodies are rewritten;
other MCP messages (``tools/list``, ``initialize``, elicitation requests)
carry no tool data and pass through unchanged. If mediation raises, the
agent receives a refusal, never the unmediated result.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from moriti import PrivacyPlane
from moriti.adapters.common import (
    WITHHELD_UNSTRUCTURED,
    DeploymentConfig,
    infer_subject,
    mediate_text,
    mediate_value,
)

logger = logging.getLogger("moriti.agentcore")

OUTPUT_VERSION = "1.0"


def _refusal(reason: str) -> dict[str, Any]:
    return {"moriti": "refused", "reason": reason}


class ResponseInterceptor:
    """Rewrites gateway responses under a deployment-bound privacy policy."""

    def __init__(self, deployment: DeploymentConfig | dict[str, Any]) -> None:
        self.deployment = (
            deployment if isinstance(deployment, DeploymentConfig) else DeploymentConfig(**deployment)
        )
        self.plane = PrivacyPlane.from_policy(self.deployment.policy)
        logger.info(
            "moriti AgentCore interceptor up: agent=%s purpose=%s policy=%s",
            self.deployment.agent, self.deployment.purpose, self.plane.policy.name,
        )

    @classmethod
    def from_environment(cls) -> ResponseInterceptor:
        """Cold-start configuration: MORITI_DEPLOYMENT (YAML path) or MORITI_DEPLOYMENT_JSON."""
        path = os.environ.get("MORITI_DEPLOYMENT")
        if path:
            return cls(DeploymentConfig.from_yaml(path))
        raw = os.environ.get("MORITI_DEPLOYMENT_JSON")
        if raw:
            return cls(DeploymentConfig(**json.loads(raw)))
        raise RuntimeError("set MORITI_DEPLOYMENT (YAML path) or MORITI_DEPLOYMENT_JSON for the interceptor")

    # -- Lambda entry ---------------------------------------------------------------

    def __call__(self, event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
        if "mcp" in event:
            return {"interceptorOutputVersion": OUTPUT_VERSION,
                    "mcp": {"transformedGatewayResponse": self._mcp(event["mcp"])}}
        if "http" in event:
            return {"interceptorOutputVersion": OUTPUT_VERSION,
                    "http": {"transformedGatewayResponse": self._http(event["http"])}}
        logger.warning("Unrecognised interceptor event shape; withholding")
        return {"interceptorOutputVersion": OUTPUT_VERSION,
                "mcp": {"transformedGatewayResponse": {"statusCode": 200, "body": _refusal("unrecognised event shape")}}}

    # -- MCP targets ----------------------------------------------------------------

    def _mcp(self, mcp: dict[str, Any]) -> dict[str, Any]:
        response = mcp.get("gatewayResponse") or {}
        request_body = (mcp.get("gatewayRequest") or {}).get("body") or {}
        body = response.get("body")
        out = {"statusCode": response.get("statusCode", 200), "body": body}

        # Only a tools/call *result* carries tool data. Requests the target sends
        # back (elicitation), errors, and every other method pass through.
        if request_body.get("method") != "tools/call" or not isinstance(body, dict) or "result" not in body:
            return out

        params = request_body.get("params") or {}
        tool = str(params.get("name", ""))
        arguments = params.get("arguments") or {}
        ctx = self.deployment.context(tool, data_subject=infer_subject(arguments if isinstance(arguments, dict) else {}))
        withheld: list[str] = []
        try:
            result = self._mediate_call_result(body["result"], ctx, withheld)
        except Exception:
            logger.exception("Mediation failed for %r; failing closed", tool)
            result = {"content": [{"type": "text", "text": json.dumps(_refusal("Privacy mediation failed; response withheld"))}],
                      "isError": True}
        logger.info("mediated %s for agent=%s purpose=%s: withheld=%s",
                    tool, self.deployment.agent, self.deployment.purpose, sorted(set(withheld)))
        out["body"] = {**body, "result": result}
        return out

    def _mediate_call_result(self, result: Any, ctx, withheld: list[str]) -> Any:
        if not isinstance(result, dict):
            return result
        out = dict(result)
        if isinstance(result.get("content"), list):
            content = []
            for block in result["content"]:
                if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                    content.append({**block, "text": mediate_text(self.plane, block["text"], ctx, withheld)})
                else:
                    # Images, audio, embedded resources: nothing this interceptor can field-mediate.
                    logger.warning("Dropping non-text content block of type %r", block.get("type") if isinstance(block, dict) else type(block).__name__)
            out["content"] = content
        for key in ("structuredContent", "structured_content"):
            if isinstance(result.get(key), (dict, list)):
                out[key] = mediate_value(self.plane, result[key], ctx, withheld)
        return out

    # -- HTTP targets ---------------------------------------------------------------

    def _http(self, http: dict[str, Any]) -> dict[str, Any]:
        response = http.get("gatewayResponse") or {}
        out = {k: v for k, v in response.items() if k in ("statusCode", "headers", "contentType")}
        raw = response.get("body")
        ctx = self.deployment.context("http", data_subject=None)
        withheld: list[str] = []
        try:
            decoded = base64.b64decode(raw).decode("utf-8") if isinstance(raw, str) else None
            value = json.loads(decoded) if decoded is not None else None
        except (ValueError, UnicodeDecodeError):
            value = None
        if value is None:
            logger.warning("Non-JSON HTTP body withheld")
            rewritten = json.dumps(WITHHELD_UNSTRUCTURED)
        else:
            try:
                rewritten = json.dumps(mediate_value(self.plane, value, ctx, withheld))
            except Exception:
                logger.exception("Mediation failed for HTTP body; failing closed")
                rewritten = json.dumps(_refusal("Privacy mediation failed; response withheld"))
        out["body"] = base64.b64encode(rewritten.encode("utf-8")).decode("ascii")
        out.setdefault("contentType", "application/json")
        return out


def make_handler(deployment: DeploymentConfig | dict[str, Any]):
    """Build a Lambda handler bound to one deployment (for tests and for wrapping)."""
    return ResponseInterceptor(deployment)


_default: ResponseInterceptor | None = None


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """The Lambda entry point: ``moriti.adapters.agentcore.handler``. Configured from the environment."""
    global _default
    if _default is None:
        _default = ResponseInterceptor.from_environment()
    return _default(event, context)
