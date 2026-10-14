"""
Safe-by-default purposes, and what an audit event records.

An undefined purpose is the quiet failure: a typo in a deployment file must not
read as "nothing to check". And the audit event is the evidence record, so it
has to say which rule proposed each decision as well as which guard restricted it.
"""

from __future__ import annotations

import logging

import pytest

from moriti import Decision, LegalBasis, PrivacyPlane, RequestContext, audit
from moriti.policy import Policy

RECORD = {"name": "Sarah Ndlovu", "email": "sarah@example.co.za", "salary": 1450000}


def ctx(purpose: str, **kw) -> RequestContext:
    return RequestContext(
        agent="hr_assistant", purpose=purpose, legal_basis=LegalBasis.LEGITIMATE_INTEREST, **kw
    )


def open_policy(**flags) -> Policy:
    """A policy whose only rule allows everything for any purpose, so only the guards can object."""
    return Policy.model_validate(
        {
            "name": "open",
            "purposes": {"directory": {"necessary_fields": ["name", "email"]}},
            "rules": [{"id": "allow-all", "field": "*", "decision": "allow"}],
            **flags,
        }
    )


# -- require_known_purpose ---------------------------------------------------------


def test_an_undefined_purpose_is_denied_by_default():
    result = PrivacyPlane(open_policy()).mediate(RECORD, ctx("directry"), audit=False)  # a typo
    assert result.data == {}
    for d in result.decisions:
        assert d.decision is Decision.DENY
        assert d.restricted_by == ["purpose_necessity"]
        assert "not defined in policy 'open'" in d.reason


def test_a_defined_purpose_is_unaffected():
    result = PrivacyPlane(open_policy()).mediate(RECORD, ctx("directory"), audit=False)
    assert set(result.data) == {"name", "email"}
    assert result.withheld == ["salary"]


def test_a_policy_can_opt_out_of_requiring_known_purposes():
    plane = PrivacyPlane(open_policy(require_known_purpose=False))
    result = plane.mediate(RECORD, ctx("anything_at_all"), audit=False)
    assert set(result.data) == set(RECORD)


@pytest.mark.parametrize("pack", ["popia_hr_v1", "popia_customer_v1"])
def test_bundled_packs_require_known_purposes(pack):
    assert PrivacyPlane.from_policy(pack).policy.require_known_purpose is True


def test_necessity_reason_says_assigned_purpose():
    result = PrivacyPlane(open_policy()).mediate(RECORD, ctx("directory"), audit=False)
    reason = next(d.reason for d in result.decisions if d.field == "salary")
    assert "assigned purpose 'directory'" in reason


# -- the audit event ---------------------------------------------------------------


def test_audit_event_records_the_rule_that_proposed_each_decision():
    plane = PrivacyPlane(open_policy())
    event = plane.mediate(RECORD, ctx("directory")).audit
    assert event is not None
    assert event.matched_rule == {"name": "allow-all", "email": "allow-all", "salary": "allow-all"}
    assert event.restricted_by == {"salary": ["purpose_necessity"]}


def test_a_field_decided_by_the_policy_default_has_no_matched_rule():
    policy = Policy.model_validate({"name": "closed", "purposes": {"directory": {}}, "rules": []})
    event = PrivacyPlane(policy).mediate({"name": "S"}, ctx("directory")).audit
    assert event is not None and event.matched_rule == {}


def test_audit_event_never_contains_a_protected_value():
    event = PrivacyPlane(open_policy()).mediate(RECORD, ctx("directory")).audit
    assert event is not None
    dumped = event.to_json()
    assert "1450000" not in dumped and "sarah@example.co.za" not in dumped


# -- the audit sink ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_sink():
    yield
    audit.set_sink(None)


def test_a_registered_sink_receives_events_instead_of_the_log(caplog):
    received = []
    audit.set_sink(received.append)
    with caplog.at_level(logging.INFO, logger="moriti.audit"):
        PrivacyPlane(open_policy()).mediate(RECORD, ctx("directory"))
    assert len(received) == 1 and received[0].purpose == "directory"
    assert not [r for r in caplog.records if "privacy.audit" in r.getMessage()]


def test_a_failing_sink_does_not_block_the_response_and_falls_back_to_the_log(caplog):
    def broken(_event):
        raise RuntimeError("siem down")

    audit.set_sink(broken)
    with caplog.at_level(logging.INFO, logger="moriti.audit"):
        result = PrivacyPlane(open_policy()).mediate(RECORD, ctx("directory"))
    assert set(result.data) == {"name", "email"}
    messages = [r.getMessage() for r in caplog.records]
    assert any("Audit sink failed" in m for m in messages)
    assert any("privacy.audit" in m for m in messages)  # the event was not lost


def test_set_sink_none_restores_the_log(caplog):
    audit.set_sink(lambda _e: None)
    audit.set_sink(None)
    with caplog.at_level(logging.INFO, logger="moriti.audit"):
        PrivacyPlane(open_policy()).mediate(RECORD, ctx("directory"))
    assert any("privacy.audit" in r.getMessage() for r in caplog.records)
