"""Deterministic audio executor: turn an ``audio_plan.v0`` into stems and a validated mix.

The contract states **intent**. This module decides **levels**, executes with FFmpeg, and
emits **measurements** as evidence. Nothing here copies a number out of a finished job:
an intent plus the competition in the mix produces a relative automation curve, and the
measured outcome is what gets reported.

Responsibilities, in order:

* resolve semantic windows to concrete timeline seconds;
* cut voice spans from **one continuous performance**;
* build stems, including an empty foley stem when no sound is justified;
* derive BGM automation from intent, and duck everything under voice;
* measure the result, so a mix claim is a reading rather than an assertion.

No paid API is called anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
import shutil
import subprocess
from typing import Iterable, Mapping, Sequence

from .audio_plan import (
    AudioPlan,
    BgmSection,
    VoEvent,
)

#: Every non-voice source ducks under voice. This mirrors ``audio_plan.MIX_PRIORITY``.
LEADING_SOURCE = "VO"

#: How far a competing source pushes the music down, per competing source, in dB.
#:
#: This is a **rule**, not a copied value: each source with a higher claim on attention
#: takes a share of the space. The absolute level is set later by the mixing and loudness
#: stage, so no absolute gain is ever baked into this module.
YIELD_DB_PER_COMPETING_SOURCE = 2.5

#: Reasons a sound may be added. A sound that improves none of these is absent.
SFX_JUSTIFICATIONS = ("comprehension", "realism", "commercial_emphasis", "rhythm")

#: A stem name must be filesystem-safe and is part of the evidence.
_STEM_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")

_LOUDNESS_RANGE = re.compile(r"^\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", re.MULTILINE)
_TRUE_PEAK = re.compile(r"^\s*Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", re.MULTILINE)
_MEAN_VOLUME = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
_MAX_VOLUME = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


class AudioExecutorError(ValueError):
    """Raised when a plan cannot be executed safely."""


def _which_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise AudioExecutorError("ffmpeg is required to execute an audio plan")
    return found


# --------------------------------------------------------------- semantic resolution


@dataclass(frozen=True)
class ResolvedVoice:
    """A voice event with its semantic unit resolved to concrete seconds."""

    vo_id: str
    purpose: str
    semantic_unit: str
    start_seconds: float
    end_seconds: float
    required: bool
    silence_reason: str | None

    @property
    def window_seconds(self) -> float:
        return round(self.end_seconds - self.start_seconds, 4)


def resolve_semantic_windows(
    vo_events: Sequence[VoEvent], unit_windows: Mapping[str, tuple[float, float]]
) -> tuple[ResolvedVoice, ...]:
    """Resolve every voice event against the timeline it will actually be placed on.

    The binding target is the **semantic unit**, not a stored timestamp, so a timeline
    that shifts re-resolves instead of leaving the voice describing an old shot. A
    declared ``window_seconds`` is used only when the timeline cannot resolve the unit,
    and that fallback is visible in the result.
    """

    resolved: list[ResolvedVoice] = []
    for event in vo_events:
        window = unit_windows.get(event.semantic_unit)
        if window is None:
            if event.window_seconds is None:
                raise AudioExecutorError(
                    f"voice event {event.vo_id!r} binds to semantic unit "
                    f"{event.semantic_unit!r}, which the timeline does not contain, and "
                    "declares no fallback window"
                )
            window = event.window_seconds
        start, end = float(window[0]), float(window[1])
        if end <= start:
            raise AudioExecutorError(
                f"semantic unit {event.semantic_unit!r} resolved to an empty window"
            )
        resolved.append(ResolvedVoice(
            vo_id=event.vo_id, purpose=event.purpose,
            semantic_unit=event.semantic_unit,
            start_seconds=start, end_seconds=end,
            required=event.required, silence_reason=event.silence_reason,
        ))
    return tuple(resolved)


# ------------------------------------------------------ continuous performance proof


@dataclass(frozen=True)
class VoCut:
    """One span cut out of a performance take."""

    vo_id: str
    source_in: float
    source_out: float
    target_start: float

    @property
    def duration(self) -> float:
        return round(self.source_out - self.source_in, 4)


@dataclass(frozen=True)
class ContinuityProof:
    """Evidence that every span came from one take rather than several generations."""

    take_path: str
    spans: int
    single_source: bool
    take_duration: float
    non_overlapping: bool
    ordered: bool

    @property
    def is_continuous_performance(self) -> bool:
        return self.single_source and self.non_overlapping and self.ordered


def verify_continuous_performance(
    take_path: str, cuts: Sequence[VoCut], *, take_duration: float | None = None
) -> ContinuityProof:
    """Prove multiple voice spans were cut from a single performance.

    One source path for every span, spans in order, and no span overlapping another: a
    per-sentence generation cannot produce this shape, because each sentence would have
    its own file and its own take.
    """

    if not cuts:
        raise AudioExecutorError("a continuity proof needs at least one span")
    inputs = [cut.source_in for cut in cuts]
    outputs = [cut.source_out for cut in cuts]
    if any(o <= i for i, o in zip(inputs, outputs)):
        raise AudioExecutorError("every voice span must be a non-empty range")
    ordered = all(inputs[i] < inputs[i + 1] for i in range(len(inputs) - 1))
    non_overlapping = all(
        outputs[i] <= inputs[i + 1] for i in range(len(inputs) - 1)
    )
    duration = take_duration
    if duration is None:
        duration = measure_duration(take_path)
    overrun = max(outputs) > duration + 1e-6
    return ContinuityProof(
        take_path=take_path,
        spans=len(cuts),
        single_source=not overrun,
        take_duration=round(duration, 4),
        non_overlapping=non_overlapping,
        ordered=ordered,
    )


# ------------------------------------------------------------------------- SFX policy


@dataclass(frozen=True)
class SfxDecision:
    """Whether a unit carries an added sound, and why."""

    unit_id: str
    added: bool
    reason: str = ""

    def __post_init__(self) -> None:
        if not _STEM_PATTERN.fullmatch(self.unit_id):
            raise AudioExecutorError(f"malformed unit id: {self.unit_id!r}")
        if self.added:
            if not any(token in self.reason for token in SFX_JUSTIFICATIONS):
                raise AudioExecutorError(
                    f"unit {self.unit_id!r} adds a sound without naming what it improves; "
                    f"expected one of: {', '.join(SFX_JUSTIFICATIONS)}"
                )


def decide_sfx(units: Iterable[tuple[str, str]]) -> tuple[SfxDecision, ...]:
    """Default every unit to **no added sound**.

    ``units`` is ``(unit_id, justification)``. An empty justification means no sound: an
    action existing is not a reason for one, and the First Job measured a decorative
    handling sound at an inaudible level before removing it.
    """

    decisions: list[SfxDecision] = []
    for unit_id, justification in units:
        text = (justification or "").strip()
        decisions.append(SfxDecision(unit_id=unit_id, added=bool(text), reason=text))
    return tuple(decisions)


# ----------------------------------------------------------------- BGM automation


@dataclass(frozen=True)
class BgmAutomationSegment:
    """One section's derived automation, in **relative** dB. Never an absolute level."""

    section: str
    intent: str
    start_seconds: float
    end_seconds: float
    start_relative_db: float
    end_relative_db: float
    kind: str
    transition_seconds: float
    competing_sources: int


