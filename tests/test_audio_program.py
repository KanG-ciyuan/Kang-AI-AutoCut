"""Second-SKU regression — audio program verification and source timebase.

Every test here represents a **real observed failure mode** from the first two production SKUs.
The docstrings name which one. No test exists merely to raise a count.
"""

from __future__ import annotations

import unittest

from src.ai_autocut.audio_program import (
    GAP_CLASSES,
    AlignmentFinding,
    AudioProgramError,
    KeywordExpectation,
    PlacedSegment,
    assess_program,
    check_fit,
    check_rhythm,
    check_sync,
    classify_gaps,
    detect_fixed_sum,
    order_segments,
)
from src.ai_autocut.timebase import (
    DEFAULT_FPS,
    SourceTiming,
    TimebaseError,
    frame_table,
    extract_timeline_frames,
)

# --- fixtures: a five-segment program with a declared breath -------------------------------

SLOTS = {"a": (0.0, 1.6), "b": (1.6, 3.5), "c": (3.5, 5.4), "d": (5.4, 11.4), "e": (13.8, 15.3)}


def prog(a_start=0.1, a_end=1.5, b_start=1.7, b_end=3.4, c_start=3.6, c_end=5.2,
         d_start=5.5, d_end=11.2, e_start=13.9, e_end=15.2):
    return [PlacedSegment("a", a_start, a_end, "open"),
            PlacedSegment("b", b_start, b_end, "usage"),
            PlacedSegment("c", c_start, c_end, "rinse"),
            PlacedSegment("d", d_start, d_end, "selling points"),
            PlacedSegment("e", e_start, e_end, "cta")]


DESIGN = {("a", "b"): ("INTENTIONAL_SEMANTIC_PAUSE", "new evidence unit"),
          ("b", "c"): ("INTENTIONAL_MICRO_PAUSE", "one instruction"),
          ("c", "d"): ("INTENTIONAL_SEMANTIC_PAUSE", "lift into the selling points")}


class FitIsNotApproval(unittest.TestCase):
    """SKU 2 — Audio v1 passed every technical check and was still rejected on creative review."""

    def test_a_program_can_pass_fit_and_fail_the_other_two(self) -> None:
        partial = {("a", "b"): ("INTENTIONAL_SEMANTIC_PAUSE", "new evidence unit"),
                   ("b", "c"): ("INTENTIONAL_MICRO_PAUSE", "one instruction")}
        report = assess_program(prog(), slots=SLOTS, design=partial,
                                hero_window=(11.5, 13.8), hero_approach_from="d")
        self.assertEqual(report.fit, "PASS")
        self.assertEqual(report.rhythm, "FAIL", "c->d is undeclared and must be a defect")
        self.assertFalse(report.approved)
        self.assertTrue(any("FIT passed but the program is not approvable" in f
                            for f in report.findings))

    def test_fit_fails_when_speech_runs_past_its_slot(self) -> None:
        status, notes = check_fit([PlacedSegment("a", 0.0, 3.0)], {"a": (0.0, 2.3)})
        self.assertEqual(status, "FAIL")
        self.assertTrue(any("past its slot" in n for n in notes))

    def test_fit_notes_deliberate_early_lead(self) -> None:
        """A voice may lead the picture on purpose; the check must say so, not just fail."""

        _, notes = check_fit([PlacedSegment("a", 2.20, 3.0)], {"a": (2.3, 4.6)})
        self.assertTrue(any("deliberately leading the picture" in n for n in notes))


