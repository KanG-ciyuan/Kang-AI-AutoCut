"""Deterministic, linear Editing Plan snapshots for AI-AutoCut.

An Editing Plan chooses an ordered sequence of complete Candidates from one
Candidate Pool. It deliberately does not store source facts, trim ranges,
timeline state, or planning explanations.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping, Sequence

from .candidate_pool import (
    CandidatePool,
    validate_candidate_membership,
    validate_candidate_pool,
)
from .identity import CandidateIdentity, IdentityCatalog, bind_boundary_preflight


SCHEMA_VERSION = "editing_plan.v1"

_PLAN_PREFIX = "planv1_"
_PLAN_DOMAIN = b"ai-autocut:editing-plan:v1\n"
_CANDIDATE_ID_PATTERN = re.compile(r"candv1_[0-9a-f]{64}\Z")
_POOL_ID_PATTERN = re.compile(r"poolv1_[0-9a-f]{64}\Z")
_PLAN_ID_PATTERN = re.compile(r"planv1_[0-9a-f]{64}\Z")
_PLAN_KEYS = ("schema_version", "plan_id", "candidate_pool_id", "segments")
_SEGMENT_KEYS = ("candidate_id",)


class EditingPlanContractError(ValueError):
    """Raised when an Editing Plan cannot be consumed safely."""


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise EditingPlanContractError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise EditingPlanContractError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise EditingPlanContractError(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise EditingPlanContractError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


def _candidate_id(value: object, label: str = "candidate_id") -> str:
    if not isinstance(value, str) or _CANDIDATE_ID_PATTERN.fullmatch(value) is None:
        raise EditingPlanContractError(f"{label} must match candv1_<sha256>")
    return value


def _pool_id(value: object, label: str = "candidate_pool_id") -> str:
    if not isinstance(value, str) or _POOL_ID_PATTERN.fullmatch(value) is None:
        raise EditingPlanContractError(f"{label} must match poolv1_<sha256>")
    return value


def _plan_id(value: object, label: str = "plan_id") -> str:
    if not isinstance(value, str) or _PLAN_ID_PATTERN.fullmatch(value) is None:
        raise EditingPlanContractError(f"{label} must match planv1_<sha256>")
    return value


def _ordered_candidate_ids(candidate_ids: Sequence[object]) -> tuple[str, ...]:
    if isinstance(candidate_ids, (str, bytes)) or not isinstance(candidate_ids, Sequence):
        raise EditingPlanContractError("candidate_ids must be a sequence")
    if not candidate_ids:
        raise EditingPlanContractError("segments must not be empty")
    return tuple(
        _candidate_id(value, f"candidate_ids[{index}]")
        for index, value in enumerate(candidate_ids)
    )


def canonical_plan_identity_json(
    candidate_pool_id: object, candidate_ids: Sequence[object]
) -> str:
    """Return the canonical ordered payload that defines one Plan ID."""

    pool_id = _pool_id(candidate_pool_id)
    ordered_ids = _ordered_candidate_ids(candidate_ids)
    return json.dumps(
        {
            "candidate_pool_id": pool_id,
            "segments": [{"candidate_id": candidate_id} for candidate_id in ordered_ids],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def plan_id_for(candidate_pool_id: object, candidate_ids: Sequence[object]) -> str:
    """Derive one immutable Plan ID from Pool identity and ordered members."""

    canonical = canonical_plan_identity_json(candidate_pool_id, candidate_ids)
    digest = hashlib.sha256(_PLAN_DOMAIN + canonical.encode("utf-8")).hexdigest()
    return _PLAN_PREFIX + digest


def segment_id_for_position(position: object) -> str:
    """Derive a deterministic one-based preflight segment identifier."""

    if isinstance(position, bool) or not isinstance(position, int) or position < 1:
        raise EditingPlanContractError("segment position must be a positive integer")
    return f"segv1_{position:06d}"


@dataclass(frozen=True)
class EditingPlanSegment:
    candidate_id: str

    def __post_init__(self) -> None:
        _candidate_id(self.candidate_id)

    def as_dict(self) -> dict[str, object]:
        return {"candidate_id": self.candidate_id}


@dataclass(frozen=True)
class EditingPlan:
    plan_id: str
    candidate_pool_id: str
    segments: tuple[EditingPlanSegment, ...]

    def __post_init__(self) -> None:
        supplied_id = _plan_id(self.plan_id)
        pool_id = _pool_id(self.candidate_pool_id)
        candidate_ids = tuple(segment.candidate_id for segment in self.segments)
        expected_id = plan_id_for(pool_id, candidate_ids)
        if supplied_id != expected_id:
            raise EditingPlanContractError(
                "plan_id does not match its canonical Pool and ordered Candidate sequence"
            )

    @classmethod
    def create(
        cls, candidate_pool_id: object, candidate_ids: Sequence[object]
    ) -> "EditingPlan":
        pool_id = _pool_id(candidate_pool_id)
        ordered_ids = _ordered_candidate_ids(candidate_ids)
        return cls(
            plan_id_for(pool_id, ordered_ids),
            pool_id,
            tuple(EditingPlanSegment(candidate_id) for candidate_id in ordered_ids),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "candidate_pool_id": self.candidate_pool_id,
            "segments": [segment.as_dict() for segment in self.segments],
        }


def parse_editing_plan(document: object) -> EditingPlan:
    mapping = _object(document, "editing plan")
    _exact_keys(mapping, _PLAN_KEYS, "editing plan")
    if mapping["schema_version"] != SCHEMA_VERSION:
        raise EditingPlanContractError(f"schema_version must be {SCHEMA_VERSION!r}")

    segments: list[EditingPlanSegment] = []
    for index, raw in enumerate(_array(mapping["segments"], "segments")):
        item = _object(raw, f"segments[{index}]")
        _exact_keys(item, _SEGMENT_KEYS, f"segments[{index}]")
        segments.append(EditingPlanSegment(item["candidate_id"]))
    return EditingPlan(
        mapping["plan_id"], mapping["candidate_pool_id"], tuple(segments)
    )


def render_editing_plan(plan: EditingPlan) -> str:
    if not isinstance(plan, EditingPlan):
        raise EditingPlanContractError("plan must be an EditingPlan")
    return json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def validate_editing_plan(
    plan: EditingPlan, pool: CandidatePool, catalog: IdentityCatalog
) -> tuple[CandidateIdentity, ...]:
    """Validate the Plan-to-Pool-to-Identity chain and resolve Candidates."""

    if not isinstance(plan, EditingPlan):
        raise EditingPlanContractError("plan must be an EditingPlan")
    if not isinstance(pool, CandidatePool):
        raise EditingPlanContractError("pool must be a CandidatePool")
    if not isinstance(catalog, IdentityCatalog):
        raise EditingPlanContractError("catalog must be an IdentityCatalog")
    if plan.candidate_pool_id != pool.pool_id:
        raise EditingPlanContractError(
            "candidate_pool_id does not match the supplied pool"
        )
    try:
        validate_candidate_pool(pool, catalog)
        return tuple(
            validate_candidate_membership(
                plan.candidate_pool_id, segment.candidate_id, pool, catalog
            )
            for segment in plan.segments
        )
    except ValueError as exc:
        raise EditingPlanContractError(
            "plan does not reference valid Candidate Pool members"
        ) from exc


def bind_plan_boundary_preflight(
    plan: EditingPlan, pool: CandidatePool, catalog: IdentityCatalog
) -> dict[str, object]:
    """Emit unchanged boundary_preflight.v1 input for one validated Plan."""

    candidates = validate_editing_plan(plan, pool, catalog)
    record_frame_relative = 0
    segments: list[dict[str, object]] = []
    for position, candidate in enumerate(candidates, start=1):
        segments.append(
            {
                "segment_id": segment_id_for_position(position),
                "material_id": candidate.material_id,
                "candidate_id": candidate.candidate_id,
                "source_range": {
                    "start_frame": candidate.start_frame,
                    "end_frame_exclusive": candidate.end_frame_exclusive,
                },
                "planned_record_frame_relative": record_frame_relative,
            }
        )
        record_frame_relative += (
            candidate.end_frame_exclusive - candidate.start_frame
        )
    return bind_boundary_preflight(catalog, tuple(segments))
