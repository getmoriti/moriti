"""Hardening that a typo or a default must not defeat: strict keys, keyed tokens, exposure warning."""

import logging

import pytest
from pydantic import ValidationError

from moriti import masking
from moriti._config import warn_if_exposed
from moriti.adapters.common import DeploymentConfig
from moriti.mcp.config import ProxyConfig

BASE = {"agent": "hr_assistant", "purpose": "employee_directory_lookup", "policy": "popia_hr_v1"}


def test_a_misspelt_key_is_refused_with_a_hint():
    with pytest.raises(ValidationError, match=r"allowed_tool.*did you mean 'allowed_tools'"):
        DeploymentConfig(**BASE, allowed_tool=["get_employee"])


def test_the_proxys_downstream_block_is_still_accepted_by_every_adapter():
    cfg = DeploymentConfig(**BASE, downstream={"command": "{python}", "args": ["-m", "x"]})
    assert cfg.agent == "hr_assistant"
    assert not hasattr(cfg, "downstream")


def test_the_proxy_config_refuses_unknown_keys_too():
    good = {**BASE, "downstream": {"command": "{python}"}}
    ProxyConfig.model_validate(good)
    with pytest.raises(ValidationError, match="unknown key"):
        ProxyConfig.model_validate({**good, "retension": "ephemeral"})
    with pytest.raises(ValidationError):
        ProxyConfig.model_validate({**BASE, "downstream": {"commnad": "{python}"}})


def test_shipped_deployment_files_still_load():
    import glob

    paths = glob.glob("deployments/*.yaml")
    assert paths
    for path in paths:
        ProxyConfig.from_yaml(path)
        DeploymentConfig.from_yaml(path)


def test_tokens_are_keyed_when_a_key_is_set(monkeypatch):
    monkeypatch.delenv("MORITI_TOKEN_KEY", raising=False)
    unkeyed = masking.pseudonymise("8001015009087")
    monkeypatch.setenv("MORITI_TOKEN_KEY", "k1")
    keyed = masking.pseudonymise("8001015009087")
    assert keyed != unkeyed and keyed == masking.pseudonymise("8001015009087")
    monkeypatch.setenv("MORITI_TOKEN_KEY", "k2")
    assert masking.pseudonymise("8001015009087") != keyed


def test_unkeyed_tokens_warn_once(monkeypatch, caplog):
    monkeypatch.delenv("MORITI_TOKEN_KEY", raising=False)
    monkeypatch.setattr(masking, "_warned_unkeyed", False)
    with caplog.at_level(logging.WARNING, logger="moriti.masking"):
        masking.pseudonymise("a")
        masking.pseudonymise("b")
    assert len([r for r in caplog.records if "MORITI_TOKEN_KEY" in r.message]) == 1


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]"])
def test_loopback_does_not_warn(host, caplog):
    with caplog.at_level(logging.WARNING, logger="t"):
        warn_if_exposed(host, "svc", logging.getLogger("t"))
    assert not caplog.records


@pytest.mark.parametrize("host", ["0.0.0.0", "10.1.2.3", "my-host.internal"])
def test_exposed_bind_warns(host, caplog):
    with caplog.at_level(logging.WARNING, logger="t"):
        warn_if_exposed(host, "svc", logging.getLogger("t"))
    assert any("no authentication" in r.message for r in caplog.records)
