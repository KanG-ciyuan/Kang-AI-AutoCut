"""Tests for spoken duration validation.

The copy used here is neutral and invented. The Filter First Job's closing block appears
only in the job-side regression, never in this file, because production logic must not be
shaped by one job's strings.
"""

from __future__ import annotations

import sys
import unittest

from src.ai_autocut.spoken_duration import (
    CONFIDENCES,
    DEFAULT_PAUSE_MODEL,
    GLOBAL_FALLBACK_WORDS_PER_SECOND,
    LANGUAGE_DEFAULT_WORDS_PER_SECOND,
    PauseModel,
    RATE_SOURCES,
    RISKS,
    SAFE_MAX_RATIO,
    TIGHT_MAX_RATIO,
    RateObservation,
    SpeakingRate,
    SpokenDurationError,
    WindowCheck,
    check_window,
    count_words,
    estimate_line,
    fits,
    recommended_action_for,
    resolve_rate,
)

#: Neutral copy: a short simple line, a near-window line, and a deliberately long one.
SHORT_LINE = "Pasang di ujung keran"
NEAR_LINE = "Bilas sayur buah sampai cuci piring jadi lebih praktis dipakai"
LONG_LINE = ("Bilas sayur buah sampai cuci piring jadi lebih praktis dipakai setiap hari, "
             "dan sekarang harganya sedang lebih ringan untuk dicoba")


def rate(words_per_second: float = 2.5, source: str = "MEASURED_SAME_VOICE") -> SpeakingRate:
    confidence = {"MEASURED_SAME_VOICE": "HIGH", "MEASURED_SAME_LANGUAGE": "MEDIUM",
                  "LANGUAGE_DEFAULT": "LOW", "FALLBACK_ESTIMATE": "LOW"}[source]
    return SpeakingRate(words_per_second=words_per_second, language="id",
                        rate_source=source, confidence=confidence)


class RiskBandTests(unittest.TestCase):
    """SAFE / TIGHT / OVERFLOW, and the boundaries between them."""

    def test_safe_when_copy_fits_comfortably(self) -> None:
        check = check_window([("L1", SHORT_LINE)], available_window=6.0, rate=rate())
        self.assertEqual(check.risk, "SAFE")
        self.assertLess(check.ratio, SAFE_MAX_RATIO)
        self.assertTrue(fits(check))

    def test_tight_when_copy_is_near_the_window(self) -> None:
        probe = check_window([("L1", NEAR_LINE)], available_window=6.0, rate=rate())
        check = check_window([("L1", NEAR_LINE)],
                             available_window=probe.estimated_spoken_duration / 0.95,
                             rate=rate())
        self.assertEqual(check.risk, "TIGHT")
        self.assertGreater(check.ratio, SAFE_MAX_RATIO)
        self.assertLessEqual(check.ratio, TIGHT_MAX_RATIO)
        self.assertTrue(fits(check))

    def test_overflow_when_normal_pace_does_not_fit(self) -> None:
        check = check_window([("L1", LONG_LINE)], available_window=4.0, rate=rate())
        self.assertEqual(check.risk, "OVERFLOW")
        self.assertGreater(check.ratio, TIGHT_MAX_RATIO)
        self.assertFalse(fits(check))

    def test_risk_is_always_from_the_declared_set(self) -> None:
        for window in (0.5, 3.0, 8.0, 20.0):
            with self.subTest(window=window):
                self.assertIn(
                    check_window([("L1", NEAR_LINE)], available_window=window,
                                 rate=rate()).risk, RISKS)

    def test_bands_are_ordered(self) -> None:
        self.assertLess(SAFE_MAX_RATIO, TIGHT_MAX_RATIO)

    def test_recommended_action_differs_by_risk(self) -> None:
        actions = {recommended_action_for(r) for r in RISKS}
        self.assertEqual(len(actions), 3)


