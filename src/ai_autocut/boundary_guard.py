"""Pure multi-segment preflight for frame-accurate source boundaries.

The guard composes the existing frame-boundary kernel. It performs no file,
network, editor, or process I/O and reports business risks as data. Malformed
guard inputs raise :class:`BoundaryGuardContractError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .frame_boundary import (
    CandidateSlice,
    FrameBoundaryError,
    Placement,
    SourceRange,
    assess_candidate_cut,
    assess_source_boundary,
    build_relative_placements,
)


class BoundaryGuardContractError(FrameBoundaryError):
    """Raised when the guard input does not satisfy its contract."""


def _required_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise BoundaryGuardContractError(f"{label} must be a non-empty string")


def _optional_non_negative_frame(value: int | None, label: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BoundaryGuardContractError(
            f"{label} must be a non-negative integer frame or None"
        )


@dataclass(frozen=True)
class GuardSegment:
    """One ordered segment presented to the boundary guard."""

    segment_id: str
    candidate_id: str
    source_id: str
    source_range: SourceRange
    continuation_group: str | None = None
    verified_safe_end_frame_exclusive: int | None = None
    planned_record_frame_relative: int | None = None

    def __post_init__(self) -> None:
        _required_text(self.segment_id, "segment_id")
        _required_text(self.candidate_id, "candidate_id")
        _required_text(self.source_id, "source_id")
        if not isinstance(self.source_range, SourceRange):
            raise BoundaryGuardContractError("source_range must be a SourceRange")
        if self.continuation_group is not None:
            _required_text(self.continuation_group, "continuation_group")
        _optional_non_negative_frame(
            self.verified_safe_end_frame_exclusive,
            "verified_safe_end_frame_exclusive",
        )
        _optional_non_negative_frame(
            self.planned_record_frame_relative,
            "planned_record_frame_relative",
        )


@dataclass(frozen=True)
class GuardIssue:
    """One stable, locatable, and human-auditable guard finding."""

    code: str
    segment_ids: tuple[str, ...]
    source_id: str
    frame: int
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "segment_ids": list(self.segment_ids),
            "source_id": self.source_id,
            "frame": self.frame,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GuardReport:
    """Deterministic result of checking an ordered segment sequence."""

    passed: bool
    issues: tuple[GuardIssue, ...]
    placements: tuple[Placement, ...]
    total_frames: int

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "issues": [issue.as_dict() for issue in self.issues],
            "placements": [
                {
                    "segment_id": placement.segment_id,
                    "source_in_frame": placement.source_range.start_frame,
                    "source_out_frame_exclusive": (
                        placement.source_range.end_frame_exclusive
                    ),
                    "duration_frames": placement.duration_frames,
                    "record_frame_relative": placement.record_frame_relative,
                }
                for placement in self.placements
            ],
            "total_frames": self.total_frames,
        }


def _validate_segments(segments: Sequence[GuardSegment]) -> None:
    if isinstance(segments, (str, bytes)) or not isinstance(segments, Sequence):
        raise BoundaryGuardContractError("segments must be a sequence")
    if not segments:
        raise BoundaryGuardContractError("segments must not be empty")
    seen_segment_ids: set[str] = set()
    for index, segment in enumerate(segments):
        if not isinstance(segment, GuardSegment):
            raise BoundaryGuardContractError(
                f"segments[{index}] must be a GuardSegment"
            )
        if segment.segment_id in seen_segment_ids:
            raise BoundaryGuardContractError(
                f"duplicate segment_id: {segment.segment_id}"
            )
        seen_segment_ids.add(segment.segment_id)


def run_boundary_guard(segments: Sequence[GuardSegment]) -> GuardReport:
    """Check source limits, relative placements, and adjacent candidate cuts.

    Issue ordering is stable and follows input timeline order. For each segment
    the guard reports its source-boundary issue, then its planned-placement
    issue, then the outgoing candidate-cut issue before moving to the next
    segment.
    """

    _validate_segments(segments)
    placements = build_relative_placements(
        tuple((segment.segment_id, segment.source_range) for segment in segments)
    )
    issues: list[GuardIssue] = []

    for index, (segment, placement) in enumerate(zip(segments, placements)):
        safe_end = segment.verified_safe_end_frame_exclusive
        if safe_end is not None:
            assessment = assess_source_boundary(segment.source_range, safe_end)
            if not assessment.accepted:
                issues.append(
                    GuardIssue(
                        code=assessment.code,
                        segment_ids=(segment.segment_id,),
                        source_id=segment.source_id,
                        frame=safe_end,
                        reason=assessment.reason,
                    )
                )

        planned_relative = segment.planned_record_frame_relative
        if (
            planned_relative is not None
            and planned_relative != placement.record_frame_relative
        ):
            issues.append(
                GuardIssue(
                    code="TIMELINE_RELATIVE_PLACEMENT_MISMATCH",
                    segment_ids=(segment.segment_id,),
                    source_id=segment.source_id,
                    frame=placement.record_frame_relative,
                    reason=(
                        f"segment {segment.segment_id} planned relative frame "
                        f"{planned_relative}, but contiguous placement requires "
                        f"{placement.record_frame_relative}"
                    ),
                )
            )

        if index + 1 < len(segments):
            next_segment = segments[index + 1]
            cut_assessment = assess_candidate_cut(
                CandidateSlice(
                    segment.candidate_id,
                    segment.source_id,
                    segment.source_range,
                    segment.continuation_group,
                ),
                CandidateSlice(
                    next_segment.candidate_id,
                    next_segment.source_id,
                    next_segment.source_range,
                    next_segment.continuation_group,
                ),
            )
            if not cut_assessment.accepted:
                issues.append(
                    GuardIssue(
                        code=cut_assessment.code,
                        segment_ids=(segment.segment_id, next_segment.segment_id),
                        source_id=segment.source_id,
                        frame=segment.source_range.end_frame_exclusive,
                        reason=cut_assessment.reason,
                    )
                )

    total_frames = sum(placement.duration_frames for placement in placements)
    return GuardReport(
        passed=not issues,
        issues=tuple(issues),
        placements=placements,
        total_frames=total_frames,
    )
