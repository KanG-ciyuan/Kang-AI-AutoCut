"""Tests for B3-B / B3-C — the KEEP / REVIEW / CORRECT decision.

The cases that matter:

* an all-KEEP run is a success;
* a large statistical difference alone never produces CORRECT;
* the same magnitude of difference leads to different decisions depending on the pair's
  relationship;
* CORRECT is unreachable without a product-protection result that authorises it.
"""

from __future__ import annotations

import unittest

from src.ai_autocut.picture_decision import (
    CORRECT,
    CORRECTION_DIMENSIONS,
    DIRECTIONS_BY_DIMENSION,
    KEEP,
    LARGE_FACTOR,
    MARGINAL_FACTOR,
    OUTCOMES,
    REVIEW,
    CorrectionIntent,
    PictureDecisionError,
    ShotDecision,
    decide_shot,
    summarise,
)
from src.ai_autocut.picture_measurement import (
    SAME_PRODUCT,
    SAME_SCENE,
    SAME_SEMANTIC_UNIT,
    UNRELATED,
    ShotMeasurement,
    compare_shots,
)
from src.ai_autocut.product_protection import (
    PASS,
    REJECT,
    UNAVAILABLE,
    ProductRegion,
    ProtectionResult,
    assess_protection,
)
from src.ai_autocut.product_protection import ProductEvidence

REGION = ProductRegion(0.25, 0.25, 0.5, 0.5, source="supplied")


def _shot(shot_id: str, *, luminance=100.0, saturation=50.0, contrast=200.0,
          sharpness=3.0, cast_u=128.0, cast_v=128.0, confidence="HIGH",
          product=False) -> ShotMeasurement:
    return ShotMeasurement(
        shot_id=shot_id, start_seconds=0.0, duration_seconds=1.0,
        luminance=luminance, cast_u=cast_u, cast_v=cast_v, saturation=saturation,
        contrast=contrast, sharpness=sharpness,
        product_region=REGION if product else None,
        product_luminance=luminance if product else None,
        product_saturation=saturation if product else None,
        product_contrast=contrast if product else None,
        confidence=confidence,
    )


def _protection_pass() -> ProtectionResult:
    return ProtectionResult(shot_id="S02", outcome=PASS, confidence="HIGH", checks=(),
                            reason="every product measure stayed inside tolerance")


def _protection_unavailable() -> ProtectionResult:
    return ProtectionResult(shot_id="S02", outcome=UNAVAILABLE, confidence="LOW",
                            checks=(), reason="no reliable product region was supplied",
                            missing_region=True)


def _protection_reject() -> ProtectionResult:
    return ProtectionResult(shot_id="S02", outcome=REJECT, confidence="HIGH", checks=(),
                            reason="the correction damaged the product")


def _pair(previous, current, tier):
    return compare_shots(previous, current, tier=tier)


class KeepIsFirstClassTests(unittest.TestCase):
    """KEEP is a successful outcome, not a skipped one."""

    def test_the_first_shot_is_kept(self) -> None:
        decision = decide_shot(shot=_shot("S01"), pair=None, contains_product=False,
                               protection=None)
        self.assertEqual(decision.outcome, KEEP)
        self.assertIn("first shot", decision.reason)

    def test_matching_shots_are_kept(self) -> None:
        previous, current = _shot("S01"), _shot("S02")
        decision = decide_shot(shot=current, pair=_pair(previous, current, SAME_SCENE),
                               contains_product=False, protection=None)
        self.assertEqual(decision.outcome, KEEP)

    def test_an_all_keep_run_is_recorded_as_a_success(self) -> None:
        decisions = [
            decide_shot(shot=_shot("S01"), pair=None, contains_product=False,
                        protection=None),
            decide_shot(shot=_shot("S02"),
                        pair=_pair(_shot("S01"), _shot("S02"), SAME_SCENE),
                        contains_product=False, protection=None),
        ]
        summary = summarise(decisions)
        self.assertTrue(summary["all_keep"])
        self.assertEqual(summary["correct"], 0)
        self.assertEqual(summary["shots_decided"], 2)

    def test_unrelated_shots_are_kept_even_when_they_differ_a_lot(self) -> None:
        previous = _shot("S01", luminance=60.0, saturation=20.0)
        current = _shot("S02", luminance=170.0, saturation=90.0)
        decision = decide_shot(shot=current, pair=_pair(previous, current, UNRELATED),
                               contains_product=False, protection=None)
        self.assertEqual(decision.outcome, KEEP)
        self.assertIn(UNRELATED, decision.reason)


