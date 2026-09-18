"""Shot Understanding Foundation — A1 segmentation, A2 grouping, A3 comprehension.

Three capabilities, one deterministic pass, answering three questions in order:

  A1  how many real visual shots are actually inside this window?
  A2  which of those shots are the same thing happening?
  A3  does this group get enough time to be understood?

Design constraints inherited from the frozen Batch 1 specification:

* ``Candidate Window != Visual Segment``. Candidate edges are never treated as real
  visual boundaries.
* The decode is forced to CFR before any comparison. A raw decode of a variable-PTS
  source compares non-adjacent frames and reports cuts that are not there.
* Nothing here is product-specific, category-specific or job-specific. There is no
  reference to any known cut list, candidate id or product.
* A3 produces a **warning**, never a build failure, and it must name *which* factor was
  short. There is no universal minimum duration: ``Comprehension Requirement > Fixed
  Duration Threshold``.

This module is an analysis plane. It annotates evidence; it never edits a timeline.
"""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Iterable, Sequence

import numpy as np

#: Forced constant frame rate for every comparison. Non-negotiable.
CFR_FPS = 30

#: Difference threshold, in mean-absolute-difference units on the analysis raster.
#: Chosen from the metric's own distribution, not from any expected answer: on the
#: reference corpus the per-frame differences are grouped around a median of ~6 with a
#: single outlier at 20, and the real boundaries form a separate cluster from 43 upward.
#: The threshold sits in that valley. Any value in roughly 25-35 produces identical
#: boundaries.
DETECTION_THRESHOLD = 30.0

#: Analysis raster. Small enough to decode quickly, large enough that a cut remains a
#: large spike.
ANALYSIS_WIDTH = 270
ANALYSIS_HEIGHT = 480

#: Diagnostic only. Reported as a metric, never applied as a defect rule: a 0.5-0.7s
#: shot is legitimate as an established-context insert, a detail beat or a rhythm beat.
MICRO_FRAGMENT_SECONDS = 0.75

#: Accidental fragments. A 1-2 frame segment cannot be an intentional beat.
ACCIDENTAL_FRAGMENT_FRAMES = 2

#: How far a documented window edge may sit from the real cut it approximates. A sliver
#: this short between two windows is the edge seen twice, not a shot.
EDGE_TOLERANCE_FRAMES = 2

#: Roles that can complete an Action -> Result relationship.
RESULT_ROLES = frozenset({"proof", "identity", "hero", "ending"})

#: Roles that carry an action.
ACTION_ROLES = frozenset({"action"})

#: Roles that establish the product, so later groups need less reading time.
ESTABLISHING_ROLES = frozenset({"hook", "identity"})

#: Heuristic comprehension requirement per narrative role, in seconds. These are
#: STARTING VALUES for a warning heuristic, deliberately explicit so they can be
#: reviewed and adjusted. They are not a threshold and are not applied as one.
#:
#: Calibration anchor: the accepted D.5 edit contains units of 0.73s (a closing
#: identity beat) and 0.77s (a complete purchase-check detail) which a human accepted,
#: and units of 0.60s and 0.40s which were dropped. The heuristic must separate those
#: on composition and context, not on length alone.
ROLE_BASE_SECONDS = {
    "hook": 0.9,
    "identity": 0.9,
    "action": 1.5,
    "proof": 1.0,
    "hero": 2.1,
    "ending": 1.1,
}

#: Each extra visual segment inside one group adds something new to read.
COMPLEXITY_PER_EXTRA_SEGMENT = 0.12

#: Credit when the product is already established by an earlier beat.
CONTEXT_CREDIT_SECONDS = 0.45

#: Credit for a deliberate insert: one segment covering its whole window, not an action,
#: in established context. This is the case the gate says must not be penalised.
SIMPLE_INSERT_CREDIT_SECONDS = 0.35

#: The floor a deliberate insert still has to clear. The gate states the legitimate
#: range for an established-context insert as roughly 0.5-0.7s, so the floor sits at the
#: bottom of that range. This is NOT a universal minimum shot duration: it only ever
#: applies to a group that already qualifies as a deliberate insert, and it is not
#: applied to fragments, to actions, or to anything without established context.
MIN_SIMPLE_INSERT_SECONDS = 0.50


