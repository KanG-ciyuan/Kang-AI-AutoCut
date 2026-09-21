"""Small reusable rules for evidence-led timeline trimming.

This module deliberately does not score footage or author an edit.  It makes
two production invariants explicit: a Candidate is an opportunity window, not
the final timeline duration; and a physical action must retain its observable
result before its timeline boundary may be accepted.

It also holds the shared Editing Intelligence vocabulary that the vNext
companion contracts reuse - narrative roles, frame-exact action evidence, the
coverage tokens a plan must satisfy, and the reason codes that explain a
coverage or redundancy decision. The companion contract that consumes them is
``planning_evidence.v1`` at the end of this file. It is a contract only: this
module still scores nothing, selects nothing, and authors no edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
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
from .candidate_pool import CandidatePool, validate_candidate_membership
from .editing_plan import EditingPlan, validate_editing_plan
from .identity import CandidateIdentity, IdentityCatalog


class EditingIntelligenceError(ValueError):
    """Raised when evidence cannot support a safe timeline decision."""


class NarrativeRole(str, Enum):
    HOOK = "hook"
    IDENTITY = "identity"
    ACTION = "action"
    PROOF = "proof"
    HERO = "hero"
    ENDING = "ending"


@dataclass(frozen=True)
class ActionEvidence:
    """Frame-exact observable phases for one physical action."""

    preparation_start: int
    action_onset: int
    action_completion: int
    result_end_exclusive: int

    def __post_init__(self) -> None:
        values = (
            self.preparation_start,
            self.action_onset,
            self.action_completion,
            self.result_end_exclusive,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise EditingIntelligenceError("action evidence frames must be integers")
        if not (
            self.preparation_start <= self.action_onset
            <= self.action_completion < self.result_end_exclusive
        ):
            raise EditingIntelligenceError("action evidence phases must be chronological")


def useful_action_range(evidence: ActionEvidence) -> tuple[int, int]:
    """Return the shortest action-comprehension range including a result."""

    return evidence.action_onset, evidence.result_end_exclusive


def validate_timeline_range(
    *, role: NarrativeRole, start_frame: int, end_frame_exclusive: int,
    evidence: ActionEvidence | None = None,
) -> None:
    """Reject redundant or incomplete action cuts without prescribing duration."""

    if isinstance(start_frame, bool) or isinstance(end_frame_exclusive, bool):
        raise EditingIntelligenceError("timeline frames must be integers")
    if not isinstance(start_frame, int) or not isinstance(end_frame_exclusive, int):
        raise EditingIntelligenceError("timeline frames must be integers")
    if end_frame_exclusive <= start_frame:
        raise EditingIntelligenceError("timeline range must be non-empty")
    if role in {NarrativeRole.ACTION, NarrativeRole.PROOF, NarrativeRole.HERO}:
        if evidence is None:
            raise EditingIntelligenceError("action-like timeline roles require evidence")
        if start_frame > evidence.action_onset:
            raise EditingIntelligenceError("timeline enters after observable action onset")
        if end_frame_exclusive < evidence.result_end_exclusive:
            raise EditingIntelligenceError("timeline exits before observable result")


# ---------------------------------------------------------------------------
# Planning Evidence v1
# ---------------------------------------------------------------------------
#
# The Editing Plan records which Candidates were chosen, in which order. It does
# not record why, and it must not start recording why: selection belongs to the
# Plan, explanation belongs here.
#
# Planning Evidence is a companion artifact. It is contract-only in this phase -
# nothing in production writes one yet - and it is deliberately not a Sequence
# Planner. It defines the vocabulary a planner will later have to speak, and it
# defines what a planner is forbidden to claim.

PLANNING_EVIDENCE_SCHEMA_VERSION = "planning_evidence.v1"

#: Canonical workspace location suggested for this artifact.
PLANNING_EVIDENCE_CANONICAL_REF = "planning/planning_evidence.json"

_PLAN_ID_PATTERN = re.compile(r"planv1_[0-9a-f]{64}\Z")
_CANDIDATE_ID_PATTERN = re.compile(r"candv1_[0-9a-f]{64}\Z")
#: A logical identifier. The hyphen must stay last in the class: ``._:-_`` would
#: be read as the range ``:`` to ``_`` and would exclude ``-``.
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

_PLANNING_DOCUMENT_KEYS = (
    "schema_version",
    "plan_id",
    "hook_decision",
    "requirements",
    "decisions",
    "coverage_summary",
    "total_duration_frames",
    "planner_run_id",
)
_PLANNING_DECISION_KEYS = (
    "candidate_id",
    "decision",
    "sequence_position",
    "adds_coverage",
    "redundant_with",
    "duration_cost_frames",
    "reason_codes",
    "why",
)
_COVERAGE_SUMMARY_KEYS = (
    "covered_tokens",
    "missing_tokens",
    "redundant_keeps",
    "decision_counts",
)
_DECISION_COUNT_KEYS = ("KEEP", "TRIM", "REJECT")


class PlanningEvidenceContractError(ValueError):
    """Raised when Planning Evidence cannot be consumed safely."""


class CoverageToken(str, Enum):
    """One evidence dimension a plan can cover.

    Tokens are the shared currency between a coverage requirement and the
    Candidate that satisfies it. They are deliberately coarse: a token says
    which question a shot answers, not what the shot looks like.
    """

    PRODUCT_VISIBLE = "PRODUCT_VISIBLE"
    ACTION_ONSET = "ACTION_ONSET"
    OBSERVABLE_RESULT = "OBSERVABLE_RESULT"
    BEFORE_STATE = "BEFORE_STATE"
    AFTER_STATE = "AFTER_STATE"
    USAGE_CONTEXT = "USAGE_CONTEXT"
    CLAIM_SUPPORT_DIRECT = "CLAIM_SUPPORT_DIRECT"
    IDENTITY_SHOT = "IDENTITY_SHOT"
    BODY_AREA = "BODY_AREA"


class PlanDecision(str, Enum):
    """What happened to one considered Candidate.

    ``TRIM`` declares that a Candidate's planned contribution is shorter than
    its identified interval. It does not authorize trimming inside
    ``editing_plan.v1``: the Plan still references complete Candidates, so a
    shorter interval has to exist as a distinct Candidate Identity first.
    """

    KEEP = "KEEP"
    TRIM = "TRIM"
    REJECT = "REJECT"


class CoverageReasonCode(str, Enum):
    """Finite machine vocabulary for coverage and redundancy.

    ``FIRST_DIRECT_PROOF`` and the withholding codes explain a coverage
    decision. The reinforcement codes explain why a redundant Candidate was
    retained anyway - the only six reasons this contract accepts for that.
    """

    FIRST_DIRECT_PROOF = "FIRST_DIRECT_PROOF"
    SEMANTIC_SATURATION = "SEMANTIC_SATURATION"
    NO_NEW_EVIDENCE_DIMENSION = "NO_NEW_EVIDENCE_DIMENSION"
    ANALYSIS_UNAVAILABLE = "ANALYSIS_UNAVAILABLE"
    MULTI_AREA_REQUIREMENT = "MULTI_AREA_REQUIREMENT"
    ACTION_TO_RESULT_RELATION = "ACTION_TO_RESULT_RELATION"
    CONTRAST_OR_OLD_WAY = "CONTRAST_OR_OLD_WAY"
    HOOK_CALLBACK = "HOOK_CALLBACK"
    RHYTHM_BRIDGE_WITH_NO_SEMANTIC_ALTERNATIVE = (
        "RHYTHM_BRIDGE_WITH_NO_SEMANTIC_ALTERNATIVE"
    )
    PRODUCER_EXPLICIT_REINFORCEMENT = "PRODUCER_EXPLICIT_REINFORCEMENT"


#: Reasons that justify adding a newly covered dimension.
COVERAGE_ADD_REASON_CODES = frozenset({CoverageReasonCode.FIRST_DIRECT_PROOF})

#: Reasons that justify keeping a semantically redundant Candidate.
REINFORCEMENT_REASON_CODES = frozenset(
    {
        CoverageReasonCode.MULTI_AREA_REQUIREMENT,
        CoverageReasonCode.ACTION_TO_RESULT_RELATION,
        CoverageReasonCode.CONTRAST_OR_OLD_WAY,
        CoverageReasonCode.HOOK_CALLBACK,
        CoverageReasonCode.RHYTHM_BRIDGE_WITH_NO_SEMANTIC_ALTERNATIVE,
        CoverageReasonCode.PRODUCER_EXPLICIT_REINFORCEMENT,
    }
)

#: Reasons that justify not selecting a considered Candidate.
COVERAGE_WITHHOLD_REASON_CODES = frozenset(
    {
        CoverageReasonCode.SEMANTIC_SATURATION,
        CoverageReasonCode.NO_NEW_EVIDENCE_DIMENSION,
        CoverageReasonCode.ANALYSIS_UNAVAILABLE,
    }
)


def _planning_object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise PlanningEvidenceContractError(f"{label} must be a JSON object")
    return value


def _planning_array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise PlanningEvidenceContractError(f"{label} must be a JSON array")
    return value


def _planning_exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise PlanningEvidenceContractError(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise PlanningEvidenceContractError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


def _planning_plan_id(value: object, label: str = "plan_id") -> str:
    if not isinstance(value, str) or _PLAN_ID_PATTERN.fullmatch(value) is None:
        raise PlanningEvidenceContractError(f"{label} must match planv1_<sha256>")
    return value


def _planning_candidate_id(value: object, label: str = "candidate_id") -> str:
    if not isinstance(value, str) or _CANDIDATE_ID_PATTERN.fullmatch(value) is None:
        raise PlanningEvidenceContractError(f"{label} must match candv1_<sha256>")
    return value


def _planning_token(value: object, label: str) -> str:
    if not isinstance(value, str) or _TOKEN_PATTERN.fullmatch(value) is None:
        raise PlanningEvidenceContractError(
            f"{label} must be a logical token without paths or spaces"
        )
    return value


def _planning_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanningEvidenceContractError(f"{label} must be a non-empty string")
    return value


def _planning_count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PlanningEvidenceContractError(f"{label} must be a non-negative integer")
    return value


def _planning_enum(
    value: object, member_type: type[Enum], label: str
) -> object:
    choices = ", ".join(member.name for member in member_type)
    if not isinstance(value, str):
        raise PlanningEvidenceContractError(f"{label} must be one of: {choices}")
    try:
        return member_type(value)
    except ValueError as exc:
        raise PlanningEvidenceContractError(
            f"{label} must be one of: {choices}"
        ) from exc


def _member_inputs(value: object, member_type: type[Enum], label: str) -> list[object]:
    """Accept a JSON array of names, or a sequence of already-typed members."""

    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PlanningEvidenceContractError(f"{label} must be an array of values")
    return [
        raw.value if isinstance(raw, member_type) else raw for raw in value
    ]


def _coverage_tokens(value: object, label: str) -> tuple[CoverageToken, ...]:
    tokens = tuple(
        _planning_enum(raw, CoverageToken, f"{label}[{index}]")
        for index, raw in enumerate(_member_inputs(value, CoverageToken, label))
    )
    names = [token.value for token in tokens]  # type: ignore[union-attr]
    if len(set(names)) != len(names):
        raise PlanningEvidenceContractError(f"{label} must not repeat a token")
    return tuple(sorted(tokens, key=lambda token: token.value))  # type: ignore[union-attr]


def _reason_codes(value: object, label: str) -> tuple[CoverageReasonCode, ...]:
    codes = tuple(
        _planning_enum(raw, CoverageReasonCode, f"{label}[{index}]")
        for index, raw in enumerate(
            _member_inputs(value, CoverageReasonCode, label)
        )
    )
    names = [code.value for code in codes]  # type: ignore[union-attr]
    if len(set(names)) != len(names):
        raise PlanningEvidenceContractError(f"{label} must not repeat a reason code")
    return tuple(sorted(codes, key=lambda code: code.value))  # type: ignore[union-attr]


@dataclass(frozen=True)
class CoverageSummary:
    """What the plan covers, what it does not, and how it decided."""

    covered_tokens: tuple[CoverageToken, ...]
    missing_tokens: tuple[CoverageToken, ...]
    redundant_keeps: int
    keep_count: int
    trim_count: int
    reject_count: int

    def __post_init__(self) -> None:
        for field in ("covered_tokens", "missing_tokens"):
            object.__setattr__(
                self,
                field,
                _coverage_tokens(
                    getattr(self, field), f"coverage_summary.{field}"
                ),
            )
        for field in ("redundant_keeps", "keep_count", "trim_count", "reject_count"):
            _planning_count(getattr(self, field), f"coverage_summary.{field}")

    def as_dict(self) -> dict[str, object]:
        return {
            "covered_tokens": [token.value for token in self.covered_tokens],
            "missing_tokens": [token.value for token in self.missing_tokens],
            "redundant_keeps": self.redundant_keeps,
            "decision_counts": {
                "KEEP": self.keep_count,
                "TRIM": self.trim_count,
                "REJECT": self.reject_count,
            },
        }


@dataclass(frozen=True)
class PlannedCandidateDecision:
    """One considered Candidate, and the machine-readable reason for its fate.

    ``why`` is human-readable prose and nothing else. Every machine judgement in
    this contract reads ``decision``, ``adds_coverage``, ``redundant_with``,
    ``duration_cost_frames``, and ``reason_codes``. No validator, planner, or
    reviewer may parse ``why`` to reconstruct a decision.
    """

    candidate_id: str
    decision: PlanDecision
    duration_cost_frames: int
    reason_codes: tuple[CoverageReasonCode, ...]
    why: str
    sequence_position: int | None = None
    adds_coverage: tuple[CoverageToken, ...] = ()
    redundant_with: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _planning_candidate_id(self.candidate_id)
        object.__setattr__(
            self,
            "decision",
            _planning_enum(self.decision, PlanDecision, "decisions[].decision"),
        )
        _planning_count(self.duration_cost_frames, "decisions[].duration_cost_frames")
        _planning_text(self.why, "decisions[].why")
        object.__setattr__(
            self,
            "reason_codes",
            _reason_codes(self.reason_codes, "decisions[].reason_codes"),
        )
        if not self.reason_codes:
            raise PlanningEvidenceContractError(
                "every decision must carry at least one reason code"
            )
        object.__setattr__(
            self,
            "adds_coverage",
            _coverage_tokens(self.adds_coverage, "decisions[].adds_coverage"),
        )
        targets = tuple(
            _planning_candidate_id(raw, f"decisions[].redundant_with[{index}]")
            for index, raw in enumerate(self.redundant_with)
        )
        if len(set(targets)) != len(targets):
            raise PlanningEvidenceContractError(
                "decisions[].redundant_with must not repeat a candidate_id"
            )
        if self.candidate_id in targets:
            raise PlanningEvidenceContractError(
                "a Candidate cannot be redundant with itself"
            )
        object.__setattr__(self, "redundant_with", tuple(sorted(targets)))
        if self.sequence_position is not None:
            if (
                isinstance(self.sequence_position, bool)
                or not isinstance(self.sequence_position, int)
                or self.sequence_position < 1
            ):
                raise PlanningEvidenceContractError(
                    "decisions[].sequence_position must be a positive integer or null"
                )
        if self.decision is PlanDecision.REJECT:
            if self.sequence_position is not None:
                raise PlanningEvidenceContractError(
                    "a REJECT decision must not claim a sequence position"
                )
            if self.duration_cost_frames != 0:
                raise PlanningEvidenceContractError(
                    "a REJECT decision must have zero duration cost"
                )
            if self.adds_coverage:
                raise PlanningEvidenceContractError(
                    "a REJECT decision must not claim coverage"
                )
            if self.redundant_with:
                raise PlanningEvidenceContractError(
                    "a REJECT decision must not declare redundancy with the plan"
                )
            if not set(self.reason_codes) <= COVERAGE_WITHHOLD_REASON_CODES:
                raise PlanningEvidenceContractError(
                    "a REJECT decision must use a coverage-withholding reason code"
                )
            return
        if self.sequence_position is None:
            raise PlanningEvidenceContractError(
                "a selected decision must state its sequence position"
            )
        if self.duration_cost_frames <= 0:
            raise PlanningEvidenceContractError(
                "a selected decision must have a positive duration cost"
            )
        if self.redundant_with:
            if self.adds_coverage:
                raise PlanningEvidenceContractError(
                    "a redundant Candidate cannot also claim new coverage"
                )
            if not set(self.reason_codes) <= REINFORCEMENT_REASON_CODES:
                raise PlanningEvidenceContractError(
                    "a redundant Candidate must use a reinforcement reason code"
                )
        elif not self.adds_coverage:
            raise PlanningEvidenceContractError(
                "a non-redundant selected decision must claim coverage tokens"
            )
        elif not set(self.reason_codes) <= (
            COVERAGE_ADD_REASON_CODES | REINFORCEMENT_REASON_CODES
        ):
            raise PlanningEvidenceContractError(
                "a non-redundant selected decision must use a coverage or "
                "reinforcement reason code"
            )

    @property
    def is_selected(self) -> bool:
        return self.decision is not PlanDecision.REJECT

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "decision": self.decision.value,
            "sequence_position": self.sequence_position,
            "adds_coverage": [token.value for token in self.adds_coverage],
            "redundant_with": list(self.redundant_with),
            "duration_cost_frames": self.duration_cost_frames,
            "reason_codes": [code.value for code in self.reason_codes],
            "why": self.why,
        }


@dataclass(frozen=True)
class PlanningEvidence:
    """One planner run's explanation of one Editing Plan."""

    plan_id: str
    hook_decision: ArtifactReference
    requirements: tuple[CoverageToken, ...]
    decisions: tuple[PlannedCandidateDecision, ...]
    coverage_summary: CoverageSummary
    total_duration_frames: int
    planner_run_id: str

    def __post_init__(self) -> None:
        _planning_plan_id(self.plan_id)
        if not isinstance(self.hook_decision, ArtifactReference):
            raise PlanningEvidenceContractError(
                "hook_decision must be an ArtifactReference"
            )
        if not isinstance(self.coverage_summary, CoverageSummary):
            raise PlanningEvidenceContractError(
                "coverage_summary must be a CoverageSummary"
            )
        for index, decision in enumerate(self.decisions):
            if not isinstance(decision, PlannedCandidateDecision):
                raise PlanningEvidenceContractError(
                    f"decisions[{index}] must be a PlannedCandidateDecision"
                )
        candidate_ids = [decision.candidate_id for decision in self.decisions]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise PlanningEvidenceContractError(
                "duplicate candidate_id in planning evidence"
            )
        object.__setattr__(
            self,
            "decisions",
            tuple(sorted(self.decisions, key=lambda item: item.candidate_id)),
        )
        object.__setattr__(
            self,
            "requirements",
            _coverage_tokens(self.requirements, "requirements"),
        )
        if not self.requirements:
            raise PlanningEvidenceContractError("requirements must not be empty")
        _planning_count(self.total_duration_frames, "total_duration_frames")
        _planning_token(self.planner_run_id, "planner_run_id")

    def decision_for(self, candidate_id: str) -> PlannedCandidateDecision:
        requested = _planning_candidate_id(candidate_id)
        for decision in self.decisions:
            if decision.candidate_id == requested:
                return decision
        raise PlanningEvidenceContractError(
            "candidate_id has no planning evidence entry"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": PLANNING_EVIDENCE_SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "hook_decision": self.hook_decision.as_dict(),
            "requirements": [token.value for token in self.requirements],
            "decisions": [decision.as_dict() for decision in self.decisions],
            "coverage_summary": self.coverage_summary.as_dict(),
            "total_duration_frames": self.total_duration_frames,
            "planner_run_id": self.planner_run_id,
        }


