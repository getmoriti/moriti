"""
moriti inside Strands Agents -- demonstration.

Run:  python -m examples.demo_strands        (needs `pip install -e ".[strands]"`)

Fires the same events Strands fires around a tool call, through a real
HookRegistry, for two deployments. In a real agent you pass the hooks to
``Agent(hooks=[...])`` and Strands fires them itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

try:
    from strands.hooks import HookRegistry
    from strands.hooks.events import AfterToolCallEvent
except ImportError:  # pragma: no cover
    sys.exit("This demo needs the Strands extra:  pip install -e '.[strands]'")

from moriti.adapters.strands import MoritiHooks

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


def main() -> None:
    for deployment in ("hr_assistant", "payroll_agent"):
        hooks = MoritiHooks.from_yaml(ROOT / "deployments" / f"{deployment}.yaml")
        registry = HookRegistry()
        registry.add_hook(hooks)
        event = AfterToolCallEvent(
            agent=SimpleNamespace(name="demo"), selected_tool=None,
            tool_use={"toolUseId": "t-1", "name": "get_employee", "input": {"name": "sarah"}},
            invocation_state={},
            result={"toolUseId": "t-1", "status": "success", "content": [{"json": dict(SARAH)}]},
        )
        event, _ = registry.invoke_callbacks(event)
        print(f"\n{RULE}\n{deployment}  (bound purpose: {hooks.deployment.purpose})\n{RULE}")
        print("get_employee('sarah') returned the whole record; after the hooks the model sees:\n")
        print(json.dumps(event.result["content"][0]["json"], indent=2))

    print(f"\n{RULE}")
    print("Same tool. Same record. The purpose lives in the deployment file and the")
    print("agent cannot vary it. To run this inside a real agent:\n")
    print("  from strands import Agent")
    print("  from moriti.adapters.strands import MoritiHooks\n")
    print("  agent = Agent(tools=[get_employee], hooks=[MoritiHooks.from_yaml('deployments/hr_assistant.yaml')])")


if __name__ == "__main__":
    main()
