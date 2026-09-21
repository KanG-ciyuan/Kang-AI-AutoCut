"""Hook / Narrative Decision: one creative call, and a deterministic veto.

The ownership split is the whole design. The **model** generates and orders the hook
hypotheses; the **code** owns a factual, support and structural veto only, and never
compares two viable angles. So this stage never fabricates a reason to reject a
hypothesis the evidence supports: when more than one hypothesis is eligible it records
a *pending* decision and leaves the choice to the decision owner, because
``hook_decision.v1`` has no honest code for "viable, but ranked lower".

Provenance and reasoning are kept apart on purpose. The reference a decision carries is
computed from the Candidate Evidence bytes **as supplied**, in the version they were
supplied under, while eligibility is answered from the migrated authoritative view. A
v1 artifact therefore keeps meaning v1 bytes.

Boundary: this stage produces a Hook Decision and stops. It does not order shots, build
a Timeline, trim, plan a sequence, write voice-over or subtitle text, choose typography,
mix audio, render, run QA, release, A/B test, or predict conversion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from . import authoring, producer_registry
from .artifact_reference import (
    ArtifactReference,
    ArtifactReferenceError,
    artifact_reference,
    parse_artifact_reference,
    validate_reference_binding,
)
from .candidate_evidence import ClaimSupport, EvidenceStatus, ProductFacts
from .candidate_evidence_v2 import (
    ActionPresence,
    AuthoritativeObservation,
    ObservableState,
    authoritative_evidence_view,
    read_candidate_evidence,
    supplied_evidence_text,
)
from .candidate_pool import CandidatePool
from .creative_intent import (
    PRODUCT_ON_SCREEN,
    RESULT_OBSERVATIONS,
    DecisionOwner,
    EvidenceCoverage,
    EvidenceRequirement,
    FactSafety,
    HookAssessment,
    HookDecision,
    HookDecisionContractError,
    HookHypothesis,
    HookType,
    RejectionCode,
    SelectionReasonCode,
    VisualSupport,
    hook_id_for,
    parse_evidence_requirements,
    parse_visual_support,
    render_hook_decision,
    structured_support_satisfied,
    validate_hook_decision,
    validate_hook_decision_against_evidence,
)
from .identity import IdentityCatalog


PLANNING_REQUEST_SCHEMA_VERSION = "hook_planning_request.v1"
PLANNING_RESPONSE_SCHEMA_VERSION = "hook_planning_response.v1"

#: The versioned creative prompt. One contract, one call.
PROMPT_CONTRACT_VERSION = "hook_decision_prompt.v1"

#: Fields a Creative Brief may contribute to the model context. Everything else in a
#: job manifest - runtime locations, source inventory, timestamps - stays out.
BRIEF_FIELDS = (
    "name",
    "name_localized",
    "market",
    "platform",
    "language",
    "cta",
    "target_duration_seconds",
    "notes",
)

#: What each Hook type requires in the structured evidence. The common shape - states
#: that must all be present, and states of which at least one must be - is a table, not
#: a rule engine: five frozen Hook types do not need a predicate registry.
REQUIRED_ALL: Mapping[HookType, tuple[ObservableState, ...]] = {
    HookType.PAIN: (ObservableState.PROBLEM_STATE_VISIBLE,),
    HookType.OLD_WAY: (ObservableState.HUMAN_USE_VISIBLE,),
}
REQUIRED_ANY: Mapping[HookType, tuple[ObservableState, ...]] = {
    HookType.RESULT: RESULT_OBSERVATIONS,
}
REQUIRES_ACTION = frozenset({HookType.OLD_WAY})
PRODUCT_DIRECT_TOKENS = (
    ObservableState.PRODUCT_IDENTITY_VISIBLE,
    ObservableState.PRODUCT_BEAUTY_STATE_VISIBLE,
)

#: The three, and only three, ways a run can end.
OUTCOME_SELECTED = "SELECTED"
OUTCOME_PENDING = "PENDING"
OUTCOME_INSUFFICIENT = "INSUFFICIENT"

_DOCUMENT_KEYS = (
    "schema_version",
    "run_id",
    "candidate_pool_id",
    "provider",
    "model",
    "prompt_contract_version",
    "request",
    "hypotheses",
)
_PROPOSAL_KEYS = (
    "hook_type",
    "commercial_premise",
    "copy_direction",
    "expected_opening_structure",
    "required_evidence",
    "available_visual_support",
    "product_fact_refs",
)


class HookPlanningError(ValueError):
    """Raised when a hook planning run cannot be requested, trusted or produced."""


HOOK_PLANNING_QUESTION = """\
You are choosing the opening angle for one short commercial video. You are not
writing the advertisement: no voice-over, no subtitles, no final call to action.

You are given, and may use only:
- a compact Creative Brief (product, market, platform, language, call to action,
  target duration, notes);