class NeverCorrectOnDifferenceAloneTests(unittest.TestCase):
    """R-P2 — a large statistical difference is never sufficient on its own."""

    def test_a_large_difference_between_unrelated_shots_stays_keep(self) -> None:
        previous = _shot("S01", luminance=20.0)
        current = _shot("S02", luminance=200.0)
        decision = decide_shot(shot=current, pair=_pair(previous, current, UNRELATED),
                               contains_product=False, protection=None)
        self.assertNotEqual(decision.outcome, CORRECT)

    def test_a_huge_difference_between_adjacent_shots_becomes_review_not_correct(self) -> None:
        previous = _shot("S01", luminance=10.0)
        current = _shot("S02", luminance=250.0)
        decision = decide_shot(shot=current,
                               pair=_pair(previous, current, SAME_SEMANTIC_UNIT),
                               contains_product=False, protection=None)
        self.assertEqual(decision.outcome, REVIEW)
        self.assertIn("not a conservative match", decision.reason)

    def test_a_marginal_difference_is_kept(self) -> None:
        """benefit ~= risk => KEEP."""

        from src.ai_autocut.picture_measurement import REPORTING_LEVEL
        level = REPORTING_LEVEL["HIGH"]["luminance"]
        previous = _shot("S01")
        current = _shot("S02", luminance=100.0 + level * 1.1)
        decision = decide_shot(shot=current,
                               pair=_pair(previous, current, SAME_SEMANTIC_UNIT),
                               contains_product=False, protection=None)
        self.assertEqual(decision.outcome, KEEP)
        self.assertIn("comparable to the risk", decision.reason)

    def test_the_marginal_and_large_factors_are_ordered(self) -> None:
        self.assertLess(MARGINAL_FACTOR, LARGE_FACTOR)


class RelationshipDrivesDecisionTests(unittest.TestCase):
    """N-3 / N-4 — the same magnitude, different outcomes, because the relationship differs."""

    def test_the_same_difference_decides_differently_by_relationship(self) -> None:
        from src.ai_autocut.picture_measurement import REPORTING_LEVEL
        delta = REPORTING_LEVEL["HIGH"]["luminance"] * 1.8
        previous = _shot("S01")
        current = _shot("S02", luminance=100.0 + delta)

        tight = decide_shot(shot=current,
                            pair=_pair(previous, current, SAME_SEMANTIC_UNIT),
                            contains_product=False, protection=None)
        loose = decide_shot(shot=current, pair=_pair(previous, current, UNRELATED),
                            contains_product=False, protection=None)

        self.assertAlmostEqual(
            _pair(previous, current, SAME_SEMANTIC_UNIT).deltas["luminance"],
            _pair(previous, current, UNRELATED).deltas["luminance"], places=4)
        self.assertEqual(tight.outcome, CORRECT)
        self.assertEqual(loose.outcome, KEEP)

    def test_a_same_product_pair_is_a_correction_candidate(self) -> None:
        from src.ai_autocut.picture_measurement import REPORTING_LEVEL
        delta = REPORTING_LEVEL["MEDIUM"]["luminance"] * 1.8
        previous, current = _shot("S01"), _shot("S02", luminance=100.0 + delta)
        decision = decide_shot(shot=current, pair=_pair(previous, current, SAME_PRODUCT),
                               contains_product=False, protection=None)
        self.assertEqual(decision.outcome, CORRECT)


