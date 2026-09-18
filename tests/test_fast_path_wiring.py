"""Production wiring proof for the eight-stage Production Fast Path.

The Gate G.0 audit found the failure mode this file exists to catch: capabilities that
were implemented, had passing unit tests, and were never called by any production path —
``timebase.py``, ``narration_coverage.py``, ``audio_program.py`` and the whole
``review``/repair contract.

Unit tests cannot catch that, because a unit test calls the module directly. So these
tests assert the *production path* calls the module, using four independent angles:

1. **Structural** — every stage declares a resolvable capability, and every required
   module is declared by some stage.
2. **Behavioural** — a spy wrapped around the real capability proves the stage invoked it.
3. **Artifact** — the stage's output exists and re-parses through the module's own parser.
4. **Disconnection** — breaking the capability changes the stage outcome. If a stage
   silently stopped calling its module, this test would not notice; it is here precisely
   so that the opposite is true.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from src.ai_autocut import fast_path
from src.ai_autocut.fast_path import (
    HALTING_OUTCOMES,
    OUTCOMES,
    OUTCOME_TO_LOW_LEVEL_STATE,
    REQUIRED_PRODUCTION_MODULES,
    SEMANTIC_STAGES,
    STAGES,
    FastPath,
    FastPathError,
    StageResult,
    resolve_capability,
)
from src.ai_autocut.job_foundation import STAGE_ORDER
from src.ai_autocut.review import REVIEWER_DIMENSIONS
from src.ai_autocut.timebase_adapter import (
    SourceRangeExecution,
    TimebaseAdapter,
    TimebaseAdapterError,
)


class RecordingTimebase:
    """A timebase adapter stand-in that records the calls the fast path makes."""

    def __init__(self) -> None:
        self.resolved: list[dict[str, object]] = []
        self.verified: list[str] = []
        self.executed: list[str] = []
        self.coverage_checked: list[list[str]] = []

    def resolve_from_seconds(self, **kwargs: object) -> mock.Mock:
        self.resolved.append(kwargs)
        resolution = mock.Mock()
        resolution.unit_id = kwargs["unit_id"]
        resolution.as_dict.return_value = {
            "unit_id": kwargs["unit_id"],
            "coordinate_system": "SOURCE_PTS_SECONDS -> CFR_TIMELINE_FRAMES",
            "t_in_seconds": kwargs["t_in_seconds"],
            "frames": kwargs["frames"],
        }
        return resolution

    def resolve_from_source_index(self, **kwargs: object) -> mock.Mock:
        self.resolved.append(kwargs)
        resolution = mock.Mock()
        resolution.unit_id = kwargs["unit_id"]
        resolution.as_dict.return_value = {
            "unit_id": kwargs["unit_id"],
            "resolved_from": "MEASURED_PTS_LOOKUP",
        }
        return resolution

    def execute(self, resolution: mock.Mock, out_path: str) -> SourceRangeExecution:
        self.executed.append(resolution.unit_id)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"fake")
        return SourceRangeExecution(
            unit_id=resolution.unit_id,
            source="fake.mp4",
            t_in_seconds=0.0,
            frames_requested=30,
            frames_produced=30,
            out_path=out_path,
        )

    def assert_placement_timing(self, **kwargs: object) -> dict[str, object]:
        placement_id = str(kwargs["placement_id"])
        if kwargs.get("t_in_seconds") is None:
            raise TimebaseAdapterError(
                f"placement {placement_id!r} states no t_in_seconds"
            )
        self.verified.append(placement_id)
        return {
            "placement_id": placement_id,
            "coordinate_system": "SOURCE_PTS_SECONDS -> CFR_TIMELINE_FRAMES",
            "measured_t_in_seconds": float(kwargs["t_in_seconds"]),
            "measured_duration_seconds": 1.0,
            "assumed_cfr_duration_seconds": 1.0,
            "duration_delta_seconds": 0.0,
            "variable_frame_rate": False,
            "duration_coordinate": "MEASURED_PTS",
        }

    def assert_range_coverage(self, unit_ids: object) -> None:
        expected = list(unit_ids)  # type: ignore[arg-type]
        self.coverage_checked.append(expected)
        missing = [unit for unit in expected if unit not in self.executed]
        if missing:
            raise TimebaseAdapterError(f"bypass detected for {missing}")


def build_job(root: Path, *, silence_units: bool = False, undesigned_gap: bool = False,
              complete_review: bool = True) -> Path:
    """A minimal job whose inputs let the pure capabilities run for real."""

    root.mkdir(parents=True, exist_ok=True)

    # PREPARE — a real source file, so immutability verification is genuine, and real
    # decodable media where ffmpeg exists so shot understanding can actually run.
    source = root / "source-01.mp4"
    if _has_ffmpeg():
        import subprocess

        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30:duration=1",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(source),
            ],
            check=True,
            capture_output=True,
        )
    else:
        source.write_bytes(b"placeholder-not-decodable")
    inventory = {
        "schema_version": "source_inventory.v1",
        "files": [
            {
                "source_id": "SKU3-01",
                "filename": source.name,
                "path": str(source),
                "size_bytes": source.stat().st_size,
                "mtime_ns": source.stat().st_mtime_ns,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        ],
    }
    (root / "source_inventory.json").write_text(json.dumps(inventory), encoding="utf-8")

    # UNDERSTAND SHOTS
    (root / "shots").mkdir(exist_ok=True)
    (root / "shots" / "placements.json").write_text(
        json.dumps(
            {
                "placements": [
                    {
                        "placement_id": "P01",
                        "source_id": "SKU3-01",
                        "media_path": str(source),
                        "source_in": 0,
                        "source_out_exclusive": 30,
                        "t_in_seconds": 0.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    # PLAN THE EDIT
    (root / "edit").mkdir(exist_ok=True)
    (root / "edit" / "timeline_ranges.json").write_text(
        json.dumps(
            {
                "ranges": [
                    {
                        "shot_id": "S01",
                        "role": "identity",
                        "start_frame": 0,
                        "end_frame_exclusive": 30,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    # FINISH THE PICTURE
    (root / "picture").mkdir(exist_ok=True)
    (root / "picture" / "measurements.json").write_text(
        json.dumps(
            {
                "shots": [
                    {
                        "measurement": {
                            "shot_id": "S01",
                            "start_seconds": 0.0,
                            "duration_seconds": 1.0,
                            "luminance": 0.5,
                            "cast_u": 0.0,
                            "cast_v": 0.0,
                            "saturation": 0.5,
                            "contrast": 0.5,
                            "sharpness": 0.5,
                            "product_region": None,
                            "product_luminance": None,
                            "product_saturation": None,
                            "product_contrast": None,
                            "confidence": "HIGH",
                        },
                        "contains_product": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "picture" / "source_ranges.json").write_text(
        json.dumps(
            {
                "ranges": [
                    {
                        "unit_id": "U01",
                        "source": str(source),
                        "t_in_seconds": 0.0,
                        "frames": 30,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    # PLAN THE WORDS
    (root / "copy").mkdir(exist_ok=True)
    units = [
        {
            "unit_id": "U01",
            "start_seconds": 0.0,
            "end_seconds": 2.0,
            "visual_self_explanatory": False,
            "carries_new_commercial_information": True,
            "has_title": False,
            "vo_adds_function_beyond_title": True,
            "explanation_supported": True,
            "vo": {
                "vo_id": "VO01",
                "purpose": "DEMONSTRATION_EXPLANATION",
                "semantic_unit": "U01",
                "required": True,
                "silence_reason": None,
                "window_seconds": [0.0, 2.0],
            },
        },
        {
            "unit_id": "U02",
            "start_seconds": 2.0,
            "end_seconds": 4.0,
            "visual_self_explanatory": True,
            "carries_new_commercial_information": True,
            "has_title": False,
            "vo_adds_function_beyond_title": True,
            "explanation_supported": True,
            "vo": {
                "vo_id": "VO02",
                "purpose": "CTA",
                "semantic_unit": "U02",
                "required": True,
                "silence_reason": None,
                "window_seconds": [2.0, 4.0],
            },
        },
        {
            "unit_id": "U03",
            "start_seconds": 4.0,
            "end_seconds": 6.0,
            "visual_self_explanatory": True,
            "carries_new_commercial_information": True,
            "has_title": False,
            "vo_adds_function_beyond_title": True,
            "explanation_supported": True,
            "vo": {
                "vo_id": "VO03",
                "purpose": "DESIRE_RELEVANCE",
                "semantic_unit": "U03",
                "required": False,
                "silence_reason": "HERO_VISUAL_CARRIES_MESSAGE",
                "window_seconds": None,
            },
        },
    ]
    if silence_units:
        # The Cushion Puff defect in one unit: a scene carrying new commercial
        # information is left silent, and the only reason offered is that a Title
        # already summarises it. That is a WEAK reason, not a justified one.
        units.append(
            {
                "unit_id": "U04",
                "start_seconds": 6.0,
                "end_seconds": 9.0,
                "visual_self_explanatory": False,
                "carries_new_commercial_information": True,
                "has_title": True,
                "vo_adds_function_beyond_title": False,
                "explanation_supported": True,
                "vo": {
                    "vo_id": "VO04",
                    "purpose": "SELLING_POINT_EXPANSION",
                    "semantic_unit": "U04",
                    "required": False,
                    "silence_reason": "TITLE_ALREADY_EXISTS",
                    "window_seconds": None,
                },
            }
        )
    (root / "copy" / "commercial_units.json").write_text(
        json.dumps({"units": units}), encoding="utf-8"
    )

    # BUILD THE AUDIO
    (root / "audio").mkdir(exist_ok=True)
    segments = [
        {"segment_id": "VO01", "start_seconds": 0.0, "end_seconds": 1.6, "text": "pasang di jari"},
        {"segment_id": "VO02", "start_seconds": 1.8, "end_seconds": 3.2, "text": "tinggal bilas"},
    ]
    design = {
        "VO01->VO02": ["INTENTIONAL_SEMANTIC_PAUSE", "a new evidence unit begins"]
    }
    if undesigned_gap:
        # A 1.4s hole the job never declares. The module must report it rather than
        # assume a reason for the silence.
        design = {}
        segments = [
            {"segment_id": "VO01", "start_seconds": 0.0, "end_seconds": 1.6, "text": "pasang di jari"},
            {"segment_id": "VO02", "start_seconds": 3.0, "end_seconds": 4.4, "text": "tinggal bilas"},
        ]
    (root / "audio" / "placement.json").write_text(
        json.dumps(
            {
                "segments": segments,
                # Declared art direction: the pause between the two lines is intended.
                "design": design,
            }
        ),
        encoding="utf-8",
    )
    (root / "audio" / "sync_expectations.json").write_text(
        json.dumps({"sync_tolerance": 0.35, "expectations": []}), encoding="utf-8"
    )

    # REVIEW & REPAIR
    (root / "review").mkdir(exist_ok=True)
    dimensions = REVIEWER_DIMENSIONS if complete_review else REVIEWER_DIMENSIONS[:-1]
    (root / "review" / "review.json").write_text(
        json.dumps(
            {
                "schema_version": "review.v0",
                "reviewer_id": "reviewer-1",
                "executor_id": "executor-1",
                "findings": [
                    {"dimension": d, "severity": "PASS", "detail": f"{d} ok", "accepted": False}
                    for d in dimensions
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def _has_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class Fixture:
    def setUp(self) -> None:  # noqa: N802 - unittest naming
        self.tmp = Path(tempfile.mkdtemp())
        self.timebase = RecordingTimebase()
        self.job = build_job(self.tmp / "job")
        self.path = FastPath(self.job, job_id="sku3", timebase=self.timebase)

    def tearDown(self) -> None:  # noqa: N802
        shutil.rmtree(self.tmp, ignore_errors=True)


class StructuralWiringTests(unittest.TestCase):
    """If a refactor disconnects a P0 module, these fail first."""

    def test_the_eight_semantic_stages_are_declared(self) -> None:
        self.assertEqual(tuple(stage.name for stage in STAGES), SEMANTIC_STAGES)
        self.assertEqual(len(SEMANTIC_STAGES), 8)

    def test_every_required_production_module_is_declared_by_some_stage(self) -> None:
        declared = " ".join(
            " ".join([stage.capability or ""] + list(stage.invariants)) for stage in STAGES
        )
        for module in REQUIRED_PRODUCTION_MODULES:
            with self.subTest(module=module):
                self.assertIn(module, declared)

    def test_the_four_p0_capabilities_are_declared(self) -> None:
        declared = {stage.capability for stage in STAGES}
        self.assertIn("narration_coverage.assess_narration_coverage", declared)
        self.assertIn("audio_program.assess_program", declared)
        self.assertIn("review.parse_review", declared)
        # timebase is invoked by the FINISH THE PICTURE runner rather than declared as
        # the stage's headline capability, because it is an invariant applied to every
        # source range rather than one step of the stage.
        self.assertIn("picture_decision.decide_shot", declared)

    def test_every_declared_capability_resolves(self) -> None:
        for stage in STAGES:
            if stage.capability is None:
                continue
            with self.subTest(stage=stage.name):
                self.assertTrue(callable(resolve_capability(stage.capability)))

    def test_an_unresolvable_capability_is_reported(self) -> None:
        with self.assertRaises(FastPathError):
            resolve_capability("narration_coverage.no_such_function")
        with self.assertRaises(FastPathError):
            resolve_capability("not_a_module.thing")

    def test_every_stage_declares_its_outputs(self) -> None:
        for stage in STAGES:
            with self.subTest(stage=stage.name):
                self.assertTrue(stage.outputs)

    def test_low_level_states_cover_every_semantic_stage(self) -> None:
        for stage in STAGES:
            for low in stage.low_level:
                with self.subTest(stage=stage.name, low=low):
                    self.assertIn(low, STAGE_ORDER)

    def test_the_two_added_low_level_states_exist(self) -> None:
        self.assertIn("PLAN_THE_WORDS", STAGE_ORDER)
        self.assertIn("BUILD_THE_AUDIO", STAGE_ORDER)

    def test_no_existing_low_level_state_was_renamed_or_removed(self) -> None:
        for original in (
            "PREPARE", "ANALYZE", "CANDIDATE_SHOT_POOL", "MATERIAL_COVERAGE",
            "EDITING_PLAN", "EXECUTABLE_TIMELINE", "DAVINCI_EXECUTION", "PREVIEW",
            "REVIEW", "FINAL", "DELIVERY",
        ):
            with self.subTest(state=original):
                self.assertIn(original, STAGE_ORDER)

    def test_the_added_states_sit_between_preview_and_review(self) -> None:
        self.assertLess(STAGE_ORDER.index("PREVIEW"), STAGE_ORDER.index("PLAN_THE_WORDS"))
        self.assertLess(STAGE_ORDER.index("PLAN_THE_WORDS"), STAGE_ORDER.index("BUILD_THE_AUDIO"))
        self.assertLess(STAGE_ORDER.index("BUILD_THE_AUDIO"), STAGE_ORDER.index("REVIEW"))

    def test_every_outcome_maps_to_a_low_level_state(self) -> None:
        self.assertEqual(set(OUTCOME_TO_LOW_LEVEL_STATE), set(OUTCOMES))
        for state in OUTCOME_TO_LOW_LEVEL_STATE.values():
            with self.subTest(state=state):
                self.assertIn(state, ("PASS", "FAILED", "NEEDS_REVIEW"))


class WiringProofTests(Fixture, unittest.TestCase):
    """The production path really calls the module."""

    @unittest.skipUnless(_has_ffmpeg(), "decodable media is required")
    def test_fast_path_calls_shot_understanding(self) -> None:
        from src.ai_autocut import shot_understanding

        with mock.patch.object(
            shot_understanding,
            "analyse_placements",
            wraps=shot_understanding.analyse_placements,
        ) as spy:
            result = self.path.run_stage("UNDERSTAND SHOTS")
        spy.assert_called_once()
        self.assertEqual(result.outcome, "PASS")

    def test_fast_path_calls_narration_coverage(self) -> None:
        from src.ai_autocut import narration_coverage

        with mock.patch.object(
            narration_coverage,
            "assess_narration_coverage",
            wraps=narration_coverage.assess_narration_coverage,
        ) as spy:
            result = self.path.run_stage("PLAN THE WORDS")
        spy.assert_called_once()
        self.assertEqual(result.outcome, "PASS")
        self.assertEqual(result.capability, "narration_coverage.assess_narration_coverage")
        self.assertEqual(len(spy.call_args.args[0]), 3)

    def test_fast_path_calls_audio_program(self) -> None:
        from src.ai_autocut import audio_program

        with mock.patch.object(
            audio_program, "assess_program", wraps=audio_program.assess_program
        ) as spy:
            result = self.path.run_stage("BUILD THE AUDIO")
        spy.assert_called_once()
        self.assertEqual(result.capability, "audio_program.assess_program")
        self.assertEqual(result.outcome, "PASS")

    def test_fast_path_calls_review(self) -> None:
        from src.ai_autocut import review

        with mock.patch.object(review, "parse_review", wraps=review.parse_review) as spy:
            result = self.path.run_stage("REVIEW & REPAIR")
        spy.assert_called_once()
        self.assertEqual(result.capability, "review.parse_review")
        # The reviewer's verdict is PRODUCTION_READY, but a verdict is not a release.
        self.assertEqual(result.outcome, "SUPERVISOR_DECISION_REQUIRED")
        self.assertEqual(result.gate["artifact"], "release/human_release.json")

    def test_fast_path_calls_timebase_for_every_source_range(self) -> None:
        result = self.path.run_stage("FINISH THE PICTURE")
        self.assertEqual(result.outcome, "PASS")
        self.assertEqual(self.timebase.executed, ["U01"])
        self.assertEqual(self.timebase.coverage_checked, [["U01"]])
        self.assertEqual(result.evidence["source_ranges_executed"], 1)

    def test_fast_path_calls_editing_intelligence(self) -> None:
        from src.ai_autocut import editing_intelligence

        with mock.patch.object(
            editing_intelligence,
            "validate_timeline_range",
            wraps=editing_intelligence.validate_timeline_range,
        ) as spy:
            result = self.path.run_stage("PLAN THE EDIT")
        spy.assert_called_once()
        self.assertEqual(result.outcome, "PASS")

    def test_fast_path_calls_picture_decision(self) -> None:
        from src.ai_autocut import picture_decision

        with mock.patch.object(
            picture_decision, "decide_shot", wraps=picture_decision.decide_shot
        ) as spy:
            self.path.run_stage("FINISH THE PICTURE")
        spy.assert_called_once()

    def test_fast_path_calls_job_foundation(self) -> None:
        from src.ai_autocut import job_foundation

        with mock.patch.object(
            job_foundation,
            "verify_source_immutability",
            wraps=job_foundation.verify_source_immutability,
        ) as spy:
            result = self.path.run_stage("PREPARE")
        spy.assert_called_once()
        self.assertEqual(result.outcome, "PASS")


class DisconnectionTests(Fixture, unittest.TestCase):
    """If a stage stopped calling its module, these would fail.

    Each test breaks the capability the stage is declared to use and requires the stage
    to notice. A stage that silently skipped its module would still report PASS here,
    which is exactly the regression these guard against.
    """

    def test_breaking_narration_coverage_changes_the_outcome(self) -> None:
        from src.ai_autocut import narration_coverage

        with mock.patch.object(
            narration_coverage,
            "assess_narration_coverage",
            side_effect=narration_coverage.NarrationCoverageError("broken"),
        ):
            result = self.path.run_stage("PLAN THE WORDS")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("broken", str(result.reason))

    def test_breaking_audio_program_changes_the_outcome(self) -> None:
        from src.ai_autocut import audio_program

        with mock.patch.object(
            audio_program,
            "assess_program",
            side_effect=audio_program.AudioProgramError("broken"),
        ):
            result = self.path.run_stage("BUILD THE AUDIO")
        self.assertEqual(result.outcome, "FAIL")

    def test_breaking_review_changes_the_outcome(self) -> None:
        from src.ai_autocut import review

        with mock.patch.object(
            review, "parse_review", side_effect=review.ReviewContractError("broken")
        ):
            result = self.path.run_stage("REVIEW & REPAIR")
        self.assertEqual(result.outcome, "FAIL")

    def test_removing_the_timebase_adapter_changes_the_outcome(self) -> None:
        self.path.timebase = mock.Mock()
        self.path.timebase.resolve_from_seconds.side_effect = ValueError("no adapter")
        result = self.path.run_stage("FINISH THE PICTURE")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("timebase_adapter", str(result.capability))

    def test_a_bypassing_timebase_is_caught(self) -> None:
        """A range extracted without the adapter must not pass silently."""

        self.timebase.execute = lambda resolution, out_path: None  # type: ignore[assignment]
        self.timebase.executed = []
        result = self.path.run_stage("FINISH THE PICTURE")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("bypass", str(result.reason).lower())


class ArtifactTests(Fixture, unittest.TestCase):
    """The stage's output exists and re-parses through the module's own parser."""

    def test_narration_coverage_artifact_is_a_real_coverage_document(self) -> None:
        result = self.path.run_stage("PLAN THE WORDS")
        document = json.loads((self.job / result.artifacts[0]).read_text(encoding="utf-8"))
        self.assertEqual(document["schema_version"], "commercial_narration_coverage.v1")
        self.assertIn("verdict", document)
        self.assertIn("findings", document)

    def test_audio_program_artifact_carries_all_three_judgements(self) -> None:
        result = self.path.run_stage("BUILD THE AUDIO")
        document = json.loads((self.job / result.artifacts[0]).read_text(encoding="utf-8"))
        self.assertEqual(set(("fit", "sync", "rhythm")) - set(document), set())
        self.assertIn("approved_on_all_three", document)

    def test_review_artifact_is_a_derived_verdict(self) -> None:
        from src.ai_autocut.review import parse_review

        result = self.path.run_stage("REVIEW & REPAIR")
        document = json.loads((self.job / result.artifacts[0]).read_text(encoding="utf-8"))
        self.assertEqual(document["verdict"], "PRODUCTION_READY")
        self.assertTrue(document["requires_human_gate"])
        # The verdict must also be reproducible from the review document itself.
        review_doc = json.loads((self.job / "review" / "review.json").read_text(encoding="utf-8"))
        self.assertEqual(parse_review(review_doc).verdict, document["verdict"])

    def test_timing_profile_is_written_for_every_executed_range(self) -> None:
        self.path.run_stage("FINISH THE PICTURE")
        document = json.loads(
            (self.job / "picture" / "timing_profile.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            document["coordinate_system"],
            "SOURCE_PTS_SECONDS -> CFR_TIMELINE_FRAMES",
        )
        self.assertEqual(len(document["ranges"]), 1)

    def test_state_and_artifact_references_are_checkpointed(self) -> None:
        self.path.step("PLAN THE WORDS")
        state = json.loads((self.job / "fast_path_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["stages"]["PLAN THE WORDS"]["outcome"], "PASS")
        references = json.loads(
            (self.job / "artifact_references.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            references["artifacts"]["narration_coverage"], "copy/narration_coverage.json"
        )


class RefusalTests(Fixture, unittest.TestCase):
    """A wired capability that can never refuse is not wired."""

    def test_a_sku2_style_narration_gap_requires_review(self) -> None:
        """The Second SKU shipped 7.07s of consecutive silence in a 16.23s advert.

        The unit that carries new commercial information is left silent, and the only
        justification offered is that a title already exists. That is a WEAK reason, and
        the production path must stop rather than proceed to paid voice generation.
        """

        job = build_job(self.tmp / "silent", silence_units=True)
        path = FastPath(job, job_id="sku3-silent", timebase=RecordingTimebase())
        result = path.run_stage("PLAN THE WORDS")
        self.assertEqual(result.outcome, "REVIEW_REQUIRED")
        self.assertIn("U04", result.evidence["silent_units"])
        self.assertIn("Paid voice generation must not run", str(result.reason))

    def test_an_undesigned_audio_gap_requires_review(self) -> None:
        job = build_job(self.tmp / "gap", undesigned_gap=True)
        path = FastPath(job, job_id="sku3-gap", timebase=RecordingTimebase())
        result = path.run_stage("BUILD THE AUDIO")
        self.assertEqual(result.outcome, "REVIEW_REQUIRED")
        self.assertGreater(result.evidence["undesigned_silence_seconds"], 0.45)

    def test_fit_alone_is_never_approval(self) -> None:
        """The First SKU audio passed every technical check and was still rejected."""

        job = build_job(self.tmp / "fit", undesigned_gap=True)
        path = FastPath(job, job_id="sku3-fit", timebase=RecordingTimebase())
        result = path.run_stage("BUILD THE AUDIO")
        document = json.loads((job / result.artifacts[0]).read_text(encoding="utf-8"))
        self.assertFalse(document["approved_on_all_three"])

    def test_an_incomplete_review_is_refused(self) -> None:
        job = build_job(self.tmp / "short", complete_review=False)
        path = FastPath(job, job_id="sku3-short", timebase=RecordingTimebase())
        result = path.run_stage("REVIEW & REPAIR")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("refused", str(result.reason))

    def test_a_review_that_needs_repair_requires_review(self) -> None:
        job = build_job(self.tmp / "repair")
        document = json.loads((job / "review" / "review.json").read_text(encoding="utf-8"))
        document["findings"][0]["severity"] = "FAIL"
        (job / "review" / "review.json").write_text(json.dumps(document), encoding="utf-8")
        path = FastPath(job, job_id="sku3-repair", timebase=RecordingTimebase())
        result = path.run_stage("REVIEW & REPAIR")
        self.assertEqual(result.outcome, "REVIEW_REQUIRED")
        self.assertEqual(result.evidence["verdict"], "NEEDS_REPAIR")

    def test_assemble_and_master_gates_on_adapter_evidence(self) -> None:
        """There is no packaging code here, so it gates rather than passing."""

        result = self.path.run_stage("ASSEMBLE & MASTER")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertIsNone(result.capability)
        self.assertEqual(result.gate["producer_type"], "ADAPTER")
        self.assertEqual(result.gate["producer_id"], "packaging-adapter")

    def test_assemble_and_master_refuses_evidence_that_is_a_claim(self) -> None:
        """The stage passes on measured QA, not on an assertion that it was done."""

        (self.job / "assemble").mkdir(exist_ok=True)
        (self.job / "assemble" / "assembly_evidence.json").write_text(
            json.dumps({"master_path": "final/master.mp4"}), encoding="utf-8"
        )
        result = self.path.run_stage("ASSEMBLE & MASTER")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("assemble_master contract", str(result.reason))

    def test_an_uninitialized_job_stops_at_prepare(self) -> None:
        job = build_job(self.tmp / "noinit")
        (job / "source_inventory.json").unlink()
        path = FastPath(job, job_id="sku3-noinit", timebase=RecordingTimebase())
        result = path.run_stage("PREPARE")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.gate["missing_artifact"], "source_inventory.json")
        self.assertEqual(result.gate["producer_type"], "CODEX")

    def test_a_missing_input_blocks_rather_than_passes(self) -> None:
        job = build_job(self.tmp / "missing")
        (job / "copy" / "commercial_units.json").unlink()
        path = FastPath(job, job_id="sku3-missing", timebase=RecordingTimebase())
        result = path.run_stage("PLAN THE WORDS")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertIsNone(result.capability)

    def test_changed_source_material_fails_prepare(self) -> None:
        source = self.job / "source-01.mp4"
        source.write_bytes(b"material changed after the inventory was taken")
        result = self.path.run_stage("PREPARE")
        self.assertEqual(result.outcome, "FAIL")

    def test_a_commercial_unit_without_judgements_is_refused(self) -> None:
        """Creative judgement fields must be stated, never defaulted."""

        job = build_job(self.tmp / "nojudgement")
        document = json.loads(
            (job / "copy" / "commercial_units.json").read_text(encoding="utf-8")
        )
        del document["units"][0]["visual_self_explanatory"]
        (job / "copy" / "commercial_units.json").write_text(
            json.dumps(document), encoding="utf-8"
        )
        path = FastPath(job, job_id="sku3-nojudgement", timebase=RecordingTimebase())
        result = path.run_stage("PLAN THE WORDS")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("judgement", str(result.reason))

    def test_a_source_range_without_a_coordinate_is_refused(self) -> None:
        job = build_job(self.tmp / "nocoord")
        document = json.loads(
            (job / "picture" / "source_ranges.json").read_text(encoding="utf-8")
        )
        del document["ranges"][0]["t_in_seconds"]
        (job / "picture" / "source_ranges.json").write_text(
            json.dumps(document), encoding="utf-8"
        )
        path = FastPath(job, job_id="sku3-nocoord", timebase=RecordingTimebase())
        result = path.run_stage("FINISH THE PICTURE")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("cannot be addressed", str(result.reason))


class RunLevelTests(Fixture, unittest.TestCase):
    """The run as a whole, and its refusal to resolve anything itself."""

    @unittest.skipUnless(_has_ffmpeg(), "decodable media is required")
    def test_a_clean_job_runs_to_the_assembly_producer_gate(self) -> None:
        report = self.path.run()
        self.assertEqual(report.stopped_at, "ASSEMBLE & MASTER")
        self.assertFalse(report.completed)
        outcomes = [result.outcome for result in report.results]
        self.assertEqual(outcomes[:-1], ["PASS"] * 6)
        self.assertEqual(outcomes[-1], "BLOCKED")
        self.assertEqual(
            report.results[-1].gate["missing_artifact"], "assemble/assembly_evidence.json"
        )
        self.assertEqual(report.exit_code, 3)

    def test_the_run_never_auto_resolves_a_review(self) -> None:
        job = build_job(self.tmp / "haltsilent", silence_units=True)
        path = FastPath(job, job_id="sku3-haltsilent", timebase=RecordingTimebase())
        report = path.run()
        self.assertEqual(report.stopped_at, "PLAN THE WORDS")
        self.assertEqual(len(report.results), 5)

    def test_next_stage_reports_the_first_unpassed_stage(self) -> None:
        self.assertEqual(self.path.next_stage(), "PREPARE")
        self.path.step("PREPARE")
        self.assertEqual(self.path.next_stage(), "UNDERSTAND SHOTS")

    def test_a_run_is_resumable_from_its_checkpoint(self) -> None:
        self.path.step("PREPARE")
        state = json.loads((self.job / "fast_path_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["stages"]["PREPARE"]["outcome"], "PASS")
        self.assertEqual(
            state["stages"]["PREPARE"]["low_level"],
            [{"stage": "PREPARE", "state": "PASS"}],
        )

    def test_the_plan_is_the_eight_semantic_stages(self) -> None:
        self.assertEqual(self.path.plan(), SEMANTIC_STAGES)


class StageResultTests(unittest.TestCase):
    def test_a_pass_must_name_its_capability(self) -> None:
        """The core guard: no silent success."""

        with self.assertRaises(FastPathError):
            StageResult(stage="PREPARE", outcome="PASS", capability=None)

    def test_a_blocked_result_may_omit_the_capability(self) -> None:
        result = StageResult(stage="PREPARE", outcome="BLOCKED", capability=None)
        self.assertIsNone(result.capability)

    def test_an_unknown_outcome_is_refused(self) -> None:
        with self.assertRaises(FastPathError):
            StageResult(stage="PREPARE", outcome="MAYBE", capability="x.y")

    def test_an_unknown_stage_is_refused(self) -> None:
        with self.assertRaises(FastPathError):
            StageResult(stage="NOPE", outcome="PASS", capability="x.y")

    def test_halting_outcomes_are_every_non_pass_outcome(self) -> None:
        self.assertEqual(
            set(HALTING_OUTCOMES),
            {
                "REVIEW_REQUIRED",
                "SUPERVISOR_DECISION_REQUIRED",
                "BLOCKED",
                "FAIL",
                "REJECT",
            },
        )
        self.assertNotIn("PASS", HALTING_OUTCOMES)
        self.assertEqual(set(OUTCOMES), set(HALTING_OUTCOMES) | {"PASS"})


if __name__ == "__main__":
    unittest.main()
