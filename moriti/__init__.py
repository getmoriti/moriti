"""
moriti privacy control plane.

Sits above the existing data plane (a data plane such as a tokenisation vault)
and decides what a caller may do with personal data, rather than merely how to
obscure it. The data plane answers "how do I mask this?"; the control plane
answers "should this agent receive this person's field, for this purpose, headed
to this destination, retained this long?"

Typical use::

    from moriti import PrivacyPlane, RequestContext

    plane = PrivacyPlane.from_policy("popia_hr_v1")
    result = plane.mediate(record, RequestContext(...))
    result.data      # what the agent is allowed to receive
    result.audit     # the evidence record
"""

from moriti.context import (
    Destination,
    LegalBasis,
    RequestContext,
    Retention,
)
from moriti.decisions import Decision, Obligation
from moriti.plane import MediationResult, PrivacyPlane
from moriti.policy import FieldDecision, Policy, PolicyEngine

__all__ = [
    "Decision",
    "Destination",
    "FieldDecision",
    "LegalBasis",
    "MediationResult",
    "Obligation",
    "Policy",
    "PolicyEngine",
    "PrivacyPlane",
    "RequestContext",
    "Retention",
]

__version__ = "0.1.0rc1"
