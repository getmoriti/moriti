"""
moriti privacy control plane -- demonstration.

Run:  python -m examples.demo_policy_engine

Four scenarios. The first two show the same field resolving differently on
purpose alone. The fourth shows a request that every IAM system would permit
and POPIA would not.
"""

from __future__ import annotations

import json

from moriti import (
    Destination,
    LegalBasis,
    PrivacyPlane,
    RequestContext,
    Retention,
)

RULE = "=" * 78
THIN = "-" * 78

EMPLOYEE_RECORD = {
    "name": "Sarah Ndlovu",
    "email": "sarah.ndlovu@example.co.za",
    "department": "Engineering",
    "job_title": "Staff Engineer",
    "employee_id": "EMP-4831",
    "salary": 1450000.00,
    "bank_account": "10000007792",
    "tax_number": "0100007263",
}

CUSTOMER_RECORD = {
    "name": "Thabo Mokoena",
    "email": "thabo.mokoena@example.co.za",
    "mobile_number": "0000000044",
    "account_number": "4055120099",
    "national_id": "0000000000000",
}


def show(title: str, question: str, result, record: dict) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")
    print(f"Question to the agent:\n  \"{question}\"\n")
    print("Agent receives:")
    print(json.dumps(result.data, indent=2, default=str))
    print("\nControl plane decisions:")
    print(result.explain())
    withheld = result.withheld
    if withheld:
        print(f"\nWithheld: {', '.join(withheld)}")


def scenario_directory_lookup(plane: PrivacyPlane) -> None:
    ctx = RequestContext(
        agent="hr_assistant",
        principal="employee_titus",
        principal_role="employee",
        data_subject="employee_sarah",
        resource="employee_profile",
        requested_fields=["name", "email", "salary"],
        purpose="employee_directory_lookup",
        tool="get_employee",
        destination=Destination.INTERNAL_MODEL,
        retention=Retention.EPHEMERAL,
        jurisdiction="ZA",
        legal_basis=LegalBasis.LEGITIMATE_INTEREST,
    )
    result = plane.mediate(EMPLOYEE_RECORD, ctx)
    show(
        "SCENARIO 1  --  HR Assistant, directory lookup",
        "What is Sarah's current salary and email address?",
        result,
        EMPLOYEE_RECORD,
    )


def scenario_payroll(plane: PrivacyPlane) -> None:
    ctx = RequestContext(
        agent="payroll_agent",
        principal="employee_nomsa",
        principal_role="hr_payroll_admin",
        data_subject="employee_sarah",
        resource="employee_profile",
        requested_fields=["name", "salary", "bank_account", "tax_number"],
        purpose="monthly_payroll_processing",
        tool="get_employee",
        destination=Destination.INTERNAL_SYSTEM,
        retention=Retention.EPHEMERAL,
        jurisdiction="ZA",
        legal_basis=LegalBasis.CONTRACT,
    )
    result = plane.mediate(EMPLOYEE_RECORD, ctx)
    show(
        "SCENARIO 2  --  Payroll Agent, payroll run  (same field, opposite answer)",
        "Process Sarah's salary for the March payroll run.",
        result,
        EMPLOYEE_RECORD,
    )


def scenario_expense(plane: PrivacyPlane) -> None:
    ctx = RequestContext(
        agent="finance_agent",
        principal="employee_123",
        principal_role="finance_clerk",
        data_subject="employee_sarah",
        resource="employee_profile",
        requested_fields=["name", "bank_account", "salary"],
        purpose="expense_reimbursement",
        tool="get_employee",
        destination=Destination.INTERNAL_SYSTEM,
        retention=Retention.EPHEMERAL,
        jurisdiction="ZA",
        legal_basis=LegalBasis.CONTRACT,
    )
    result = plane.mediate(EMPLOYEE_RECORD, ctx)
    show(
        "SCENARIO 3  --  Finance Agent, expense reimbursement",
        "Reimburse employee_123's approved travel expense.",
        result,
        EMPLOYEE_RECORD,
    )


def scenario_purpose_mismatch() -> None:
    plane = PrivacyPlane.from_policy("popia_customer_v1")
    ctx = RequestContext(
        agent="marketing_agent",
        principal="employee_marketing_07",
        principal_role="marketing_employee",     # genuinely holds CRM access
        data_subject="customer_29281",
        resource="customer_profile",
        requested_fields=["name", "mobile_number"],
        purpose="fraud_investigation",           # not what the consent covers
        tool="enrich_customer",
        destination=Destination.THIRD_PARTY_API,
        retention=Retention.PERSISTENT,
        jurisdiction="ZA",
        legal_basis=LegalBasis.CONSENT,
        consent_scopes=["marketing_communication"],
    )
    result = plane.mediate(CUSTOMER_RECORD, ctx)
    show(
        "SCENARIO 4  --  Marketing Agent  (where IAM and privacy diverge)",
        "Send this customer's mobile number to the enrichment API for the fraud case.",
        result,
        CUSTOMER_RECORD,
    )
    print(
        "\nNote: rule 'crm-access-broad' MATCHED and proposed ALLOW -- the principal\n"
        "does hold CRM access, so a traditional IAM check passes here. The guards\n"
        "then overrode it. That gap is the product thesis."
    )
    print(f"\n{THIN}\nAudit event (s24 evidence layer):\n{THIN}")
    print(result.audit.to_json())


def main() -> None:
    plane = PrivacyPlane.from_policy("popia_hr_v1")
    scenario_directory_lookup(plane)
    scenario_payroll(plane)
    scenario_expense(plane)
    scenario_purpose_mismatch()


if __name__ == "__main__":
    main()