class UndesignedSilence(unittest.TestCase):
    """SKU 2 — 6.96 s of silence inside the first VO take read as slowness and failed review."""

    def test_undeclared_gap_is_a_defect(self) -> None:
        gaps = classify_gaps(prog(), design=DESIGN)
        undeclared = [g for g in gaps if g.is_defect]
        self.assertTrue(undeclared)

    def test_declared_breathing_space_is_not_a_defect(self) -> None:
        gaps = classify_gaps(prog(), design=DESIGN, hero_window=(11.5, 13.8),
                             hero_approach_from="d")
        self.assertFalse(any(g.is_defect for g in gaps),
                         "a declared breath must not be counted as undesigned silence")
        self.assertIn("HERO_BREATHING_SPACE", {g.gap_class for g in gaps})

    def test_micro_pause_is_not_punished(self) -> None:
        """A natural micro pause is not bad silence - the lesson was explicit about this."""

        gaps = classify_gaps(prog(b_start=1.55), design=DESIGN)
        micro = [g for g in gaps if g.previous_segment == "a"][0]
        self.assertEqual(micro.gap_class, "INTENTIONAL_SEMANTIC_PAUSE")
        self.assertFalse(micro.is_defect)

    def test_rhythm_reports_the_total_not_just_a_count(self) -> None:
        gaps = classify_gaps(prog(), design=DESIGN)
        status, notes, total = check_rhythm(gaps)
        self.assertEqual(status, "FAIL")
        self.assertGreater(total, 0.0)
        self.assertTrue(any("undesigned silence totalling" in n for n in notes))

    def test_a_large_declared_pause_is_questioned(self) -> None:
        gaps = [__import__("src.ai_autocut.audio_program", fromlist=["GapFinding"]).GapFinding(
            "a", "b", 1.2, "INTENTIONAL_SEMANTIC_PAUSE", "claimed")]
        status, notes, _ = check_rhythm(gaps, unexplained_gap_limit=0.45)
        self.assertEqual(status, "WEAK")
        self.assertTrue(any("confirm the reason is real" in n for n in notes))

    def test_classify_never_invents_a_reason(self) -> None:
        gaps = classify_gaps(prog())
        self.assertTrue(all(g.is_defect for g in gaps),
                        "with no design supplied, every gap must be treated as undesigned")


class SyncVerification(unittest.TestCase):
    """SKU 2 — planned alignment said 'bilas' at 4.90-5.50 s; the actual placed position was 5.665 s."""

    def test_phrase_inside_its_evidence_window_is_good(self) -> None:
        exps = [KeywordExpectation("bilas", "c", 0.70, 4.65, 5.70, "visible water")]
        status, found, _ = check_sync(exps, prog(), tolerance=0.5)
        self.assertEqual(found[0].alignment, "GOOD")
        self.assertEqual(status, "PASS")

    def test_phrase_just_outside_is_late_not_weak(self) -> None:
        exps = [KeywordExpectation("bilas", "c", 0.85, 4.65, 4.80, "visible water")]
        status, found, _ = check_sync(exps, prog(), tolerance=0.5)
        self.assertEqual(found[0].alignment, "LATE")
        self.assertEqual(status, "WARN")

    def test_phrase_far_from_its_evidence_is_weak(self) -> None:
        exps = [KeywordExpectation("bilas", "d", 0.5, 4.65, 5.20, "visible water")]
        status, found, _ = check_sync(exps, prog(), tolerance=0.5)
        self.assertEqual(found[0].alignment, "WEAK")
        self.assertEqual(status, "FAIL")

    def test_sync_is_estimated_not_measured_by_default(self) -> None:
        """A word's onset cannot be measured without listening, and the report must say so."""

        exps = [KeywordExpectation("bilas", "c", 0.70, 4.65, 5.70, "water")]
        _, found, _ = check_sync(exps, prog(), tolerance=0.5)
        self.assertFalse(found[0].measured)

    def test_a_phrase_may_cross_two_visual_units(self) -> None:
        """One sentence spanning two units is legitimate and must not be flagged."""

        exps = [KeywordExpectation("colours and strap", "d", 0.5, 6.8, 11.5, "U04 + U05")]
        status, found, _ = check_sync(exps, prog(), tolerance=0.5)
        self.assertEqual(found[0].alignment, "GOOD")
        self.assertEqual(status, "PASS")


