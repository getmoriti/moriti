"""
The privacy policy engine.

Two mechanisms combine, deliberately:

1. **Rules propose.** Explicit, ordered by specificity, first match wins. This is
   the familiar part -- "the payroll agent may read salary for payroll runs".

2. **Guards dispose.** Purpose necessity, consent compatibility and external
   transfer are evaluated *after* the rule and may only ever restrict the result,
   never loosen it.

The second mechanism is the reason this is not IAM. Take a marketing employee
who holds legitimate CRM access -- a rule would allow it -- but the assigned purpose is fraud investigation, the consent on file
covers marketing only, and the destination is a third party. The guards take a
proposed ALLOW down to DENY, and record which one did it. That is the decision
IAM structurally cannot reach, because purpose and consent are not in its model.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from moriti.context import Destination, LegalBasis, RequestContext, Retention
from moriti.decisions import Decision, Obligation, parse_decision

logger = logging.getLogger(__name__)

POLICY_DIR = Path(__file__).parent / "policies"
POLICY_PATH_ENV = "MORITI_POLICY_PATH"


def resolve_policy(ref: str | Path) -> Path:
    """Where a policy reference points.

    In order: a path to a YAML file (absolute, or relative to the working
    directory); a name looked up in each directory of $MORITI_POLICY_PATH
    (separated like $PATH); a name of a pack bundled with moriti. Your own
    packs win over bundled ones, so a deployment can say `policy: my_bank_v1`
    or `policy: ./policies/my_bank_v1.yaml` and never touch site-packages.
    """
    text = str(ref)
    candidate = Path(text)
    if candidate.suffix in {".yaml", ".yml"} or candidate.is_absolute() or os.sep in text or "/" in text:
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"No policy file at {candidate}")
    searched: list[str] = []
    user_dirs = [Path(p) for p in os.environ.get(POLICY_PATH_ENV, "").split(os.pathsep) if p]
    for directory in [*user_dirs, POLICY_DIR]:
        for ext in (".yaml", ".yml"):
            path = directory / f"{text}{ext}"
            if path.exists():
                return path
        searched.append(str(directory))
    raise FileNotFoundError(f"No policy pack named {text!r} in {', '.join(searched)}")

#: How restrictive each decision is. Guards may raise this, never lower it.
_RESTRICTIVENESS: dict[Decision, int] = {
    Decision.ALLOW: 0,
    Decision.DETOKENISE: 0,
    Decision.TOKENISE: 1,
    Decision.MASK: 2,
    Decision.REDACT: 3,
    Decision.FILTER: 3,
    Decision.REQUIRE_APPROVAL: 4,
    Decision.DENY: 5,
}

#: Context attributes a rule may match on.
_MATCHABLE = (
    "agent", "principal", "principal_role", "purpose", "task",
    "tool", "resource", "destination", "jurisdiction", "retention",
)


def _more_restrictive(a: Decision, b: Decision) -> Decision:
    return a if _RESTRICTIVENESS[a] >= _RESTRICTIVENESS[b] else b


class FieldDecision(BaseModel):
    """The outcome for one requested field."""

    field: str
    decision: Decision
    reason: str
    obligations: list[Obligation] = Field(default_factory=list)
    matched_rule: str | None = None
    #: Guards that restricted the rule's proposal, in the order they fired.
    restricted_by: list[str] = Field(default_factory=list)


class Rule(BaseModel):
    id: str
    match: dict[str, Any] = Field(default_factory=dict)
    field: Any = "*"
    decision: str
    reason: str = ""

    @property
    def specificity(self) -> int:
        """Rules that constrain more context win over vaguer ones."""
        score = sum(1 for k, v in self.match.items() if v not in (None, "*"))
        if self.field not in (None, "*"):
            score += 1
        return score

    def matches(self, ctx: RequestContext, field: str) -> bool:
        if not _value_matches(self.field, field):
            return False
        for key, expected in self.match.items():
            if key not in _MATCHABLE:
                logger.warning("Rule %s matches on unknown context key %r", self.id, key)
                return False
            actual = getattr(ctx, key, None)
            if hasattr(actual, "value"):       # unwrap enums
                actual = actual.value
            if not _value_matches(expected, actual):
                return False
        return True


def _value_matches(expected: Any, actual: Any) -> bool:
    """Wildcards, scalars and lists all behave as you'd expect."""
    if expected in (None, "*"):
        return True
    if isinstance(expected, (list, tuple, set)):
        return actual in expected
    return expected == actual


