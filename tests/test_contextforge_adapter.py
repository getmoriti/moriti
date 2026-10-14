"""
Tests for the ContextForge (cpex) adapter.

Skipped entirely unless ``cpex`` is importable (it needs Python 3.12), so the
core suite stays green on 3.11. The load-bearing tests are the last two: one
proves the rewrite survives dispatch through cpex's *real* plugin manager with
the gateway's own field policy, and one proves an engine failure never
releases the payload.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

cpex = pytest.importorskip("cpex")

from cpex.framework.hooks.tools import ToolPostInvokePayload
from cpex.framework.models import (
    GlobalContext,
    PluginConfig,
    PluginContext,
)

from moriti.adapters.contextforge import (
    DeploymentConfig,
    MoritiPrivacyPlugin,
)
from moriti.adapters.contextforge.plugin import (
    VIOLATION_CODE,
    WITHHELD_UNSTRUCTURED,
)

pytestmark = pytest.mark.anyio

RESOURCES = Path(__file__).resolve().parent.parent / "moriti" / "adapters" / "contextforge" / "resources" / "plugins"

EMPLOYEE = {
    "name": "Sarah Ndlovu",
    "email": "sarah.ndlovu@example.co.za",
    "department": "Engineering",
    "employee_id": "EMP-4831",
    "salary": 1450000.0,
    "bank_account": "10000007792",
    "tax_number": "0100007263",
}
SENSITIVE = ("salary", "bank_account", "tax_number")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def plugin_from(deployment: str) -> MoritiPrivacyPlugin:
    """Build the plugin exactly as the server would, from the deployment YAML."""
    import yaml

    entry = yaml.safe_load((RESOURCES / f"{deployment}.yaml").read_text())["plugins"][0]
    return MoritiPrivacyPlugin(PluginConfig(**entry))


def ctx(user: str = "employee_titus") -> PluginContext:
    return PluginContext(global_context=GlobalContext(request_id="req-1", user=user))


def mcp_result(record, **extra) -> dict:
    """Shape the gateway produces: CallToolResult.model_dump(by_alias=True)."""
    return {"content": [{"type": "text", "text": json.dumps(record)}], "isError": False, **extra}


def text_of(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


# --- the core claim, inside the gateway's hook -------------------------------

async def test_hr_assistant_never_receives_salary():
    plugin = plugin_from("hr_assistant")
    out = await plugin.tool_post_invoke(ToolPostInvokePayload(name="get_employee", result=mcp_result(EMPLOYEE)), ctx())

    assert out.continue_processing is True
    assert out.violation is None
    data = text_of(out.modified_payload.result)
    assert data["name"] == EMPLOYEE["name"]
    assert data["email"] == EMPLOYEE["email"]
    for field in SENSITIVE:
        assert field not in data
    withheld = set(out.metadata["moriti"]["withheld"])
    assert set(SENSITIVE) <= withheld
    # employee_id goes too: not in the purpose's necessary_fields and nothing
    # grants it -- minimisation withholding what a directory lookup doesn't need.
    assert "employee_id" in withheld and "employee_id" not in data


async def test_payroll_agent_same_tool_receives_salary():
    plugin = plugin_from("payroll_agent")
    out = await plugin.tool_post_invoke(ToolPostInvokePayload(name="get_employee", result=mcp_result(EMPLOYEE)), ctx())
    data = text_of(out.modified_payload.result)
    assert data["salary"] == EMPLOYEE["salary"]
    assert data["bank_account"] == EMPLOYEE["bank_account"]


async def test_purpose_is_bound_in_config_not_taken_from_the_call():
    plugin = plugin_from("hr_assistant")
    request_ctx = plugin._context("get_employee", user="anyone")
    assert request_ctx.purpose == "employee_directory_lookup"
    assert request_ctx.agent == "hr_assistant"
    # The hook signature carries only (name, result): no purpose can arrive on the wire.


async def test_gateway_user_becomes_the_principal():
    plugin = plugin_from("hr_assistant")
    assert plugin._context("t", user="alice@example.co.za").principal == "alice@example.co.za"
    assert plugin._context("t", user=None).principal is None


# --- result shapes -----------------------------------------------------------

async def test_empty_probe_result_passes_through():
    """The gateway probes hooks with result={} while building retry policy."""
    plugin = plugin_from("hr_assistant")
    out = await plugin.tool_post_invoke(ToolPostInvokePayload(name="get_employee", result={}), ctx())
    assert out.continue_processing is True
    assert out.modified_payload is None


async def test_structured_content_is_mediated_too():
    plugin = plugin_from("hr_assistant")
    payload = ToolPostInvokePayload(name="get_employee", result=mcp_result(EMPLOYEE, structuredContent=dict(EMPLOYEE)))
    out = await plugin.tool_post_invoke(payload, ctx())
    structured = out.modified_payload.result["structuredContent"]
    assert "salary" not in structured and structured["email"] == EMPLOYEE["email"]


async def test_list_of_records_is_mediated_element_wise():
    plugin = plugin_from("hr_assistant")
    out = await plugin.tool_post_invoke(ToolPostInvokePayload(name="list_employees", result=mcp_result([EMPLOYEE, EMPLOYEE])), ctx())
    rows = text_of(out.modified_payload.result)
    assert len(rows) == 2 and all("salary" not in r for r in rows)


async def test_plain_dict_result_is_mediated():
    """REST->MCP translation can yield a bare dict rather than content blocks."""
    plugin = plugin_from("hr_assistant")
    out = await plugin.tool_post_invoke(ToolPostInvokePayload(name="get_employee", result=dict(EMPLOYEE)), ctx())
    assert "salary" not in out.modified_payload.result
    assert out.modified_payload.result["name"] == EMPLOYEE["name"]


async def test_is_error_flag_and_block_shape_preserved():
    plugin = plugin_from("hr_assistant")
    out = await plugin.tool_post_invoke(ToolPostInvokePayload(name="get_employee", result=mcp_result(EMPLOYEE)), ctx())
    res = out.modified_payload.result
    assert res["isError"] is False
    assert res["content"][0]["type"] == "text"


# --- failure posture ---------------------------------------------------------

async def test_non_json_text_is_withheld_not_passed_through():
    plugin = plugin_from("hr_assistant")
    leaky = {"content": [{"type": "text", "text": "Sarah Ndlovu earns 1450000 and banks at 10000007792"}], "isError": False}
    out = await plugin.tool_post_invoke(ToolPostInvokePayload(name="get_employee", result=leaky), ctx())
    text = out.modified_payload.result["content"][0]["text"]
    assert "10000007792" not in text and "1450000" not in text
    assert json.loads(text) == WITHHELD_UNSTRUCTURED


async def test_non_text_content_blocks_are_dropped():
    plugin = plugin_from("hr_assistant")
    result = {"content": [{"type": "image", "data": "...", "mimeType": "image/png"}, {"type": "text", "text": json.dumps(EMPLOYEE)}], "isError": False}
    out = await plugin.tool_post_invoke(ToolPostInvokePayload(name="get_employee", result=result), ctx())
    blocks = out.modified_payload.result["content"]
    assert len(blocks) == 1 and blocks[0]["type"] == "text"


async def test_engine_failure_fails_closed_with_violation(monkeypatch):
    plugin = plugin_from("hr_assistant")

    def boom(*a, **k):
        raise RuntimeError("engine down")

    monkeypatch.setattr(plugin.plane, "mediate", boom)
    out = await plugin.tool_post_invoke(ToolPostInvokePayload(name="get_employee", result=mcp_result(EMPLOYEE)), ctx())
    assert out.continue_processing is False
    assert out.violation is not None and out.violation.code == VIOLATION_CODE
    # The refusal rides along as the replacement result: cpex's transform mode suppresses a
    # denial and continues with the payload it has, so the violation alone would fail open.
    assert out.modified_payload is not None
    blocks = out.modified_payload.result["content"]
    assert out.modified_payload.result["isError"] is True
    assert json.loads(blocks[0]["text"])["moriti"] == "refused"
    assert not any(s in json.dumps(out.modified_payload.result) for s in ("1450000", "10000007792", "0100007263"))


def test_invalid_config_block_is_rejected_at_startup():
    bad = PluginConfig(name="x", kind="moriti.adapters.contextforge.plugin.MoritiPrivacyPlugin", hooks=["tool_post_invoke"], config={"agent": "a"})
    with pytest.raises(ValueError, match="invalid config block"):
        MoritiPrivacyPlugin(bad)


def test_deployment_config_vocabulary_matches_proxy():
    """Same keys as the standalone proxy's deployment YAML, minus transport."""
    fields = set(DeploymentConfig.model_fields)
    for key in ("agent", "purpose", "policy", "principal_role", "destination", "retention", "jurisdiction", "legal_basis", "consent_scopes"):
        assert key in fields


