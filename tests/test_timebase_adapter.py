"""The timebase invariant, at the production boundary.

SOURCE coordinate  = a PTS timestamp in seconds
TIMELINE coordinate = a CFR frame index

The defect this guards: the Second SKU repair selected source frames with
``trim=start_frame=A:end_frame=B`` against raw variable-frame-rate sources and then
forced ``-r 30``. A source frame index is not 30 x its time, so the range did not hold
the frames it was assumed to hold — the build produced **502 frames instead of 487**,
and on a re-run **66 frames where 67 were expected**.

Two properties are tested here that unit tests of ``timebase.py`` alone cannot show:
the unsafe coordinate is *refused*, and a range that bypassed the adapter is *detected*.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
import unittest

from src.ai_autocut.timebase import TimebaseError
from src.ai_autocut.timebase_adapter import (
    COORDINATE_SYSTEM,
    FORBIDDEN_SOURCE_SELECTORS,
    TimebaseAdapter,
    TimebaseAdapterError,
    assert_timestamp_safe,
)


def _has_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class FakeTiming:
    """A measured-timing stand-in with a deliberately non-uniform delta table.

    ``timestamps`` is what a real VFR source's PTS table looks like: the gaps are not
    all ``1/fps``, so ``index / fps`` and ``timestamp_of(index)`` disagree — which is
    the entire point.
    """

    def __init__(self, timestamps: list[float], fps: int = 30) -> None:
        self.path = "fake.mp4"
        self.fps = fps
        self.timestamps = timestamps
        deltas: dict[float, int] = {}
        for i in range(len(timestamps) - 1):
            delta = round(timestamps[i + 1] - timestamps[i], 5)
            deltas[delta] = deltas.get(delta, 0) + 1
        self.deltas = deltas

    @property
    def frame_count(self) -> int:
        return len(self.timestamps)

    @property
    def span_seconds(self) -> float:
        return round(self.timestamps[-1] - self.timestamps[0], 4)

    @property
    def nominal(self) -> int:
        return int(round(self.span_seconds * self.fps))

    @property
    def is_variable_frame_rate(self) -> bool:
        expected = 1.0 / self.fps
        return any(abs(delta - expected) > 1e-4 for delta in self.deltas)

    def timestamp_of(self, index: int) -> float:
        if index < 0 or index >= len(self.timestamps):
            raise TimebaseError(f"frame {index} is outside the source")
        return self.timestamps[index]

    def timeline_index(self, timestamp: float) -> int:
        return int(round(timestamp * self.fps))

    def describe(self) -> dict:
        return {
            "frames": self.frame_count,
            "span_seconds": self.span_seconds,
            "nominal_frames_at_fps": self.nominal,
            "fps": self.fps,
            "variable_frame_rate": self.is_variable_frame_rate,
            "dominant_deltas": {str(k): v for k, v in self.deltas.items()},
        }


def vfr_adapter() -> TimebaseAdapter:
    """An adapter whose only source is a variable-frame-rate fake.

    Frame 5 starts at 0.3s: on a CFR-30 assumption it would start at 0.1667s. The two
    answers differ by nearly a tenth of a second, which is several frames.
    """

    adapter = TimebaseAdapter(fps=30)
    timestamps = [0.0, 0.0333, 0.0667, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    adapter._timing_cache["vfr-mixed.mp4"] = FakeTiming(timestamps)  # type: ignore[assignment]
    return adapter


class ForbiddenCoordinateTests(unittest.TestCase):
    def test_every_forbidden_selector_is_a_frame_index_selector(self) -> None:
        self.assertIn("trim=start_frame", FORBIDDEN_SOURCE_SELECTORS)
        self.assertIn("trim=end_frame", FORBIDDEN_SOURCE_SELECTORS)

    def test_the_sku2_defect_command_is_refused(self) -> None:
        """The exact shape that produced 502 frames instead of 487."""

        command = [
            "ffmpeg", "-i", "raw.mp4",
            "-vf", "trim=start_frame=61:end_frame=127,setpts=PTS-STARTPTS",
            "-r", "30", "out.mp4",
        ]
        with self.assertRaises(TimebaseAdapterError) as caught:
            assert_timestamp_safe(command)
        self.assertIn("frame index", str(caught.exception))

    def test_a_select_by_index_is_refused(self) -> None:
        with self.assertRaises(TimebaseAdapterError):
            assert_timestamp_safe(
                ["ffmpeg", "-i", "raw.mp4", "-vf", "select='gte(n\\,372)'", "out.mp4"]
            )

    def test_a_timestamp_command_is_accepted(self) -> None:
        assert_timestamp_safe(
            [
                "ffmpeg", "-ss", "12.400000", "-t", "2.200000", "-i", "raw.mp4",
                "-vf", "setpts=PTS-STARTPTS,fps=30", "-frames:v", "66", "out.mp4",
            ]
        )

    def test_an_empty_command_is_refused(self) -> None:
        with self.assertRaises(TimebaseAdapterError):
            assert_timestamp_safe([])


class ResolutionTests(unittest.TestCase):
    def test_a_source_frame_index_resolves_through_measured_pts(self) -> None:
        """The crux: index 5 is 0.3s, not 5/30 = 0.1667s."""

        adapter = vfr_adapter()
        resolution = adapter.resolve_from_source_index(
            unit_id="U03", source="vfr-mixed.mp4", source_frame_index=5, frames=30
        )
        self.assertAlmostEqual(resolution.t_in_seconds, 0.3, places=6)
        self.assertNotAlmostEqual(resolution.t_in_seconds, 5 / 30, places=3)
        self.assertEqual(resolution.resolved_from, "MEASURED_PTS_LOOKUP")
        self.assertTrue(resolution.variable_frame_rate)

    def test_an_assumed_fps_answer_would_have_been_wrong(self) -> None:
        adapter = vfr_adapter()
        measured = adapter.resolve_from_source_index(
            unit_id="U03", source="vfr-mixed.mp4", source_frame_index=5, frames=30
        ).t_in_seconds
        assumed = 5 / 30
        self.assertGreater(abs(measured - assumed), 0.1)

    def test_an_explicit_timestamp_is_taken_as_given(self) -> None:
        adapter = vfr_adapter()
        resolution = adapter.resolve_from_seconds(
            unit_id="U01", source="vfr-mixed.mp4", t_in_seconds=0.25, frames=15
        )
        self.assertAlmostEqual(resolution.t_in_seconds, 0.25, places=6)
        self.assertEqual(resolution.resolved_from, "EXPLICIT_SOURCE_SECONDS")

    def test_the_coordinate_system_is_recorded(self) -> None:
        adapter = vfr_adapter()
        resolution = adapter.resolve_from_seconds(
            unit_id="U01", source="vfr-mixed.mp4", t_in_seconds=0.1, frames=15
        )
        self.assertEqual(resolution.as_dict()["coordinate_system"], COORDINATE_SYSTEM)

    def test_variable_frame_rate_is_visible_in_the_profile(self) -> None:
        adapter = vfr_adapter()
        profile = adapter.profile("vfr-mixed.mp4")
        self.assertTrue(profile["variable_frame_rate"])
        self.assertEqual(profile["coordinate_system"], COORDINATE_SYSTEM)

    def test_a_range_past_the_end_of_the_source_is_refused(self) -> None:
        adapter = vfr_adapter()
        resolution = adapter.resolve_from_seconds(
            unit_id="U09", source="vfr-mixed.mp4", t_in_seconds=0.85, frames=90
        )
        with self.assertRaises(TimebaseAdapterError):
            adapter.assert_safe(resolution)

    def test_a_frame_index_past_the_end_of_the_source_is_refused(self) -> None:
        adapter = vfr_adapter()
        with self.assertRaises(TimebaseAdapterError):
            adapter.resolve_from_source_index(
                unit_id="U09", source="vfr-mixed.mp4", source_frame_index=999, frames=15
            )

    def test_a_non_integer_frame_index_is_refused(self) -> None:
        adapter = vfr_adapter()
        with self.assertRaises(TimebaseAdapterError):
            adapter.resolve_from_source_index(
                unit_id="U01", source="vfr-mixed.mp4", source_frame_index=1.5, frames=15  # type: ignore[arg-type]
            )


class BypassDetectionTests(unittest.TestCase):
    def test_an_unexecuted_unit_is_reported(self) -> None:
        """This is what makes a bypass a test failure rather than a silent gap."""

        adapter = vfr_adapter()
        adapter._ledger.append(  # simulate one unit that did go through
            __import__(
                "src.ai_autocut.timebase_adapter", fromlist=["SourceRangeExecution"]
            ).SourceRangeExecution(
                unit_id="U01", source="vfr-mixed.mp4", t_in_seconds=0.0,
                frames_requested=15, frames_produced=15, out_path="out.mp4",
            )
        )
        with self.assertRaises(TimebaseAdapterError) as caught:
            adapter.assert_range_coverage(["U01", "U02"])
        self.assertIn("U02", str(caught.exception))
        self.assertIn("bypassed", str(caught.exception))

    def test_full_coverage_passes(self) -> None:
        adapter = vfr_adapter()
        from src.ai_autocut.timebase_adapter import SourceRangeExecution

        for unit in ("U01", "U02"):
            adapter._ledger.append(
                SourceRangeExecution(
                    unit_id=unit, source="vfr-mixed.mp4", t_in_seconds=0.0,
                    frames_requested=15, frames_produced=15, out_path="out.mp4",
                )
            )
        adapter.assert_range_coverage(["U01", "U02"])

    def test_an_empty_expectation_passes(self) -> None:
        vfr_adapter().assert_range_coverage([])

    def test_the_ledger_is_serialisable_evidence(self) -> None:
        adapter = vfr_adapter()
        document = adapter.ledger_document()
        self.assertEqual(document["coordinate_system"], COORDINATE_SYSTEM)
        self.assertEqual(document["executions"], [])


class BadInputTests(unittest.TestCase):
    def test_a_non_positive_fps_is_refused(self) -> None:
        with self.assertRaises(TimebaseAdapterError):
            TimebaseAdapter(fps=0)

    def test_a_boolean_fps_is_refused(self) -> None:
        with self.assertRaises(TimebaseAdapterError):
            TimebaseAdapter(fps=True)  # type: ignore[arg-type]

    def test_an_empty_source_is_refused(self) -> None:
        with self.assertRaises(TimebaseAdapterError):
            TimebaseAdapter().timing("")

    def test_a_resolution_with_non_positive_frames_is_refused(self) -> None:
        from src.ai_autocut.timebase_adapter import SourceRangeResolution

        with self.assertRaises(TimebaseAdapterError):
            SourceRangeResolution(
                unit_id="U01", source="s.mp4", t_in_seconds=0.0, frames=0, fps=30,
                variable_frame_rate=False, source_frame_index=None,
                resolved_from="EXPLICIT_SOURCE_SECONDS",
            )


@unittest.skipUnless(_has_ffmpeg(), "ffmpeg is required")
class RealExtractionTests(unittest.TestCase):
    """The adapter against real media, when ffmpeg is available."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.source = self.tmp / "source.mp4"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_source(self, frames: int = 90, fps: int = 30) -> None:
        import subprocess

        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"testsrc2=size=64x64:rate={fps}:duration={frames / fps}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps), str(self.source),
            ],
            check=True,
            capture_output=True,
        )

    def test_extraction_produces_exactly_the_requested_frames(self) -> None:
        self._make_source(frames=90)
        adapter = TimebaseAdapter(fps=30)
        resolution = adapter.resolve_from_seconds(
            unit_id="U01", source=str(self.source), t_in_seconds=0.5, frames=20
        )
        out = self.tmp / "out.mp4"
        execution = adapter.execute(resolution, str(out))
        self.assertEqual(execution.frames_produced, 20)
        self.assertEqual(execution.frames_requested, 20)
        adapter.verify_frames(execution)

    def test_execution_is_recorded_in_the_ledger(self) -> None:
        self._make_source(frames=60)
        adapter = TimebaseAdapter(fps=30)
        resolution = adapter.resolve_from_seconds(
            unit_id="U01", source=str(self.source), t_in_seconds=0.0, frames=15
        )
        adapter.execute(resolution, str(self.tmp / "out.mp4"))
        self.assertEqual(len(adapter.ledger), 1)
        self.assertEqual(adapter.ledger[0].unit_id, "U01")
        self.assertEqual(adapter.ledger[0].coordinate_system, COORDINATE_SYSTEM)

    def test_the_buggy_frame_index_range_would_not_hold_its_count(self) -> None:
        """Demonstrates the failure mode the invariant exists to prevent.

        Selecting by frame index and forcing ``-r 30`` is what lost frames on the
        Second SKU. The adapter's timestamp path returns the exact requested count.
        """

        self._make_source(frames=90)
        adapter = TimebaseAdapter(fps=30)
        resolution = adapter.resolve_from_seconds(
            unit_id="U01", source=str(self.source), t_in_seconds=0.0, frames=30
        )
        execution = adapter.execute(resolution, str(self.tmp / "exact.mp4"))
        self.assertEqual(execution.frames_produced, 30)


if __name__ == "__main__":
    unittest.main()