class PurposeSpec(BaseModel):
    """What an assigned purpose legitimately requires."""

    description: str = ""
    #: Data minimisation: fields genuinely needed to fulfil this purpose.
    necessary_fields: list[str] = Field(default_factory=list)
    #: Purposes this one is a compatible secondary use of.
    compatible_with: list[str] = Field(default_factory=list)


class FieldSpec(BaseModel):
    sensitivity: str = "normal"
    #: Never leaves the organisation, whatever a rule says.
    never_external: bool = False
    #: Released to external destinations only in tokenised form.
    tokenise_when_external: bool = False
    #: Must not be written to long-term memory or persistent storage.
    no_persistence: bool = False


class Policy(BaseModel):
    name: str
    version: str = "1"
    description: str = ""
    default_decision: str = "deny"
    #: Require an explicit legal basis before releasing anything.
    require_legal_basis: bool = True
    #: Deny every field when the request's purpose is not defined under `purposes`.
    #: On by default: set false only for a policy that deliberately leaves purposes open.
    require_known_purpose: bool = True
    purposes: dict[str, PurposeSpec] = Field(default_factory=dict)
    fields: dict[str, FieldSpec] = Field(default_factory=dict)
    rules: list[Rule] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str | Path) -> Policy:
        with open(path, encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))

    @classmethod
    def load(cls, ref: str | Path) -> Policy:
        """Load a policy by file path, by name from $MORITI_POLICY_PATH, or by bundled name."""
        return cls.from_yaml(resolve_policy(ref))

    def field_spec(self, field: str) -> FieldSpec:
        return self.fields.get(field, FieldSpec())


