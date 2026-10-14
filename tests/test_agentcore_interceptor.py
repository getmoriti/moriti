"""
The AgentCore Gateway response interceptor, driven with the event shapes from
the AgentCore developer guide. Pure dict in, dict out: no AWS account needed.
"""

from __future__ import annotations

import base64
import json

import pytest

from moriti.adapters.agentcore import ResponseInterceptor, handler, make_handler
from moriti.adapters.common import DeploymentConfig

SARAH = {
    "name": "Sarah Ndlovu",
    "email": "sarah.ndlovu@example.co.za",
    "department": "Engineering",
    "job_title": "Staff Engineer",
    "employee_id": "EMP-4831",
    "salary": 1450000.0,
    "bank_account": "10000007792",
    "tax_number": "0100007263",
}


def tools_call_event(result: dict, *, tool: str = "get_employee", arguments: dict | None = None, streaming: bool = False) -> dict:
    return {
        "interceptorInputVersion": "1.0",
        "mcp": {
            "rawGatewayRequest": {"body": "<raw>"},
            "gatewayRequest": {
                "path": "/mcp", "httpMethod": "POST",
                "body": {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                         "params": {"name": tool, "arguments": arguments or {"name": "sarah"}}},
            },
            "gatewayResponse": {
                "statusCode": 200, "headers": {"Mcp-Session-Id": "s-1"}, "isStreamingResponse": streaming,
                "body": {"jsonrpc": "2.0", "id": 7, "result": result},
            },
        },
    }


def text_result(record: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(record)}]}


def first_text(out: dict) -> dict:
    return json.loads(out["mcp"]["transformedGatewayResponse"]["body"]["result"]["content"][0]["text"])


def test_directory_deployment_withholds_salary_from_a_tools_call_result():
    interceptor = make_handler(DeploymentConfig.from_yaml("deployments/hr_assistant.yaml"))
    out = interceptor(tools_call_event(text_result(SARAH)), None)
    assert out["interceptorOutputVersion"] == "1.0"
    assert out["mcp"]["transformedGatewayResponse"]["statusCode"] == 200
    assert out["mcp"]["transformedGatewayResponse"]["body"]["id"] == 7  # JSON-RPC envelope preserved
    data = first_text(out)
    assert data["name"] == "Sarah Ndlovu" and data["email"] == "sarah.ndlovu@example.co.za"
    for field in ("salary", "bank_account", "tax_number", "employee_id"):
        assert field not in data


def test_payroll_deployment_releases_salary_for_the_same_call():
    interceptor = make_handler(DeploymentConfig.from_yaml("deployments/payroll_agent.yaml"))
    data = first_text(interceptor(tools_call_event(text_result(SARAH))))
    assert data["salary"] == 1450000.0 and data["bank_account"] == "10000007792"
    assert "email" not in data


def test_structured_content_is_mediated_too():
    interceptor = make_handler(DeploymentConfig.from_yaml("deployments/hr_assistant.yaml"))
    result = {**text_result(SARAH), "structuredContent": dict(SARAH)}
    body = interceptor(tools_call_event(result))["mcp"]["transformedGatewayResponse"]["body"]
    assert "salary" not in body["result"]["structuredContent"]
    assert body["result"]["structuredContent"]["name"] == "Sarah Ndlovu"


def test_other_methods_pass_through_untouched():
    interceptor = make_handler(DeploymentConfig.from_yaml("deployments/hr_assistant.yaml"))
    event = tools_call_event({"tools": [{"name": "get_employee"}]})
    event["mcp"]["gatewayRequest"]["body"] = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    out = interceptor(event)
    assert out["mcp"]["transformedGatewayResponse"]["body"] == event["mcp"]["gatewayResponse"]["body"]