class ProtectionVetoTests(unittest.TestCase):
    """CORRECT is unreachable without an authorising protection result."""

    def _correctable(self):
        from src.ai_autocut.picture_measurement import REPORTING_LEVEL
        delta = REPORTING_LEVEL["HIGH"]["luminance"] * 1.8
        previous, current = _shot("S01"), _shot("S02", luminance=100.0 + delta)
        return current, _pair(previous, current, SAME_SEMANTIC_UNIT)

    def test_a_product_shot_without_protection_becomes_review(self) -> None:
        current, pair = self._correctable()
        decision = decide_shot(shot=current, pair=pair, contains_product=True,
                               protection=None)
        self.assertEqual(decision.outcome, REVIEW)
        self.assertIn("no product-protection result", decision.reason)

    def test_a_rejected_protection_becomes_review(self) -> None:
        current, pair = self._correctable()
        decision = decide_shot(shot=current, pair=pair, contains_product=True,
                               protection=_protection_reject())
        self.assertEqual(decision.outcome, REVIEW)
        self.assertIn("REJECT", decision.reason)

    def test_unavailable_protection_becomes_review(self) -> None:
        current, pair = self._correctable()
        decision = decide_shot(shot=current, pair=pair, contains_product=True,
                               protection=_protection_unavailable())
        self.assertEqual(decision.outcome, REVIEW)
        self.assertIn("UNAVAILABLE", decision.reason)

    def test_authorised_protection_permits_correct(self) -> None:
        current, pair = self._correctable()
        decision = decide_shot(shot=current, pair=pair, contains_product=True,
                               protection=_protection_pass())
        self.assertEqual(decision.outcome, CORRECT)
        self.assertTrue(decision.protection.may_correct)

    def test_a_correct_decision_cannot_be_built_without_protection(self) -> None:
        with self.assertRaises(PictureDecisionError):
            ShotDecision(shot_id="S", outcome=CORRECT, reason="r", confidence="HIGH",
                         evidence={}, dimension="luminance",
                         intent=CorrectionIntent(target_shot_id="S", reference_shot_id="R",
                                                 dimension="luminance",
                                                 direction="lift_luminance",
                                                 reason="r", bound="minor"))

    def test_a_correct_decision_cannot_be_built_on_a_rejected_gate(self) -> None:
        intent = CorrectionIntent(target_shot_id="S", reference_shot_id="R",
                                  dimension="luminance", direction="lift_luminance",
                                  reason="r", bound="minor")
        with self.assertRaises(PictureDecisionError):
            ShotDecision(shot_id="S", outcome=CORRECT, reason="r", confidence="HIGH",
                         evidence={}, dimension="luminance", intent=intent,
                         protection=_protection_reject())


class ConfidenceTests(unittest.TestCase):
    def test_a_low_confidence_reading_never_corrects(self) -> None:
        from src.ai_autocut.picture_measurement import REPORTING_LEVEL
        delta = REPORTING_LEVEL["HIGH"]["luminance"] * 1.8
        previous = _shot("S01", confidence="LOW")
        current = _shot("S02", luminance=100.0 + delta, confidence="LOW")
        decision = decide_shot(shot=current,
                               pair=_pair(previous, current, SAME_SEMANTIC_UNIT),
                               contains_product=False, protection=None)
        self.assertEqual(decision.outcome, KEEP)
        self.assertIn("confidence is too low", decision.reason)