def _parse_planned_decision(value: object, label: str) -> PlannedCandidateDecision:
    mapping = _planning_object(value, label)
    _planning_exact_keys(mapping, _PLANNING_DECISION_KEYS, label)
    return PlannedCandidateDecision(
        candidate_id=mapping["candidate_id"],  # type: ignore[arg-type]
        decision=_planning_enum(  # type: ignore[arg-type]
            mapping["decision"], PlanDecision, f"{label}.decision"
        ),
        sequence_position=mapping["sequence_position"],  # type: ignore[arg-type]
        adds_coverage=_coverage_tokens(
            mapping["adds_coverage"], f"{label}.adds_coverage"
        ),
        redundant_with=tuple(
            _planning_array(mapping["redundant_with"], f"{label}.redundant_with")
        ),  # type: ignore[arg-type]
        duration_cost_frames=mapping["duration_cost_frames"],  # type: ignore[arg-type]
        reason_codes=_reason_codes(mapping["reason_codes"], f"{label}.reason_codes"),
        why=mapping["why"],  # type: ignore[arg-type]
    )


def parse_planning_evidence(document: object) -> PlanningEvidence:
    """Parse one ``planning_evidence.v1`` document with exact-key validation."""

    mapping = _planning_object(document, "planning evidence")
    _planning_exact_keys(mapping, _PLANNING_DOCUMENT_KEYS, "planning evidence")
    if mapping["schema_version"] != PLANNING_EVIDENCE_SCHEMA_VERSION:
        raise PlanningEvidenceContractError(
            f"schema_version must be {PLANNING_EVIDENCE_SCHEMA_VERSION!r}"
        )
    try:
        hook_reference = parse_artifact_reference(
            mapping["hook_decision"], label="hook_decision"
        )
    except ArtifactReferenceError as exc:
        raise PlanningEvidenceContractError(str(exc)) from exc

    summary = _planning_object(mapping["coverage_summary"], "coverage_summary")
    _planning_exact_keys(summary, _COVERAGE_SUMMARY_KEYS, "coverage_summary")
    counts = _planning_object(
        summary["decision_counts"], "coverage_summary.decision_counts"
    )
    _planning_exact_keys(
        counts, _DECISION_COUNT_KEYS, "coverage_summary.decision_counts"
    )

    evidence = PlanningEvidence(
        plan_id=mapping["plan_id"],  # type: ignore[arg-type]
        hook_decision=hook_reference,
        requirements=_coverage_tokens(mapping["requirements"], "requirements"),
        decisions=tuple(
            _parse_planned_decision(raw, f"decisions[{index}]")
            for index, raw in enumerate(
                _planning_array(mapping["decisions"], "decisions")
            )
        ),
        coverage_summary=CoverageSummary(
            covered_tokens=_coverage_tokens(
                summary["covered_tokens"], "coverage_summary.covered_tokens"
            ),
            missing_tokens=_coverage_tokens(
                summary["missing_tokens"], "coverage_summary.missing_tokens"
            ),
            redundant_keeps=summary["redundant_keeps"],  # type: ignore[arg-type]
            keep_count=counts["KEEP"],  # type: ignore[arg-type]
            trim_count=counts["TRIM"],  # type: ignore[arg-type]
            reject_count=counts["REJECT"],  # type: ignore[arg-type]
        ),
        total_duration_frames=mapping["total_duration_frames"],  # type: ignore[arg-type]
        planner_run_id=mapping["planner_run_id"],  # type: ignore[arg-type]
    )
    validate_planning_evidence(evidence)
    return evidence