class OutputShapeTests(unittest.TestCase):
    """Every field the specification requires is present."""

    def test_check_carries_every_required_field(self) -> None:
        check = check_window([("L1", NEAR_LINE)], available_window=5.0, rate=rate())
        for field in ("available_window", "estimated_spoken_duration", "ratio", "risk",
                      "recommended_action", "rate_source", "pause_model"):
            with self.subTest(field=field):
                self.assertIsNotNone(getattr(check, field))
        self.assertIn(check.rate_source, RATE_SOURCES)
        self.assertIn(check.confidence, CONFIDENCES)
        self.assertGreater(check.uncertainty_margin, 0)

    def test_available_window_is_reported_as_given(self) -> None:
        check = check_window([("L1", SHORT_LINE)], available_window=7.25, rate=rate())
        self.assertAlmostEqual(check.available_window, 7.25, places=4)

    def test_per_line_estimates_are_reported(self) -> None:
        check = check_window([("L1", SHORT_LINE), ("L2", NEAR_LINE)],
                             available_window=8.0, rate=rate())
        self.assertEqual([e.line_id for e in check.lines], ["L1", "L2"])
        self.assertTrue(all(e.words > 0 for e in check.lines))

    def test_estimated_duration_includes_speech_and_pauses(self) -> None:
        check = check_window([("L1", NEAR_LINE)], available_window=8.0, rate=rate())
        line = check.lines[0]
        self.assertAlmostEqual(line.estimated_seconds,
                               line.speech_seconds + line.pause_seconds, places=3)

    def test_a_required_window_with_no_lines_is_refused(self) -> None:
        with self.assertRaises(SpokenDurationError):
            check_window([], available_window=4.0, rate=rate(), required=True)

    def test_an_optional_window_with_no_lines_is_not_a_warning(self) -> None:
        check = check_window([], available_window=4.0, rate=rate(), required=False)
        self.assertEqual(check.risk, "SAFE")
        self.assertEqual(check.estimated_spoken_duration, 0.0)
        self.assertIn("no copy is required", check.recommended_action)


class ShortLineTests(unittest.TestCase):
    """The mirror of Batch 1's withdrawn floor: short is not wrong."""

    def test_a_short_line_in_a_wide_window_is_safe(self) -> None:
        check = check_window([("L1", "Halo")], available_window=10.0, rate=rate())
        self.assertEqual(check.risk, "SAFE")

    def test_a_short_line_is_not_flagged_for_being_short(self) -> None:
        one_word = check_window([("L1", "Ya")], available_window=5.0, rate=rate())
        self.assertIn(one_word.risk, ("SAFE", "TIGHT"))

    def test_an_empty_window_is_not_treated_as_a_requirement_to_speak(self) -> None:
        check = check_window([], available_window=3.0, rate=rate(), required=False)
        self.assertFalse(check.lines)
        self.assertEqual(check.ratio, 0.0)


class CopyIsNeverMutatedTests(unittest.TestCase):
    """The validator can warn; it cannot rewrite copy."""

    def test_line_text_is_untouched(self) -> None:
        copy_blocks = [SHORT_LINE, NEAR_LINE, LONG_LINE]
        snapshot = list(copy_blocks)
        for text in copy_blocks:
            check_window([("L1", text)], available_window=5.0, rate=rate())
        self.assertEqual(copy_blocks, snapshot)

    def test_estimate_line_returns_no_text(self) -> None:
        estimate = estimate_line(NEAR_LINE, line_id="L1", rate=rate())
        self.assertFalse(hasattr(estimate, "text"))
        self.assertFalse(hasattr(estimate, "rewritten"))

    def test_no_exported_callable_suggests_rewriting(self) -> None:
        import src.ai_autocut.spoken_duration as module

        for name in dir(module):
            lowered = name.lower()
            self.assertNotIn("rewrite", lowered)
            self.assertNotIn("shorten", lowered)
            self.assertNotIn("trim_copy", lowered)

    def test_counts_do_not_change_the_input(self) -> None:
        original = NEAR_LINE
        count_words(original)
        estimate_line(original, line_id="L1", rate=rate())
        self.assertEqual(NEAR_LINE, original)