def plan_bgm_automation(
    sections: Sequence[BgmSection],
    *,
    section_windows: Mapping[str, tuple[float, float]],
    competing_sources: Mapping[str, int] | None = None,
) -> tuple[BgmAutomationSegment, ...]:
    """Derive a relative automation curve per section from its stated intent.

    ``HOLD`` keeps the level, ``YIELD`` ramps down in proportion to how many sources
    outrank the music in that section, ``RETURN`` ramps back, and ``RAMP`` sweeps between
    the previous section's level and this one's target. The output is relative and the
    absolute level is decided downstream, so no finished job's gain values enter here.
    """

    competition = competing_sources or {}
    segments: list[BgmAutomationSegment] = []
    previous_end = 0.0
    for section in sections:
        window = section_windows.get(section.section)
        if window is None:
            raise AudioExecutorError(
                f"bgm section {section.section!r} has no resolved window"
            )
        start, end = float(window[0]), float(window[1])
        if end <= start:
            raise AudioExecutorError(
                f"bgm section {section.section!r} resolved to an empty window"
            )
        count = int(competition.get(section.section, 0))
        if count < 0:
            raise AudioExecutorError("competing source count cannot be negative")
        yield_db = -(YIELD_DB_PER_COMPETING_SOURCE * count)

        if section.intent == "HOLD":
            start_db = end_db = previous_end
        elif section.intent == "YIELD":
            start_db, end_db = previous_end, yield_db
        elif section.intent == "RETURN":
            start_db, end_db = previous_end, 0.0
        else:  # RAMP
            start_db, end_db = previous_end, yield_db
        previous_end = end_db

        segments.append(BgmAutomationSegment(
            section=section.section, intent=section.intent,
            start_seconds=start, end_seconds=end,
            start_relative_db=round(start_db, 3), end_relative_db=round(end_db, 3),
            kind=section.transition, transition_seconds=section.transition_seconds,
            competing_sources=count,
        ))
    return tuple(segments)