class ShotUnderstandingError(ValueError):
    """Raised when shot understanding cannot be computed safely."""


# --------------------------------------------------------------------------- A1


@dataclass(frozen=True)
class VisualBoundary:
    """A real visual boundary: the first frame of the new shot."""

    frame_index: int
    difference: float

    def __post_init__(self) -> None:
        if self.frame_index < 1:
            raise ShotUnderstandingError("a boundary cannot be the first frame")
        if self.difference <= 0:
            raise ShotUnderstandingError("a boundary must record a positive difference")


@dataclass(frozen=True)
class VisualSegment:
    """One real visual shot, half-open ``[start, end)`` in the analysis frame space."""

    start_frame: int
    end_frame_exclusive: int

    def __post_init__(self) -> None:
        if self.end_frame_exclusive <= self.start_frame:
            raise ShotUnderstandingError("a segment must be non-empty")

    @property
    def duration_frames(self) -> int:
        return self.end_frame_exclusive - self.start_frame

    @property
    def duration_seconds(self) -> float:
        return self.duration_frames / CFR_FPS

    @property
    def is_micro_fragment(self) -> bool:
        """Diagnostic metric only. Never a defect on its own."""

        return self.duration_seconds < MICRO_FRAGMENT_SECONDS

    @property
    def is_accidental_fragment(self) -> bool:
        """A 1-2 frame segment cannot be an intentional beat."""

        return self.duration_frames <= ACCIDENTAL_FRAGMENT_FRAMES


@dataclass(frozen=True)
class Placement:
    """A window placed on a timeline: a candidate window, or a shot in an edit."""

    placement_id: str
    source_id: str
    media_path: str
    source_in: int
    source_out_exclusive: int
    timeline_start: int = 0
    narrative_role: str = "identity"
    action_state: str = ""
    #: The parent candidate's available range, when this placement is a shot inside an
    #: edit rather than the candidate itself. Used only to detect truncation.
    candidate_in: int | None = None
    candidate_out_exclusive: int | None = None


@dataclass(frozen=True)
class PlacementAnalysis:
    """A placement split into the real visual segments it contains."""

    placement_id: str
    source_id: str
    narrative_role: str
    source_in: int
    source_out_exclusive: int
    timeline_start: int
    segments: tuple[VisualSegment, ...]
    internal_boundaries: tuple[VisualBoundary, ...]
    #: True when this window continues the previous one in the same source file with no
    #: visual boundary at the join. A real shot can straddle a window edge, so the edge
    #: is not automatically a cut.
    joins_previous: bool = False

    @property
    def duration_seconds(self) -> float:
        return (self.source_out_exclusive - self.source_in) / CFR_FPS

    @property
    def contains_internal_cuts(self) -> bool:
        return bool(self.internal_boundaries)


def decode_differences(
    media_path: str, *, fps: int = CFR_FPS,
    width: int = ANALYSIS_WIDTH, height: int = ANALYSIS_HEIGHT,
) -> tuple[int, list[float]]:
    """Decode at a forced CFR and return (frame_count, per-frame difference).

    The difference list has ``frame_count - 1`` entries; ``differences[i]`` is the
    mean absolute difference between frame ``i`` and frame ``i + 1``.
    """

    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", media_path,
        "-vf", f"fps={fps},scale={width}:{height}",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    frame_bytes = width * height * 3
    previous: np.ndarray | None = None
    count = 0
    differences: list[float] = []
    try:
        while True:
            raw = process.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            current = np.frombuffer(raw, dtype=np.uint8).astype(np.int16)
            if previous is not None:
                differences.append(float(np.abs(current - previous).mean()))
            previous = current
            count += 1
    finally:
        process.stdout.close()
        process.wait()
    if count == 0:
        raise ShotUnderstandingError(f"no frames decoded from {media_path}")
    return count, differences


def detect_boundaries(
    differences: Sequence[float], *, threshold: float = DETECTION_THRESHOLD
) -> tuple[VisualBoundary, ...]:
    """Return the boundaries where the frame-to-frame difference spikes.

    Deterministic: the same input always yields the same boundaries.
    """

    return tuple(
        VisualBoundary(frame_index=index + 1, difference=round(value, 4))
        for index, value in enumerate(differences)
        if value > threshold
    )


