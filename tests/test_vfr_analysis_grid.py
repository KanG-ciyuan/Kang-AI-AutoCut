"""Real variable-frame-rate regression for the analysis-grid mapping.

The defect this closes
----------------------
``resolve_placement_window`` validated a measured timestamp and then returned the **raw
decoded source ordinal**. The Shot Understanding engine decodes at a forced CFR, so that
ordinal is not an analysis frame. For a source whose first second runs at 10 fps and whose
second runs at 30 fps, the 1.0 s content sits at raw index 10 but at analysis frame 30, so
the raw ordinal would analyse the content at 0.333 s.

This file proves the fix against a **real local VFR file**, not a synthetic timestamp
table, and it proves it by inspecting the *temporal content* that was analysed rather than
the index alone.

The fixture is built so the two cadence regions are visually distinct: red for the 10 fps
second, blue for the 30 fps second. If the mapping regresses, the frame the engine
analyses at the 1.0 s window turns red again.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from src.ai_autocut import media_probe, timebase_adapter
from src.ai_autocut.timebase_adapter import TimebaseAdapter

ANALYSIS_FPS = 30
#: The measured source timestamp under test. It sits exactly on the cadence boundary.
BOUNDARY_SECONDS = 1.0
#: The raw decoded ordinal of that timestamp: ten 0.1 s frames precede it.
EXPECTED_RAW_INDEX = 10
#: The analysis frame that actually holds that timestamp on a 30 fps grid.
EXPECTED_ANALYSIS_FRAME = 30


def _run(command: list[str], label: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"{label} failed: {result.stderr[-300:]}")


def build_vfr_source(path: Path) -> Path:
    """A real VFR file: first second at 10 fps, second second at 30 fps.

    Built by concatenating a red 30 fps second with a blue 30 fps second and then
    dropping two frames in three across the first second with ``select``, keeping the
    original presentation timestamps (``-fps_mode vfr``). The result is genuinely
    variable: ten frames at 0.1 s cadence followed by thirty at 1/30 s.
    """

    base = path.with_name("base.mp4")
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=red:size=64x64:rate=30:duration=1",
            "-f", "lavfi", "-i", "color=c=blue:size=64x64:rate=30:duration=1",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(base),
        ],
        "building the CFR base",
    )
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(base),
            "-vf", "select='if(lt(t,1),not(mod(n,3)),1)'", "-fps_mode", "vfr",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        "building the VFR source",
    )
    return path


def analysis_frame_colour(source: Path, index: int, *, fps: int = ANALYSIS_FPS) -> tuple[float, float, float]:
    """Mean RGB of one frame of the forced-CFR analysis stream.

    This is the same way the Shot Understanding engine sees the media: decoded at a
    forced ``fps`` with a scaled raster.
    """

    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(source),
            "-vf", f"fps={fps},scale=64:64", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"could not decode the analysis stream: {result.stderr[-300:]}")
    frame_bytes = 64 * 64 * 3
    data = result.stdout
    total = len(data) // frame_bytes
    if index >= total:
        raise AssertionError(
            f"the analysis stream holds {total} frames; frame {index} was requested"
        )
    frame = data[index * frame_bytes : (index + 1) * frame_bytes]
    pixels = 64 * 64
    return (
        sum(frame[0::3]) / pixels,
        sum(frame[1::3]) / pixels,
        sum(frame[2::3]) / pixels,
    )


@unittest.skipUnless(media_probe.have_tools(), "ffmpeg and ffprobe are required")
class RealVfrAnalysisGridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp())
        cls.source = build_vfr_source(cls.tmp / "vfr.mp4")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self) -> None:
        self.adapter = TimebaseAdapter(fps=ANALYSIS_FPS)

    # ---- the fixture really is what the blocker describes ----------------------

    def test_the_fixture_is_a_real_variable_frame_rate_source(self) -> None:
        timing = self.adapter.timing(str(self.source))
        self.assertTrue(timing.is_variable_frame_rate)
        deltas = sorted(timing.deltas)
        self.assertIn(0.1, [round(d, 4) for d in deltas])
        self.assertIn(round(1 / 30, 4), [round(d, 4) for d in deltas])

    def test_the_fixture_has_the_two_cadence_regions(self) -> None:
        timing = self.adapter.timing(str(self.source))
        self.assertEqual(timing.frame_count, 40)
        self.assertAlmostEqual(timing.timestamp_of(0), 0.0, places=6)
        self.assertAlmostEqual(timing.timestamp_of(EXPECTED_RAW_INDEX), BOUNDARY_SECONDS, places=6)

    def test_the_two_regions_are_visually_distinct(self) -> None:
        """Without this the temporal check below would prove nothing."""

        before = analysis_frame_colour(self.source, EXPECTED_ANALYSIS_FRAME - 5)
        after = analysis_frame_colour(self.source, EXPECTED_ANALYSIS_FRAME + 5)
        self.assertGreater(before[0], 200)  # red before the boundary
        self.assertLess(before[2], 50)
        self.assertGreater(after[2], 200)  # blue after it
        self.assertLess(after[0], 50)

    # ---- the mapping -----------------------------------------------------------

    def test_the_measured_timestamp_maps_to_the_analysis_grid(self) -> None:
        window = self.adapter.resolve_placement_window(
            placement_id="P01", source=str(self.source),
            t_in_seconds=BOUNDARY_SECONDS, duration_seconds=0.5,
            analysis_fps=ANALYSIS_FPS,
        )
        self.assertEqual(window["analysis_start_frame"], EXPECTED_ANALYSIS_FRAME)
        self.assertEqual(window["source_in"], EXPECTED_ANALYSIS_FRAME)
        self.assertEqual(window["analysis_frames_cfr"], 15)
        self.assertEqual(window["source_out_exclusive"], EXPECTED_ANALYSIS_FRAME + 15)

    def test_the_raw_ordinal_is_recorded_but_is_not_the_coordinate(self) -> None:
        window = self.adapter.resolve_placement_window(
            placement_id="P01", source=str(self.source),
            t_in_seconds=BOUNDARY_SECONDS, duration_seconds=0.5,
            analysis_fps=ANALYSIS_FPS,
        )
        self.assertEqual(window["raw_source_in"], EXPECTED_RAW_INDEX)
        self.assertNotEqual(window["source_in"], window["raw_source_in"])
        self.assertTrue(window["raw_index_differs_from_analysis"])
        self.assertEqual(window["analysis_grid"], "CFR_DERIVED_FROM_MEASURED_PTS")

    def test_the_analysis_window_axes_on_the_right_temporal_content(self) -> None:
        """The decisive check: the frame the analysis starts at is the 1.0 s content.

        Under the old implementation the start index was the raw ordinal 10, whose
        content is the 0.333 s frame — red. The corrected index 30 is blue.
        """

        window = self.adapter.resolve_placement_window(
            placement_id="P01", source=str(self.source),
            t_in_seconds=BOUNDARY_SECONDS, duration_seconds=0.5,
            analysis_fps=ANALYSIS_FPS,
        )
        analysed = analysis_frame_colour(self.source, int(window["source_in"]))
        # The analysed frame is the blue 30 fps region, i.e. the 1.0 s content.
        self.assertGreater(analysed[2], 200, f"analysed frame was {analysed}, expected blue")
        self.assertLess(analysed[0], 50)

        # And the raw ordinal would have selected the red 0.333 s frame instead.
        wrong = analysis_frame_colour(self.source, EXPECTED_RAW_INDEX)
        self.assertGreater(wrong[0], 200, f"raw ordinal gave {wrong}, expected red")
        self.assertNotEqual(analysed, wrong)

    def test_the_regression_fails_under_the_old_mapping(self) -> None:
        """Explicitly asserts the old behaviour would have been wrong.

        If the analysis grid ever collapses back to the raw decoded ordinal, the frame
        it selects stops matching the measured timestamp's content.
        """

        window = self.adapter.resolve_placement_window(
            placement_id="P01", source=str(self.source),
            t_in_seconds=BOUNDARY_SECONDS, duration_seconds=0.5,
            analysis_fps=ANALYSIS_FPS,
        )
        old_style_index = window["raw_source_in"]
        correct_index = window["source_in"]
        old_colour = analysis_frame_colour(self.source, int(old_style_index))
        correct_colour = analysis_frame_colour(self.source, int(correct_index))
        self.assertNotEqual(
            old_colour, correct_colour,
            "the raw ordinal and the analysis frame selected identical content, so this "
            "fixture cannot distinguish the old mapping from the new one",
        )

    def test_a_non_variable_source_maps_identically_in_both_domains(self) -> None:
        """The fix must not disturb the constant frame rate case."""

        cfr = self.tmp / "cfr.mp4"
        if not cfr.is_file():
            _run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=green:size=64x64:rate=30:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(cfr),
                ],
                "building the CFR source",
            )
        window = self.adapter.resolve_placement_window(
            placement_id="P01", source=str(cfr),
            t_in_seconds=1.0, duration_seconds=0.5, analysis_fps=ANALYSIS_FPS,
        )
        self.assertFalse(window["variable_frame_rate"])
        self.assertEqual(window["source_in"], EXPECTED_ANALYSIS_FRAME)
        self.assertEqual(window["raw_source_in"], EXPECTED_ANALYSIS_FRAME)
        self.assertFalse(window["raw_index_differs_from_analysis"])

    def test_the_measured_timestamp_is_still_validated(self) -> None:
        window = self.adapter.resolve_placement_window(
            placement_id="P01", source=str(self.source),
            t_in_seconds=0.5, duration_seconds=0.3, analysis_fps=ANALYSIS_FPS,
        )
        self.assertAlmostEqual(window["measured_t_in_seconds"], 0.5, places=6)
        self.assertEqual(window["source_in"], 15)  # 0.5 s on a 30 fps analysis grid
        self.assertEqual(window["raw_source_in"], 5)  # 0.5 s at 10 fps

    def test_a_window_past_the_measured_end_is_refused(self) -> None:
        with self.assertRaises(timebase_adapter.TimebaseAdapterError):
            self.adapter.resolve_placement_window(
                placement_id="P01", source=str(self.source),
                t_in_seconds=1.9, duration_seconds=5.0, analysis_fps=ANALYSIS_FPS,
            )


@unittest.skipUnless(media_probe.have_tools(), "ffmpeg and ffprobe are required")
class VfrThroughTheProductionPathTests(unittest.TestCase):
    """The same mapping, exercised through the fast path rather than the adapter alone."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp())
        source = build_vfr_source(cls.tmp / "vfr.mp4")
        cls.job = cls.tmp / "job"
        cls.job.mkdir()
        import hashlib

        (cls.job / "source_inventory.json").write_text(
            json.dumps(
                {
                    "schema_version": "source_inventory.v1",
                    "files": [
                        {
                            "source_id": "VFR-01",
                            "filename": source.name,
                            "path": str(source),
                            "size_bytes": source.stat().st_size,
                            "mtime_ns": source.stat().st_mtime_ns,
                            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (cls.job / "shots").mkdir()
        (cls.job / "shots" / "placements.json").write_text(
            json.dumps(
                {
                    "placements": [
                        {
                            "placement_id": "P01",
                            "source_id": "VFR-01",
                            "media_path": str(source),
                            "t_in_seconds": BOUNDARY_SECONDS,
                            "duration_seconds": 0.5,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_production_path_analyses_the_measured_window(self) -> None:
        from src.ai_autocut.fast_path import FastPath

        result = FastPath(self.job, job_id="vfr-job").run_stage("UNDERSTAND SHOTS")
        self.assertEqual(result.outcome, "PASS", result.reason)
        document = json.loads(
            (self.job / "shots" / "shot_understanding.json").read_text(encoding="utf-8")
        )
        entry = document["placement_timing"][0]
        self.assertTrue(entry["variable_frame_rate"])
        self.assertEqual(entry["analysis_start_frame"], EXPECTED_ANALYSIS_FRAME)
        self.assertEqual(entry["raw_source_in"], EXPECTED_RAW_INDEX)
        self.assertEqual(document["analysis_grid"], "CFR_DERIVED_FROM_MEASURED_PTS")

    def test_the_analysed_segment_starts_at_the_measured_window(self) -> None:
        """The segment the engine reports must begin at the analysis frame, not the raw index."""

        from src.ai_autocut.fast_path import FastPath

        FastPath(self.job, job_id="vfr-job").run_stage("UNDERSTAND SHOTS")
        document = json.loads(
            (self.job / "shots" / "shot_understanding.json").read_text(encoding="utf-8")
        )
        segments = document["placements"][0]["segments"]
        self.assertTrue(segments)
        self.assertEqual(segments[0]["start_frame"], EXPECTED_ANALYSIS_FRAME)


if __name__ == "__main__":
    unittest.main()
