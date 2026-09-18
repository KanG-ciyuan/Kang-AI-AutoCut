"""Audio program verification — what the placed voice track actually does.

Post-blind learning, Second SKU (cushion-puff-second-sku-v1).

Why this exists
---------------
The first audio mix passed every technical check and was still rejected on creative review. It fitted
every slot, did not clip, and hit its loudness target. What it also had was **6.96 seconds of
undesigned silence**, selling phrases that arrived after the picture that supported them, and a
completely flat read. None of that was visible to any check the system had.

So this module separates three questions that are easy to mistake for one:

    FIT     does the speech fit the slot?          (the only one v1 passed)
    SYNC    do the selling words land on their evidence?
    RHYTHM  does it flow as one pitch, with pauses that were designed?

**A program can pass FIT and fail the other two.** Approving on FIT alone is the failure this
prevents.

Second lesson: a large gap needs a *reason*. Silence is not automatically wrong — a deliberate breath
is a creative instrument. But an unexplained gap is a defect, and the difference must be declared
rather than inferred.

Third lesson: two gaps inside a fixed span are a **zero-sum** split. Moving silence does not remove
it. When that happens, report the sum and the candidate distributions instead of quietly picking one.

Nothing here is product-specific.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

#: What a gap between two placed segments is.
GAP_CLASSES = (
    "INTENTIONAL_MICRO_PAUSE",      # inside one thought; a comma's worth
    "INTENTIONAL_SEMANTIC_PAUSE",   # a new evidence unit begins
    "HERO_BREATHING_SPACE",         # a declared creative breath
    "HERO_APPROACH",                # the lead-out into a declared breath
    "NARRATIVE_END",                # nothing follows; the piece is over
    "UNDESIGNED_GAP",               # no reason given - this is the defect
)

#: Classes that count as designed silence rather than a defect.
DESIGNED_GAP_CLASSES = tuple(c for c in GAP_CLASSES if c != "UNDESIGNED_GAP")

SEVERITIES = ("PASS", "WEAK", "FAIL", "CRITICAL")


class AudioProgramError(ValueError):
    """Raised when a placement cannot be assessed safely."""


@dataclass(frozen=True)
class PlacedSegment:
    """One placed piece of speech. Times are timeline seconds."""

    segment_id: str
    start_seconds: float
    end_seconds: float
    text: str = ""

    def __post_init__(self) -> None:
        if not self.segment_id:
            raise AudioProgramError("a placed segment needs an id")
        if self.end_seconds <= self.start_seconds:
            raise AudioProgramError(f"segment {self.segment_id!r} must be a non-empty interval")

    @property
    def duration(self) -> float:
        return round(self.end_seconds - self.start_seconds, 4)


@dataclass(frozen=True)
class KeywordExpectation:
    """Where a selling phrase is *expected* to land, and what proves it.

    ``fraction`` is the phrase's position inside its own segment, because the exact onset of a word
    cannot be measured without listening. Carrying that uncertainty explicitly is the point: an
    estimated time is reported as estimated.
    """

    phrase: str
    segment_id: str
    fraction: float
    evidence_start: float
    evidence_end: float
    evidence_label: str
    measured: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.fraction <= 1.0:
            raise AudioProgramError("fraction must be between 0 and 1")
        if self.evidence_end <= self.evidence_start:
            raise AudioProgramError("an evidence window must be a non-empty interval")


@dataclass(frozen=True)
class GapFinding:
    previous_segment: str
    next_segment: str
    gap_seconds: float
    gap_class: str
    why: str = ""

    @property
    def is_defect(self) -> bool:
        return self.gap_class == "UNDESIGNED_GAP"


@dataclass(frozen=True)
class AlignmentFinding:
    phrase: str
    estimated_start: float
    estimated_end: float
    evidence_start: float
    evidence_end: float
    evidence_label: str
    alignment: str          # GOOD / EARLY / LATE / WEAK
    measured: bool


@dataclass(frozen=True)
class AudioProgramReport:
    fit: str
    sync: str
    rhythm: str
    gaps: tuple[GapFinding, ...] = ()
    alignments: tuple[AlignmentFinding, ...] = ()
    findings: tuple[str, ...] = ()
    undesigned_silence_seconds: float = 0.0
    designed_pause_seconds: float = 0.0
    hero_seconds: float = 0.0
    fixed_sum: dict | None = None

    @property
    def approved(self) -> bool:
        """FIT alone is never approval."""

        return (self.fit == "PASS" and self.sync in ("PASS", "WARN")
                and self.rhythm == "PASS")

    def as_dict(self) -> dict:
        return {"fit": self.fit, "sync": self.sync, "rhythm": self.rhythm,
                "approved_on_all_three": self.approved,
                "undesigned_silence_seconds": round(self.undesigned_silence_seconds, 3),
                "designed_pause_seconds": round(self.designed_pause_seconds, 3),
                "hero_seconds": round(self.hero_seconds, 3),
                "gaps": [{"previous": g.previous_segment, "next": g.next_segment,
                          "seconds": g.gap_seconds, "class": g.gap_class, "why": g.why}
                         for g in self.gaps],
                "alignments": [{"phrase": a.phrase, "start": a.estimated_start,
                                "end": a.estimated_end, "evidence": a.evidence_label,
                                "alignment": a.alignment, "measured": a.measured}
                               for a in self.alignments],
                "fixed_sum": self.fixed_sum,
                "findings": list(self.findings)}


def order_segments(segments: Iterable[PlacedSegment]) -> list[PlacedSegment]:
    ordered = sorted(segments, key=lambda s: s.start_seconds)
    for a, b in zip(ordered, ordered[1:]):
        if b.start_seconds < a.end_seconds - 1e-6:
            raise AudioProgramError(
                f"segments {a.segment_id!r} and {b.segment_id!r} overlap - two pieces of speech "
                f"cannot play at once")
    return ordered


def check_fit(segments: Sequence[PlacedSegment], slots: dict[str, tuple[float, float]]
              ) -> tuple[str, list[str]]:
    """Does every segment fit inside the slot it belongs to?"""

    findings: list[str] = []
    status = "PASS"
    for seg in segments:
        if seg.segment_id not in slots:
            continue
        lo, hi = slots[seg.segment_id]
        if seg.start_seconds < lo - 1e-6:
            status = "FAIL"
            findings.append(
                f"{seg.segment_id} starts at {seg.start_seconds:.3f}s, before its slot opens at "
                f"{lo:.4f}s - unless it is deliberately leading the picture")
        if seg.end_seconds > hi + 1e-6:
            status = "FAIL"
            findings.append(
                f"{seg.segment_id} ends at {seg.end_seconds:.3f}s, past its slot closing at "
                f"{hi:.4f}s by {seg.end_seconds - hi:.3f}s")
    return status, findings


def classify_gaps(segments: Sequence[PlacedSegment], *,
                  design: dict[tuple[str, str], tuple[str, str]] | None = None,
                  hero_window: tuple[float, float] | None = None,
                  hero_approach_from: str | None = None,
                  final_segment: str | None = None,
                  default_class: str = "UNDESIGNED_GAP"
                  ) -> list[GapFinding]:
    """Classify every gap between consecutive placed segments.

    ``design`` maps ``(previous_id, next_id)`` to ``(gap_class, why)``. Anything the caller does not
    declare stays ``UNDESIGNED_GAP`` - the module does not invent reasons for silence.

    A gap that **contains a declared breathing space is decomposed** into approach / breath / tail
    rather than reported as one number. Reporting it whole hides the breath inside an aggregate,
    which is exactly how a 3.954 s gap once looked like a 3.954 s "approach".
    """

    if default_class not in GAP_CLASSES:
        raise AudioProgramError(f"unknown gap class {default_class!r}")
    design = design or {}
    ordered = order_segments(segments)
    out: list[GapFinding] = []
    for a, b in zip(ordered, ordered[1:]):
        gap = round(b.start_seconds - a.end_seconds, 3)
        if gap <= 0:
            continue
        if (hero_window and a.end_seconds < hero_window[0] - 1e-6
                and b.start_seconds > hero_window[1] + 1e-6):
            approach = round(hero_window[0] - a.end_seconds, 3)
            breath = round(hero_window[1] - hero_window[0], 3)
            tail = round(b.start_seconds - hero_window[1], 3)
            declared = design.get((a.segment_id, b.segment_id))
            if approach > 0:
                why = (declared[1] if declared else
                       "lead-out into a declared breathing space")
                out.append(GapFinding(a.segment_id, "(breath)", approach, "HERO_APPROACH", why))
            out.append(GapFinding("(breath)", "(breath)", breath, "HERO_BREATHING_SPACE",
                                  "declared breathing space"))
            if tail > 0:
                tail_declared = design.get(("(breath)", b.segment_id))
                cls, why = (tail_declared if tail_declared else
                            ("INTENTIONAL_MICRO_PAUSE",
                             "separation after a declared breathing space"))
                out.append(GapFinding("(breath)", b.segment_id, tail, cls, why))
            continue
        declared = design.get((a.segment_id, b.segment_id))
        if declared:
            gap_class, why = declared
        elif hero_approach_from and a.segment_id == hero_approach_from:
            gap_class, why = "HERO_APPROACH", "lead-out into a declared breathing space"
        elif final_segment and a.segment_id == final_segment:
            gap_class, why = "NARRATIVE_END", "nothing follows; the piece has ended"
        else:
            gap_class, why = default_class, ""
        if gap_class not in GAP_CLASSES:
            raise AudioProgramError(f"unknown gap class {gap_class!r}")
        out.append(GapFinding(a.segment_id, b.segment_id, gap, gap_class, why))
    return out


def check_rhythm(gaps: Sequence[GapFinding], *, unexplained_gap_limit: float = 0.45
                 ) -> tuple[str, list[str], float]:
    """Undesigned silence is a defect; designed silence is not.

    ``unexplained_gap_limit`` is where a *declared* pause stops being credible as a pause and starts
    needing a stronger reason than a one-line label.
    """

    findings: list[str] = []
    undesigned = round(sum(g.gap_seconds for g in gaps if g.is_defect), 3)
    status = "PASS"
    if undesigned > 0:
        status = "FAIL"
        holes = [g for g in gaps if g.is_defect]
        findings.append(
            "undesigned silence totalling {:.3f}s across {} gap(s): {}".format(
                undesigned, len(holes),
                ", ".join(f"{g.previous_segment}->{g.next_segment} {g.gap_seconds:.3f}s"
                          for g in holes)))
    for g in gaps:
        if g.is_defect or g.gap_class in ("HERO_BREATHING_SPACE", "NARRATIVE_END"):
            continue
        if g.gap_seconds > unexplained_gap_limit:
            status = "WEAK" if status == "PASS" else status
            findings.append(
                f"{g.previous_segment}->{g.next_segment} is {g.gap_seconds:.3f}s declared as "
                f"{g.gap_class} - larger than a pause usually is; confirm the reason is real")
    return status, findings, undesigned


def check_sync(expectations: Sequence[KeywordExpectation], segments: Sequence[PlacedSegment],
               *, tolerance: float | None = None) -> tuple[str, list[AlignmentFinding], list[str]]:
    """Do the selling words land near the evidence that supports them?

    ``tolerance`` is how far outside the evidence window a phrase may fall before it stops being
    supported by nearby picture. **It has no default and must be supplied.**

    A tolerance is evidence-dependent: how much drift a piece can absorb depends on the shot length,
    the action, and what the phrase is claiming. The value used during Second-SKU work was derived
    from one Cushion Puff cut and is **not** authorised as a production default. Rather than invent a
    replacement universal number, this function refuses to guess.
    """

    if tolerance is None:
        raise AudioProgramError(
            "a sync tolerance must be supplied by the caller - there is no authorised default. "
            "The tolerance depends on the evidence window and must not be inherited from another SKU.")
    if tolerance <= 0:
        raise AudioProgramError("tolerance must be positive")
    by_id = {s.segment_id: s for s in segments}
    findings: list[AlignmentFinding] = []
    notes: list[str] = []
    status = "PASS"
    for exp in expectations:
        seg = by_id.get(exp.segment_id)
        if seg is None:
            raise AudioProgramError(f"unknown segment {exp.segment_id!r} for phrase {exp.phrase!r}")
        start = round(seg.start_seconds + seg.duration * exp.fraction, 3)
        end = round(start + seg.duration * 0.25, 3)
        if exp.evidence_start <= start <= exp.evidence_end:
            verdict = "GOOD"
        elif start < exp.evidence_start:
            verdict = "EARLY" if exp.evidence_start - start <= tolerance else "WEAK"
        else:
            verdict = "LATE" if start - exp.evidence_end <= tolerance else "WEAK"
        if verdict == "WEAK":
            status = "FAIL"
            notes.append(
                f"{exp.phrase!r} lands at {start:.3f}s but its evidence "
                f"({exp.evidence_label}) is {exp.evidence_start:.4f}-{exp.evidence_end:.4f}s")
        elif verdict in ("EARLY", "LATE") and status == "PASS":
            status = "WARN"
            notes.append(
                f"{exp.phrase!r} lands at {start:.3f}s, {verdict.lower()} of its evidence "
                f"({exp.evidence_label}) by "
                f"{abs(start - min(max(start, exp.evidence_start), exp.evidence_end)):.3f}s")
        findings.append(AlignmentFinding(exp.phrase, start, end, exp.evidence_start,
                                         exp.evidence_end, exp.evidence_label, verdict,
                                         exp.measured))
    return status, findings, notes


def detect_fixed_sum(segments: Sequence[PlacedSegment], span_start: float, span_end: float,
                     *, candidate_splits: Sequence[float] | None = None) -> dict | None:
    """Detect gaps inside a span whose total is fixed by things that cannot move.

    When a locked timeline and a locked piece of speech leave only so much room, tightening one gap
    necessarily lengthens the other. **The fixed quantity is the span minus the speech inside it** -
    not the span itself, which would be wrong whenever a segment sits in the middle.

    Reporting the sum is the honest move; reporting only the chosen value makes it look as though
    silence was removed when it was only moved.
    """

    if span_end <= span_start:
        raise AudioProgramError("a span must be a non-empty interval")
    ordered = order_segments(segments)
    inside = [s for s in ordered
              if s.start_seconds >= span_start - 1e-6 and s.end_seconds <= span_end + 1e-6]
    if len(inside) < 2:
        return None
    speech = round(sum(s.duration for s in inside), 3)
    free = round((span_end - span_start) - speech, 3)
    gaps = [g for g in classify_gaps(inside) if g.gap_seconds > 0]
    if len(gaps) < 2:
        return None
    if free <= 0:
        return None
    carried = round(sum(g.gap_seconds for g in gaps), 3)
    first = gaps[0]
    splits = []
    for value in (candidate_splits or ()):
        if 0 <= value <= free:
            splits.append({first.next_segment: round(value, 3),
                           "remaining": round(free - value, 3)})
    return {"span_seconds": round(span_end - span_start, 3), "speech_inside_seconds": speech,
            "fixed_sum": free, "gap_sum_between_segments": carried,
            "gaps_in_span": [g.previous_segment + "->" + g.next_segment for g in gaps],
            "note": ("the gaps share a fixed span minus the speech inside it - tightening one "
                     "necessarily lengthens the other. Silence was redistributed, not removed."),
            "candidate_splits": splits}


def assess_program(segments: Sequence[PlacedSegment], *,
                   slots: dict[str, tuple[float, float]] | None = None,
                   design: dict[tuple[str, str], tuple[str, str]] | None = None,
                   hero_window: tuple[float, float] | None = None,
                   hero_approach_from: str | None = None,
                   final_segment: str | None = None,
                   expectations: Sequence[KeywordExpectation] | None = None,
                   sync_tolerance: float | None = None,
                   unexplained_gap_limit: float = 0.45) -> AudioProgramReport:
    """Assess FIT, SYNC and RHYTHM separately. All three must pass.

    Sync cannot be judged without a caller-supplied tolerance. When expectations are present and no
    tolerance was given, SYNC is reported as ``REVIEW_REQUIRED`` - the assessment degrades to "a human
    must decide" rather than silently applying a heuristic borrowed from another SKU.
    """

    ordered = order_segments(segments)
    fit_status, fit_notes = check_fit(ordered, slots or {}) if slots else ("PASS", [])
    gaps = classify_gaps(ordered, design=design, hero_window=hero_window,
                         hero_approach_from=hero_approach_from, final_segment=final_segment)
    rhythm_status, rhythm_notes, undesigned = check_rhythm(
        gaps, unexplained_gap_limit=unexplained_gap_limit)
    if expectations and sync_tolerance is None:
        sync_status, alignments, sync_notes = "REVIEW_REQUIRED", [], [
            "SYNC cannot be judged: no tolerance was supplied and there is no authorised default. "
            "Supply a tolerance derived from this piece's own evidence window, or review manually."]
    elif expectations:
        sync_status, alignments, sync_notes = check_sync(
            expectations, ordered, tolerance=sync_tolerance)
    else:
        sync_status, alignments, sync_notes = "PASS", [], []
    hero = 0.0
    if hero_window:
        hero = round(max(0.0, hero_window[1] - hero_window[0]), 3)
    designed = round(sum(g.gap_seconds for g in gaps if not g.is_defect), 3)
    findings = fit_notes + sync_notes + rhythm_notes
    if fit_status == "PASS" and (sync_status != "PASS" or rhythm_status != "PASS"):
        findings.append(
            "FIT passed but the program is not approvable: fitting every slot is not the same as "
            "landing the words on their evidence or flowing as one pitch")
    return AudioProgramReport(fit=fit_status, sync=sync_status, rhythm=rhythm_status,
                              gaps=tuple(gaps), alignments=tuple(alignments),
                              findings=tuple(findings),
                              undesigned_silence_seconds=undesigned,
                              designed_pause_seconds=designed, hero_seconds=hero)
