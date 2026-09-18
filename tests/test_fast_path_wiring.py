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

import importlib.util
import json
from pathlib import Path
import shutil
import shutil
import tempfile
import unittest
from unittest import mock

from src.ai_autocut import fast_path, media_probe
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
from src.ai_autocut.timebase_adapter import TimebaseAdapter, TimebaseAdapterError


REPO = Path(__file__).resolve().parents[1]
PROOF_SCRIPT = REPO / "scripts" / "run_pre_exam_proof.py"


def load_proof_module():
    """The proof job builder, shared with the runbook so there is one source of truth."""

    spec = importlib.util.spec_from_file_location("pre_exam_proof_wiring", PROOF_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def build_job(root: Path) -> Path:
    """A complete real job. The production path now executes, so fixtures must be real."""

    load_proof_module().build_job(root)
    return root


class RealJobFixture(unittest.TestCase):
    """Copies a pre-built real job per test, so the media work happens once."""

    _template: Path
    _tmp: Path

    @classmethod
    def setUpClass(cls) -> None:
        if not media_probe.have_tools():
            raise unittest.SkipTest("ffmpeg and ffprobe are required")
        cls._tmp = Path(tempfile.mkdtemp())
        cls._template = cls._tmp / "template"
        build_job(cls._template)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp())
        self.job = self.work / "job"
        shutil.copytree(self._template, self.job)
        self.path = FastPath(self.job, job_id="sku3-wiring")
        self.job_id = "sku3-wiring"

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def advance_to(self, stage: str) -> None:
        """Run the stages before ``stage`` so it has its real prerequisites on disk."""

        for name in SEMANTIC_STAGES[: SEMANTIC_STAGES.index(stage)]:
            result = self.path.step(name)
            if result.outcome != "PASS":
                self.fail(
                    f"prerequisite stage {name!r} did not pass: {result.outcome} "
                    f"({result.reason})"
                )

    def run_through(self, stage: str) -> None:
        """Run every stage up to and including ``stage``."""

        report = self.path.run(until=stage)
        if not report.results or report.results[-1].outcome != "PASS":
            self.fail(f"could not run through {stage!r}: {report.outcome}")

    def read(self, relative: str) -> dict:
        return json.loads((self.job / relative).read_text(encoding="utf-8"))

    def write(self, relative: str, payload: object) -> None:
        target = self.job / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


