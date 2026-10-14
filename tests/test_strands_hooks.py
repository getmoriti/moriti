"""
The Strands Agents adapter, driven through a real HookRegistry with the events
Strands fires around a tool call.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("strands")

from strands.hooks import HookRegistry
from strands.hooks.events import AfterToolCallEvent, BeforeToolCallEvent

from moriti.adapters.strands import MoritiHooks

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
AGENT = SimpleNamespace(name="demo")


def registry_for(deployment: str) -> HookRegistry:
    registry = HookRegistry()
    registry.add_hook(MoritiHooks.from_yaml(f"deployments/{deployment}.yaml"))
    return registry


def after_event(result_content: list[dict], *, tool: str = "get_employee", arguments: dict | None = None) -> AfterToolCallEvent:
    return AfterToolCallEvent(
        agent=AGENT, selected_tool=None,
        tool_use={"toolUseId": "t-1", "name": tool, "input": arguments or {"name": "sarah"}},
        invocation_state={},
        result={"toolUseId": "t-1", "status": "success", "content": result_content},
    )


def test_directory_agent_never_receives_salary_from_a_json_block():
    event, _ = registry_for("hr_assistant").invoke_callbacks(after_event([{"json": dict(SARAH)}]))
    data = event.result["content"][0]["json"]
    assert data["name"] == "Sarah Ndlovu" and data["email"] == "sarah.ndlovu@example.co.za"
    for field in ("salary", "bank_account", "tax_number", "employee_id"):
        assert field not in data
    assert event.result["status"] == "success"


def test_payroll_agent_same_tool_receives_salary():
    event, _ = registry_for("payroll_agent").invoke_callbacks(after_event([{"json": dict(SARAH)}]))
    data = event.result["content"][0]["json"]
    assert data["salary"] == 1450000.0 and "email" not in data


def test_text_blocks_carrying_json_are_mediated():
    event, _ = registry_for("hr_assistant").invoke_callbacks(after_event([{"text": json.dumps(SARAH)}]))
    data = json.loads(event.result["content"][0]["text"])
    assert "salary" not in data and data["name"] == "Sarah Ndlovu"


def test_free_text_is_withheld_and_images_are_dropped():
    blocks = [{"text": "Sarah earns 1450000"}, {"image": {"format": "png", "source": {"bytes": b"..."}}}]
    event, _ = registry_for("hr_assistant").invoke_callbacks(after_event(blocks))
    assert len(event.result["content"]) == 1
    assert json.loads(event.result["content"][0]["text"])["moriti"].startswith("unstructured")


def test_disallowed_tool_is_cancelled_before_it_runs():
    registry = registry_for("payroll_agent")  # allowlist: get_employee only
    refused = BeforeToolCallEvent(agent=AGENT, selected_tool=None,
                                  tool_use={"toolUseId": "t-2", "name": "list_employees", "input": {}}, invocation_state={})
    event, _ = registry.invoke_callbacks(refused)
    assert event.cancel_tool == "Tool 'list_employees' is not permitted for agent 'payroll_agent'"
    allowed = BeforeToolCallEvent(agent=AGENT, selected_tool=None,
                                  tool_use={"toolUseId": "t-3", "name": "get_employee", "input": {}}, invocation_state={})
    event, _ = registry.invoke_callbacks(allowed)
    assert event.cancel_tool is False


def test_purpose_cannot_be_smuggled_through_tool_input():
    event, _ = registry_for("hr_assistant").invoke_callbacks(
        after_event([{"json": dict(SARAH)}], arguments={"name": "sarah", "purpose": "monthly_payroll_processing"})
    )
    assert "salary" not in event.result["content"][0]["json"]


def test_mediation_failure_fails_closed(monkeypatch):
    hooks = MoritiHooks.from_yaml("deployments/hr_assistant.yaml")
    monkeypatch.setattr(hooks.plane, "mediate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    registry = HookRegistry()
    registry.add_hook(hooks)
    event, _ = registry.invoke_callbacks(after_event([{"json": dict(SARAH)}]))
    assert event.result["status"] == "error"
    assert json.loads(event.result["content"][0]["text"]) == {"moriti": "refused", "reason": "Privacy mediation failed; response withheld"}
