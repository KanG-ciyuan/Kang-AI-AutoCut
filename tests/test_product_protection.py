"""Tests for B3-D product protection — the hard gate.

The cases that matter are the refusals: a correction that improves the background and damages
the product must be rejected, and a missing product region must never become a silent pass.
"""

from __future__ import annotations

import unittest

from src.ai_autocut.picture_measurement import ProductRegion, ShotMeasurement
from src.ai_autocut.product_protection import (
    DEFAULT_TOLERANCE,
    OUTCOMES,
    PASS,
    REJECT,
    UNAVAILABLE,
    ProductEvidence,
    ProductProtectionError,
    ProtectionTolerance,
    assess_protection,
    summarise,
)


def _shot(shot_id: str, *, luminance=None, saturation=None, contrast=None,
          cast_u=128.0, cast_v=128.0, confidence="HIGH") -> ShotMeasurement:
    return ShotMeasurement(
        shot_id=shot_id, start_seconds=0.0, duration_seconds=1.0,
        luminance=luminance or 100.0, cast_u=cast_u, cast_v=cast_v,
        saturation=50.0, contrast=200.0, sharpness=3.0,
        product_region=None,
        product_luminance=luminance, product_saturation=saturation,
        product_contrast=contrast, confidence=confidence,
    )


REGION = ProductRegion(0.25, 0.25, 0.5, 0.5, source="supplied")


def _evidence(*, before, after=None, contains_product=True, region=REGION) -> ProductEvidence:
    return ProductEvidence(shot_id="S01", contains_product=contains_product, region=region,
                           before=before, after=after)


class ScenarioTests(unittest.TestCase):
    """The decision table, in priority order."""

    def test_a_shot_with_no_product_passes_and_says_why(self) -> None:
        result = assess_protection(_evidence(before=_shot("S", luminance=100.0),
                                             contains_product=False, region=None))
        self.assertEqual(result.outcome, PASS)
        self.assertTrue(result.may_correct)
        self.assertIn("no product", result.reason)

    def test_product_without_a_region_is_unavailable_not_a_pass(self) -> None:
        result = assess_protection(_evidence(before=_shot("S", luminance=100.0),
                                             region=None))
        self.assertEqual(result.outcome, UNAVAILABLE)
        self.assertFalse(result.may_correct)
        self.assertTrue(result.missing_region)
        self.assertEqual(result.confidence, "LOW")

    def test_the_missing_region_reason_is_explicit_evidence(self) -> None:
        result = assess_protection(_evidence(before=_shot("S"), region=None))
        self.assertIn("no reliable product region", result.reason)
        self.assertIn("may not proceed", result.reason)

    def test_a_region_without_a_correction_cannot_claim_a_pass(self) -> None:
        result = assess_protection(_evidence(before=_shot("S"), after=None))
        self.assertEqual(result.outcome, UNAVAILABLE)
        self.assertFalse(result.may_correct)

    def test_a_gentle_correction_that_keeps_the_product_passes(self) -> None:
        result = assess_protection(_evidence(
            before=_shot("S", luminance=100.0, saturation=50.0, contrast=200.0),
            after=_shot("S", luminance=102.0, saturation=51.0, contrast=195.0),
        ))
        self.assertEqual(result.outcome, PASS)
        self.assertTrue(result.may_correct)

    def test_a_correction_that_darkens_the_product_is_rejected(self) -> None:
        result = assess_protection(_evidence(
            before=_shot("S", luminance=100.0, saturation=50.0, contrast=200.0),
            after=_shot("S", luminance=80.0, saturation=50.0, contrast=200.0),
        ))
        self.assertEqual(result.outcome, REJECT)
        self.assertFalse(result.may_correct)

    def test_a_correction_that_washes_out_the_product_is_rejected(self) -> None:
        result = assess_protection(_evidence(
            before=_shot("S", luminance=100.0, saturation=50.0, contrast=200.0),
            after=_shot("S", luminance=100.0, saturation=20.0, contrast=200.0),
        ))
        self.assertEqual(result.outcome, REJECT)

    def test_a_correction_that_shifts_the_product_colour_is_rejected(self) -> None:
        before = _shot("S", luminance=100.0, saturation=50.0, contrast=200.0)
        after = _shot("S", luminance=100.0, saturation=50.0, contrast=200.0,
                      cast_u=150.0, cast_v=110.0)
        result = assess_protection(_evidence(before=before, after=after))
        self.assertEqual(result.outcome, REJECT)
        self.assertIn("product_colour_drift", [c.name for c in result.failed_checks])

    def test_a_correction_that_destroys_product_detail_is_rejected(self) -> None:
        result = assess_protection(_evidence(
            before=_shot("S", luminance=100.0, saturation=50.0, contrast=200.0),
            after=_shot("S", luminance=100.0, saturation=50.0, contrast=60.0),
        ))
        self.assertEqual(result.outcome, REJECT)
        self.assertIn("product_recognisability_retention",
                      [c.name for c in result.failed_checks])

    def test_the_rejection_reason_states_the_priority(self) -> None:
        result = assess_protection(_evidence(
            before=_shot("S", luminance=100.0, saturation=50.0, contrast=200.0),
            after=_shot("S", luminance=70.0, saturation=50.0, contrast=200.0),
        ))
        self.assertIn("damaged the product", result.reason)
        self.assertIn("does not outrank", result.reason)


