from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.ai_autocut.boundary_guard import (
    BoundaryGuardContractError,
    GuardSegment,
    run_boundary_guard,
)
from src.ai_autocut.frame_boundary import SourceRange


FIXTURE = Path(__file__).parent / "fixtures" / "s06_boundary_regression.json"


def segment(
    segment_id: str,
    candidate_id: str,
    source_id: str,
    start: int,
    end: int,
    *,
    continuation_group: str | None = None,
    safe_end: int | None = None,
    planned_relative: int | None = None,
) -> GuardSegment:
    return GuardSegment(
        segment_id=segment_id,
        candidate_id=candidate_id,
        source_id=source_id,
        source_range=SourceRange(start, end),
        continuation_group=continuation_group,
        verified_safe_end_frame_exclusive=safe_end,
        planned_record_frame_relative=planned_relative,
    )


class BoundaryGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.s06 = json.loads(FIXTURE.read_text(encoding="utf-8"))[
            "canonical_frame_evidence"
        ]

    def test_s06_unsafe_frame_607_is_rejected(self) -> None:
        report = run_boundary_guard(
            (
                segment(
                    "S06",
                    "C16",
                    "SRC-B",
                    self.s06["source_in_frame"],
                    self.s06["unsafe_legacy_rounded_end_frame_exclusive"],
                    safe_end=self.s06["verified_safe_end_frame_exclusive"],
                ),
            )
        )
        self.assertFalse(report.passed)
        self.assertEqual(len(report.issues), 1)
        self.assertEqual(
            report.issues[0].code, "SOURCE_OUT_EXCEEDS_VERIFIED_BOUNDARY"
        )
        self.assertEqual(report.issues[0].frame, 605)
        self.assertIn("by 2 frame(s)", report.issues[0].reason)

    def test_s06_repaired_frame_605_passes(self) -> None:
        report = run_boundary_guard(
            (
                segment(
                    "S06",
                    "C16",
                    "SRC-B",
                    self.s06["source_in_frame"],
                    self.s06["repaired_end_frame_exclusive"],
                    safe_end=self.s06["verified_safe_end_frame_exclusive"],
                ),
            )
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.issues, ())

    def test_contiguous_continuation_candidate_cut_is_reported(self) -> None:
        report = run_boundary_guard(
            (
                segment("S01", "C07", "SRC-A", 404, 453, continuation_group="A1"),
                segment("S02", "C08", "SRC-A", 453, 510, continuation_group="A1"),
            )
        )
        self.assertFalse(report.passed)
        issue = report.issues[0]
        self.assertEqual(issue.code, "CANDIDATE_BOUNDARY_SPLITS_CONTINUOUS_SOURCE")
        self.assertEqual(issue.segment_ids, ("S01", "S02"))
        self.assertEqual(issue.frame, 453)

    def test_normal_candidate_boundary_does_not_false_alarm(self) -> None:
        report = run_boundary_guard(
            (
                segment("S01", "C01", "SRC-A", 10, 20, continuation_group="A1"),
                segment("S02", "C02", "SRC-B", 20, 30, continuation_group="A1"),
            )
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.issues, ())

    def test_multiple_issues_have_deterministic_timeline_order(self) -> None:
        segments = (
            segment(
                "S01",
                "C01",
                "SRC-A",
                10,
                22,
                continuation_group="A1",
                safe_end=20,
            ),
            segment(
                "S02",
                "C02",
                "SRC-A",
                22,
                30,
                continuation_group="A1",
                planned_relative=99,
            ),
        )
        first = run_boundary_guard(segments)
        second = run_boundary_guard(segments)
        expected_codes = [
            "SOURCE_OUT_EXCEEDS_VERIFIED_BOUNDARY",
            "CANDIDATE_BOUNDARY_SPLITS_CONTINUOUS_SOURCE",
            "TIMELINE_RELATIVE_PLACEMENT_MISMATCH",
        ]
        self.assertEqual([issue.code for issue in first.issues], expected_codes)
        self.assertEqual(first.as_dict(), second.as_dict())

    def test_relative_placements_and_total_frames_are_correct(self) -> None:
        report = run_boundary_guard(
            (
                segment("S01", "C01", "SRC-A", 10, 20, planned_relative=0),
                segment("S02", "C02", "SRC-B", 30, 35, planned_relative=10),
                segment("S03", "C03", "SRC-C", 7, 9, planned_relative=15),
            )
        )
        self.assertTrue(report.passed)
        self.assertEqual(
            [placement.record_frame_relative for placement in report.placements],
            [0, 10, 15],
        )
        self.assertEqual(report.total_frames, 17)

    def test_relative_placement_mismatch_is_a_reported_risk(self) -> None:
        report = run_boundary_guard(
            (segment("S01", "C01", "SRC-A", 10, 20, planned_relative=4),)
        )
        self.assertFalse(report.passed)
        self.assertEqual(
            report.issues[0].code, "TIMELINE_RELATIVE_PLACEMENT_MISMATCH"
        )
        self.assertIn("requires 0", report.issues[0].reason)

    def test_malformed_contract_raises_instead_of_returning_business_issue(self) -> None:
        with self.assertRaises(BoundaryGuardContractError):
            run_boundary_guard(())
        with self.assertRaises(BoundaryGuardContractError):
            run_boundary_guard(
                (
                    segment("S01", "C01", "SRC-A", 10, 20),
                    segment("S01", "C02", "SRC-B", 30, 40),
                )
            )
        with self.assertRaises(BoundaryGuardContractError):
            GuardSegment("S01", "C01", "SRC-A", "10..20")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main(verbosity=2)