def split_into_segments(
    start_frame: int, end_frame_exclusive: int, boundaries: Iterable[VisualBoundary]
) -> tuple[tuple[VisualSegment, ...], tuple[VisualBoundary, ...]]:
    """Split ``[start, end)`` at the boundaries that fall strictly inside it."""

    inside = [b for b in boundaries if start_frame < b.frame_index < end_frame_exclusive]
    edges = [start_frame] + [b.frame_index for b in inside] + [end_frame_exclusive]
    segments = tuple(
        VisualSegment(edges[i], edges[i + 1]) for i in range(len(edges) - 1)
    )
    return segments, tuple(inside)


def analyse_placements(
    placements: Sequence[Placement], *, threshold: float = DETECTION_THRESHOLD
) -> tuple[PlacementAnalysis, ...]:
    """Analyse placements, decoding each distinct media file exactly once."""

    cache: dict[str, tuple[int, tuple[VisualBoundary, ...], list[float]]] = {}
    results: list[PlacementAnalysis] = []
    previous: Placement | None = None
    for placement in placements:
        if placement.media_path not in cache:
            _, differences = decode_differences(placement.media_path)
            cache[placement.media_path] = (
                len(differences) + 1,
                detect_boundaries(differences, threshold=threshold),
                differences,
            )
        frame_count, boundaries, differences = cache[placement.media_path]
        if placement.source_out_exclusive > frame_count:
            raise ShotUnderstandingError(
                f"{placement.placement_id} asks for frame "
                f"{placement.source_out_exclusive} but {placement.media_path} has "
                f"{frame_count} frames"
            )
        segments, inside = split_into_segments(
            placement.source_in, placement.source_out_exclusive, boundaries
        )
        # A shot continues across a window edge when the two windows are the same media
        # and contiguous, and the measured difference at the join is not a boundary.
        joins = False
        if (
            previous is not None
            and previous.media_path == placement.media_path
            and previous.source_out_exclusive == placement.source_in
            and previous.source_out_exclusive - 1 < len(differences)
        ):
            join_difference = differences[previous.source_out_exclusive - 1]
            joins = join_difference <= threshold
        results.append(PlacementAnalysis(
            placement_id=placement.placement_id,
            source_id=placement.source_id,
            narrative_role=placement.narrative_role,
            source_in=placement.source_in,
            source_out_exclusive=placement.source_out_exclusive,
            timeline_start=placement.timeline_start,
            segments=segments,
            internal_boundaries=inside,
            joins_previous=joins,
        ))
        previous = placement
    return tuple(results)


def timeline_segments(analyses: Sequence[PlacementAnalysis]) -> tuple[VisualSegment, ...]:
    """Merge the per-window segments into the timeline's real visual segments.

    A documented window edge is an approximation of a real cut, not the cut itself. Two
    things follow, and both are visible in the reference corpus:

    * a window edge with no measured difference across it is not a cut at all, so the
      two half-segments are one shot;
    * when a real cut falls one or two frames inside a window, the sliver between the
      documented edge and the real cut is not a shot. It is the same cut seen twice, so
      the sliver merges into the neighbouring segment rather than becoming its own
      one- or two-frame beat.

    Without the second rule a 1-frame sliver is emitted at the window edge and is then
    (correctly) flagged as an accidental fragment, which would blame the picture for an
    imprecision in the documentation.
    """

    flattened: list[VisualSegment] = []
    for analysis in analyses:
        flattened.extend(analysis.segments)

    merged: list[VisualSegment] = []
    index = 0
    while index < len(flattened):
        current = flattened[index]
        nxt = flattened[index + 1] if index + 1 < len(flattened) else None

        if merged and merged[-1].end_frame_exclusive == current.start_frame:
            previous = merged[-1]
            # a sliver immediately before this segment is the documented edge, not a shot
            if current.duration_frames <= EDGE_TOLERANCE_FRAMES:
                merged[-1] = VisualSegment(previous.start_frame,
                                           current.end_frame_exclusive)
                index += 1
                continue
            # a sliver immediately after this segment belongs to it as well
            if (nxt is not None and nxt.duration_frames <= EDGE_TOLERANCE_FRAMES
                    and current.end_frame_exclusive == nxt.start_frame):
                merged[-1] = VisualSegment(previous.start_frame,
                                           nxt.end_frame_exclusive)
                index += 2
                continue

        merged.append(current)
        index += 1
    return tuple(merged)