class WiringProofTests(RealJobFixture):
    """The production path really calls the module, using the real adapters."""

    def test_fast_path_calls_job_foundation(self) -> None:
        from src.ai_autocut import job_foundation

        with mock.patch.object(
            job_foundation, "verify_source_immutability",
            wraps=job_foundation.verify_source_immutability,
        ) as spy:
            result = self.path.run_stage("PREPARE")
        spy.assert_called_once()
        self.assertEqual(result.outcome, "PASS")

    def test_fast_path_calls_shot_understanding(self) -> None:
        from src.ai_autocut import shot_understanding

        with mock.patch.object(
            shot_understanding, "analyse_placements",
            wraps=shot_understanding.analyse_placements,
        ) as spy:
            result = self.path.run_stage("UNDERSTAND SHOTS")
        spy.assert_called_once()
        self.assertEqual(result.outcome, "PASS")

    def test_fast_path_resolves_placements_from_measured_pts(self) -> None:
        """The window used for analysis is derived from PTS, not from an index/fps guess."""

        with mock.patch.object(
            type(self.path.timebase), "resolve_placement_window",
            wraps=self.path.timebase.resolve_placement_window,
        ) as spy:
            result = self.path.run_stage("UNDERSTAND SHOTS")
        spy.assert_called_once()
        document = self.read("shots/shot_understanding.json")
        self.assertEqual(document["analysis_grid"], "CFR_DERIVED_FROM_MEASURED_PTS")
        self.assertEqual(result.outcome, "PASS")

    def test_fast_path_calls_editing_intelligence(self) -> None:
        from src.ai_autocut import editing_intelligence

        with mock.patch.object(
            editing_intelligence, "validate_timeline_range",
            wraps=editing_intelligence.validate_timeline_range,
        ) as spy:
            result = self.path.run_stage("PLAN THE EDIT")
        spy.assert_called_once()
        self.assertEqual(result.outcome, "PASS")

    def test_fast_path_calls_picture_decision_and_executes_the_picture(self) -> None:
        from src.ai_autocut import picture_decision

        self.advance_to("FINISH THE PICTURE")

        with mock.patch.object(
            picture_decision, "decide_shot", wraps=picture_decision.decide_shot
        ) as spy:
            result = self.path.run_stage("FINISH THE PICTURE")
        spy.assert_called_once()
        self.assertEqual(result.outcome, "PASS")
        # A decision alone is not a pass: a real video artifact must exist.
        self.assertTrue((self.job / "picture" / "picture_master.mp4").is_file())
        self.assertTrue(result.evidence["picture_artifact"]["measured"])

    def test_fast_path_calls_timebase_for_every_source_range(self) -> None:
        self.advance_to("FINISH THE PICTURE")
        with mock.patch.object(
            type(self.path.timebase), "execute", wraps=self.path.timebase.execute
        ) as spy:
            result = self.path.run_stage("FINISH THE PICTURE")
        self.assertEqual(spy.call_count, 2)
        self.assertEqual(result.outcome, "PASS")
        self.assertEqual(result.evidence["source_ranges_executed"], 2)

    def test_fast_path_checks_range_coverage(self) -> None:
        """A unit executed without the adapter must be detectable."""

        self.advance_to("FINISH THE PICTURE")
        with mock.patch.object(
            type(self.path.timebase), "assert_range_coverage",
            wraps=self.path.timebase.assert_range_coverage,
        ) as spy:
            self.path.run_stage("FINISH THE PICTURE")
        self.assertTrue(spy.called, "range coverage was never asserted")
        covered = {unit for call in spy.call_args_list for unit in call.args[0]}
        self.assertEqual(covered, {"U01", "U02"})

    def test_fast_path_calls_narration_coverage(self) -> None:
        from src.ai_autocut import narration_coverage

        self.advance_to("PLAN THE WORDS")

        with mock.patch.object(
            narration_coverage, "assess_narration_coverage",
            wraps=narration_coverage.assess_narration_coverage,
        ) as spy:
            result = self.path.run_stage("PLAN THE WORDS")
        spy.assert_called_once()
        self.assertEqual(result.outcome, "PASS")

    def test_fast_path_calls_audio_program_and_measures_the_mix(self) -> None:
        from src.ai_autocut import audio_program

        self.advance_to("BUILD THE AUDIO")

        with mock.patch.object(
            audio_program, "assess_program", wraps=audio_program.assess_program
        ) as spy:
            result = self.path.run_stage("BUILD THE AUDIO")
        spy.assert_called_once()
        self.assertEqual(result.outcome, "PASS")
        self.assertTrue((self.job / "audio" / "audio_master.wav").is_file())
        self.assertFalse(result.evidence["audio_artifact"]["clipping"])

    def test_fast_path_calls_review(self) -> None:
        from src.ai_autocut import review

        self.advance_to("REVIEW & REPAIR")

        with mock.patch.object(review, "parse_review", wraps=review.parse_review) as spy:
            result = self.path.run_stage("REVIEW & REPAIR")
        spy.assert_called_once()
        # A reviewer verdict is PRODUCTION_READY, but a verdict is not a release.
        self.assertEqual(result.outcome, "SUPERVISOR_DECISION_REQUIRED")

    def test_the_typography_stage_renders_a_real_artifact(self) -> None:
        self.advance_to("PLAN THE WORDS")
        result = self.path.run_stage("PLAN THE WORDS")
        self.assertEqual(result.outcome, "PASS")
        self.assertTrue((self.job / "typography" / "typography_master.mp4").is_file())
        self.assertTrue(result.evidence["typography_artifact"]["measured"])

    def test_the_assemble_stage_produces_and_verifies_a_real_master(self) -> None:
        self.advance_to("ASSEMBLE & MASTER")
        result = self.path.run_stage("ASSEMBLE & MASTER")
        self.assertEqual(result.outcome, "PASS")
        self.assertTrue(self.work.joinpath("job", "final", "master.mp4").is_file())
        self.assertTrue(result.evidence["measured"])