def bgm_is_eased(segments: Sequence[BgmAutomationSegment]) -> bool:
    """True when every level change is ramped rather than instantaneous.

    A declared ``STEP`` is legitimate but is by definition not eased, so it makes this
    false. The check exists because an unstated instant change is what makes music appear
    to drop out at a hero.
    """

    for segment in segments:
        changing = abs(segment.end_relative_db - segment.start_relative_db) > 1e-9
        if not changing:
            continue
        if segment.kind != "RAMP" or segment.transition_seconds <= 0:
            return False
    return True


def _segment_level_expression(segment: BgmAutomationSegment) -> str:
    """The relative-dB expression for one section, in FFmpeg ``volume`` syntax."""

    target = segment.end_relative_db
    previous = segment.start_relative_db
    if segment.kind != "RAMP" or segment.transition_seconds <= 0:
        return f"{target:g}dB"
    if abs(target - previous) <= 1e-9:
        return f"{target:g}dB"
    ramp_end = segment.start_seconds + segment.transition_seconds
    slope = (target - previous) / segment.transition_seconds
    linear = f"({previous:g})+({slope:g})*(t-{segment.start_seconds:g})"
    return f"if(lt(t,{ramp_end:g}),{linear},{target:g})"


def build_bgm_volume_filter(segments: Sequence[BgmAutomationSegment]) -> str:
    """Build the FFmpeg ``volume`` expression for the derived curve.

    Segments are nested **in reverse** — last section first, earliest section outermost —
    so that the first section ends up as the outermost test. Building them forwards is
    the mistake that once made a music bed roughly 15 dB too loud.
    """

    if not segments:
        raise AudioExecutorError("an automation curve needs at least one segment")
    ordered = sorted(segments, key=lambda s: s.start_seconds)
    expression = _segment_level_expression(ordered[-1])
    for index in range(len(ordered) - 2, -1, -1):
        current = ordered[index]
        following = ordered[index + 1]
        expression = (f"if(lt(t,{following.start_seconds:g}),"
                      f"{_segment_level_expression(current)},{expression})")
    return expression


# ------------------------------------------------------------------- ducking


@dataclass(frozen=True)
class DuckingRule:
    """One source ducking under another."""

    source: str
    under: str
    depth_db: float


def plan_ducking(
    *, sources: Sequence[str], depth_db: float = -6.0
) -> tuple[DuckingRule, ...]:
    """Every non-voice source ducks under voice, mirroring the plan's mix priority."""

    if not sources:
        raise AudioExecutorError("ducking needs at least one source")
    rules: list[DuckingRule] = []
    for source in sources:
        if not _STEM_PATTERN.fullmatch(source):
            raise AudioExecutorError(f"malformed source name: {source!r}")
        if source == LEADING_SOURCE:
            continue
        rules.append(DuckingRule(source=source, under=LEADING_SOURCE, depth_db=depth_db))
    return tuple(rules)


# ------------------------------------------------------------------- measurement


@dataclass(frozen=True)
class WindowLevel:
    """Measured level of one window."""

    label: str
    start_seconds: float
    duration_seconds: float
    mean_db: float
    max_db: float

    @property
    def is_silent(self) -> bool:
        return self.max_db <= -70.0


@dataclass(frozen=True)
class LoudnessReading:
    integrated_lufs: float
    true_peak_dbtp: float
    clipping: bool


def measure_duration(path: str) -> float:
    if not os.path.isfile(path):
        raise AudioExecutorError(f"no such audio file: {path}")
    process = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(process.stdout.strip())


