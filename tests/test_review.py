from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from src.ai_autocut.review import (
    RELEASE_VERDICTS,
    REVIEWER_DIMENSIONS,
    REVIEW_GATES,
    SEVERITIES,
    Finding,
    RepairPlan,
    Review,
    ReviewContractError,
    build_targeted_repair,
    parse_review,
    verdict_rank,
)


REPO_ROOT = Path(__file__).parents[1]
SCHEMA = REPO_ROOT / "schemas" / "review" / "review.v0.schema.json"


def document(severities: dict[str, str] | None = None, accepted: tuple[str, ...] = ()) -> dict:
    chosen = severities or {}
    findings = []
    for dimension in REVIEWER_DIMENSIONS:
        severity = chosen.get(dimension, "PASS")
        findings.append(
            {
                "dimension": dimension,
                "severity": severity,
                "detail": f"{dimension} judged {severity}",
                "accepted": dimension in accepted,
            }
        )
    return {
        "schema_version": "review.v0",
        "reviewer_id": "independent-reviewer",
        "executor_id": "production-executor",
        "findings": findings,
    }


class ReviewContractTestCase(unittest.TestCase):
    def test_all_dimensions_pass_is_production_ready(self) -> None:
        self.assertEqual(parse_review(document()).verdict, "PRODUCTION_READY")

    def test_fail_forces_needs_repair(self) -> None:
        review = parse_review(document({"rhythm": "FAIL"}))
        self.assertEqual(review.verdict, "NEEDS_REPAIR")

    def test_critical_forces_reject(self) -> None:
        review = parse_review(document({"visual_continuity": "CRITICAL"}))
        self.assertEqual(review.verdict, "REJECT")

    def test_critical_outranks_fail(self) -> None:
        review = parse_review(
            document({"rhythm": "FAIL", "visual_continuity": "CRITICAL"})
        )
        self.assertEqual(review.verdict, "REJECT")

    def test_weak_finding_blocks_release_by_default(self) -> None:
        review = parse_review(document({"rhythm": "WEAK"}))
        self.assertEqual(review.verdict, "NEEDS_REPAIR")

    def test_an_accepted_weak_finding_does_not_block(self) -> None:
        review = parse_review(document({"rhythm": "WEAK"}, accepted=("rhythm",)))
        self.assertEqual(review.verdict, "PRODUCTION_READY")

    def test_fail_can_never_be_accepted(self) -> None:
        with self.assertRaises(ReviewContractError):
            Finding("rhythm", "FAIL", "bad pacing", accepted=True)

    def test_critical_can_never_be_accepted(self) -> None:
        with self.assertRaises(ReviewContractError):
            Finding("rhythm", "CRITICAL", "broken cut", accepted=True)

    def test_blocking_findings_exclude_acceptances(self) -> None:
        review = parse_review(document({"rhythm": "WEAK"}, accepted=("rhythm",)))
        self.assertEqual(review.blocking_findings, ())

    def test_worst_severity_is_reported(self) -> None:
        review = parse_review(document({"rhythm": "WEAK", "shot_selection": "FAIL"}))
        self.assertEqual(review.worst_severity, "FAIL")

    def test_human_gate_is_always_required(self) -> None:
        self.assertTrue(parse_review(document()).requires_human_gate)


class ReviewerIndependenceTestCase(unittest.TestCase):
    """A reviewer is not the executor repeating its own success claim."""

    def test_same_actor_cannot_review_its_own_work(self) -> None:
        payload = document()
        payload["reviewer_id"] = payload["executor_id"]
        with self.assertRaises(ReviewContractError):
            parse_review(payload)

    def test_distinct_actors_are_accepted(self) -> None:
        self.assertEqual(
            parse_review(document()).reviewer_id, "independent-reviewer"
        )

    def test_three_gates_are_declared(self) -> None:
        self.assertEqual(
            REVIEW_GATES,
            ("DETERMINISTIC_QA", "INDEPENDENT_AI_REVIEW", "HUMAN_FINAL_GATE"),
        )