class PriorityTests(unittest.TestCase):
    """PRODUCT AUTHENTICITY > PERFECT BACKGROUND MATCH, enforced."""

    def test_the_hard_gate_verdict_is_may_correct(self) -> None:
        rejecting = assess_protection(_evidence(
            before=_shot("S", luminance=100.0, saturation=50.0, contrast=200.0),
            after=_shot("S", luminance=60.0, saturation=50.0, contrast=200.0),
        ))
        self.assertFalse(rejecting.may_correct)

    def test_an_unavailable_region_can_never_authorise_a_correction(self) -> None:
        result = assess_protection(_evidence(before=_shot("S"), region=None))
        self.assertFalse(result.may_correct)

    def test_only_pass_authorises(self) -> None:
        for before, after, region, product, expected in (
            (_shot("S", luminance=100.0, saturation=50.0, contrast=200.0), None,
             REGION, False, PASS),
            (_shot("S", luminance=100.0, saturation=50.0, contrast=200.0),
             _shot("S", luminance=99.0, saturation=50.0, contrast=200.0),
             REGION, True, PASS),
            (_shot("S", luminance=100.0, saturation=50.0, contrast=200.0),
             _shot("S", luminance=50.0, saturation=50.0, contrast=200.0),
             REGION, True, REJECT),
            (_shot("S", luminance=100.0, saturation=50.0, contrast=200.0), None,
             None, True, UNAVAILABLE),
        ):
            with self.subTest(expected=expected):
                result = assess_protection(_evidence(before=before, after=after,
                                                     region=region,
                                                     contains_product=product))
                self.assertEqual(result.outcome, expected)
                self.assertEqual(result.may_correct, expected == PASS)


