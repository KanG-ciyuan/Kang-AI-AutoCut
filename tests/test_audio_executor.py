"""Tests for the deterministic audio executor.

Measurement tests generate their own tiny signals with FFmpeg, so no Filter First Job
asset is needed and no job value can leak into production behaviour.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest

from src.ai_autocut.audio_executor import (
    LEADING_SOURCE,
    SFX_JUSTIFICATIONS,
    YIELD_DB_PER_COMPETING_SOURCE,
    AudioExecutorError,
    ContinuityProof,
    DuckingRule,
    LoudnessReading,
    SfxDecision,
    VoCut,
    WindowLevel,
    bgm_is_eased,
    build_bgm_volume_filter,
    decide_sfx,
    measure_duration,
    measure_loudness,
    measure_window,
    plan_bgm_automation,
    plan_ducking,
    resolve_semantic_windows,
    validate_mix,
    verify_continuous_performance,
)
from src.ai_autocut.audio_plan import (
    BGM_STRUCTURE,
    AudioPlan,
    BgmSection,
    VoEvent,
    WaterEvent,
)


def _has_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _tone(path: str, *, seconds: float, frequency: int = 440, volume: float = 0.5) -> str:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={seconds}",
         "-af", f"volume={volume}", "-ar", "48000", "-ac", "2", path],
        check=True,
    )
    return path


class SemanticBindingTests(unittest.TestCase):
    """Audio binds to a unit, and resolving is what turns it into seconds."""

    def test_a_unit_resolves_to_a_concrete_window(self) -> None:
        events = (VoEvent(vo_id="VO1", purpose="open", semantic_unit="UNIT_A"),)
        resolved = resolve_semantic_windows(events, {"UNIT_A": (1.0, 4.0)})
        self.assertEqual(resolved[0].start_seconds, 1.0)
        self.assertEqual(resolved[0].end_seconds, 4.0)
        self.assertAlmostEqual(resolved[0].window_seconds, 3.0, places=4)

    def test_the_binding_target_is_the_unit_not_a_timestamp(self) -> None:
        events = (VoEvent(vo_id="VO1", purpose="open", semantic_unit="UNIT_A"),)
        first = resolve_semantic_windows(events, {"UNIT_A": (1.0, 4.0)})
        shifted = resolve_semantic_windows(events, {"UNIT_A": (2.5, 5.5)})
        self.assertNotEqual(first[0].start_seconds, shifted[0].start_seconds)
        self.assertEqual(first[0].semantic_unit, shifted[0].semantic_unit)

    def test_an_unknown_unit_without_a_fallback_is_refused(self) -> None:
        events = (VoEvent(vo_id="VO1", purpose="open", semantic_unit="MISSING"),)
        with self.assertRaises(AudioExecutorError):
            resolve_semantic_windows(events, {})

    def test_a_declared_window_is_used_only_as_a_fallback(self) -> None:
        events = (VoEvent(vo_id="VO1", purpose="open", semantic_unit="UNIT_A",
                          window_seconds=(9.0, 12.0)),)
        fallback = resolve_semantic_windows(events, {})
        self.assertEqual(fallback[0].start_seconds, 9.0)
        authoritative = resolve_semantic_windows(events, {"UNIT_A": (1.0, 4.0)})
        self.assertEqual(authoritative[0].start_seconds, 1.0)

    def test_an_empty_resolved_window_is_refused(self) -> None:
        events = (VoEvent(vo_id="VO1", purpose="open", semantic_unit="UNIT_A"),)
        with self.assertRaises(AudioExecutorError):
            resolve_semantic_windows(events, {"UNIT_A": (4.0, 4.0)})


class ContinuousPerformanceTests(unittest.TestCase):
    """Several spans must come from one take, not several generations."""

    def test_spans_from_one_take_prove_continuity(self) -> None:
        cuts = (VoCut("VO1", 0.0, 1.0, 0.0), VoCut("VO2", 2.0, 3.0, 1.5),
                VoCut("VO3", 4.0, 6.0, 3.0))
        proof = verify_continuous_performance("take.wav", cuts, take_duration=8.0)
        self.assertTrue(proof.is_continuous_performance)
        self.assertTrue(proof.single_source)
        self.assertTrue(proof.non_overlapping)
        self.assertTrue(proof.ordered)
        self.assertEqual(proof.spans, 3)

    def test_overlapping_spans_break_continuity(self) -> None:
        cuts = (VoCut("VO1", 0.0, 3.0, 0.0), VoCut("VO2", 2.0, 4.0, 3.0))
        proof = verify_continuous_performance("take.wav", cuts, take_duration=8.0)
        self.assertFalse(proof.non_overlapping)
        self.assertFalse(proof.is_continuous_performance)

    def test_out_of_order_spans_break_continuity(self) -> None:
        cuts = (VoCut("VO1", 4.0, 6.0, 0.0), VoCut("VO2", 0.0, 2.0, 2.0))
        proof = verify_continuous_performance("take.wav", cuts, take_duration=8.0)
        self.assertFalse(proof.ordered)

    def test_a_span_past_the_end_of_the_take_breaks_continuity(self) -> None:
        cuts = (VoCut("VO1", 0.0, 12.0, 0.0),)
        proof = verify_continuous_performance("take.wav", cuts, take_duration=8.0)
        self.assertFalse(proof.single_source)
        self.assertFalse(proof.is_continuous_performance)

    def test_an_empty_span_is_refused(self) -> None:
        with self.assertRaises(AudioExecutorError):
            verify_continuous_performance("take.wav", (VoCut("VO1", 2.0, 2.0, 0.0),),
                                          take_duration=8.0)

    def test_no_spans_is_refused(self) -> None:
        with self.assertRaises(AudioExecutorError):
            verify_continuous_performance("take.wav", (), take_duration=8.0)

    def test_a_per_sentence_generation_cannot_satisfy_the_proof(self) -> None:
        """Separate takes have separate files, so no single-take proof exists."""

        proof = verify_continuous_performance("one-of-six.wav", (VoCut("VO1", 0.0, 1.0, 0.0),),
                                              take_duration=1.0)
        self.assertEqual(proof.spans, 1)
        self.assertLess(proof.spans, 2)


class SfxPolicyTests(unittest.TestCase):
    """Do not add sound just because an action exists."""

    def test_sound_is_off_by_default(self) -> None:
        decisions = decide_sfx([("UNIT_A", ""), ("UNIT_B", "   ")])
        self.assertTrue(all(not d.added for d in decisions))

    def test_an_action_existing_is_not_a_justification(self) -> None:
        with self.assertRaises(AudioExecutorError):
            decide_sfx([("UNIT_A", "there is a hand action here")])
        with self.assertRaises(AudioExecutorError):
            SfxDecision(unit_id="UNIT_A", added=True, reason="there is a hand action here")

    def test_a_declared_improvement_allows_a_sound(self) -> None:
        for justification in SFX_JUSTIFICATIONS:
            with self.subTest(justification=justification):
                decision = decide_sfx([("UNIT_A", f"improves {justification}")])[0]
                self.assertTrue(decision.added)

    def test_a_sound_without_a_named_improvement_is_refused(self) -> None:
        with self.assertRaises(AudioExecutorError):
            SfxDecision(unit_id="UNIT_A", added=True, reason="it seemed nice")

    def test_a_malformed_unit_id_is_refused(self) -> None:
        with self.assertRaises(AudioExecutorError):
            SfxDecision(unit_id="bad id!", added=False)

    def test_removal_is_recorded_with_its_reason(self) -> None:
        decision = SfxDecision(unit_id="UNIT_A", added=False,
                               reason="measured inaudible and unrelated to the action")
        self.assertFalse(decision.added)
        self.assertTrue(decision.reason)


class BgmAutomationTests(unittest.TestCase):
    """Intent in, relative curve out. No absolute level, no copied gain."""

    def _segments(self, sections, competition):
        windows = {name: (float(index * 5), float(index * 5 + 5))
                   for index, name in enumerate(BGM_STRUCTURE)}
        return plan_bgm_automation(sections, section_windows=windows,
                                   competing_sources=competition)

    def test_hold_keeps_the_level(self) -> None:
        sections = [BgmSection("HOOK_INTRO", "HOLD", "RAMP", 0.5)]
        segments = self._segments(sections, {"HOOK_INTRO": 0})
        self.assertEqual(segments[0].start_relative_db, 0.0)
        self.assertEqual(segments[0].end_relative_db, 0.0)

    def test_yield_lowers_the_music_in_proportion_to_competition(self) -> None:
        one = self._segments([BgmSection("HOOK_INTRO", "YIELD", "RAMP", 0.5)],
                             {"HOOK_INTRO": 1})[0]
        two = self._segments([BgmSection("HOOK_INTRO", "YIELD", "RAMP", 0.5)],
                             {"HOOK_INTRO": 2})[0]
        self.assertLess(one.end_relative_db, 0.0)
        self.assertLess(two.end_relative_db, one.end_relative_db)
        self.assertAlmostEqual(one.end_relative_db, -YIELD_DB_PER_COMPETING_SOURCE, places=3)

    def test_return_restores_the_level(self) -> None:
        sections = [BgmSection("HOOK_INTRO", "YIELD", "RAMP", 0.5),
                    BgmSection("PRODUCT_BUILD", "RETURN", "RAMP", 0.6)]
        segments = self._segments(sections, {"HOOK_INTRO": 2, "PRODUCT_BUILD": 0})
        self.assertEqual(segments[1].end_relative_db, 0.0)

    def test_the_curve_is_relative_never_absolute(self) -> None:
        sections = [BgmSection("HOOK_INTRO", "YIELD", "RAMP", 0.5)]
        segments = self._segments(sections, {"HOOK_INTRO": 1})
        self.assertLessEqual(abs(segments[0].end_relative_db), 24.0)

    def test_no_copied_gain_appears_in_the_module(self) -> None:
        import src.ai_autocut.audio_executor as module

        source = open(module.__file__, encoding="utf-8").read()
        for copied in ("0.92", "0.52", "0.86", "0.78", "0.62", "0.66", "0.42", "0.34"):
            with self.subTest(value=copied):
                self.assertNotIn(copied, source)

    def test_a_ramped_plan_is_eased(self) -> None:
        sections = [BgmSection("HOOK_INTRO", "HOLD", "RAMP", 0.5),
                    BgmSection("PRODUCT_BUILD", "YIELD", "RAMP", 0.8),
                    BgmSection("USAGE_LIFT", "RETURN", "RAMP", 0.9)]
        self.assertTrue(bgm_is_eased(self._segments(sections, {"PRODUCT_BUILD": 2})))

    def test_a_step_is_not_eased(self) -> None:
        sections = [BgmSection("HOOK_INTRO", "HOLD", "RAMP", 0.5),
                    BgmSection("PRODUCT_BUILD", "YIELD", "STEP",
                               step_reason="the cut lands on the beat")]
        self.assertFalse(bgm_is_eased(self._segments(sections, {"PRODUCT_BUILD": 2})))

    def test_the_filter_expression_is_built_for_the_whole_curve(self) -> None:
        sections = [BgmSection("HOOK_INTRO", "HOLD", "RAMP", 0.5),
                    BgmSection("PRODUCT_BUILD", "YIELD", "RAMP", 0.8)]
        expression = build_bgm_volume_filter(self._segments(sections, {"PRODUCT_BUILD": 2}))
        self.assertIn("if(", expression)
        self.assertIn("t,", expression)
        self.assertTrue(expression.endswith("dB") or expression.endswith(")"))

    def test_an_empty_curve_is_refused(self) -> None:
        with self.assertRaises(AudioExecutorError):
            build_bgm_volume_filter(())

    def test_a_section_without_a_window_is_refused(self) -> None:
        sections = [BgmSection("HOOK_INTRO", "HOLD", "RAMP", 0.5)]
        with self.assertRaises(AudioExecutorError):
            plan_bgm_automation(sections, section_windows={})


class DuckingTests(unittest.TestCase):
    def test_every_non_voice_source_ducks_under_voice(self) -> None:
        rules = plan_ducking(sources=["VO", "BGM", "WATER", "AMBIENCE"])
        self.assertEqual({r.source for r in rules}, {"BGM", "WATER", "AMBIENCE"})
        self.assertTrue(all(r.under == LEADING_SOURCE for r in rules))

    def test_voice_does_not_duck_under_itself(self) -> None:
        rules = plan_ducking(sources=["VO"])
        self.assertEqual(rules, ())

    def test_every_rule_has_a_negative_depth(self) -> None:
        for rule in plan_ducking(sources=["VO", "BGM"]):
            with self.subTest(source=rule.source):
                self.assertLess(rule.depth_db, 0.0)

    def test_no_sources_is_refused(self) -> None:
        with self.assertRaises(AudioExecutorError):
            plan_ducking(sources=[])

    def test_a_malformed_source_is_refused(self) -> None:
        with self.assertRaises(AudioExecutorError):
            plan_ducking(sources=["VO", "bad name"])


class DryShotTests(unittest.TestCase):
    """A dry visual shot never carries water sound."""

    def _plan(self, *, has_water: bool) -> AudioPlan:
        return AudioPlan(
            vo_strategy="CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS",
            water_events=(WaterEvent(shot_id="SHOT_A", has_water_evidence=has_water,
                                     event_state="FLOW" if has_water else "OFF",
                                     mix_role="EVIDENCE" if has_water else "BED"),),
            bgm_structure=BGM_STRUCTURE,
        )

    def test_a_wet_shot_is_not_a_dry_shot(self) -> None:
        self.assertEqual(self._plan(has_water=True).dry_shots, ())

    def test_a_dry_shot_is_reported_as_dry(self) -> None:
        self.assertEqual(self._plan(has_water=False).dry_shots, ("SHOT_A",))

    def test_a_dry_window_is_checked_for_water_energy(self) -> None:
        findings = validate_mix(
            self._plan(has_water=False),
            vo_levels=[WindowLevel("SHOT_A", 0.0, 1.0, -18.0, -6.0)],
            bed_levels=[WindowLevel("SHOT_A", 0.0, 1.0, -20.0, -60.0)],
            loudness=LoudnessReading(-16.0, -1.5, False),
            reference_lufs=-16.0, reference_dbtp=-1.4,
        )
        check = {f.check: f for f in findings}["dry_shots_carry_no_water"]
        self.assertTrue(check.passed)

    def test_water_in_a_dry_window_fails_the_check(self) -> None:
        findings = validate_mix(
            self._plan(has_water=False),
            vo_levels=[WindowLevel("SHOT_A", 0.0, 1.0, -18.0, -6.0)],
            bed_levels=[WindowLevel("SHOT_A", 0.0, 1.0, -20.0, -20.0)],
            loudness=LoudnessReading(-16.0, -1.5, False),
            reference_lufs=-16.0, reference_dbtp=-1.4,
        )
        check = {f.check: f for f in findings}["dry_shots_carry_no_water"]
        self.assertFalse(check.passed)


class MixValidationTests(unittest.TestCase):
    """A mix claim must be a reading, not an assertion."""

    def _plan(self) -> AudioPlan:
        return AudioPlan(
            vo_strategy="CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS",
            water_events=(WaterEvent(shot_id="SHOT_A", has_water_evidence=True,
                                     event_state="FLOW", mix_role="HERO"),),
            bgm_structure=BGM_STRUCTURE,
        )

    def test_voice_leading_the_mix_passes(self) -> None:
        findings = validate_mix(
            self._plan(),
            vo_levels=[WindowLevel("W1", 0.0, 2.0, -18.0, -6.0),
                       WindowLevel("W2", 2.0, 2.0, -20.0, -8.0)],
            bed_levels=[WindowLevel("W1", 0.0, 2.0, -24.0, -10.0),
                        WindowLevel("W2", 2.0, 2.0, -26.0, -12.0)],
            loudness=LoudnessReading(-16.0, -1.5, False),
            reference_lufs=-16.0, reference_dbtp=-1.4,
        )
        self.assertTrue({f.check: f for f in findings}["voice_leads_the_mix"].passed)

    def test_voice_buried_in_the_mix_fails(self) -> None:
        findings = validate_mix(
            self._plan(),
            vo_levels=[WindowLevel("W1", 0.0, 2.0, -30.0, -12.0)],
            bed_levels=[WindowLevel("W1", 0.0, 2.0, -18.0, -6.0)],
            loudness=LoudnessReading(-16.0, -1.5, False),
            reference_lufs=-16.0, reference_dbtp=-1.4,
        )
        check = {f.check: f for f in findings}["voice_leads_the_mix"]
        self.assertFalse(check.passed)
        self.assertIn("dB", check.detail)

    def test_loudness_outside_tolerance_fails(self) -> None:
        findings = validate_mix(
            self._plan(),
            vo_levels=[WindowLevel("W1", 0.0, 2.0, -18.0, -6.0)],
            bed_levels=[WindowLevel("W1", 0.0, 2.0, -24.0, -10.0)],
            loudness=LoudnessReading(-9.0, -1.5, False),
            reference_lufs=-16.0, reference_dbtp=-1.4,
        )
        self.assertFalse({f.check: f for f in findings}["loudness_matches_reference"].passed)

    def test_clipping_fails(self) -> None:
        findings = validate_mix(
            self._plan(),
            vo_levels=[WindowLevel("W1", 0.0, 2.0, -18.0, -6.0)],
            bed_levels=[WindowLevel("W1", 0.0, 2.0, -24.0, -10.0)],
            loudness=LoudnessReading(-16.0, 0.4, True),
            reference_lufs=-16.0, reference_dbtp=-1.4,
        )
        self.assertFalse({f.check: f for f in findings}["true_peak_does_not_clip"].passed)

    def test_every_finding_carries_a_measured_detail(self) -> None:
        findings = validate_mix(
            self._plan(),
            vo_levels=[WindowLevel("W1", 0.0, 2.0, -18.0, -6.0)],
            bed_levels=[WindowLevel("W1", 0.0, 2.0, -24.0, -10.0)],
            loudness=LoudnessReading(-16.0, -1.5, False),
            reference_lufs=-16.0, reference_dbtp=-1.4,
        )
        for finding in findings:
            with self.subTest(check=finding.check):
                self.assertTrue(finding.detail)

    def test_no_windows_is_refused(self) -> None:
        with self.assertRaises(AudioExecutorError):
            validate_mix(self._plan(), vo_levels=[], bed_levels=[],
                         loudness=LoudnessReading(-16.0, -1.5, False),
                         reference_lufs=-16.0, reference_dbtp=-1.4)


@unittest.skipUnless(_has_ffmpeg(), "ffmpeg is required")
class MeasurementTests(unittest.TestCase):
    """Real measurements, on signals this test generates itself."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="audio-exec-")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_duration_is_measured(self) -> None:
        path = _tone(os.path.join(self.tmp, "tone.wav"), seconds=3.0)
        self.assertAlmostEqual(measure_duration(path), 3.0, delta=0.05)

    def test_a_missing_file_is_refused(self) -> None:
        with self.assertRaises(AudioExecutorError):
            measure_duration(os.path.join(self.tmp, "absent.wav"))

    def test_a_window_is_measured(self) -> None:
        path = _tone(os.path.join(self.tmp, "tone.wav"), seconds=4.0, volume=0.5)
        level = measure_window(path, label="W1", start_seconds=0.5,
                               duration_seconds=1.0)
        self.assertGreater(level.max_db, -30.0)
        self.assertFalse(level.is_silent)

    def test_a_genuinely_silent_window_is_reported_as_silent(self) -> None:
        path = os.path.join(self.tmp, "silence.wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "2",
                        path], check=True)
        level = measure_window(path, label="W2", start_seconds=0.5,
                               duration_seconds=1.0)
        self.assertTrue(level.is_silent)
        self.assertLess(level.max_db, -70.0)

    def test_a_window_outside_the_file_is_an_error_not_a_silence(self) -> None:
        """A missing window means the offset or the file is wrong; do not call it quiet."""

        path = _tone(os.path.join(self.tmp, "tone.wav"), seconds=2.0)
        with self.assertRaises(AudioExecutorError) as caught:
            measure_window(path, label="W3", start_seconds=10.0, duration_seconds=1.0)
        self.assertIn("outside the file", str(caught.exception))

    def test_a_non_positive_window_is_refused(self) -> None:
        path = _tone(os.path.join(self.tmp, "tone.wav"), seconds=2.0)
        with self.assertRaises(AudioExecutorError):
            measure_window(path, label="W", start_seconds=0.0, duration_seconds=0.0)

    def test_loudness_and_true_peak_are_measured(self) -> None:
        path = _tone(os.path.join(self.tmp, "tone.wav"), seconds=4.0, volume=0.5)
        reading = measure_loudness(path)
        self.assertLess(reading.integrated_lufs, 0.0)
        self.assertLess(reading.true_peak_dbtp, 0.0)
        self.assertFalse(reading.clipping)

    def test_a_loud_signal_is_reported_as_clipping(self) -> None:
        # the lavfi sine sits near -21 dBFS, so a x16 gain is needed to reach full scale
        path = _tone(os.path.join(self.tmp, "loud.wav"), seconds=2.0, volume=16.0)
        reading = measure_loudness(path)
        self.assertTrue(reading.clipping)
        self.assertGreaterEqual(reading.true_peak_dbtp, 0.0)

    def test_continuity_can_be_proved_against_a_real_take(self) -> None:
        path = _tone(os.path.join(self.tmp, "take.wav"), seconds=6.0)
        cuts = (VoCut("VO1", 0.0, 1.0, 0.0), VoCut("VO2", 3.0, 4.5, 2.0))
        proof = verify_continuous_performance(path, cuts)
        self.assertTrue(proof.is_continuous_performance)
        self.assertAlmostEqual(proof.take_duration, 6.0, delta=0.05)


if __name__ == "__main__":
    unittest.main()