class ReviewParsingTestCase(unittest.TestCase):
    def reject(self, mutate) -> None:
        payload = copy.deepcopy(document())
        mutate(payload)
        with self.assertRaises(ReviewContractError):
            parse_review(payload)

    def test_unknown_dimension_is_refused(self) -> None:
        self.reject(lambda d: d["findings"][0].__setitem__("dimension", "vibes"))

    def test_duplicate_dimension_is_refused(self) -> None:
        self.reject(lambda d: d["findings"].append(copy.deepcopy(d["findings"][0])))

    def test_unknown_severity_is_refused(self) -> None:
        self.reject(lambda d: d["findings"][0].__setitem__("severity", "MEH"))

    def test_empty_detail_is_refused(self) -> None:
        self.reject(lambda d: d["findings"][0].__setitem__("detail", "   "))

    def test_empty_findings_are_refused(self) -> None:
        self.reject(lambda d: d.__setitem__("findings", []))

    def test_unknown_key_is_refused(self) -> None:
        self.reject(lambda d: d.__setitem__("score", 9))

    def test_missing_key_is_refused(self) -> None:
        self.reject(lambda d: d.pop("executor_id"))

    def test_a_full_review_is_required_to_report_a_verdict(self) -> None:
        # Every default document is complete, so a verdict is always reachable.
        self.assertEqual(
            len(parse_review(document()).findings), len(REVIEWER_DIMENSIONS)
        )

    def test_severity_and_verdict_vocabularies_are_disjoint(self) -> None:
        self.assertEqual(set(SEVERITIES) & set(RELEASE_VERDICTS), set())
        self.assertEqual(tuple(RELEASE_VERDICTS), ("PRODUCTION_READY", "NEEDS_REPAIR", "REJECT"))

    def test_verdict_rank_orders_by_severity(self) -> None:
        self.assertLess(verdict_rank("PRODUCTION_READY"), verdict_rank("REJECT"))

    def test_schema_records_the_same_dimensions(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        dimensions = schema["properties"]["findings"]["items"]["properties"]["dimension"][
            "enum"
        ]
        self.assertEqual(tuple(dimensions), REVIEWER_DIMENSIONS)


class ReviewCompletenessTestCase(unittest.TestCase):
    """A review must judge every dimension exactly once.

    Regression cover for a real defect: the validator previously rejected a
    duplicated dimension but accepted a *missing* one, so a single
    ``rhythm: PASS`` finding could reach ``PRODUCTION_READY``.
    """

    def findings_for(self, dimensions) -> list[dict]:
        return [
            {
                "dimension": dimension,
                "severity": "PASS",
                "detail": f"{dimension} judged PASS",
                "accepted": False,
            }
            for dimension in dimensions
        ]

    def payload(self, dimensions) -> dict:
        return {
            "schema_version": "review.v0",
            "reviewer_id": "independent-reviewer",
            "executor_id": "production-executor",
            "findings": self.findings_for(dimensions),
        }

    def test_a_single_pass_finding_is_rejected(self) -> None:
        with self.assertRaises(ReviewContractError) as caught:
            parse_review(self.payload(["rhythm"]))
        message = str(caught.exception)
        # The rejection names every dimension that was skipped, so the fix is
        # unambiguous rather than a hunt.
        self.assertIn("shot_selection", message)
        self.assertIn("commercial_effectiveness", message)
        self.assertIn("every dimension exactly once", message)

    def test_nine_of_ten_dimensions_is_rejected(self) -> None:
        incomplete = REVIEWER_DIMENSIONS[:-1]
        self.assertEqual(len(incomplete), len(REVIEWER_DIMENSIONS) - 1)
        with self.assertRaises(ReviewContractError) as caught:
            parse_review(self.payload(incomplete))
        self.assertIn(REVIEWER_DIMENSIONS[-1], str(caught.exception))

    def test_an_incomplete_review_cannot_reach_production_ready(self) -> None:
        for size in range(1, len(REVIEWER_DIMENSIONS)):
            with self.subTest(size=size):
                with self.assertRaises(ReviewContractError):
                    parse_review(self.payload(REVIEWER_DIMENSIONS[:size]))

    def test_all_ten_passing_is_production_ready(self) -> None:
        review = parse_review(self.payload(REVIEWER_DIMENSIONS))
        self.assertEqual(len(review.findings), len(REVIEWER_DIMENSIONS))
        self.assertEqual(review.verdict, "PRODUCTION_READY")

    def test_duplicate_dimension_is_still_rejected(self) -> None:
        duplicated = list(REVIEWER_DIMENSIONS[:-1]) + [REVIEWER_DIMENSIONS[0]]
        self.assertEqual(len(duplicated), len(REVIEWER_DIMENSIONS))
        with self.assertRaises(ReviewContractError) as caught:
            parse_review(self.payload(duplicated))
        self.assertIn("more than once", str(caught.exception))

    def test_a_duplicate_cannot_be_hidden_by_matching_the_count(self) -> None:
        # Ten findings with one repeated is still not ten dimensions judged.
        duplicated = list(REVIEWER_DIMENSIONS[:-1]) + [REVIEWER_DIMENSIONS[0]]
        with self.assertRaises(ReviewContractError):
            parse_review(self.payload(duplicated))

    def test_unknown_dimension_is_still_rejected(self) -> None:
        with self.assertRaises(ReviewContractError) as caught:
            parse_review(self.payload(["vibes"]))
        self.assertIn("unknown review dimension", str(caught.exception))

    def test_unknown_dimension_is_rejected_even_when_the_rest_are_complete(self) -> None:
        swapped = list(REVIEWER_DIMENSIONS[:-1]) + ["vibes"]
        with self.assertRaises(ReviewContractError):
            parse_review(self.payload(swapped))

    def test_completeness_is_enforced_by_the_constructor_too(self) -> None:
        with self.assertRaises(ReviewContractError):
            Review(
                "independent-reviewer",
                "production-executor",
                (Finding("rhythm", "PASS", "only one dimension"),),
            )

    def test_schema_cardinality_matches_the_dimension_count(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        findings = schema["properties"]["findings"]
        count = len(REVIEWER_DIMENSIONS)
        self.assertEqual(findings["minItems"], count)
        self.assertEqual(findings["maxItems"], count)



        review = parse_review(document({"rhythm": "FAIL", "shot_selection": "WEAK"}))
        plan = build_targeted_repair(review, ["S03", "S07"])
        self.assertEqual(plan.affected_dimensions, ("rhythm", "shot_selection"))
        self.assertEqual(plan.affected_shots, ("S03", "S07"))

class TargetedRepairTestCase(unittest.TestCase):
    def test_repair_is_scoped_to_blocking_dimensions(self) -> None:
        review = parse_review(document({"rhythm": "FAIL", "shot_selection": "WEAK"}))
        plan = build_targeted_repair(review, ["S03", "S07"])
        self.assertEqual(plan.affected_dimensions, ("rhythm", "shot_selection"))
        self.assertEqual(plan.affected_shots, ("S03", "S07"))

    def test_regeneration_is_refused(self) -> None:
        with self.assertRaises(ReviewContractError):
            RepairPlan(("rhythm",), ("S03",), regenerate_entire_video=True)

    def test_repair_requires_affected_shots(self) -> None:
        with self.assertRaises(ReviewContractError):
            RepairPlan(("rhythm",), ())

    def test_repair_requires_affected_dimensions(self) -> None:
        with self.assertRaises(ReviewContractError):
            RepairPlan((), ("S03",))

    def test_repair_requires_a_blocking_finding(self) -> None:
        review = parse_review(document())
        with self.assertRaises(ReviewContractError):
            build_targeted_repair(review, ["S03"])

    def test_reject_is_not_repaired_by_a_targeted_fix(self) -> None:
        review = parse_review(document({"rhythm": "CRITICAL"}))
        with self.assertRaises(ReviewContractError):
            build_targeted_repair(review, ["S03"])

    def test_unknown_dimension_in_repair_is_refused(self) -> None:
        with self.assertRaises(ReviewContractError):
            RepairPlan(("vibes",), ("S03",))


if __name__ == "__main__":
    unittest.main()
