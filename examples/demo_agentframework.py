"""
moriti inside Microsoft Agent Framework -- demonstration.

Run:  python -m examples.demo_agentframework     (needs `pip install -e ".[agentframework]"`)

Drives the middleware's ``process`` directly, the way the framework does around
every function call, for two deployments. In a real agent you pass it to
``Agent(..., middleware=[...])`` and the framework calls it itself.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

try:
    from agent_framework import FunctionInvocationContext, FunctionTool
except ImportError:  # pragma: no cover
    sys.exit("This demo needs the Agent Framework extra:  pip install -e '.[agentframework]'")

from moriti.adapters.agentframework import MoritiFunctionMiddleware

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


def get_employee(name: str) -> dict:
    """Look up an employee record by first name. Returns everything, like a real internal API."""
    return dict(SARAH)


def _invoke(ctx: FunctionInvocationContext):
    """What the framework does at call_next(): run the function and set the result."""

    async def call_next() -> None:
        ctx.result = get_employee("sarah")

    return call_next


async def main() -> None:
    tool = FunctionTool(name="get_employee", description="Look up an employee record by first name.", func=get_employee)
    for deployment in ("hr_assistant", "payroll_agent"):
        middleware = MoritiFunctionMiddleware.from_yaml(ROOT / "deployments" / f"{deployment}.yaml")
        ctx = FunctionInvocationContext(function=tool, arguments={"name": "sarah"})
        await middleware.process(ctx, _invoke(ctx))
        print(f"\n{RULE}\n{deployment}  (bound purpose: {middleware.deployment.purpose})\n{RULE}")
        print("get_employee('sarah') returned the whole record; after the middleware the model sees:\n")
        print(json.dumps(ctx.result, indent=2))

    print(f"\n{RULE}")
    print("Same function. Same record. The purpose lives in the deployment file and the")
    print("agent cannot vary it. To run this inside a real agent:\n")
    print("  from agent_framework import Agent")
    print("  from moriti.adapters.agentframework import MoritiFunctionMiddleware\n")
    print("  agent = Agent(client=client, tools=[get_employee],")
    print("                middleware=[MoritiFunctionMiddleware.from_yaml('deployments/hr_assistant.yaml')])")


if __name__ == "__main__":
    asyncio.run(main())