class DisconnectionTests(RealJobFixture):
    """Break the capability and the stage must notice.

    A stage that silently stopped calling its module would still report PASS here,
    which is exactly the regression these guard against.
    """

    def test_breaking_narration_coverage_changes_the_outcome(self) -> None:
        from src.ai_autocut import narration_coverage

        with mock.patch.object(
            narration_coverage, "assess_narration_coverage",
            side_effect=narration_coverage.NarrationCoverageError("broken"),
        ):
            result = self.path.run_stage("PLAN THE WORDS")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("broken", str(result.reason))

    def test_breaking_audio_program_changes_the_outcome(self) -> None:
        from src.ai_autocut import audio_program

        with mock.patch.object(
            audio_program, "assess_program",
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

    def test_breaking_the_timebase_adapter_changes_the_outcome(self) -> None:
        with mock.patch.object(
            type(self.path.timebase), "execute", side_effect=TimebaseAdapterError("broken")
        ):
            result = self.path.run_stage("FINISH THE PICTURE")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("timebase_adapter", str(result.capability))

    def test_breaking_the_placement_resolver_changes_the_outcome(self) -> None:
        with mock.patch.object(
            type(self.path.timebase), "resolve_placement_window",
            side_effect=TimebaseAdapterError("broken"),
        ):
            result = self.path.run_stage("UNDERSTAND SHOTS")
        self.assertEqual(result.outcome, "FAIL")

    def test_removing_the_picture_adapter_request_blocks_the_stage(self) -> None:
        (self.job / "picture" / "picture_request.json").unlink()
        result = self.path.run_stage("FINISH THE PICTURE")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.gate["missing_artifact"], "picture/picture_request.json")


class ArtifactTests(RealJobFixture):
    """The stage's output exists and re-parses through the module's own parser."""

    def test_narration_coverage_artifact_is_a_real_coverage_document(self) -> None:
        self.advance_to("PLAN THE WORDS")
        result = self.path.run_stage("PLAN THE WORDS")
        document = self.read(result.artifacts[0])
        self.assertEqual(document["schema_version"], "commercial_narration_coverage.v1")
        self.assertIn("verdict", document)

    def test_audio_program_artifact_carries_all_three_judgements(self) -> None:
        self.advance_to("BUILD THE AUDIO")
        result = self.path.run_stage("BUILD THE AUDIO")
        document = self.read("audio/audio_program.json")
        for key in ("fit", "sync", "rhythm"):
            self.assertIn(key, document)

    def test_review_artifact_is_a_derived_verdict(self) -> None:
        from src.ai_autocut.review import parse_review

        self.advance_to("REVIEW & REPAIR")

        result = self.path.run_stage("REVIEW & REPAIR")
        document = self.read("review/verdict.json")
        self.assertEqual(document["verdict"], "PRODUCTION_READY")
        self.assertTrue(document["requires_human_gate"])
        self.assertEqual(parse_review(self.read("review/review.json")).verdict, document["verdict"])

    def test_timing_profile_records_the_coordinate_system(self) -> None:
        self.advance_to("FINISH THE PICTURE")
        self.path.run_stage("FINISH THE PICTURE")
        document = self.read("picture/timing_profile.json")
        self.assertEqual(
            document["coordinate_system"], "SOURCE_PTS_SECONDS -> CFR_TIMELINE_FRAMES"
        )
        self.assertEqual(len(document["ranges"]), 2)

    def test_state_and_artifact_references_are_checkpointed(self) -> None:
        self.run_through("PLAN THE WORDS")
        state = self.read("fast_path_state.json")
        self.assertEqual(state["stages"]["PLAN THE WORDS"]["outcome"], "PASS")
        references = self.read("artifact_references.json")
        self.assertEqual(
            references["artifacts"]["narration_coverage"], "copy/narration_coverage.json"
        )


