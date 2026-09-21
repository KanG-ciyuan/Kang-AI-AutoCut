"""Hook Decision v1: how an opening was chosen, and on what evidence.

A hook is a commercial premise for the first seconds of a piece. Deciding one is
a creative act, and this module does not perform it: it never calls a provider,
never writes copy, never ranks hypotheses, and never selects one. It defines the
document a human or a supervisor Agent must produce when they do.

The contract exists because "the AI picked an opening" is not reviewable. Every
hypothesis has to state a finite Hook type, the premise in words, the evidence
it requires, the visual support it actually has, and an assessment that says
whether the premise is fact-safe and whether the footage can carry it. A
rejection is not a sentence in prose: it is a code from a closed vocabulary.

The load-bearing rule is the same one Candidate Evidence enforces one layer
down. Declaring visual support is a claim about specific Candidates, and the
``DIRECT`` form of that claim is checked against the Candidate Evidence document
it names - a hypothesis cannot assert direct visual proof of something the
evidence does not actually record.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Mapping, Sequence

from .artifact_reference import (
    ArtifactReference,
    ArtifactReferenceError,
    artifact_reference,
    parse_artifact_reference,
    validate_reference_binding,
)
from .candidate_evidence import (
    BodyArea,
    CandidateEvidence,
    CandidateEvidenceContractError,
    CandidateEvidenceEntry,
    ClaimSupport,
    EvidenceStatus,
    ProductVisibility,
    UsageContext,
    validate_candidate_evidence,
)
from .candidate_evidence_v2 import (
    ActionPresence,
    AuthoritativeObservation,
    ObservableState,
    as_v1,
    authoritative_evidence_view,
    read_candidate_evidence,
    supplied_evidence_text,
)
from .candidate_pool import CandidatePool
from .editing_intelligence import CoverageToken
from .identity import IdentityCatalog


SCHEMA_VERSION = "hook_decision.v1"

#: Canonical workspace location suggested for this artifact.
CANONICAL_REF = "planning/hook_decision.json"

_HOOK_PREFIX = "hookv1_"
_HOOK_DOMAIN = b"ai-autocut:hook:v1\n"
_CANDIDATE_ID_PATTERN = re.compile(r"candv1_[0-9a-f]{64}\Z")
_HOOK_ID_PATTERN = re.compile(r"hookv1_[0-9a-f]{64}\Z")

#: A Hook set is an exploration, not a list. Fewer is not a decision; more is a
#: brainstorm.
MIN_HYPOTHESES = 2
MAX_HYPOTHESES = 5

_DOCUMENT_KEYS = (
    "schema_version",
    "candidate_evidence",
    "brief",
    "hypotheses",
    "selected_hook_id",
    "selection_reason_codes",
    "decision_owner",
)
_HYPOTHESIS_KEYS = (
    "hook_id",
    "hook_type",
    "commercial_premise",
    "required_evidence",
    "available_visual_support",
    "copy_direction",
    "expected_opening_structure",
    "assessment",
)
_ASSESSMENT_KEYS = ("fact_safety", "evidence_coverage", "rejection_codes")
_REQUIREMENT_KEYS = ("coverage_token", "description")
_SUPPORT_KEYS = ("candidate_id", "coverage_token", "support")


class HookDecisionContractError(ValueError):
    """Raised when a Hook Decision cannot be consumed safely."""


class HookType(str, Enum):
    """The finite v1 Hook vocabulary.

    It is finite on purpose. A free-text hook type cannot be counted, compared,
    or reviewed, and the difference between two openings becomes a matter of
    wording rather than of structure.
    """

    PAIN = "PAIN"
    OLD_WAY = "OLD_WAY"
    RESULT = "RESULT"
    CURIOSITY = "CURIOSITY"
    PRODUCT_DIRECT = "PRODUCT_DIRECT"


class FactSafety(str, Enum):
    FACT_SAFE = "FACT_SAFE"
    FACT_UNVERIFIED = "FACT_UNVERIFIED"
    FACT_UNSAFE = "FACT_UNSAFE"


class EvidenceCoverage(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class RejectionCode(str, Enum):
    """Closed vocabulary for why a hypothesis was not chosen."""

    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    NO_OPENING_VISUAL = "NO_OPENING_VISUAL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    DUPLICATES_SELECTED_PREMISE = "DUPLICATES_SELECTED_PREMISE"
    WEAKER_EVIDENCE = "WEAKER_EVIDENCE"
    FACT_UNSAFE_PREMISE = "FACT_UNSAFE_PREMISE"


class SelectionReasonCode(str, Enum):
    """Closed vocabulary for why the selected hypothesis was chosen."""

    FACT_SAFE = "FACT_SAFE"
    DIRECT_VISUAL_SUPPORT = "DIRECT_VISUAL_SUPPORT"
    BRIEF_ALIGNED = "BRIEF_ALIGNED"
    STRONGER_EVIDENCE = "STRONGER_EVIDENCE"


class DecisionOwner(str, Enum):
    """Who owns the hook decision, and whether it has been made yet."""

    HUMAN_PRODUCER = "HUMAN_PRODUCER"
    SUPERVISOR_AGENT = "SUPERVISOR_AGENT"
    UNASSIGNED = "UNASSIGNED"


HOOK_TYPES = frozenset(member.value for member in HookType)
REJECTION_CODES = frozenset(member.value for member in RejectionCode)
SELECTION_REASON_CODES = frozenset(member.value for member in SelectionReasonCode)


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise HookDecisionContractError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise HookDecisionContractError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise HookDecisionContractError(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise HookDecisionContractError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


def _enum(value: object, member_type: type[Enum], label: str) -> object:
    choices = ", ".join(member.name for member in member_type)
    if not isinstance(value, str):
        raise HookDecisionContractError(f"{label} must be one of: {choices}")
    try:
        return member_type(value)
    except ValueError as exc:
        raise HookDecisionContractError(f"{label} must be one of: {choices}") from exc


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HookDecisionContractError(f"{label} must be a non-empty string")
    return value


def _candidate_id(value: object, label: str = "candidate_id") -> str:
    if not isinstance(value, str) or _CANDIDATE_ID_PATTERN.fullmatch(value) is None:
        raise HookDecisionContractError(f"{label} must match candv1_<sha256>")
    return value


def _hook_id(value: object, label: str = "hook_id") -> str:
    if not isinstance(value, str) or _HOOK_ID_PATTERN.fullmatch(value) is None:
        raise HookDecisionContractError(f"{label} must match hookv1_<sha256>")
    return value


def canonical_hook_identity_json(hook_type: object, commercial_premise: object) -> str:
    """Return the exact canonical JSON whose bytes define a Hook ID."""

    member = _enum(hook_type, HookType, "hook_type")
    premise = _text(commercial_premise, "commercial_premise")
    return json.dumps(
        {
            "commercial_premise": premise,
            "hook_type": member.value,  # type: ignore[union-attr]
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def hook_id_for(hook_type: object, commercial_premise: object) -> str:
    """Derive one content-addressed Hook ID from the premise it states.

    Copy direction and expected opening structure are downstream styling and do
    not participate: the same premise, restated differently, is the same hook.
    """

    canonical = canonical_hook_identity_json(hook_type, commercial_premise)
    digest = hashlib.sha256(_HOOK_DOMAIN + canonical.encode("utf-8")).hexdigest()
    return _HOOK_PREFIX + digest


def _coverage_token(value: object, label: str) -> CoverageToken:
    member = _enum(value, CoverageToken, label)
    assert isinstance(member, CoverageToken)
    return member


def _rejection_codes(value: object, label: str) -> tuple[RejectionCode, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise HookDecisionContractError(f"{label} must be an array of reason codes")
    codes = tuple(
        _enum(raw, RejectionCode, f"{label}[{index}]")
        for index, raw in enumerate(value)
    )
    names = [code.value for code in codes]  # type: ignore[union-attr]
    if len(set(names)) != len(names):
        raise HookDecisionContractError(f"{label} must not repeat a rejection code")
    return tuple(sorted(codes, key=lambda code: code.value))  # type: ignore[union-attr]


@dataclass(frozen=True)
class EvidenceRequirement:
    """One evidence dimension a hypothesis needs before it can be used."""

    coverage_token: CoverageToken
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "coverage_token",
            _coverage_token(self.coverage_token, "required_evidence[].coverage_token"),
        )
        _text(self.description, "required_evidence[].description")

    def as_dict(self) -> dict[str, object]:
        return {
            "coverage_token": self.coverage_token.value,
            "description": self.description,
        }


@dataclass(frozen=True)
class VisualSupport:
    """One Candidate offered as support for one required evidence dimension."""

    candidate_id: str
    coverage_token: CoverageToken
    support: ClaimSupport

    def __post_init__(self) -> None:
        _candidate_id(self.candidate_id)
        object.__setattr__(
            self,
            "coverage_token",
            _coverage_token(
                self.coverage_token, "available_visual_support[].coverage_token"
            ),
        )
        object.__setattr__(
            self,
            "support",
            _enum(self.support, ClaimSupport, "available_visual_support[].support"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "coverage_token": self.coverage_token.value,
            "support": self.support.value,
        }


@dataclass(frozen=True)
class HookAssessment:
    """Whether the premise is fact-safe and whether the footage can carry it."""

    fact_safety: FactSafety
    evidence_coverage: EvidenceCoverage
    rejection_codes: tuple[RejectionCode, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fact_safety",
            _enum(self.fact_safety, FactSafety, "assessment.fact_safety"),
        )
        object.__setattr__(
            self,
            "evidence_coverage",
            _enum(
                self.evidence_coverage,
                EvidenceCoverage,
                "assessment.evidence_coverage",
            ),
        )
        object.__setattr__(
            self,
            "rejection_codes",
            _rejection_codes(self.rejection_codes, "assessment.rejection_codes"),
        )
        if (
            self.fact_safety is not FactSafety.FACT_SAFE
            and not self.rejection_codes
        ):
            raise HookDecisionContractError(
                "a hypothesis that is not fact-safe must state a rejection code"
            )
        if (
            self.evidence_coverage is EvidenceCoverage.INSUFFICIENT
            and RejectionCode.INSUFFICIENT_EVIDENCE not in self.rejection_codes
        ):
            raise HookDecisionContractError(
                "INSUFFICIENT coverage requires the INSUFFICIENT_EVIDENCE code"
            )
        if (
            self.fact_safety is FactSafety.FACT_UNSAFE
            and RejectionCode.UNSUPPORTED_CLAIM not in self.rejection_codes
        ):
            raise HookDecisionContractError(
                "FACT_UNSAFE requires the UNSUPPORTED_CLAIM code"
            )

    @property
    def is_rejected(self) -> bool:
        return bool(self.rejection_codes)

    def as_dict(self) -> dict[str, object]:
        return {
            "fact_safety": self.fact_safety.value,
            "evidence_coverage": self.evidence_coverage.value,
            "rejection_codes": [code.value for code in self.rejection_codes],
        }


@dataclass(frozen=True)
class HookHypothesis:
    """One candidate opening, stated so that it can be reviewed or rejected."""

    hook_type: HookType
    commercial_premise: str
    required_evidence: tuple[EvidenceRequirement, ...]
    copy_direction: str
    expected_opening_structure: str
    assessment: HookAssessment
    available_visual_support: tuple[VisualSupport, ...] = ()
    hook_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "hook_type", _enum(self.hook_type, HookType, "hook_type")
        )
        _text(self.commercial_premise, "commercial_premise")
        _text(self.copy_direction, "copy_direction")
        _text(self.expected_opening_structure, "expected_opening_structure")
        expected_id = hook_id_for(self.hook_type, self.commercial_premise)
        if self.hook_id is None:
            object.__setattr__(self, "hook_id", expected_id)
        elif _hook_id(self.hook_id) != expected_id:
            raise HookDecisionContractError(
                "hook_id does not match its canonical Hook type and premise"
            )
        if not isinstance(self.assessment, HookAssessment):
            raise HookDecisionContractError("assessment must be a HookAssessment")

        requirements = tuple(self.required_evidence)
        if not requirements:
            raise HookDecisionContractError(
                "a hypothesis must state at least one evidence requirement"
            )
        for index, item in enumerate(requirements):
            if not isinstance(item, EvidenceRequirement):
                raise HookDecisionContractError(
                    f"required_evidence[{index}] must be an EvidenceRequirement"
                )
        tokens = [item.coverage_token for item in requirements]
        if len(set(tokens)) != len(tokens):
            raise HookDecisionContractError(
                "required_evidence must not repeat a coverage token"
            )
        object.__setattr__(
            self,
            "required_evidence",
            tuple(sorted(requirements, key=lambda item: item.coverage_token.value)),
        )

        support = tuple(self.available_visual_support)
        for index, item in enumerate(support):
            if not isinstance(item, VisualSupport):
                raise HookDecisionContractError(
                    f"available_visual_support[{index}] must be a VisualSupport"
                )
            if item.coverage_token not in tokens:
                raise HookDecisionContractError(
                    "declared visual support must answer a stated evidence requirement"
                )
        pairs = [(item.candidate_id, item.coverage_token.value) for item in support]
        if len(set(pairs)) != len(pairs):
            raise HookDecisionContractError(
                "available_visual_support must not repeat a Candidate and token pair"
            )
        object.__setattr__(
            self,
            "available_visual_support",
            tuple(
                sorted(
                    support,
                    key=lambda item: (item.coverage_token.value, item.candidate_id),
                )
            ),
        )
        if not support and (
            RejectionCode.NO_OPENING_VISUAL not in self.assessment.rejection_codes
        ):
            raise HookDecisionContractError(
                "a hypothesis with no visual support must state NO_OPENING_VISUAL"
            )
        if self.assessment.evidence_coverage is EvidenceCoverage.FULL:
            supported = {item.coverage_token for item in support}
            unsupported = sorted(
                token.value for token in tokens if token not in supported
            )
            if unsupported:
                raise HookDecisionContractError(
                    "FULL evidence coverage requires support for every requirement; "
                    "unsupported: " + ", ".join(unsupported)
                )

    @property
    def is_rejected(self) -> bool:
        return self.assessment.is_rejected

    def as_dict(self) -> dict[str, object]:
        return {
            "hook_id": self.hook_id,
            "hook_type": self.hook_type.value,
            "commercial_premise": self.commercial_premise,
            "required_evidence": [item.as_dict() for item in self.required_evidence],
            "available_visual_support": [
                item.as_dict() for item in self.available_visual_support
            ],
            "copy_direction": self.copy_direction,
            "expected_opening_structure": self.expected_opening_structure,
            "assessment": self.assessment.as_dict(),
        }


@dataclass(frozen=True)
class HookDecision:
    """One recorded hook decision over one Candidate Evidence revision."""

    candidate_evidence: ArtifactReference
    brief: ArtifactReference
    hypotheses: tuple[HookHypothesis, ...]
    selection_reason_codes: tuple[SelectionReasonCode, ...] = ()
    selected_hook_id: str | None = None
    decision_owner: DecisionOwner = DecisionOwner.UNASSIGNED

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_evidence, ArtifactReference):
            raise HookDecisionContractError(
                "candidate_evidence must be an ArtifactReference"
            )
        if not isinstance(self.brief, ArtifactReference):
            raise HookDecisionContractError("brief must be an ArtifactReference")
        object.__setattr__(
            self,
            "decision_owner",
            _enum(self.decision_owner, DecisionOwner, "decision_owner"),
        )

        hypotheses = tuple(self.hypotheses)
        for index, item in enumerate(hypotheses):
            if not isinstance(item, HookHypothesis):
                raise HookDecisionContractError(
                    f"hypotheses[{index}] must be a HookHypothesis"
                )
        ordered = tuple(sorted(hypotheses, key=lambda item: item.hook_id or ""))
        hook_ids = [item.hook_id for item in ordered]
        if len(set(hook_ids)) != len(hook_ids):
            raise HookDecisionContractError("duplicate hook_id in hook decision")
        object.__setattr__(self, "hypotheses", ordered)
        for index, item in enumerate(ordered):
            if item.hook_id is None:
                raise HookDecisionContractError(
                    f"hypotheses[{index}] must carry a hook_id"
                )

        codes = tuple(
            _enum(raw, SelectionReasonCode, f"selection_reason_codes[{index}]")
            for index, raw in enumerate(self.selection_reason_codes)
        )
        names = [code.value for code in codes]  # type: ignore[union-attr]
        if len(set(names)) != len(names):
            raise HookDecisionContractError(
                "selection_reason_codes must not repeat a reason code"
            )
        object.__setattr__(
            self,
            "selection_reason_codes",
            tuple(sorted(codes, key=lambda code: code.value)),  # type: ignore[union-attr]
        )
        if self.selected_hook_id is not None:
            _hook_id(self.selected_hook_id, "selected_hook_id")

    def _validate_selection(self, hypotheses: tuple[HookHypothesis, ...]) -> None:
        """Set-level rules: a decision must be complete and internally honest.

        These live behind :func:`validate_hook_decision` rather than
        ``__post_init__`` because they describe the whole hook set, exactly as
        Pool cardinality is checked outside the Candidate Evidence record.
        """

        rejection_names = [code.value for code in self.selection_reason_codes]
        if self.selected_hook_id is None:
            if self.decision_owner is DecisionOwner.UNASSIGNED:
                if rejection_names:
                    raise HookDecisionContractError(
                        "an unassigned decision must not state selection reasons"
                    )
                return
            if rejection_names:
                raise HookDecisionContractError(
                    "a decision with no selected hook must not state selection reasons"
                )
            for item in hypotheses:
                if not item.is_rejected:
                    raise HookDecisionContractError(
                        "a decided hook set must reject every unselected hypothesis"
                    )
            return

        selected_id = self.selected_hook_id
        selected = next(
            (item for item in hypotheses if item.hook_id == selected_id), None
        )
        if selected is None:
            raise HookDecisionContractError(
                "selected_hook_id does not name a hypothesis in this document"
            )
        if self.decision_owner is DecisionOwner.UNASSIGNED:
            raise HookDecisionContractError(
                "a selected hook requires an assigned decision owner"
            )
        if not rejection_names:
            raise HookDecisionContractError(
                "a selected hook requires at least one selection reason code"
            )
        if selected.assessment.fact_safety is not FactSafety.FACT_SAFE:
            raise HookDecisionContractError(
                "a hypothesis that is not fact-safe must not be selected"
            )
        if selected.assessment.evidence_coverage is EvidenceCoverage.INSUFFICIENT:
            raise HookDecisionContractError(
                "a hypothesis with insufficient evidence must not be selected"
            )
        if selected.is_rejected:
            raise HookDecisionContractError(
                "a rejected hypothesis must not be selected"
            )
        for item in hypotheses:
            if item.hook_id == selected_id:
                continue
            if not item.is_rejected:
                raise HookDecisionContractError(
                    "a selected hook requires a rejection code on every other hypothesis"
                )
            if item.hook_type is selected.hook_type and (
                RejectionCode.DUPLICATES_SELECTED_PREMISE
                not in item.assessment.rejection_codes
            ):
                raise HookDecisionContractError(
                    "a hypothesis sharing the selected Hook type must state "
                    "DUPLICATES_SELECTED_PREMISE"
                )

    def hypothesis_for(self, hook_id: object) -> HookHypothesis:
        requested = _hook_id(hook_id)
        for item in self.hypotheses:
            if item.hook_id == requested:
                return item
        raise HookDecisionContractError("hook_id is not part of this decision")

    @property
    def selected_hypothesis(self) -> HookHypothesis | None:
        if self.selected_hook_id is None:
            return None
        return self.hypothesis_for(self.selected_hook_id)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "candidate_evidence": self.candidate_evidence.as_dict(),
            "brief": self.brief.as_dict(),
            "hypotheses": [item.as_dict() for item in self.hypotheses],
            "selected_hook_id": self.selected_hook_id,
            "selection_reason_codes": [
                code.value for code in self.selection_reason_codes
            ],
            "decision_owner": self.decision_owner.value,
        }


def parse_evidence_requirements(
    value: object, label: str
) -> tuple[EvidenceRequirement, ...]:
    requirements: list[EvidenceRequirement] = []
    for index, raw in enumerate(_array(value, label)):
        item = _object(raw, f"{label}[{index}]")
        _exact_keys(item, _REQUIREMENT_KEYS, f"{label}[{index}]")
        requirements.append(
            EvidenceRequirement(
                coverage_token=item["coverage_token"],  # type: ignore[arg-type]
                description=item["description"],  # type: ignore[arg-type]
            )
        )
    return tuple(requirements)


def parse_visual_support(value: object, label: str) -> tuple[VisualSupport, ...]:
    support: list[VisualSupport] = []
    for index, raw in enumerate(_array(value, label)):
        item = _object(raw, f"{label}[{index}]")
        _exact_keys(item, _SUPPORT_KEYS, f"{label}[{index}]")
        support.append(
            VisualSupport(
                candidate_id=item["candidate_id"],  # type: ignore[arg-type]
                coverage_token=item["coverage_token"],  # type: ignore[arg-type]
                support=item["support"],  # type: ignore[arg-type]
            )
        )
    return tuple(support)


def _parse_hypothesis(value: object, label: str) -> HookHypothesis:
    mapping = _object(value, label)
    _exact_keys(mapping, _HYPOTHESIS_KEYS, label)
    assessment = _object(mapping["assessment"], f"{label}.assessment")
    _exact_keys(assessment, _ASSESSMENT_KEYS, f"{label}.assessment")
    return HookHypothesis(
        hook_id=mapping["hook_id"],  # type: ignore[arg-type]
        hook_type=mapping["hook_type"],  # type: ignore[arg-type]
        commercial_premise=mapping["commercial_premise"],  # type: ignore[arg-type]
        required_evidence=parse_evidence_requirements(
            mapping["required_evidence"], f"{label}.required_evidence"
        ),
        available_visual_support=parse_visual_support(
            mapping["available_visual_support"], f"{label}.available_visual_support"
        ),
        copy_direction=mapping["copy_direction"],  # type: ignore[arg-type]
        expected_opening_structure=mapping["expected_opening_structure"],  # type: ignore[arg-type]
        assessment=HookAssessment(
            fact_safety=assessment["fact_safety"],  # type: ignore[arg-type]
            evidence_coverage=assessment["evidence_coverage"],  # type: ignore[arg-type]
            rejection_codes=_rejection_codes(
                assessment["rejection_codes"], f"{label}.assessment.rejection_codes"
            ),
        ),
    )


def parse_hook_decision(document: object) -> HookDecision:
    """Parse one ``hook_decision.v1`` document with exact-key validation."""

    mapping = _object(document, "hook decision")
    _exact_keys(mapping, _DOCUMENT_KEYS, "hook decision")
    if mapping["schema_version"] != SCHEMA_VERSION:
        raise HookDecisionContractError(f"schema_version must be {SCHEMA_VERSION!r}")
    try:
        candidate_evidence = parse_artifact_reference(
            mapping["candidate_evidence"], label="candidate_evidence"
        )
        brief = parse_artifact_reference(mapping["brief"], label="brief")
    except ArtifactReferenceError as exc:
        raise HookDecisionContractError(str(exc)) from exc
    decision = HookDecision(
        candidate_evidence=candidate_evidence,
        brief=brief,
        hypotheses=tuple(
            _parse_hypothesis(raw, f"hypotheses[{index}]")
            for index, raw in enumerate(_array(mapping["hypotheses"], "hypotheses"))
        ),
        selected_hook_id=mapping["selected_hook_id"],  # type: ignore[arg-type]
        selection_reason_codes=tuple(
            _array(mapping["selection_reason_codes"], "selection_reason_codes")
        ),  # type: ignore[arg-type]
        decision_owner=mapping["decision_owner"],  # type: ignore[arg-type]
    )
    validate_hook_decision(decision)
    return decision


def render_hook_decision(decision: HookDecision) -> str:
    if not isinstance(decision, HookDecision):
        raise HookDecisionContractError("decision must be a HookDecision")
    return (
        json.dumps(decision.as_dict(), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n"
    )


def hook_decision_reference(
    decision: HookDecision, ref: object = CANONICAL_REF
) -> ArtifactReference:
    """The ``{ref, sha256}`` pair that binds this exact rendered document."""

    return artifact_reference(ref, render_hook_decision(decision))


def validate_hook_decision_reference(
    decision: HookDecision, candidate_evidence_text: object
) -> None:
    """Fail closed when the referenced Candidate Evidence is stale or never matched.

    The declared ``candidate_evidence`` reference is compared against the bytes of
    the Candidate Evidence the caller actually holds, so a hook chosen from one
    evidence revision cannot be presented beside another.
    """

    if not isinstance(decision, HookDecision):
        raise HookDecisionContractError("decision must be a HookDecision")
    try:
        validate_reference_binding(
            decision.candidate_evidence,
            candidate_evidence_text,
            label="candidate_evidence",
        )
    except ArtifactReferenceError as exc:
        raise HookDecisionContractError(str(exc)) from exc


def validate_hook_decision(decision: HookDecision) -> None:
    """Validate a Hook Decision on its own terms. Fail closed.

    Structural rules were already enforced when each record was constructed.
    This gate adds the rules that only make sense for the whole hook set: the
    2-5 hypothesis bound, and whether the recorded selection is complete,
    owned, and consistent with the assessments it cites.
    """

    if not isinstance(decision, HookDecision):
        raise HookDecisionContractError("decision must be a HookDecision")
    if not MIN_HYPOTHESES <= len(decision.hypotheses) <= MAX_HYPOTHESES:
        raise HookDecisionContractError(
            f"hypotheses must contain between {MIN_HYPOTHESES} and "
            f"{MAX_HYPOTHESES} entries"
        )
    decision._validate_selection(decision.hypotheses)


#: Structured observations that constitute a visible result. Used by the structured
#: predicate below, and by the Phase 3 gate, which admits a result only from these: a
#: sentence is not evidence, and Phase 2.5 showed that an attractive shot with no
#: change in it can still be described in confident prose.
RESULT_OBSERVATIONS = (
    ObservableState.CLEAN_STATE_VISIBLE,
    ObservableState.STATE_CHANGE_VISIBLE,
    ObservableState.BEFORE_AFTER_RELATION_VISIBLE,
)

#: Product visibility values that count as the product being on screen.
PRODUCT_ON_SCREEN = ("PARTIAL", "CLEAR", "HERO")


def direct_support_satisfied(
    entry: CandidateEvidenceEntry, token: CoverageToken
) -> bool:
    """Whether Candidate Evidence v1 records direct support for one coverage token.

    This is the frozen v1 rule, kept exactly as the contract defined it. Phase 3 does
    **not** narrow it: an artifact that was directly supported before Phase 3 exists is
    still directly supported, including a result stated in ``visible_result``. The
    stricter, structured-only policy Phase 3 applies to its own hooks lives in
    ``hook_planning`` and is a decision about new hooks, not a retroactive change to
    what old evidence means.
    """

    if not isinstance(entry, CandidateEvidenceEntry):
        raise HookDecisionContractError(
            "direct support must be checked against a Candidate Evidence entry"
        )
    if entry.status is not EvidenceStatus.ANALYZED:
        return False
    observations = entry.observations
    assert observations is not None  # guaranteed by the ANALYZED status
    if token is CoverageToken.PRODUCT_VISIBLE:
        return observations.product_visibility in {
            ProductVisibility.PARTIAL,
            ProductVisibility.CLEAR,
            ProductVisibility.HERO,
        }
    if token is CoverageToken.IDENTITY_SHOT:
        return observations.product_visibility is ProductVisibility.HERO
    if token is CoverageToken.ACTION_ONSET:
        return bool(entry.action_evidence)
    if token is CoverageToken.OBSERVABLE_RESULT:
        return bool(entry.action_evidence) and observations.visible_result is not None
    if token is CoverageToken.BEFORE_STATE:
        return observations.usage_context is UsageContext.PRE_USE
    if token is CoverageToken.AFTER_STATE:
        return observations.usage_context is UsageContext.POST_USE
    if token is CoverageToken.USAGE_CONTEXT:
        return observations.usage_context is not UsageContext.UNKNOWN
    if token is CoverageToken.BODY_AREA:
        return observations.body_area not in {BodyArea.UNKNOWN, BodyArea.NOT_APPLICABLE}
    if token is CoverageToken.CLAIM_SUPPORT_DIRECT:
        return any(
            claim.support is ClaimSupport.DIRECT for claim in entry.claims or ()
        )
    return False


def structured_support_satisfied(
    view: AuthoritativeObservation, token: CoverageToken
) -> bool:
    """The same question answered from structured evidence.

    Deliberately stricter than :func:`direct_support_satisfied` in two places, and
    identical everywhere else: an action or a result requires ``ACTION_PRESENT``, and a
    result requires a structured result observation rather than a sentence. Phase 3
    reads its eligibility through this predicate; ``NO_ACTION`` and ``NOT_RECORDED``
    can never be mistaken for evidence that something happened.
    """

    if not isinstance(view, AuthoritativeObservation):
        raise HookDecisionContractError(
            "structured support must be checked against an authoritative observation"
        )
    action_present = view.action_presence is ActionPresence.ACTION_PRESENT
    if token is CoverageToken.PRODUCT_VISIBLE:
        return view.product_visibility in PRODUCT_ON_SCREEN
    if token is CoverageToken.IDENTITY_SHOT:
        return view.product_visibility == "HERO"
    if token is CoverageToken.ACTION_ONSET:
        return action_present
    if token is CoverageToken.OBSERVABLE_RESULT:
        return action_present and any(
            state in view.observable_states for state in RESULT_OBSERVATIONS
        )
    if token is CoverageToken.BEFORE_STATE:
        return view.usage_context == "PRE_USE"
    if token is CoverageToken.AFTER_STATE:
        return view.usage_context == "POST_USE"
    if token is CoverageToken.USAGE_CONTEXT:
        return view.usage_context not in (None, "UNKNOWN")
    if token is CoverageToken.BODY_AREA:
        return view.body_area not in (None, "UNKNOWN", "NOT_APPLICABLE")
    if token is CoverageToken.CLAIM_SUPPORT_DIRECT:
        return any(kind is ClaimSupport.DIRECT for _, kind, _ in view.claims)
    return False


def support_recorded(
    entry: CandidateEvidenceEntry,
    view: AuthoritativeObservation,
    token: CoverageToken,
) -> bool:
    """Whether the evidence records a declared support, in either contract version.

    The disjunction is the compatibility rule: it is never narrower than the frozen v1
    check, because v1 text is still read the v1 way, and it can also be satisfied from
    structured evidence a v2 document records. It is therefore not a new permission for
    v1 artifacts - on a v1 document the structured half is always false.
    """

    return direct_support_satisfied(entry, token) or structured_support_satisfied(
        view, token
    )


def validate_hook_decision_against_evidence(
    decision: HookDecision,
    evidence: object,
    pool: CandidatePool,
    catalog: IdentityCatalog,
) -> None:
    """Validate declared visual support against the evidence it names.

    This is the anti-fabrication gate of the Hook layer. The declared Candidate
    Evidence reference must match the supplied bytes, the evidence and the Pool must
    validate together, every Candidate offered as support must be an analyzed member,
    and ``DIRECT`` support must describe something the evidence records.

    The evidence may be a v1 or a v2 document, or an already-parsed one: both are read
    through the unified reader, the frozen v1 rules are applied to the v1 projection
    unchanged, and the structured view answers what v1 could not express.
    """

    if not isinstance(decision, HookDecision):
        raise HookDecisionContractError("decision must be a HookDecision")
    try:
        read = read_candidate_evidence(evidence)
    except CandidateEvidenceContractError as exc:
        raise HookDecisionContractError(
            f"evidence must be a Candidate Evidence document: {exc}"
        ) from exc
    frozen = as_v1(read)
    try:
        validate_candidate_evidence(frozen, pool, catalog)
    except CandidateEvidenceContractError as exc:
        raise HookDecisionContractError(str(exc)) from exc
    try:
        validate_reference_binding(
            decision.candidate_evidence,
            supplied_evidence_text(evidence),
            label="candidate_evidence",
        )
    except ArtifactReferenceError as exc:
        raise HookDecisionContractError(str(exc)) from exc

    entries = {entry.candidate_id: entry for entry in frozen.entries}
    views = {view.candidate_id: view for view in authoritative_evidence_view(read)}
    for hypothesis in decision.hypotheses:
        for item in hypothesis.available_visual_support:
            entry = entries.get(item.candidate_id)
            view = views.get(item.candidate_id)
            if entry is None or view is None:
                raise HookDecisionContractError(
                    "declared visual support names a Candidate with no evidence entry"
                )
            if entry.status is not EvidenceStatus.ANALYZED:
                raise HookDecisionContractError(
                    "declared visual support requires an ANALYZED Candidate"
                )
            if item.support is ClaimSupport.DIRECT and not support_recorded(
                entry, view, item.coverage_token
            ):
                raise HookDecisionContractError(
                    "declared DIRECT visual support is not recorded in the "
                    "Candidate Evidence"
                )
