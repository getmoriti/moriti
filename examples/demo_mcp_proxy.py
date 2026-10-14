"""
MCP proxy demonstration: one downstream HR system, two agents, two outcomes.

Run:  python -m examples.demo_mcp_proxy

Both agents call the SAME tool on the SAME server and ask about the SAME
employee. The only difference is the purpose bound to each proxy deployment.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
RULE = "=" * 74


async def ask_via(deployment: str) -> dict:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "moriti.mcp.proxy",
              f"deployments/{deployment}.yaml"],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("get_employee", {"name": "sarah"})
        return json.loads(result.content[0].text)


async def main() -> None:
    print(f"{RULE}\nDownstream HR server returns the FULL record for every caller:")
    print("  name, email, department, job_title, employee_id, salary,")
    print("  bank_account, tax_number\n")

    for deployment, purpose in [
        ("hr_assistant", "employee_directory_lookup"),
        ("payroll_agent", "monthly_payroll_processing"),
    ]:
        data = await ask_via(deployment)
        print(f"{RULE}\n{deployment}  (bound purpose: {purpose})")
        print(f"{RULE}")
        print("get_employee('sarah') through the moriti proxy returns:\n")
        print(json.dumps(data, indent=2))
        print()

    print(f"{RULE}")
    print("Same server. Same tool. Same employee. The purpose is configured on")
    print("the proxy deployment -- the agent never declares it and cannot vary")
    print("it. Audit events for both calls are in the proxy's stderr log.")


if __name__ == "__main__":
    asyncio.run(main())
