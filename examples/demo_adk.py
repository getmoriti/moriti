"""
moriti inside Google ADK -- demonstration.

Run:  python -m examples.demo_adk        (needs `pip install -e ".[adk]"`)

Drives the plugin's callbacks directly with the same tool result for two
deployments. In a real agent the plugin is attached to the Runner and ADK
fires the callbacks itself; nothing else changes.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

try:
    from google.adk.tools.base_tool import BaseTool
except ImportError:  # pragma: no cover
    sys.exit("This demo needs the ADK extra:  pip install -e '.[adk]'")

from moriti.adapters.adk import MoritiPlugin

ROOT = Path(__file__).resolve().parent.parent
RULE = "=" * 74

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


class GetEmployee(BaseTool):
    """Stands in for the real tool; the callbacks only need its name."""

    def __init__(self) -> None:
        super().__init__(name="get_employee", description="Look up an employee record by first name.")

    async def run_async(self, *, args, tool_context):
        return dict(SARAH)


async def main() -> None:
    tool = GetEmployee()
    tool_context = SimpleNamespace(agent_name="demo", session=SimpleNamespace(user_id="employee_titus"), state={})

    for deployment in ("hr_assistant", "payroll_agent"):
        plugin = MoritiPlugin.from_yaml(ROOT / "deployments" / f"{deployment}.yaml")
        print(f"\n{RULE}\n{deployment}  (bound purpose: {plugin.deployment.purpose})\n{RULE}")
        print("get_employee('sarah') returns the whole record; after the plugin the agent sees:\n")
        out = await plugin.after_tool_callback(
            tool=tool, tool_args={"name": "sarah"}, tool_context=tool_context, result=dict(SARAH)
        )
        print(json.dumps(out, indent=2))

    print(f"\n{RULE}")
    print("Same tool. Same record. The purpose lives in the deployment file and the")
    print("agent cannot vary it. To run this inside a real agent:\n")
    print("  from google.adk.runners import Runner")
    print("  from moriti.adapters.adk import MoritiPlugin\n")
    print("  runner = Runner(app_name='hr', agent=root_agent, session_service=session_service,")
    print("                  plugins=[MoritiPlugin.from_yaml('deployments/hr_assistant.yaml')])")


if __name__ == "__main__":
    asyncio.run(main())