class RefusalTests(RealJobFixture):
    """A wired capability that can never refuse is not wired."""

    def _silence_variant(self) -> None:
        document = self.read("copy/commercial_units.json")
        document["units"].append(
            {
                "unit_id": "U03",
                "start_seconds": 3.0,
                "end_seconds": 4.0,
                "visual_self_explanatory": False,
                "carries_new_commercial_information": True,
                "has_title": True,
                "vo_adds_function_beyond_title": False,
                "explanation_supported": True,
                "vo": {
                    "vo_id": "VO03",
                    "purpose": "SELLING_POINT_EXPANSION",
                    "semantic_unit": "U03",
                    "required": False,
                    "silence_reason": "TITLE_ALREADY_EXISTS",
                    "window_seconds": None,
                },
            }
        )
        self.write("copy/commercial_units.json", document)

    def test_a_sku2_style_narration_gap_requires_review(self) -> None:
        """The Cushion Puff defect: a title treated as sufficient reason for silence."""

        self._silence_variant()
        result = self.path.run_stage("PLAN THE WORDS")
        self.assertEqual(result.outcome, "REVIEW_REQUIRED")
        self.assertIn("U03", result.evidence["silent_units"])
        self.assertIn("Paid voice generation must not run", str(result.reason))

    def test_an_undesigned_audio_gap_requires_review(self) -> None:
        document = self.read("audio/placement.json")
        document.pop("design", None)
        document["segments"][0]["end_seconds"] = 1.0
        document["segments"][1]["start_seconds"] = 2.5
        self.write("audio/placement.json", document)
        result = self.path.run_stage("BUILD THE AUDIO")
        self.assertEqual(result.outcome, "REVIEW_REQUIRED")
        self.assertGreater(result.evidence["undesigned_silence_seconds"], 0.45)

    def test_fit_alone_is_never_approval(self) -> None:
        document = self.read("audio/placement.json")
        document.pop("design", None)
        document["segments"][0]["end_seconds"] = 1.0
        document["segments"][1]["start_seconds"] = 2.5
        self.write("audio/placement.json", document)
        result = self.path.run_stage("BUILD THE AUDIO")
        self.assertEqual(result.outcome, "REVIEW_REQUIRED")
        self.assertNotEqual(result.evidence["fit"], "FAIL")

    def test_an_incomplete_review_is_refused(self) -> None:
        document = self.read("review/review.json")
        document["findings"] = document["findings"][:-1]
        self.write("review/review.json", document)
        result = self.path.run_stage("REVIEW & REPAIR")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("refused", str(result.reason))

    def test_a_critical_finding_returns_reject(self) -> None:
        document = self.read("review/review.json")
        document["findings"][0]["severity"] = "CRITICAL"
        self.write("review/review.json", document)
        result = self.path.run_stage("REVIEW & REPAIR")
        self.assertEqual(result.outcome, "REJECT")
        self.assertEqual(result.exit_code, 7)

    def test_a_missing_input_blocks_with_a_producer_gate(self) -> None:
        (self.job / "copy" / "commercial_units.json").unlink()
        result = self.path.run_stage("PLAN THE WORDS")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.gate["missing_artifact"], "copy/commercial_units.json")
        self.assertEqual(result.gate["producer_type"], "CODEX")

    def test_an_uninitialized_job_gates_at_prepare(self) -> None:
        (self.job / "source_inventory.json").unlink()
        result = self.path.run_stage("PREPARE")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.gate["missing_artifact"], "source_inventory.json")

    def test_changed_source_material_fails_prepare(self) -> None:
        media = Path(self.read("source_inventory.json")["files"][0]["path"])
        media.write_bytes(b"material changed after the inventory was taken")
        result = self.path.run_stage("PREPARE")
        self.assertEqual(result.outcome, "FAIL")

    def test_a_commercial_unit_without_judgements_is_refused(self) -> None:
        document = self.read("copy/commercial_units.json")
        del document["units"][0]["visual_self_explanatory"]
        self.write("copy/commercial_units.json", document)
        result = self.path.run_stage("PLAN THE WORDS")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("judgement", str(result.reason))

    def test_a_source_range_without_a_coordinate_is_refused(self) -> None:
        document = self.read("picture/source_ranges.json")
        document["ranges"][0].pop("t_in_seconds")
        self.write("picture/source_ranges.json", document)
        result = self.path.run_stage("FINISH THE PICTURE")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("cannot be addressed", str(result.reason))

    def test_a_placement_without_a_measured_timestamp_is_refused(self) -> None:
        document = self.read("shots/placements.json")
        document["placements"][0].pop("t_in_seconds")
        self.write("shots/placements.json", document)
        result = self.path.run_stage("UNDERSTAND SHOTS")
        self.assertEqual(result.outcome, "FAIL")

    def test_assembly_evidence_that_is_a_claim_is_refused(self) -> None:
        self.write("assemble/assembly_evidence.json", {"master_path": "final/master.mp4"})
        result = self.path.run_stage("ASSEMBLE & MASTER")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("assemble_master contract", str(result.reason))