def truncation_of(placement: Placement) -> bool:
    """Whether a placement stops short of its parent candidate's available range.

    This is the only signal that can catch an edit which cuts an action before its
    result while still looking complete in isolation.
    """

    if placement.candidate_in is None or placement.candidate_out_exclusive is None:
        return False
    if placement.candidate_out_exclusive <= placement.candidate_in:
        raise ShotUnderstandingError("candidate range must be non-empty")
    return (
        placement.source_in > placement.candidate_in
        or placement.source_out_exclusive < placement.candidate_out_exclusive
    )


# --------------------------------------------------------------------------- A2


@dataclass(frozen=True)
class SegmentRef:
    """A reference to one segment, addressable across placements."""

    placement_id: str
    index: int
    role: str
    start_frame: int
    end_frame_exclusive: int
    timeline_start: int

    @property
    def duration_seconds(self) -> float:
        return (self.end_frame_exclusive - self.start_frame) / CFR_FPS


@dataclass(frozen=True)
class SemanticGroup:
    """Segments that are one thing happening."""

    group_id: str
    shape: str
    members: tuple[SegmentRef, ...]
    roles: tuple[str, ...]
    duration_seconds: float
    truncated: bool = False

    @property
    def segment_count(self) -> int:
        return len(self.members)


def build_segment_refs(
    placements: Sequence[Placement], analyses: Sequence[PlacementAnalysis]
) -> tuple[SegmentRef, ...]:
    """Flatten placements into one timeline-ordered segment sequence."""

    by_id = {a.placement_id: a for a in analyses}
    refs: list[SegmentRef] = []
    for placement in placements:
        analysis = by_id[placement.placement_id]
        offset = 0
        for index, segment in enumerate(analysis.segments):
            refs.append(SegmentRef(
                placement_id=placement.placement_id,
                index=index,
                role=placement.narrative_role,
                start_frame=segment.start_frame,
                end_frame_exclusive=segment.end_frame_exclusive,
                timeline_start=placement.timeline_start + offset,
            ))
            offset += segment.duration_frames
    refs.sort(key=lambda r: r.timeline_start)
    return tuple(refs)


def group_segments(
    placements: Sequence[Placement],
    analyses: Sequence[PlacementAnalysis],
    *,
    truncated_ids: Iterable[str] = (),
) -> tuple[SemanticGroup, ...]:
    """Group adjacent segments that form one understandable action unit.

    Deterministic and explainable. Rules, in priority order:

    R1 ``ACTION_RESULT`` — an action placement immediately followed by a placement
       whose role can carry a result.
    R2 ``HERO_UNIT`` — a hero placement, with all of its segments.
    R3 ``SINGLE`` — any other placement is its own unit.

    A group never merges two unrelated beats: R1 requires the action/result role
    relationship, which is exactly the ``Visual Change != Semantic Change`` rule.
    """

    by_id = {a.placement_id: a for a in analyses}
    truncated = set(truncated_ids)
    groups: list[SemanticGroup] = []
    index = 0
    ordered = list(placements)
    counter = 0
    while index < len(ordered):
        placement = ordered[index]
        analysis = by_id[placement.placement_id]
        members: list[SegmentRef] = []
        shape = "SINGLE"
        roles = [placement.narrative_role]
        span = 0

        def add(current: PlacementAnalysis, role: str) -> int:
            added = 0
            for sub, segment in enumerate(current.segments):
                members.append(SegmentRef(
                    placement_id=current.placement_id, index=sub, role=role,
                    start_frame=segment.start_frame,
                    end_frame_exclusive=segment.end_frame_exclusive,
                    timeline_start=0,
                ))
                added += segment.duration_frames
            return added

        if (
            placement.narrative_role in ACTION_ROLES
            and index + 1 < len(ordered)
            and ordered[index + 1].narrative_role in RESULT_ROLES
        ):
            span += add(analysis, placement.narrative_role)
            follower = ordered[index + 1]
            span += add(by_id[follower.placement_id], follower.narrative_role)
            roles.append(follower.narrative_role)
            shape = "ACTION_RESULT"
            index += 2
        elif placement.narrative_role == "hero":
            span += add(analysis, placement.narrative_role)
            shape = "HERO_UNIT"
            index += 1
        else:
            span += add(analysis, placement.narrative_role)
            index += 1

        counter += 1
        group_truncated = any(m.placement_id in truncated for m in members)
        groups.append(SemanticGroup(
            group_id=f"grp{counter:03d}",
            shape=shape,
            members=tuple(members),
            roles=tuple(roles),
            duration_seconds=round(span / CFR_FPS, 4),
            truncated=group_truncated,
        ))
    return tuple(groups)