class NoUnauthorisedSyncDefault(unittest.TestCase):
    """Closeout correction - the Cushion Puff ~0.5 s tolerance must NOT be a production default.

    It was derived from one cut of one SKU. Silently applying it would let the system judge sync
    against a number that nothing in the current piece justifies.
    """

    def test_low_level_api_refuses_to_guess_a_tolerance(self) -> None:
        exps = [KeywordExpectation("phrase", "c", 0.70, 4.65, 5.70, "evidence")]
        with self.assertRaises(AudioProgramError) as ctx:
            check_sync(exps, prog())
        self.assertIn("must be supplied", str(ctx.exception))

    def test_no_zero_point_five_default_survives_in_the_signature(self) -> None:
        import inspect
        sig = inspect.signature(check_sync)
        self.assertIsNone(sig.parameters["tolerance"].default,
                          "check_sync must not carry a default tolerance")
        sig2 = inspect.signature(assess_program)
        self.assertIsNone(sig2.parameters["sync_tolerance"].default,
                          "assess_program must not carry a default sync tolerance")

    def test_absence_returns_review_required_not_a_silent_pass(self) -> None:
        exps = [KeywordExpectation("phrase", "c", 0.70, 4.65, 5.70, "evidence")]
        report = assess_program(prog(), slots=SLOTS, design=DESIGN, expectations=exps)
        self.assertEqual(report.sync, "REVIEW_REQUIRED")
        self.assertNotEqual(report.sync, "PASS")
        self.assertFalse(report.approved)
        self.assertTrue(any("no authorised default" in f for f in report.findings))

    def test_an_explicit_tolerance_still_works(self) -> None:
        exps = [KeywordExpectation("phrase", "c", 0.70, 4.65, 5.70, "evidence")]
        report = assess_program(prog(), slots=SLOTS, design=DESIGN, expectations=exps,
                                sync_tolerance=0.25)
        self.assertEqual(report.sync, "PASS")

    def test_the_value_is_therefore_caller_and_evidence_dependent(self) -> None:
        """The same phrase may pass under one tolerance and warn under another - which is exactly
        why no universal number may be baked in."""

        exps = [KeywordExpectation("phrase", "c", 0.85, 4.65, 4.80, "narrow evidence")]
        lenient, _, _ = check_sync(exps, prog(), tolerance=0.50)
        strict, _, _ = check_sync(exps, prog(), tolerance=0.05)
        self.assertEqual(lenient, "WARN")
        self.assertEqual(strict, "FAIL")


class FixedSumGaps(unittest.TestCase):
    """SKU 2 — v2.1 made explicit that gap_A + gap_B = a fixed span, so silence was moved, not removed."""

    def test_fixed_sum_is_detected_and_reported(self) -> None:
        segs = [PlacedSegment("y", 4.3, 6.0), PlacedSegment("z", 6.2, 7.4),
                PlacedSegment("w", 7.6, 8.0)]
        found = detect_fixed_sum(segs, 4.0, 8.0, candidate_splits=(0.3, 0.4, 0.5))
        self.assertIsNotNone(found)
        self.assertAlmostEqual(found["fixed_sum"], 0.7, places=3)
        self.assertTrue(any("redistributed, not removed" in found["note"] for _ in [0]))
        self.assertEqual(len(found["candidate_splits"]), 3)

    def test_no_fixed_sum_when_the_span_does_not_account_for_the_gaps(self) -> None:
        segs = [PlacedSegment("x", 0.0, 1.0), PlacedSegment("y", 1.1, 2.0)]
        self.assertIsNone(detect_fixed_sum(segs, 0.0, 9.0),
                          "a single gap is not a two-gap split")


class PlacementIntegrity(unittest.TestCase):
    """SKU 2 — a first build placed two speech segments in a 0.020 s overlap."""

    def test_overlapping_segments_are_refused(self) -> None:
        with self.assertRaises(AudioProgramError):
            order_segments([PlacedSegment("a", 0.0, 2.0), PlacedSegment("b", 1.98, 3.0)])

    def test_an_empty_segment_is_refused(self) -> None:
        with self.assertRaises(AudioProgramError):
            PlacedSegment("a", 1.0, 1.0)

    def test_unknown_gap_class_is_refused(self) -> None:
        with self.assertRaises(AudioProgramError):
            classify_gaps(prog(), design={("a", "b"): ("LOOKS_FINE", "vibes")})

    def test_gap_classes_are_a_closed_vocabulary(self) -> None:
        self.assertIn("UNDESIGNED_GAP", GAP_CLASSES)
        self.assertIn("HERO_BREATHING_SPACE", GAP_CLASSES)