class RunLevelTests(RealJobFixture):
    """The run as a whole, and its refusal to resolve anything itself."""

    def test_a_complete_job_reaches_the_human_release_gate(self) -> None:
        report = self.path.run()
        self.assertEqual(report.stopped_at, "REVIEW & REPAIR")
        self.assertFalse(report.completed)
        self.assertEqual(report.outcome, "SUPERVISOR_DECISION_REQUIRED")
        self.assertEqual(report.results[-2].stage, "ASSEMBLE & MASTER")
        self.assertEqual(report.results[-2].outcome, "PASS")

    def test_the_run_never_auto_resolves_a_review(self) -> None:
        document = self.read("audio/placement.json")
        document.pop("design", None)
        document["segments"][0]["end_seconds"] = 1.0
        document["segments"][1]["start_seconds"] = 2.5
        self.write("audio/placement.json", document)
        report = self.path.run()
        self.assertEqual(report.stopped_at, "BUILD THE AUDIO")
        self.assertEqual(report.outcome, "REVIEW_REQUIRED")

    def test_next_stage_reports_the_first_unpassed_stage(self) -> None:
        self.assertEqual(self.path.next_stage(), "PREPARE")
        self.path.step("PREPARE")
        self.assertEqual(self.path.next_stage(), "UNDERSTAND SHOTS")

    def test_the_plan_is_the_eight_semantic_stages(self) -> None:
        self.assertEqual(self.path.plan(), SEMANTIC_STAGES)

    def test_a_completed_stage_is_not_reexecuted(self) -> None:
        self.path.step("PREPARE")
        fresh = FastPath(self.job, job_id=self.job_id)
        report = fresh.run()
        self.assertEqual(report.resumed_from, "UNDERSTAND SHOTS")
        self.assertNotIn("PREPARE", [r.stage for r in report.results])

    def test_invalidating_an_upstream_stage_reopens_everything_downstream(self) -> None:
        """The coherence fix: a downstream PASS may not outlive its cause."""

        self.run_through("PLAN THE WORDS")
        before = self.path.completed_stages()
        self.assertIn("FINISH THE PICTURE", before)
        self.assertIn("PLAN THE WORDS", before)
        invalidated = self.path.invalidate("PLAN THE EDIT", reason="edit changed")
        self.assertIn("PLAN THE EDIT", invalidated)
        self.assertIn("FINISH THE PICTURE", invalidated)
        self.assertIn("PLAN THE WORDS", invalidated)
        self.assertIn("REVIEW & REPAIR", invalidated)
        self.assertNotIn("PLAN THE EDIT", self.path.completed_stages())
        self.assertNotIn("PLAN THE WORDS", self.path.completed_stages())


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
