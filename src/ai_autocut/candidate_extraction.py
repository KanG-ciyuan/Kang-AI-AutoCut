"""Candidate Extraction: measured source windows to traceable Candidates.

Phase 1 defined what Candidate Evidence must say. This module produces the thing
it says it about: Candidate Identity records built from registered material whose
timebase has actually been measured, plus the immutable Candidate Pool that
Planning is allowed to see.

What a Candidate is
-------------------
A Candidate is a source window that can carry an observable action, an
observable result, a product state, or a commercial evidence opportunity. It is
**not** a scene cut. A cut is where the picture changes; a Candidate is where
something can be shown and judged.

Only four window rules are allowed in v1:

``SINGLE_SEGMENT``
    one complete visual segment is a valid Candidate as it stands.
``ADJACENT_MERGE``
    adjacent segments may be merged **only** when one observable action continues
    across the join. A merge is bounded, must cover its listed segments exactly,
    and must be justified by an action whose onset is in the first segment and
    whose result is in the last.
``ACTION_SAFE_WINDOW``
    the shortest window that still contains the whole action and its result:
    ``[action_onset, result_end_exclusive)``.
``SHORTER_ACTION_WINDOW``
    a shorter window inside a parent segment that still shows the action and its
    result. It becomes a **new Candidate Identity**; nothing here trims an
    existing Candidate, and ``editing_plan.v1`` never gains a trim field.

The analyzer proposes, this module disposes
-------------------------------------------
A window may be proposed by an analyzer, but the analyzer has no authority here.
Every proposal is checked against the registered Material, the measured
timestamps, the visual segmentation, the action chronology, and the identity
contract. A proposal that breaks any of them is rejected with a code and a
detail, and the run continues: rejection is an observable outcome, not a
silently dropped window. Nothing guesses a "close enough" time.

Measured time, not assumed time
-------------------------------
Coverage, bounds, and duration come from the source's measured presentation
timestamps (``timebase.frame_table`` by way of ``timebase_adapter``), never from
``frame_index / fps``. For a variable-frame-rate source those two answers differ,
and that difference is the defect this repository already paid for once.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
from typing import Mapping, Sequence

from .candidate_pool import CandidatePool
from .editing_intelligence import (
    ActionEvidence,
    EditingIntelligenceError,
    NarrativeRole,
    validate_timeline_range,
)
from .identity import CandidateIdentity, IdentityCatalog
from .timebase import DEFAULT_FPS
from .timebase_adapter import TimebaseAdapter


#: Schema of the extraction document this module can render.
SCHEMA_VERSION = "candidate_extraction.v1"

#: A Candidate window is expressed as a range of decoded source frames plus the
#: measured presentation timestamp of its first frame. The source half of
#: ``timebase_adapter.COORDINATE_SYSTEM`` is what applies here: there is no
#: timeline frame in a Candidate, because nothing has been placed on a timeline
#: yet. The value is stated in the document so a reader never has to guess which
#: clock a frame number is on.
SOURCE_COORDINATE_SYSTEM = "SOURCE_PTS_SECONDS"

#: A merge may not grow without bound. Four adjacent segments is already a long
#: single beat; a longer window has to be justified as a different Candidate
#: rather than as one widening window.
MAX_MERGE_SEGMENTS = 4

_MATERIAL_ID_PATTERN = re.compile(r"matv1_[0-9a-f]{64}\Z")
#: A logical identifier. The hyphen must stay last in the class: ``._:-_`` would
#: be read as the range ``:`` to ``_`` and would exclude ``-``.
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class CandidateExtractionError(ValueError):
    """Raised when extraction input is malformed rather than merely rejectable."""


class WindowRule(str, Enum):
    """The closed set of allowed Candidate window sources."""

    SINGLE_SEGMENT = "SINGLE_SEGMENT"
    ADJACENT_MERGE = "ADJACENT_MERGE"
    ACTION_SAFE_WINDOW = "ACTION_SAFE_WINDOW"
    SHORTER_ACTION_WINDOW = "SHORTER_ACTION_WINDOW"


class ProposalDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RejectionCode(str, Enum):
    """Why one proposal did not become a Candidate.

    Every code names a deterministic check, not an opinion. Rejection is
    recorded and counted; the proposal never disappears silently.
    """

    UNREGISTERED_MATERIAL = "UNREGISTERED_MATERIAL"
    MEASURED_TIMEBASE_UNAVAILABLE = "MEASURED_TIMEBASE_UNAVAILABLE"
    UNKNOWN_STREAM = "UNKNOWN_STREAM"
    EMPTY_RANGE = "EMPTY_RANGE"
    OUT_OF_MATERIAL_BOUNDS = "OUT_OF_MATERIAL_BOUNDS"
    UNKNOWN_SEGMENT = "UNKNOWN_SEGMENT"
    SEGMENT_NOT_ADJACENT = "SEGMENT_NOT_ADJACENT"
    MERGE_TOO_WIDE = "MERGE_TOO_WIDE"
    WINDOW_NOT_A_SEGMENT = "WINDOW_NOT_A_SEGMENT"
    WINDOW_NOT_THE_MERGE = "WINDOW_NOT_THE_MERGE"
    PARENT_SEGMENT_REQUIRED = "PARENT_SEGMENT_REQUIRED"
    NOT_SHORTER_THAN_PARENT = "NOT_SHORTER_THAN_PARENT"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    ACTION_CHRONOLOGY_INVALID = "ACTION_CHRONOLOGY_INVALID"
    ACTION_ONSET_EXCLUDED = "ACTION_ONSET_EXCLUDED"
    RESULT_TRUNCATED = "RESULT_TRUNCATED"
    ACTION_NOT_CROSSING_BOUNDARY = "ACTION_NOT_CROSSING_BOUNDARY"
    WINDOW_NOT_ACTION_SAFE = "WINDOW_NOT_ACTION_SAFE"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    IDENTITY_CONTRACT_REJECTED = "IDENTITY_CONTRACT_REJECTED"


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise CandidateExtractionError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise CandidateExtractionError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise CandidateExtractionError(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise CandidateExtractionError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CandidateExtractionError(f"{label} must be a non-empty string")
    return value


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or _TOKEN_PATTERN.fullmatch(value) is None:
        raise CandidateExtractionError(
            f"{label} must be a logical token without paths or spaces"
        )
    return value


def _material_id(value: object, label: str = "material_id") -> str:
    if not isinstance(value, str) or _MATERIAL_ID_PATTERN.fullmatch(value) is None:
        raise CandidateExtractionError(f"{label} must match matv1_<sha256>")
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CandidateExtractionError(
            f"{label} must be an integer >= {minimum}"
        )
    return value


def _enum(value: object, member_type: type[Enum], label: str) -> object:
    choices = ", ".join(member.name for member in member_type)
    if not isinstance(value, str):
        raise CandidateExtractionError(f"{label} must be one of: {choices}")
    try:
        return member_type(value)
    except ValueError as exc:
        raise CandidateExtractionError(f"{label} must be one of: {choices}") from exc


@dataclass(frozen=True)
class SourceMeasurement:
    """One registered Material's measured presentation timestamps.

    The table is produced by the existing measurement path
    (:meth:`from_source`, which reads ``timebase_adapter.TimebaseAdapter``), so
    this class never invents a clock. It only answers questions about windows.
    """

    material_id: str
    stream_index: int
    source: str
    timestamps: tuple[float, ...]
    fps: int = DEFAULT_FPS

    def __post_init__(self) -> None:
        _material_id(self.material_id)
        _integer(self.stream_index, "stream_index")
        _text(self.source, "source")
        if isinstance(self.fps, bool) or not isinstance(self.fps, int) or self.fps <= 0:
            raise CandidateExtractionError("fps must be a positive integer")
        values = tuple(self.timestamps)
        if not values:
            raise CandidateExtractionError(
                "a measured source must have at least one frame timestamp"
            )
        previous: float | None = None
        for index, value in enumerate(values):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CandidateExtractionError(
                    f"timestamps[{index}] must be a measured number"
                )
            measured = float(value)
            if measured != measured or measured in (float("inf"), float("-inf")):
                raise CandidateExtractionError(
                    f"timestamps[{index}] must be a finite measured time"
                )
            if measured < 0:
                raise CandidateExtractionError(
                    f"timestamps[{index}] must not be negative"
                )
            if previous is not None and measured <= previous:
                raise CandidateExtractionError(
                    "measured timestamps must increase strictly"
                )
            previous = measured
        object.__setattr__(self, "timestamps", tuple(float(v) for v in values))

    @classmethod
    def from_source(
        cls,
        *,
        material_id: str,
        stream_index: int,
        source: str,
        adapter: TimebaseAdapter,
    ) -> "SourceMeasurement":
        """Measure a real source through the existing timebase adapter."""

        timing = adapter.timing(source)
        return cls(
            material_id=material_id,
            stream_index=stream_index,
            source=source,
            timestamps=tuple(timing.timestamps),
            fps=adapter.fps,
        )

    @property
    def frame_count(self) -> int:
        return len(self.timestamps)

    @property
    def is_variable_frame_rate(self) -> bool:
        """True when the measured cadence is not the nominal ``1 / fps``.

        Same rule as ``timebase.SourceTiming``: the deltas are the source's own,
        so a nominal-rate source is recognised without being assumed.
        """

        expected = 1.0 / self.fps
        for index in range(len(self.timestamps) - 1):
            delta = round(self.timestamps[index + 1] - self.timestamps[index], 5)
            if abs(delta - expected) > 1e-4:
                return True
        return False

    def pts_at(self, frame: int) -> float:
        """The measured timestamp of one decoded frame. Never ``frame / fps``."""

        _integer(frame, "frame")
        if frame >= self.frame_count:
            raise CandidateExtractionError(
                "frame is outside the measured source"
            )
        return self.timestamps[frame]

    def measured_duration_frames(
        self, start_frame: int, end_frame_exclusive: int
    ) -> float:
        """The real duration of a decoded range, from the measured table.

        The last frame's cadence is extrapolated the way
        ``timebase_adapter.measured_duration_seconds`` does, so a range that ends
        at the last frame still gets a real duration instead of a guess.
        """

        if end_frame_exclusive <= start_frame:
            raise CandidateExtractionError("a window must be non-empty")
        if start_frame < 0 or end_frame_exclusive > self.frame_count:
            raise CandidateExtractionError(
                "the window is outside the measured source"
            )
        start = self.timestamps[start_frame]
        if end_frame_exclusive < self.frame_count:
            end = self.timestamps[end_frame_exclusive]
        elif self.frame_count >= 2:
            end = self.timestamps[-1] + (self.timestamps[-1] - self.timestamps[-2])
        else:
            end = self.timestamps[-1] + (1.0 / self.fps)
        return round(end - start, 6)

    def within_bounds(self, start_frame: int, end_frame_exclusive: int) -> bool:
        return 0 <= start_frame < end_frame_exclusive <= self.frame_count

    def as_dict(self) -> dict[str, object]:
        return {
            "material_id": self.material_id,
            "stream_index": self.stream_index,
            "source": self.source,
            "frame_count": self.frame_count,
            "fps": self.fps,
            "variable_frame_rate": self.is_variable_frame_rate,
            "first_pts_seconds": self.timestamps[0],
            "last_pts_seconds": self.timestamps[-1],
        }


@dataclass(frozen=True)
class SegmentSpan:
    """One visual segment in measured source frame indices."""

    segment_index: int
    start_frame: int
    end_frame_exclusive: int

    def __post_init__(self) -> None:
        _integer(self.segment_index, "segment_index")
        _integer(self.start_frame, "start_frame")
        _integer(self.end_frame_exclusive, "end_frame_exclusive")
        if self.end_frame_exclusive <= self.start_frame:
            raise CandidateExtractionError("a visual segment must be non-empty")

    @property
    def duration_frames(self) -> int:
        return self.end_frame_exclusive - self.start_frame

    def as_dict(self) -> dict[str, object]:
        return {
            "segment_index": self.segment_index,
            "start_frame": self.start_frame,
            "end_frame_exclusive": self.end_frame_exclusive,
        }


@dataclass(frozen=True)
class SourceSegmentation:
    """The visual segments of one Material's stream, in source frame indices.

    Segments are ordered and contiguous: each one starts where the previous one
    ended. A gap would make "adjacent merge" ambiguous, so it is refused rather
    than patched.
    """

    material_id: str
    stream_index: int
    segments: tuple[SegmentSpan, ...]

    def __post_init__(self) -> None:
        _material_id(self.material_id)
        _integer(self.stream_index, "stream_index")
        segments = tuple(self.segments)
        if not segments:
            raise CandidateExtractionError("a segmentation must contain a segment")
        for position, segment in enumerate(segments):
            if not isinstance(segment, SegmentSpan):
                raise CandidateExtractionError(
                    f"segments[{position}] must be a SegmentSpan"
                )
            if segment.segment_index != position:
                raise CandidateExtractionError(
                    "segment_index must be the contiguous position of the segment"
                )
            if position and segments[position - 1].end_frame_exclusive != segment.start_frame:
                raise CandidateExtractionError(
                    "visual segments must be contiguous and ordered"
                )
        object.__setattr__(self, "segments", segments)

    @property
    def frame_span(self) -> tuple[int, int]:
        return self.segments[0].start_frame, self.segments[-1].end_frame_exclusive

    def segment(self, index: int) -> SegmentSpan:
        _integer(index, "segment_index")
        if index >= len(self.segments):
            raise CandidateExtractionError("segment_index is outside the segmentation")
        return self.segments[index]

    def union(self, indices: Sequence[int]) -> tuple[int, int]:
        spans = [self.segment(index) for index in indices]
        return spans[0].start_frame, spans[-1].end_frame_exclusive

    def as_dict(self) -> dict[str, object]:
        return {
            "material_id": self.material_id,
            "stream_index": self.stream_index,
            "segments": [segment.as_dict() for segment in self.segments],
        }


@dataclass(frozen=True)
class WindowProposal:
    """One proposed Candidate window, and why it was proposed.

    ``rationale`` is prose for a human reviewer. Every machine decision reads
    ``rule``, the frame range, the segment indices, and the action evidence.
    """

    proposal_id: str
    rule: WindowRule
    material_id: str
    stream_index: int
    start_frame: int
    end_frame_exclusive: int
    rationale: str
    segment_indices: tuple[int, ...] = ()
    parent_segment_indices: tuple[int, ...] = ()
    action_evidence: ActionEvidence | None = None

    def __post_init__(self) -> None:
        _token(self.proposal_id, "proposal_id")
        object.__setattr__(
            self, "rule", _enum(self.rule, WindowRule, "rule")
        )
        _material_id(self.material_id)
        _integer(self.stream_index, "stream_index")
        _integer(self.start_frame, "start_frame")
        _integer(self.end_frame_exclusive, "end_frame_exclusive")
        _text(self.rationale, "rationale")
        indices = tuple(
            _integer(index, f"segment_indices[{position}]")
            for position, index in enumerate(self.segment_indices)
        )
        if len(set(indices)) != len(indices):
            raise CandidateExtractionError("segment_indices must not repeat")
        object.__setattr__(self, "segment_indices", tuple(sorted(indices)))
        if self.action_evidence is not None and not isinstance(
            self.action_evidence, ActionEvidence
        ):
            raise CandidateExtractionError("action_evidence must be ActionEvidence")
        parents = tuple(
            _integer(index, f"parent_segment_indices[{position}]")
            for position, index in enumerate(self.parent_segment_indices)
        )
        if len(set(parents)) != len(parents):
            raise CandidateExtractionError("parent_segment_indices must not repeat")
        parents = tuple(sorted(parents))
        if parents and (
            len(parents) > MAX_MERGE_SEGMENTS
            or parents != tuple(range(parents[0], parents[0] + len(parents)))
        ):
            raise CandidateExtractionError(
                "a parent window must be one bounded run of adjacent segments"
            )
        object.__setattr__(self, "parent_segment_indices", parents)

        if self.rule is WindowRule.SINGLE_SEGMENT:
            if len(indices) != 1:
                raise CandidateExtractionError(
                    "a SINGLE_SEGMENT proposal names exactly one segment"
                )
        elif self.rule is WindowRule.ADJACENT_MERGE:
            if len(indices) < 2:
                raise CandidateExtractionError(
                    "an ADJACENT_MERGE proposal names at least two segments"
                )
            if self.action_evidence is None:
                raise CandidateExtractionError(
                    "an ADJACENT_MERGE proposal must carry the action that spans it"
                )
        elif self.rule is WindowRule.SHORTER_ACTION_WINDOW:
            if not parents:
                raise CandidateExtractionError(
                    "a SHORTER_ACTION_WINDOW proposal names the window it is "
                    "shorter than"
                )
            if self.action_evidence is None:
                raise CandidateExtractionError(
                    "a SHORTER_ACTION_WINDOW proposal must carry its action evidence"
                )
        elif self.action_evidence is None:
            raise CandidateExtractionError(
                "an ACTION_SAFE_WINDOW proposal must carry its action evidence"
            )

    @property
    def frame_range(self) -> tuple[int, int]:
        return self.start_frame, self.end_frame_exclusive

    def as_dict(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "rule": self.rule.value,
            "material_id": self.material_id,
            "stream_index": self.stream_index,
            "start_frame": self.start_frame,
            "end_frame_exclusive": self.end_frame_exclusive,
            "segment_indices": list(self.segment_indices),
            "parent_segment_indices": list(self.parent_segment_indices),
            "action_evidence": (
                None
                if self.action_evidence is None
                else {
                    "preparation_start": self.action_evidence.preparation_start,
                    "action_onset": self.action_evidence.action_onset,
                    "action_completion": self.action_evidence.action_completion,
                    "result_end_exclusive": self.action_evidence.result_end_exclusive,
                }
            ),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class MeasuredWindow:
    """A Candidate's window in measured source time."""

    t_in_seconds: float
    t_out_seconds: float
    duration_seconds: float
    frame_count: int
    variable_frame_rate: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "t_in_seconds": self.t_in_seconds,
            "t_out_seconds": self.t_out_seconds,
            "duration_seconds": self.duration_seconds,
            "frame_count": self.frame_count,
            "variable_frame_rate": self.variable_frame_rate,
            "coordinate_system": SOURCE_COORDINATE_SYSTEM,
        }