# --------------------------------------------------------------------------- A3


@dataclass(frozen=True)
class ComprehensionFinding:
    """A warning about reading time. Never a build failure."""

    group_id: str
    actual_seconds: float
    required_seconds: float
    warning: bool
    factor: str | None
    detail: str
    accidental_fragments: int = 0
    micro_fragments: int = 0
    spans_window: bool = False

    @property
    def shortfall_seconds(self) -> float:
        return round(max(0.0, self.required_seconds - self.actual_seconds), 4)


#: Which factor A3 should name for a short group. Ordered by how specific the evidence is.
FACTOR_ACCIDENTAL_FRAGMENT = "accidental_fragment"
FACTOR_ACTION_COMPLETION = "action_completion"
FACTOR_VISUAL_COMPLEXITY = "visual_complexity"
FACTOR_PRODUCT_RECOGNITION = "product_recognition"
FACTOR_CONTEXT = "context"
FACTOR_INFORMATION_DENSITY = "information_density"
FACTOR_RHYTHM = "rhythm"


def _spans_its_window(
    group: SemanticGroup, analyses: Sequence[PlacementAnalysis]
) -> bool:
    """True when the group is exactly one placement's full window.

    A deliberate insert covers its window. A fragment carved out of a window by an
    internal cut does not, and that difference is what separates a valid 0.7s beat from
    a 0.4s leftover.
    """

    if len({m.placement_id for m in group.members}) != 1:
        return False
    placement_id = group.members[0].placement_id
    analysis = next((a for a in analyses if a.placement_id == placement_id), None)
    if analysis is None or len(group.members) != len(analysis.segments):
        return False
    return (
        group.members[0].start_frame == analysis.source_in
        and group.members[-1].end_frame_exclusive == analysis.source_out_exclusive
    )


def required_seconds(
    group: SemanticGroup,
    *,
    product_established: bool,
    spans_window: bool = False,
) -> tuple[float, str | None]:
    """Estimate how long this group needs, and name the factor that dominates."""

    base = max(ROLE_BASE_SECONDS.get(role, 1.0) for role in group.roles)
    requirement = base
    dominant: str | None = None

    extra = group.segment_count - 1
    if extra > 0:
        requirement *= 1.0 + COMPLEXITY_PER_EXTRA_SEGMENT * extra
        dominant = FACTOR_VISUAL_COMPLEXITY

    if any(role in {"hook", "proof"} for role in group.roles):
        requirement *= 1.15
        dominant = FACTOR_PRODUCT_RECOGNITION

    deliberate_insert = (
        spans_window
        and group.segment_count == 1
        and not any(role in ACTION_ROLES for role in group.roles)
        and product_established
    )

    if product_established:
        requirement -= CONTEXT_CREDIT_SECONDS
    if deliberate_insert:
        requirement -= SIMPLE_INSERT_CREDIT_SECONDS

    requirement = max(requirement, 0.0)
    if deliberate_insert:
        requirement = max(requirement, MIN_SIMPLE_INSERT_SECONDS)
    return round(requirement, 4), dominant