class PolicyEngine:
    """Evaluates a RequestContext against a Policy, field by field."""

    def __init__(self, policy: Policy):
        self.policy = policy
        # Highest specificity first; ties broken by declaration order.
        self._rules = sorted(
            enumerate(policy.rules),
            key=lambda pair: (-pair[1].specificity, pair[0]),
        )

    def evaluate(self, ctx: RequestContext) -> list[FieldDecision]:
        return [self._evaluate_field(ctx, f) for f in ctx.requested_fields]

    # -- rules propose -----------------------------------------------------

    def _propose(self, ctx: RequestContext, field: str) -> FieldDecision:
        for _, rule in self._rules:
            if rule.matches(ctx, field):
                decision, obligations = parse_decision(rule.decision)
                return FieldDecision(
                    field=field,
                    decision=decision,
                    reason=rule.reason or f"matched rule {rule.id}",
                    obligations=obligations,
                    matched_rule=rule.id,
                )
        decision, obligations = parse_decision(self.policy.default_decision)
        return FieldDecision(
            field=field,
            decision=decision,
            reason=f"no rule matched; policy default is {self.policy.default_decision}",
            obligations=obligations,
        )

    # -- guards dispose ----------------------------------------------------

    def _evaluate_field(self, ctx: RequestContext, field: str) -> FieldDecision:
        outcome = self._propose(ctx, field)
        spec = self.policy.field_spec(field)

        for guard in (
            self._guard_purpose_necessity,
            self._guard_consent,
            self._guard_legal_basis,
            self._guard_external_transfer,
            self._guard_retention,
        ):
            guard(ctx, field, spec, outcome)

        return outcome

    def _restrict(self, outcome: FieldDecision, to: Decision, guard: str, reason: str) -> None:
        """Apply a guard's finding. A guard may tighten the outcome, never loosen it."""
        current = _RESTRICTIVENESS[outcome.decision]
        proposed = _RESTRICTIVENESS[to]
        if proposed > current:
            outcome.decision = to
            outcome.reason = reason
            outcome.restricted_by.append(guard)
        elif proposed == current:
            # The guard independently reached the same outcome. It still fired, and
            # where the outcome was only a policy default its reason is the one
            # worth recording -- "not necessary for this purpose" explains the
            # denial; "no rule matched" merely restates the default.
            outcome.restricted_by.append(guard)
            if outcome.matched_rule is None:
                outcome.reason = reason

    def _guard_purpose_necessity(self, ctx, field, spec, outcome) -> None:
        """Data minimisation: a field not needed for the assigned purpose is not released.

        A purpose the policy does not define is denied when `require_known_purpose`
        is set (the default): the guard cannot assert necessity for a purpose it has
        never heard of, so a typo in a deployment must not read as "nothing to check".
        """
        purpose = self.policy.purposes.get(ctx.purpose)
        if purpose is None:
            if self.policy.require_known_purpose:
                self._restrict(
                    outcome, Decision.DENY, "purpose_necessity",
                    f"purpose '{ctx.purpose}' is not defined in policy '{self.policy.name}'",
                )
            return                                  # opted out: unmodelled purpose, nothing to assert
        if not purpose.necessary_fields:
            return                                  # purpose lists no fields; nothing to assert
        if field in purpose.necessary_fields:
            return
        self._restrict(
            outcome, Decision.DENY, "purpose_necessity",
            f"'{field}' is not necessary for the assigned purpose '{ctx.purpose}'",
        )

    def _guard_consent(self, ctx, field, spec, outcome) -> None:
        """Where consent is the basis, the purpose must actually fall within it."""
        if ctx.legal_basis is not LegalBasis.CONSENT:
            return
        if ctx.consent_covers(ctx.purpose):
            return
        purpose = self.policy.purposes.get(ctx.purpose)
        compatible = purpose.compatible_with if purpose else []
        if any(ctx.consent_covers(p) for p in compatible):
            return                                  # compatible secondary use
        scopes = ", ".join(ctx.consent_scopes) or "none on file"
        self._restrict(
            outcome, Decision.DENY, "consent",
            f"consent does not cover purpose '{ctx.purpose}' (consented: {scopes})",
        )

    def _guard_legal_basis(self, ctx, field, spec, outcome) -> None:
        if not self.policy.require_legal_basis or ctx.legal_basis is not None:
            return
        self._restrict(
            outcome, Decision.DENY, "legal_basis",
            "no legal basis declared for processing this personal data",
        )

    def _guard_external_transfer(self, ctx, field, spec, outcome) -> None:
        """Field-level limits on data leaving the organisation."""
        if not ctx.destination.is_external:
            return
        if spec.never_external:
            self._restrict(
                outcome, Decision.DENY, "external_transfer",
                f"'{field}' may never be sent to {ctx.destination.value}",
            )
        elif spec.tokenise_when_external:
            self._restrict(
                outcome, Decision.TOKENISE, "external_transfer",
                f"'{field}' must be tokenised before reaching {ctx.destination.value}",
            )

    def _guard_retention(self, ctx, field, spec, outcome) -> None:
        """Task-necessary data does not silently become persistent agent memory."""
        if not outcome.decision.releases_value:
            return
        persistent = {Retention.LONG_TERM_MEMORY, Retention.PERSISTENT}
        if spec.no_persistence and ctx.retention in persistent:
            self._restrict(
                outcome, Decision.DENY, "retention",
                f"'{field}' may not be retained as {ctx.retention.value}",
            )
        elif spec.no_persistence or ctx.destination is Destination.AGENT_MEMORY:
            for ob in (Obligation.NO_LONG_TERM_MEMORY, Obligation.DELETE_AFTER_TASK):
                if ob not in outcome.obligations:
                    outcome.obligations.append(ob)