# --- the definitive one: through cpex's real manager, with the gateway's policy --

async def test_rewrite_survives_real_plugin_manager_dispatch(tmp_path):
    """Dispatch via cpex's PluginManager with the gateway's field policy for
    tool_post_invoke (writable_fields={'result'}). If this passes, the rewrite
    is exactly what a real ContextForge would hand the agent."""
    import yaml
    from cpex.framework import PluginManager
    from cpex.framework.hooks.policies import HookPayloadPolicy
    from cpex.framework.hooks.tools import ToolHookType

    entry = yaml.safe_load((RESOURCES / "hr_assistant.yaml").read_text())
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(entry))

    policies = {"tool_post_invoke": HookPayloadPolicy(writable_fields=frozenset({"result"}))}
    try:
        manager = PluginManager(str(cfg_path), hook_policies=policies)
    except TypeError:  # older/newer signature without hook_policies: default policy is "allow"
        manager = PluginManager(str(cfg_path))
    await manager.initialize()
    try:
        result, _ = await manager.invoke_hook(
            ToolHookType.TOOL_POST_INVOKE,
            payload=ToolPostInvokePayload(name="get_employee", result=mcp_result(EMPLOYEE)),
            global_context=GlobalContext(request_id="req-9", user="employee_titus"),
        )
    finally:
        await manager.shutdown()

    assert result.continue_processing is True
    assert result.modified_payload is not None, "manager discarded the rewrite"
    data = text_of(result.modified_payload.result)
    assert "salary" not in data and data["email"] == EMPLOYEE["email"]