def assess_comprehension(
    groups: Sequence[SemanticGroup],
    analyses: Sequence[PlacementAnalysis],
    *,
    establishing_roles_seen_before: int = 0,
) -> tuple[ComprehensionFinding, ...]:
    """Compare what each group needs with what it gets, and name the short factor.

    Deliberately a warning heuristic. A short group can be accepted, and the finding
    reports *which* factor was short rather than a bare number, so a human can judge it.
    """

    findings: list[ComprehensionFinding] = []
    established = establishing_roles_seen_before > 0
    for group in groups:
        spans = _spans_its_window(group, analyses)
        requirement, dominant = required_seconds(
            group, product_established=established, spans_window=spans
        )
        actual = group.duration_seconds
        accidental = sum(
            1 for m in group.members
            if (m.end_frame_exclusive - m.start_frame) <= ACCIDENTAL_FRAGMENT_FRAMES
        )
        micro = sum(
            1 for m in group.members
            if (m.end_frame_exclusive - m.start_frame) / CFR_FPS < MICRO_FRAGMENT_SECONDS
        )

        factor: str | None = None
        warning = False
        detail = ""

        if accidental:
            warning = True
            factor = FACTOR_ACCIDENTAL_FRAGMENT
            detail = (f"{accidental} segment(s) of {ACCIDENTAL_FRAGMENT_FRAMES} frames or "
                      f"fewer cannot be an intentional beat")
        elif group.truncated:
            warning = True
            factor = FACTOR_ACTION_COMPLETION
            detail = ("the placement stops short of the candidate's available range, so "
                      "the action may not reach its result")
        elif actual < requirement:
            warning = True
            if not spans:
                factor = FACTOR_CONTEXT
                detail = ("a fragment of a window rather than a deliberate beat: it "
                          f"arrives without its own context and gets {actual:.2f}s")
            else:
                factor = dominant or FACTOR_INFORMATION_DENSITY
                detail = (f"needs about {requirement:.2f}s for role(s) "
                          f"{'/'.join(group.roles)} but gets {actual:.2f}s")
            if micro:
                detail += f"; {micro} segment(s) under {MICRO_FRAGMENT_SECONDS}s"

        findings.append(ComprehensionFinding(
            group_id=group.group_id,
            actual_seconds=actual,
            required_seconds=requirement,
            warning=warning,
            factor=factor,
            detail=detail,
            accidental_fragments=accidental,
            micro_fragments=micro,
            spans_window=spans,
        ))

        if any(role in ESTABLISHING_ROLES for role in group.roles):
            established = True
    return tuple(findings)


# --------------------------------------------------------------------- reporting


def summarise(
    analyses: Sequence[PlacementAnalysis],
    groups: Sequence[SemanticGroup],
    findings: Sequence[ComprehensionFinding],
) -> dict[str, object]:
    """A compact, machine-readable summary of one shot-understanding pass."""

    segments = [s for a in analyses for s in a.segments]
    merged = timeline_segments(analyses)
    placements_with_cuts = [a.placement_id for a in analyses if a.contains_internal_cuts]
    return {
        "placements_analysed": len(analyses),
        "visual_segments": len(segments),
        "visual_segments_in_timeline": len(merged),
        "window_edges_that_continue_a_shot": sum(1 for a in analyses if a.joins_previous),
        "boundaries_detected": sum(len(a.internal_boundaries) for a in analyses),
        "placements_containing_internal_cuts": placements_with_cuts,
        "placements_containing_internal_cuts_count": len(placements_with_cuts),
        "micro_fragments_under_0_75s": sum(1 for s in segments if s.is_micro_fragment),
        "micro_fragments_in_timeline": sum(1 for s in merged if s.is_micro_fragment),
        "accidental_fragments_under_3_frames": sum(
            1 for s in segments if s.is_accidental_fragment
        ),
        "accidental_fragment_durations": [
            s.duration_frames for s in segments if s.is_accidental_fragment
        ],
        "semantic_groups": len(groups),
        "group_shapes": {
            shape: sum(1 for g in groups if g.shape == shape)
            for shape in sorted({g.shape for g in groups})
        },
        "comprehension_warnings": sum(1 for f in findings if f.warning),
        "warning_factors": {
            factor: sum(1 for f in findings if f.factor == factor)
            for factor in sorted({f.factor for f in findings if f.factor})
        },
    }