def render_planning_evidence(evidence: PlanningEvidence) -> str:
    if not isinstance(evidence, PlanningEvidence):
        raise PlanningEvidenceContractError(
            "evidence must be PlanningEvidence"
        )
    return (
        json.dumps(evidence.as_dict(), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n"
    )


def planning_evidence_reference(
    evidence: PlanningEvidence, ref: object = PLANNING_EVIDENCE_CANONICAL_REF
) -> ArtifactReference:
    """The ``{ref, sha256}`` pair that binds this exact rendered document."""

    return artifact_reference(ref, render_planning_evidence(evidence))


def validate_planning_evidence_reference(
    evidence: PlanningEvidence, hook_decision_text: object
) -> None:
    """Fail closed when the referenced Hook Decision is stale or never matched.

    The declared ``hook_decision`` reference is compared against the bytes of the
    Hook Decision the caller actually holds. A plan explained against one hook
    revision and presented beside another is rejected, not reconciled.
    """

    if not isinstance(evidence, PlanningEvidence):
        raise PlanningEvidenceContractError("evidence must be PlanningEvidence")
    try:
        validate_reference_binding(
            evidence.hook_decision,
            hook_decision_text,
            label="hook_decision",
        )
    except ArtifactReferenceError as exc:
        raise PlanningEvidenceContractError(str(exc)) from exc


def validate_planning_evidence(evidence: PlanningEvidence) -> None:
    """Validate internal coverage consistency. Fail closed on any contradiction."""

    if not isinstance(evidence, PlanningEvidence):
        raise PlanningEvidenceContractError("evidence must be PlanningEvidence")

    selected = tuple(item for item in evidence.decisions if item.is_selected)
    rejected = tuple(item for item in evidence.decisions if not item.is_selected)

    positions = sorted(
        item.sequence_position for item in selected if item.sequence_position is not None
    )
    if positions != list(range(1, len(selected) + 1)):
        raise PlanningEvidenceContractError(
            "selected sequence_position values must be 1..N without gaps or repeats"
        )

    position_of = {
        item.candidate_id: item.sequence_position for item in selected
    }
    claimed: dict[CoverageToken, str] = {}
    for item in selected:
        for token in item.adds_coverage:
            if token in claimed:
                raise PlanningEvidenceContractError(
                    "a coverage token may be claimed by only one sequence position"
                )
            claimed[token] = item.candidate_id
        for target in item.redundant_with:
            target_position = position_of.get(target)
            if target_position is None:
                raise PlanningEvidenceContractError(
                    "redundant_with must name another selected Candidate"
                )
            if item.sequence_position is None or target_position >= item.sequence_position:
                raise PlanningEvidenceContractError(
                    "redundant_with must name an earlier sequence position"
                )

    required = set(evidence.requirements)
    claimed_tokens = set(claimed)
    if not claimed_tokens <= required:
        raise PlanningEvidenceContractError(
            "a decision claims coverage that the requirements do not ask for"
        )
    summary = evidence.coverage_summary
    if set(summary.covered_tokens) != claimed_tokens:
        raise PlanningEvidenceContractError(
            "coverage_summary.covered_tokens does not match the claimed coverage"
        )
    if set(summary.missing_tokens) != required - claimed_tokens:
        raise PlanningEvidenceContractError(
            "coverage_summary.missing_tokens does not match the unmet requirements"
        )
    if set(summary.covered_tokens) & set(summary.missing_tokens):
        raise PlanningEvidenceContractError(
            "a coverage token cannot be both covered and missing"
        )

    redundant_keeps = sum(
        1
        for item in selected
        if item.decision is PlanDecision.KEEP and item.redundant_with
    )
    if summary.redundant_keeps != redundant_keeps:
        raise PlanningEvidenceContractError(
            "coverage_summary.redundant_keeps does not match the decisions"
        )
    counts = {
        PlanDecision.KEEP: summary.keep_count,
        PlanDecision.TRIM: summary.trim_count,
        PlanDecision.REJECT: summary.reject_count,
    }
    for decision, reported in counts.items():
        actual = sum(1 for item in evidence.decisions if item.decision is decision)
        if reported != actual:
            raise PlanningEvidenceContractError(
                "coverage_summary.decision_counts does not match the decisions"
            )
    if summary.reject_count != len(rejected):
        raise PlanningEvidenceContractError(
            "coverage_summary.decision_counts does not match the decisions"
        )

    total = sum(item.duration_cost_frames for item in selected)
    if evidence.total_duration_frames != total:
        raise PlanningEvidenceContractError(
            "total_duration_frames does not match the selected duration costs"
        )


def validate_planning_evidence_binding(
    evidence: PlanningEvidence,
    plan: EditingPlan,
    pool: CandidatePool,
    catalog: IdentityCatalog,
) -> tuple[CandidateIdentity, ...]:
    """Bind Planning Evidence to its Editing Plan, Pool, and Identity Catalog.

    Returns the resolved Candidate Identities in Plan order. A KEEP must spend
    exactly the Candidate's identified duration; a TRIM must spend strictly less
    and still leave the Plan referencing the complete Candidate.
    """

    if not isinstance(plan, EditingPlan):
        raise PlanningEvidenceContractError("plan must be an EditingPlan")
    if not isinstance(pool, CandidatePool):
        raise PlanningEvidenceContractError("pool must be a CandidatePool")
    if not isinstance(catalog, IdentityCatalog):
        raise PlanningEvidenceContractError("catalog must be an IdentityCatalog")
    validate_planning_evidence(evidence)
    if evidence.plan_id != plan.plan_id:
        raise PlanningEvidenceContractError(
            "plan_id does not match the supplied plan"
        )
    try:
        resolved = validate_editing_plan(plan, pool, catalog)
    except ValueError as exc:
        raise PlanningEvidenceContractError(str(exc)) from exc

    plan_members = [candidate.candidate_id for candidate in resolved]
    for item in evidence.decisions:
        try:
            candidate = validate_candidate_membership(
                pool.pool_id, item.candidate_id, pool, catalog
            )
        except ValueError as exc:
            raise PlanningEvidenceContractError(str(exc)) from exc
        identified = candidate.end_frame_exclusive - candidate.start_frame
        if item.decision is PlanDecision.KEEP:
            if item.duration_cost_frames != identified:
                raise PlanningEvidenceContractError(
                    "a KEEP must spend the Candidate's exact identified duration"
                )
        elif item.decision is PlanDecision.TRIM:
            if item.duration_cost_frames >= identified:
                raise PlanningEvidenceContractError(
                    "a TRIM must spend less than the Candidate's identified duration"
                )
        elif item.candidate_id in plan_members:
            raise PlanningEvidenceContractError(
                "a REJECT decision must not appear in the Editing Plan"
            )

    selected = sorted(
        (item for item in evidence.decisions if item.is_selected),
        key=lambda item: item.sequence_position or 0,
    )
    if len(selected) != len(plan_members):
        raise PlanningEvidenceContractError(
            "selected decisions must account for every Editing Plan segment"
        )
    for position, (item, candidate_id) in enumerate(
        zip(selected, plan_members), start=1
    ):
        if item.candidate_id != candidate_id:
            raise PlanningEvidenceContractError(
                f"sequence position {position} does not match the Editing Plan"
            )
    return tuple(resolved)