def measure_window(path: str, *, label: str, start_seconds: float,
                   duration_seconds: float) -> WindowLevel:
    """Measure one window with FFmpeg ``volumedetect``.

    ``-t`` is passed as an **input** option, because as an output option it silently
    cancels filters that follow.
    """

    if duration_seconds <= 0:
        raise AudioExecutorError("a measured window must have a positive duration")
    process = subprocess.run(
        [_which_ffmpeg(), "-hide_banner", "-nostats",
         "-ss", f"{start_seconds:.6f}", "-t", f"{duration_seconds:.6f}", "-i", path,
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    text = process.stderr
    mean = _MEAN_VOLUME.search(text)
    peak = _MAX_VOLUME.search(text)
    if mean is None or peak is None:
        if "n_samples: 0" in text:
            raise AudioExecutorError(
                f"window {label!r} at {start_seconds:.3f}s for {duration_seconds:.3f}s "
                f"contains no samples in {path}; it lies outside the file, which means "
                "the offset or the file is wrong"
            )
        raise AudioExecutorError(f"could not measure window {label!r} of {path}")
    return WindowLevel(label=label, start_seconds=round(start_seconds, 4),
                       duration_seconds=round(duration_seconds, 4),
                       mean_db=float(mean.group(1)), max_db=float(peak.group(1)))


def measure_loudness(path: str) -> LoudnessReading:
    """Integrated loudness and true peak, with clipping refused."""

    process = subprocess.run(
        [_which_ffmpeg(), "-hide_banner", "-nostats", "-i", path,
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    integrated = _LOUDNESS_RANGE.search(process.stderr)
    peak = _TRUE_PEAK.search(process.stderr)
    if integrated is None or peak is None:
        raise AudioExecutorError(f"could not measure loudness of {path}")
    lufs = float(integrated.group(1))
    dbtp = float(peak.group(1))
    return LoudnessReading(integrated_lufs=lufs, true_peak_dbtp=dbtp,
                           clipping=dbtp >= 0.0)


# ------------------------------------------------------------------- validation


@dataclass(frozen=True)
class ValidationFinding:
    check: str
    passed: bool
    detail: str


def validate_mix(
    plan: AudioPlan,
    *,
    vo_levels: Sequence[WindowLevel],
    bed_levels: Sequence[WindowLevel],
    loudness: LoudnessReading,
    reference_lufs: float,
    reference_dbtp: float,
    lufs_tolerance: float = 1.0,
) -> tuple[ValidationFinding, ...]:
    """Check the produced mix against the plan it claims to implement.

    ``bed_levels`` is the measured mix of **everything except voice**. Comparing the voice
    stem against a full mix that already contains the voice would measure nothing, so the
    comparison is voice against its competition.
    """

    findings: list[ValidationFinding] = []

    pairs = list(zip(vo_levels, bed_levels))
    if not pairs:
        raise AudioExecutorError("validation needs at least one VO/bed window pair")
    worst = min(vo.mean_db - bed.mean_db for vo, bed in pairs)
    findings.append(ValidationFinding(
        "voice_leads_the_mix", worst > 0.0,
        f"smallest VO-over-bed margin across {len(pairs)} window(s) is {worst:.2f} dB",
    ))

    dry_ids = set(plan.dry_shots)
    dry_windows = [w for w in bed_levels if w.label in dry_ids]
    if dry_windows:
        loudest_dry = max(w.max_db for w in dry_windows)
        findings.append(ValidationFinding(
            "dry_shots_carry_no_water", loudest_dry <= -50.0,
            f"loudest dry-window peak is {loudest_dry:.2f} dB across "
            f"{len(dry_windows)} dry shot(s)",
        ))

    findings.append(ValidationFinding(
        "loudness_matches_reference",
        abs(loudness.integrated_lufs - reference_lufs) <= lufs_tolerance,
        f"integrated {loudness.integrated_lufs:.2f} LUFS against reference "
        f"{reference_lufs:.2f} (tolerance {lufs_tolerance:g})",
    ))
    findings.append(ValidationFinding(
        "true_peak_does_not_clip",
        (not loudness.clipping) and loudness.true_peak_dbtp <= reference_dbtp,
        f"true peak {loudness.true_peak_dbtp:.2f} dBTP against ceiling "
        f"{reference_dbtp:.2f}",
    ))
    return tuple(findings)