- the permitted Product Facts. That list is closed. A premise that depends on
  anything else is not available to you;
- a compact structured summary of the evidence Phase 2 already recorded from the
  footage. There is no video here and no prose description of it, and you must not ask
  for one.

Propose between two and five GENUINELY DIFFERENT hook hypotheses, then order them by
your own creative judgement, best first. You own that ranking; nothing downstream
re-ranks it. For each hypothesis give:

- hook_type: exactly one of PAIN, OLD_WAY, RESULT, CURIOSITY, PRODUCT_DIRECT.
- commercial_premise: the angle in one sentence, as the piece would state it.
- copy_direction: how the opening should be written, in the imperative, one or two
  sentences. Direction only - never the finished line.
- expected_opening_structure: what the first seconds should show, and in what order.
- required_evidence: the evidence dimensions the premise needs, as
  {coverage_token, description}, using tokens PRODUCT_VISIBLE, ACTION_ONSET,
  OBSERVABLE_RESULT, BEFORE_STATE, AFTER_STATE, USAGE_CONTEXT,
  CLAIM_SUPPORT_DIRECT, IDENTITY_SHOT or BODY_AREA.
- available_visual_support: the Candidates you rely on, as
  {candidate_id, coverage_token, support} with support DIRECT, CONTEXTUAL or
  INFERRED. Use only candidate_id values you were given, and claim DIRECT only when
  the structured evidence for that Candidate really records it.
- product_fact_refs: the permitted Product Facts the premise depends on, or an empty
  list when it needs none. Name every fact the premise rests on: the gate checks the
  facts you declare, and it cannot see a claim you leave implicit.

What each hook type requires in the evidence:

- PAIN needs PROBLEM_STATE_VISIBLE: the adverse or soiled state must be on screen.
  Do not propose a pain angle because pain sells; propose it because it is visible.
- RESULT needs CLEAN_STATE_VISIBLE, STATE_CHANGE_VISIBLE or
  BEFORE_AFTER_RELATION_VISIBLE.
- OLD_WAY needs ACTION_PRESENT and HUMAN_USE_VISIBLE: someone must be visibly doing it
  the old way.
- PRODUCT_DIRECT needs the product on screen or an identity observation.
- CURIOSITY needs real evidence that can answer the question later. Never propose
  suspense with nothing behind it.

Do not invent Product Facts, do not lean on a premise the structured evidence does not
contain, and never treat action_presence NO_ACTION and NOT_RECORDED as if they meant
the same thing: NO_ACTION means the footage shows no action, NOT_RECORDED means nobody
has said either way.

