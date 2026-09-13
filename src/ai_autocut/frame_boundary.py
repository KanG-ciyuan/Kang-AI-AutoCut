"""Exact frame geometry and auditable source-boundary checks.

Frames are the canonical unit. Second-based inputs are accepted only when
they map exactly to a frame at the supplied frame rate; callers must make any
rounding policy outside this kernel and record that decision explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Sequence


FrameRateInput = int | str | Decimal | Fraction
SecondsInput = int | str | Decimal | Fraction


class FrameBoundaryError(ValueError):
    """Base error for invalid or unsafe frame-boundary input."""


class FrameAlignmentError(FrameBoundaryError):
    """Raised when a second-based value is not exactly frame-aligned."""


class TimelineGeometryError(FrameBoundaryError):
    """Raised when a timeline coordinate is missing or invalid."""


class ReadbackMismatchError(FrameBoundaryError):
    """Raised when observed placement geometry disagrees with the request."""

    def __init__(self, verification: "ReadbackVerification") -> None:
        self.verification = verification
        super().__init__(verification.reason)


def _as_fraction(value: FrameRateInput | SecondsInput, label: str) -> Fraction:
    if isinstance(value, bool) or isinstance(value, float):
        raise FrameBoundaryError(
            f"{label} must be an int, string, Decimal, or Fraction; "
            "binary float input is ambiguous"
        )
    try:
        result = value if isinstance(value, Fraction) else Fraction(value)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise FrameBoundaryError(f"{label} is not an exact rational value: {value!r}") from exc
    return result


def _frame_rate(value: FrameRateInput) -> Fraction:
    result = _as_fraction(value, "fps")
    if result <= 0:
        raise FrameBoundaryError("fps must be greater than zero")
    return result


def _frame(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FrameBoundaryError(f"{label} must be an integer frame number")
    return value


def seconds_to_frame_exact(seconds: SecondsInput, fps: FrameRateInput) -> int:
    """Convert seconds to a frame only when the result is exact.

    This function never rounds. For example, ``"20.23"`` at ``"30/1"``
    raises :class:`FrameAlignmentError` because it equals frame 606.9.
    """

    exact_frame = _as_fraction(seconds, "seconds") * _frame_rate(fps)
    if exact_frame.denominator != 1:
        raise FrameAlignmentError(
            f"seconds={seconds!r} is not frame-aligned at fps={fps!r}; "
            f"exact frame position is {exact_frame}"
        )
    return exact_frame.numerator


def frames_to_seconds_exact(frames: int, fps: FrameRateInput) -> Fraction:
    """Return an exact rational duration for a whole number of frames."""

    return Fraction(_frame(frames, "frames"), 1) / _frame_rate(fps)


@dataclass(frozen=True)
class SourceRange:
    """A source-media frame range using ``[start, end)`` semantics."""

    start_frame: int
    end_frame_exclusive: int

    def __post_init__(self) -> None:
        start = _frame(self.start_frame, "start_frame")
        end = _frame(self.end_frame_exclusive, "end_frame_exclusive")
        if start < 0:
            raise FrameBoundaryError("start_frame must not be negative")
        if end <= start:
            raise FrameBoundaryError(
                "source range must have positive duration under end-exclusive semantics"
            )

    @property
    def duration_frames(self) -> int:
        return self.end_frame_exclusive - self.start_frame


@dataclass(frozen=True)
class Placement:
    segment_id: str
    source_range: SourceRange
    record_frame_relative: int

    @property
    def duration_frames(self) -> int:
        return self.source_range.duration_frames


def build_relative_placements(
    segments: Sequence[tuple[str, SourceRange]],
) -> tuple[Placement, ...]:
    """Lay source ranges contiguously in timeline-relative coordinates."""

    placements: list[Placement] = []
    cursor = 0
    for segment_id, source_range in segments:
        if not segment_id:
            raise FrameBoundaryError("segment_id must not be empty")
        if not isinstance(source_range, SourceRange):
            raise FrameBoundaryError("source_range must be a SourceRange")
        placements.append(Placement(segment_id, source_range, cursor))
        cursor += source_range.duration_frames
    return tuple(placements)


def absolute_timeline_frame(record_frame_relative: int, timeline_start_frame: int) -> int:
    """Map a non-negative relative frame to the timeline's absolute space."""

    relative = _frame(record_frame_relative, "record_frame_relative")
    start = _frame(timeline_start_frame, "timeline_start_frame")
    if relative < 0:
        raise TimelineGeometryError("record_frame_relative must not be negative")
    return start + relative


def assert_not_before_timeline_start(
    actual_start_frame: int | None, timeline_start_frame: int
) -> None:
    """Refuse unreadable or pre-start timeline placement."""

    start = _frame(timeline_start_frame, "timeline_start_frame")
    if actual_start_frame is None:
        raise TimelineGeometryError("actual_start_frame is unreadable")
    actual = _frame(actual_start_frame, "actual_start_frame")
    if actual < start:
        raise TimelineGeometryError(
            f"actual start {actual} is before timeline start {start}"
        )


@dataclass(frozen=True)
class CandidateSlice:
    candidate_id: str
    source_id: str
    source_range: SourceRange
    continuation_group: str | None = None


