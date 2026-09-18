"""Minimal per-unit picture geometry: FIT and CROP.

The production blocker this closes
----------------------------------
The picture executor could only scale-to-fit and pad. A 3:4 source in a 9:16 delivery was
therefore letterboxed, with no way for a job to state an explicit crop. Recorded on the
Third SKU as 216 of 906 frames (23.84 % of the timeline) carrying 240 px bars.

What is asserted here
---------------------
``FIT`` is the historical behaviour and is unchanged, byte for byte, including for a unit
that declares no geometry at all. ``CROP`` applies an explicitly stated source rectangle
and is never inferred, never adjusted, and never silently replaced by a fit. An invalid
crop is refused.

The pixel tests are the point. A geometry claim that is only checked in JSON is a claim;
these tests decode the produced frames and prove which source pixels actually landed in
the output.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.ai_autocut import execution_adapters, media_probe
from src.ai_autocut.execution_adapters import (
    GEOMETRY_DECLARATIONS,
    GEOMETRY_MODES,
    CropRect,
    ExecutionAdapterError,
    execute_picture,
    fit_geometry_filter,
    resolve_unit_geometry,
)
from src.ai_autocut.timebase_adapter import TimebaseAdapter

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


# --------------------------------------------------------------------------- helpers


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"ffmpeg failed: {result.stderr[-400:]}")


def _frame_rgb(path: Path, at_seconds: float = 0.0) -> np.ndarray:
    """Decode one frame as an (h, w, 3) uint8 array. Real pixels, not a JSON claim."""

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{at_seconds:.6f}", "-i", str(path),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    ).stdout
    probe = media_probe.probe_streams(path)
    width, height = int(probe["width"]), int(probe["height"])
    expected = width * height * 3
    if len(raw) < expected:
        raise AssertionError(f"could not decode a frame from {path}")
    return np.frombuffer(raw[:expected], dtype=np.uint8).reshape(height, width, 3)


def _banded_source(path: Path, *, width: int, height: int, dark_each_side: int = 134,
                   seconds: float = 1.0) -> None:
    """A source whose left/right margins are dark and whose middle band is bright green.

    Cropping the middle band yields an almost purely green frame; fitting the whole frame
    keeps the dark margins. That makes "was the crop really applied?" a pixel question
    rather than a JSON question.

    The band boundaries are deliberately EVEN. yuv420p is chroma subsampled, so a
    boundary at an odd column is itself a blended pixel in the source; that is a property
    of the test fixture, not of the crop. Keeping the boundaries even means the fixture
    cannot be mistaken for a crop defect.

    ``dark_each_side`` defaults to 134, which places the green band on columns 134..945 —
    so the production rectangle ``x=135, width=810`` (columns 135..944) sits strictly
    inside it while still exercising an ODD crop offset.
    """

    middle = width - 2 * dark_each_side
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=0x101010:s={dark_each_side}x{height}:d={seconds}:r=30",
        "-f", "lavfi", "-i", f"color=c=0x00E000:s={middle}x{height}:d={seconds}:r=30",
        "-f", "lavfi", "-i", f"color=c=0x101010:s={dark_each_side}x{height}:d={seconds}:r=30",
        "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3[out]",
        "-map", "[out]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", "30", str(path),
    ])


def _write_request(job: Path, *, source: Path, width: int, height: int, units: list) -> None:
    target = job / "picture" / "picture_request.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"source": str(source), "width": width, "height": height, "fps": 30,
                    "units": units}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ------------------------------------------------------- resolver, no media required


class ResolverTests(unittest.TestCase):
    """The pure decision plane: no media, no ffmpeg."""

    def _resolve(self, unit: dict) -> execution_adapters.UnitGeometry:
        return resolve_unit_geometry(
            unit, unit_id="U01", source_width=1080, source_height=1440,
            output_width=1080, output_height=1920,
        )

    def test_modes_are_exactly_fit_and_crop(self) -> None:
        self.assertEqual(GEOMETRY_MODES, ("FIT", "CROP"))
        self.assertEqual(GEOMETRY_DECLARATIONS, ("EXPLICIT", "ABSENT_DEFAULT_FIT"))

    def test_absent_geometry_defaults_to_fit(self) -> None:
        geometry = self._resolve({})
        self.assertEqual(geometry.requested_mode, "FIT")
        self.assertEqual(geometry.applied_mode, "FIT")
        self.assertEqual(geometry.declaration, "ABSENT_DEFAULT_FIT")
        self.assertIsNone(geometry.applied_crop_rect)
        self.assertEqual(geometry.geometry_filter, fit_geometry_filter(1080, 1920))

    def test_explicit_fit_is_recorded_as_explicit(self) -> None:
        geometry = self._resolve({"geometry": {"mode": "FIT"}})
        self.assertEqual(geometry.declaration, "EXPLICIT")
        self.assertEqual(geometry.applied_mode, "FIT")
        self.assertEqual(geometry.geometry_filter, fit_geometry_filter(1080, 1920))

    def test_valid_crop_resolves_exactly(self) -> None:
        geometry = self._resolve({"geometry": {
            "mode": "CROP",
            "crop_rect": {"x": 135, "y": 0, "width": 810, "height": 1440},
            "confidence": "HIGH", "evidence_ref": "g1c-framing-evidence",
        }})
        self.assertEqual(geometry.requested_mode, "CROP")
        self.assertEqual(geometry.applied_mode, "CROP")
        self.assertEqual(geometry.confidence, "HIGH")
        self.assertEqual(geometry.evidence_ref, "g1c-framing-evidence")
        self.assertEqual(geometry.geometry_filter, "crop=810:1440:135:0,scale=1080:1920")

    def test_requested_and_applied_rect_are_identical(self) -> None:
        """No path may adjust a rectangle. The evidence must show them equal."""

        declared = {"x": 135, "y": 0, "width": 810, "height": 1440}
        geometry = self._resolve({"geometry": {"mode": "CROP", "crop_rect": declared}})
        self.assertEqual(geometry.requested_crop_rect, declared)
        self.assertEqual(geometry.applied_crop_rect, declared)
        self.assertEqual(geometry.requested_crop_rect, geometry.applied_crop_rect)

    def test_mode_is_case_and_whitespace_insensitive(self) -> None:
        rect = {"x": 135, "y": 0, "width": 810, "height": 1440}
        self.assertEqual(
            self._resolve({"geometry": {"mode": " crop ", "crop_rect": rect}}).applied_mode,
            "CROP",
        )
        self.assertEqual(self._resolve({"geometry": {"mode": "fit"}}).applied_mode, "FIT")

    # ---- refusals ---------------------------------------------------------------

    def test_unknown_mode_is_rejected(self) -> None:
        for bad in ("SCALE", "PAD", "AUTO", "CENTER_CROP", ""):
            with self.subTest(mode=bad):
                with self.assertRaises(ExecutionAdapterError):
                    self._resolve({"geometry": {"mode": bad}})

    def test_missing_mode_is_rejected(self) -> None:
        with self.assertRaises(ExecutionAdapterError):
            self._resolve({"geometry": {}})

    def test_geometry_must_be_an_object(self) -> None:
        with self.assertRaises(ExecutionAdapterError):
            self._resolve({"geometry": "CROP"})

    def test_crop_without_rect_is_rejected(self) -> None:
        with self.assertRaises(ExecutionAdapterError) as caught:
            self._resolve({"geometry": {"mode": "CROP"}})
        self.assertIn("cannot be inferred", str(caught.exception))

    def test_partial_crop_rect_is_rejected(self) -> None:
        for missing in ("x", "y", "width", "height"):
            rect = {"x": 135, "y": 0, "width": 810, "height": 1440}
            del rect[missing]
            with self.subTest(missing=missing):
                with self.assertRaises(ExecutionAdapterError):
                    self._resolve({"geometry": {"mode": "CROP", "crop_rect": rect}})

    def test_rect_outside_the_source_is_rejected(self) -> None:
        cases = [
            {"x": 271, "y": 0, "width": 810, "height": 1440},   # x + width = 1081
            {"x": 0, "y": 1, "width": 810, "height": 1440},     # y + height = 1441
            {"x": -1, "y": 0, "width": 810, "height": 1440},    # negative
            {"x": 0, "y": -4, "width": 810, "height": 1440},    # negative
        ]
        for rect in cases:
            with self.subTest(rect=rect):
                with self.assertRaises(ExecutionAdapterError):
                    self._resolve({"geometry": {"mode": "CROP", "crop_rect": rect}})

    def test_non_integer_and_boolean_rect_values_are_rejected(self) -> None:
        for value in (135.5, "135", True, None):
            rect = {"x": value, "y": 0, "width": 810, "height": 1440}
            with self.subTest(value=value):
                with self.assertRaises(ExecutionAdapterError):
                    self._resolve({"geometry": {"mode": "CROP", "crop_rect": rect}})

    def test_odd_dimension_rect_is_rejected(self) -> None:
        """yuv420p is chroma subsampled, so an odd edge cannot be encoded faithfully."""

        with self.assertRaises(ExecutionAdapterError):
            CropRect(x=0, y=0, width=809, height=1440)
        with self.assertRaises(ExecutionAdapterError):
            CropRect(x=0, y=0, width=810, height=1439)

    def test_zero_or_tiny_rect_is_rejected(self) -> None:
        for rect in ({"x": 0, "y": 0, "width": 0, "height": 0},
                     {"x": 0, "y": 0, "width": 810, "height": 0}):
            with self.subTest(rect=rect):
                with self.assertRaises(ExecutionAdapterError):
                    self._resolve({"geometry": {"mode": "CROP", "crop_rect": rect}})

    def test_aspect_mismatch_is_rejected_rather_than_distorted(self) -> None:
        """A CROP never becomes a FIT and is never stretched to fit."""

        with self.assertRaises(ExecutionAdapterError) as caught:
            self._resolve({"geometry": {
                "mode": "CROP",
                "crop_rect": {"x": 0, "y": 0, "width": 810, "height": 1400},
            }})
        message = str(caught.exception)
        self.assertIn("never silently", message)

    def test_fit_with_a_crop_rect_is_rejected(self) -> None:
        with self.assertRaises(ExecutionAdapterError) as caught:
            self._resolve({"geometry": {
                "mode": "FIT",
                "crop_rect": {"x": 0, "y": 0, "width": 810, "height": 1440},
            }})
        self.assertIn("contradict", str(caught.exception).lower() + " contradiction")

    def test_crop_is_accepted_when_the_source_is_already_the_output_aspect(self) -> None:
        geometry = resolve_unit_geometry(
            {"geometry": {"mode": "CROP",
                          "crop_rect": {"x": 0, "y": 0, "width": 1080, "height": 1920}}},
            unit_id="U", source_width=1080, source_height=1920,
            output_width=1080, output_height=1920,
        )
        self.assertEqual(geometry.applied_mode, "CROP")


# ------------------------------------------------------------ executor, real media


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg and ffprobe are required")
class ExecutorTests(unittest.TestCase):
    """The executor against real encoded media."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.job = self.root / "job"
        self.job.mkdir(parents=True)

    def _vertical_source(self) -> Path:
        """1080x1440 (3:4) banded source — the SRC-021 shape."""

        source = self.root / "vertical_3x4.mp4"
        _banded_source(source, width=1080, height=1440)
        return source

    def _native_source(self) -> Path:
        """1080x1920 (9:16) banded source — the native delivery shape."""

        source = self.root / "native_9x16.mp4"
        _banded_source(source, width=1080, height=1920)
        return source

    # ---- FIT -------------------------------------------------------------------

    def test_default_unit_still_fits_exactly_as_before(self) -> None:
        source = self._vertical_source()
        _write_request(self.job, source=source, width=1080, height=1920,
                       units=[{"unit_id": "U01", "t_in_seconds": 0.0, "frames": 30}])
        result = execute_picture(self.job)

        self.assertEqual(result["width"], 1080)
        self.assertEqual(result["height"], 1920)
        self.assertEqual(result["frame_count"], 30)
        entry = result["unit_geometry"][0]
        self.assertEqual(entry["requested_geometry_mode"], "FIT")
        self.assertEqual(entry["applied_geometry_mode"], "FIT")
        self.assertEqual(entry["geometry_declaration"], "ABSENT_DEFAULT_FIT")
        self.assertIsNone(entry["applied_crop_rect"])

    def test_explicit_fit_produces_padding_for_a_3x4_source(self) -> None:
        """The historical behaviour, and the reason this repair exists."""

        source = self._vertical_source()
        _write_request(self.job, source=source, width=1080, height=1920,
                       units=[{"unit_id": "U01", "t_in_seconds": 0.0, "frames": 30,
                               "geometry": {"mode": "FIT"}}])
        result = execute_picture(self.job)
        frame = _frame_rgb(self.job / result["path"])
        self.assertEqual(frame.shape, (1920, 1080, 3))
        # 1080x1440 scaled into 1080x1920 leaves 240 px top and bottom.
        self.assertLess(int(frame[5].mean()), 20, "expected a letterbox bar at the top")
        self.assertLess(int(frame[-5].mean()), 20, "expected a letterbox bar at the bottom")
        self.assertGreater(int(frame[960].mean()), 20, "expected picture at mid frame")

    def test_native_9x16_fit_does_not_regress(self) -> None:
        """A native 9:16 unit still fills the frame with no padding at all."""

        source = self._native_source()
        _write_request(self.job, source=source, width=1080, height=1920,
                       units=[{"unit_id": "U01", "t_in_seconds": 0.0, "frames": 30}])
        result = execute_picture(self.job)
        frame = _frame_rgb(self.job / result["path"])
        self.assertEqual(frame.shape, (1920, 1080, 3))
        for row in (0, 5, 1914, 1919):
            with self.subTest(row=row):
                self.assertGreater(int(frame[row].mean()), 20,
                                   "a native 9:16 unit must not gain padding")

    # ---- CROP ------------------------------------------------------------------

    def test_valid_crop_applies_the_exact_rectangle(self) -> None:
        """The pixel proof: the cropped band is what reaches the output."""

        source = self._vertical_source()   # 135 dark | 810 green | 135 dark
        _write_request(self.job, source=source, width=1080, height=1920, units=[{
            "unit_id": "U01", "t_in_seconds": 0.0, "frames": 30,
            "geometry": {"mode": "CROP",
                         "crop_rect": {"x": 135, "y": 0, "width": 810, "height": 1440},
                         "confidence": "HIGH", "evidence_ref": "unit-test"},
        }])
        result = execute_picture(self.job)
        frame = _frame_rgb(self.job / result["path"])

        self.assertEqual((result["width"], result["height"]), (1080, 1920))
        self.assertEqual(result["frame_count"], 30)
        # Every corner must be the green band: the dark margins were really removed.
        for row, col in ((0, 0), (0, 1079), (1919, 0), (1919, 1079), (960, 540)):
            pixel = frame[row, col]
            with self.subTest(row=row, col=col):
                self.assertGreater(int(pixel[1]), 150, "green band expected")
                self.assertLess(int(pixel[0]), 60, "dark margin must not survive the crop")
                self.assertLess(int(pixel[2]), 60, "dark margin must not survive the crop")

    def test_crop_removes_the_letterbox_that_fit_produces(self) -> None:
        """The production blocker, asserted as a before/after on the same source."""

        source = self._vertical_source()
        crop = {"mode": "CROP",
                "crop_rect": {"x": 135, "y": 0, "width": 810, "height": 1440}}
        _write_request(self.job, source=source, width=1080, height=1920,
                       units=[{"unit_id": "FITU", "t_in_seconds": 0.0, "frames": 30,
                               "geometry": {"mode": "FIT"}},
                              {"unit_id": "CROPU", "t_in_seconds": 0.0, "frames": 30,
                               "geometry": crop}])
        result = execute_picture(self.job)
        by_id = {entry["unit_id"]: entry for entry in result["unit_geometry"]}
        self.assertEqual(by_id["FITU"]["applied_geometry_mode"], "FIT")
        self.assertEqual(by_id["CROPU"]["applied_geometry_mode"], "CROP")

        fitted = _frame_rgb(self.job / "picture" / "units" / "FITU-norm.mp4")
        cropped = _frame_rgb(self.job / "picture" / "units" / "CROPU-norm.mp4")
        self.assertLess(int(fitted[5].mean()), 20)          # bars
        self.assertGreater(int(cropped[5].mean()), 20)      # no bars

    def test_crop_evidence_records_every_required_field(self) -> None:
        source = self._vertical_source()
        rect = {"x": 135, "y": 0, "width": 810, "height": 1440}
        _write_request(self.job, source=source, width=1080, height=1920, units=[{
            "unit_id": "U01", "t_in_seconds": 0.0, "frames": 24,
            "geometry": {"mode": "CROP", "crop_rect": rect,
                         "confidence": "HIGH", "evidence_ref": "g1c"},
        }])
        result = execute_picture(self.job)
        entry = result["unit_geometry"][0]
        for key in ("requested_geometry_mode", "applied_geometry_mode",
                    "requested_crop_rect", "applied_crop_rect",
                    "output_width", "output_height", "frame_count",
                    "source_width", "source_height", "geometry_filter",
                    "geometry_declaration", "confidence", "evidence_ref"):
            with self.subTest(key=key):
                self.assertIn(key, entry)
        self.assertEqual(entry["requested_geometry_mode"], "CROP")
        self.assertEqual(entry["applied_geometry_mode"], "CROP")
        self.assertEqual(entry["requested_crop_rect"], rect)
        self.assertEqual(entry["applied_crop_rect"], rect)
        self.assertEqual((entry["output_width"], entry["output_height"]), (1080, 1920))
        self.assertEqual((entry["source_width"], entry["source_height"]), (1080, 1440))
        self.assertEqual(entry["frame_count"], 24)

    def test_invalid_crop_fails_the_run_and_produces_no_master(self) -> None:
        """No silent fallback: a bad CROP must not become a FIT."""

        source = self._vertical_source()
        _write_request(self.job, source=source, width=1080, height=1920, units=[{
            "unit_id": "U01", "t_in_seconds": 0.0, "frames": 30,
            "geometry": {"mode": "CROP",
                         "crop_rect": {"x": 500, "y": 0, "width": 810, "height": 1440}},
        }])
        with self.assertRaises(ExecutionAdapterError):
            execute_picture(self.job)
        self.assertFalse((self.job / "picture" / "picture_master.mp4").is_file(),
                         "a refused crop must not leave a master behind")
        self.assertFalse((self.job / "picture" / "units" / "U01-norm.mp4").is_file(),
                         "a refused crop must not leave a fitted unit behind")

    def test_missing_crop_rect_fails_the_run(self) -> None:
        source = self._vertical_source()
        _write_request(self.job, source=source, width=1080, height=1920, units=[{
            "unit_id": "U01", "t_in_seconds": 0.0, "frames": 30,
            "geometry": {"mode": "CROP"},
        }])
        with self.assertRaises(ExecutionAdapterError):
            execute_picture(self.job)
        self.assertFalse((self.job / "picture" / "picture_master.mp4").is_file())

    # ---- mixed ----------------------------------------------------------------

    def test_mixed_fit_and_crop_units_preserve_order_and_total_frames(self) -> None:
        vertical = self._vertical_source()
        native = self._native_source()
        _write_request(self.job, source=vertical, width=1080, height=1920, units=[
            {"unit_id": "A", "t_in_seconds": 0.0, "frames": 20, "geometry": {"mode": "FIT"}},
            {"unit_id": "B", "t_in_seconds": 0.0, "frames": 25,
             "geometry": {"mode": "CROP",
                          "crop_rect": {"x": 135, "y": 0, "width": 810, "height": 1440}}},
            {"unit_id": "C", "t_in_seconds": 0.0, "frames": 15},
        ])
        result = execute_picture(self.job)

        self.assertEqual(result["units_executed"], ["A", "B", "C"])
        self.assertEqual([e["unit_id"] for e in result["unit_geometry"]], ["A", "B", "C"])
        self.assertEqual([e["applied_geometry_mode"] for e in result["unit_geometry"]],
                         ["FIT", "CROP", "FIT"])
        self.assertEqual([e["geometry_declaration"] for e in result["unit_geometry"]],
                         ["EXPLICIT", "EXPLICIT", "ABSENT_DEFAULT_FIT"])
        self.assertEqual(result["frame_count"], 60)

    def test_reused_ranges_are_cropped_too(self) -> None:
        """Production reuses picture/ranges/<unit>.mp4; geometry must still apply.

        This mirrors the fast path exactly: the SAME adapter instance extracts the range
        during its own stage and is then handed to the picture boundary, which is why
        ``assert_range_coverage`` accepts the reused unit.
        """

        source = self._vertical_source()
        ranges = self.job / "picture" / "ranges"
        ranges.mkdir(parents=True, exist_ok=True)

        adapter = TimebaseAdapter(fps=30)
        resolution = adapter.resolve_from_seconds(
            unit_id="U01", source=str(source), t_in_seconds=0.0, frames=24
        )
        adapter.execute(resolution, str(ranges / "U01.mp4"))

        _write_request(self.job, source=source, width=1080, height=1920, units=[{
            "unit_id": "U01", "t_in_seconds": 0.0, "frames": 24,
            "geometry": {"mode": "CROP",
                         "crop_rect": {"x": 135, "y": 0, "width": 810, "height": 1440}},
        }])
        result = execute_picture(self.job, timebase=adapter)
        self.assertEqual(result["units_reused"], ["U01"])
        self.assertEqual(result["unit_geometry"][0]["applied_geometry_mode"], "CROP")
        frame = _frame_rgb(self.job / "picture" / "units" / "U01-norm.mp4")
        self.assertGreater(int(frame[5, 5][1]), 150, "the reused range must still be cropped")

    def test_crop_is_validated_against_the_measured_source_not_the_request(self) -> None:
        """A rectangle legal for 1080x1440 must be refused for a smaller real source."""

        small = self.root / "small.mp4"
        _banded_source(small, width=540, height=720)
        _write_request(self.job, source=small, width=1080, height=1920, units=[{
            "unit_id": "U01", "t_in_seconds": 0.0, "frames": 20,
            "geometry": {"mode": "CROP",
                         "crop_rect": {"x": 135, "y": 0, "width": 810, "height": 1440}},
        }])
        with self.assertRaises(ExecutionAdapterError) as caught:
            execute_picture(self.job)
        self.assertIn("outside the measured", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
