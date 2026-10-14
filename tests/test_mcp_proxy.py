"""
End-to-end tests for the MCP privacy proxy.

Each test drives the proxy's own handlers with a REAL downstream MCP server
running as a subprocess over stdio -- the same wire path production uses; only
the agent-facing stdio front is invoked directly.
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack

import pytest
from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client

from moriti.mcp.config import ProxyConfig
from moriti.mcp.proxy import PrivacyProxy, _fingerprint

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def proxy_for(deployment: str, stack: AsyncExitStack) -> PrivacyProxy:
    """A PrivacyProxy wired to a live demo_hr_server subprocess."""
    config = ProxyConfig.from_yaml(f"deployments/{deployment}.yaml")
    proxy = PrivacyProxy(config)
    params = StdioServerParameters(
        command=config.downstream.resolved_command, args=config.downstream.args
    )
    read, write = await stack.enter_async_context(stdio_client(params))
    proxy.downstream = await stack.enter_async_context(ClientSession(read, write))
    await proxy.downstream.initialize()
    listed = await proxy.downstream.list_tools()
    for tool in listed.tools:
        proxy._pinned[tool.name] = _fingerprint(tool)
    return proxy


def payload(content: list[types.TextContent]) -> dict | list:
    assert len(content) == 1
    return json.loads(content[0].text)


async def test_hr_assistant_never_receives_salary():
    """The downstream server returns salary; the agent must not see it."""
    async with AsyncExitStack() as stack:
        proxy = await proxy_for("hr_assistant", stack)
        result = payload(await proxy._call_tool("get_employee", {"name": "sarah"}))

        assert result["name"] == "Sarah Ndlovu"
        assert result["email"] == "sarah.ndlovu@example.co.za"
        for field in ("salary", "bank_account", "tax_number"):
            assert field not in result


async def test_payroll_agent_same_tool_receives_salary():
    """Identical downstream tool; different bound purpose; opposite outcome."""
    async with AsyncExitStack() as stack:
        proxy = await proxy_for("payroll_agent", stack)
        result = payload(await proxy._call_tool("get_employee", {"name": "sarah"}))

        assert result["salary"] == 1450000.00
        assert result["bank_account"] == "10000007792"


async def test_agent_cannot_choose_its_own_purpose():
    """The context the proxy evaluates comes from config, not the wire."""
    async with AsyncExitStack() as stack:
        proxy = await proxy_for("hr_assistant", stack)
        ctx = proxy._context("get_employee", "sarah")
        assert ctx.purpose == "employee_directory_lookup"
        assert ctx.agent == "hr_assistant"
        # Nothing in _call_tool's signature accepts purpose/agent/context:
        # arguments flow to the downstream tool, never into RequestContext.


async def test_disallowed_tool_is_refused_before_downstream():
    async with AsyncExitStack() as stack:
        proxy = await proxy_for("payroll_agent", stack)   # allows only get_employee
        result = payload(await proxy._call_tool("list_employees", {}))
        assert result["moriti"] == "refused"


async def test_tools_list_filtered_to_allowlist():
    async with AsyncExitStack() as stack:
        proxy = await proxy_for("payroll_agent", stack)
        tools = await proxy._list_tools()
        assert [t.name for t in tools] == ["get_employee"]


async def test_rug_pull_definition_change_refused():
    """A tool whose definition drifts after pinning must not be callable."""
    async with AsyncExitStack() as stack:
        proxy = await proxy_for("hr_assistant", stack)
        proxy._pinned["get_employee"] = "not-the-real-fingerprint"
        result = payload(await proxy._call_tool("get_employee", {"name": "sarah"}))
        assert result["moriti"] == "refused"
        assert "changed its definition" in result["reason"]


async def test_mediation_failure_fails_closed(monkeypatch):
    """If the policy engine itself blows up, the agent gets nothing."""
    async with AsyncExitStack() as stack:
        proxy = await proxy_for("hr_assistant", stack)

        def boom(*a, **k):
            raise RuntimeError("engine down")

        monkeypatch.setattr(proxy.plane, "mediate", boom)
        result = payload(await proxy._call_tool("get_employee", {"name": "sarah"}))
        assert result["moriti"] == "refused"


async def test_unknown_employee_error_passes_through_shape():
    """Error objects are dicts too; they are mediated, not special-cased."""
    async with AsyncExitStack() as stack:
        proxy = await proxy_for("hr_assistant", stack)
        result = payload(await proxy._call_tool("get_employee", {"name": "nobody"}))
        assert "salary" not in result
