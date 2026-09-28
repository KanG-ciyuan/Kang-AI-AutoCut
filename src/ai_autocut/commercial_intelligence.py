"""Commercial Intelligence v1: auditable Commercial Strategy candidates.

Why this exists
---------------
Commercial Strategy v1 records what one piece argues, but it is a *decision* document:
it holds the variants that were chosen. Nothing in the repository recorded the step before
the choice - why these candidates were on the table at all, which consumer belief each one
rests on, and which commercially attractive ideas the material cannot currently support.

This contract is that missing step. It is the plan's reasoning made reviewable:

    WHAT MAY THE CONSUMER CARE ABOUT?      consumer_hypotheses
      x WHAT IS TRUE ABOUT THE PRODUCT?    product_facts
      x WHAT CAN THE FOOTAGE PROVE?        visual_evidence_boundary
      x WHAT ARE WE ALLOWED TO CLAIM?      claim_boundary
                     =
              STRATEGY CANDIDATES          candidates
                     +
        IDEAS BLOCKED BY MISSING EVIDENCE  blocked_opportunities

What this module is, and is not
-------------------------------
It is the **contract and the deterministic half**: parse, validate, derive, render. It is
not the intelligence. Nothing here invents a consumer belief, a persuasion job, a hook, a
rationale or a candidate: those arrive as declared input, and this module decides whether
they may stand and what they mechanically imply.

The boundary is explicit, because a passing validation must never be read as the system
having generated a strategy:

===============================  ===============================================
SYSTEM CONTRACT / VALIDATION     AGENT INTELLIGENCE / AUTHORING
===============================  ===============================================
shape and enum validation        which consumer beliefs are worth hypothesising
reference integrity               which persuasion job a version is doing
viability rules (below)           the hook strategy and the copy direction
deterministic unavailability      the rationale for choosing an angle
deterministic unlock analysis     spotting an opportunity worth pursuing
===============================  ===============================================

There is no candidate-generation entry point in this module, and that is deliberate.

Viability is checked, not asserted
----------------------------------
A candidate is viable only if every layer supports it:

* it cites at least one declared consumer hypothesis;
* every Product Fact it rests on is permitted by the bound fact document;
* every Visual Evidence reference it cites is declared **and PRESENT** - so a
  ``direction adjustable`` fact whose evidence is ABSENT cannot be presented as a
  demonstrated result;
* every claim it uses is ``ALLOWED``: a ``CONDITIONAL`` claim used as though its condition
  held is refused, and a ``FORBIDDEN`` claim can never be used;
* and the facts and evidence it cites must actually cover the claims it uses, so neither
  list is decoration.

A commercially attractive idea that cannot pass those checks is not deleted. It belongs in
``blocked_opportunities``, where the module derives *why* it is unavailable and *what would
unlock it* - the honest answer to "what footage would make a stronger strategy possible?"
rather than "I cannot use this".

No winner, no fake precision
----------------------------
This contract has **no numeric field at all**, and no ranking, score, confidence or
expected-performance field exists to be filled in. There is currently no real performance
data behind such a number, so the document offers candidates and says plainly that it does
not know which would perform best. Selection is a later human, supervisor or experiment
decision. Candidates are rendered ordered by id, which - as ``hook_decision.json`` already
records about its own ordering - is not a ranking.

Consumer hypotheses are not market facts
----------------------------------------
V1 performs no external market research, so a hypothesis must never be presented as
verified market knowledge. Support reuses the repository's existing
:class:`~src.ai_autocut.candidate_evidence.ClaimSupport` vocabulary unchanged -
``DIRECT`` / ``CONTEXTUAL`` / ``INFERRED`` - and the strongest level is citable only:
``DIRECT`` **requires** a bound basis reference, and any weaker level **must not** name
one. An inference therefore cannot dress itself up as a verified finding.

Status
------
CONTRACT_ONLY and NOT_WIRED, following ``planning_evidence.v1`` and Commercial Strategy v1:
the shape is defined, validated and tested, and nothing in production writes or reads one
yet. No producer is registered, no stage requires it, and the frozen production chain is
untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Callable, Mapping, Sequence, TypeVar

from .artifact_reference import (
    ArtifactReference,
    ArtifactReferenceError,
    parse_artifact_reference,
    validate_logical_ref,
    validate_sha256,
)
from .commercial_strategy import (
    ClaimBoundary,
    CommercialStrategyContractError,
    EvidenceBoundary,
    ProductFactBinding,
    StrategyAuthor,
    StrategyProvenance,
    parse_claim_boundary,
    parse_evidence_boundary,
    parse_product_facts,
)
from .intervention_ledger import ACTORS


SCHEMA_VERSION = "commercial_intelligence.v1"

#: Canonical workspace-relative location suggested for this artifact.
CANONICAL_REF = "strategy/commercial_intelligence.json"

#: Honest implementation state. The shape is defined and validated; nothing in production
#: writes or reads one yet, and no producer is registered for the artifact.
IMPLEMENTATION = "CONTRACT_ONLY"

#: Wiring status, in the production chain manifest's vocabulary.
WIRING_STATUS = "NOT_WIRED"

#: The project's stable default for ordinary e-commerce commercial jobs. Recording the
#: source beside the value is what keeps a default from passing as a decision.
DEFAULT_OBJECTIVE = "DIRECT_CONVERSION"

#: What the artifact records when the job states no platform. A platform is not invented
#: here: the validated production scope happens to be short-form vertical commerce, but
#: that is a project fact, not a universal truth, so it is not baked into the contract.
UNSPECIFIED_PLATFORM = "UNSPECIFIED"

#: Where a context value came from. Same idiom as ``spoken_duration.RateObservation``,
#: which records ``rate_source`` beside the rate it derived.
CONTEXT_SOURCES = ("DECLARED", "DEFAULTED", "UNSPECIFIED")

#: Hypothesis support. Deliberately identical to ``candidate_evidence.ClaimSupport`` so the
#: repository keeps one vocabulary for "how directly is this backed", rather than a second
#: taxonomy for the same idea. Asserted equal to that enum by test.
HYPOTHESIS_SUPPORT = ("DIRECT", "CONTEXTUAL", "INFERRED")

#: Why a claim is unavailable. Derived from the claim and evidence boundaries by
#: :func:`claim_availability`; never free text, and never declared by hand without being
#: cross-checked against the derivation.
BLOCKING_CODES = (
    "CLAIM_NOT_DECLARED",
    "CLAIM_FORBIDDEN",
    "CONDITIONAL_EVIDENCE_ABSENT",
    "CONDITIONAL_NOT_MECHANICALLY_RESOLVED",
)

#: A logical identifier: letters, digits, and the separators ``. _ : -``.
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

_DOCUMENT_KEYS = (
    "schema_version",
    "candidate_set_id",
    "context",
    "product_facts",
    "visual_evidence_boundary",
    "claim_boundary",
    "consumer_hypotheses",
    "candidates",
    "blocked_opportunities",
    "provenance",
)
_CONTEXT_KEYS = (
    "product",
    "market",
    "platform",
    "platform_source",
    "objective",
    "objective_source",
)
_PRODUCT_KEYS = ("name",)
_HYPOTHESIS_KEYS = ("hypothesis_id", "statement", "support", "basis_ref")
_CANDIDATE_KEYS = (
    "candidate_id",
    "persuasion_job",
    "hypothesis_refs",
    "product_fact_refs",
    "evidence_refs",
    "claims_used",
    "hook_strategy",
    "copy_direction",
    "cta_direction",
    "rationale",
    "limitations",
)
_BLOCKED_KEYS = (
    "opportunity_id",
    "statement",
    "persuasion_job",
    "claim_ref",
    "blocked_by",
    "missing",
    "next_action",
)
_PROVENANCE_KEYS = ("authored_by", "based_on")
_AUTHOR_KEYS = ("actor", "producer_id")


class CommercialIntelligenceContractError(ValueError):
    """Raised when a candidate set cannot be consumed safely."""


# --------------------------------------------------------------------------- plumbing
#
# These four helpers are per-module plumbing, which is the existing convention here:
# artifact_reference, editing_plan and candidate_evidence each carry their own copy. The
# domain contracts - facts, evidence, claims - are *imported* instead, so those have one
# implementation rather than four.


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise CommercialIntelligenceContractError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise CommercialIntelligenceContractError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise CommercialIntelligenceContractError(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise CommercialIntelligenceContractError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or _TOKEN_PATTERN.fullmatch(value) is None:
        raise CommercialIntelligenceContractError(
            f"{label} must be a logical identifier matching {_TOKEN_PATTERN.pattern!r}"
        )
    return value


def _line(value: object, label: str) -> str:
    """One line of decision basis, never a deliberation transcript.

    Rationale, strategy direction and every statement in this contract are single-line
    text. A block of multi-line prose is how hidden reasoning or a pasted model transcript
    would enter an audit artifact, so the shape refuses it rather than trusting a length
    limit.
    """

    if not isinstance(value, str) or not value.strip():
        raise CommercialIntelligenceContractError(f"{label} must be a non-empty string")
    if "\n" in value or "\r" in value:
        raise CommercialIntelligenceContractError(
            f"{label} must be a single line; a decision basis is one line, not a "
            "deliberation transcript"
        )
    return value


def _line_list(
    value: object, label: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    items = _array(value, label)
    if not items and not allow_empty:
        raise CommercialIntelligenceContractError(f"{label} must not be empty")
    return tuple(_line(raw, f"{label}[{index}]") for index, raw in enumerate(items))


def _token_list(
    value: object, label: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    items = _array(value, label)
    if not items and not allow_empty:
        raise CommercialIntelligenceContractError(f"{label} must not be empty")
    return tuple(_token(raw, f"{label}[{index}]") for index, raw in enumerate(items))


def _distinct(values: Sequence[str], label: str) -> None:
    seen: set[str] = set()
    repeats: list[str] = []
    for value in values:
        if value in seen:
            repeats.append(value)
        seen.add(value)
    if repeats:
        raise CommercialIntelligenceContractError(
            f"{label} must not repeat: {', '.join(sorted(set(repeats)))}"
        )


def _optional_reference(value: object, label: str) -> ArtifactReference | None:
    """Parse one ``{ref, sha256}`` reference, reported as this contract's own error.

    Wrapped rather than allowed to escape: a caller of this contract should be able to
    catch one error type, and a malformed citation is a contract rejection either way.
    """

    if value is None:
        return None
    try:
        return parse_artifact_reference(value, label=label)
    except ArtifactReferenceError as exc:
        raise CommercialIntelligenceContractError(str(exc)) from exc


_T = TypeVar("_T")


def _parse_shared(parser: Callable[[object], _T], document: object) -> _T:
    """Run a boundary-block parser owned by the shared contract family.

    The parser belongs to ``commercial_strategy`` because the block is that contract's
    shape; but a malformed block inside a candidate set is a rejection of *this* document,
    so the error is reported as one this module's callers already catch.
    """

    try:
        return parser(document)
    except CommercialStrategyContractError as exc:
        raise CommercialIntelligenceContractError(str(exc)) from exc


# ------------------------------------------------------------------ job context


@dataclass(frozen=True)
class JobContext:
    """The job facts the candidate set reasons over, with the source of each value.

    Only ``product`` and ``market`` are genuinely required from a person. ``objective``
    falls back to the project default and ``platform`` is left ``UNSPECIFIED`` rather than
    invented, and either may be overridden. Recording ``objective_source`` /
    ``platform_source`` is what stops an assumed value from reading as a decision.
    """

    product_name: str
    market: str
    platform: str
    platform_source: str
    objective: str
    objective_source: str

    def __post_init__(self) -> None:
        _line(self.product_name, "context.product.name")
        _token(self.market, "context.market")
        _token(self.platform, "context.platform")
        _token(self.objective, "context.objective")
        for field, value in (
            ("context.platform_source", self.platform_source),
            ("context.objective_source", self.objective_source),
        ):
            if value not in CONTEXT_SOURCES:
                raise CommercialIntelligenceContractError(
                    f"{field} must be one of: {', '.join(CONTEXT_SOURCES)}"
                )
        # A stated platform cannot be the unspecified placeholder, and an unspecified one
        # must say so rather than claiming to have been declared.
        if self.platform_source == "UNSPECIFIED":
            if self.platform != UNSPECIFIED_PLATFORM:
                raise CommercialIntelligenceContractError(
                    "context.platform_source is UNSPECIFIED, so context.platform must be "
                    f"{UNSPECIFIED_PLATFORM!r}"
                )
        elif self.platform == UNSPECIFIED_PLATFORM:
            raise CommercialIntelligenceContractError(
                f"context.platform {UNSPECIFIED_PLATFORM!r} must be recorded with "
                "platform_source UNSPECIFIED"
            )
        if self.objective_source == "DEFAULTED" and self.objective != DEFAULT_OBJECTIVE:
            raise CommercialIntelligenceContractError(
                f"only {DEFAULT_OBJECTIVE!r} may be recorded as DEFAULTED; a different "
                "objective must be declared"
            )
        if self.objective_source == "UNSPECIFIED":
            raise CommercialIntelligenceContractError(
                "an objective is always resolvable: it is either declared or defaulted"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "product": {"name": self.product_name},
            "market": self.market,
            "platform": self.platform,
            "platform_source": self.platform_source,
            "objective": self.objective,
            "objective_source": self.objective_source,
        }


def resolve_context(
    product_name: object,
    market: object,
    *,
    platform: object | None = None,
    objective: object | None = None,
) -> JobContext:
    """Build the job context from minimum human input.

    Two values are required - the product and the market - because nothing in the
    repository can derive either. ``objective`` defaults to the project's stable default
    for commerce, and ``platform`` is recorded as UNSPECIFIED when the job does not state
    one. Neither default is presented as knowledge.
    """

    if platform is None or (isinstance(platform, str) and not platform.strip()):
        resolved_platform, platform_source = UNSPECIFIED_PLATFORM, "UNSPECIFIED"
    else:
        resolved_platform, platform_source = platform, "DECLARED"
    if objective is None or (isinstance(objective, str) and not objective.strip()):
        resolved_objective, objective_source = DEFAULT_OBJECTIVE, "DEFAULTED"
    else:
        resolved_objective, objective_source = objective, "DECLARED"
    return JobContext(
        product_name=product_name,  # type: ignore[arg-type]
        market=market,  # type: ignore[arg-type]
        platform=resolved_platform,  # type: ignore[arg-type]
        platform_source=platform_source,
        objective=resolved_objective,  # type: ignore[arg-type]
        objective_source=objective_source,
    )


# ------------------------------------------------------- consumer hypotheses


@dataclass(frozen=True)
class ConsumerHypothesis:
    """A belief about the buyer that the candidate set is reasoning from.

    It is not a market fact. ``support`` says how directly it is backed, using the
    repository's existing support vocabulary: ``DIRECT`` requires a bound citation and the
    weaker levels must not name one, so an inference cannot present itself as a finding.
    """

    hypothesis_id: str
    statement: str
    support: str
    basis_ref: ArtifactReference | None = None

    def __post_init__(self) -> None:
        _token(self.hypothesis_id, "hypothesis.hypothesis_id")
        _line(self.statement, "hypothesis.statement")
        if self.support not in HYPOTHESIS_SUPPORT:
            raise CommercialIntelligenceContractError(
                f"hypothesis.support must be one of: {', '.join(HYPOTHESIS_SUPPORT)}"
            )
        if self.support == "DIRECT" and self.basis_ref is None:
            raise CommercialIntelligenceContractError(
                f"hypothesis {self.hypothesis_id!r} claims DIRECT support, so it must cite "
                "the basis it rests on; an inference may not be presented as verified"
            )
        if self.support != "DIRECT" and self.basis_ref is not None:
            raise CommercialIntelligenceContractError(
                f"hypothesis {self.hypothesis_id!r} has {self.support} support and must not "
                "name a basis reference; only DIRECT support may cite one"
            )

    @property
    def is_verified(self) -> bool:
        """True only when a bound citation actually backs this hypothesis."""

        return self.support == "DIRECT" and self.basis_ref is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "support": self.support,
            "basis_ref": None if self.basis_ref is None else self.basis_ref.as_dict(),
        }


# ---------------------------------------------------------- strategy candidates


@dataclass(frozen=True)
class StrategyCandidate:
    """One commercially viable strategy the evidence can actually support."""

    candidate_id: str
    persuasion_job: str
    hypothesis_refs: tuple[str, ...]
    product_fact_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    claims_used: tuple[str, ...]
    hook_strategy: str
    copy_direction: tuple[str, ...]
    cta_direction: str
    rationale: str
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _token(self.candidate_id, "candidate.candidate_id")
        _token(self.persuasion_job, "candidate.persuasion_job")
        for field, value in (
            ("candidate.hypothesis_refs", self.hypothesis_refs),
            ("candidate.product_fact_refs", self.product_fact_refs),
            ("candidate.evidence_refs", self.evidence_refs),
            ("candidate.claims_used", self.claims_used),
        ):
            _distinct(value, field)
        _line(self.hook_strategy, "candidate.hook_strategy")
        _line(self.cta_direction, "candidate.cta_direction")
        _line(self.rationale, "candidate.rationale")
        object.__setattr__(
            self,
            "copy_direction",
            _line_list(list(self.copy_direction), "candidate.copy_direction"),
        )
        object.__setattr__(
            self,
            "limitations",
            _line_list(
                list(self.limitations), "candidate.limitations", allow_empty=True
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "persuasion_job": self.persuasion_job,
            "hypothesis_refs": list(self.hypothesis_refs),
            "product_fact_refs": list(self.product_fact_refs),
            "evidence_refs": list(self.evidence_refs),
            "claims_used": list(self.claims_used),
            "hook_strategy": self.hook_strategy,
            "copy_direction": list(self.copy_direction),
            "cta_direction": self.cta_direction,
            "rationale": self.rationale,
            "limitations": list(self.limitations),
        }


# ------------------------------------------------------ blocked opportunities


@dataclass(frozen=True)
class ClaimAvailability:
    """What the boundaries mechanically say about one claim.

    Derived, never declared: the two boundaries already determine this, and a document that
    could assert it freely could assert its way around them.
    """

    claim_id: str
    state: str | None
    blocked_by: str | None
    missing: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.state == "ALLOWED"

    def as_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "state": self.state,
            "blocked_by": self.blocked_by,
            "missing": list(self.missing),
        }


def claim_availability(
    claim_id: str,
    claim_boundary: ClaimBoundary,
    evidence_boundary: EvidenceBoundary,
) -> ClaimAvailability:
    """Derive why a claim may or may not be used, from the boundaries alone."""

    state = claim_boundary.state_of(claim_id)
    if state is None:
        return ClaimAvailability(claim_id, None, "CLAIM_NOT_DECLARED", ())
    if state == "ALLOWED":
        return ClaimAvailability(claim_id, state, None, ())
    if state == "FORBIDDEN":
        return ClaimAvailability(claim_id, state, "CLAIM_FORBIDDEN", ())
    # CONDITIONAL: only an ABSENT prerequisite is a mechanical blocker. If the required
    # evidence is present, or none was named, then promoting the claim is a decision for
    # whoever owns the claim boundary - this module will not promote it for them.
    requires = next(
        (
            claim.requires_evidence_ref
            for claim in claim_boundary.conditional
            if claim.claim_id == claim_id
        ),
        None,
    )
    if requires is None:
        return ClaimAvailability(
            claim_id, state, "CONDITIONAL_NOT_MECHANICALLY_RESOLVED", ()
        )
    presence = evidence_boundary.presence_of(requires)
    if presence == "PRESENT":
        return ClaimAvailability(
            claim_id, state, "CONDITIONAL_NOT_MECHANICALLY_RESOLVED", ()
        )
    return ClaimAvailability(claim_id, state, "CONDITIONAL_EVIDENCE_ABSENT", (requires,))


@dataclass(frozen=True)
class BlockedOpportunity:
    """A commercially interesting strategy the material cannot currently support.

    It is not a soft claim and not a to-do for this repository: it records what is missing
    and what would unlock the idea, so a later decision can be about acquiring evidence
    rather than about quietly lowering the evidence rules.
    """

    opportunity_id: str
    statement: str
    persuasion_job: str
    claim_ref: str
    blocked_by: str
    missing: tuple[str, ...]
    next_action: str

    def __post_init__(self) -> None:
        _token(self.opportunity_id, "blocked.opportunity_id")
        _line(self.statement, "blocked.statement")
        _token(self.persuasion_job, "blocked.persuasion_job")
        _token(self.claim_ref, "blocked.claim_ref")
        if self.blocked_by not in BLOCKING_CODES:
            raise CommercialIntelligenceContractError(
                f"blocked.blocked_by must be one of: {', '.join(BLOCKING_CODES)}"
            )
        _distinct(self.missing, "blocked.missing")
        _line(self.next_action, "blocked.next_action")

    def as_dict(self) -> dict[str, object]:
        return {
            "opportunity_id": self.opportunity_id,
            "statement": self.statement,
            "persuasion_job": self.persuasion_job,
            "claim_ref": self.claim_ref,
            "blocked_by": self.blocked_by,
            "missing": list(self.missing),
            "next_action": self.next_action,
        }


# --------------------------------------------------------------- the document


@dataclass(frozen=True)
class CommercialIntelligence:
    """One validated candidate set: the reasoning, not the choice."""

    candidate_set_id: str
    context: JobContext
    product_facts: ProductFactBinding
    visual_evidence_boundary: EvidenceBoundary
    claim_boundary: ClaimBoundary
    consumer_hypotheses: tuple[ConsumerHypothesis, ...]
    candidates: tuple[StrategyCandidate, ...]
    blocked_opportunities: tuple[BlockedOpportunity, ...]
    provenance: StrategyProvenance

    def __post_init__(self) -> None:
        _token(self.candidate_set_id, "candidate_set_id")
        if not self.consumer_hypotheses:
            raise CommercialIntelligenceContractError(
                "consumer_hypotheses must not be empty; a candidate set reasons from at "
                "least one declared belief"
            )
        _distinct(
            [item.hypothesis_id for item in self.consumer_hypotheses],
            "consumer_hypotheses.hypothesis_id",
        )
        if not self.candidates:
            raise CommercialIntelligenceContractError(
                "candidates must not be empty; use blocked_opportunities for ideas the "
                "material cannot support"
            )
        _distinct(
            [item.candidate_id for item in self.candidates], "candidates.candidate_id"
        )
        _distinct(
            [item.opportunity_id for item in self.blocked_opportunities],
            "blocked_opportunities.opportunity_id",
        )
        # Ordered by id for deterministic rendering. Per hook_decision.json, ordering by id
        # is not a ranking and no ranking is expressed anywhere in this contract.
        object.__setattr__(
            self,
            "consumer_hypotheses",
            tuple(sorted(self.consumer_hypotheses, key=lambda item: item.hypothesis_id)),
        )
        object.__setattr__(
            self,
            "candidates",
            tuple(sorted(self.candidates, key=lambda item: item.candidate_id)),
        )
        object.__setattr__(
            self,
            "blocked_opportunities",
            tuple(
                sorted(self.blocked_opportunities, key=lambda item: item.opportunity_id)
            ),
        )
        self._assert_candidates_are_supported()
        self._assert_blocked_opportunities_are_actually_blocked()
        self._assert_provenance_binds_the_declared_artifacts()

    # ------------------------------------------------------------------ invariants

    def _assert_candidates_are_supported(self) -> None:
        """Every layer must support a candidate: hypothesis, fact, evidence, claim."""

        hypothesis_ids = {item.hypothesis_id for item in self.consumer_hypotheses}
        boundary = self.visual_evidence_boundary
        for candidate in self.candidates:
            label = f"candidate {candidate.candidate_id!r}"
            for hypothesis_id in candidate.hypothesis_refs:
                if hypothesis_id not in hypothesis_ids:
                    raise CommercialIntelligenceContractError(
                        f"{label} cites hypothesis {hypothesis_id!r}, which "
                        "consumer_hypotheses does not declare"
                    )
            for fact_ref in candidate.product_fact_refs:
                if not self.product_facts.permits(fact_ref):
                    raise CommercialIntelligenceContractError(
                        f"{label} rests on Product Fact {fact_ref!r}, which product_facts "
                        "does not permit"
                    )
            for evidence_id in candidate.evidence_refs:
                presence = boundary.presence_of(evidence_id)
                if presence is None:
                    raise CommercialIntelligenceContractError(
                        f"{label} cites evidence {evidence_id!r}, which "
                        "visual_evidence_boundary does not declare"
                    )
                if presence != "PRESENT":
                    raise CommercialIntelligenceContractError(
                        f"{label} cites evidence {evidence_id!r}, which the material "
                        f"records as {presence}; a viable candidate may not lean on "
                        "evidence the footage does not have"
                    )
            for claim_id in candidate.claims_used:
                availability = claim_availability(
                    claim_id, self.claim_boundary, boundary
                )
                if availability.available:
                    claim = next(
                        item
                        for item in self.claim_boundary.allowed
                        if item.claim_id == claim_id
                    )
                    # Both lists must actually cover the claim, so neither is decoration.
                    if claim.product_fact_ref not in candidate.product_fact_refs:
                        raise CommercialIntelligenceContractError(
                            f"{label} uses claim {claim_id!r} but does not cite Product "
                            f"Fact {claim.product_fact_ref!r} that the claim rests on"
                        )
                    if (
                        claim.evidence_ref is not None
                        and claim.evidence_ref not in candidate.evidence_refs
                    ):
                        raise CommercialIntelligenceContractError(
                            f"{label} uses claim {claim_id!r} but does not cite evidence "
                            f"{claim.evidence_ref!r} that the claim rests on"
                        )
                    continue
                if availability.blocked_by == "CLAIM_FORBIDDEN":
                    raise CommercialIntelligenceContractError(
                        f"{label} uses forbidden claim {claim_id!r}; a forbidden claim may "
                        "never be used by a candidate"
                    )
                if availability.blocked_by == "CONDITIONAL_EVIDENCE_ABSENT":
                    raise CommercialIntelligenceContractError(
                        f"{label} uses conditional claim {claim_id!r} as though its "
                        f"condition held; evidence {', '.join(availability.missing)} is "
                        "ABSENT"
                    )
                if availability.blocked_by == "CONDITIONAL_NOT_MECHANICALLY_RESOLVED":
                    raise CommercialIntelligenceContractError(
                        f"{label} uses conditional claim {claim_id!r}, which the claim "
                        "boundary has not promoted to ALLOWED; a candidate may not promote "
                        "it on the boundary's behalf"
                    )
                raise CommercialIntelligenceContractError(
                    f"{label} uses claim {claim_id!r}, which claim_boundary does not declare"
                )

    def _assert_blocked_opportunities_are_actually_blocked(self) -> None:
        """A blocked opportunity must be blocked for the reason the boundaries give."""

        for opportunity in self.blocked_opportunities:
            availability = claim_availability(
                opportunity.claim_ref,
                self.claim_boundary,
                self.visual_evidence_boundary,
            )
            label = f"blocked opportunity {opportunity.opportunity_id!r}"
            if availability.available:
                raise CommercialIntelligenceContractError(
                    f"{label} is recorded as blocked, but claim "
                    f"{opportunity.claim_ref!r} is ALLOWED; an idea the claim boundary "
                    "permits belongs in candidates, not in blocked_opportunities"
                )
            if opportunity.blocked_by != availability.blocked_by:
                raise CommercialIntelligenceContractError(
                    f"{label} states blocked_by {opportunity.blocked_by!r}, but the "
                    f"boundaries give {availability.blocked_by!r}"
                )
            undeclared = sorted(set(availability.missing) - set(opportunity.missing))
            if undeclared:
                raise CommercialIntelligenceContractError(
                    f"{label} does not declare the derived missing item(s): "
                    + ", ".join(undeclared)
                )

    def _assert_provenance_binds_the_declared_artifacts(self) -> None:
        for label, reference in (
            ("product_facts", self.product_facts.reference),
            ("visual_evidence_boundary", self.visual_evidence_boundary.reference),
        ):
            declared = self.provenance.reference_for(reference.ref)
            if declared is None:
                raise CommercialIntelligenceContractError(
                    f"provenance.based_on does not name {label}.ref {reference.ref!r}"
                )
            if declared.sha256 != reference.sha256:
                raise CommercialIntelligenceContractError(
                    f"provenance.based_on disagrees with {label}.sha256 for "
                    f"{reference.ref!r}"
                )

    # ---------------------------------------------------------------------- output

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "candidate_set_id": self.candidate_set_id,
            "context": self.context.as_dict(),
            "product_facts": self.product_facts.as_dict(),
            "visual_evidence_boundary": self.visual_evidence_boundary.as_dict(),
            "claim_boundary": self.claim_boundary.as_dict(),
            "consumer_hypotheses": [
                item.as_dict() for item in self.consumer_hypotheses
            ],
            "candidates": [item.as_dict() for item in self.candidates],
            "blocked_opportunities": [
                item.as_dict() for item in self.blocked_opportunities
            ],
            "provenance": self.provenance.as_dict(),
        }

    def candidate(self, candidate_id: str) -> StrategyCandidate:
        for item in self.candidates:
            if item.candidate_id == candidate_id:
                return item
        raise CommercialIntelligenceContractError(
            f"unknown candidate_id {candidate_id!r}"
        )

    def hypothesis(self, hypothesis_id: str) -> ConsumerHypothesis:
        for item in self.consumer_hypotheses:
            if item.hypothesis_id == hypothesis_id:
                return item
        raise CommercialIntelligenceContractError(
            f"unknown hypothesis_id {hypothesis_id!r}"
        )


def parse_commercial_intelligence(document: object) -> CommercialIntelligence:
    """Parse and fully validate one candidate set. Fail closed, never repair."""

    mapping = _object(document, "commercial intelligence")
    _exact_keys(mapping, _DOCUMENT_KEYS, "commercial intelligence")
    if mapping["schema_version"] != SCHEMA_VERSION:
        raise CommercialIntelligenceContractError(
            f"schema_version must be {SCHEMA_VERSION!r}"
        )

    raw_context = _object(mapping["context"], "context")
    _exact_keys(raw_context, _CONTEXT_KEYS, "context")
    product = _object(raw_context["product"], "context.product")
    _exact_keys(product, _PRODUCT_KEYS, "context.product")
    context = JobContext(
        product_name=product["name"],  # type: ignore[arg-type]
        market=raw_context["market"],  # type: ignore[arg-type]
        platform=raw_context["platform"],  # type: ignore[arg-type]
        platform_source=raw_context["platform_source"],  # type: ignore[arg-type]
        objective=raw_context["objective"],  # type: ignore[arg-type]
        objective_source=raw_context["objective_source"],  # type: ignore[arg-type]
    )

    # The three boundary blocks are parsed by the existing parsers, so there is exactly one
    # implementation of each and a second fact/evidence/claim vocabulary cannot appear.
    product_facts = _parse_shared(parse_product_facts, mapping["product_facts"])
    boundary = _parse_shared(
        parse_evidence_boundary, mapping["visual_evidence_boundary"]
    )
    claim_boundary = _parse_shared(parse_claim_boundary, mapping["claim_boundary"])

    hypotheses: list[ConsumerHypothesis] = []
    for index, raw in enumerate(
        _array(mapping["consumer_hypotheses"], "consumer_hypotheses")
    ):
        item = _object(raw, f"consumer_hypotheses[{index}]")
        _exact_keys(item, _HYPOTHESIS_KEYS, f"consumer_hypotheses[{index}]")
        hypotheses.append(
            ConsumerHypothesis(
                hypothesis_id=item["hypothesis_id"],  # type: ignore[arg-type]
                statement=item["statement"],  # type: ignore[arg-type]
                support=item["support"],  # type: ignore[arg-type]
                basis_ref=_optional_reference(
                    item["basis_ref"], f"consumer_hypotheses[{index}].basis_ref"
                ),
            )
        )

    candidates: list[StrategyCandidate] = []
    for index, raw in enumerate(_array(mapping["candidates"], "candidates")):
        item = _object(raw, f"candidates[{index}]")
        _exact_keys(item, _CANDIDATE_KEYS, f"candidates[{index}]")
        candidates.append(
            StrategyCandidate(
                candidate_id=item["candidate_id"],  # type: ignore[arg-type]
                persuasion_job=item["persuasion_job"],  # type: ignore[arg-type]
                hypothesis_refs=tuple(
                    _token_list(
                        item["hypothesis_refs"], f"candidates[{index}].hypothesis_refs"
                    )
                ),
                product_fact_refs=tuple(
                    _token_list(
                        item["product_fact_refs"], f"candidates[{index}].product_fact_refs"
                    )
                ),
                evidence_refs=tuple(
                    _token_list(
                        item["evidence_refs"], f"candidates[{index}].evidence_refs"
                    )
                ),
                claims_used=tuple(
                    _token_list(item["claims_used"], f"candidates[{index}].claims_used")
                ),
                hook_strategy=item["hook_strategy"],  # type: ignore[arg-type]
                copy_direction=tuple(
                    _line_list(
                        item["copy_direction"], f"candidates[{index}].copy_direction"
                    )
                ),
                cta_direction=item["cta_direction"],  # type: ignore[arg-type]
                rationale=item["rationale"],  # type: ignore[arg-type]
                limitations=tuple(
                    _line_list(
                        item["limitations"],
                        f"candidates[{index}].limitations",
                        allow_empty=True,
                    )
                ),
            )
        )

    blocked: list[BlockedOpportunity] = []
    for index, raw in enumerate(
        _array(mapping["blocked_opportunities"], "blocked_opportunities")
    ):
        item = _object(raw, f"blocked_opportunities[{index}]")
        _exact_keys(item, _BLOCKED_KEYS, f"blocked_opportunities[{index}]")
        blocked.append(
            BlockedOpportunity(
                opportunity_id=item["opportunity_id"],  # type: ignore[arg-type]
                statement=item["statement"],  # type: ignore[arg-type]
                persuasion_job=item["persuasion_job"],  # type: ignore[arg-type]
                claim_ref=item["claim_ref"],  # type: ignore[arg-type]
                blocked_by=item["blocked_by"],  # type: ignore[arg-type]
                missing=tuple(
                    _line_list(item["missing"], f"blocked_opportunities[{index}].missing")
                ),
                next_action=item["next_action"],  # type: ignore[arg-type]
            )
        )

    provenance = _object(mapping["provenance"], "provenance")
    _exact_keys(provenance, _PROVENANCE_KEYS, "provenance")
    author = _object(provenance["authored_by"], "provenance.authored_by")
    _exact_keys(author, _AUTHOR_KEYS, "provenance.authored_by")
    based_on: list[ArtifactReference] = []
    for index, raw in enumerate(_array(provenance["based_on"], "provenance.based_on")):
        parsed_reference = _optional_reference(
            _object(raw, f"provenance.based_on[{index}]"),
            f"provenance.based_on[{index}]",
        )
        assert parsed_reference is not None  # a based_on entry is never null
        based_on.append(parsed_reference)

    return CommercialIntelligence(
        candidate_set_id=mapping["candidate_set_id"],  # type: ignore[arg-type]
        context=context,
        product_facts=product_facts,
        visual_evidence_boundary=boundary,
        claim_boundary=claim_boundary,
        consumer_hypotheses=tuple(hypotheses),
        candidates=tuple(candidates),
        blocked_opportunities=tuple(blocked),
        provenance=StrategyProvenance(
            StrategyAuthor(author["actor"], author["producer_id"]),  # type: ignore[arg-type]
            tuple(based_on),
        ),
    )


def render_commercial_intelligence(document: CommercialIntelligence) -> str:
    """Canonical one-document rendering. Identical input renders identical bytes."""

    if not isinstance(document, CommercialIntelligence):
        raise CommercialIntelligenceContractError(
            "document must be a CommercialIntelligence"
        )
    return json.dumps(
        document.as_dict(), ensure_ascii=False, sort_keys=True, indent=2
    ) + "\n"


def unlock_requirements(
    document: CommercialIntelligence,
) -> tuple[dict[str, object], ...]:
    """What would have to become true for each blocked opportunity to be usable.

    This is the answer to "what additional footage or evidence would unlock a stronger
    commercial strategy?", derived from the two boundaries rather than authored. It grants
    nothing: an unlock requirement is a description of missing evidence, never permission
    to use the claim.
    """

    if not isinstance(document, CommercialIntelligence):
        raise CommercialIntelligenceContractError(
            "document must be a CommercialIntelligence"
        )
    out: list[dict[str, object]] = []
    for opportunity in document.blocked_opportunities:
        availability = claim_availability(
            opportunity.claim_ref,
            document.claim_boundary,
            document.visual_evidence_boundary,
        )
        out.append(
            {
                "opportunity_id": opportunity.opportunity_id,
                "claim_ref": opportunity.claim_ref,
                "claim_state": availability.state,
                "blocked_by": availability.blocked_by,
                "derived_missing": list(availability.missing),
                "declared_missing": list(opportunity.missing),
                "next_action": opportunity.next_action,
                "grants_claim_use": False,
            }
        )
    return tuple(out)


__all__ = [
    "BLOCKING_CODES",
    "CANONICAL_REF",
    "CONTEXT_SOURCES",
    "ClaimAvailability",
    "CommercialIntelligence",
    "CommercialIntelligenceContractError",
    "BlockedOpportunity",
    "ConsumerHypothesis",
    "DEFAULT_OBJECTIVE",
    "HYPOTHESIS_SUPPORT",
    "IMPLEMENTATION",
    "JobContext",
    "SCHEMA_VERSION",
    "StrategyCandidate",
    "UNSPECIFIED_PLATFORM",
    "WIRING_STATUS",
    "claim_availability",
    "parse_commercial_intelligence",
    "render_commercial_intelligence",
    "resolve_context",
    "unlock_requirements",
]
