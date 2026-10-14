"""
The Google ADK adapter, driven directly through the plugin's two callbacks.

ADK's contract is simple: a dict returned from ``before_tool_callback`` replaces
the tool call, a dict returned from ``after_tool_callback`` replaces the result.
These tests exercise that contract with the shipped deployment files.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("google.adk")

from google.adk.tools.base_tool import BaseTool

from moriti.adapters.adk import MoritiPlugin
from moriti.adapters.common import DeploymentConfig

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


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


class _Tool(BaseTool):
    async def run_async(self, *, args, tool_context):  # pragma: no cover - never invoked here
        return {}


def tool(name: str = "get_employee") -> BaseTool:
    return _Tool(name=name, description="Look up an employee record by first name.")


def context(user: str | None = "employee_titus"):
    return SimpleNamespace(agent_name="hr_assistant", session=SimpleNamespace(user_id=user), state={})


async def test_directory_agent_never_receives_salary():
    plugin = MoritiPlugin.from_yaml("deployments/hr_assistant.yaml")
    out = await plugin.after_tool_callback(
        tool=tool(), tool_args={"name": "sarah"}, tool_context=context(), result=dict(SARAH)
    )
    assert out["name"] == "Sarah Ndlovu"
    assert out["email"] == "sarah.ndlovu@example.co.za"
    for field in ("salary", "bank_account", "tax_number", "employee_id"):
        assert field not in out


async def test_payroll_agent_same_tool_receives_salary():
    plugin = MoritiPlugin.from_yaml("deployments/payroll_agent.yaml")
    out = await plugin.after_tool_callback(
        tool=tool(), tool_args={"name": "sarah"}, tool_context=context("hr_admin_lerato"), result=dict(SARAH)
    )
    assert out["salary"] == 1450000.0
    assert out["bank_account"] == "10000007792"
    assert "email" not in out  # not necessary for payroll


async def test_purpose_cannot_be_smuggled_through_tool_args():
    plugin = MoritiPlugin.from_yaml("deployments/hr_assistant.yaml")
    out = await plugin.after_tool_callback(
        tool=tool(),
        tool_args={"name": "sarah", "purpose": "monthly_payroll_processing"},
        tool_context=context(),
        result=dict(SARAH),
    )
    assert "salary" not in out


async def test_disallowed_tool_is_refused_before_it_runs():
    plugin = MoritiPlugin.from_yaml("deployments/hr_assistant.yaml")  # allowlist: get_employee, list_employees
    refused = await plugin.before_tool_callback(tool=tool("delete_employee"), tool_args={}, tool_context=context())
    assert refused == {"moriti": "refused", "reason": "Tool 'delete_employee' is not permitted for agent 'hr_assistant'"}
    allowed = await plugin.before_tool_callback(tool=tool("get_employee"), tool_args={}, tool_context=context())
    assert allowed is None


async def test_lists_of_records_are_mediated_element_wise():
    plugin = MoritiPlugin.from_yaml("deployments/hr_assistant.yaml")
    out = await plugin.after_tool_callback(
        tool=tool("list_employees"), tool_args={}, tool_context=context(), result={"employees": [dict(SARAH)]}
    )
    # The wrapper key is not a field any rule grants: default deny applies to the wrapper itself.
    assert out == {}


async def test_mediation_failure_fails_closed(monkeypatch):
    plugin = MoritiPlugin.from_yaml("deployments/hr_assistant.yaml")

    def boom(*_args, **_kwargs):
        raise RuntimeError("engine down")

    monkeypatch.setattr(plugin.plane, "mediate", boom)
    out = await plugin.after_tool_callback(tool=tool(), tool_args={"name": "sarah"}, tool_context=context(), result=dict(SARAH))
    assert out == {"moriti": "refused", "reason": "Privacy mediation failed; response withheld"}


async def test_the_proxy_deployment_file_configures_the_plugin_unchanged():
    config = DeploymentConfig.from_yaml("deployments/hr_assistant.yaml")  # has a `downstream:` block the plugin ignores
    assert config.agent == "hr_assistant"
    assert config.purpose == "employee_directory_lookup"
    assert config.allowed_tools == ["get_employee", "list_employees"]
    assert not hasattr(config, "downstream")
