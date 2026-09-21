"""Candidate Evidence v2: structured visual observations, and the machine-truth boundary.

Why a successor version, and not a patch
----------------------------------------
Phase 2.5's live validation produced honest answers that the v1 contract could not
hold. Two windows showed no action at all, and the only place to say so was the
free-text ``visible_action`` field: *"no action: the surface is static across every
sampled frame"*. The visible problem state of a surface - the thing a hook would
open on - had no home either, because the Claim Envelope deliberately carries no
hygiene fact. ``candidate_evidence.v1`` states its own rule: *"Version 1 is closed.
Adding, removing, renaming, or changing any key or vocabulary member requires a
separately reviewed version."* So v1 stays as it is, and v2 is a successor.

What v2 adds, and what it refuses to add
----------------------------------------
Exactly two keys inside ``observations``:

``action_presence``
    ``ACTION_PRESENT``, ``NO_ACTION``, or ``NOT_RECORDED``. Absence becomes a
    statement instead of a silence, and "nobody said" stays distinguishable from
    "there was nothing to see".
``observable_states``
    A finite list of :class:`ObservableState` codes: what is visibly there -
    problem state, clean state, contact, flow, a state change, a before/after
    relation, product identity, product beauty presentation, human use.

Everything else is unchanged: the same eleven entry keys, the same frame-exact
provenance rules, the same Product Fact binding, the same DIRECT proof obligations.
The entry key set is *identical* to v1; only the observations object grows from
seven keys to nine.

These are observations, not claims. There is deliberately no code for "cleans
well", "kills bacteria", "improves health", or any other effect: an effect is a
commercial claim, a commercial claim requires a Product Fact, and a Product Fact
requires the Claim Envelope. A structured observation can never become claim
support - nothing here derives a claim from a state, and the code that builds
evidence only copies claims from the analyzer's answer after the envelope checked
them.

Machine truth, and what is not machine truth
--------------------------------------------
Authoritative, machine-readable truth is: the status, the two structured fields
above, the Product-Fact-bound claims with their support class, the frame
coordinates of provenance and action evidence, the enumerated observation fields,
confidence, and risk codes. That is exactly what
:func:`authoritative_evidence_view` exposes, and exactly what Phase 3 may consume.

Non-authoritative explanatory text is: ``rationale``, ``observations.visible_action``,
``observations.visible_result``, ``claims[].note``, and ``risks[].note``. Phase 2.5
proved that claim-like marketing language can sit in a ``rationale`` with no envelope
checking it. Prose may therefore explain a structured decision but may never create
one, and no consumer may parse it for claims, coverage, or requirements. The view
above omits every prose field by construction, so a planner cannot read prose even
by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import Mapping, Sequence

from .candidate_evidence import (
    SCHEMA_VERSION as V1_SCHEMA_VERSION,
    AnalysisRun,
    CandidateEvidence,
    CandidateEvidenceContractError,
    CandidateEvidenceEntry,
    ClaimSupport,
    EvidenceStatus,
    EvidenceType,
    Observations,
    ProductFacts,
    parse_candidate_evidence,
    render_candidate_evidence,
    validate_candidate_evidence,
)
from .candidate_pool import CandidatePool
from .identity import CandidateIdentity, IdentityCatalog


SCHEMA_VERSION = "candidate_evidence.v2"

#: The v1 error type, reused so a caller catching contract errors catches both
#: versions. v2 is a successor of one contract, not a second contract family.
CandidateEvidenceV2Error = CandidateEvidenceContractError

#: The observations key set of v1, which v2 keeps verbatim.
V1_OBSERVATION_KEYS = (
    "visible_action",
    "visible_result",
    "product_visibility",
    "usage_context",
    "body_area",
    "visual_usability",
    "claim_support_class",
)

#: The two keys v2 adds inside ``observations``.
V2_OBSERVATION_KEYS = V1_OBSERVATION_KEYS + ("action_presence", "observable_states")

_DOCUMENT_KEYS = (
    "schema_version",
    "candidate_pool_id",
    "product_facts",
    "analysis_run",
    "entries",
)

#: Fields that carry machine truth. A consumer may branch on these.
AUTHORITATIVE_FIELDS = (
    "candidate_id",
    "status",
    "action_presence",
    "observable_states",
    "claims",
    "provenance",
    "action_evidence",
    "confidence",
    "evidence_type",
    "product_visibility",
    "usage_context",
    "body_area",
    "visual_usability",
    "risk_codes",
)

#: Fields that are explanatory prose. A consumer must not branch on these.
NON_AUTHORITATIVE_FIELDS = (
    "rationale",
    "observations.visible_action",
    "observations.visible_result",
    "claims[].note",
    "risks[].note",
)

#: The sentence every downstream consumer is entitled to rely on.
RATIONALE_STATUS = "NON_AUTHORITATIVE_EXPLANATORY_TEXT"


class ActionPresence(str, Enum):
    """Whether an observable action happens in this Candidate.

    The distinction between ``NO_ACTION`` and ``NOT_RECORDED`` is the point: a
    static plate is a fact about the footage, while silence is a fact about the
    analysis. v1 could express neither, and the difference mattered.
    """

    ACTION_PRESENT = "ACTION_PRESENT"
    NO_ACTION = "NO_ACTION"
    NOT_RECORDED = "NOT_RECORDED"


class ObservableState(str, Enum):
    """A finite vocabulary of visually observable states, events and relations.

    Every member is a statement about what is *visible*. None of them is a claim
    about effect, and none may be turned into one: an effect needs a Product Fact
    from the Claim Envelope.
    """

    #: The subject is visibly in the adverse or soiled state the piece addresses.
    PROBLEM_STATE_VISIBLE = "PROBLEM_STATE_VISIBLE"
    #: The subject is visibly in the cleared, improved state.
    CLEAN_STATE_VISIBLE = "CLEAN_STATE_VISIBLE"
    #: The subject's visible state changes within the Candidate's frames.
    STATE_CHANGE_VISIBLE = "STATE_CHANGE_VISIBLE"
    #: Both states and their relation are visible within the frames.
    BEFORE_AFTER_RELATION_VISIBLE = "BEFORE_AFTER_RELATION_VISIBLE"
    #: An implement or body part is visibly in contact with the subject.
    CONTACT_VISIBLE = "CONTACT_VISIBLE"
    #: A liquid is visibly moving over the subject.
    FLOW_VISIBLE = "FLOW_VISIBLE"
    #: The product itself is visibly identifiable in the frames.
    PRODUCT_IDENTITY_VISIBLE = "PRODUCT_IDENTITY_VISIBLE"
    #: The product is presented in a beauty or hero state, with no effect asserted.
    PRODUCT_BEAUTY_STATE_VISIBLE = "PRODUCT_BEAUTY_STATE_VISIBLE"
    #: A person is visibly handling or using the product or subject.
    HUMAN_USE_VISIBLE = "HUMAN_USE_VISIBLE"


#: One-line meaning per code, for docs, prompts, and tests.
OBSERVABLE_STATE_MEANINGS: Mapping[str, str] = {
    ObservableState.PROBLEM_STATE_VISIBLE.value: (
        "the subject is visibly in the adverse or soiled state the piece addresses"
    ),
    ObservableState.CLEAN_STATE_VISIBLE.value: (
        "the subject is visibly in the cleared or restored state"
    ),
    ObservableState.STATE_CHANGE_VISIBLE.value: (
        "the visible state of the subject changes within these frames"
    ),
    ObservableState.BEFORE_AFTER_RELATION_VISIBLE.value: (
        "both the before and the after state, and their relation, are visible"
    ),
    ObservableState.CONTACT_VISIBLE.value: (
        "an implement or body part is visibly in contact with the subject"
    ),
    ObservableState.FLOW_VISIBLE.value: (
        "a liquid is visibly moving over the subject"
    ),
    ObservableState.PRODUCT_IDENTITY_VISIBLE.value: (
        "the product itself is visibly identifiable in these frames"
    ),
    ObservableState.PRODUCT_BEAUTY_STATE_VISIBLE.value: (
        "the product is presented in a beauty or hero state; this asserts no effect"
    ),
    ObservableState.HUMAN_USE_VISIBLE.value: (
        "a person is visibly handling or using the product or subject"
    ),
}

#: Codes that describe an event rather than a static appearance. They assert that
#: something happens, so they require an action to have been recorded.
EVENT_STATE_CODES = frozenset(
    {
        ObservableState.CONTACT_VISIBLE,
        ObservableState.FLOW_VISIBLE,
        ObservableState.STATE_CHANGE_VISIBLE,
        ObservableState.BEFORE_AFTER_RELATION_VISIBLE,
    }
)

#: Codes that assert something about product presentation specifically.
PRODUCT_STATE_CODES = frozenset(
    {
        ObservableState.PRODUCT_IDENTITY_VISIBLE,
        ObservableState.PRODUCT_BEAUTY_STATE_VISIBLE,
    }
)

#: Words that must never appear in the observation vocabulary: an observation
#: asserts what is visible, never an effect. Asserted by test.
FORBIDDEN_IN_OBSERVATION_VOCABULARY = (
    "efficacy",
    "kill",
    "steril",
    "disinfect",
    "hygien",
    "health",
    "safe",
    "guarantee",
    "improve",
    "remove",
    "eliminate",
)


def _enum(value: object, member_type: type[Enum], label: str) -> object:
    choices = ", ".join(member.name for member in member_type)
    if not isinstance(value, str):
        raise CandidateEvidenceV2Error(f"{label} must be one of: {choices}")
    try:
        return member_type(value)
    except ValueError as exc:
        raise CandidateEvidenceV2Error(f"{label} must be one of: {choices}") from exc


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise CandidateEvidenceV2Error(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise CandidateEvidenceV2Error(f"{label} must be a JSON array")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise CandidateEvidenceV2Error(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise CandidateEvidenceV2Error(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


@dataclass(frozen=True)
class ObservationsV2:
    """v1's seven observation fields, plus the two structured ones.

    The v1 fields are held as a validated :class:`Observations` instance, so every
    v1 rule about them - the enum vocabulary, the non-empty action text, the
    nullable result - is enforced by v1 itself rather than copied here.
    """

    base: Observations
    action_presence: ActionPresence = ActionPresence.NOT_RECORDED
    observable_states: tuple[ObservableState, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.base, Observations):
            raise CandidateEvidenceV2Error("observations must be v1 Observations")
        presence = _enum(
            self.action_presence, ActionPresence, "observations.action_presence"
        )
        object.__setattr__(self, "action_presence", presence)
        states = tuple(
            _enum(raw, ObservableState, f"observations.observable_states[{index}]")
            for index, raw in enumerate(self.observable_states)
        )
        names = [state.value for state in states]  # type: ignore[union-attr]
        if len(set(names)) != len(names):
            raise CandidateEvidenceV2Error(
                "observations.observable_states must not repeat a state"
            )
        ordered = tuple(sorted(states, key=lambda state: state.value))  # type: ignore[union-attr]
        object.__setattr__(self, "observable_states", ordered)

        # A beauty or hero presentation requires the product to be visible enough
        # to present; an identity assertion requires it to be visible at all.
        visibility = self.base.product_visibility
        product_states = set(ordered) & PRODUCT_STATE_CODES  # type: ignore[arg-type]
        if (
            ObservableState.PRODUCT_BEAUTY_STATE_VISIBLE in product_states
            and visibility.value == "NOT_VISIBLE"
        ):
            raise CandidateEvidenceV2Error(
                "a beauty-state observation requires the product to be visibly present"
            )
        if (
            ObservableState.PRODUCT_IDENTITY_VISIBLE in product_states
            and visibility.value == "NOT_VISIBLE"
        ):
            raise CandidateEvidenceV2Error(
                "a product-identity observation contradicts product_visibility "
                "NOT_VISIBLE"
            )

    @property
    def visible_action(self) -> str:
        return self.base.visible_action

    @property
    def visible_result(self) -> str | None:
        return self.base.visible_result

    def has(self, state: ObservableState) -> bool:
        return state in self.observable_states

    def as_dict(self) -> dict[str, object]:
        return {
            **self.base.as_dict(),
            "action_presence": self.action_presence.value,
            "observable_states": [state.value for state in self.observable_states],
        }


@dataclass(frozen=True)
class CandidateEvidenceEntryV2:
    """A v1 entry plus the two structured observation fields.

    ``base`` is a fully validated v1 entry, so the status matrix, the confidence
    bounds, the action chronology, the DIRECT proof obligations and every
    field-consistency rule are enforced by v1. This wrapper adds the v2 semantics
    and the two rules that need both layers: presence must agree with the recorded
    action evidence, and an event must have an action behind it.
    """

    base: CandidateEvidenceEntry
    observations: ObservationsV2 | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.base, CandidateEvidenceEntry):
            raise CandidateEvidenceV2Error("base must be a v1 entry")
        analyzed = self.base.status is EvidenceStatus.ANALYZED
        if analyzed != (self.observations is not None):
            raise CandidateEvidenceV2Error(
                "an ANALYZED entry states its observations and a non-ANALYZED entry "
                "states none"
            )
        if self.observations is None:
            return
        if self.base.observations is None:
            raise CandidateEvidenceV2Error(
                "the v2 observations must extend the v1 observations"
            )
        presence = self.observations.action_presence
        recorded = bool(self.base.action_evidence)
        if presence is ActionPresence.ACTION_PRESENT and not recorded:
            raise CandidateEvidenceV2Error(
                "ACTION_PRESENT requires the action evidence that shows it"
            )
        if presence is ActionPresence.NO_ACTION and recorded:
            raise CandidateEvidenceV2Error(
                "NO_ACTION contradicts recorded action evidence"
            )
        events = set(self.observations.observable_states) & EVENT_STATE_CODES
        if events and presence is not ActionPresence.ACTION_PRESENT:
            names = ", ".join(sorted(state.value for state in events))
            raise CandidateEvidenceV2Error(
                "an event observation requires ACTION_PRESENT; got " + names
            )

    @property
    def candidate_id(self) -> str:
        return self.base.candidate_id

    @property
    def status(self) -> EvidenceStatus:
        return self.base.status

    @property
    def action_presence(self) -> ActionPresence:
        if self.observations is None:
            return ActionPresence.NOT_RECORDED
        return self.observations.action_presence

    @property
    def observable_states(self) -> tuple[ObservableState, ...]:
        if self.observations is None:
            return ()
        return self.observations.observable_states

    @property
    def claims(self):
        return self.base.claims

    @property
    def provenance(self):
        return self.base.provenance

    @property
    def action_evidence(self):
        return self.base.action_evidence

    @property
    def confidence(self):
        return self.base.confidence

    @property
    def evidence_type(self):
        return self.base.evidence_type

    @property
    def risks(self):
        return self.base.risks

    @property
    def rationale(self) -> str:
        """Explanatory text. NON_AUTHORITATIVE_EXPLANATORY_TEXT - never a decision."""

        return self.base.rationale

    def as_dict(self) -> dict[str, object]:
        document = self.base.as_dict()
        document["observations"] = (
            None if self.observations is None else self.observations.as_dict()
        )
        return document


@dataclass(frozen=True)
class CandidateEvidenceV2:
    """One analysis snapshot under the v2 contract."""

    candidate_pool_id: str
    product_facts: ProductFacts
    analysis_run: AnalysisRun
    entries: tuple[CandidateEvidenceEntryV2, ...]

    def __post_init__(self) -> None:
        for index, entry in enumerate(self.entries):
            if not isinstance(entry, CandidateEvidenceEntryV2):
                raise CandidateEvidenceV2Error(
                    f"entries[{index}] must be a v2 entry"
                )
        candidate_ids = [entry.candidate_id for entry in self.entries]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise CandidateEvidenceV2Error("duplicate candidate_id in candidate evidence")
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(self.entries, key=lambda entry: entry.candidate_id)),
        )

    def entry_for(self, candidate_id: str) -> CandidateEvidenceEntryV2:
        for entry in self.entries:
            if entry.candidate_id == candidate_id:
                return entry
        raise CandidateEvidenceV2Error("candidate_id has no evidence entry")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "candidate_pool_id": self.candidate_pool_id,
            "product_facts": self.product_facts.as_dict(),
            "analysis_run": self.analysis_run.as_dict(),
            "entries": [entry.as_dict() for entry in self.entries],
        }


def _migrate_v1_entry_object(entry: CandidateEvidenceEntry) -> CandidateEvidenceEntryV2:
    """One v1 entry object, migrated by the same rule the JSON migration uses.

    The two paths must agree, and the rule is the documented one: no structured
    observation was recorded, so ``observable_states`` is empty and
    ``action_presence`` is derived only from action evidence the v1 entry actually
    carried. An analysed v1 entry therefore gains an observations object carrying
    ``NOT_RECORDED`` (or ``ACTION_PRESENT``) rather than being rejected: the entry is
    well formed, it simply never had the chance to say these two things.
    """

    if not isinstance(entry, CandidateEvidenceEntry):
        raise CandidateEvidenceV2Error("a v1 entry object is required")
    observations: ObservationsV2 | None = None
    if entry.observations is not None:
        observations = ObservationsV2(
            base=entry.observations,
            action_presence=(
                ActionPresence.ACTION_PRESENT
                if entry.action_evidence
                else ActionPresence.NOT_RECORDED
            ),
            observable_states=(),
        )
    return CandidateEvidenceEntryV2(base=entry, observations=observations)


def entry_payload_without_v2_keys(payload: Mapping[str, object]) -> dict[str, object]:
    """The same entry with the two v2 observation keys removed."""

    document = dict(payload)
    observations = document.get("observations")
    if isinstance(observations, dict):
        document["observations"] = {
            key: value
            for key, value in observations.items()
            if key in V1_OBSERVATION_KEYS
        }
    return document


def _build_v1_entry(
    payload: Mapping[str, object],
    *,
    pool_id: str,
    product_facts: ProductFacts,
    analysis_run: AnalysisRun,
) -> CandidateEvidenceEntry:
    document = {
        "schema_version": V1_SCHEMA_VERSION,
        "candidate_pool_id": pool_id,
        "product_facts": product_facts.as_dict(),
        "analysis_run": analysis_run.as_dict(),
        "entries": [entry_payload_without_v2_keys(payload)],
    }
    return parse_candidate_evidence(document).entries[0]


def observations_v2_from_payload(
    payload: Mapping[str, object],
) -> ObservationsV2 | None:
    raw = payload.get("observations")
    if raw is None:
        return None
    item = _object(raw, "observations")
    _exact_keys(item, V2_OBSERVATION_KEYS, "observations")
    base = Observations(
        visible_action=item["visible_action"],  # type: ignore[arg-type]
        visible_result=item["visible_result"],  # type: ignore[arg-type]
        product_visibility=item["product_visibility"],  # type: ignore[arg-type]
        usage_context=item["usage_context"],  # type: ignore[arg-type]
        body_area=item["body_area"],  # type: ignore[arg-type]
        visual_usability=item["visual_usability"],  # type: ignore[arg-type]
        claim_support_class=item["claim_support_class"],  # type: ignore[arg-type]
    )
    states = tuple(
        _enum(raw_state, ObservableState, f"observations.observable_states[{index}]")
        for index, raw_state in enumerate(
            _array(item["observable_states"], "observations.observable_states")
        )
    )
    return ObservationsV2(
        base=base,
        action_presence=_enum(  # type: ignore[arg-type]
            item["action_presence"], ActionPresence, "observations.action_presence"
        ),
        observable_states=states,  # type: ignore[arg-type]
    )


def parse_candidate_evidence_v2(document: object) -> CandidateEvidenceV2:
    """Parse one ``candidate_evidence.v2`` document with exact-key validation."""

    mapping = _object(document, "candidate evidence")
    _exact_keys(mapping, _DOCUMENT_KEYS, "candidate evidence")
    if mapping["schema_version"] != SCHEMA_VERSION:
        if mapping["schema_version"] == V1_SCHEMA_VERSION:
            raise CandidateEvidenceV2Error(
                "this is a v1 document; read it with read_candidate_evidence, which "
                "migrates it, or parse it with parse_candidate_evidence"
            )
        raise CandidateEvidenceV2Error(f"schema_version must be {SCHEMA_VERSION!r}")

    product_facts_mapping = _object(mapping["product_facts"], "product_facts")
    analysis_run_mapping = _object(mapping["analysis_run"], "analysis_run")
    product_facts = ProductFacts(
        ref=product_facts_mapping["ref"],  # type: ignore[arg-type]
        sha256=product_facts_mapping["sha256"],  # type: ignore[arg-type]
        allowed_fact_refs=tuple(
            _array(
                product_facts_mapping["allowed_fact_refs"],
                "product_facts.allowed_fact_refs",
            )
        ),  # type: ignore[arg-type]
    )
    analysis_run = AnalysisRun(
        run_id=analysis_run_mapping["run_id"],  # type: ignore[arg-type]
        provider=analysis_run_mapping["provider"],  # type: ignore[arg-type]
        model=analysis_run_mapping["model"],  # type: ignore[arg-type]
        prompt_contract_version=analysis_run_mapping["prompt_contract_version"],  # type: ignore[arg-type]
    )

    entries: list[CandidateEvidenceEntryV2] = []
    for position, raw in enumerate(_array(mapping["entries"], "entries")):
        item = _object(raw, f"entries[{position}]")
        base = _build_v1_entry(
            item,
            pool_id=mapping["candidate_pool_id"],  # type: ignore[arg-type]
            product_facts=product_facts,
            analysis_run=analysis_run,
        )
        entries.append(
            CandidateEvidenceEntryV2(
                base=base, observations=observations_v2_from_payload(item)
            )
        )
    return CandidateEvidenceV2(
        candidate_pool_id=mapping["candidate_pool_id"],  # type: ignore[arg-type]
        product_facts=product_facts,
        analysis_run=analysis_run,
        entries=tuple(entries),
    )


def render_candidate_evidence_v2(evidence: CandidateEvidenceV2) -> str:
    if not isinstance(evidence, CandidateEvidenceV2):
        raise CandidateEvidenceV2Error("evidence must be CandidateEvidenceV2")
    return (
        json.dumps(evidence.as_dict(), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n"
    )


def as_v1(evidence: CandidateEvidenceV2) -> CandidateEvidence:
    """The same document expressed under v1, with the v2 keys dropped.

    Used for validation: the Pool, cardinality, and frame-containment rules are the
    v1 validator's, and they must not be reimplemented here.
    """

    if not isinstance(evidence, CandidateEvidenceV2):
        raise CandidateEvidenceV2Error("evidence must be CandidateEvidenceV2")
    return CandidateEvidence(
        candidate_pool_id=evidence.candidate_pool_id,
        product_facts=evidence.product_facts,
        analysis_run=evidence.analysis_run,
        entries=tuple(entry.base for entry in evidence.entries),
    )


def validate_candidate_evidence_v2(
    evidence: CandidateEvidenceV2, pool: CandidatePool, catalog: IdentityCatalog
) -> tuple[CandidateIdentity, ...]:
    """Validate a v2 document through the v1 validator, then re-assert v2 shape."""

    if not isinstance(evidence, CandidateEvidenceV2):
        raise CandidateEvidenceV2Error("evidence must be CandidateEvidenceV2")
    resolved = validate_candidate_evidence(as_v1(evidence), pool, catalog)
    for entry in evidence.entries:
        if entry.status is EvidenceStatus.ANALYZED:
            if entry.observations is None:
                raise CandidateEvidenceV2Error(
                    "an ANALYZED entry must carry its v2 observations"
                )
            if entry.action_presence is not entry.observations.action_presence:
                raise CandidateEvidenceV2Error(
                    "the entry and its observations disagree about action presence"
                )
    return resolved


def migrate_v1_document_to_v2(document: object) -> dict[str, object]:
    """Deterministically re-express a v1 document under v2.

    Migration adds the two keys and nothing else. It does **not** invent
    observations: a migrated entry records ``observable_states: []``, which states
    that no structured observation was recorded, and derives ``action_presence``
    from the recorded action evidence - ``ACTION_PRESENT`` when evidence exists,
    ``NOT_RECORDED`` when the document is silent. A v1 entry that says "no action"
    in prose migrates to ``NOT_RECORDED``, never to ``NO_ACTION``: prose is not
    machine truth and migration may not upgrade it.
    """

    mapping = _object(document, "candidate evidence")
    _exact_keys(mapping, _DOCUMENT_KEYS, "candidate evidence")
    if mapping["schema_version"] != V1_SCHEMA_VERSION:
        raise CandidateEvidenceV2Error(
            "only a v1 document can be migrated to v2"
        )
    entries: list[dict[str, object]] = []
    for position, raw in enumerate(_array(mapping["entries"], "entries")):
        item = _object(raw, f"entries[{position}]")
        observations = item.get("observations")
        if observations is None:
            migrated = dict(item)
            migrated["observations"] = None
            entries.append(migrated)
            continue
        payload = _object(observations, f"entries[{position}].observations")
        _exact_keys(payload, V1_OBSERVATION_KEYS, f"entries[{position}].observations")
        migrated_observations = dict(payload)
        migrated_observations["action_presence"] = (
            ActionPresence.ACTION_PRESENT.value
            if item.get("action_evidence")
            else ActionPresence.NOT_RECORDED.value
        )
        migrated_observations["observable_states"] = []
        migrated = dict(item)
        migrated["observations"] = migrated_observations
        entries.append(migrated)
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_pool_id": mapping["candidate_pool_id"],
        "product_facts": mapping["product_facts"],
        "analysis_run": mapping["analysis_run"],
        "entries": entries,
    }


def read_candidate_evidence(document: object) -> CandidateEvidenceV2:
    """Read either version as v2. The one read path a consumer needs.

    A v1 document — as JSON or as an already-parsed object — is migrated by the same
    rule, which is lossless for everything v1 could express and explicit about
    everything it could not: structured observations are empty, and action presence is
    derived only from action evidence v1 actually recorded (``ACTION_PRESENT`` when it
    exists, ``NOT_RECORDED`` otherwise). A consumer therefore never has to ask which
    version it holds, and never has to read prose to fill the gap.
    """

    if isinstance(document, CandidateEvidenceV2):
        return document
    if isinstance(document, CandidateEvidence):
        return CandidateEvidenceV2(
            candidate_pool_id=document.candidate_pool_id,
            product_facts=document.product_facts,
            analysis_run=document.analysis_run,
            entries=tuple(_migrate_v1_entry_object(entry) for entry in document.entries),
        )
    mapping = _object(document, "candidate evidence")
    if mapping.get("schema_version") == SCHEMA_VERSION:
        return parse_candidate_evidence_v2(mapping)
    if mapping.get("schema_version") == V1_SCHEMA_VERSION:
        return parse_candidate_evidence_v2(migrate_v1_document_to_v2(mapping))
    raise CandidateEvidenceV2Error(
        f"schema_version must be {SCHEMA_VERSION!r} or {V1_SCHEMA_VERSION!r}"
    )


def supplied_evidence_text(document: object) -> str:
    """Canonical bytes of an evidence document, in the version it was supplied under.

    An artifact reference names the bytes a decision was made against, so the text has
    to be produced in the supplied version. Rendering a v1 document as v2 would bind a
    decision to an artifact nobody wrote, and would make a frozen v1 reference
    unverifiable.
    """

    if isinstance(document, CandidateEvidenceV2):
        return render_candidate_evidence_v2(document)
    if isinstance(document, CandidateEvidence):
        return render_candidate_evidence(document)
    mapping = _object(document, "candidate evidence")
    if mapping.get("schema_version") == SCHEMA_VERSION:
        return render_candidate_evidence_v2(parse_candidate_evidence_v2(mapping))
    return render_candidate_evidence(parse_candidate_evidence(mapping))


# --------------------------------------------------------------------------- Phase 3 boundary


@dataclass(frozen=True)
class AuthoritativeObservation:
    """One Candidate's machine truth: structured fields and frame coordinates only.

    No prose field appears here. Mutating a ``rationale`` or a ``note`` cannot
    change this object, which is what makes it safe for a planner to consume.
    """

    candidate_id: str
    status: EvidenceStatus
    action_presence: ActionPresence
    observable_states: tuple[ObservableState, ...]
    claims: tuple[tuple[str, ClaimSupport, tuple[tuple[int, int], ...]], ...]
    provenance: tuple[tuple[int, int], ...]
    action_evidence: tuple[tuple[int, int, int, int], ...]
    confidence: float | None
    evidence_type: EvidenceType | None
    product_visibility: str | None
    usage_context: str | None
    body_area: str | None
    visual_usability: str | None
    risk_codes: tuple[str, ...]

    @property
    def claim_fact_refs(self) -> tuple[str, ...]:
        return tuple(fact for fact, _, _ in self.claims)

    def claims_with(self, support: ClaimSupport) -> tuple[str, ...]:
        return tuple(fact for fact, kind, _ in self.claims if kind is support)

    def has_state(self, state: ObservableState) -> bool:
        return state in self.observable_states

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status.value,
            "action_presence": self.action_presence.value,
            "observable_states": [state.value for state in self.observable_states],
            "claims": [
                {
                    "product_fact_ref": fact,
                    "support": kind.value,
                    "provenance": [
                        {"start_frame": start, "end_frame_exclusive": end}
                        for start, end in ranges
                    ],
                }
                for fact, kind, ranges in self.claims
            ],
            "provenance": [
                {"start_frame": start, "end_frame_exclusive": end}
                for start, end in self.provenance
            ],
            "action_evidence": [
                {
                    "preparation_start": preparation,
                    "action_onset": onset,
                    "action_completion": completion,
                    "result_end_exclusive": result_end,
                }
                for preparation, onset, completion, result_end in self.action_evidence
            ],
            "confidence": self.confidence,
            "evidence_type": None if self.evidence_type is None else self.evidence_type.value,
            "product_visibility": self.product_visibility,
            "usage_context": self.usage_context,
            "body_area": self.body_area,
            "visual_usability": self.visual_usability,
            "risk_codes": list(self.risk_codes),
        }


def authoritative_evidence_view(
    evidence: CandidateEvidenceV2 | object,
) -> tuple[AuthoritativeObservation, ...]:
    """The machine-truth view of one evidence document, in Candidate order.

    Accepts a v1 or a v2 document (a v1 document is migrated first). Every field
    listed in :data:`AUTHORITATIVE_FIELDS` is present; every field listed in
    :data:`NON_AUTHORITATIVE_FIELDS` is absent by construction.
    """

    document = read_candidate_evidence(evidence)
    views: list[AuthoritativeObservation] = []
    for entry in document.entries:
        observations = entry.observations
        views.append(
            AuthoritativeObservation(
                candidate_id=entry.candidate_id,
                status=entry.status,
                action_presence=entry.action_presence,
                observable_states=entry.observable_states,
                claims=tuple(
                    (
                        claim.product_fact_ref,
                        claim.support,
                        tuple(
                            (item.start_frame, item.end_frame_exclusive)
                            for item in claim.provenance
                        ),
                    )
                    for claim in (entry.claims or ())
                ),
                provenance=tuple(
                    (item.start_frame, item.end_frame_exclusive)
                    for item in (entry.provenance or ())
                ),
                action_evidence=tuple(
                    (
                        item.preparation_start,
                        item.action_onset,
                        item.action_completion,
                        item.result_end_exclusive,
                    )
                    for item in (entry.action_evidence or ())
                ),
                confidence=entry.confidence,
                evidence_type=entry.evidence_type,
                product_visibility=(
                    None if observations is None else observations.base.product_visibility.value
                ),
                usage_context=(
                    None if observations is None else observations.base.usage_context.value
                ),
                body_area=(
                    None if observations is None else observations.base.body_area.value
                ),
                visual_usability=(
                    None if observations is None else observations.base.visual_usability.value
                ),
                risk_codes=tuple(risk.code.value for risk in (entry.risks or ())),
            )
        )
    return tuple(views)


class MachineSupport(str, Enum):
    """Whether a required visual premise is supported by machine truth."""

    SUPPORTED = "SUPPORTED"
    NOT_MACHINE_SUPPORTED = "NOT_MACHINE_SUPPORTED"


@dataclass(frozen=True)
class SupportCheck:
    """The verdict on one required premise, and exactly what satisfied it."""

    candidate_id: str
    support: MachineSupport
    satisfied_by: tuple[str, ...]
    missing: tuple[str, ...]
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "support": self.support.value,
            "satisfied_by": list(self.satisfied_by),
            "missing": list(self.missing),
            "detail": self.detail,
        }


def check_machine_support(
    observation: AuthoritativeObservation,
    *,
    observable_states: Sequence[ObservableState] = (),
    product_fact_refs: Sequence[str] = (),
    required_support: ClaimSupport = ClaimSupport.DIRECT,
) -> SupportCheck:
    """Whether a required premise is backed by structured truth.

    This is the gate Phase 3 calls. A premise is supported when the structured
    observations contain it, or when a Product Fact claim carries at least the
    required support class. A premise that exists only in prose is
    ``NOT_MACHINE_SUPPORTED`` - which is the honest answer, and the one the
    contract is designed to give rather than guessing from a sentence.
    """

    if not isinstance(observation, AuthoritativeObservation):
        raise CandidateEvidenceV2Error(
            "observation must be an AuthoritativeObservation"
        )
    satisfied: list[str] = []
    missing: list[str] = []
    for state in observable_states:
        member = state if isinstance(state, ObservableState) else _enum(
            state, ObservableState, "observable_states"
        )
        if observation.has_state(member):  # type: ignore[arg-type]
            satisfied.append(f"observation:{member.value}")  # type: ignore[union-attr]
        else:
            missing.append(f"observation:{member.value}")  # type: ignore[union-attr]

    ranks = {
        ClaimSupport.INFERRED: 0,
        ClaimSupport.CONTEXTUAL: 1,
        ClaimSupport.DIRECT: 2,
    }
    for fact_ref in product_fact_refs:
        found = [
            kind
            for fact, kind, _ in observation.claims
            if fact == fact_ref
        ]
        if found and max(ranks[kind] for kind in found) >= ranks[required_support]:
            satisfied.append(f"claim:{fact_ref}:{required_support.value}")
        elif found:
            missing.append(f"claim:{fact_ref}:{required_support.value}")
        else:
            missing.append(f"claim:{fact_ref}")
    if not observable_states and not product_fact_refs:
        raise CandidateEvidenceV2Error(
            "a support check must name at least one required premise"
        )
    if missing:
        return SupportCheck(
            candidate_id=observation.candidate_id,
            support=MachineSupport.NOT_MACHINE_SUPPORTED,
            satisfied_by=tuple(satisfied),
            missing=tuple(missing),
            detail=(
                "the required premise is not present in structured observations or "
                "Product-Fact-bound claims; prose cannot supply it"
            ),
        )
    return SupportCheck(
        candidate_id=observation.candidate_id,
        support=MachineSupport.SUPPORTED,
        satisfied_by=tuple(satisfied),
        missing=(),
        detail="every required premise is present in structured machine truth",
    )
