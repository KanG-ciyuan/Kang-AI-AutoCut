"""Tests for B3-A read-only picture measurement.

Measurement tests generate their own signals locally, so no First Job media is needed and no
First Job value can leak into the module's behaviour.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest

from src.ai_autocut.picture_measurement import (
    CONFIDENCES,
    DIMENSIONS,
    RELATIONSHIP_TIERS,
    REPORTING_LEVEL,
    SAME_PRODUCT,
    SAME_SCENE,
    SAME_SEMANTIC_UNIT,
    SENSITIVITY_BY_TIER,
    UNRELATED,
    PairComparison,
    PictureMeasurement,
    PictureMeasurementError,
    ProductRegion,
    ShotMeasurement,
    ShotWindow,
    compare_shots,
    measure_sequence,
    measure_shot,
    sensitivity_for,
    tier_for,
)


def _has_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _video(path: str, *, seconds: float = 2.0, brightness: float = 0.0,
           saturation: float = 1.0, blur: float = 0.0, size: str = "320x240") -> str:
    chain = []
    if brightness:
        chain.append(f"eq=brightness={brightness}")
    if saturation != 1.0:
        chain.append(f"eq=saturation={saturation}")
    if blur:
        chain.append(f"gblur=sigma={blur}")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "lavfi", "-i", f"testsrc2=size={size}:duration={seconds}"]
    if chain:
        command += ["-vf", ",".join(chain)]
    command += ["-pix_fmt", "yuv420p", path]
    subprocess.run(command, check=True)
    return path


def _shot(shot_id: str, **overrides) -> ShotMeasurement:
    base = dict(
        shot_id=shot_id, start_seconds=0.0, duration_seconds=1.0,
        luminance=100.0, cast_u=128.0, cast_v=128.0, saturation=50.0,
        contrast=200.0, sharpness=3.0, product_region=None,
        product_luminance=None, product_saturation=None, product_contrast=None,
        confidence="HIGH",
    )
    base.update(overrides)
    return ShotMeasurement(**base)


class RelationshipTierTests(unittest.TestCase):
    """Pairs are described categorically, from metadata that already exists."""

    def test_every_tier_is_declared(self) -> None:
        self.assertEqual(set(RELATIONSHIP_TIERS),
                         {"SAME_SEMANTIC_UNIT", "SAME_SCENE", "SAME_PRODUCT", "UNRELATED"})

    def test_semantic_unit_wins_over_scene_and_product(self) -> None:
        self.assertEqual(
            tier_for(same_semantic_unit=True, same_scene=True, same_product=True),
            SAME_SEMANTIC_UNIT)

    def test_scene_wins_over_product(self) -> None:
        self.assertEqual(tier_for(same_scene=True, same_product=True), SAME_SCENE)

    def test_product_alone(self) -> None:
        self.assertEqual(tier_for(same_product=True), SAME_PRODUCT)

    def test_nothing_shared_is_unrelated(self) -> None:
        self.assertEqual(tier_for(), UNRELATED)

    def test_sensitivity_is_categorical_and_ordered(self) -> None:
        self.assertEqual(sensitivity_for(SAME_SEMANTIC_UNIT), "HIGH")
        self.assertEqual(sensitivity_for(SAME_SCENE), "HIGH")
        self.assertEqual(sensitivity_for(SAME_PRODUCT), "MEDIUM")
        self.assertEqual(sensitivity_for(UNRELATED), "LOW")

    def test_an_unknown_tier_is_refused(self) -> None:
        with self.assertRaises(PictureMeasurementError):
            sensitivity_for("SORT_OF_SIMILAR")

    def test_reporting_levels_exist_for_every_tier_and_dimension(self) -> None:
        for tier in RELATIONSHIP_TIERS:
            levels = REPORTING_LEVEL[SENSITIVITY_BY_TIER[tier]]
            for dimension in DIMENSIONS:
                with self.subTest(tier=tier, dimension=dimension):
                    self.assertGreater(levels[dimension], 0)

    def test_tighter_relationships_report_smaller_differences(self) -> None:
        self.assertLess(REPORTING_LEVEL["HIGH"]["luminance"],
                        REPORTING_LEVEL["MEDIUM"]["luminance"])
        self.assertLess(REPORTING_LEVEL["MEDIUM"]["luminance"],
                        REPORTING_LEVEL["LOW"]["luminance"])


class ProductRegionTests(unittest.TestCase):
    def test_a_region_crops_inside_the_frame(self) -> None:
        region = ProductRegion(0.25, 0.25, 0.5, 0.5, source="supplied")
        self.assertEqual(region.as_crop_filter(1080, 1920), "crop=540:960:270:480")

    def test_a_region_outside_the_frame_is_refused(self) -> None:
        with self.assertRaises(PictureMeasurementError):
            ProductRegion(0.8, 0.2, 0.5, 0.5)

    def test_a_negative_coordinate_is_refused(self) -> None:
        with self.assertRaises(PictureMeasurementError):
            ProductRegion(-0.1, 0.1, 0.3, 0.3)

    def test_a_zero_area_region_is_refused(self) -> None:
        with self.assertRaises(PictureMeasurementError):
            ProductRegion(0.1, 0.1, 0.0, 0.3)

    def test_the_region_records_where_it_came_from(self) -> None:
        self.assertEqual(ProductRegion(0.1, 0.1, 0.2, 0.2, source="upstream").source,
                         "upstream")


class ComparisonTests(unittest.TestCase):
    """Comparison is relative: a shot against its neighbour, never against an ideal."""

    def test_identical_shots_report_nothing(self) -> None:
        pair = compare_shots(_shot("A"), _shot("B"), tier=SAME_SCENE)
        self.assertFalse(pair.is_reported)
        self.assertEqual(pair.above_reporting_level, ())

    def test_a_large_difference_in_a_tight_pair_is_reported(self) -> None:
        pair = compare_shots(_shot("A"), _shot("B", luminance=140.0),
                             tier=SAME_SEMANTIC_UNIT)
        self.assertTrue(pair.is_reported)
        self.assertIn("luminance", pair.above_reporting_level)

    def test_the_same_difference_is_not_reported_between_unrelated_shots(self) -> None:
        """The central property: magnitude alone does not decide what matters."""

        delta = 12.0
        tight = compare_shots(_shot("A"), _shot("B", luminance=100.0 + delta),
                              tier=SAME_SEMANTIC_UNIT)
        loose = compare_shots(_shot("A"), _shot("B", luminance=100.0 + delta),
                              tier=UNRELATED)
        self.assertAlmostEqual(tight.deltas["luminance"], loose.deltas["luminance"],
                               places=4)
        self.assertTrue(tight.is_reported)
        self.assertFalse(loose.is_reported)

    def test_deltas_carry_a_sign(self) -> None:
        pair = compare_shots(_shot("A", luminance=120.0), _shot("B", luminance=100.0),
                             tier=SAME_SCENE)
        self.assertLess(pair.deltas["luminance"], 0)

    def test_every_dimension_is_compared(self) -> None:
        pair = compare_shots(_shot("A"), _shot("B"), tier=SAME_SCENE)
        self.assertEqual(set(pair.deltas), set(DIMENSIONS))

    def test_a_cast_difference_is_computed_from_the_chroma_plane(self) -> None:
        warm = _shot("A", cast_u=140.0, cast_v=120.0)
        neutral = _shot("B", cast_u=128.0, cast_v=128.0)
        self.assertGreater(warm.cast, neutral.cast)

    def test_the_largest_normalised_difference_is_named(self) -> None:
        pair = compare_shots(_shot("A"), _shot("B", sharpness=40.0), tier=SAME_SCENE)
        self.assertEqual(pair.largest, "sharpness")


class ReadOnlyTests(unittest.TestCase):
    """The measurement stage may not create or modify any file."""

    def test_the_module_writes_no_media(self) -> None:
        """Scan the executable source, not the prose that explains it."""

        import re
        import src.ai_autocut.picture_measurement as module

        source = open(module.__file__, encoding="utf-8").read()
        code = re.sub(r'""".*?"""', "", source, flags=re.S)
        code = "\n".join(line for line in code.splitlines()
                         if not line.strip().startswith("#"))
        for forbidden in ('"-y"', "open(", ".write(", "shutil.copy", "os.remove",
                          "os.rename", "TemporaryFile", "mkstemp"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)

    def test_no_ffmpeg_call_is_given_an_overwrite_flag(self) -> None:
        import src.ai_autocut.picture_measurement as module

        source = open(module.__file__, encoding="utf-8").read()
        self.assertNotIn('"-y"', source)

    def test_every_ffmpeg_call_discards_its_output(self) -> None:
        import src.ai_autocut.picture_measurement as module

        source = open(module.__file__, encoding="utf-8").read()
        self.assertIn('"-f", "null", "-"', source)

    def test_the_module_declares_itself_read_only(self) -> None:
        import src.ai_autocut.picture_measurement as module

        self.assertIn("read-only", (module.__doc__ or "").lower())


@unittest.skipUnless(_has_ffmpeg(), "ffmpeg is required")
class LiveMeasurementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="pic-measure-")
        self.plain = _video(os.path.join(self.tmp, "plain.mp4"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_measurement_produces_real_numbers(self) -> None:
        shot = measure_shot(self.plain, shot_id="S1", start_seconds=0.2,
                            duration_seconds=1.0)
        self.assertGreater(shot.luminance, 0.0)
        self.assertGreater(shot.saturation, 0.0)
        self.assertGreater(shot.sharpness, 0.0)

    def test_measuring_creates_no_file(self) -> None:
        before = set(os.listdir(self.tmp))
        measure_shot(self.plain, shot_id="S1", start_seconds=0.2, duration_seconds=1.0)
        self.assertEqual(set(os.listdir(self.tmp)), before)

    def test_a_brighter_video_measures_brighter(self) -> None:
        bright = _video(os.path.join(self.tmp, "bright.mp4"), brightness=0.3)
        dark = measure_shot(self.plain, shot_id="D", start_seconds=0.2,
                            duration_seconds=1.0)
        light = measure_shot(bright, shot_id="L", start_seconds=0.2,
                             duration_seconds=1.0)
        self.assertGreater(light.luminance, dark.luminance)

    def test_a_blurred_video_measures_less_edge_energy(self) -> None:
        blurred = _video(os.path.join(self.tmp, "blur.mp4"), blur=3)
        sharp = measure_shot(self.plain, shot_id="S", start_seconds=0.2,
                             duration_seconds=1.0)
        soft = measure_shot(blurred, shot_id="B", start_seconds=0.2,
                            duration_seconds=1.0)
        self.assertLess(soft.sharpness, sharp.sharpness)

    def test_a_product_region_is_measured_separately(self) -> None:
        region = ProductRegion(0.25, 0.25, 0.5, 0.5, source="supplied")
        shot = measure_shot(self.plain, shot_id="S1", start_seconds=0.2,
                            duration_seconds=1.0, product_region=region)
        self.assertTrue(shot.has_product_region)
        self.assertIsNotNone(shot.product_luminance)
        self.assertIsNotNone(shot.product_saturation)
        self.assertIsNotNone(shot.product_contrast)

    def test_no_region_means_no_product_measurement(self) -> None:
        shot = measure_shot(self.plain, shot_id="S1", start_seconds=0.2,
                            duration_seconds=1.0)
        self.assertFalse(shot.has_product_region)
        self.assertIsNone(shot.product_luminance)

    def test_a_short_window_reports_lower_confidence(self) -> None:
        short = measure_shot(self.plain, shot_id="S", start_seconds=0.2,
                             duration_seconds=0.2)
        long = measure_shot(self.plain, shot_id="L", start_seconds=0.2,
                            duration_seconds=1.5)
        self.assertEqual(short.confidence, "LOW")
        self.assertEqual(long.confidence, "HIGH")

    def test_confidence_is_always_a_declared_level(self) -> None:
        shot = measure_shot(self.plain, shot_id="S", start_seconds=0.2,
                            duration_seconds=1.0)
        self.assertIn(shot.confidence, CONFIDENCES)

    def test_a_missing_file_is_refused(self) -> None:
        with self.assertRaises(PictureMeasurementError):
            measure_shot(os.path.join(self.tmp, "absent.mp4"), shot_id="S",
                         start_seconds=0.0, duration_seconds=1.0)

    def test_a_non_positive_window_is_refused(self) -> None:
        with self.assertRaises(PictureMeasurementError):
            measure_shot(self.plain, shot_id="S", start_seconds=0.0,
                         duration_seconds=0.0)

    def test_a_measurement_needs_a_shot_id(self) -> None:
        with self.assertRaises(PictureMeasurementError):
            measure_shot(self.plain, shot_id="", start_seconds=0.0,
                         duration_seconds=1.0)

    def test_a_sequence_measures_every_shot_and_pair(self) -> None:
        windows = [
            ShotWindow("S1", self.plain, 0.2, 1.0, same_scene=True),
            ShotWindow("S2", self.plain, 0.2, 1.0, same_scene=True),
            ShotWindow("S3", self.plain, 0.2, 1.0),
        ]
        result = measure_sequence(windows)
        self.assertEqual(len(result.shots), 3)
        self.assertEqual(len(result.pairs), 2)
        self.assertEqual(result.pairs[1].tier, UNRELATED)

    def test_an_empty_sequence_is_refused(self) -> None:
        with self.assertRaises(PictureMeasurementError):
            measure_sequence([])

    def test_the_artifact_serialises(self) -> None:
        result = measure_sequence([ShotWindow("S1", self.plain, 0.2, 1.0),
                                   ShotWindow("S2", self.plain, 0.2, 1.0)])
        payload = result.as_dict()
        self.assertEqual(payload["schema_version"], "picture_measurement.v1")
        self.assertEqual(len(payload["shots"]), 2)


class NoInventedTargetTests(unittest.TestCase):
    """There is no global target anywhere in the module."""

    def test_no_absolute_reference_value_exists(self) -> None:
        import src.ai_autocut.picture_measurement as module

        source = open(module.__file__, encoding="utf-8").read().lower()
        for forbidden in ("global_target", "target_luminance", "ideal_", "reference_rgb",
                          "mean_rgb", "histogram"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_comparison_needs_two_shots(self) -> None:
        import inspect

        signature = inspect.signature(compare_shots)
        self.assertIn("previous", signature.parameters)
        self.assertIn("current", signature.parameters)

    def test_a_pair_never_references_an_ideal(self) -> None:
        pair = compare_shots(_shot("A"), _shot("B"), tier=SAME_SCENE)
        self.assertNotIn("target", pair.as_dict())


if __name__ == "__main__":
    unittest.main()