Answer with a JSON document containing exactly: schema_version, run_id,
candidate_pool_id, provider, model, prompt_contract_version, request, hypotheses -
where hypotheses is your ordered list, each with exactly the keys listed above.
"""


# --------------------------------------------------------------------------- brief


@dataclass(frozen=True)
class BriefContext:
    """The Creative Brief, reduced to what a creative decision needs.

    ``reference`` binds the exact bytes of the brief document, so a decision is tied to
    the revision it was made against and rejected when the brief changes.
    """

    reference: ArtifactReference
    fields: tuple[tuple[str, object], ...]

    @property
    def ref(self) -> str:
        return self.reference.ref

    @property
    def sha256(self) -> str:
        return self.reference.sha256

    def as_dict(self) -> dict[str, object]:
        return dict(self.fields)


def _brief_fields(
    product: Mapping[str, object], document: Mapping[str, object]
) -> tuple[tuple[str, object], ...]:
    """Keep the creative fields, in a stable order, and nothing else."""

    fields: list[tuple[str, object]] = []
    for name in BRIEF_FIELDS:
        raw = product.get(name)
        if raw is None:
            raw = document.get(name)
        if raw is None or isinstance(raw, bool):
            continue
        if isinstance(raw, (str, int, float)):
            if str(raw).strip():
                fields.append((name, raw))
        elif isinstance(raw, dict):
            # A duration target may be stated as a range; keep only its numbers.
            compact = {
                key: value
                for key, value in raw.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
            if compact:
                fields.append((name, compact))
    return tuple(fields)


def build_brief_context(document: object, *, ref: str, text: object) -> BriefContext:
    """Read a job manifest or brief document and keep only the creative fields.

    ``text`` is the exact brief text whose SHA-256 binds the decision. Machine-bound
    material - ``runtime``, ``source``, timestamps, paths - is dropped here by
    construction, so it cannot reach a model even by accident.
    """

    if not isinstance(document, dict):
        raise HookPlanningError("a Creative Brief must be a JSON object")
    product = document.get("product") or {}
    if not isinstance(product, dict):
        raise HookPlanningError("brief.product must be a JSON object")
    fields = _brief_fields(product, document)
    name = next((value for key, value in fields if key == "name"), None)
    if not isinstance(name, str) or not name.strip():
        raise HookPlanningError("a Creative Brief must state the product name")
    try:
        reference = artifact_reference(ref, text)
    except ArtifactReferenceError as exc:
        raise HookPlanningError(str(exc)) from exc
    return BriefContext(reference=reference, fields=fields)


# ------------------------------------------------------------------------- context


@dataclass(frozen=True)
class CompactCandidate:
    """One Candidate as the model sees it: structured truth, nothing else.

    Prose, frame coordinates and provenance are deliberately absent. A hook decision
    does not need them, and sending them would invite a premise built on a sentence
    rather than on evidence.
    """

    candidate_id: str
    status: str
    action_presence: str
    observable_states: tuple[str, ...]
    product_visibility: str | None
    usage_context: str | None
    claims: tuple[tuple[str, str], ...]
    risk_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status,
            "action_presence": self.action_presence,
            "observable_states": list(self.observable_states),
            "product_visibility": self.product_visibility,
            "usage_context": self.usage_context,
            "claims": [
                {"product_fact_ref": fact, "support": support}
                for fact, support in self.claims
            ],
            "risk_codes": list(self.risk_codes),
        }


@dataclass(frozen=True)
class PlanningContext:
    """Everything this stage needs, read exactly once.

    ``supplied`` is the evidence exactly as the caller handed it over, and it is the
    only thing provenance is computed from. ``read`` and ``views`` are the migrated
    document and its authoritative view, and they are the only things eligibility is
    computed from. The two must never be confused.
    """

    run_id: str
    supplied: object
    read: object
    views: Mapping[str, AuthoritativeObservation]
    compact: tuple[CompactCandidate, ...]
    evidence: ArtifactReference
    brief: BriefContext
    product_facts: ProductFacts

    @property
    def permitted_fact_refs(self) -> frozenset[str]:
        return frozenset(self.product_facts.allowed_fact_refs)


def planning_context(
    *,
    run_id: str,
    evidence: object,
    brief: BriefContext,
    product_facts: ProductFacts,
) -> PlanningContext:
    """Read the evidence once, and keep provenance and reasoning apart.

    The reference binds the supplied version's canonical bytes; the view is migrated to
    the authoritative shape. The permitted Product Facts must be the ones the evidence
    was analysed under: a hook decision may narrow a premise, never the Claim Envelope
    behind it.
    """

    read = read_candidate_evidence(evidence)
    if product_facts != read.product_facts:
        raise HookPlanningError(
            "the permitted Product Facts must be the ones the candidate evidence was "
            "analyzed under; hook planning cannot widen the Claim Envelope"
        )
    observations = authoritative_evidence_view(read)
    try:
        reference = artifact_reference(
            producer_registry.CANDIDATE_EVIDENCE_ARTIFACT,
            supplied_evidence_text(evidence),
        )
    except ArtifactReferenceError as exc:
        raise HookPlanningError(str(exc)) from exc
    return PlanningContext(
        run_id=_token(run_id, "run_id"),
        supplied=evidence,
        read=read,
        views={view.candidate_id: view for view in observations},
        compact=tuple(_compact(view) for view in observations),
        evidence=reference,
        brief=brief,
        product_facts=product_facts,
    )


def _compact(view: AuthoritativeObservation) -> CompactCandidate:
    return CompactCandidate(
        candidate_id=view.candidate_id,
        status=view.status.value,
        action_presence=view.action_presence.value,
        observable_states=tuple(state.value for state in view.observable_states),
        product_visibility=view.product_visibility,
        usage_context=view.usage_context,
        claims=tuple((fact, kind.value) for fact, kind, _ in view.claims),
        risk_codes=tuple(view.risk_codes),
    )


# ------------------------------------------------------------------------- request


@dataclass(frozen=True)
class HookPlanningRequest:
    """The compact context, and the exact documents it was built from."""

    run_id: str
    candidate_evidence: ArtifactReference
    brief: ArtifactReference
    product_facts: ProductFacts
    brief_context: dict[str, object]
    candidates: tuple[CompactCandidate, ...]
    prompt_contract_version: str = PROMPT_CONTRACT_VERSION
    question: str = HOOK_PLANNING_QUESTION

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": PLANNING_REQUEST_SCHEMA_VERSION,
            "run_id": self.run_id,
            "candidate_evidence": self.candidate_evidence.as_dict(),
            "brief": self.brief.as_dict(),
            "product_facts": self.product_facts.as_dict(),
            "prompt_contract_version": self.prompt_contract_version,
            "question": self.question,
            "brief_context": {
                "ref": self.brief.ref,
                "sha256": self.brief.sha256,
                "fields": dict(self.brief_context),
            },
            "candidates": [candidate.as_dict() for candidate in self.candidates],
        }


def build_planning_request(context: PlanningContext) -> HookPlanningRequest:
    """The model's input: the compact context, and the revisions it is bound to."""

    if not isinstance(context, PlanningContext):
        raise HookPlanningError("context must be a PlanningContext")
    return HookPlanningRequest(
        run_id=context.run_id,
        candidate_evidence=context.evidence,
        brief=context.brief.reference,
        product_facts=context.product_facts,
        brief_context=context.brief.as_dict(),
        candidates=context.compact,
    )


