"""
moriti inside IBM ContextForge -- demonstration.

Run:  python -m examples.demo_contextforge        (Python 3.12 + `moriti[contextforge]`)

Drives the plugin's ``tool_post_invoke`` hook directly with a payload shaped
exactly as the gateway produces it (a CallToolResult dumped to a dict), for
two deployments bound to two different purposes. The final section prints the
commands to run the same thing live inside a real ContextForge.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

try:
    from cpex.framework.hooks.tools import ToolPostInvokePayload
    from cpex.framework.models import GlobalContext, PluginConfig, PluginContext
except ImportError:  # pragma: no cover
    sys.exit("This demo needs the ContextForge extra on Python 3.12:  pip install 'moriti[contextforge]'")

import yaml

from moriti.adapters.contextforge import MoritiPrivacyPlugin

RESOURCES = Path(__file__).resolve().parent.parent / "moriti" / "adapters" / "contextforge" / "resources"
RULE = "=" * 74

EMPLOYEE = {
    "name": "Sarah Ndlovu",
    "email": "sarah.ndlovu@example.co.za",
    "department": "Engineering",
    "job_title": "Staff Engineer",
    "employee_id": "EMP-4831",
    "salary": 1450000.00,
    "bank_account": "10000007792",
    "tax_number": "0100007263",
}


def gateway_payload(record: dict) -> ToolPostInvokePayload:
    """What ContextForge hands the hook: CallToolResult.model_dump(by_alias=True)."""
    return ToolPostInvokePayload(
        name="get_employee",
        result={"content": [{"type": "text", "text": json.dumps(record)}], "isError": False},
    )


async def run(deployment: str) -> None:
    entry = yaml.safe_load((RESOURCES / "plugins" / f"{deployment}.yaml").read_text())["plugins"][0]
    plugin = MoritiPrivacyPlugin(PluginConfig(**entry))
    context = PluginContext(global_context=GlobalContext(request_id="demo", user="employee_titus"))

    out = await plugin.tool_post_invoke(gateway_payload(EMPLOYEE), context)
    received = json.loads(out.modified_payload.result["content"][0]["text"])

    print(f"{RULE}\n{deployment}  (bound purpose: {entry['config']['purpose']})\n{RULE}")
    print("Gateway rebuilds the agent's response from the rewritten result:\n")
    print(json.dumps(received, indent=2))
    print(f"\nwithheld: {out.metadata['moriti']['withheld']}   policy: {out.metadata['moriti']['policy']}\n")


async def main() -> None:
    print(f"{RULE}\nThe downstream tool returns the FULL record for every caller:")
    print("  " + ", ".join(EMPLOYEE))
    print("ContextForge fires tool_post_invoke; moriti rewrites the result before")
    print("the gateway builds the response the agent sees.\n")

    await run("hr_assistant")
    await run("payroll_agent")

    print(RULE)
    print("Same tool. Same gateway. The purpose lives in the plugin's config block,")
    print("bound at provisioning time -- the agent never declares it.\n")
    print("Run it live inside ContextForge (Python 3.12):\n")
    print("  # 1. start the moriti plugin server for a deployment")
    print(f"  PLUGINS_CONFIG_PATH={RESOURCES}/plugins/hr_assistant.yaml \\")
    print(f"  CHUK_MCP_CONFIG_PATH={RESOURCES}/runtime/config.yaml \\")
    print("  PLUGINS_SERVER_PORT=8000 python -m cpex.framework.external.mcp.server.runtime\n")
    print("  # 2. register it in the gateway's plugins/config.yaml")
    print(f"  #    see {RESOURCES.parent}/gateway-plugin.example.yaml\n")
    print("  # 3. call any tool through the gateway -- withheld fields never reach the agent")


if __name__ == "__main__":
    asyncio.run(main())
