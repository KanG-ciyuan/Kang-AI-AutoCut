"""Candidate Evidence v1: the analysis companion to a Candidate Pool.

A Candidate Pool answers membership only. Everything a model or a human observes
about a Candidate - the visible action, the visible result, whether the product is
on screen, which commercial claim those frames can actually carry - has to live
somewhere else, because putting it in the Pool would change what a Pool means.
This module is that somewhere else.

Two responsibilities are deliberately separated:

* **Deterministic fields** are validated against the frozen identity chain.
  Candidate ID, Pool ID, the exact frame ranges, chronology, the Product Fact
  allow-list, enum vocabulary, confidence bounds, and run metadata are all
  checked here, and any violation fails closed.
* **Model-owned semantic fields** are carried, not invented. This module never
  calls a provider, never reads media, and never decides what the footage shows.
  A caller supplies those values, and Phase 1 supplies them only from fixtures.

The rule the contract exists to enforce is: a claim may be judged, but it may not
be asserted without evidence. ``DIRECT`` support must be bound to real frames of
the exact Candidate it names, commercial claims must name a Product Fact that the
document's own allow-list permits, and inference may not present itself as
something the camera proved.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import math
import re
from typing import Mapping, Sequence

from .artifact_reference import (
    ArtifactReference,
    ArtifactReferenceError,
    artifact_reference,
    validate_logical_ref,
    validate_reference_binding,
    validate_sha256,
)
from .candidate_pool import CandidatePool, validate_candidate_pool
from .editing_intelligence import (
    ActionEvidence,
    EditingIntelligenceError,
    NarrativeRole,
)
from .frame_boundary import FrameBoundaryError, SourceRange
from .identity import CandidateIdentity, IdentityCatalog


SCHEMA_VERSION = "candidate_evidence.v1"

#: Canonical workspace location suggested for this artifact.
CANONICAL_REF = "analysis/candidate_evidence.json"

_CANDIDATE_ID_PATTERN = re.compile(r"candv1_[0-9a-f]{64}\Z")
_POOL_ID_PATTERN = re.compile(r"poolv1_[0-9a-f]{64}\Z")
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-_]{0,127}\Z")
_PROMPT_CONTRACT_PATTERN = re.compile(r"[a-z][a-z0-9_]*\.v[0-9]+\Z")

_DOCUMENT_KEYS = (
    "schema_version",
    "candidate_pool_id",
    "product_facts",
    "analysis_run",
    "entries",
)
_PRODUCT_FACT_KEYS = ("ref", "sha256", "allowed_fact_refs")
_ANALYSIS_RUN_KEYS = ("run_id", "provider", "model", "prompt_contract_version")
_ENTRY_KEYS = (
    "candidate_id",
    "status",
    "observations",
    "action_evidence",
    "claims",
    "evidence_type",
    "confidence",
    "provenance",
    "role_affinities",
    "risks",
    "rationale",
)
#: Entry keys that carry analysis payload. An entry that was not analysed may
#: not populate any of them.
_ENTRY_PAYLOAD_KEYS = _ENTRY_KEYS[2:-1]
_OBSERVATION_KEYS = (
    "visible_action",
    "visible_result",
    "product_visibility",
    "usage_context",
    "body_area",
    "visual_usability",
    "claim_support_class",
)
_RANGE_KEYS = ("start_frame", "end_frame_exclusive")
_ACTION_KEYS = (
    "preparation_start",
    "action_onset",
    "action_completion",
    "result_end_exclusive",
)
_CLAIM_KEYS = ("product_fact_ref", "support", "provenance", "note")
_RISK_KEYS = ("code", "severity", "note")


class CandidateEvidenceContractError(ValueError):
    """Raised when Candidate Evidence cannot be consumed safely."""


class EvidenceStatus(str, Enum):
    """Whether one Candidate was analysed at all.

    A Pool member that was not analysed must still appear with one of the
    non-``ANALYZED`` statuses. Silence is not a permitted outcome.
    """

    ANALYZED = "ANALYZED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    UNKNOWN = "UNKNOWN"


class EvidenceType(str, Enum):
    DIRECT_DEMONSTRATION = "DIRECT_DEMONSTRATION"
    CONTEXTUAL_USAGE = "CONTEXTUAL_USAGE"
    RESULT_STATE = "RESULT_STATE"
    PRODUCT_IDENTITY = "PRODUCT_IDENTITY"
    COMPARISON = "COMPARISON"
    NONE = "NONE"


class ClaimSupport(str, Enum):
    """How strongly the named frames support one Product Fact.

    ``DIRECT`` asserts that the frames themselves show it. ``CONTEXTUAL`` says
    they are consistent with it. ``INFERRED`` says it was concluded, not seen.
    """

    DIRECT = "DIRECT"
    CONTEXTUAL = "CONTEXTUAL"
    INFERRED = "INFERRED"


class ProductVisibility(str, Enum):
    NOT_VISIBLE = "NOT_VISIBLE"
    PARTIAL = "PARTIAL"
    CLEAR = "CLEAR"
    HERO = "HERO"


class UsageContext(str, Enum):
    IN_USE = "IN_USE"
    PRE_USE = "PRE_USE"
    POST_USE = "POST_USE"
    PACKAGING = "PACKAGING"
    LIFESTYLE = "LIFESTYLE"
    UNKNOWN = "UNKNOWN"


class BodyArea(str, Enum):
    FACE = "FACE"
    HAIR = "HAIR"
    SCALP = "SCALP"
    HANDS = "HANDS"
    BODY = "BODY"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class VisualUsability(str, Enum):
    USABLE = "USABLE"
    USABLE_WITH_TRIM = "USABLE_WITH_TRIM"
    UNUSABLE = "UNUSABLE"


class ClaimSupportClass(str, Enum):
    NONE = "NONE"
    CONTEXTUAL_ONLY = "CONTEXTUAL_ONLY"
    DIRECT_DEMONSTRATION = "DIRECT_DEMONSTRATION"


class RiskCode(str, Enum):
    MOTION_BLUR = "MOTION_BLUR"
    OCCLUSION = "OCCLUSION"
    POOR_LIGHTING = "POOR_LIGHTING"
    OFF_FRAME_ACTION = "OFF_FRAME_ACTION"
    PRODUCT_NOT_VISIBLE = "PRODUCT_NOT_VISIBLE"
    RESULT_NOT_VISIBLE = "RESULT_NOT_VISIBLE"
    FRAME_RANGE_TOO_SHORT = "FRAME_RANGE_TOO_SHORT"
    CONTINUITY_BREAK = "CONTINUITY_BREAK"


class RiskSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise CandidateEvidenceContractError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise CandidateEvidenceContractError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise CandidateEvidenceContractError(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise CandidateEvidenceContractError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


def _candidate_id(value: object, label: str = "candidate_id") -> str:
    if not isinstance(value, str) or _CANDIDATE_ID_PATTERN.fullmatch(value) is None:
        raise CandidateEvidenceContractError(f"{label} must match candv1_<sha256>")
    return value


def _pool_id(value: object, label: str = "candidate_pool_id") -> str:
    if not isinstance(value, str) or _POOL_ID_PATTERN.fullmatch(value) is None:
        raise CandidateEvidenceContractError(f"{label} must match poolv1_<sha256>")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CandidateEvidenceContractError(f"{label} must be a non-empty string")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or _TOKEN_PATTERN.fullmatch(value) is None:
        raise CandidateEvidenceContractError(
            f"{label} must be a logical lowercase-safe token without paths or spaces"
        )
    return value


def _prompt_contract_version(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or _PROMPT_CONTRACT_PATTERN.fullmatch(value) is None
    ):
        raise CandidateEvidenceContractError(f"{label} must look like <name>.v<number>")
    return value


def _enum(value: object, member_type: type[Enum], label: str) -> object:
    if not isinstance(value, str):
        raise CandidateEvidenceContractError(
            f"{label} must be one of: " + ", ".join(member.name for member in member_type)
        )
    try:
        return member_type(value)
    except ValueError as exc:
        raise CandidateEvidenceContractError(
            f"{label} must be one of: " + ", ".join(member.name for member in member_type)
        ) from exc


def _non_negative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CandidateEvidenceContractError(f"{label} must be a non-negative integer")
    return value


def _confidence(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateEvidenceContractError(
            f"{label} must be a number between 0.0 and 1.0"
        )
    measured = float(value)
    if not math.isfinite(measured) or measured < 0.0 or measured > 1.0:
        raise CandidateEvidenceContractError(
            f"{label} must be a finite number between 0.0 and 1.0"
        )
    return measured


def _source_range(value: object, label: str) -> SourceRange:
    mapping = _object(value, label)
    _exact_keys(mapping, _RANGE_KEYS, label)
    try:
        return SourceRange(
            mapping["start_frame"],  # type: ignore[arg-type]
            mapping["end_frame_exclusive"],  # type: ignore[arg-type]
        )
    except FrameBoundaryError as exc:
        raise CandidateEvidenceContractError(f"{label} is invalid: {exc}") from exc


def _range_tuple(value: object, label: str) -> tuple[SourceRange, ...]:
    ranges = tuple(
        _source_range(raw, f"{label}[{index}]")
        for index, raw in enumerate(_array(value, label))
    )
    ordered = tuple(sorted(ranges, key=lambda item: (item.start_frame, item.end_frame_exclusive)))
    if len(set((item.start_frame, item.end_frame_exclusive) for item in ordered)) != len(
        ordered
    ):
        raise CandidateEvidenceContractError(f"{label} must not repeat a frame range")
    return ordered


def _range_dict(source_range: SourceRange) -> dict[str, object]:
    return {
        "start_frame": source_range.start_frame,
        "end_frame_exclusive": source_range.end_frame_exclusive,
    }


def _covers(ranges: Sequence[SourceRange], start: int, end_exclusive: int) -> bool:
    """Whether the union of ``ranges`` fully contains ``[start, end_exclusive)``."""

    cursor = start
    for source_range in sorted(ranges, key=lambda item: item.start_frame):
        if source_range.start_frame > cursor:
            return False
        cursor = max(cursor, source_range.end_frame_exclusive)
        if cursor >= end_exclusive:
            return True
    return cursor >= end_exclusive


@dataclass(frozen=True)
class ProductFacts:
    """The permitted commercial facts, plus the artifact that states them."""

    ref: str
    sha256: str
    allowed_fact_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        try:
            validate_logical_ref(self.ref, "product_facts.ref")
            validate_sha256(self.sha256, "product_facts.sha256")
        except ArtifactReferenceError as exc:
            raise CandidateEvidenceContractError(str(exc)) from exc
        facts = tuple(
            _token(raw, f"product_facts.allowed_fact_refs[{index}]")
            for index, raw in enumerate(self.allowed_fact_refs)
        )
        if not facts:
            raise CandidateEvidenceContractError(
                "product_facts.allowed_fact_refs must not be empty"
            )
        if len(set(facts)) != len(facts):
            raise CandidateEvidenceContractError(
                "product_facts.allowed_fact_refs must not repeat a fact reference"
            )
        object.__setattr__(self, "allowed_fact_refs", tuple(sorted(facts)))

    @property
    def reference(self) -> ArtifactReference:
        return ArtifactReference(self.ref, self.sha256)

    def permits(self, fact_ref: str) -> bool:
        return fact_ref in self.allowed_fact_refs

    def as_dict(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "sha256": self.sha256,
            "allowed_fact_refs": list(self.allowed_fact_refs),
        }


@dataclass(frozen=True)
class AnalysisRun:
    """Who produced the semantic fields, under which prompt contract.

    ``run_id`` is a caller-owned logical identity. It is never derived from a
    wall clock, so the same structured input renders the same document.
    """

    run_id: str
    provider: str
    model: str
    prompt_contract_version: str

    def __post_init__(self) -> None:
        _token(self.run_id, "analysis_run.run_id")
        _token(self.provider, "analysis_run.provider")
        _token(self.model, "analysis_run.model")
        _prompt_contract_version(
            self.prompt_contract_version, "analysis_run.prompt_contract_version"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "provider": self.provider,
            "model": self.model,
            "prompt_contract_version": self.prompt_contract_version,
        }


@dataclass(frozen=True)
class Observations:
    """Model-owned description of what the cited frames show."""

    visible_action: str
    visible_result: str | None
    product_visibility: ProductVisibility
    usage_context: UsageContext
    body_area: BodyArea
    visual_usability: VisualUsability
    claim_support_class: ClaimSupportClass

    def __post_init__(self) -> None:
        _text(self.visible_action, "observations.visible_action")
        _optional_text(self.visible_result, "observations.visible_result")
        for field, member_type in (
            ("product_visibility", ProductVisibility),
            ("usage_context", UsageContext),
            ("body_area", BodyArea),
            ("visual_usability", VisualUsability),
            ("claim_support_class", ClaimSupportClass),
        ):
            object.__setattr__(
                self,
                field,
                _enum(getattr(self, field), member_type, f"observations.{field}"),
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "visible_action": self.visible_action,
            "visible_result": self.visible_result,
            "product_visibility": self.product_visibility.value,
            "usage_context": self.usage_context.value,
            "body_area": self.body_area.value,
            "visual_usability": self.visual_usability.value,
            "claim_support_class": self.claim_support_class.value,
        }


@dataclass(frozen=True)
class ClaimSupportRecord:
    """One commercial claim bound to one permitted Product Fact."""

    product_fact_ref: str
    support: ClaimSupport
    provenance: tuple[SourceRange, ...] = ()
    note: str | None = None

    def __post_init__(self) -> None:
        _token(self.product_fact_ref, "claims[].product_fact_ref")
        object.__setattr__(
            self,
            "support",
            _enum(self.support, ClaimSupport, "claims[].support"),
        )
        if not isinstance(self.provenance, tuple):
            raise CandidateEvidenceContractError("claims[].provenance must be a tuple")
        for index, item in enumerate(self.provenance):
            if not isinstance(item, SourceRange):
                raise CandidateEvidenceContractError(
                    f"claims[].provenance[{index}] must be a SourceRange"
                )
        ordered = tuple(
            sorted(
                self.provenance,
                key=lambda item: (item.start_frame, item.end_frame_exclusive),
            )
        )
        object.__setattr__(self, "provenance", ordered)
        _optional_text(self.note, "claims[].note")
        if self.support is ClaimSupport.DIRECT and not ordered:
            raise CandidateEvidenceContractError(
                "a DIRECT claim must bind at least one frame range"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "product_fact_ref": self.product_fact_ref,
            "support": self.support.value,
            "provenance": [_range_dict(item) for item in self.provenance],
            "note": self.note,
        }


@dataclass(frozen=True)
class RiskRecord:
    code: RiskCode
    severity: RiskSeverity
    note: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _enum(self.code, RiskCode, "risks[].code"))
        object.__setattr__(
            self, "severity", _enum(self.severity, RiskSeverity, "risks[].severity")
        )
        _text(self.note, "risks[].note")

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "severity": self.severity.value,
            "note": self.note,
        }


@dataclass(frozen=True)
class CandidateEvidenceEntry:
    """Exactly one evidence record for exactly one Candidate.

    Every key is always present. A Candidate that was not analysed carries
    ``ANALYSIS_FAILED`` or ``UNKNOWN``, ``null`` payload fields, and a
    ``rationale`` that states why. A payload field that is present while the
    status is not ``ANALYZED`` is a contract error, so an unanalysed Candidate
    cannot smuggle in observations.
    """

    candidate_id: str
    status: EvidenceStatus
    rationale: str
    observations: Observations | None = None
    action_evidence: tuple[ActionEvidence, ...] | None = None
    claims: tuple[ClaimSupportRecord, ...] | None = None
    evidence_type: EvidenceType | None = None
    confidence: float | None = None
    provenance: tuple[SourceRange, ...] | None = None
    role_affinities: tuple[NarrativeRole, ...] | None = None
    risks: tuple[RiskRecord, ...] | None = None

    def __post_init__(self) -> None:
        _candidate_id(self.candidate_id)
        object.__setattr__(
            self, "status", _enum(self.status, EvidenceStatus, "status")
        )
        _text(self.rationale, "rationale")

        payload = {
            "observations": self.observations,
            "action_evidence": self.action_evidence,
            "claims": self.claims,
            "evidence_type": self.evidence_type,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "role_affinities": self.role_affinities,
            "risks": self.risks,
        }
        if self.status is not EvidenceStatus.ANALYZED:
            present = sorted(
                key for key, value in payload.items() if value is not None
            )
            if present:
                raise CandidateEvidenceContractError(
                    "a non-ANALYZED entry must not carry semantic field(s): "
                    + ", ".join(present)
                )
            return

        missing = sorted(key for key, value in payload.items() if value is None)
        if missing:
            raise CandidateEvidenceContractError(
                "an ANALYZED entry is missing required field(s): " + ", ".join(missing)
            )

        if not isinstance(self.observations, Observations):
            raise CandidateEvidenceContractError("observations must be Observations")
        provenance = self.provenance
        if not provenance:
            raise CandidateEvidenceContractError(
                "an ANALYZED entry must cite at least one provenance frame range"
            )
        for index, item in enumerate(provenance):
            if not isinstance(item, SourceRange):
                raise CandidateEvidenceContractError(
                    f"provenance[{index}] must be a SourceRange"
                )
        confidence = _confidence(self.confidence, "confidence")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(
            self,
            "evidence_type",
            _enum(self.evidence_type, EvidenceType, "evidence_type"),
        )

        actions = self._ordered_actions()
        object.__setattr__(self, "action_evidence", actions)
        object.__setattr__(self, "claims", self._ordered_claims())
        object.__setattr__(self, "role_affinities", self._ordered_roles())
        object.__setattr__(self, "risks", self._ordered_risks())
        self._validate_cross_rules(actions)

    def _ordered_actions(self) -> tuple[ActionEvidence, ...]:
        actions = self.action_evidence or ()
        for index, item in enumerate(actions):
            if not isinstance(item, ActionEvidence):
                raise CandidateEvidenceContractError(
                    f"action_evidence[{index}] must be an ActionEvidence"
                )
        ordered = tuple(
            sorted(
                actions,
                key=lambda item: (
                    item.preparation_start,
                    item.action_onset,
                    item.action_completion,
                    item.result_end_exclusive,
                ),
            )
        )
        for previous, current in zip(ordered, ordered[1:]):
            if current.preparation_start < previous.result_end_exclusive:
                raise CandidateEvidenceContractError(
                    "action_evidence phases must not overlap between actions"
                )
        return ordered

    def _ordered_claims(self) -> tuple[ClaimSupportRecord, ...]:
        claims = self.claims or ()
        for index, item in enumerate(claims):
            if not isinstance(item, ClaimSupportRecord):
                raise CandidateEvidenceContractError(
                    f"claims[{index}] must be a ClaimSupportRecord"
                )
        fact_refs = [item.product_fact_ref for item in claims]
        if len(set(fact_refs)) != len(fact_refs):
            raise CandidateEvidenceContractError(
                "claims must not repeat the same product_fact_ref"
            )
        return tuple(sorted(claims, key=lambda item: item.product_fact_ref))

    def _ordered_roles(self) -> tuple[NarrativeRole, ...]:
        roles = self.role_affinities or ()
        if isinstance(roles, (str, bytes)) or not isinstance(roles, Sequence):
            raise CandidateEvidenceContractError("role_affinities must be a sequence")
        converted = tuple(
            _enum(item, NarrativeRole, f"role_affinities[{index}]")
            for index, item in enumerate(roles)
        )
        names = [item.value for item in converted]  # type: ignore[union-attr]
        if len(set(names)) != len(names):
            raise CandidateEvidenceContractError(
                "role_affinities must not repeat a role"
            )
        return tuple(sorted(converted, key=lambda item: item.value))  # type: ignore[union-attr]

    def _ordered_risks(self) -> tuple[RiskRecord, ...]:
        risks = self.risks or ()
        for index, item in enumerate(risks):
            if not isinstance(item, RiskRecord):
                raise CandidateEvidenceContractError(
                    f"risks[{index}] must be a RiskRecord"
                )
        codes = [item.code.value for item in risks]
        if len(set(codes)) != len(codes):
            raise CandidateEvidenceContractError("risks must not repeat a risk code")
        return tuple(sorted(risks, key=lambda item: item.code.value))

    def _validate_cross_rules(self, actions: tuple[ActionEvidence, ...]) -> None:
        observations = self.observations
        assert observations is not None  # guarded by the ANALYZED branch
        if observations.visual_usability is VisualUsability.UNUSABLE:
            if self.evidence_type is not EvidenceType.NONE:
                raise CandidateEvidenceContractError(
                    "UNUSABLE frames must be recorded as evidence_type NONE"
                )
        if self.evidence_type is EvidenceType.NONE and any(
            claim.support is ClaimSupport.DIRECT for claim in self.claims or ()
        ):
            raise CandidateEvidenceContractError(
                "evidence_type NONE must not carry DIRECT claim support"
            )
        claims = self.claims or ()
        if claims and observations.claim_support_class is ClaimSupportClass.NONE:
            raise CandidateEvidenceContractError(
                "claims require an explicit claim_support_class"
            )
        if observations.claim_support_class is ClaimSupportClass.DIRECT_DEMONSTRATION:
            if not any(claim.support is ClaimSupport.DIRECT for claim in claims):
                raise CandidateEvidenceContractError(
                    "DIRECT_DEMONSTRATION requires at least one DIRECT claim"
                )
        if actions and observations.visible_result is None:
            raise CandidateEvidenceContractError(
                "action evidence requires an observable visible_result"
            )
        provenance = self.provenance or ()
        for action in actions:
            if not _covers(
                provenance, action.preparation_start, action.result_end_exclusive
            ):
                raise CandidateEvidenceContractError(
                    "action evidence must lie inside the cited provenance frames"
                )

    @property
    def is_analyzed(self) -> bool:
        return self.status is EvidenceStatus.ANALYZED

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status.value,
            "observations": (
                None if self.observations is None else self.observations.as_dict()
            ),
            "action_evidence": (
                None
                if self.action_evidence is None
                else [
                    {
                        "preparation_start": item.preparation_start,
                        "action_onset": item.action_onset,
                        "action_completion": item.action_completion,
                        "result_end_exclusive": item.result_end_exclusive,
                    }
                    for item in self.action_evidence
                ]
            ),
            "claims": (
                None if self.claims is None else [item.as_dict() for item in self.claims]
            ),
            "evidence_type": (
                None if self.evidence_type is None else self.evidence_type.value
            ),
            "confidence": self.confidence,
            "provenance": (
                None
                if self.provenance is None
                else [_range_dict(item) for item in self.provenance]
            ),
            "role_affinities": (
                None
                if self.role_affinities is None
                else [item.value for item in self.role_affinities]
            ),
            "risks": None if self.risks is None else [item.as_dict() for item in self.risks],
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class CandidateEvidence:
    """One analysis snapshot covering one Candidate Pool in full."""

    candidate_pool_id: str
    product_facts: ProductFacts
    analysis_run: AnalysisRun
    entries: tuple[CandidateEvidenceEntry, ...]

    def __post_init__(self) -> None:
        _pool_id(self.candidate_pool_id)
        if not isinstance(self.product_facts, ProductFacts):
            raise CandidateEvidenceContractError("product_facts must be ProductFacts")
        if not isinstance(self.analysis_run, AnalysisRun):
            raise CandidateEvidenceContractError("analysis_run must be an AnalysisRun")
        for index, entry in enumerate(self.entries):
            if not isinstance(entry, CandidateEvidenceEntry):
                raise CandidateEvidenceContractError(
                    f"entries[{index}] must be a CandidateEvidenceEntry"
                )
        candidate_ids = [entry.candidate_id for entry in self.entries]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise CandidateEvidenceContractError(
                "duplicate candidate_id in candidate evidence"
            )
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(self.entries, key=lambda entry: entry.candidate_id)),
        )

    def entry_for(self, candidate_id: str) -> CandidateEvidenceEntry:
        requested = _candidate_id(candidate_id)
        for entry in self.entries:
            if entry.candidate_id == requested:
                return entry
        raise CandidateEvidenceContractError("candidate_id has no evidence entry")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "candidate_pool_id": self.candidate_pool_id,
            "product_facts": self.product_facts.as_dict(),
            "analysis_run": self.analysis_run.as_dict(),
            "entries": [entry.as_dict() for entry in self.entries],
        }


def _parse_observations(value: object, label: str) -> Observations:
    mapping = _object(value, label)
    _exact_keys(mapping, _OBSERVATION_KEYS, label)
    return Observations(
        visible_action=mapping["visible_action"],  # type: ignore[arg-type]
        visible_result=mapping["visible_result"],  # type: ignore[arg-type]
        product_visibility=mapping["product_visibility"],  # type: ignore[arg-type]
        usage_context=mapping["usage_context"],  # type: ignore[arg-type]
        body_area=mapping["body_area"],  # type: ignore[arg-type]
        visual_usability=mapping["visual_usability"],  # type: ignore[arg-type]
        claim_support_class=mapping["claim_support_class"],  # type: ignore[arg-type]
    )


def _parse_actions(value: object, label: str) -> tuple[ActionEvidence, ...]:
    actions: list[ActionEvidence] = []
    for index, raw in enumerate(_array(value, label)):
        item = _object(raw, f"{label}[{index}]")
        _exact_keys(item, _ACTION_KEYS, f"{label}[{index}]")
        try:
            actions.append(
                ActionEvidence(
                    preparation_start=item["preparation_start"],  # type: ignore[arg-type]
                    action_onset=item["action_onset"],  # type: ignore[arg-type]
                    action_completion=item["action_completion"],  # type: ignore[arg-type]
                    result_end_exclusive=item["result_end_exclusive"],  # type: ignore[arg-type]
                )
            )
        except EditingIntelligenceError as exc:
            raise CandidateEvidenceContractError(
                f"{label}[{index}] chronology is invalid: {exc}"
            ) from exc
    return tuple(actions)


def _parse_claims(value: object, label: str) -> tuple[ClaimSupportRecord, ...]:
    claims: list[ClaimSupportRecord] = []
    for index, raw in enumerate(_array(value, label)):
        item = _object(raw, f"{label}[{index}]")
        _exact_keys(item, _CLAIM_KEYS, f"{label}[{index}]")
        claims.append(
            ClaimSupportRecord(
                product_fact_ref=item["product_fact_ref"],  # type: ignore[arg-type]
                support=item["support"],  # type: ignore[arg-type]
                provenance=_range_tuple(
                    item["provenance"], f"{label}[{index}].provenance"
                ),
                note=item["note"],  # type: ignore[arg-type]
            )
        )
    return tuple(claims)


def _parse_risks(value: object, label: str) -> tuple[RiskRecord, ...]:
    risks: list[RiskRecord] = []
    for index, raw in enumerate(_array(value, label)):
        item = _object(raw, f"{label}[{index}]")
        _exact_keys(item, _RISK_KEYS, f"{label}[{index}]")
        risks.append(
            RiskRecord(
                code=item["code"],  # type: ignore[arg-type]
                severity=item["severity"],  # type: ignore[arg-type]
                note=item["note"],  # type: ignore[arg-type]
            )
        )
    return tuple(risks)


def _parse_entry(value: object, label: str) -> CandidateEvidenceEntry:
    mapping = _object(value, label)
    _exact_keys(mapping, _ENTRY_KEYS, label)
    raw_status = mapping["status"]
    status = _enum(raw_status, EvidenceStatus, f"{label}.status")
    assert isinstance(status, EvidenceStatus)
    if status is not EvidenceStatus.ANALYZED:
        present = sorted(
            key for key in _ENTRY_PAYLOAD_KEYS if mapping[key] is not None
        )
        if present:
            raise CandidateEvidenceContractError(
                f"{label} is not ANALYZED and must not carry semantic field(s): "
                + ", ".join(present)
            )
        return CandidateEvidenceEntry(
            candidate_id=mapping["candidate_id"],  # type: ignore[arg-type]
            status=status,
            rationale=mapping["rationale"],  # type: ignore[arg-type]
        )
    roles = _array(mapping["role_affinities"], f"{label}.role_affinities")
    return CandidateEvidenceEntry(
        candidate_id=mapping["candidate_id"],  # type: ignore[arg-type]
        status=status,
        rationale=mapping["rationale"],  # type: ignore[arg-type]
        observations=_parse_observations(
            mapping["observations"], f"{label}.observations"
        ),
        action_evidence=_parse_actions(
            mapping["action_evidence"], f"{label}.action_evidence"
        ),
        claims=_parse_claims(mapping["claims"], f"{label}.claims"),
        evidence_type=_enum(  # type: ignore[arg-type]
            mapping["evidence_type"], EvidenceType, f"{label}.evidence_type"
        ),
        confidence=mapping["confidence"],  # type: ignore[arg-type]
        provenance=_range_tuple(mapping["provenance"], f"{label}.provenance"),
        role_affinities=tuple(
            _enum(raw, NarrativeRole, f"{label}.role_affinities[{index}]")  # type: ignore[arg-type]
            for index, raw in enumerate(roles)
        ),
        risks=_parse_risks(mapping["risks"], f"{label}.risks"),
    )


def parse_candidate_evidence(document: object) -> CandidateEvidence:
    mapping = _object(document, "candidate evidence")
    _exact_keys(mapping, _DOCUMENT_KEYS, "candidate evidence")
    if mapping["schema_version"] != SCHEMA_VERSION:
        raise CandidateEvidenceContractError(f"schema_version must be {SCHEMA_VERSION!r}")

    product_facts = _object(mapping["product_facts"], "product_facts")
    _exact_keys(product_facts, _PRODUCT_FACT_KEYS, "product_facts")
    analysis_run = _object(mapping["analysis_run"], "analysis_run")
    _exact_keys(analysis_run, _ANALYSIS_RUN_KEYS, "analysis_run")

    return CandidateEvidence(
        candidate_pool_id=mapping["candidate_pool_id"],  # type: ignore[arg-type]
        product_facts=ProductFacts(
            ref=product_facts["ref"],  # type: ignore[arg-type]
            sha256=product_facts["sha256"],  # type: ignore[arg-type]
            allowed_fact_refs=tuple(
                _array(
                    product_facts["allowed_fact_refs"],
                    "product_facts.allowed_fact_refs",
                )
            ),  # type: ignore[arg-type]
        ),
        analysis_run=AnalysisRun(
            run_id=analysis_run["run_id"],  # type: ignore[arg-type]
            provider=analysis_run["provider"],  # type: ignore[arg-type]
            model=analysis_run["model"],  # type: ignore[arg-type]
            prompt_contract_version=analysis_run["prompt_contract_version"],  # type: ignore[arg-type]
        ),
        entries=tuple(
            _parse_entry(raw, f"entries[{index}]")
            for index, raw in enumerate(_array(mapping["entries"], "entries"))
        ),
    )


def render_candidate_evidence(evidence: CandidateEvidence) -> str:
    if not isinstance(evidence, CandidateEvidence):
        raise CandidateEvidenceContractError("evidence must be CandidateEvidence")
    return (
        json.dumps(evidence.as_dict(), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n"
    )


def candidate_evidence_reference(
    evidence: CandidateEvidence, ref: object = CANONICAL_REF
) -> ArtifactReference:
    """The ``{ref, sha256}`` pair that binds this exact rendered document."""

    return artifact_reference(ref, render_candidate_evidence(evidence))


def validate_candidate_evidence_reference(
    evidence: CandidateEvidence, text: object, *, ref: object = CANONICAL_REF
) -> None:
    """Fail closed when the supplied bytes are not this evidence revision."""

    try:
        validate_reference_binding(
            candidate_evidence_reference(evidence, ref), text, label="candidate_evidence"
        )
    except ArtifactReferenceError as exc:
        raise CandidateEvidenceContractError(str(exc)) from exc


def _require_inside(
    candidate: CandidateIdentity, source_range: SourceRange, label: str
) -> None:
    if (
        source_range.start_frame < candidate.start_frame
        or source_range.end_frame_exclusive > candidate.end_frame_exclusive
    ):
        raise CandidateEvidenceContractError(
            f"{label} lies outside the exact Candidate frame range"
        )


def _require_action_inside(
    candidate: CandidateIdentity, action: ActionEvidence, label: str
) -> None:
    if (
        action.preparation_start < candidate.start_frame
        or action.result_end_exclusive > candidate.end_frame_exclusive
    ):
        raise CandidateEvidenceContractError(
            f"{label} lies outside the exact Candidate frame range"
        )


def validate_candidate_evidence(
    evidence: CandidateEvidence, pool: CandidatePool, catalog: IdentityCatalog
) -> tuple[CandidateIdentity, ...]:
    """Validate Pool identity, cardinality, and frame provenance. Fail closed.

    Returns the resolved Candidate Identities in Pool member order, which is the
    canonical order of both documents.
    """

    if not isinstance(evidence, CandidateEvidence):
        raise CandidateEvidenceContractError("evidence must be CandidateEvidence")
    if not isinstance(pool, CandidatePool):
        raise CandidateEvidenceContractError("pool must be a CandidatePool")
    if not isinstance(catalog, IdentityCatalog):
        raise CandidateEvidenceContractError("catalog must be an IdentityCatalog")
    if evidence.candidate_pool_id != pool.pool_id:
        raise CandidateEvidenceContractError(
            "candidate_pool_id does not match the supplied pool"
        )
    try:
        validate_candidate_pool(pool, catalog)
    except ValueError as exc:
        raise CandidateEvidenceContractError(str(exc)) from exc

    members = tuple(entry.candidate_id for entry in pool.entries)
    recorded = tuple(entry.candidate_id for entry in evidence.entries)
    missing = sorted(set(members) - set(recorded))
    extra = sorted(set(recorded) - set(members))
    if missing:
        raise CandidateEvidenceContractError(
            "candidate evidence must record every Pool member; missing "
            f"{len(missing)} entry(ies)"
        )
    if extra:
        raise CandidateEvidenceContractError(
            "candidate evidence references a Candidate outside the Pool"
        )

    resolved: list[CandidateIdentity] = []
    for candidate_id in members:
        try:
            candidate = catalog.candidate(candidate_id)
        except ValueError as exc:
            raise CandidateEvidenceContractError(
                "evidence references an unknown candidate_id"
            ) from exc
        entry = evidence.entry_for(candidate_id)
        for index, action in enumerate(entry.action_evidence or ()):
            _require_action_inside(candidate, action, f"action_evidence[{index}]")
        if entry.provenance is not None:
            for index, source_range in enumerate(entry.provenance):
                _require_inside(candidate, source_range, f"provenance[{index}]")
        for claim in entry.claims or ():
            if not evidence.product_facts.permits(claim.product_fact_ref):
                raise CandidateEvidenceContractError(
                    "a claim references a Product Fact that is not permitted"
                )
            for index, source_range in enumerate(claim.provenance):
                _require_inside(
                    candidate,
                    source_range,
                    f"claims[{claim.product_fact_ref}].provenance[{index}]",
                )
        resolved.append(candidate)
    return tuple(resolved)