def render_planning_request(request: HookPlanningRequest) -> str:
    if not isinstance(request, HookPlanningRequest):
        raise HookPlanningError("request must be a HookPlanningRequest")
    return (
        json.dumps(request.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )


def planning_request_reference(request: HookPlanningRequest) -> ArtifactReference:
    """The reference a creative answer must declare to prove it answered this request."""

    return artifact_reference(
        producer_registry.HOOK_PLANNING_REQUEST_ARTIFACT,
        render_planning_request(request),
    )


# ------------------------------------------------------------------------ response


@dataclass(frozen=True)
class ProposedHypothesis:
    """One hypothesis as the model ranked it, before any veto."""

    hook_type: HookType
    commercial_premise: str
    copy_direction: str
    expected_opening_structure: str
    required_evidence: tuple[EvidenceRequirement, ...]
    available_visual_support: tuple[VisualSupport, ...]
    product_fact_refs: tuple[str, ...]

    @property
    def hook_id(self) -> str:
        return hook_id_for(self.hook_type, self.commercial_premise)

    def as_dict(self) -> dict[str, object]:
        """The inverse of :func:`_parse_proposal`, so the shape has one home."""

        return {
            "hook_type": self.hook_type.value,
            "commercial_premise": self.commercial_premise,
            "copy_direction": self.copy_direction,
            "expected_opening_structure": self.expected_opening_structure,
            "required_evidence": [item.as_dict() for item in self.required_evidence],
            "available_visual_support": [
                item.as_dict() for item in self.available_visual_support
            ],
            "product_fact_refs": list(self.product_fact_refs),
        }


def parse_planning_response(
    document: object,
    *,
    request: HookPlanningRequest,
    request_text: object | None = None,
) -> tuple[tuple[ProposedHypothesis, ...], tuple[str, str, str]]:
    """Parse the creative answer. Order is preserved: it is the model's ranking."""

    mapping = _object(document, "hook planning response")
    _exact_keys(mapping, _DOCUMENT_KEYS, "hook planning response")
    if mapping["schema_version"] != PLANNING_RESPONSE_SCHEMA_VERSION:
        raise HookPlanningError(
            f"schema_version must be {PLANNING_RESPONSE_SCHEMA_VERSION!r}"
        )
    for key, expected in (
        ("run_id", request.run_id),
        ("prompt_contract_version", request.prompt_contract_version),
    ):
        if mapping[key] != expected:
            raise HookPlanningError(f"the response answers a different {key}")
    provider = _token(mapping["provider"], "response.provider")
    model = _token(mapping["model"], "response.model")
    try:
        declared = parse_artifact_reference(
            mapping["request"],
            label="hook planning response.request",
            expected_ref=producer_registry.HOOK_PLANNING_REQUEST_ARTIFACT,
        )
    except ArtifactReferenceError as exc:
        raise HookPlanningError(f"the response request reference is malformed: {exc}")
    if request_text is not None:
        try:
            validate_reference_binding(
                declared, request_text, label="hook planning response.request"
            )
        except ArtifactReferenceError as exc:
            raise HookPlanningError(f"the response answers a different request: {exc}")

    proposals: list[ProposedHypothesis] = []
    for index, item in enumerate(_array(mapping["hypotheses"], "hypotheses")):
        proposals.append(_parse_proposal(item, f"hypotheses[{index}]"))
    if not 2 <= len(proposals) <= 5:
        raise HookPlanningError("a creative answer must hold between 2 and 5 hypotheses")
    identities = [proposal.hook_id for proposal in proposals]
    if len(set(identities)) != len(identities):
        raise HookPlanningError(
            "two hypotheses restate the same premise; a hook set must offer real "
            "alternatives"
        )
    return tuple(proposals), (provider, model, str(mapping["prompt_contract_version"]))


def _parse_proposal(value: object, label: str) -> ProposedHypothesis:
    """One hypothesis, refused here rather than downstream.

    The shape rules ``hook_decision.v1`` enforces on a hypothesis - at least one
    requirement, no repeated token, support that answers a stated requirement, no
    repeated Candidate and token pair - are checked here, because a creative answer that
    breaks them is a malformed answer and must fail closed as one instead of surfacing
    later as a contract error.
    """

    mapping = _object(value, label)
    _exact_keys(mapping, _PROPOSAL_KEYS, label)
    facts = tuple(
        _token(raw, f"{label}.product_fact_refs[{index}]")
        for index, raw in enumerate(
            _array(mapping["product_fact_refs"], f"{label}.product_fact_refs")
        )
    )
    if len(set(facts)) != len(facts):
        raise HookPlanningError(f"{label}.product_fact_refs must not repeat a fact")
    try:
        requirements = parse_evidence_requirements(
            mapping["required_evidence"], f"{label}.required_evidence"
        )
        support = parse_visual_support(
            mapping["available_visual_support"],
            f"{label}.available_visual_support",
        )
    except HookDecisionContractError as exc:
        raise HookPlanningError(f"{label} is malformed: {exc}") from exc

    tokens = [item.coverage_token for item in requirements]
    if not tokens:
        raise HookPlanningError(f"{label} must state at least one evidence requirement")
    if len(set(tokens)) != len(tokens):
        raise HookPlanningError(
            f"{label}.required_evidence must not repeat a coverage token"
        )
    for index, item in enumerate(support):
        if item.coverage_token not in set(tokens):
            raise HookPlanningError(
                f"{label}.available_visual_support[{index}] must answer a stated "
                "evidence requirement"
            )
    pairs = [(item.candidate_id, item.coverage_token) for item in support]
    if len(set(pairs)) != len(pairs):
        raise HookPlanningError(
            f"{label}.available_visual_support must not repeat a Candidate and token"
        )
    return ProposedHypothesis(
        hook_type=_enum(mapping["hook_type"], HookType, f"{label}.hook_type"),  # type: ignore[arg-type]
        commercial_premise=_text(
            mapping["commercial_premise"], f"{label}.commercial_premise"
        ),
        copy_direction=_text(mapping["copy_direction"], f"{label}.copy_direction"),
        expected_opening_structure=_text(
            mapping["expected_opening_structure"],
            f"{label}.expected_opening_structure",
        ),
        required_evidence=requirements,
        available_visual_support=support,
        product_fact_refs=tuple(sorted(facts)),
    )


# ---------------------------------------------------------------------- veto gate


@dataclass(frozen=True)
class HypothesisVerdict:
    """What the deterministic gate decided about one hypothesis, and why."""

    proposal: ProposedHypothesis
    eligible: bool
    rejection: RejectionCode | None
    fact_safety: FactSafety
    coverage: EvidenceCoverage
    kept_support: tuple[VisualSupport, ...]
    direct_claim_backed: bool
    detail: str

    @property
    def hook_id(self) -> str:
        return self.proposal.hook_id

    @property
    def rejection_codes(self) -> tuple[RejectionCode, ...]:
        """Every code ``hook_decision.v1`` requires for this verdict.

        ``rejection`` is the one cause that decided it; the frozen contract also demands
        codes that follow from the recorded assessment rather than from a cause - an
        INSUFFICIENT coverage, an unsafe premise, and a hypothesis left with no validated
        support each have a required code. Derived here, once, so no veto path can
        produce a document the contract refuses.
        """

        if self.rejection is None:
            return ()
        codes = {self.rejection}
        if self.coverage is EvidenceCoverage.INSUFFICIENT:
            codes.add(RejectionCode.INSUFFICIENT_EVIDENCE)
        if self.fact_safety is FactSafety.FACT_UNSAFE:
            codes.add(RejectionCode.UNSUPPORTED_CLAIM)
        if not self.kept_support:
            codes.add(RejectionCode.NO_OPENING_VISUAL)
        return tuple(sorted(codes, key=lambda code: code.value))


def validate_declared_support(
    proposal: ProposedHypothesis,
    *,
    pool: CandidatePool,
    views: Mapping[str, AuthoritativeObservation],
) -> tuple[tuple[VisualSupport, ...], RejectionCode | None, str]:
    """Check every declared support item, and report what survived.

    Support is checked, not trusted: a Candidate must be an analyzed Pool member, and a
    ``DIRECT`` claim must describe something the structured evidence records. The
    validated subset is returned even when the hypothesis is vetoed, so a partly honest
    answer is recorded exactly as far as it was honest.
    """

    members = {entry.candidate_id for entry in pool.entries}
    kept: list[VisualSupport] = []
    for item in proposal.available_visual_support:
        if item.candidate_id not in members:
            return (
                tuple(kept),
                RejectionCode.INSUFFICIENT_EVIDENCE,
                "declared visual support names a Candidate outside the Pool",
            )
        view = views.get(item.candidate_id)
        if view is None or view.status is not EvidenceStatus.ANALYZED:
            return (
                tuple(kept),
                RejectionCode.INSUFFICIENT_EVIDENCE,
                "declared visual support names a Candidate with no analyzed evidence",
            )
        if item.support is ClaimSupport.DIRECT and not structured_support_satisfied(
            view, item.coverage_token
        ):
            return (
                tuple(kept),
                RejectionCode.INSUFFICIENT_EVIDENCE,
                "declared DIRECT visual support is not recorded in the structured "
                "evidence",
            )
        kept.append(item)
    if not kept:
        return (
            (),
            RejectionCode.NO_OPENING_VISUAL,
            "the hypothesis offers no Candidate support that survived validation",
        )
    return tuple(kept), None, ""


def evidence_gap(
    hook_type: HookType,
    states: frozenset[ObservableState],
    *,
    has_action: bool,
    product_on_screen: bool,
    answerable: bool,
) -> str | None:
    """What the structured evidence lacks for this Hook type, or ``None``.

    The table covers the Hook types answered by observations. The two that need
    something else - the product itself, or evidence able to answer a question - keep
    explicit branches. This is a lookup, not a rule engine.
    """

    if hook_type in REQUIRES_ACTION and not has_action:
        return "nothing in the structured evidence says an action happens"
    missing = tuple(
        state for state in REQUIRED_ALL.get(hook_type, ()) if state not in states
    )
    if missing:
        return "it does not record " + ", ".join(
            state.value for state in missing
        )
    any_of = REQUIRED_ANY.get(hook_type, ())
    if any_of and not any(state in states for state in any_of):
        return "it records none of " + ", ".join(state.value for state in any_of)
    if (
        hook_type is HookType.PRODUCT_DIRECT
        and not product_on_screen
        and not states.intersection(PRODUCT_DIRECT_TOKENS)
    ):
        return "the product is neither on screen nor recorded by an identity observation"
    if hook_type is HookType.CURIOSITY and not answerable:
        return "no observation and no supported claim can answer the question later"
    return None


def assess_hypothesis(
    proposal: ProposedHypothesis,
    *,
    pool: CandidatePool,
    context: PlanningContext,
) -> HypothesisVerdict:
    """The factual, support and structural veto for one hypothesis.

    Three questions, asked independently: does the premise declare Product Facts the
    Claim Envelope does not permit, is its declared support real, and does the structured
    evidence contain what this Hook type requires? The most serious failure is the
    recorded cause - facts before support, support before the hook type - so a veto names
    the earliest thing that was wrong.

    What is deliberately absent is any comparison between hypotheses: the gate judges
    each one against the evidence, never against another premise.
    """

    if not isinstance(proposal, ProposedHypothesis):
        raise HookPlanningError("proposal must be a ProposedHypothesis")

    unpermitted = sorted(
        fact
        for fact in proposal.product_fact_refs
        if fact not in context.permitted_fact_refs
    )
    fact_safety = FactSafety.FACT_UNSAFE if unpermitted else FactSafety.FACT_SAFE
    kept, support_rejection, support_detail = validate_declared_support(
        proposal, pool=pool, views=context.views
    )

    supporting = [context.views[item.candidate_id] for item in kept]
    states: set[ObservableState] = set()
    for view in supporting:
        states.update(view.observable_states)
    frozen_states = frozenset(states)
    declared_facts = set(proposal.product_fact_refs)
    # A direct-support reason is only honest when the premise names the fact and a kept
    # Candidate records direct support for that same fact.
    direct_backed = any(
        kind is ClaimSupport.DIRECT and fact in declared_facts
        for view in supporting
        for fact, kind, _ in view.claims
    )

    def verdict(
        rejection: RejectionCode | None,
        coverage: EvidenceCoverage,
        detail: str,
        *,
        eligible: bool = False,
    ) -> HypothesisVerdict:
        return HypothesisVerdict(
            proposal=proposal,
            eligible=eligible,
            rejection=rejection,
            fact_safety=fact_safety,
            coverage=coverage,
            kept_support=kept,
            direct_claim_backed=direct_backed,
            detail=detail,
        )

    if unpermitted:
        return verdict(
            RejectionCode.UNSUPPORTED_CLAIM,
            EvidenceCoverage.INSUFFICIENT,
            "the premise declares Product Facts the Claim Envelope does not permit: "
            + ", ".join(unpermitted),
        )
    if support_rejection is not None:
        return verdict(support_rejection, EvidenceCoverage.INSUFFICIENT, support_detail)

    gap = evidence_gap(
        proposal.hook_type,
        frozen_states,
        has_action=any(
            view.action_presence is ActionPresence.ACTION_PRESENT for view in supporting
        ),
        product_on_screen=any(
            view.product_visibility in PRODUCT_ON_SCREEN for view in supporting
        ),
        answerable=bool(frozen_states)
        or any(
            kind in (ClaimSupport.DIRECT, ClaimSupport.CONTEXTUAL)
            for view in supporting
            for _, kind, _ in view.claims
        ),
    )
    if gap is not None:
        return verdict(
            RejectionCode.INSUFFICIENT_EVIDENCE,
            EvidenceCoverage.INSUFFICIENT,
            f"a {proposal.hook_type.value} premise is not carried by the footage: {gap}",
        )

    requirements = {item.coverage_token for item in proposal.required_evidence}
    supported_tokens = {item.coverage_token for item in kept}
    return verdict(
        None,
        (
            EvidenceCoverage.FULL
            if requirements <= supported_tokens
            else EvidenceCoverage.PARTIAL
        ),
        "the premise is permitted, its Candidates are Pool members, and the structured "
        "evidence contains what this hook type requires",
        eligible=True,
    )


def select_first_eligible(verdicts: Sequence[HypothesisVerdict]) -> int | None:
    """The gate's choice, and the limit of its authority.

    Exactly one eligible hypothesis is selected: the model already ranked it, and there
    is nothing left to decide. None is eligible and every hypothesis was rejected. More
    than one and the gate declines to choose at all - it has no basis on which to prefer
    one viable creative angle over another, and ``hook_decision.v1`` has no honest code
    for "viable, but ranked lower". That case is recorded as a pending decision.
    """

    eligible = [index for index, verdict in enumerate(verdicts) if verdict.eligible]
    return eligible[0] if len(eligible) == 1 else None


# ------------------------------------------------------------------------ decision


def build_hook_decision(
    *,
    request: HookPlanningRequest,
    verdicts: Sequence[HypothesisVerdict],
    selected_index: int | None,
) -> HookDecision:
    """Record the outcome: the model's hypotheses, and the gate's verdicts.

    ``decision_owner`` is derived rather than passed, because it is not a creative
    choice: an unselected but viable hypothesis means nobody has decided yet, and an
    assigned owner with no selection means every hypothesis was rejected.
    """

    if not isinstance(request, HookPlanningRequest):
        raise HookPlanningError("request must be a HookPlanningRequest")
    if selected_index is not None and not verdicts[selected_index].eligible:
        raise HookPlanningError("the selected hypothesis must be eligible")

    selected_type = (
        None if selected_index is None else verdicts[selected_index].proposal.hook_type
    )
    pending = selected_index is None and any(verdict.eligible for verdict in verdicts)
    hypotheses: list[HookHypothesis] = []
    for index, verdict in enumerate(verdicts):
        codes = set(verdict.rejection_codes)
        if index == selected_index:
            pass  # the chosen hypothesis carries no rejection code
        elif selected_type is not None and verdict.proposal.hook_type is selected_type:
            # hook_decision.v1 names a hypothesis that shares the selected Hook type as
            # a duplicate of the chosen premise, whether or not it was vetoed as well.
            codes.add(RejectionCode.DUPLICATES_SELECTED_PREMISE)
        hypotheses.append(
            HookHypothesis(
                hook_type=verdict.proposal.hook_type,
                commercial_premise=verdict.proposal.commercial_premise,
                required_evidence=verdict.proposal.required_evidence,
                copy_direction=verdict.proposal.copy_direction,
                expected_opening_structure=verdict.proposal.expected_opening_structure,
                assessment=HookAssessment(
                    fact_safety=verdict.fact_safety,
                    evidence_coverage=verdict.coverage,
                    rejection_codes=tuple(sorted(codes, key=lambda code: code.value)),
                ),
                available_visual_support=verdict.kept_support,
            )
        )

    reasons: tuple[SelectionReasonCode, ...] = ()
    if selected_index is not None:
        selected = verdicts[selected_index]
        reasons = (
            (SelectionReasonCode.FACT_SAFE, SelectionReasonCode.DIRECT_VISUAL_SUPPORT)
            if selected.direct_claim_backed
            else (SelectionReasonCode.FACT_SAFE,)
        )

    decision = HookDecision(
        candidate_evidence=request.candidate_evidence,
        brief=request.brief,
        hypotheses=tuple(hypotheses),
        selected_hook_id=(
            None if selected_index is None else verdicts[selected_index].hook_id
        ),
        selection_reason_codes=reasons,
        decision_owner=(
            DecisionOwner.UNASSIGNED if pending else DecisionOwner.SUPERVISOR_AGENT
        ),
    )
    validate_hook_decision(decision)
    return decision


@dataclass(frozen=True)
class HookPlanningResult:
    """The decision, the evidence behind it, and the cost of producing it."""

    request: HookPlanningRequest
    verdicts: tuple[HypothesisVerdict, ...]
    decision: HookDecision
    decision_text: str
    provider: str
    model: str
    prompt_contract_version: str
    model_call_count: int
    response_source: str

    @property
    def selected_hook_id(self) -> str | None:
        return self.decision.selected_hook_id

    @property
    def outcome(self) -> str:
        """``SELECTED``, ``PENDING`` or ``INSUFFICIENT``.

        Pending is not insufficiency: pending means several hypotheses were eligible and
        the choice went to the decision owner, which is the only honest record when the
        gate may not rank creative options.
        """

        if self.decision.selected_hook_id is not None:
            return OUTCOME_SELECTED
        if self.decision.decision_owner is DecisionOwner.UNASSIGNED:
            return OUTCOME_PENDING
        return OUTCOME_INSUFFICIENT

def run_hook_planning_stage(
    *,
    job_root: Path | str,
    evidence: object,
    brief: BriefContext,
    product_facts: ProductFacts,
    pool: CandidatePool,
    catalog: IdentityCatalog,
    run_id: str,
    agent: authoring.AuthoringAgent | None = None,
    response_document: object | None = None,
) -> HookPlanningResult:
    """Request one creative answer, veto it factually, and write the decision.

    Exactly one provider call is made on the normal path. A declined, missing or
    malformed answer fails closed: hypotheses that cannot be validated are not invented,
    and no second call is made to rescue the result.
    """

    if not isinstance(pool, CandidatePool):
        raise HookPlanningError("pool must be a CandidatePool")
    if not isinstance(catalog, IdentityCatalog):
        raise HookPlanningError("catalog must be an IdentityCatalog")

    context = planning_context(
        run_id=run_id, evidence=evidence, brief=brief, product_facts=product_facts
    )
    request = build_planning_request(context)
    request_text = render_planning_request(request)
    root = Path(job_root)
    _write_json(root, producer_registry.HOOK_PLANNING_REQUEST_ARTIFACT, request_text)

    model_calls = 0
    if response_document is not None:
        document: object = response_document
        source = "SUPPLIED_DOCUMENT"
    else:
        if agent is None:
            raise HookPlanningError(
                "hook planning needs either a creative answer or an authoring agent"
            )
        source = "AUTHORING_SEAM"
        authoring_request = authoring.request_for_vnext(
            producer_registry.HOOK_PLANNING_RESPONSE_ARTIFACT, root
        )
        model_calls = 1
        if not bool(agent.author(authoring_request)):
            raise HookPlanningError(
                "the creative model produced no answer; no second call is made"
            )
        document = _read_json(root, producer_registry.HOOK_PLANNING_RESPONSE_ARTIFACT)

    proposals, (provider, model, prompt_version) = parse_planning_response(
        document, request=request, request_text=request_text
    )
    verdicts = tuple(
        assess_hypothesis(proposal, pool=pool, context=context)
        for proposal in proposals
    )
    decision = build_hook_decision(
        request=request,
        verdicts=verdicts,
        selected_index=select_first_eligible(verdicts),
    )
    try:
        validate_hook_decision_against_evidence(
            decision, context.supplied, pool, catalog
        )
    except HookDecisionContractError as exc:
        raise HookPlanningError(
            f"the produced Hook Decision does not satisfy hook_decision.v1: {exc}"
        ) from exc
    decision_text = render_hook_decision(decision)
    _write_json(root, producer_registry.HOOK_DECISION_ARTIFACT, decision_text)
    return HookPlanningResult(
        request=request,
        verdicts=verdicts,
        decision=decision,
        decision_text=decision_text,
        provider=provider,
        model=model,
        prompt_contract_version=prompt_version,
        model_call_count=model_calls,
        response_source=source,
    )


def validate_brief_binding(
    decision: HookDecision, brief_text: object, *, label: str = "brief"
) -> None:
    """Fail closed when a decision was made against different brief bytes."""

    if not isinstance(decision, HookDecision):
        raise HookPlanningError("decision must be a HookDecision")
    try:
        validate_reference_binding(decision.brief, brief_text, label=label)
    except ArtifactReferenceError as exc:
        raise HookPlanningError(str(exc)) from exc


# ------------------------------------------------------------------ small helpers


def _write_json(job_root: Path, artifact: str, payload: str) -> Path:
    target = Path(job_root) / artifact
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")
    return target


def _read_json(job_root: Path, artifact: str) -> object:
    path = Path(job_root) / artifact
    if not path.is_file():
        raise HookPlanningError("the creative answer artifact is missing")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HookPlanningError(
            f"the creative answer is not readable JSON: {exc}"
        ) from exc


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise HookPlanningError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise HookPlanningError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise HookPlanningError(f"{label} has unsupported key(s): {', '.join(unknown)}")
    if missing:
        raise HookPlanningError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HookPlanningError(f"{label} must be a non-empty string")
    return value


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HookPlanningError(f"{label} must be a non-empty string")
    if len(value) > 128 or any(character.isspace() for character in value):
        raise HookPlanningError(f"{label} must be a logical token")
    if value.startswith(("/", "~", ".")) or "\\" in value:
        raise HookPlanningError(f"{label} must not be a machine path")
    return value


def _enum(value: object, member_type: type, label: str) -> object:
    choices = ", ".join(member.name for member in member_type)
    if not isinstance(value, str):
        raise HookPlanningError(f"{label} must be one of: {choices}")
    try:
        return member_type(value)
    except ValueError as exc:
        raise HookPlanningError(f"{label} must be one of: {choices}") from exc
