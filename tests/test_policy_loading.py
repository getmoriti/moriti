"""Policy packs can live anywhere: by path, by name on MORITI_POLICY_PATH, or bundled."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from moriti import PrivacyPlane
from moriti.adapters.common import DeploymentConfig
from moriti.mcp.config import ProxyConfig
from moriti.policy import POLICY_DIR, Policy, resolve_policy

BUNDLED = POLICY_DIR / "popia_hr_v1.yaml"


def custom_pack(directory: Path, name: str, description: str) -> Path:
    text = BUNDLED.read_text().replace("name: popia_hr\n", f"name: {name}\n", 1)
    text = re.sub(r"description: >\n(?:  .*\n)+", f"description: {description}\n", text, count=1)  # the whole folded block
    path = directory / f"{name}.yaml"
    path.write_text(text)
    return path


def test_bundled_name_still_loads():
    assert Policy.load("popia_hr_v1").name == "popia_hr"
    assert resolve_policy("popia_customer_v1") == POLICY_DIR / "popia_customer_v1.yaml"


def test_path_loads_a_pack_from_anywhere(tmp_path):
    path = custom_pack(tmp_path, "my_bank_v1", "a bank's own pack")
    assert Policy.load(path).name == "my_bank_v1"
    assert PrivacyPlane.from_policy(str(path)).policy.name == "my_bank_v1"


def test_name_on_policy_path_and_user_packs_win(tmp_path, monkeypatch):
    custom_pack(tmp_path, "my_bank_v1", "a bank's own pack")
    custom_pack(tmp_path, "popia_hr_v1", "overridden by the user")  # same name as a bundled pack
    monkeypatch.setenv("MORITI_POLICY_PATH", str(tmp_path))
    assert Policy.load("my_bank_v1").name == "my_bank_v1"
    assert Policy.load("popia_hr_v1").description.strip() == "overridden by the user"
    assert Policy.load("popia_customer_v1").name == "popia_customer"  # falls through to bundled


def test_missing_packs_say_where_they_looked(tmp_path, monkeypatch):
    monkeypatch.setenv("MORITI_POLICY_PATH", str(tmp_path))
    with pytest.raises(FileNotFoundError) as excinfo:
        Policy.load("nope")
    assert str(tmp_path) in str(excinfo.value) and str(POLICY_DIR) in str(excinfo.value)
    with pytest.raises(FileNotFoundError):
        Policy.load(tmp_path / "missing.yaml")


def test_deployment_files_resolve_a_relative_policy_beside_themselves(tmp_path):
    custom_pack(tmp_path, "my_bank_v1", "a bank's own pack")
    deployment = tmp_path / "hr.yaml"
    deployment.write_text(
        "agent: hr_assistant\npurpose: employee_directory_lookup\npolicy: ./my_bank_v1.yaml\n"
        "legal_basis: legitimate_interest\ndownstream:\n  command: \"{python}\"\n  args: [-m, moriti.mcp.demo_hr_server]\n"
    )
    assert PrivacyPlane.from_policy(DeploymentConfig.from_yaml(deployment).policy).policy.name == "my_bank_v1"
    assert PrivacyPlane.from_policy(ProxyConfig.from_yaml(deployment).policy).policy.name == "my_bank_v1"
