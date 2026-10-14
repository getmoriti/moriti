"""The mediation service, through Starlette's test client."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from moriti.adapters.common import DeploymentConfig
from moriti.http import build_app
from moriti.http.service import load_deployments

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


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(load_deployments(["deployments/hr_assistant.yaml", "deployments/payroll_agent.yaml"])))


def test_health_and_listing(client):
    assert client.get("/healthz").json() == {"status": "ok", "deployments": ["hr_assistant", "payroll_agent"]}
    listed = {d["deployment"]: d for d in client.get("/deployments").json()["deployments"]}
    assert listed["hr_assistant"]["purpose"] == "employee_directory_lookup"
    assert listed["payroll_agent"]["policy"] == "popia_hr_v1"


def test_directory_deployment_withholds_salary(client):
    out = client.post("/mediate/hr_assistant", json={"tool": "get_employee", "arguments": {"name": "sarah"}, "result": SARAH}).json()
    assert out["result"]["name"] == "Sarah Ndlovu" and "salary" not in out["result"]
    assert set(out["withheld"]) >= {"salary", "bank_account", "tax_number"}
    assert out["agent"] == "hr_assistant" and out["purpose"] == "employee_directory_lookup"


def test_payroll_deployment_releases_salary(client):
    out = client.post("/mediate/payroll_agent", json={"tool": "get_employee", "arguments": {}, "result": SARAH}).json()
    assert out["result"]["salary"] == 1450000.0 and "email" not in out["result"]


def test_lists_and_json_text_and_free_text(client):
    out = client.post("/mediate/hr_assistant", json={"tool": "list", "result": [SARAH, SARAH]}).json()
    assert [r.get("salary") for r in out["result"]] == [None, None]
    out = client.post("/mediate/hr_assistant", json={"tool": "t", "result": json.dumps(SARAH)}).json()
    assert "salary" not in json.loads(out["result"])
    out = client.post("/mediate/hr_assistant", json={"tool": "t", "result": "Sarah earns 1450000"}).json()
    assert json.loads(out["result"])["moriti"].startswith("unstructured")


def test_errors_are_explicit(client):
    assert client.post("/mediate/nobody", json={"tool": "t", "result": {}}).status_code == 404
    assert client.post("/mediate/hr_assistant", content=b"not json", headers={"content-type": "application/json"}).status_code == 400
    assert client.post("/mediate/hr_assistant", json={"tool": "t"}).status_code == 400
    ambiguous = client.post("/mediate", json={"tool": "t", "result": {}})
    assert ambiguous.status_code == 400 and "several deployments" in ambiguous.json()["error"]


def test_single_deployment_serves_bare_mediate():
    single = TestClient(build_app({"hr": DeploymentConfig.from_yaml("deployments/hr_assistant.yaml")}))
    out = single.post("/mediate", json={"tool": "get_employee", "result": SARAH}).json()
    assert "salary" not in out["result"] and out["deployment"] == "hr"


def test_mediation_failure_returns_a_refusal_not_the_original(monkeypatch):
    app = build_app({"hr": DeploymentConfig.from_yaml("deployments/hr_assistant.yaml")})
    from moriti.http import service as svc
    monkeypatch.setattr(svc, "mediate_value", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    out = TestClient(app).post("/mediate", json={"tool": "t", "result": SARAH})
    assert out.status_code == 200
    assert out.json()["error"] == "mediation_failed"
    assert out.json()["result"] == {"moriti": "refused", "reason": "Privacy mediation failed; response withheld"}