class IntentTests(unittest.TestCase):
    """The intent is semantic. It carries no Resolve parameter value."""

    def test_a_correct_decision_carries_a_semantic_intent(self) -> None:
        from src.ai_autocut.picture_measurement import REPORTING_LEVEL
        delta = REPORTING_LEVEL["HIGH"]["luminance"] * 1.8
        previous, current = _shot("S01"), _shot("S02", luminance=100.0 + delta)
        decision = decide_shot(shot=current,
                               pair=_pair(previous, current, SAME_SEMANTIC_UNIT),
                               contains_product=False, protection=None)
        self.assertIsNotNone(decision.intent)
        self.assertEqual(decision.intent.dimension, "luminance")
        self.assertEqual(decision.intent.direction, "lift_luminance")
        self.assertEqual(decision.intent.reference_shot_id, "S01")

    def test_an_intent_carries_no_numeric_parameter(self) -> None:
        intent = CorrectionIntent(target_shot_id="S", reference_shot_id="R",
                                  dimension="cast", direction="reduce_warm_cast",
                                  reason="r", bound="minor")
        payload = intent.as_dict()
        for field in ("slope", "offset", "power", "cdl", "value", "amount", "gain"):
            with self.subTest(field=field):
                self.assertNotIn(field, payload)

    def test_an_intent_addresses_one_dimension(self) -> None:
        intent = CorrectionIntent(target_shot_id="S", reference_shot_id="R",
                                  dimension="luminance", direction="lift_luminance",
                                  reason="r", bound="minor")
        self.assertFalse(intent.touches_multiple_dimensions)

    def test_a_negative_delta_selects_the_opposite_direction(self) -> None:
        from src.ai_autocut.picture_measurement import REPORTING_LEVEL
        delta = REPORTING_LEVEL["HIGH"]["luminance"] * 1.8
        previous, current = _shot("S01", luminance=100.0 + delta), _shot("S02")
        decision = decide_shot(shot=current,
                               pair=_pair(previous, current, SAME_SEMANTIC_UNIT),
                               contains_product=False, protection=None)
        self.assertEqual(decision.intent.direction, "lower_luminance")

    def test_a_shot_cannot_be_its_own_reference(self) -> None:
        with self.assertRaises(PictureDecisionError):
            CorrectionIntent(target_shot_id="S", reference_shot_id="S",
                             dimension="luminance", direction="lift_luminance",
                             reason="r", bound="minor")

    def test_an_unknown_dimension_is_refused(self) -> None:
        with self.assertRaises(PictureDecisionError):
            CorrectionIntent(target_shot_id="S", reference_shot_id="R",
                             dimension="vibes", direction="lift_luminance",
                             reason="r", bound="minor")

    def test_a_direction_from_the_wrong_dimension_is_refused(self) -> None:
        with self.assertRaises(PictureDecisionError):
            CorrectionIntent(target_shot_id="S", reference_shot_id="R",
                             dimension="luminance", direction="reduce_warm_cast",
                             reason="r", bound="minor")

    def test_an_intent_must_state_a_reason_and_a_bound(self) -> None:
        for field in ("reason", "bound"):
            with self.subTest(field=field):
                kwargs = dict(target_shot_id="S", reference_shot_id="R",
                              dimension="luminance", direction="lift_luminance",
                              reason="r", bound="minor")
                kwargs[field] = "  "
                with self.assertRaises(PictureDecisionError):
                    CorrectionIntent(**kwargs)

    def test_every_dimension_has_two_directions(self) -> None:
        for dimension in CORRECTION_DIMENSIONS:
            with self.subTest(dimension=dimension):
                self.assertEqual(len(DIRECTIONS_BY_DIMENSION[dimension]), 2)


class OutcomeTests(unittest.TestCase):
    def test_the_outcomes_are_exactly_three(self) -> None:
        self.assertEqual(set(OUTCOMES), {KEEP, REVIEW, CORRECT})

    def test_review_is_reachable_and_is_not_a_failure(self) -> None:
        previous = _shot("S01", luminance=10.0)
        current = _shot("S02", luminance=250.0)
        decision = decide_shot(shot=current,
                               pair=_pair(previous, current, SAME_SEMANTIC_UNIT),
                               contains_product=False, protection=None)
        self.assertEqual(decision.outcome, REVIEW)
        self.assertFalse(decision.is_correct)

    def test_an_unknown_outcome_is_refused(self) -> None:
        with self.assertRaises(PictureDecisionError):
            ShotDecision(shot_id="S", outcome="MAYBE", reason="r", confidence="HIGH",
                         evidence={})

    def test_the_summary_counts_every_outcome(self) -> None:
        decisions = [
            decide_shot(shot=_shot("S01"), pair=None, contains_product=False,
                        protection=None),
        ]
        summary = summarise(decisions)
        self.assertEqual(summary["keep"], 1)
        self.assertEqual(summary["review"], 0)
        self.assertEqual(summary["correct"], 0)

    def test_an_empty_summary_is_refused(self) -> None:
        with self.assertRaises(PictureDecisionError):
            summarise([])

    def test_every_decision_carries_evidence(self) -> None:
        decision = decide_shot(shot=_shot("S01"), pair=None, contains_product=False,
                               protection=None)
        self.assertIn("measurement_confidence", decision.evidence)


class NoCreativeGradeTests(unittest.TestCase):
    """R-P10 — no LUT, no look, no mood anywhere in the decision layer."""

    def test_the_module_contains_no_grade_concept(self) -> None:
        import re
        import src.ai_autocut.picture_decision as module

        source = open(module.__file__, encoding="utf-8").read()
        code = re.sub(r'""".*?"""', "", source, flags=re.S)
        for forbidden in ("lut", "film_emulation", "teal", "orange", "vignette",
                          "bloom", "glow", "mood", "look_preset", "grade_preset",
                          "creative_grade"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code.lower())


if __name__ == "__main__":
    unittest.main()
