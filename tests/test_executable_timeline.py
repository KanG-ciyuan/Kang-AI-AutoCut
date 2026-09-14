from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from src.ai_autocut.executable_timeline import (
    BACKENDS,
    COMPILER_STATUS,
    SCHEMA_VERSION,
    ExecutableTimeline,
    ExecutableTimelineContractError,
    TimelineSegment,
    compile_for_backend,
    parse_executable_timeline,
    render_executable_timeline,
)


REPO_ROOT = Path(__file__).parents[1]
SCHEMA = (
    REPO_ROOT / "schemas" / "executable_timeline" / "executable_timeline.v0.schema.json"
)


def document() -> dict:
    """Two contiguous segments: 443 frames then 75, total 518 at 30 fps."""

    return {
        "schema_version": SCHEMA_VERSION,
        "frame_rate": "30/1",
        "width": 1080,
        "height": 1920,
        "segments": [
            {
                "segment_id": "segv1_000001",
                "source_id": "SRC-A",
                "source_start_frame": 100,
                "source_end_frame_exclusive": 543,
                "record_frame": 0,
            },
            {
                "segment_id": "segv1_000002",
                "source_id": "SRC-B",
                "source_start_frame": 200,
                "source_end_frame_exclusive": 275,
                "record_frame": 443,
            },
        ],
    }


class ExecutableTimelineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.timeline = parse_executable_timeline(document())

    def test_extent_matches_the_gold_spine(self) -> None:
        # 443 + 75 = 518, the validated Gold timeline length.
        self.assertEqual(self.timeline.extent_frames, 518)

    def test_duration_derives_from_the_exact_rational_rate(self) -> None:
        self.assertAlmostEqual(self.timeline.duration_seconds, 518 / 30, places=9)

    def test_frame_rate_is_kept_as_an_exact_rational(self) -> None:
        self.assertEqual(self.timeline.frame_rate_fraction, (30, 1))

    def test_29_97_stays_distinct_from_30(self) -> None:
        payload = document()
        payload["frame_rate"] = "30000/1001"
        timeline = parse_executable_timeline(payload)
        self.assertEqual(timeline.frame_rate_fraction, (30000, 1001))
        self.assertNotAlmostEqual(timeline.duration_seconds, 518 / 30, places=3)

    def test_segment_end_is_exclusive(self) -> None:
        first = self.timeline.segments[0]
        self.assertEqual(first.duration_frames, 443)
        self.assertEqual(first.record_end_frame_exclusive, 443)

    def test_render_is_deterministic(self) -> None:
        again = render_executable_timeline(
            parse_executable_timeline(json.loads(render_executable_timeline(self.timeline)))
        )
        self.assertEqual(again, render_executable_timeline(self.timeline))


class ExecutableTimelineInvariantTestCase(unittest.TestCase):
    def reject(self, mutate) -> None:
        payload = copy.deepcopy(document())
        mutate(payload)
        with self.assertRaises(ExecutableTimelineContractError):
            parse_executable_timeline(payload)

    def test_a_gap_is_rejected(self) -> None:
        self.reject(lambda d: d["segments"][1].__setitem__("record_frame", 444))

    def test_an_overlap_is_rejected(self) -> None:
        self.reject(lambda d: d["segments"][1].__setitem__("record_frame", 442))

    def test_empty_source_range_is_rejected(self) -> None:
        self.reject(
            lambda d: d["segments"][0].__setitem__("source_end_frame_exclusive", 100)
        )

    def test_inverted_source_range_is_rejected(self) -> None:
        self.reject(
            lambda d: d["segments"][0].__setitem__("source_end_frame_exclusive", 50)
        )

    def test_duplicate_segment_id_is_rejected(self) -> None:
        self.reject(lambda d: d["segments"][1].__setitem__("segment_id", "segv1_000001"))

    def test_negative_record_frame_is_rejected(self) -> None:
        self.reject(lambda d: d["segments"][0].__setitem__("record_frame", -1))

    def test_seconds_field_is_rejected_rather_than_rounded(self) -> None:
        self.reject(lambda d: d["segments"][0].__setitem__("source_in_seconds", 3.33))

    def test_top_level_seconds_field_is_rejected(self) -> None:
        self.reject(lambda d: d.__setitem__("duration_seconds", 17.2667))

    def test_empty_segments_are_rejected(self) -> None:
        self.reject(lambda d: d.__setitem__("segments", []))

    def test_unknown_key_is_rejected(self) -> None:
        self.reject(lambda d: d.__setitem__("davinci_project", "x"))

    def test_missing_key_is_rejected(self) -> None:
        self.reject(lambda d: d.pop("frame_rate"))

    def test_float_frame_is_rejected(self) -> None:
        self.reject(
            lambda d: d["segments"][0].__setitem__("source_start_frame", 100.5)
        )

    def test_boolean_frame_is_rejected(self) -> None:
        self.reject(lambda d: d["segments"][0].__setitem__("source_start_frame", True))

    def test_inexact_frame_rate_string_is_rejected(self) -> None:
        self.reject(lambda d: d.__setitem__("frame_rate", "30"))

    def test_zero_frame_rate_is_rejected(self) -> None:
        self.reject(lambda d: d.__setitem__("frame_rate", "30/0"))

    def test_path_shaped_source_id_is_rejected(self) -> None:
        self.reject(lambda d: d["segments"][0].__setitem__("source_id", "/media/a.mp4"))


class BackendBoundaryTestCase(unittest.TestCase):
    def test_exactly_three_backends_consume_one_contract(self) -> None:
        self.assertEqual(tuple(BACKENDS), ("ffmpeg", "davinci", "jianying"))

    def test_every_compiler_is_declared_unimplemented(self) -> None:
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                self.assertEqual(COMPILER_STATUS[backend], "NOT_IMPLEMENTED")

    def test_compiling_raises_instead_of_returning_a_partial_timeline(self) -> None:
        timeline = parse_executable_timeline(document())
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                with self.assertRaises(NotImplementedError):
                    compile_for_backend(timeline, backend)

    def test_unknown_backend_is_a_contract_error(self) -> None:
        timeline = parse_executable_timeline(document())
        with self.assertRaises(ExecutableTimelineContractError):
            compile_for_backend(timeline, "premiere")

    def test_schema_records_the_same_compiler_status(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        status = schema["x-implementation-status"]
        self.assertEqual(status["contract"], "VALIDATED")
        self.assertEqual(tuple(status["compilers"]), tuple(BACKENDS))
        self.assertTrue(
            all(value == "NOT_IMPLEMENTED" for value in status["compilers"].values())
        )


class SegmentValueTestCase(unittest.TestCase):
    def test_segment_rejects_a_path_shaped_source(self) -> None:
        with self.assertRaises(ExecutableTimelineContractError):
            TimelineSegment("segv1_000001", "~/clip.mp4", 0, 10, 0)

    def test_segment_duration_is_end_exclusive(self) -> None:
        segment = TimelineSegment("segv1_000001", "SRC-A", 10, 25, 0)
        self.assertEqual(segment.duration_frames, 15)

    def test_timeline_requires_a_tuple_of_segments(self) -> None:
        with self.assertRaises(ExecutableTimelineContractError):
            ExecutableTimeline("30/1", 1080, 1920, [])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
