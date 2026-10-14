"""
Tests for the privacy control plane.

The load-bearing assertions are the ones about *guards*: that purpose, consent
and destination can override an explicit grant. If those regress, the product is
an access-control list with extra fields.
"""

from __future__ import annotations

import pytest

from moriti import (
    Decision,
    Destination,
    LegalBasis,
    Obligation,
    PrivacyPlane,
    RequestContext,
    Retention,
)
from moriti.policy import Policy, PolicyEngine

EMPLOYEE = {
    "name": "Sarah Ndlovu",
    "email": "sarah.ndlovu@example.co.za",
    "employee_id": "EMP-4831",
    "salary": 1450000.00,
    "bank_account": "10000007792",
    "tax_number": "0100007263",
}

CUSTOMER = {
    "name": "Thabo Mokoena",
    "mobile_number": "0000000044",
    "national_id": "0000000000000",
}


@pytest.fixture
def hr() -> PrivacyPlane:
    return PrivacyPlane.from_policy("popia_hr_v1")


@pytest.fixture
def customer() -> PrivacyPlane:
    return PrivacyPlane.from_policy("popia_customer_v1")


def decisions_by_field(result) -> dict[str, Decision]:
    return {d.field: d.decision for d in result.decisions}


def directory_ctx(**overrides) -> RequestContext:
    base = dict(
        agent="hr_assistant",
        principal_role="employee",
        data_subject="employee_sarah",
        requested_fields=["name", "email", "salary"],
        purpose="employee_directory_lookup",
        tool="get_employee",
        destination=Destination.INTERNAL_MODEL,
        legal_basis=LegalBasis.LEGITIMATE_INTEREST,
    )
    base.update(overrides)
    return RequestContext(**base)


def payroll_ctx(**overrides) -> RequestContext:
    base = dict(
        agent="payroll_agent",
        principal_role="hr_payroll_admin",
        data_subject="employee_sarah",
        requested_fields=["name", "salary", "bank_account"],
        purpose="monthly_payroll_processing",
        tool="get_employee",
        destination=Destination.INTERNAL_SYSTEM,
        legal_basis=LegalBasis.CONTRACT,
    )
    base.update(overrides)
    return RequestContext(**base)


# --- the core claim: purpose changes the answer ----------------------------

def test_salary_denied_for_directory_lookup(hr):
    result = hr.mediate(EMPLOYEE, directory_ctx(), audit=False)
    assert decisions_by_field(result)["salary"] is Decision.DENY
    assert "salary" not in result.data
    assert result.data["email"] == EMPLOYEE["email"]


def test_salary_allowed_for_payroll_run(hr):
    result = hr.mediate(EMPLOYEE, payroll_ctx(), audit=False)
    assert decisions_by_field(result)["salary"] is Decision.ALLOW
    assert result.data["salary"] == EMPLOYEE["salary"]


def test_same_field_same_record_opposite_outcomes(hr):
    denied = hr.mediate(EMPLOYEE, directory_ctx(), audit=False)
    allowed = hr.mediate(EMPLOYEE, payroll_ctx(), audit=False)
    assert decisions_by_field(denied)["salary"] is not decisions_by_field(allowed)["salary"]


def test_denial_reason_cites_purpose_not_the_default(hr):
    result = hr.mediate(EMPLOYEE, directory_ctx(), audit=False)
    salary = next(d for d in result.decisions if d.field == "salary")
    assert "purpose_necessity" in salary.restricted_by
    assert "employee_directory_lookup" in salary.reason


# --- guards may only restrict ----------------------------------------------

def test_consent_guard_overrides_an_explicit_grant(customer):
    """The IAM check passes; the privacy check does not."""
    ctx = RequestContext(
        agent="marketing_agent",
        principal_role="marketing_employee",
        data_subject="customer_29281",
        requested_fields=["name", "mobile_number"],
        purpose="fraud_investigation",
        destination=Destination.THIRD_PARTY_API,
        legal_basis=LegalBasis.CONSENT,
        consent_scopes=["marketing_communication"],
    )
    result = customer.mediate(CUSTOMER, ctx, audit=False)
    mobile = next(d for d in result.decisions if d.field == "mobile_number")

    assert mobile.matched_rule == "crm-access-broad"   # a rule DID grant it
    assert mobile.decision is Decision.DENY            # and was overridden
    assert "consent" in mobile.restricted_by
    assert result.data == {}


def test_compatible_secondary_use_is_permitted(customer):
    ctx = RequestContext(
        agent="customer_support_agent",
        principal_role="support_agent_human",
        requested_fields=["name"],
        purpose="support_case_resolution",
        destination=Destination.INTERNAL_MODEL,
        legal_basis=LegalBasis.CONSENT,
        consent_scopes=["service_communication"],   # compatible_with in the pack
    )
    result = customer.mediate(CUSTOMER, ctx, audit=False)
    assert decisions_by_field(result)["name"] is Decision.ALLOW