@dataclass(frozen=True)
class ProposalOutcome:
    """The deterministic verdict on one proposal."""

    proposal: WindowProposal
    decision: ProposalDecision
    detail: str
    rejection: RejectionCode | None = None
    candidate: CandidateIdentity | None = None
    measured: MeasuredWindow | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, WindowProposal):
            raise CandidateExtractionError("proposal must be a WindowProposal")
        object.__setattr__(
            self, "decision", _enum(self.decision, ProposalDecision, "decision")
        )
        _text(self.detail, "detail")
        if self.decision is ProposalDecision.ACCEPTED:
            if self.rejection is not None:
                raise CandidateExtractionError(
                    "an accepted proposal carries no rejection code"
                )
            if self.candidate is None or self.measured is None:
                raise CandidateExtractionError(
                    "an accepted proposal carries its Candidate and measured window"
                )
        else:
            if self.rejection is None:
                raise CandidateExtractionError(
                    "a rejected proposal states its rejection code"
                )
            if self.candidate is not None:
                raise CandidateExtractionError(
                    "a rejected proposal carries no Candidate"
                )

    @property
    def accepted(self) -> bool:
        return self.decision is ProposalDecision.ACCEPTED

    def as_dict(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal.proposal_id,
            "rule": self.proposal.rule.value,
            "decision": self.decision.value,
            "rejection": None if self.rejection is None else self.rejection.value,
            "detail": self.detail,
            "candidate_id": None if self.candidate is None else self.candidate.candidate_id,
            "material_id": self.proposal.material_id,
            "stream_index": self.proposal.stream_index,
            "start_frame": self.proposal.start_frame,
            "end_frame_exclusive": self.proposal.end_frame_exclusive,
            "measured": None if self.measured is None else self.measured.as_dict(),
        }


