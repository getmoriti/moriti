"""
Toy HR MCP server for demonstrating the proxy.

Deliberately naive: `get_employee` returns the ENTIRE record, salary and all,
exactly like a real internal API that predates any notion of agent access.
The point of the demo is that the proxy -- not this server -- is what stops
sensitive fields reaching the agent.

Run standalone:  python -m moriti.mcp.demo_hr_server                       # stdio
                 python -m moriti.mcp.demo_hr_server --http 127.0.0.1:8766  # streamable HTTP
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

EMPLOYEES = {
    "sarah": {
        "name": "Sarah Ndlovu",
        "email": "sarah.ndlovu@example.co.za",
        "department": "Engineering",
        "job_title": "Staff Engineer",
        "employee_id": "EMP-4831",
        "salary": 1450000.00,
        "bank_account": "10000007792",
        "tax_number": "0100007263",
    },
    "thabo": {
        "name": "Thabo Mokoena",
        "email": "thabo.mokoena@example.co.za",
        "department": "Finance",
        "job_title": "Financial Analyst",
        "employee_id": "EMP-2210",
        "salary": 890000.00,
        "bank_account": "10000004418",
        "tax_number": "0100004419",
    },
}

async def list_tools(_ctx, _params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=[
        types.Tool(
            name="get_employee",
            description="Look up an employee record by first name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Employee first name"},
                },
                "required": ["name"],
            },
        ),
        types.Tool(
            name="list_employees",
            description="List all employee first names.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ])


async def call_tool(_ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    name, arguments = params.name, params.arguments or {}
    return types.CallToolResult(content=_answer(name, arguments))


def _answer(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "list_employees":
        return [types.TextContent(type="text", text=json.dumps(sorted(EMPLOYEES)))]

    if name == "get_employee":
        key = str(arguments.get("name", "")).strip().lower()
        record = EMPLOYEES.get(key)
        if record is None:
            return [types.TextContent(type="text", text=json.dumps({"error": f"no employee named {key!r}"}))]
        # The whole record. No masking. That is the point.
        return [types.TextContent(type="text", text=json.dumps(record))]

    return [types.TextContent(type="text", text=json.dumps({"error": f"unknown tool {name!r}"}))]


server = Server("demo-hr-system", on_list_tools=list_tools, on_call_tool=call_tool)


async def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--http":
        import uvicorn

        host, _, port = sys.argv[2].rpartition(":")
        app = server.streamable_http_app(host=host)
        await uvicorn.Server(uvicorn.Config(app, host=host, port=int(port), log_level="warning")).serve()
        return
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