def test_missing_legal_basis_denies(hr):
    result = hr.mediate(EMPLOYEE, directory_ctx(legal_basis=None), audit=False)
    email = next(d for d in result.decisions if d.field == "email")
    assert email.decision is Decision.DENY
    assert "legal_basis" in email.restricted_by


def test_guards_never_loosen_a_denial(hr):
    """A permissive context cannot turn a policy default-deny into a release."""
    ctx = directory_ctx(requested_fields=["tax_number"])
    result = hr.mediate(EMPLOYEE, ctx, audit=False)
    assert decisions_by_field(result)["tax_number"] is Decision.DENY


# --- destination and retention ---------------------------------------------

def test_grant_scoped_to_a_destination_does_not_survive_a_different_one(hr):
    """The payroll rule is scoped to the internal payroll system by design."""
    ctx = payroll_ctx(destination=Destination.EXTERNAL_MODEL,
                      requested_fields=["bank_account"])
    bank = next(d for d in hr.mediate(EMPLOYEE, ctx, audit=False).decisions
                if d.field == "bank_account")
    assert bank.decision is Decision.DENY
    assert bank.matched_rule is None


def test_allow_is_downgraded_to_tokenise_when_leaving_the_organisation(customer):
    """An unrestricted grant still cannot send a raw identifier to a third party."""
    ctx = RequestContext(
        agent="marketing_agent",
        principal_role="marketing_employee",
        requested_fields=["mobile_number"],
        purpose="marketing_communication",
        destination=Destination.THIRD_PARTY_API,
        legal_basis=LegalBasis.CONSENT,
        consent_scopes=["marketing_communication"],
    )
    result = customer.mediate(CUSTOMER, ctx, audit=False)
    mobile = next(d for d in result.decisions if d.field == "mobile_number")

    assert mobile.matched_rule == "crm-access-broad"    # the rule said allow
    assert mobile.decision is Decision.TOKENISE         # the guard downgraded it
    assert "external_transfer" in mobile.restricted_by
    assert result.data["mobile_number"] != CUSTOMER["mobile_number"]


def test_salary_never_leaves_the_organisation(hr):
    ctx = payroll_ctx(destination=Destination.EXTERNAL_MODEL,
                      requested_fields=["salary"])
    result = hr.mediate(EMPLOYEE, ctx, audit=False)
    salary = next(d for d in result.decisions if d.field == "salary")
    assert salary.decision is Decision.DENY
    assert "external_transfer" in salary.restricted_by


def test_persistent_retention_blocked_for_no_persistence_field(hr):
    ctx = payroll_ctx(retention=Retention.LONG_TERM_MEMORY, requested_fields=["salary"])
    result = hr.mediate(EMPLOYEE, ctx, audit=False)
    salary = next(d for d in result.decisions if d.field == "salary")
    assert salary.decision is Decision.DENY
    assert "retention" in salary.restricted_by


def test_released_sensitive_field_carries_memory_obligations(hr):
    result = hr.mediate(EMPLOYEE, payroll_ctx(), audit=False)
    salary = next(d for d in result.decisions if d.field == "salary")
    assert Obligation.NO_LONG_TERM_MEMORY in salary.obligations
    assert Obligation.DELETE_AFTER_TASK in salary.obligations


# --- mechanics --------------------------------------------------------------

def test_more_specific_rule_wins():
    policy = Policy.model_validate({
        "name": "t", "default_decision": "deny", "require_legal_basis": False,
        "rules": [
            {"id": "broad", "match": {"agent": "a"}, "field": "*", "decision": "allow"},
            {"id": "narrow", "match": {"agent": "a", "purpose": "p"},
             "field": "salary", "decision": "mask"},
        ],
    })
    engine = PolicyEngine(policy)
    ctx = RequestContext(agent="a", purpose="p", requested_fields=["salary"])
    assert engine.evaluate(ctx)[0].matched_rule == "narrow"


def test_empty_requested_fields_defaults_to_whole_record(hr):
    ctx = payroll_ctx(requested_fields=[])
    result = hr.mediate(EMPLOYEE, ctx, audit=False)
    assert {d.field for d in result.decisions} == set(EMPLOYEE)


def test_denied_fields_are_omitted_not_nulled(hr):
    result = hr.mediate(EMPLOYEE, directory_ctx(), audit=False)
    assert "salary" not in result.data          # not present, not None


def test_audit_event_records_the_deciding_guard(hr):
    result = hr.mediate(EMPLOYEE, directory_ctx())
    event = result.audit
    assert event.policy == "popia_hr_v1"
    assert event.decisions["salary"] == "deny"
    assert event.restricted_by["salary"] == ["purpose_necessity"]
    assert event.purpose == "employee_directory_lookup"


def test_unknown_policy_name_raises():
    with pytest.raises(FileNotFoundError):
        PrivacyPlane.from_policy("no_such_pack")