@pytest.mark.parametrize("mode", ["transform", "sequential"])
async def test_engine_failure_never_releases_the_original_result_in_any_plugin_mode(tmp_path, monkeypatch, mode):
    """The shipped config runs in `transform`, where cpex suppresses a denial and continues. Through
    the real manager, a failing engine must not let the unmediated result out in either mode."""
    import yaml
    from cpex.framework import PluginManager
    from cpex.framework.hooks.policies import HookPayloadPolicy
    from cpex.framework.hooks.tools import ToolHookType

    def boom(self, *a, **k):
        raise RuntimeError("engine down")

    monkeypatch.setattr(MoritiPrivacyPlugin, "_mediate_result", boom)

    entry = yaml.safe_load((RESOURCES / "hr_assistant.yaml").read_text())
    entry["plugins"][0]["mode"] = mode
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(entry))

    policies = {"tool_post_invoke": HookPayloadPolicy(writable_fields=frozenset({"result"}))}
    try:
        manager = PluginManager(str(cfg_path), hook_policies=policies)
    except TypeError:
        manager = PluginManager(str(cfg_path))
    await manager.initialize()
    try:
        result, _ = await manager.invoke_hook(
            ToolHookType.TOOL_POST_INVOKE,
            payload=ToolPostInvokePayload(name="get_employee", result=mcp_result(EMPLOYEE)),
            global_context=GlobalContext(request_id="req-10", user="employee_titus"),
        )
    finally:
        await manager.shutdown()

    # Whichever mode, the agent gets the refusal in place of the result, never the original.
    assert result.modified_payload is not None, f"{mode} mode let the original result through"
    released = json.dumps(result.modified_payload.result)
    assert "refused" in released
    assert not any(secret in released for secret in ("1450000", "10000007792", "0100007263"))
