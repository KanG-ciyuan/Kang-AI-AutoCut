"""Tests for the three added review dimensions and Repair Scope Lock.

The pre-existing review tests live in ``tests/test_review.py`` and still pass; this file
covers only what the extension introduced.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.ai_autocut.review import (
    DIMENSION_LAYERS,
    REPAIR_LAYERS,
    REVIEWER_DIMENSIONS,
    Finding,
    RepairPlan,
    Review,
    ReviewContractError,
    build_targeted_repair,
    deterministic_finding,
    layers_for_repair,
    verdict_rank,
)

SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "review" / "review.v0.schema.json"

ADDED = ("comprehension", "typography_quality", "audio_hierarchy")
REJECTED = ("fragmentation", "product_authenticity", "ending_closure")


def full_review(**overrides: str) -> Review:
    findings = tuple(
        Finding(dimension, overrides.get(dimension, "PASS"),
                f"judged {dimension} against the rendered artifact")
        for dimension in REVIEWER_DIMENSIONS
    )
    return Review(reviewer_id="independent-reviewer", executor_id="production-executor",
                  findings=findings)


class AddedDimensionTests(unittest.TestCase):
    def test_the_three_dimensions_are_present(self) -> None:
        for dimension in ADDED:
            with self.subTest(dimension=dimension):
                self.assertIn(dimension, REVIEWER_DIMENSIONS)

    def test_the_rejected_dimensions_were_not_added(self) -> None:
        """These are expressible by existing dimensions and would duplicate them."""

        for dimension in REJECTED:
            with self.subTest(dimension=dimension):
                self.assertNotIn(dimension, REVIEWER_DIMENSIONS)

    def test_no_existing_dimension_was_removed_or_renamed(self) -> None:
        for original in ("shot_selection", "action_boundary", "shot_relationship",
                         "narrative_progression", "rhythm", "multi_source_remix",
                         "information_density", "visual_continuity", "effect_judgment",
                         "commercial_effectiveness"):
            with self.subTest(dimension=original):
                self.assertIn(original, REVIEWER_DIMENSIONS)

    def test_each_added_dimension_can_carry_a_finding(self) -> None:
        for dimension in ADDED:
            with self.subTest(dimension=dimension):
                finding = Finding(dimension, "FAIL", "measured against the artifact")
                self.assertTrue(finding.blocks_release)

    def test_a_review_must_judge_the_new_dimensions_too(self) -> None:
        incomplete = tuple(
            Finding(d, "PASS", "ok") for d in REVIEWER_DIMENSIONS if d not in ADDED
        )
        with self.assertRaises(ReviewContractError) as caught:
            Review(reviewer_id="r", executor_id="e", findings=incomplete)
        for dimension in ADDED:
            with self.subTest(dimension=dimension):
                self.assertIn(dimension, str(caught.exception))

    def test_the_schema_agrees_with_the_contract(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        findings = schema["properties"]["findings"]
        self.assertEqual(findings["minItems"], len(REVIEWER_DIMENSIONS))
        self.assertEqual(findings["maxItems"], len(REVIEWER_DIMENSIONS))
        self.assertEqual(tuple(findings["items"]["properties"]["dimension"]["enum"]),
                         REVIEWER_DIMENSIONS)

    def test_reviewer_independence_still_holds(self) -> None:
        findings = tuple(Finding(d, "PASS", "ok") for d in REVIEWER_DIMENSIONS)
        with self.assertRaises(ReviewContractError) as caught:
            Review(reviewer_id="same", executor_id="same", findings=findings)
        self.assertIn("must differ", str(caught.exception))


class EvidenceRuleTests(unittest.TestCase):
    """A deterministic finding must carry the measurement behind it."""

    def test_a_finding_with_a_measurement_is_accepted(self) -> None:
        finding = deterministic_finding("comprehension", "FAIL",
                                        claim="a beat is too short to read",
                                        measured="0.400s against 1.050s required")
        self.assertIn("0.400s", finding.detail)
        self.assertIn("measured:", finding.detail)

    def test_a_finding_without_a_measurement_is_refused(self) -> None:
        for measured in (None, "", "   "):
            with self.subTest(measured=measured):
                with self.assertRaises(ReviewContractError):
                    deterministic_finding("audio_hierarchy", "FAIL",
                                          claim="the mix feels wrong", measured=measured)

    def test_a_finding_without_a_claim_is_refused(self) -> None:
        with self.assertRaises(ReviewContractError):
            deterministic_finding("typography_quality", "FAIL", claim="  ", measured="x")

    def test_numeric_measurements_are_accepted(self) -> None:
        finding = deterministic_finding("audio_hierarchy", "PASS",
                                        claim="voice leads the bed",
                                        measured=3.8)
        self.assertIn("3.8", finding.detail)

    def test_the_helper_does_not_change_the_finding_shape(self) -> None:
        finding = deterministic_finding("comprehension", "WEAK", claim="tight",
                                        measured="ratio 0.91")
        self.assertEqual(set(finding.as_dict()),
                         {"dimension", "severity", "detail", "accepted"})

    def test_a_deterministic_finding_is_never_pre_accepted(self) -> None:
        """A machine finding must reach the reviewer, not disposition itself away."""

        finding = deterministic_finding("comprehension", "FAIL", claim="x", measured="y")
        self.assertFalse(finding.accepted)
        self.assertTrue(finding.blocks_release)


class RepairScopeLockTests(unittest.TestCase):
    """A failed dimension unlocks its own layer and nothing else."""

    def test_every_dimension_maps_to_a_layer(self) -> None:
        for dimension in REVIEWER_DIMENSIONS:
            with self.subTest(dimension=dimension):
                self.assertIn(dimension, DIMENSION_LAYERS)
                self.assertIn(DIMENSION_LAYERS[dimension], REPAIR_LAYERS)

    def test_layer_mapping_covers_only_known_dimensions(self) -> None:
        self.assertEqual(set(DIMENSION_LAYERS), set(REVIEWER_DIMENSIONS))

    def test_typography_failure_unlocks_typography_only(self) -> None:
        review = full_review(typography_quality="FAIL")
        plan = build_targeted_repair(review, ["TX02"])
        self.assertEqual(layers_for_repair(plan), ("typography",))

    def test_audio_failure_unlocks_audio_only(self) -> None:
        review = full_review(audio_hierarchy="FAIL")
        plan = build_targeted_repair(review, ["HERO"])
        self.assertEqual(layers_for_repair(plan), ("audio",))

    def test_comprehension_failure_unlocks_editing(self) -> None:
        review = full_review(comprehension="FAIL")
        plan = build_targeted_repair(review, ["S04"])
        self.assertEqual(layers_for_repair(plan), ("editing",))

    def test_continuity_failure_unlocks_picture_finishing(self) -> None:
        review = full_review(visual_continuity="FAIL")
        plan = build_targeted_repair(review, ["S07"])
        self.assertEqual(layers_for_repair(plan), ("picture_finishing",))

    def test_two_failures_unlock_two_layers_cheapest_first(self) -> None:
        review = full_review(typography_quality="FAIL", audio_hierarchy="FAIL")
        plan = build_targeted_repair(review, ["TX03", "HERO"])
        self.assertEqual(layers_for_repair(plan), ("typography", "audio"))

    def test_an_unrelated_layer_is_never_unlocked(self) -> None:
        review = full_review(typography_quality="FAIL")
        plan = build_targeted_repair(review, ["TX02"])
        unlocked = layers_for_repair(plan)
        for layer in ("editing", "picture_finishing", "copy", "audio"):
            with self.subTest(layer=layer):
                self.assertNotIn(layer, unlocked)

    def test_full_regeneration_is_still_refused(self) -> None:
        with self.assertRaises(ReviewContractError):
            RepairPlan(affected_dimensions=("comprehension",), affected_shots=("S04",),
                       regenerate_entire_video=True)

    def test_a_repair_plan_still_needs_its_dimensions_and_shots(self) -> None:
        with self.assertRaises(ReviewContractError):
            RepairPlan(affected_dimensions=(), affected_shots=("S04",))
        with self.assertRaises(ReviewContractError):
            RepairPlan(affected_dimensions=("comprehension",), affected_shots=())

    def test_layers_for_repair_checks_its_input(self) -> None:
        with self.assertRaises(ReviewContractError):
            layers_for_repair("not a plan")

    def test_a_passing_review_produces_no_blocking_findings(self) -> None:
        self.assertEqual(full_review().blocking_findings, ())

    def test_verdict_ranking_is_unchanged(self) -> None:
        self.assertLess(verdict_rank("PRODUCTION_READY"), verdict_rank("NEEDS_REPAIR"))
        self.assertLess(verdict_rank("NEEDS_REPAIR"), verdict_rank("REJECT"))


if __name__ == "__main__":
    unittest.main()
