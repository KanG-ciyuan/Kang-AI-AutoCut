"""G.1E.1 — a failed picture attempt must leave no misleading successful output.

The G.1F acceptance blocker
---------------------------
Independent review executed a valid picture request, then re-entered with an invalid crop
request. The executor raised, as it should — but the earlier run's ``picture_master.mp4``
and its normalised units were still sitting on the official paths. A downstream caller
could therefore read stale output from a previous success as the result of the run that had
just failed.

What these tests pin down
-------------------------
1. valid run  -> master and normalised units exist
2. invalid rerun -> the error still propagates, unchanged
3. after that failure -> no master, no normalised unit, no partial output, no staging left
4. multi-unit runs that fail part-way expose nothing either

The failure must still be the failure. Nothing here catches or suppresses it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.ai_autocut import execution_adapters, media_probe
from src.ai_autocut.execution_adapters import (
    ExecutionAdapterError,
    execute_picture,
    picture_output_paths,
)
from src.ai_autocut.timebase_adapter import TimebaseAdapter

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

CROP = {"x": 135, "y": 0, "width": 810, "height": 1440}
OUT_OF_BOUNDS = {"x": 500, "y": 0, "width": 810, "height": 1440}


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"ffmpeg failed: {result.stderr[-400:]}")


def _source(path: Path, *, width: int = 1080, height: int = 1440, dark: int = 134) -> None:
    middle = width - 2 * dark
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=0x101010:s={dark}x{height}:d=1:r=30",
        "-f", "lavfi", "-i", f"color=c=0x00E000:s={middle}x{height}:d=1:r=30",
        "-f", "lavfi", "-i", f"color=c=0x101010:s={dark}x{height}:d=1:r=30",
        "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3[out]", "-map", "[out]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-r", "30", str(path),
    ])


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg and ffprobe are required")
class FailureOutputInvalidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.job = self.root / "job"
        self.job.mkdir(parents=True)
        self.source = self.root / "vertical.mp4"
        _source(self.source)

    # ---- helpers ---------------------------------------------------------------

    def _units(self, *specs: tuple[str, int, dict]) -> list[dict]:
        return [{"unit_id": uid, "t_in_seconds": 0.0, "frames": frames,
                 "geometry": geometry} for uid, frames, geometry in specs]

    def _write(self, units: list[dict]) -> None:
        target = self.job / "picture" / "picture_request.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"source": str(self.source), "width": 1080, "height": 1920,
                        "fps": 30, "units": units}),
            encoding="utf-8",
        )

    def _adapter_with_ranges(self, units: list[dict]) -> TimebaseAdapter:
        """Mirror the fast path: the SAME adapter extracts, then executes."""

        ranges = self.job / "picture" / "ranges"
        ranges.mkdir(parents=True, exist_ok=True)
        adapter = TimebaseAdapter(fps=30)
        for unit in units:
            resolution = adapter.resolve_from_seconds(
                unit_id=unit["unit_id"], source=str(self.source),
                t_in_seconds=unit["t_in_seconds"], frames=unit["frames"],
            )
            adapter.execute(resolution, str(ranges / f"{unit['unit_id']}.mp4"))
        return adapter

    def _run_picture(self, units: list[dict]) -> dict:
        self._write(units)
        return execute_picture(self.job, timebase=self._adapter_with_ranges(units))

    def _master(self) -> Path:
        master, _ = picture_output_paths(self.job)
        return master

    def _unit_files(self) -> list[Path]:
        _master, units_dir = picture_output_paths(self.job)
        return sorted(units_dir.glob("*-norm.mp4")) if units_dir.is_dir() else []

    def _staging(self) -> list[Path]:
        return sorted((self.job / "picture").glob(".staging-*"))

    def _assert_no_output(self) -> None:
        self.assertFalse(self._master().is_file(),
                         "a failed run must not leave a picture master")
        self.assertEqual(self._unit_files(), [],
                         "a failed run must not leave a normalised unit")
        self.assertEqual(self._staging(), [],
                         "a failed run must not leave a staging directory")

    # ---- the exact G.1F scenario -----------------------------------------------

    def test_valid_then_invalid_rerun_leaves_no_stale_output(self) -> None:
        valid = self._units(("A", 20, {"mode": "FIT"}),
                            ("B", 25, {"mode": "CROP", "crop_rect": dict(CROP)}))
        result = self._run_picture(valid)

        # step 2: the valid run really did produce output
        self.assertTrue(self._master().is_file())
        self.assertEqual([p.stem for p in self._unit_files()],
                         ["A-norm", "B-norm"])
        first_digest = result["sha256"]

        # steps 3-4: re-enter with an invalid crop; the error must still propagate
        invalid = self._units(("A", 20, {"mode": "FIT"}),
                              ("B", 25, {"mode": "CROP", "crop_rect": dict(OUT_OF_BOUNDS)}))
        with self.assertRaises(ExecutionAdapterError) as caught:
            self._run_picture(invalid)
        self.assertIn("outside the measured", str(caught.exception))

        # step 5: nothing may remain that reads as this run's success
        self._assert_no_output()
        self.assertNotEqual(first_digest, "")

    def test_missing_crop_rect_rerun_leaves_no_stale_output(self) -> None:
        self._run_picture(self._units(("A", 20, {"mode": "FIT"})))
        self.assertTrue(self._master().is_file())

        with self.assertRaises(ExecutionAdapterError):
            self._run_picture(self._units(("A", 20, {"mode": "CROP"})))
        self._assert_no_output()

    def test_aspect_mismatch_rerun_leaves_no_stale_output(self) -> None:
        self._run_picture(self._units(("A", 20, {"mode": "FIT"})))
        self.assertTrue(self._master().is_file())

        with self.assertRaises(ExecutionAdapterError):
            self._run_picture(self._units(("A", 20, {
                "mode": "CROP",
                "crop_rect": {"x": 0, "y": 0, "width": 810, "height": 1400},
            })))
        self._assert_no_output()

    def test_unreadable_request_also_withdraws_prior_output(self) -> None:
        """A run that cannot even read its request is still a failed run."""

        self._run_picture(self._units(("A", 20, {"mode": "FIT"})))
        self.assertTrue(self._master().is_file())

        (self.job / "picture" / "picture_request.json").unlink()
        with self.assertRaises(ExecutionAdapterError):
            execute_picture(self.job)
        self._assert_no_output()

    # ---- multi-unit partial failure -------------------------------------------

    def test_multi_unit_partial_failure_exposes_no_partial_output(self) -> None:
        """Early units succeed, a later unit fails: nothing partial may be exposed."""

        units = self._units(
            ("A", 20, {"mode": "FIT"}),
            ("B", 25, {"mode": "CROP", "crop_rect": dict(CROP)}),
            ("C", 15, {"mode": "CROP", "crop_rect": dict(CROP)}),
        )
        self._run_picture(units)
        self.assertTrue(self._master().is_file())

        broken = self._units(
            ("A", 20, {"mode": "FIT"}),
            ("B", 25, {"mode": "CROP", "crop_rect": dict(CROP)}),
            ("C", 15, {"mode": "CROP"}),          # fails on the LAST unit
        )
        with self.assertRaises(ExecutionAdapterError):
            self._run_picture(broken)

        self._assert_no_output()
        for unit_id in ("A", "B", "C"):
            with self.subTest(unit=unit_id):
                self.assertFalse(
                    (self.job / "picture" / "units" / f"{unit_id}-norm.mp4").is_file(),
                    f"unit {unit_id} from the failed attempt must not be exposed")

    def test_first_unit_failure_after_a_previous_success(self) -> None:
        self._run_picture(self._units(("A", 20, {"mode": "FIT"}),
                                      ("B", 25, {"mode": "FIT"})))

        with self.assertRaises(ExecutionAdapterError):
            self._run_picture(self._units(
                ("A", 20, {"mode": "CROP", "crop_rect": dict(OUT_OF_BOUNDS)}),
                ("B", 25, {"mode": "FIT"}),
            ))
        self._assert_no_output()

    # ---- success path is unaffected -------------------------------------------

    def test_success_promotes_outputs_and_leaves_no_staging(self) -> None:
        units = self._units(("A", 20, {"mode": "FIT"}),
                            ("B", 25, {"mode": "CROP", "crop_rect": dict(CROP)}))
        result = self._run_picture(units)

        master = self._master()
        self.assertTrue(master.is_file())
        self.assertEqual(result["path"], "picture/picture_master.mp4")
        self.assertEqual(media_probe.sha256_of_file(master), result["sha256"])
        self.assertEqual([p.stem for p in self._unit_files()], ["A-norm", "B-norm"])
        self.assertEqual(self._staging(), [])
        self.assertEqual(result["frame_count"], 45)

    def test_second_valid_run_replaces_the_first(self) -> None:
        """A successful rerun must leave the NEW output, not a mixture."""

        first = self._run_picture(self._units(("A", 20, {"mode": "FIT"})))
        second = self._run_picture(self._units(("A", 30, {"mode": "FIT"})))

        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertEqual(second["frame_count"], 30)
        self.assertEqual(media_probe.sha256_of_file(self._master()), second["sha256"])
        self.assertEqual(media_probe.count_frames(str(self._master())), 30)

    def test_source_ranges_are_not_discarded(self) -> None:
        """picture/ranges/ is the job's INPUT, not picture output. It must survive."""

        units = self._units(("A", 20, {"mode": "FIT"}))
        self._run_picture(units)
        ranges = sorted((self.job / "picture" / "ranges").glob("*.mp4"))
        self.assertEqual([p.stem for p in ranges], ["A"])

        with self.assertRaises(ExecutionAdapterError):
            self._run_picture(self._units(("A", 20, {
                "mode": "CROP", "crop_rect": dict(OUT_OF_BOUNDS)})))

        self.assertEqual(sorted((self.job / "picture" / "ranges").glob("*.mp4")),
                         ranges, "source ranges are inputs and must not be withdrawn")

    def test_fit_only_job_is_unaffected(self) -> None:
        """No geometry declarations at all: the historical path must still work."""

        units = [{"unit_id": "A", "t_in_seconds": 0.0, "frames": 24}]
        result = self._run_picture(units)
        self.assertTrue(self._master().is_file())
        self.assertEqual(result["frame_count"], 24)
        self.assertEqual(result["unit_geometry"][0]["geometry_declaration"],
                         "ABSENT_DEFAULT_FIT")
        self.assertEqual(self._staging(), [])


if __name__ == "__main__":
    unittest.main()
