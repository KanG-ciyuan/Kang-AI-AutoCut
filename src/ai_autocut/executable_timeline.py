"""Backend-neutral ``executable_timeline.v0`` contract.

An Executable Timeline is the single interchange form that every execution
backend consumes. The point of the contract is that no backend owns the
timeline shape: FFmpeg, DaVinci Resolve, and Jianying are compilers that read
this document, not authors of their own private schema.

Status of this module
---------------------

The *contract and its invariants* are validated here and covered by tests. The
*compilers* are **NOT_IMPLEMENTED**. Nothing in this module talks to FFmpeg,
Resolve, or Jianying.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Mapping, Sequence


SCHEMA_VERSION = "executable_timeline.v0"

#: Backends that must all consume this one contract.
BACKENDS = ("ffmpeg", "davinci", "jianying")

#: Compiler implementation state. Kept explicit so nobody reads a validated
#: contract as a shipped adapter.
COMPILER_STATUS = {backend: "NOT_IMPLEMENTED" for backend in BACKENDS}

#: Frame rate is expressed as an exact rational so 30 and 29.97 stay distinct.
_RATE_PATTERN = re.compile(r"[1-9][0-9]*/[1-9][0-9]*\Z")
_SEGMENT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")

_TIMELINE_KEYS = ("schema_version", "frame_rate", "width", "height", "segments")
_SEGMENT_KEYS = (
    "segment_id",
    "source_id",
    "source_start_frame",
    "source_end_frame_exclusive",
    "record_frame",
)

#: Field names that would silently mix a seconds-based timeline into a
#: frame-canonical contract. Their presence is a contract error, not a warning.
_FORBIDDEN_SECONDS_FIELDS = (
    "source_in_seconds",
    "source_out_seconds",
    "record_seconds",
    "start_seconds",
    "duration_seconds",
)


class ExecutableTimelineContractError(ValueError):
    """Raised when an Executable Timeline cannot be executed unambiguously."""


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ExecutableTimelineContractError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ExecutableTimelineContractError(f"{label} must be a JSON array")
    return value


def _reject_seconds_fields(mapping: Mapping[str, object], label: str) -> None:
    for field in _FORBIDDEN_SECONDS_FIELDS:
        if field in mapping:
            raise ExecutableTimelineContractError(
                f"{label} must not carry {field!r}: the contract is frame-canonical "
                "and refuses to round a seconds value"
            )


def _frame(value: object, label: str, *, allow_zero: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExecutableTimelineContractError(f"{label} must be an integer frame")
    if value < 0 or (value == 0 and not allow_zero):
        raise ExecutableTimelineContractError(f"{label} must be a non-negative frame")
    return value


def _positive_frame(value: object, label: str) -> int:
    result = _frame(value, label)
    if result <= 0:
        raise ExecutableTimelineContractError(f"{label} must be a positive frame count")
    return result


@dataclass(frozen=True)
class TimelineSegment:
    segment_id: str
    source_id: str
    source_start_frame: int
    source_end_frame_exclusive: int
    record_frame: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.segment_id, str)
            or _SEGMENT_ID_PATTERN.fullmatch(self.segment_id) is None
        ):
            raise ExecutableTimelineContractError("segment_id is malformed")
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ExecutableTimelineContractError("source_id must be a logical id")
        if self.source_id.startswith(("/", "~", "\\")):
            raise ExecutableTimelineContractError(
                "source_id must be a logical id, not a filesystem path"
            )
        start = _frame(self.source_start_frame, "source_start_frame")
        end = _frame(self.source_end_frame_exclusive, "source_end_frame_exclusive")
        if end <= start:
            raise ExecutableTimelineContractError(
                "source range must be end-exclusive and non-empty"
            )
        _frame(self.record_frame, "record_frame")

    @property
    def duration_frames(self) -> int:
        return self.source_end_frame_exclusive - self.source_start_frame

    @property
    def record_end_frame_exclusive(self) -> int:
        return self.record_frame + self.duration_frames

    def as_dict(self) -> dict[str, object]:
        return {
            "segment_id": self.segment_id,
            "source_id": self.source_id,
            "source_start_frame": self.source_start_frame,
            "source_end_frame_exclusive": self.source_end_frame_exclusive,
            "record_frame": self.record_frame,
        }


@dataclass(frozen=True)
class ExecutableTimeline:
    frame_rate: str
    width: int
    height: int
    segments: tuple[TimelineSegment, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.frame_rate, str) or _RATE_PATTERN.fullmatch(
            self.frame_rate
        ) is None:
            raise ExecutableTimelineContractError(
                "frame_rate must be an exact rational such as '30/1'"
            )
        for label, value in (("width", self.width), ("height", self.height)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ExecutableTimelineContractError(f"{label} must be a positive integer")
        if not isinstance(self.segments, tuple) or not self.segments:
            raise ExecutableTimelineContractError("segments must be a non-empty tuple")
        self._assert_invariants()

    def _assert_invariants(self) -> None:
        """Enforce the invariants that make execution unambiguous."""

        seen: set[str] = set()
        expected_record = 0
        previous: TimelineSegment | None = None
        for index, segment in enumerate(self.segments):
            if not isinstance(segment, TimelineSegment):
                raise ExecutableTimelineContractError(
                    f"segments[{index}] must be a TimelineSegment"
                )
            if segment.segment_id in seen:
                raise ExecutableTimelineContractError(
                    f"duplicate segment_id: {segment.segment_id!r}"
                )
            seen.add(segment.segment_id)
            if segment.record_frame != expected_record:
                kind = "gap" if segment.record_frame > expected_record else "overlap"
                raise ExecutableTimelineContractError(
                    f"{kind} before segments[{index}]: record_frame "
                    f"{segment.record_frame} does not continue at {expected_record}"
                )
            if previous is not None:
                if segment.record_frame < previous.record_end_frame_exclusive:
                    raise ExecutableTimelineContractError(
                        f"overlap at segments[{index}]"
                    )
            expected_record = segment.record_end_frame_exclusive
            previous = segment

    @property
    def frame_rate_fraction(self) -> tuple[int, int]:
        numerator, denominator = self.frame_rate.split("/")
        return int(numerator), int(denominator)

    @property
    def extent_frames(self) -> int:
        """Total recorded length, which is contiguous by invariant."""

        return sum(segment.duration_frames for segment in self.segments)

    @property
    def duration_seconds(self) -> float:
        numerator, denominator = self.frame_rate_fraction
        return self.extent_frames * denominator / numerator

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "frame_rate": self.frame_rate,
            "width": self.width,
            "height": self.height,
            "segments": [segment.as_dict() for segment in self.segments],
        }


def parse_executable_timeline(document: object) -> ExecutableTimeline:
    """Parse a v0 timeline, refusing seconds-based or path-shaped fields."""

    mapping = _object(document, "executable timeline")
    _reject_seconds_fields(mapping, "executable timeline")
    unknown = sorted(set(mapping) - set(_TIMELINE_KEYS))
    missing = sorted(set(_TIMELINE_KEYS) - set(mapping))
    if unknown:
        raise ExecutableTimelineContractError(
            f"executable timeline has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise ExecutableTimelineContractError(
            f"executable timeline is missing required key(s): {', '.join(missing)}"
        )
    if mapping["schema_version"] != SCHEMA_VERSION:
        raise ExecutableTimelineContractError(
            f"schema_version must be {SCHEMA_VERSION!r}"
        )

    segments: list[TimelineSegment] = []
    for index, raw in enumerate(_array(mapping["segments"], "segments")):
        label = f"segments[{index}]"
        item = _object(raw, label)
        _reject_seconds_fields(item, label)
        item_unknown = sorted(set(item) - set(_SEGMENT_KEYS))
        item_missing = sorted(set(_SEGMENT_KEYS) - set(item))
        if item_unknown:
            raise ExecutableTimelineContractError(
                f"{label} has unsupported key(s): {', '.join(item_unknown)}"
            )
        if item_missing:
            raise ExecutableTimelineContractError(
                f"{label} is missing required key(s): {', '.join(item_missing)}"
            )
        segments.append(
            TimelineSegment(
                segment_id=item["segment_id"],  # type: ignore[arg-type]
                source_id=item["source_id"],  # type: ignore[arg-type]
                source_start_frame=_frame(
                    item["source_start_frame"], f"{label}.source_start_frame"
                ),
                source_end_frame_exclusive=_frame(
                    item["source_end_frame_exclusive"],
                    f"{label}.source_end_frame_exclusive",
                ),
                record_frame=_frame(item["record_frame"], f"{label}.record_frame"),
            )
        )

    return ExecutableTimeline(
        frame_rate=mapping["frame_rate"],  # type: ignore[arg-type]
        width=mapping["width"],  # type: ignore[arg-type]
        height=mapping["height"],  # type: ignore[arg-type]
        segments=tuple(segments),
    )


def render_executable_timeline(timeline: ExecutableTimeline) -> str:
    if not isinstance(timeline, ExecutableTimeline):
        raise ExecutableTimelineContractError("timeline must be an ExecutableTimeline")
    return json.dumps(
        timeline.as_dict(), ensure_ascii=False, sort_keys=True, indent=2
    ) + "\n"


def compile_for_backend(timeline: ExecutableTimeline, backend: str) -> None:
    """Placeholder for a backend compiler. Always refuses today.

    This exists so that "all backends consume one contract" is stated in code
    rather than only in a document, and so an accidental call fails loudly
    instead of returning something that looks like a compiled timeline.
    """

    if not isinstance(timeline, ExecutableTimeline):
        raise ExecutableTimelineContractError("timeline must be an ExecutableTimeline")
    if backend not in BACKENDS:
        raise ExecutableTimelineContractError(
            f"unknown backend {backend!r}; expected one of: {', '.join(BACKENDS)}"
        )
    raise NotImplementedError(
        f"the {backend} compiler is not implemented; executable_timeline.v0 is a "
        "frozen contract without shipped compilers"
    )


def positive_frame_count(value: object, label: str = "frame count") -> int:
    """Shared helper for callers that compare an extent against a real file."""

    return _positive_frame(value, label)