@dataclass(frozen=True)
class BoundaryAssessment:
    accepted: bool
    code: str
    reason: str


def assess_candidate_cut(
    left: CandidateSlice, right: CandidateSlice
) -> BoundaryAssessment:
    """Detect a candidate boundary that should not become a timeline cut.

    A cut is rejected only when both candidates are contiguous slices of the
    same source and explicitly belong to the same continuation group.
    """

    same_source = left.source_id == right.source_id
    contiguous = (
        left.source_range.end_frame_exclusive == right.source_range.start_frame
    )
    same_continuation = bool(left.continuation_group) and (
        left.continuation_group == right.continuation_group
    )
    if same_source and contiguous and same_continuation:
        return BoundaryAssessment(
            accepted=False,
            code="CANDIDATE_BOUNDARY_SPLITS_CONTINUOUS_SOURCE",
            reason=(
                f"candidate cut {left.candidate_id}->{right.candidate_id} splits "
                f"contiguous source {left.source_id} at frame "
                f"{left.source_range.end_frame_exclusive} within continuation "
                f"group {left.continuation_group}"
            ),
        )
    return BoundaryAssessment(
        accepted=True,
        code="CANDIDATE_BOUNDARY_ACCEPTED",
        reason=(
            f"candidate cut {left.candidate_id}->{right.candidate_id} is not a "
            "same-source contiguous continuation boundary"
        ),
    )


def assess_source_boundary(
    proposed_range: SourceRange, verified_safe_end_frame_exclusive: int
) -> BoundaryAssessment:
    """Check a source range against an evidence-backed maximum safe boundary."""

    safe_end = _frame(
        verified_safe_end_frame_exclusive, "verified_safe_end_frame_exclusive"
    )
    if safe_end < 0:
        raise FrameBoundaryError("verified safe boundary must not be negative")
    if proposed_range.end_frame_exclusive > safe_end:
        return BoundaryAssessment(
            accepted=False,
            code="SOURCE_OUT_EXCEEDS_VERIFIED_BOUNDARY",
            reason=(
                f"source out {proposed_range.end_frame_exclusive} exceeds verified "
                f"safe end-exclusive boundary {safe_end} by "
                f"{proposed_range.end_frame_exclusive - safe_end} frame(s)"
            ),
        )
    return BoundaryAssessment(
        accepted=True,
        code="SOURCE_RANGE_WITHIN_VERIFIED_BOUNDARY",
        reason=(
            f"source out {proposed_range.end_frame_exclusive} is within verified "
            f"safe end-exclusive boundary {safe_end}"
        ),
    )


@dataclass(frozen=True)
class ReadbackVerification:
    accepted: bool
    code: str
    reason: str
    expected_start_frame: int
    expected_end_frame_exclusive: int
    expected_duration_frames: int
    observed_start_frame: int
    observed_end_frame_exclusive: int
    observed_duration_frames: int
    start_delta_frames: int
    end_delta_frames: int
    duration_delta_frames: int


def verify_placement_readback(
    *,
    source_range: SourceRange,
    record_frame_relative: int,
    timeline_start_frame: int,
    observed_start_frame: int,
    observed_end_frame_exclusive: int,
    observed_duration_frames: int,
) -> ReadbackVerification:
    """Compare requested placement geometry with an executor's read-back.

    The function has no editor or transport dependency. A mismatch raises an
    error carrying the complete, auditable verification record.
    """

    expected_start = absolute_timeline_frame(
        record_frame_relative, timeline_start_frame
    )
    expected_duration = source_range.duration_frames
    expected_end = expected_start + expected_duration
    observed_start = _frame(observed_start_frame, "observed_start_frame")
    observed_end = _frame(
        observed_end_frame_exclusive, "observed_end_frame_exclusive"
    )
    observed_duration = _frame(observed_duration_frames, "observed_duration_frames")
    deltas = (
        observed_start - expected_start,
        observed_end - expected_end,
        observed_duration - expected_duration,
    )
    if observed_start < timeline_start_frame:
        code = "TIMELINE_START_VIOLATION"
        reason = (
            f"read-back start {observed_start} is before timeline start "
            f"{timeline_start_frame}"
        )
    elif any(deltas):
        code = "READBACK_MISMATCH"
        reason = (
            "placement read-back mismatch: "
            f"start_delta={deltas[0]}, end_delta={deltas[1]}, "
            f"duration_delta={deltas[2]}"
        )
    else:
        code = "READBACK_MATCH"
        reason = "placement read-back exactly matches requested frame geometry"
    result = ReadbackVerification(
        accepted=code == "READBACK_MATCH",
        code=code,
        reason=reason,
        expected_start_frame=expected_start,
        expected_end_frame_exclusive=expected_end,
        expected_duration_frames=expected_duration,
        observed_start_frame=observed_start,
        observed_end_frame_exclusive=observed_end,
        observed_duration_frames=observed_duration,
        start_delta_frames=deltas[0],
        end_delta_frames=deltas[1],
        duration_delta_frames=deltas[2],
    )
    if not result.accepted:
        raise ReadbackMismatchError(result)
    return result