def test_elicitation_request_from_the_target_passes_through():
    interceptor = make_handler(DeploymentConfig.from_yaml("deployments/hr_assistant.yaml"))
    event = tools_call_event({}, streaming=True)
    event["mcp"]["gatewayResponse"]["body"] = {"jsonrpc": "2.0", "id": "elicit-1", "method": "elicitation/create",
                                              "params": {"message": "Confirm?", "requestedSchema": {}}}
    out = interceptor(event)
    assert out["mcp"]["transformedGatewayResponse"]["body"]["method"] == "elicitation/create"


def test_free_text_tool_output_is_withheld():
    interceptor = make_handler(DeploymentConfig.from_yaml("deployments/hr_assistant.yaml"))
    out = interceptor(tools_call_event({"content": [{"type": "text", "text": "Sarah earns 1450000 a year"}]}))
    assert first_text(out)["moriti"].startswith("unstructured tool output withheld")


def test_non_text_blocks_are_dropped():
    interceptor = make_handler(DeploymentConfig.from_yaml("deployments/hr_assistant.yaml"))
    result = {"content": [{"type": "image", "data": "...", "mimeType": "image/png"}, {"type": "text", "text": json.dumps(SARAH)}]}
    content = interceptor(tools_call_event(result))["mcp"]["transformedGatewayResponse"]["body"]["result"]["content"]
    assert [b["type"] for b in content] == ["text"]


def test_mediation_failure_fails_closed(monkeypatch):
    interceptor = make_handler(DeploymentConfig.from_yaml("deployments/hr_assistant.yaml"))
    monkeypatch.setattr(interceptor.plane, "mediate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    result = interceptor(tools_call_event(text_result(SARAH)))["mcp"]["transformedGatewayResponse"]["body"]["result"]
    assert result["isError"] is True
    assert json.loads(result["content"][0]["text"]) == {"moriti": "refused", "reason": "Privacy mediation failed; response withheld"}


def test_http_target_json_body_is_mediated():
    interceptor = make_handler(DeploymentConfig.from_yaml("deployments/hr_assistant.yaml"))
    event = {"interceptorInputVersion": "1.0",
             "http": {"gatewayRequest": None,
                      "gatewayResponse": {"statusCode": 200, "headers": None, "contentType": "application/json",
                                          "body": base64.b64encode(json.dumps(SARAH).encode()).decode()}}}
    out = interceptor(event)["http"]["transformedGatewayResponse"]
    data = json.loads(base64.b64decode(out["body"]))
    assert data["name"] == "Sarah Ndlovu" and "salary" not in data
    assert out["contentType"] == "application/json"


def test_http_target_non_json_body_is_withheld():
    interceptor = make_handler(DeploymentConfig.from_yaml("deployments/hr_assistant.yaml"))
    event = {"interceptorInputVersion": "1.0",
             "http": {"gatewayResponse": {"statusCode": 200, "body": base64.b64encode(b"\x89PNG...").decode(), "contentType": "image/png"}}}
    out = interceptor(event)["http"]["transformedGatewayResponse"]
    assert json.loads(base64.b64decode(out["body"]))["moriti"].startswith("unstructured")


def test_module_handler_configures_itself_from_the_environment(monkeypatch):
    import moriti.adapters.agentcore.interceptor as mod
    monkeypatch.setattr(mod, "_default", None)
    monkeypatch.setenv("MORITI_DEPLOYMENT", "deployments/hr_assistant.yaml")
    data = first_text(handler(tools_call_event(text_result(SARAH)), None))
    assert "salary" not in data
    monkeypatch.setattr(mod, "_default", None)
    monkeypatch.delenv("MORITI_DEPLOYMENT")
    monkeypatch.delenv("MORITI_DEPLOYMENT_JSON", raising=False)
    with pytest.raises(RuntimeError):
        handler(tools_call_event(text_result(SARAH)), None)


def test_interceptor_is_a_plain_callable_for_wrapping():
    assert isinstance(make_handler({"agent": "a", "purpose": "employee_directory_lookup", "policy": "popia_hr_v1"}), ResponseInterceptor)
