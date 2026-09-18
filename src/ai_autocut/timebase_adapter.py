"""The timebase invariant, enforced at the production boundary.

SOURCE coordinate  = a PTS timestamp in seconds
TIMELINE coordinate = a CFR frame index; frame N occupies [N/fps, (N+1)/fps)

This is not a helper that one stage happens to call. It is a **cross-cutting production
invariant**: every operation that converts a source range into a timeline range, or
extracts frames from a source, must pass through this module. `timebase.py` holds the
mechanism; this module holds the *rule* and the evidence that the rule was followed.

The failure this prevents
-------------------------
The Second SKU repair selected frames with ``trim=start_frame=A:end_frame=B`` against
raw variable-frame-rate sources, then forced ``-r 30``. A source frame index is not
30 x its time, so the requested interval did not contain the frames it was assumed to
contain: the build produced **502 frames instead of 487**, and on a re-run **66 frames
where 67 were expected** for the same range.

What is forbidden
-----------------
``source_frame_index / assumed_fps`` as an execution coordinate for a source that may
be variable frame rate. A frame index may still be *recorded* as human evidence — but
it must be resolved through :meth:`TimebaseAdapter.resolve_from_source_index`, which
looks the index up in the **measured** PTS table rather than dividing by an assumed
frame rate.

Bypass detection
----------------
Every authorised resolution and execution is appended to a ledger. Call
:meth:`TimebaseAdapter.assert_range_coverage` with the units a stage was supposed to
process: if any unit has no ledger entry, something extracted frames without going
through this boundary, and the call raises. That is what makes "the production path
actually used the timebase" a testable property rather than a claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .timebase import (
    DEFAULT_FPS,
    SourceTiming,
    TimebaseError,
    count_frames,
    extract_timeline_frames,
)

#: The one coordinate system a production extraction may use.
COORDINATE_SYSTEM = "SOURCE_PTS_SECONDS -> CFR_TIMELINE_FRAMES"

#: ffmpeg filters that select by **source frame index**. Legal inside an already-CFR
#: intermediate; never legal as the coordinate that addresses a raw source.
FORBIDDEN_SOURCE_SELECTORS = (
    "trim=start_frame",
    "trim=end_frame",
    "select=",
)


class TimebaseAdapterError(ValueError):
    """Raised when an execution would use an unsafe source coordinate."""


def _non_empty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TimebaseAdapterError(f"{label} must be a non-empty string")
    return value


def assert_timestamp_safe(command: Sequence[str]) -> None:
    """Refuse an extraction command that addresses a source by frame index.

    This is the guard for the exact Second SKU defect. It is deliberately a separate,
    callable function so it can be applied to *any* command a job builds, including one
    assembled outside this adapter.
    """

    if not isinstance(command, (list, tuple)) or not command:
        raise TimebaseAdapterError("command must be a non-empty sequence")
    joined = " ".join(str(part) for part in command)
    for selector in FORBIDDEN_SOURCE_SELECTORS:
        if selector in joined:
            raise TimebaseAdapterError(
                f"source extraction must not select by frame index ({selector!r}); a "
                "source frame index is not 30 x its time for a variable frame rate "
                "source. Address the source by PTS seconds and let the -frames:v cap "
                "guarantee the output count."
            )


@dataclass(frozen=True)
class SourceRangeResolution:
    """A source range expressed in the one coordinate system production may use."""

    unit_id: str
    source: str
    t_in_seconds: float
    frames: int
    fps: int
    variable_frame_rate: bool
    source_frame_index: int | None
    resolved_from: str

    def __post_init__(self) -> None:
        _non_empty(self.unit_id, "unit_id")
        _non_empty(self.source, "source")
        _non_empty(self.resolved_from, "resolved_from")
        if self.t_in_seconds < 0:
            raise TimebaseAdapterError("t_in_seconds cannot be negative")
        if not isinstance(self.frames, int) or isinstance(self.frames, bool) or self.frames <= 0:
            raise TimebaseAdapterError("frames must be a positive integer")

    @property
    def duration_seconds(self) -> float:
        return round(self.frames / self.fps, 6)

    def as_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "source": self.source,
            "coordinate_system": COORDINATE_SYSTEM,
            "t_in_seconds": self.t_in_seconds,
            "duration_seconds": self.duration_seconds,
            "frames": self.frames,
            "fps": self.fps,
            "variable_frame_rate": self.variable_frame_rate,
            "source_frame_index": self.source_frame_index,
            "resolved_from": self.resolved_from,
        }


@dataclass(frozen=True)
class SourceRangeExecution:
    """Evidence that one range really was extracted through this boundary."""

    unit_id: str
    source: str
    t_in_seconds: float
    frames_requested: int
    frames_produced: int
    out_path: str

    @property
    def coordinate_system(self) -> str:
        return COORDINATE_SYSTEM

    def as_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "source": self.source,
            "coordinate_system": COORDINATE_SYSTEM,
            "t_in_seconds": self.t_in_seconds,
            "frames_requested": self.frames_requested,
            "frames_produced": self.frames_produced,
            "out_path": self.out_path,
        }


class TimebaseAdapter:
    """The single authorised path from a source range to timeline frames."""

    def __init__(self, fps: int = DEFAULT_FPS) -> None:
        if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
            raise TimebaseAdapterError("fps must be a positive integer")
        self.fps = fps
        self._timing_cache: dict[str, SourceTiming] = {}
        self._ledger: list[SourceRangeExecution] = []

    # ---- measurement -----------------------------------------------------------

    def timing(self, source: str) -> SourceTiming:
        """Measured timing for a source. VFR is detected, never assumed away."""

        _non_empty(source, "source")
        if source not in self._timing_cache:
            try:
                self._timing_cache[source] = SourceTiming(source, self.fps)
            except TimebaseError as exc:
                raise TimebaseAdapterError(str(exc)) from exc
        return self._timing_cache[source]

    def profile(self, source: str) -> dict:
        """A short factual description of a source's timing, for the job record."""

        described = dict(self.timing(source).describe())
        described["source"] = source
        described["coordinate_system"] = COORDINATE_SYSTEM
        return described

    # ---- resolution ------------------------------------------------------------

    def resolve_from_seconds(
        self, *, unit_id: str, source: str, t_in_seconds: float, frames: int
    ) -> SourceRangeResolution:
        """Resolve an explicitly stated source timestamp. The preferred entry point."""

        timing = self.timing(source)
        return SourceRangeResolution(
            unit_id=unit_id,
            source=source,
            t_in_seconds=round(float(t_in_seconds), 6),
            frames=frames,
            fps=self.fps,
            variable_frame_rate=timing.is_variable_frame_rate,
            source_frame_index=None,
            resolved_from="EXPLICIT_SOURCE_SECONDS",
        )

    def resolve_from_source_index(
        self, *, unit_id: str, source: str, source_frame_index: int, frames: int
    ) -> SourceRangeResolution:
        """Resolve a source frame index **through the measured PTS table**.

        A frame index is often how a human records a chosen range, and it may stay in
        the record. It is resolved here by looking the index up in the measured
        timestamps — never by dividing it by an assumed frame rate. For a variable
        frame rate source those two answers differ, and the difference is the bug this
        module exists to prevent.
        """

        if not isinstance(source_frame_index, int) or isinstance(source_frame_index, bool):
            raise TimebaseAdapterError("source_frame_index must be an integer")
        timing = self.timing(source)
        try:
            t_in = timing.timestamp_of(source_frame_index)
        except TimebaseError as exc:
            raise TimebaseAdapterError(str(exc)) from exc
        return SourceRangeResolution(
            unit_id=unit_id,
            source=source,
            t_in_seconds=round(t_in, 6),
            frames=frames,
            fps=self.fps,
            variable_frame_rate=timing.is_variable_frame_rate,
            source_frame_index=source_frame_index,
            resolved_from="MEASURED_PTS_LOOKUP",
        )

    def assert_safe(self, resolution: SourceRangeResolution) -> None:
        """Refuse a resolution whose range runs past the measured end of its source."""

        timing = self.timing(resolution.source)
        end = resolution.t_in_seconds + resolution.duration_seconds
        if end > timing.timestamps[-1] + (1.0 / self.fps):
            raise TimebaseAdapterError(
                f"unit {resolution.unit_id!r} ends at {end:.6f}s but "
                f"{resolution.source} ends at {timing.timestamps[-1]:.6f}s"
            )

    # ---- placement coordinates -------------------------------------------------

    def measured_duration_seconds(
        self, *, source: str, source_in: int, source_out_exclusive: int
    ) -> float:
        """The real duration of a decoded frame range, from the measured PTS table.

        This is the point of the invariant: ``(out - in) / fps`` is only correct for a
        constant frame rate source. For a variable frame rate source the decoded
        range's real duration comes from the timestamps, and the two answers differ.
        """

        timing = self.timing(source)
        if source_out_exclusive <= source_in:
            raise TimebaseAdapterError("a source range must be non-empty")
        if source_in < 0 or source_out_exclusive > timing.frame_count:
            raise TimebaseAdapterError(
                f"range [{source_in}, {source_out_exclusive}) is outside {source} "
                f"({timing.frame_count} decoded frames)"
            )
        start = timing.timestamp_of(source_in)
        if source_out_exclusive < timing.frame_count:
            end = timing.timestamp_of(source_out_exclusive)
        else:
            step = timing.timestamps[-1] - timing.timestamps[-2]
            end = timing.timestamps[-1] + step
        return round(end - start, 6)

    def assert_placement_timing(
        self,
        *,
        placement_id: str,
        source: str,
        source_in: int,
        source_out_exclusive: int,
        t_in_seconds: float | None,
        tolerance_frames: float = 1.0,
    ) -> dict[str, object]:
        """Verify a placement's coordinates against the measured PTS table.

        A placement records a decoded frame range, which is legitimate for
        segmentation. What is not legitimate is treating that range's *time* as
        ``frames / fps``: on a variable frame rate source a decoded range of N frames is
        not ``N / 30`` seconds long.

        So every production placement must also state ``t_in_seconds`` — the measured
        source timestamp of ``source_in``. This verifies the two agree. When they do not,
        the coordinates were derived from an assumed constant frame rate, and the run
        stops instead of propagating a wrong source coordinate.
        """

        timing = self.timing(source)
        if source_out_exclusive <= source_in:
            raise TimebaseAdapterError(
                f"placement {placement_id!r} must cover a non-empty range"
            )
        if source_in < 0 or source_out_exclusive > timing.frame_count:
            raise TimebaseAdapterError(
                f"placement {placement_id!r} asks for [{source_in}, "
                f"{source_out_exclusive}) but {source} has {timing.frame_count} "
                "decoded frames"
            )
        measured_start = round(timing.timestamp_of(source_in), 6)
        if t_in_seconds is None:
            raise TimebaseAdapterError(
                f"placement {placement_id!r} states no t_in_seconds. A decoded frame "
                "index is not a source time for a variable frame rate source, so the "
                "measured timestamp must be stated explicitly."
            )
        frame_tolerance = tolerance_frames / self.fps
        if abs(float(t_in_seconds) - measured_start) > frame_tolerance:
            raise TimebaseAdapterError(
                f"placement {placement_id!r} declares t_in_seconds="
                f"{float(t_in_seconds):.6f} but frame {source_in} of {source} is at "
                f"{measured_start:.6f}s. The declared coordinate was derived from an "
                "assumed constant frame rate, not from the source's measured PTS."
            )
        assumed = round((source_out_exclusive - source_in) / self.fps, 6)
        measured = self.measured_duration_seconds(
            source=source,
            source_in=source_in,
            source_out_exclusive=source_out_exclusive,
        )
        return {
            "placement_id": placement_id,
            "source": source,
            "coordinate_system": COORDINATE_SYSTEM,
            "source_frame_range": [source_in, source_out_exclusive],
            "measured_t_in_seconds": measured_start,
            "measured_duration_seconds": measured,
            "assumed_cfr_duration_seconds": assumed,
            "duration_delta_seconds": round(measured - assumed, 6),
            "variable_frame_rate": timing.is_variable_frame_rate,
            "duration_coordinate": "MEASURED_PTS",
        }

    def resolve_placement_window(
        self,
        *,
        placement_id: str,
        source: str,
        t_in_seconds: float,
        duration_seconds: float,
        analysis_fps: int | None = None,
    ) -> dict[str, object]:
        """Map a **measured** source window onto the CFR ANALYSIS grid.

        The three domains are distinct, and conflating the middle two is the defect this
        fixes:

            SOURCE DOMAIN   = measured PTS timestamp
            ANALYSIS DOMAIN = explicit CFR analysis grid (the engine decodes at a forced
                              ``fps``, so analysis frame N is the content at N/fps)
            TIMELINE DOMAIN = CFR timeline grid

        For a variable frame rate source a raw decoded source ordinal is **not** an
        analysis frame. A source whose first second runs at 10 fps and whose second runs
        at 30 fps has its 1.0 s content at raw index 10, but at analysis frame 30. Feeding
        the raw ordinal into the forced-CFR analysis stream would analyse the content at
        0.333 s instead of 1.0 s.

        So the returned ``source_in`` / ``source_out_exclusive`` are **analysis-grid**
        coordinates derived from the measured timestamp and the declared analysis rate.
        The raw decoded ordinals are returned alongside, for provenance only, and are
        never the coordinates the analysis runs on.
        """

        timing = self.timing(source)
        fps = int(analysis_fps or self.fps)
        _non_empty(placement_id, "placement_id")
        if duration_seconds is None or float(duration_seconds) <= 0:
            raise TimebaseAdapterError(
                f"placement {placement_id!r} must state a positive duration"
            )
        t_in = float(t_in_seconds)
        if t_in < 0:
            raise TimebaseAdapterError(f"placement {placement_id!r} starts before zero")
        t_out = t_in + float(duration_seconds)
        frame_span = 1.0 / fps
        if t_out > timing.timestamps[-1] + frame_span + 1e-6:
            raise TimebaseAdapterError(
                f"placement {placement_id!r} ends at {t_out:.6f}s but {source} ends at "
                f"{timing.timestamps[-1]:.6f}s"
            )

        # ---- measured-PTS validation (kept) -----------------------------------
        epsilon = 1e-6
        raw_in = next(
            (i for i, ts in enumerate(timing.timestamps) if ts >= t_in - epsilon), None
        )
        if raw_in is None:
            raise TimebaseAdapterError(
                f"placement {placement_id!r} starts at {t_in:.6f}s, past the measured "
                f"end of {source}"
            )
        measured_t_in = round(timing.timestamp_of(raw_in), 6)
        if abs(measured_t_in - t_in) > frame_span:
            raise TimebaseAdapterError(
                f"placement {placement_id!r} declares t_in_seconds={t_in:.6f} but the "
                f"nearest measured frame is at {measured_t_in:.6f}s"
            )
        raw_out = next(
            (
                i
                for i, ts in enumerate(timing.timestamps)
                if ts >= t_out - epsilon and i > raw_in
            ),
            None,
        )
        if raw_out is None:
            if t_out <= timing.timestamps[-1] + frame_span + 1e-6:
                raw_out = len(timing.timestamps)
            else:
                raise TimebaseAdapterError(
                    f"placement {placement_id!r} window [{t_in:.6f}, {t_out:.6f}) does "
                    f"not contain a decodable frame range in {source}"
                )

        # ---- ANALYSIS DOMAIN: the CFR grid, derived from measured time --------
        analysis_start = int(round(t_in * fps))
        analysis_frames = int(round(float(duration_seconds) * fps))
        if analysis_frames <= 0:
            raise TimebaseAdapterError(
                f"placement {placement_id!r} resolves to an empty analysis window"
            )

        measured_out = (
            round(timing.timestamp_of(raw_out), 6)
            if raw_out < timing.frame_count
            else round(timing.timestamps[-1] + (timing.timestamps[-1] - timing.timestamps[-2]), 6)
        )
        measured_duration = round(measured_out - measured_t_in, 6)
        decoded_frames = raw_out - raw_in
        assumed_duration = round(decoded_frames / fps, 6)
        return {
            "placement_id": placement_id,
            "source": source,
            "coordinate_system": COORDINATE_SYSTEM,
            "analysis_grid": "CFR_DERIVED_FROM_MEASURED_PTS",
            "analysis_fps": fps,
            # Authoritative: coordinates in the analysis (CFR) domain.
            "source_in": analysis_start,
            "source_out_exclusive": analysis_start + analysis_frames,
            "analysis_start_frame": analysis_start,
            "analysis_frames_cfr": analysis_frames,
            # Provenance only: positions in the raw decoded source domain. Never used
            # as analysis coordinates.
            "raw_source_in": raw_in,
            "raw_source_out_exclusive": raw_out,
            "raw_decoded_frames": decoded_frames,
            "measured_t_in_seconds": measured_t_in,
            "measured_t_out_seconds": measured_out,
            "measured_duration_seconds": measured_duration,
            "assumed_cfr_duration_seconds": assumed_duration,
            "duration_delta_seconds": round(measured_duration - assumed_duration, 6),
            "variable_frame_rate": timing.is_variable_frame_rate,
            "raw_index_differs_from_analysis": raw_in != analysis_start,
        }

    # ---- execution -------------------------------------------------------------

    def execute(
        self, resolution: SourceRangeResolution, out_path: str
    ) -> SourceRangeExecution:
        """Extract exactly the requested frames, and record that this path was used."""

        if not isinstance(resolution, SourceRangeResolution):
            raise TimebaseAdapterError("resolution must be a SourceRangeResolution")
        _non_empty(out_path, "out_path")
        self.assert_safe(resolution)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            produced = extract_timeline_frames(
                resolution.source,
                t_in=resolution.t_in_seconds,
                frames=resolution.frames,
                out_path=out_path,
                fps=self.fps,
            )
        except TimebaseError as exc:
            raise TimebaseAdapterError(str(exc)) from exc
        execution = SourceRangeExecution(
            unit_id=resolution.unit_id,
            source=resolution.source,
            t_in_seconds=resolution.t_in_seconds,
            frames_requested=resolution.frames,
            frames_produced=int(produced["frames"]),
            out_path=out_path,
        )
        self._ledger.append(execution)
        return execution

    def verify_frames(self, execution: SourceRangeExecution) -> None:
        """Re-read the produced file and confirm the count actually landed."""

        produced = count_frames(execution.out_path)
        if produced != execution.frames_requested:
            raise TimebaseAdapterError(
                f"unit {execution.unit_id!r} requested {execution.frames_requested} "
                f"frames but the file holds {produced}"
            )

    # ---- bypass detection ------------------------------------------------------

    @property
    def ledger(self) -> tuple[SourceRangeExecution, ...]:
        return tuple(self._ledger)

    def assert_range_coverage(self, unit_ids: Iterable[str]) -> None:
        """Fail if any expected unit has no ledger entry.

        This is how a bypass is caught: a future refactor that extracts frames without
        going through :meth:`execute` leaves the expected unit unrecorded, and this
        raises instead of the gap passing unnoticed.
        """

        expected = {str(unit) for unit in unit_ids}
        executed = {entry.unit_id for entry in self._ledger}
        missing = sorted(expected - executed)
        if missing:
            raise TimebaseAdapterError(
                "source-range execution bypassed the timebase adapter for: "
                + ", ".join(missing)
                + ". Every extraction must go through TimebaseAdapter.execute so the "
                "source coordinate is a measured timestamp."
            )

    def ledger_document(self) -> dict[str, object]:
        return {
            "schema_version": "timebase_ledger.v1",
            "coordinate_system": COORDINATE_SYSTEM,
            "fps": self.fps,
            "executions": [entry.as_dict() for entry in self._ledger],
        }


__all__ = [
    "COORDINATE_SYSTEM",
    "FORBIDDEN_SOURCE_SELECTORS",
    "SourceRangeExecution",
    "SourceRangeResolution",
    "TimebaseAdapter",
    "TimebaseAdapterError",
    "assert_timestamp_safe",
]
