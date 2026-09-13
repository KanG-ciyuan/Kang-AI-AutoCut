from __future__ import annotations

import json
import unittest
from fractions import Fraction
from pathlib import Path

from src.ai_autocut.frame_boundary import (
    CandidateSlice,
    FrameAlignmentError,
    FrameBoundaryError,
    ReadbackMismatchError,
    SourceRange,
    TimelineGeometryError,
    absolute_timeline_frame,
    assert_not_before_timeline_start,
    assess_candidate_cut,
    assess_source_boundary,
    build_relative_placements,
    frames_to_seconds_exact,
    seconds_to_frame_exact,
    verify_placement_readback,
)


FIXTURE = Path(__file__).parent / "fixtures" / "s06_boundary_regression.json"


class FrameConversionTests(unittest.TestCase):
    def test_exact_conversion_and_round_trip(self) -> None:
        self.assertEqual(seconds_to_frame_exact("17", "30/1"), 510)
        self.assertEqual(frames_to_seconds_exact(510, "30/1"), Fraction(17, 1))

    def test_rational_fps_keeps_exact_semantics(self) -> None:
        timestamp = Fraction(1001 * 100, 30000)
        self.assertEqual(seconds_to_frame_exact(timestamp, "30000/1001"), 100)

    def test_non_aligned_seconds_are_rejected_instead_of_rounded(self) -> None:
        for timestamp in ("20.23", "20.18"):
            with self.subTest(timestamp=timestamp):
                with self.assertRaises(FrameAlignmentError):
                    seconds_to_frame_exact(timestamp, "30/1")


class SourceRangeTests(unittest.TestCase):
    def test_end_is_exclusive(self) -> None:
        source_range = SourceRange(530, 605)
        self.assertEqual(source_range.duration_frames, 75)
        self.assertNotIn(
            605, range(source_range.start_frame, source_range.end_frame_exclusive)
        )

    def test_invalid_ranges_are_rejected(self) -> None:
        for start, end in ((5, 5), (6, 5), (-1, 5)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(FrameBoundaryError):
                    SourceRange(start, end)

    def test_relative_placements_are_contiguous(self) -> None:
        placements = build_relative_placements(
            (("S01", SourceRange(10, 20)), ("S02", SourceRange(30, 35)))
        )
        self.assertEqual([item.record_frame_relative for item in placements], [0, 10])
        self.assertEqual([item.duration_frames for item in placements], [10, 5])

    def test_timeline_start_is_protected(self) -> None:
        self.assertEqual(absolute_timeline_frame(0, 108000), 108000)
        with self.assertRaises(TimelineGeometryError):
            absolute_timeline_frame(-1, 108000)
        with self.assertRaises(TimelineGeometryError):
            assert_not_before_timeline_start(0, 108000)
        with self.assertRaises(TimelineGeometryError):
            assert_not_before_timeline_start(None, 108000)
        self.assertIsNone(assert_not_before_timeline_start(108000, 108000))


class CandidateBoundaryTests(unittest.TestCase):
    def test_contiguous_same_source_continuation_is_not_a_safe_cut(self) -> None:
        left = CandidateSlice("C07", "SRC-A", SourceRange(404, 453), "action-1")
        right = CandidateSlice("C08", "SRC-A", SourceRange(453, 510), "action-1")
        result = assess_candidate_cut(left, right)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "CANDIDATE_BOUNDARY_SPLITS_CONTINUOUS_SOURCE")
        self.assertIn("frame 453", result.reason)

    def test_unrelated_boundary_is_not_misreported(self) -> None:
        left = CandidateSlice("C01", "SRC-A", SourceRange(10, 20), "action-1")
        right = CandidateSlice("C02", "SRC-B", SourceRange(20, 30), "action-1")
        result = assess_candidate_cut(left, right)
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "CANDIDATE_BOUNDARY_ACCEPTED")


class HistoricalS06RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.case = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_unsafe_20_23_boundary_is_detected(self) -> None:
        evidence = self.case["canonical_frame_evidence"]
        proposed = SourceRange(
            evidence["source_in_frame"],
            evidence["unsafe_legacy_rounded_end_frame_exclusive"],
        )
        result = assess_source_boundary(
            proposed, evidence["verified_safe_end_frame_exclusive"]
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "SOURCE_OUT_EXCEEDS_VERIFIED_BOUNDARY")
        self.assertIn("by 2 frame(s)", result.reason)

    def test_repaired_20_18_boundary_passes_without_false_alarm(self) -> None:
        evidence = self.case["canonical_frame_evidence"]
        proposed = SourceRange(
            evidence["source_in_frame"], evidence["repaired_end_frame_exclusive"]
        )
        result = assess_source_boundary(
            proposed, evidence["verified_safe_end_frame_exclusive"]
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "SOURCE_RANGE_WITHIN_VERIFIED_BOUNDARY")


class ReadbackVerificationTests(unittest.TestCase):
    def test_exact_readback_passes(self) -> None:
        result = verify_placement_readback(
            source_range=SourceRange(659, 691),
            record_frame_relative=0,
            timeline_start_frame=108000,
            observed_start_frame=108000,
            observed_end_frame_exclusive=108032,
            observed_duration_frames=32,
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "READBACK_MATCH")

    def test_wrong_duration_readback_is_rejected_with_deltas(self) -> None:
        with self.assertRaises(ReadbackMismatchError) as caught:
            verify_placement_readback(
                source_range=SourceRange(659, 691),
                record_frame_relative=0,
                timeline_start_frame=108000,
                observed_start_frame=108000,
                observed_end_frame_exclusive=108150,
                observed_duration_frames=150,
            )
        verification = caught.exception.verification
        self.assertEqual(verification.code, "READBACK_MISMATCH")
        self.assertEqual(verification.end_delta_frames, 118)
        self.assertEqual(verification.duration_delta_frames, 118)

    def test_pre_timeline_readback_is_rejected(self) -> None:
        with self.assertRaises(ReadbackMismatchError) as caught:
            verify_placement_readback(
                source_range=SourceRange(659, 691),
                record_frame_relative=0,
                timeline_start_frame=108000,
                observed_start_frame=0,
                observed_end_frame_exclusive=32,
                observed_duration_frames=32,
            )
        self.assertEqual(caught.exception.verification.code, "TIMELINE_START_VIOLATION")


if __name__ == "__main__":
    unittest.main(verbosity=2)