class NoNetworkTests(unittest.TestCase):
    """No paid or network generation may happen during validation."""

    def test_module_imports_nothing_network_capable(self) -> None:
        import src.ai_autocut.spoken_duration as module

        source = open(module.__file__, encoding="utf-8").read()
        for forbidden in ("urllib", "requests", "http.client", "socket",
                          "subprocess", "httpx", "aiohttp"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_validation_completes_without_any_network_module_loaded(self) -> None:
        before = set(sys.modules)
        check_window([("L1", NEAR_LINE)], available_window=5.0, rate=rate())
        newly_loaded = set(sys.modules) - before
        for name in ("socket", "ssl", "http.client", "urllib.request"):
            with self.subTest(module=name):
                self.assertNotIn(name, newly_loaded)

    def test_no_provider_is_named_in_the_module(self) -> None:
        import src.ai_autocut.spoken_duration as module

        source = open(module.__file__, encoding="utf-8").read().lower()
        for provider in ("doubao", "minimax", "openai", "elevenlabs", "volcengine"):
            with self.subTest(provider=provider):
                self.assertNotIn(provider, source)


class RateSourceFallbackTests(unittest.TestCase):
    """The fallback hierarchy, best evidence first."""

    def test_same_voice_measurement_wins(self) -> None:
        resolved = resolve_rate("id", voice="narrator-a", observations=[
            RateObservation("id", 2.6, voice="narrator-a", samples=2, evidence="job A take"),
            RateObservation("id", 3.1, voice="narrator-b", samples=5, evidence="job B take"),
        ])
        self.assertEqual(resolved.rate_source, "MEASURED_SAME_VOICE")
        self.assertAlmostEqual(resolved.words_per_second, 2.6, places=3)
        self.assertEqual(resolved.voice, "narrator-a")

    def test_same_language_is_used_when_the_voice_is_unknown(self) -> None:
        resolved = resolve_rate("id", observations=[
            RateObservation("id", 2.6, voice="narrator-a", evidence="job A take"),
        ])
        self.assertEqual(resolved.rate_source, "MEASURED_SAME_LANGUAGE")

    def test_another_language_is_not_borrowed(self) -> None:
        resolved = resolve_rate("id", observations=[
            RateObservation("en", 3.9, voice="someone", evidence="english job"),
        ])
        self.assertNotIn(resolved.rate_source, ("MEASURED_SAME_VOICE",
                                                "MEASURED_SAME_LANGUAGE"))

    def test_language_default_when_nothing_is_measured(self) -> None:
        for language in LANGUAGE_DEFAULT_WORDS_PER_SECOND:
            with self.subTest(language=language):
                resolved = resolve_rate(language, observations=[])
                self.assertEqual(resolved.rate_source, "LANGUAGE_DEFAULT")
                self.assertEqual(resolved.confidence, "LOW")

    def test_unknown_language_falls_back_and_says_so(self) -> None:
        resolved = resolve_rate("xx", observations=[])
        self.assertEqual(resolved.rate_source, "FALLBACK_ESTIMATE")
        self.assertAlmostEqual(resolved.words_per_second,
                               GLOBAL_FALLBACK_WORDS_PER_SECOND, places=3)

    def test_rate_source_ordering_is_declared(self) -> None:
        self.assertEqual(RATE_SOURCES[0], "MEASURED_SAME_VOICE")
        self.assertEqual(RATE_SOURCES[-1], "FALLBACK_ESTIMATE")

    def test_language_is_required(self) -> None:
        with self.assertRaises(SpokenDurationError):
            resolve_rate("")

    def test_more_samples_raise_confidence(self) -> None:
        thin = resolve_rate("id", voice="v", observations=[
            RateObservation("id", 2.5, voice="v", samples=1)])
        thick = resolve_rate("id", voice="v", observations=[
            RateObservation("id", 2.5, voice="v", samples=4)])
        self.assertEqual(thin.confidence, "MEDIUM")
        self.assertEqual(thick.confidence, "HIGH")

    def test_observations_are_pooled_by_sample_count(self) -> None:
        resolved = resolve_rate("id", voice="v", observations=[
            RateObservation("id", 2.0, voice="v", samples=1),
            RateObservation("id", 3.0, voice="v", samples=3),
        ])
        self.assertAlmostEqual(resolved.words_per_second, 2.75, places=3)

    def test_a_bad_observation_is_refused(self) -> None:
        with self.assertRaises(SpokenDurationError):
            RateObservation("id", 0.0)
        with self.assertRaises(SpokenDurationError):
            RateObservation("id", 2.5, samples=0)


class UncertaintyTests(unittest.TestCase):
    """A weaker rate must widen the estimate, not quietly report the same number."""

    def test_weaker_evidence_widens_the_estimate(self) -> None:
        estimates = [
            check_window([("L1", NEAR_LINE)], available_window=8.0,
                         rate=rate(2.5, source)).estimated_spoken_duration
            for source in RATE_SOURCES
        ]
        self.assertEqual(estimates, sorted(estimates))
        self.assertLess(estimates[0], estimates[-1])

    def test_a_measured_rate_adds_no_margin(self) -> None:
        check = check_window([("L1", NEAR_LINE)], available_window=8.0,
                             rate=rate(2.5, "MEASURED_SAME_VOICE"))
        self.assertEqual(check.uncertainty_margin, 1.0)
        self.assertEqual(check.note, "")

    def test_a_fallback_rate_is_explained_in_the_note(self) -> None:
        check = check_window([("L1", NEAR_LINE)], available_window=8.0,
                             rate=rate(2.2, "FALLBACK_ESTIMATE"))
        self.assertIn("FALLBACK_ESTIMATE", check.note)
        self.assertGreater(check.uncertainty_margin, 1.0)

    def test_a_weaker_rate_can_turn_safe_into_tight_or_worse(self) -> None:
        strong = check_window([("L1", NEAR_LINE)], available_window=6.0,
                              rate=rate(2.5, "MEASURED_SAME_VOICE"))
        weak = check_window([("L1", NEAR_LINE)], available_window=6.0,
                            rate=rate(2.5, "FALLBACK_ESTIMATE"))
        self.assertGreater(weak.ratio, strong.ratio)
        self.assertLess(RISKS.index(strong.risk), RISKS.index(weak.risk) + 1)


class PauseModelTests(unittest.TestCase):
    """Punctuation carries time, and the model is explicit."""

    def test_punctuation_adds_time(self) -> None:
        plain = estimate_line("Bilas sayur buah sampai cuci piring", line_id="L",
                              rate=rate()).estimated_seconds
        punctuated = estimate_line(
            "Bilas sayur, buah, sampai cuci piring.", line_id="L", rate=rate()
        ).estimated_seconds
        self.assertGreater(punctuated, plain)

    def test_a_sentence_break_costs_more_than_a_clause_break(self) -> None:
        clause = estimate_line("Satu, dua tiga", line_id="L", rate=rate()).pause_seconds
        sentence = estimate_line("Satu. Dua tiga", line_id="L", rate=rate()).pause_seconds
        self.assertGreater(sentence, clause)

    def test_the_model_is_named_in_the_output(self) -> None:
        check = check_window([("L1", NEAR_LINE)], available_window=6.0, rate=rate())
        self.assertEqual(check.pause_model, DEFAULT_PAUSE_MODEL.name)

    def test_a_custom_model_changes_the_estimate(self) -> None:
        punctuated = "Bilas sayur, buah, sampai cuci piring, jadi lebih praktis dipakai."
        tight = PauseModel(name="tight", clause_seconds=0.0, sentence_seconds=0.0,
                           between_lines_seconds=0.0)
        generous = PauseModel(name="generous", clause_seconds=0.6, sentence_seconds=0.9,
                              between_lines_seconds=0.4)
        a = check_window([("L1", punctuated)], available_window=8.0, rate=rate(),
                         pause_model=tight).estimated_spoken_duration
        b = check_window([("L1", punctuated)], available_window=8.0, rate=rate(),
                         pause_model=generous).estimated_spoken_duration
        self.assertLess(a, b)

    def test_a_negative_pause_is_refused(self) -> None:
        with self.assertRaises(SpokenDurationError):
            PauseModel(clause_seconds=-0.1)

    def test_between_line_gaps_are_counted(self) -> None:
        one = check_window([("L1", NEAR_LINE)], available_window=20.0, rate=rate())
        two = check_window([("L1", NEAR_LINE), ("L2", NEAR_LINE)],
                           available_window=20.0, rate=rate())
        self.assertGreater(two.estimated_spoken_duration,
                           one.estimated_spoken_duration * 2 - 1e-6)

    def test_a_blank_line_is_refused(self) -> None:
        with self.assertRaises(SpokenDurationError):
            estimate_line("   ", line_id="L", rate=rate())


class InvalidInputTests(unittest.TestCase):
    def test_a_non_positive_window_is_refused(self) -> None:
        for window in (0.0, -1.0):
            with self.subTest(window=window):
                with self.assertRaises(SpokenDurationError):
                    check_window([("L1", SHORT_LINE)], available_window=window,
                                 rate=rate())

    def test_a_non_positive_rate_is_refused(self) -> None:
        with self.assertRaises(SpokenDurationError):
            SpeakingRate(words_per_second=0.0, language="id",
                         rate_source="LANGUAGE_DEFAULT", confidence="LOW")

    def test_an_unknown_rate_source_is_refused(self) -> None:
        with self.assertRaises(SpokenDurationError):
            SpeakingRate(words_per_second=2.5, language="id",
                         rate_source="GUESSED", confidence="LOW")

    def test_a_window_check_with_a_bad_risk_is_refused(self) -> None:
        with self.assertRaises(SpokenDurationError):
            WindowCheck(available_window=5.0, estimated_spoken_duration=5.0, ratio=1.0,
                        risk="MAYBE", recommended_action="", rate_source="LANGUAGE_DEFAULT",
                        pause_model="x", confidence="LOW", uncertainty_margin=1.0, lines=())


if __name__ == "__main__":
    unittest.main()
