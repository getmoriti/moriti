"""
The Microsoft Agent Framework adapter, driven through ``process(context, call_next)``
with the framework's own context and tool types.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("agent_framework")

from agent_framework import FunctionInvocationContext, FunctionTool, MiddlewareTermination
from pydantic import BaseModel

from moriti.adapters.agentframework import MoritiFunctionMiddleware

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


def get_employee(name: str) -> dict:
    """Look up an employee record by first name."""
    return dict(SARAH)


def tool(name: str = "get_employee") -> FunctionTool:
    return FunctionTool(name=name, description="Look up an employee record by first name.", func=get_employee)


def context(result, *, name: str = "get_employee", arguments=None) -> FunctionInvocationContext:
    return FunctionInvocationContext(function=tool(name), arguments=arguments or {"name": "sarah"},
                                     session=SimpleNamespace(user_id="employee_titus"))


async def run(middleware: MoritiFunctionMiddleware, ctx: FunctionInvocationContext, result):
    calls = []

    async def call_next():
        calls.append(1)
        ctx.result = result

    await middleware.process(ctx, call_next)
    return ctx.result, len(calls)


async def test_directory_agent_never_receives_salary():
    out, called = await run(MoritiFunctionMiddleware.from_yaml("deployments/hr_assistant.yaml"), context(None), dict(SARAH))
    assert called == 1
    assert out["name"] == "Sarah Ndlovu" and out["email"] == "sarah.ndlovu@example.co.za"
    for field in ("salary", "bank_account", "tax_number", "employee_id"):
        assert field not in out


async def test_payroll_agent_same_tool_receives_salary():
    out, _ = await run(MoritiFunctionMiddleware.from_yaml("deployments/payroll_agent.yaml"), context(None), dict(SARAH))
    assert out["salary"] == 1450000.0 and "email" not in out


async def test_disallowed_tool_is_refused_before_it_runs():
    middleware = MoritiFunctionMiddleware.from_yaml("deployments/payroll_agent.yaml")  # allowlist: get_employee
    ctx = context(None, name="list_employees", arguments={})
    with pytest.raises(MiddlewareTermination) as excinfo:
        await run(middleware, ctx, ["sarah", "thabo"])
    assert excinfo.value.result == {"moriti": "refused", "reason": "Tool 'list_employees' is not permitted for agent 'payroll_agent'"}


async def test_json_text_is_mediated_and_free_text_withheld():
    middleware = MoritiFunctionMiddleware.from_yaml("deployments/hr_assistant.yaml")
    out, _ = await run(middleware, context(None), json.dumps(SARAH))
    assert "salary" not in json.loads(out)
    out, _ = await run(middleware, context(None), "Sarah earns 1450000")
    assert json.loads(out)["moriti"].startswith("unstructured")


async def test_pydantic_results_are_dumped_and_mediated():
    class Employee(BaseModel):
        name: str
        email: str
        salary: float

    out, _ = await run(MoritiFunctionMiddleware.from_yaml("deployments/hr_assistant.yaml"), context(None),
                       Employee(name="Sarah Ndlovu", email="sarah@example.co.za", salary=1450000.0))
    assert out == {"name": "Sarah Ndlovu", "email": "sarah@example.co.za"}


async def test_unmediatable_objects_and_engine_failures_fail_closed(monkeypatch):
    middleware = MoritiFunctionMiddleware.from_yaml("deployments/hr_assistant.yaml")
    out, _ = await run(middleware, context(None), object())
    assert out["moriti"] == "refused"
    monkeypatch.setattr(middleware.plane, "mediate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    out, _ = await run(middleware, context(None), dict(SARAH))
    assert out == {"moriti": "refused", "reason": "Privacy mediation failed; response withheld"}


async def test_purpose_cannot_be_smuggled_through_arguments():
    out, _ = await run(MoritiFunctionMiddleware.from_yaml("deployments/hr_assistant.yaml"),
                       context(None, arguments={"name": "sarah", "purpose": "monthly_payroll_processing"}), dict(SARAH))
    assert "salary" not in out


# The real path. The framework turns a tool's return value into content items
# before the middleware sees it, so these drive a real FunctionTool through the
# framework's own middleware pipeline instead of handing the middleware a dict.

from agent_framework import Content  # noqa: E402
from agent_framework._middleware import FunctionMiddlewarePipeline  # noqa: E402


async def run_real(middleware: MoritiFunctionMiddleware, func, arguments=None, name: str = "get_employee"):
    the_tool = FunctionTool(name=name, description="Look up an employee record.", func=func)
    ctx = FunctionInvocationContext(function=the_tool, arguments=arguments or {"name": "sarah"},
                                    session=SimpleNamespace(user_id="employee_titus"))

    async def final(c):
        return await the_tool.invoke(arguments=c.arguments, context=c)

    return await FunctionMiddlewarePipeline(middleware).execute(ctx, final)


def texts(result) -> list[str]:
    assert isinstance(result, list) and all(isinstance(c, Content) for c in result), result
    return [c.text for c in result]


async def test_real_tool_result_is_mediated_not_passed_through():
    out = await run_real(MoritiFunctionMiddleware.from_yaml("deployments/hr_assistant.yaml"), get_employee)
    body = json.loads(texts(out)[0])
    assert body["name"] == "Sarah Ndlovu" and body["email"] == "sarah.ndlovu@example.co.za"
    for field in ("salary", "bank_account", "tax_number", "employee_id"):
        assert field not in body
    assert "1450000" not in "".join(texts(out))


async def test_real_tool_same_data_other_purpose_receives_salary():
    out = await run_real(MoritiFunctionMiddleware.from_yaml("deployments/payroll_agent.yaml"), get_employee)
    body = json.loads(texts(out)[0])
    assert body["salary"] == 1450000.0 and "email" not in body


async def test_real_tool_free_text_is_withheld():
    def narrate(name: str) -> str:
        return "Sarah earns 1450000"

    out = await run_real(MoritiFunctionMiddleware.from_yaml("deployments/hr_assistant.yaml"), narrate)
    assert "1450000" not in "".join(texts(out))


async def test_real_tool_non_text_content_is_refused_whole():
    def slip(name: str):
        return Content.from_uri(uri="https://example.com/salary-slip.png", media_type="image/png")

    out = await run_real(MoritiFunctionMiddleware.from_yaml("deployments/hr_assistant.yaml"), slip)
    assert out["moriti"] == "refused"