class StructuralRefusalTests(unittest.TestCase):
    """The gate refuses to be given something it cannot assess."""

    def test_a_correction_with_no_region_is_refused_at_construction(self) -> None:
        with self.assertRaises(ProductProtectionError):
            ProductEvidence(shot_id="S", contains_product=True, region=None,
                            before=_shot("S"), after=_shot("S"))

    def test_evidence_needs_a_shot_id(self) -> None:
        with self.assertRaises(ProductProtectionError):
            ProductEvidence(shot_id="", contains_product=False, region=None,
                            before=_shot("S"))

    def test_an_unknown_outcome_is_refused(self) -> None:
        from src.ai_autocut.product_protection import ProtectionResult
        with self.assertRaises(ProductProtectionError):
            ProtectionResult(shot_id="S", outcome="PROBABLY_FINE", confidence="HIGH",
                             checks=(), reason="r")

    def test_a_non_positive_tolerance_is_refused(self) -> None:
        for field in ("colour", "luminance", "saturation"):
            with self.subTest(field=field):
                with self.assertRaises(ProductProtectionError):
                    ProtectionTolerance(**{field: 0.0})

    def test_an_impossible_contrast_retention_is_refused(self) -> None:
        for value in (0.0, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(ProductProtectionError):
                    ProtectionTolerance(contrast_retention=value)


class ToleranceIntegrityTests(unittest.TestCase):
    """A tolerance may not be widened to let a correction through."""

    def test_the_default_tolerance_is_positive_and_finite(self) -> None:
        self.assertGreater(DEFAULT_TOLERANCE.colour, 0)
        self.assertGreater(DEFAULT_TOLERANCE.luminance, 0)
        self.assertGreater(DEFAULT_TOLERANCE.saturation, 0)
        self.assertLessEqual(DEFAULT_TOLERANCE.contrast_retention, 1.0)

    def test_a_stricter_tolerance_can_reject_what_a_looser_one_allows(self) -> None:
        before = _shot("S", luminance=100.0, saturation=50.0, contrast=200.0)
        after = _shot("S", luminance=105.0, saturation=50.0, contrast=200.0)
        strict = assess_protection(_evidence(before=before, after=after),
                                   tolerance=ProtectionTolerance(luminance=2.0))
        loose = assess_protection(_evidence(before=before, after=after),
                                  tolerance=ProtectionTolerance(luminance=12.0))
        self.assertEqual(strict.outcome, REJECT)
        self.assertEqual(loose.outcome, PASS)

    def test_protection_never_widens_its_own_tolerance(self) -> None:
        """The module must not contain logic that relaxes a tolerance on failure."""

        import re
        import src.ai_autocut.product_protection as module

        source = open(module.__file__, encoding="utf-8").read()
        code = re.sub(r'""".*?"""', "", source, flags=re.S)
        for forbidden in ("tolerance *=", "tolerance +=", "widen", "relax",
                          "tolerance_registry"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)


class SerialisationTests(unittest.TestCase):
    def test_a_result_serialises_with_its_checks(self) -> None:
        result = assess_protection(_evidence(
            before=_shot("S", luminance=100.0, saturation=50.0, contrast=200.0),
            after=_shot("S", luminance=99.0, saturation=50.0, contrast=200.0),
        ))
        payload = result.as_dict()
        self.assertEqual(payload["outcome"], PASS)
        self.assertTrue(payload["may_correct"])
        self.assertEqual(len(payload["checks"]), 4)

    def test_every_check_reports_a_measurement_and_a_limit(self) -> None:
        result = assess_protection(_evidence(
            before=_shot("S", luminance=100.0, saturation=50.0, contrast=200.0),
            after=_shot("S", luminance=99.0, saturation=50.0, contrast=200.0),
        ))
        for check in result.checks:
            with self.subTest(check=check.name):
                self.assertTrue(check.detail)
                self.assertIsInstance(check.measured, float)
                self.assertIsInstance(check.allowed, float)

    def test_the_summary_records_refusals(self) -> None:
        results = [
            assess_protection(_evidence(before=_shot("A", luminance=100.0,
                                                     saturation=50.0, contrast=200.0),
                                        after=_shot("A", luminance=99.0, saturation=50.0,
                                                    contrast=200.0))),
            assess_protection(_evidence(before=_shot("B", luminance=100.0,
                                                     saturation=50.0, contrast=200.0),
                                        after=_shot("B", luminance=50.0, saturation=50.0,
                                                    contrast=200.0))),
            assess_protection(_evidence(before=_shot("C"), region=None)),
        ]
        summary = summarise(results)
        self.assertEqual(summary["passed"], 1)
        self.assertEqual(summary["rejected"], 1)
        self.assertEqual(summary["unavailable"], 1)
        self.assertEqual(summary["missing_region"], ["S01"])
        self.assertEqual(summary["may_correct"], ["S01"])

    def test_an_empty_summary_is_refused(self) -> None:
        with self.assertRaises(ProductProtectionError):
            summarise([])

    def test_outcomes_are_the_declared_set(self) -> None:
        self.assertEqual(set(OUTCOMES), {PASS, REJECT, UNAVAILABLE})


if __name__ == "__main__":
    unittest.main()