@dataclass(frozen=True)
class CandidateExtraction:
    """Accepted Candidates, rejected proposals, the Pool, and the counters.

    ``catalog`` is the supplied Identity Catalog extended with the Candidates
    that were accepted here, so downstream validation (Candidate Pool and
    Candidate Evidence) can resolve them without a second identity system.
    """

    measurements: tuple[SourceMeasurement, ...]
    segmentations: tuple[SourceSegmentation, ...]
    outcomes: tuple[ProposalOutcome, ...]
    candidates: tuple[CandidateIdentity, ...]
    pool: CandidatePool
    catalog: IdentityCatalog
    skipped_fragments: tuple[tuple[str, int, int], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.pool, CandidatePool):
            raise CandidateExtractionError("pool must be a CandidatePool")
        if not isinstance(self.catalog, IdentityCatalog):
            raise CandidateExtractionError("catalog must be an IdentityCatalog")
        candidate_ids = [item.candidate_id for item in self.candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise CandidateExtractionError("duplicate Candidate in extraction result")
        if set(candidate_ids) != {entry.candidate_id for entry in self.pool.entries}:
            raise CandidateExtractionError(
                "the Candidate Pool must contain exactly the accepted Candidates"
            )

    @property
    def accepted(self) -> tuple[ProposalOutcome, ...]:
        return tuple(item for item in self.outcomes if item.accepted)

    @property
    def rejected(self) -> tuple[ProposalOutcome, ...]:
        return tuple(item for item in self.outcomes if not item.accepted)

    def candidate(self, candidate_id: str) -> CandidateIdentity:
        for item in self.candidates:
            if item.candidate_id == candidate_id:
                return item
        raise CandidateExtractionError("candidate_id was not extracted here")

    def measured_for(self, candidate_id: str) -> MeasuredWindow:
        for outcome in self.outcomes:
            if outcome.candidate is not None and outcome.candidate.candidate_id == candidate_id:
                assert outcome.measured is not None  # ensured by ProposalOutcome
                return outcome.measured
        raise CandidateExtractionError("candidate_id was not extracted here")

    def rejection_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for outcome in self.rejected:
            assert outcome.rejection is not None
            counts[outcome.rejection.value] = counts.get(outcome.rejection.value, 0) + 1
        return dict(sorted(counts.items()))

    def counts(self) -> dict[str, int]:
        """The observability counters for this stage."""

        return {
            "materials": len({item.material_id for item in self.measurements}),
            "measured_streams": len(self.measurements),
            "visual_segments": sum(len(item.segments) for item in self.segmentations),
            "skipped_fragments": len(self.skipped_fragments),
            "candidate_proposals": len(self.outcomes),
            "accepted_candidates": len(self.candidates),
            "rejected_proposals": len(self.rejected),
            "candidate_pool_size": len(self.pool.entries),
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "measurements": [item.as_dict() for item in self.measurements],
            "segmentations": [item.as_dict() for item in self.segmentations],
            "proposals": [item.as_dict() for item in self.outcomes],
            "accepted_candidates": [
                {
                    **candidate.as_dict(),
                    "rule": next(
                        outcome.proposal.rule.value
                        for outcome in self.accepted
                        if outcome.candidate is not None
                        and outcome.candidate.candidate_id == candidate.candidate_id
                    ),
                    "measured": self.measured_for(candidate.candidate_id).as_dict(),
                }
                for candidate in self.candidates
            ],
            "skipped_fragments": [
                {"material_id": material_id, "start_frame": start, "end_frame_exclusive": end}
                for material_id, start, end in self.skipped_fragments
            ],
            "rejection_counts": self.rejection_counts(),
            "counts": self.counts(),
            "pool_id": self.pool.pool_id,
        }


def render_extraction(extraction: CandidateExtraction) -> str:
    if not isinstance(extraction, CandidateExtraction):
        raise CandidateExtractionError("extraction must be a CandidateExtraction")
    return (
        json.dumps(extraction.as_dict(), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n"
    )


def parse_window_proposals(document: object) -> tuple[WindowProposal, ...]:
    """Parse one ``candidate_window_proposal.v1`` document from the analyzer."""

    mapping = _object(document, "candidate window proposal")
    _exact_keys(
        mapping, ("schema_version", "proposals"), "candidate window proposal"
    )
    if mapping["schema_version"] != "candidate_window_proposal.v1":
        raise CandidateExtractionError(
            "schema_version must be 'candidate_window_proposal.v1'"
        )
    proposals: list[WindowProposal] = []
    for position, raw in enumerate(_array(mapping["proposals"], "proposals")):
        item = _object(raw, f"proposals[{position}]")
        _exact_keys(
            item,
            (
                "proposal_id",
                "rule",
                "material_id",
                "stream_index",
                "start_frame",
                "end_frame_exclusive",
                "segment_indices",
                "parent_segment_indices",
                "action_evidence",
                "rationale",
            ),
            f"proposals[{position}]",
        )
        raw_action = item["action_evidence"]
        action: ActionEvidence | None = None
        if raw_action is not None:
            action_mapping = _object(
                raw_action, f"proposals[{position}].action_evidence"
            )
            _exact_keys(
                action_mapping,
                (
                    "preparation_start",
                    "action_onset",
                    "action_completion",
                    "result_end_exclusive",
                ),
                f"proposals[{position}].action_evidence",
            )
            try:
                action = ActionEvidence(
                    preparation_start=action_mapping["preparation_start"],  # type: ignore[arg-type]
                    action_onset=action_mapping["action_onset"],  # type: ignore[arg-type]
                    action_completion=action_mapping["action_completion"],  # type: ignore[arg-type]
                    result_end_exclusive=action_mapping["result_end_exclusive"],  # type: ignore[arg-type]
                )
            except EditingIntelligenceError as exc:
                raise CandidateExtractionError(
                    f"proposals[{position}].action_evidence chronology is invalid: {exc}"
                ) from exc
        proposals.append(
            WindowProposal(
                proposal_id=item["proposal_id"],  # type: ignore[arg-type]
                rule=_enum(  # type: ignore[arg-type]
                    item["rule"], WindowRule, f"proposals[{position}].rule"
                ),
                material_id=item["material_id"],  # type: ignore[arg-type]
                stream_index=item["stream_index"],  # type: ignore[arg-type]
                start_frame=item["start_frame"],  # type: ignore[arg-type]
                end_frame_exclusive=item["end_frame_exclusive"],  # type: ignore[arg-type]
                rationale=item["rationale"],  # type: ignore[arg-type]
                segment_indices=tuple(
                    _array(
                        item["segment_indices"],
                        f"proposals[{position}].segment_indices",
                    )
                ),  # type: ignore[arg-type]
                parent_segment_indices=tuple(
                    _array(
                        item["parent_segment_indices"],
                        f"proposals[{position}].parent_segment_indices",
                    )
                ),  # type: ignore[arg-type]
                action_evidence=action,
            )
        )
    return tuple(proposals)


def render_window_proposals(proposals: Sequence[WindowProposal]) -> str:
    """Render a proposal document, preserving the analyzer's order.

    Order is meaningful here and is therefore not canonicalised away. Two
    proposals may describe the same window; the first one becomes the Candidate
    and the later one is rejected as ``DUPLICATE_IDENTITY``. Sorting the document
    would silently change which proposal won, so it is not sorted.
    """

    if isinstance(proposals, (str, bytes)) or not isinstance(proposals, Sequence):
        raise CandidateExtractionError("proposals must be a sequence")
    for position, proposal in enumerate(proposals):
        if not isinstance(proposal, WindowProposal):
            raise CandidateExtractionError(
                f"proposals[{position}] must be a WindowProposal"
            )
    document = {
        "schema_version": "candidate_window_proposal.v1",
        "proposals": [proposal.as_dict() for proposal in proposals],
    }
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _measurement_index(
    measurements: Sequence[SourceMeasurement],
) -> dict[tuple[str, int], SourceMeasurement]:
    index: dict[tuple[str, int], SourceMeasurement] = {}
    for position, measurement in enumerate(measurements):
        if not isinstance(measurement, SourceMeasurement):
            raise CandidateExtractionError(
                f"measurements[{position}] must be a SourceMeasurement"
            )
        key = (measurement.material_id, measurement.stream_index)
        if key in index:
            raise CandidateExtractionError(
                "a Material stream may be measured only once"
            )
        index[key] = measurement
    return index


def _segmentation_index(
    segmentations: Sequence[SourceSegmentation],
) -> dict[tuple[str, int], SourceSegmentation]:
    index: dict[tuple[str, int], SourceSegmentation] = {}
    for position, segmentation in enumerate(segmentations):
        if not isinstance(segmentation, SourceSegmentation):
            raise CandidateExtractionError(
                f"segmentations[{position}] must be a SourceSegmentation"
            )
        key = (segmentation.material_id, segmentation.stream_index)
        if key in index:
            raise CandidateExtractionError(
                "a Material stream may be segmented only once"
            )
        index[key] = segmentation
    return index


def _reject(
    proposal: WindowProposal, code: RejectionCode, detail: str
) -> ProposalOutcome:
    return ProposalOutcome(
        proposal=proposal,
        decision=ProposalDecision.REJECTED,
        rejection=code,
        detail=detail,
    )


def _measured_window(
    candidate: CandidateIdentity, measurement: SourceMeasurement
) -> MeasuredWindow:
    """The window in measured source time: measured in-point, real duration, end."""

    t_in = round(measurement.pts_at(candidate.start_frame), 6)
    duration = measurement.measured_duration_frames(
        candidate.start_frame, candidate.end_frame_exclusive
    )
    return MeasuredWindow(
        t_in_seconds=t_in,
        t_out_seconds=round(t_in + duration, 6),
        duration_seconds=duration,
        frame_count=candidate.end_frame_exclusive - candidate.start_frame,
        variable_frame_rate=measurement.is_variable_frame_rate,
    )


def _accept(
    proposal: WindowProposal,
    candidate: CandidateIdentity,
    measurement: SourceMeasurement,
) -> ProposalOutcome:
    return ProposalOutcome(
        proposal=proposal,
        decision=ProposalDecision.ACCEPTED,
        detail="window accepted by the boundary validator",
        candidate=candidate,
        measured=_measured_window(candidate, measurement),
    )


def validate_proposal(
    proposal: WindowProposal,
    *,
    catalog: IdentityCatalog,
    measurements: Mapping[tuple[str, int], SourceMeasurement],
    segmentations: Mapping[tuple[str, int], SourceSegmentation],
    taken: set[str],
) -> ProposalOutcome:
    """The boundary validator. Everything a proposal claims is checked here.

    Order matters: identity and measurement first, then geometry, then the rule
    the proposal chose, then the action. The first failure is the recorded one,
    so a rejection always names the earliest thing that was wrong.
    """

    if not isinstance(proposal, WindowProposal):
        raise CandidateExtractionError("proposal must be a WindowProposal")
    if not isinstance(catalog, IdentityCatalog):
        raise CandidateExtractionError("catalog must be an IdentityCatalog")

    try:
        catalog.material(proposal.material_id)
    except ValueError as exc:
        return _reject(
            proposal,
            RejectionCode.UNREGISTERED_MATERIAL,
            f"the Material is not registered in the Identity Catalog: {exc}",
        )

    key = (proposal.material_id, proposal.stream_index)
    measurement = measurements.get(key)
    if measurement is None:
        return _reject(
            proposal,
            RejectionCode.MEASURED_TIMEBASE_UNAVAILABLE,
            "no measured timebase is available for this Material stream",
        )
    segmentation = segmentations.get(key)

    if proposal.end_frame_exclusive <= proposal.start_frame:
        return _reject(
            proposal,
            RejectionCode.EMPTY_RANGE,
            "a Candidate window must be non-empty",
        )
    if not measurement.within_bounds(
        proposal.start_frame, proposal.end_frame_exclusive
    ):
        return _reject(
            proposal,
            RejectionCode.OUT_OF_MATERIAL_BOUNDS,
            "the window is outside the measured bounds of the Material stream",
        )

    span_of = (
        {segment.segment_index: (segment.start_frame, segment.end_frame_exclusive)
         for segment in segmentation.segments}
        if segmentation
        else {}
    )

    def known(indices: Sequence[int]) -> bool:
        return all(index in span_of for index in indices)

    if proposal.rule is WindowRule.SINGLE_SEGMENT:
        if segmentation is None or not known(proposal.segment_indices):
            return _reject(
                proposal,
                RejectionCode.UNKNOWN_SEGMENT,
                "the proposal names a segment the segmentation does not contain",
            )
        expected = span_of[proposal.segment_indices[0]]
        if proposal.frame_range != expected:
            return _reject(
                proposal,
                RejectionCode.WINDOW_NOT_A_SEGMENT,
                "a SINGLE_SEGMENT window must be exactly its visual segment",
            )
    elif proposal.rule is WindowRule.ADJACENT_MERGE:
        if segmentation is None or not known(proposal.segment_indices):
            return _reject(
                proposal,
                RejectionCode.UNKNOWN_SEGMENT,
                "the proposal names a segment the segmentation does not contain",
            )
        indices = list(proposal.segment_indices)
        if indices != list(range(indices[0], indices[0] + len(indices))):
            return _reject(
                proposal,
                RejectionCode.SEGMENT_NOT_ADJACENT,
                "a merge may only join adjacent segments",
            )
        if len(indices) > MAX_MERGE_SEGMENTS:
            return _reject(
                proposal,
                RejectionCode.MERGE_TOO_WIDE,
                f"a merge may not exceed {MAX_MERGE_SEGMENTS} adjacent segments",
            )
        if proposal.frame_range != (span_of[indices[0]][0], span_of[indices[-1]][1]):
            return _reject(
                proposal,
                RejectionCode.WINDOW_NOT_THE_MERGE,
                "a merged window must be exactly the union of its segments",
            )
    elif proposal.rule is WindowRule.SHORTER_ACTION_WINDOW:
        parents = list(proposal.parent_segment_indices)
        if segmentation is None or not known(parents):
            return _reject(
                proposal,
                RejectionCode.PARENT_SEGMENT_REQUIRED,
                "the proposal names a parent window the segmentation does not contain",
            )
        if parents != list(range(parents[0], parents[0] + len(parents))):
            return _reject(
                proposal,
                RejectionCode.SEGMENT_NOT_ADJACENT,
                "a parent window may only join adjacent segments",
            )
        parent = (span_of[parents[0]][0], span_of[parents[-1]][1])
        if not (
            parent[0] <= proposal.start_frame
            and proposal.end_frame_exclusive <= parent[1]
        ):
            return _reject(
                proposal,
                RejectionCode.PARENT_SEGMENT_REQUIRED,
                "a shorter window must lie inside the window it shortens",
            )
        if proposal.frame_range == parent:
            return _reject(
                proposal,
                RejectionCode.NOT_SHORTER_THAN_PARENT,
                "a SHORTER_ACTION_WINDOW proposal must be shorter than its parent",
            )
    else:
        # ACTION_SAFE_WINDOW: the span is the action's, not a segment's, so any
        # segment indices it volunteers must still name real segments.
        if proposal.segment_indices and (
            segmentation is None or not known(proposal.segment_indices)
        ):
            return _reject(
                proposal,
                RejectionCode.UNKNOWN_SEGMENT,
                "the proposal names a segment the segmentation does not contain",
            )

    action = proposal.action_evidence
    if action is None:
        # Rule A needs no action: a complete visual segment is a Candidate as it
        # stands. The other three rules cannot be justified without one.
        if proposal.rule is not WindowRule.SINGLE_SEGMENT:
            return _reject(
                proposal,
                RejectionCode.ACTION_REQUIRED,
                "this window rule requires the action that justifies it",
            )
    else:
        if proposal.rule is WindowRule.ACTION_SAFE_WINDOW:
            expected = (action.action_onset, action.result_end_exclusive)
            if proposal.frame_range != expected:
                return _reject(
                    proposal,
                    RejectionCode.WINDOW_NOT_ACTION_SAFE,
                    "an ACTION_SAFE_WINDOW must be exactly "
                    "[action_onset, result_end_exclusive)",
                )

        if proposal.rule is WindowRule.ADJACENT_MERGE:
            indices = list(proposal.segment_indices)
            first = span_of[indices[0]]
            last = span_of[indices[-1]]
            onset_inside = first[0] <= action.action_onset < first[1]
            result_inside = last[0] < action.result_end_exclusive <= last[1]
            straddles = any(
                action.action_onset < span_of[index][1] <= action.result_end_exclusive
                for index in indices[:-1]
            )
            if not (onset_inside and result_inside and straddles):
                return _reject(
                    proposal,
                    RejectionCode.ACTION_NOT_CROSSING_BOUNDARY,
                    "a merge requires one observable action whose onset is in the "
                    "first segment and whose result is in the last",
                )

        try:
            validate_timeline_range(
                role=NarrativeRole.ACTION,
                start_frame=proposal.start_frame,
                end_frame_exclusive=proposal.end_frame_exclusive,
                evidence=action,
            )
        except EditingIntelligenceError as exc:
            # The shared validator owns "an action-like range must keep the
            # action and its result". The code is attributed here so a rejection
            # names the specific defect rather than repeating the message.
            code = (
                RejectionCode.ACTION_ONSET_EXCLUDED
                if proposal.start_frame > action.action_onset
                else RejectionCode.RESULT_TRUNCATED
            )
            return _reject(proposal, code, str(exc))

    try:
        candidate = CandidateIdentity.create(
            proposal.material_id,
            proposal.stream_index,
            proposal.start_frame,
            proposal.end_frame_exclusive,
        )
    except ValueError as exc:
        return _reject(
            proposal,
            RejectionCode.IDENTITY_CONTRACT_REJECTED,
            f"the identity contract refused this window: {exc}",
        )
    if candidate.candidate_id in taken:
        return _reject(
            proposal,
            RejectionCode.DUPLICATE_IDENTITY,
            "another accepted proposal already produced this Candidate Identity",
        )
    return _accept(proposal, candidate, measurement)


def extract_candidates(
    *,
    catalog: IdentityCatalog,
    measurements: Sequence[SourceMeasurement],
    segmentations: Sequence[SourceSegmentation],
    proposals: Sequence[WindowProposal],
) -> CandidateExtraction:
    """Validate every proposal and build the immutable Candidate Pool.

    The Pool contains only membership. Nothing semantic enters it: no label, no
    score, no claim, no confidence, no approval. Analysis belongs in Candidate
    Evidence, which is a different artifact.
    """

    if not isinstance(catalog, IdentityCatalog):
        raise CandidateExtractionError("catalog must be an IdentityCatalog")
    measurement_index = _measurement_index(measurements)
    segmentation_index = _segmentation_index(segmentations)

    outcomes: list[ProposalOutcome] = []
    taken: set[str] = set()
    for proposal in proposals:
        outcome = validate_proposal(
            proposal,
            catalog=catalog,
            measurements=measurement_index,
            segmentations=segmentation_index,
            taken=taken,
        )
        if outcome.accepted:
            assert outcome.candidate is not None
            taken.add(outcome.candidate.candidate_id)
        outcomes.append(outcome)

    candidates = tuple(
        sorted(
            (outcome.candidate for outcome in outcomes if outcome.candidate is not None),
            key=lambda item: item.candidate_id,
        )
    )
    pool = CandidatePool.create([item.candidate_id for item in candidates])
    extended = IdentityCatalog(
        materials=catalog.materials,
        candidates=tuple(catalog.candidates) + candidates,
    )
    return CandidateExtraction(
        measurements=tuple(measurements),
        segmentations=tuple(segmentations),
        outcomes=tuple(outcomes),
        candidates=candidates,
        pool=pool,
        catalog=extended,
    )


def proposals_from_segmentation(
    segmentation: SourceSegmentation,
    *,
    measurement: SourceMeasurement,
    skip_accidental_fragments: bool = True,
) -> tuple[tuple[WindowProposal, ...], tuple[tuple[str, int, int], ...]]:
    """Deterministically propose one Candidate per complete visual segment.

    This is rule A only. Rules B, C, and D need to know what an *action* is, and
    that is a semantic judgement, so those windows come from the analyzer instead
    of being guessed here. Returns the proposals and the spans that were skipped
    as accidental fragments (a one or two frame window cannot carry a beat).

    Skipping an accidental fragment is a stated policy and is counted. Skipping a
    segment for any *other* reason would be a silent gap, so it does not happen:
    a segment outside the measured bounds is proposed and then rejected by the
    boundary validator, and the rejection appears in the extraction result.
    """

    if not isinstance(segmentation, SourceSegmentation):
        raise CandidateExtractionError("segmentation must be a SourceSegmentation")
    if not isinstance(measurement, SourceMeasurement):
        raise CandidateExtractionError("measurement must be a SourceMeasurement")
    if (
        segmentation.material_id != measurement.material_id
        or segmentation.stream_index != measurement.stream_index
    ):
        raise CandidateExtractionError(
            "the segmentation and the measurement describe different streams"
        )

    proposals: list[WindowProposal] = []
    skipped: list[tuple[str, int, int]] = []
    for segment in segmentation.segments:
        frame_range = (segment.start_frame, segment.end_frame_exclusive)
        if skip_accidental_fragments and segment.duration_frames <= 2:
            skipped.append((segmentation.material_id, *frame_range))
            continue
        # A segment outside the measured table is still proposed, on purpose. The
        # boundary validator then rejects it with OUT_OF_MATERIAL_BOUNDS, so the
        # disagreement between the segmentation and the measurement is recorded in
        # the extraction result instead of disappearing here. A segmentation that
        # runs past the end of its source is exactly the kind of defect that must
        # not become a silent gap in the Pool.
        proposals.append(
            WindowProposal(
                proposal_id=f"wpropv1_seg{segment.segment_index:06d}",
                rule=WindowRule.SINGLE_SEGMENT,
                material_id=segmentation.material_id,
                stream_index=segmentation.stream_index,
                start_frame=segment.start_frame,
                end_frame_exclusive=segment.end_frame_exclusive,
                segment_indices=(segment.segment_index,),
                rationale=(
                    "one complete visual segment is a Candidate as it stands"
                ),
            )
        )
    return tuple(proposals), tuple(skipped)