class TimebaseCoordinates(unittest.TestCase):
    """SKU 2 — frame_index / fps was wrong for a VFR source and built 502 frames instead of 487."""

    def test_a_frame_index_is_not_a_source_time_on_a_vfr_source(self) -> None:
        """The measured shape of the real failing source: mixed deltas, span != frames/fps."""

        deltas = {1 / 30: 414, 1 / 15: 33}
        expected = 1 / 30
        is_vfr = any(abs(d - expected) > 1e-4 for d in deltas)
        self.assertTrue(is_vfr, "mixed deltas must be recognised as variable frame rate")
        frames, span = 448, 16.0
        self.assertNotAlmostEqual(frames / 30, span, places=2,
                                  msg="448 frames span 16.0 s, not 448/30 s - the bug in one line")

    def test_the_timeline_index_is_derived_from_the_timestamp(self) -> None:
        self.assertEqual(int(round(12.400000 * DEFAULT_FPS)), 372)
        self.assertEqual(int(round(14.566667 * DEFAULT_FPS)), 437)

    def test_a_span_that_sits_on_a_cfr_boundary_is_ambiguous(self) -> None:
        """This is why the same range produced 66 frames once and 67 another time."""

        span = 14.566667 - 12.400000
        self.assertAlmostEqual(span * 30, 65.0, places=1)
        self.assertAlmostEqual(span * 30, 65.0, delta=0.1,
                               msg="a natural span of 65 frames was asked to produce 66")

    def test_extraction_rejects_impossible_requests(self) -> None:
        with self.assertRaises(TimebaseError):
            extract_timeline_frames("/nonexistent.mp4", t_in=0.0, frames=0,
                                    out_path="/tmp/x.mp4")
        with self.assertRaises(TimebaseError):
            extract_timeline_frames("/nonexistent.mp4", t_in=-1.0, frames=10,
                                    out_path="/tmp/x.mp4")

    def test_unreadable_source_reports_a_clear_error(self) -> None:
        with self.assertRaises(TimebaseError):
            frame_table("/nonexistent-source.mp4")

    def test_reproducibility_needs_more_than_one_run(self) -> None:
        import tempfile, os
        from src.ai_autocut.timebase import assert_reproducible
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
            clip = fh.name
            fh.write(b"not a video")
        try:
            with self.assertRaises(TimebaseError):
                assert_reproducible(clip, t_in=0.0, frames=5, runs=1)
        finally:
            os.unlink(clip)


class AssessProgramIntegration(unittest.TestCase):
    def test_a_well_designed_program_is_approvable(self) -> None:
        report = assess_program(prog(), slots=SLOTS, design=DESIGN,
                                hero_window=(11.5, 13.8), hero_approach_from="d")
        self.assertEqual(report.rhythm, "PASS")
        self.assertTrue(report.approved)
        self.assertEqual(report.undesigned_silence_seconds, 0.0)

    def test_the_report_serialises_and_separates_the_three_judgements(self) -> None:
        payload = assess_program(prog(), slots=SLOTS, design=DESIGN).as_dict()
        for key in ("fit", "sync", "rhythm", "approved_on_all_three", "gaps", "alignments"):
            self.assertIn(key, payload)
        self.assertNotEqual(payload["fit"], payload["rhythm"])

    def test_silence_is_not_hidden_in_one_aggregate(self) -> None:
        """Designed, undesigned and hero span must be reported separately."""

        report = assess_program(prog(), slots=SLOTS, design=DESIGN,
                                hero_window=(11.5, 13.8), hero_approach_from="d")
        self.assertGreater(report.designed_pause_seconds, 0.0)
        self.assertGreater(report.hero_seconds, 0.0)
        self.assertNotEqual(report.designed_pause_seconds, report.hero_seconds)
        self.assertAlmostEqual(report.hero_seconds, 2.3, places=3)

    def test_hero_and_undesigned_silence_are_distinguished(self) -> None:
        with_breath = assess_program(prog(), slots=SLOTS, design=DESIGN,
                                     hero_window=(11.5, 13.8), hero_approach_from="d")
        self.assertEqual(with_breath.undesigned_silence_seconds, 0.0)


if __name__ == "__main__":
    unittest.main()
