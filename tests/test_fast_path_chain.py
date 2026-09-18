"""The real production chain, end to end, against a real job.

The Phase 5 inspection rejected the previous version of this file for two reasons: its
fixtures premanufactured every artifact, and it "completed" the chain against a master
that was never created and a hash that was ``"a" * 64``. Both are gone.

What is here now:

* the chain runs on the **real proof job** — real media, the real ``TimebaseAdapter``,
  the real execution adapters, and a master file that is actually measured;
* every required artifact is proven to be gated: removing it produces a gate naming
  exactly which producer must act;
* resume, invalidation, the intervention ledger and the CLI exit codes are exercised
  against that same real job.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from src.ai_autocut import fast_path, media_probe, producer_registry
from src.ai_autocut.fast_path import (
    ASSEMBLY_EVIDENCE_ARTIFACT,
    EXIT_CODES,
    HUMAN_RELEASE_ARTIFACT,
    SEMANTIC_STAGES,
    FastPath,
)
from src.ai_autocut.intervention_ledger import InterventionLedger
from src.ai_autocut.review import REVIEWER_DIMENSIONS

REPO = Path(__file__).resolve().parents[1]
PROOF_SCRIPT = REPO / "scripts" / "run_pre_exam_proof.py"

#: A small, fast substitution for the proof source: three seconds at 540x960.
WIDTH, HEIGHT, FPS, SECONDS = 540, 960, 30, 3
FRAMES = FPS * SECONDS


def load_proof_module():
    spec = importlib.util.spec_from_file_location("pre_exam_proof_chain", PROOF_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ChainFixture(unittest.TestCase):
    """A real job copied per test, so the media work happens once per class."""

    _tmp: Path
    _template: Path

    @classmethod
    def setUpClass(cls) -> None:
        if not media_probe.have_tools():
            raise unittest.SkipTest("ffmpeg and ffprobe are required")
        cls.proof = load_proof_module()
        cls._tmp = Path(tempfile.mkdtemp())
        cls._template = cls._tmp / "template"
        cls.proof.build_job(cls._template)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp())
        self.root = self.work / "job"
        shutil.copytree(self._template, self.root)
        self.job_id = "chain-job"

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def path(self) -> FastPath:
        return FastPath(self.root, job_id=self.job_id)

    def read(self, relative: str) -> dict:
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def write(self, relative: str, payload: object) -> None:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def release(self, *, decision: str = "APPROVED", verdict: str = "PRODUCTION_READY",
                master_sha: str | None = None) -> None:
        evidence = self.read(ASSEMBLY_EVIDENCE_ARTIFACT)
        self.write(
            HUMAN_RELEASE_ARTIFACT,
            {
                "schema_version": "human_release.v1",
                "decision": decision,
                "authority": "Kang",
                "review_verdict": verdict,
                "master_sha256": master_sha or evidence["master_sha256"],
                "statement": "reviewed the assembled master and the review",
            },
        )

    def assemble_first(self) -> None:
        """Produce the assembly evidence the human release must name."""

        report = self.path().run()
        self.assertIn(report.outcome, ("SUPERVISOR_DECISION_REQUIRED",), report.outcome)


class EmptyJobTests(ChainFixture):
    def test_an_empty_job_gates_at_prepare(self) -> None:
        empty = self.work / "empty"
        empty.mkdir()
        report = FastPath(empty, job_id="empty").run()
        self.assertEqual(report.stopped_at, "PREPARE")
        self.assertEqual(report.outcome, "BLOCKED")
        gate = report.results[-1].gate
        self.assertEqual(gate["missing_artifact"], "source_inventory.json")
        self.assertEqual(gate["producer_type"], "CODEX")


class ProducerGateCoverageTests(ChainFixture):
    """Every required artifact is gated. Removing one names exactly who must act."""

    def test_every_required_artifact_produces_a_gate_naming_its_producer(self) -> None:
        for artifact in producer_registry.REQUIRED_INPUT_ARTIFACTS:
            if artifact in (HUMAN_RELEASE_ARTIFACT, ASSEMBLY_EVIDENCE_ARTIFACT):
                # The release gate is a supervisor decision, and the assembly evidence
                # is produced by the packaging adapter from its request — both covered
                # by their own tests below.
                continue
            with self.subTest(artifact=artifact):
                work = Path(tempfile.mkdtemp())
                try:
                    root = work / "job"
                    shutil.copytree(self._template, root)
                    target = root / artifact
                    if target.is_dir():
                        shutil.rmtree(target)
                    elif target.exists():
                        target.unlink()
                    report = FastPath(root, job_id="gate-job").run()
                    gate = report.results[-1].gate
                    self.assertIsNotNone(
                        gate, f"removing {artifact} produced no producer gate"
                    )
                    self.assertEqual(gate["missing_artifact"], artifact)
                    self.assertIn(gate["producer_type"], producer_registry.PRODUCER_TYPES)
                finally:
                    shutil.rmtree(work, ignore_errors=True)

    def test_removing_the_assemble_request_gates_on_the_packaging_adapter(self) -> None:
        (self.root / "assemble" / "assemble_request.json").unlink()
        report = self.path().run()
        gate = report.results[-1].gate
        self.assertIsNotNone(gate)
        self.assertEqual(gate["missing_artifact"], "assemble/assemble_request.json")
        self.assertEqual(gate["producer_type"], "ADAPTER")

    def test_the_chain_runs_to_the_human_release_gate(self) -> None:
        report = self.path().run()
        self.assertEqual(report.stopped_at, "REVIEW & REPAIR")
        self.assertEqual(report.outcome, "SUPERVISOR_DECISION_REQUIRED")
        self.assertEqual(
            [r.outcome for r in report.results],
            ["PASS"] * 7 + ["SUPERVISOR_DECISION_REQUIRED"],
        )

    def test_a_normal_run_reaches_review_after_a_real_master(self) -> None:
        report = self.path().run()
        assemble = next(r for r in report.results if r.stage == "ASSEMBLE & MASTER")
        self.assertEqual(assemble.outcome, "PASS")
        self.assertTrue(assemble.evidence["measured"])
        master = self.root / "final" / "master.mp4"
        self.assertTrue(master.is_file())
        self.assertEqual(
            assemble.evidence["master_sha256"], media_probe.sha256_of_file(master)
        )
        self.assertIn("REVIEW & REPAIR", [r.stage for r in report.results])

    def test_the_full_chain_completes_only_with_a_human_release(self) -> None:
        self.assemble_first()
        self.release()
        report = self.path().run()
        self.assertTrue(report.completed, report.as_dict())
        self.assertEqual(report.exit_code, 0)

    def test_the_timebase_verified_every_placement(self) -> None:
        self.path().run()
        document = self.read("shots/shot_understanding.json")
        self.assertEqual(document["analysis_grid"], "CFR_DERIVED_FROM_MEASURED_PTS")
        self.assertTrue(document["placement_timing"])
        for entry in document["placement_timing"]:
            self.assertEqual(
                entry["coordinate_system"], "SOURCE_PTS_SECONDS -> CFR_TIMELINE_FRAMES"
            )


class ResumeTests(ChainFixture):
    def test_a_completed_stage_is_not_reexecuted_by_a_new_object(self) -> None:
        first = self.path()
        self.assertEqual(first.step("PREPARE").outcome, "PASS")
        second = self.path()
        self.assertEqual(second.completed_stages(), ("PREPARE",))
        report = second.run()
        self.assertEqual(report.resumed_from, "UNDERSTAND SHOTS")
        self.assertNotIn("PREPARE", [r.stage for r in report.results])

    def test_halting_outcomes_are_persisted_with_their_gate(self) -> None:
        (self.root / "shots" / "placements.json").unlink()
        report = self.path().run()
        self.assertEqual(report.stopped_at, "UNDERSTAND SHOTS")
        state = self.read("fast_path_state.json")
        self.assertEqual(state["stages"]["PREPARE"]["outcome"], "PASS")
        self.assertEqual(state["stages"]["UNDERSTAND SHOTS"]["outcome"], "BLOCKED")
        self.assertEqual(
            state["stages"]["UNDERSTAND SHOTS"]["gate"]["missing_artifact"],
            "shots/placements.json",
        )

    def test_stage_cli_checkpoints_through_the_same_state_path(self) -> None:
        code = fast_path.main(["--job-root", str(self.root), "--stage", "PREPARE",
                               "--job-id", self.job_id])
        self.assertEqual(code, 0)
        self.assertEqual(self.read("fast_path_state.json")["stages"]["PREPARE"]["outcome"], "PASS")

    def test_invalidation_cascades_downstream(self) -> None:
        """A downstream PASS may not outlive the stage it depended on."""

        path = self.path()
        self.assertEqual(path.run(until="BUILD THE AUDIO").results[-1].outcome, "PASS")
        self.assertIn("BUILD THE AUDIO", path.completed_stages())
        invalidated = path.invalidate("PLAN THE EDIT", reason="the edit changed")
        self.assertEqual(
            invalidated,
            ("PLAN THE EDIT", "FINISH THE PICTURE", "PLAN THE WORDS",
             "BUILD THE AUDIO", "ASSEMBLE & MASTER", "REVIEW & REPAIR"),
        )
        self.assertNotIn("BUILD THE AUDIO", path.completed_stages())
        self.assertNotEqual(path.next_stage(), None)
        self.assertNotEqual(path.state()["stages"]["BUILD THE AUDIO"]["outcome"], "PASS")

    def test_invalidation_prevents_an_immediate_completed_report(self) -> None:
        """A completed run that is invalidated must not still look completed."""

        path = self.path()
        self.assemble_first()
        self.release()
        self.assertTrue(path.run().completed)

        path.invalidate("PREPARE", reason="source inventory replaced")
        # The run is no longer complete, and the invalidated stage is next again.
        self.assertEqual(path.next_stage(), "PREPARE")
        self.assertNotIn("REVIEW & REPAIR", path.completed_stages())
        self.assertNotIn("FINISH THE PICTURE", path.completed_stages())

        # Re-running re-executes the invalidated stage rather than skipping to the end.
        report = path.run()
        self.assertEqual(report.resumed_from, "PREPARE")
        self.assertEqual(report.results[0].stage, "PREPARE")
        self.assertTrue(report.completed)

    def test_invalidation_is_reflected_in_pipeline_state(self) -> None:
        path = self.path()
        path.run(until="BUILD THE AUDIO")
        pipeline = self.read("pipeline_state.json")
        self.assertEqual(pipeline["stages"]["BUILD_THE_AUDIO"]["state"], "PASS")
        path.invalidate("PLAN THE EDIT", reason="the edit changed")
        pipeline = self.read("pipeline_state.json")
        self.assertEqual(pipeline["stages"]["EDITING_PLAN"]["state"], "PENDING")
        self.assertEqual(pipeline["stages"]["BUILD_THE_AUDIO"]["state"], "PENDING")


class LedgerIntegrationTests(ChainFixture):
    """Gates are recorded because they happened, not because someone remembered."""

    def test_a_producer_gate_is_recorded_with_the_right_actor(self) -> None:
        (self.root / "copy" / "commercial_units.json").unlink()
        self.path().run()
        rows = InterventionLedger(self.root / "intervention_ledger.jsonl").entries()
        gate = next(r for r in rows if "commercial_units.json" in str(r.get("detail", "")))
        # A CODEX producer is not a human, and must not be recorded as one.
        self.assertEqual(gate["actor"], "CODEX_SUPERVISOR")
        self.assertEqual(gate["trigger"], "BLOCKED")

    def test_an_adapter_gate_is_recorded_as_automated(self) -> None:
        (self.root / "audio" / "audio_request.json").unlink()
        self.path().run()
        rows = InterventionLedger(self.root / "intervention_ledger.jsonl").entries()
        gate = next(r for r in rows if "audio_request.json" in str(r.get("detail", "")))
        self.assertEqual(gate["actor"], "AUTOMATED_REPAIR")

    def test_a_repeated_gate_is_not_double_counted(self) -> None:
        (self.root / "shots" / "placements.json").unlink()
        path = self.path()
        path.run()
        path.run()
        rows = InterventionLedger(self.root / "intervention_ledger.jsonl").entries()
        gates = [r for r in rows if "producer gate:shots/placements.json" in str(r.get("detail", ""))]
        self.assertEqual(len(gates), 1)

    def test_a_resolved_gate_is_recorded_when_the_producer_acts(self) -> None:
        (self.root / "shots" / "placements.json").unlink()
        path = self.path()
        path.run()
        shutil.copy(
            self._template / "shots" / "placements.json", self.root / "shots" / "placements.json"
        )
        path.run(until="UNDERSTAND SHOTS")
        rows = InterventionLedger(self.root / "intervention_ledger.jsonl").entries()
        self.assertTrue(
            any(r.get("trigger") == "PRODUCER_GATE_RESOLVED" for r in rows),
            "the resolved producer gate was not recorded",
        )

    def test_the_human_release_gate_is_recorded(self) -> None:
        self.assemble_first()
        rows = InterventionLedger(self.root / "intervention_ledger.jsonl").entries()
        self.assertTrue(
            any(HUMAN_RELEASE_ARTIFACT in str(r.get("detail", "")) for r in rows),
            "the human release gate was not recorded automatically",
        )

    def test_the_successful_release_is_recorded_as_human(self) -> None:
        self.assemble_first()
        self.release()
        self.path().run()
        rows = InterventionLedger(self.root / "intervention_ledger.jsonl").entries()
        release = next(r for r in rows if r.get("trigger") == "HUMAN_RELEASE_APPROVED")
        self.assertEqual(release["actor"], "HUMAN")
        self.assertIn("Kang", release["detail"])

    def test_a_reject_is_recorded_as_a_creative_rejection(self) -> None:
        document = self.read("review/review.json")
        document["findings"][0]["severity"] = "CRITICAL"
        self.write("review/review.json", document)
        self.path().run()
        rows = InterventionLedger(self.root / "intervention_ledger.jsonl").entries()
        self.assertTrue(any(r["kind"] == "CREATIVE_REVIEW_REJECTIONS" for r in rows))


class HumanReleaseGateTests(ChainFixture):
    """A reviewer verdict is not a release."""

    def test_production_ready_alone_does_not_release(self) -> None:
        report = self.path().run()
        self.assertFalse(report.completed)
        self.assertEqual(report.outcome, "SUPERVISOR_DECISION_REQUIRED")
        self.assertNotEqual(
            self.read("fast_path_state.json")["stages"]["REVIEW & REPAIR"]["outcome"], "PASS"
        )

    def test_a_release_naming_the_verified_master_passes(self) -> None:
        self.assemble_first()
        self.release()
        self.assertTrue(self.path().run().completed)

    def test_a_release_that_does_not_name_the_master_is_refused(self) -> None:
        self.assemble_first()
        self.write(
            HUMAN_RELEASE_ARTIFACT,
            {
                "schema_version": "human_release.v1", "decision": "APPROVED",
                "authority": "Kang", "review_verdict": "PRODUCTION_READY",
                "statement": "no master named",
            },
        )
        self.assertEqual(self.path().run().outcome, "FAIL")

    def test_a_release_naming_a_different_master_is_refused(self) -> None:
        self.assemble_first()
        self.release(master_sha="b" * 64)
        report = self.path().run()
        self.assertEqual(report.outcome, "FAIL")
        self.assertIn("does not describe the master", str(report.results[-1].reason))

    def test_a_release_answering_a_different_verdict_is_refused(self) -> None:
        self.assemble_first()
        document = self.read("review/review.json")
        document["findings"][0]["severity"] = "FAIL"
        self.write("review/review.json", document)
        self.release(verdict="PRODUCTION_READY")
        report = self.path().run()
        self.assertEqual(report.outcome, "REVIEW_REQUIRED")

    def test_a_rejected_release_is_a_reject(self) -> None:
        self.assemble_first()
        self.release(decision="REJECTED")
        report = self.path().run()
        self.assertEqual(report.outcome, "REJECT")
        self.assertEqual(report.exit_code, 7)

    def test_a_critical_finding_returns_reject_not_review(self) -> None:
        document = self.read("review/review.json")
        document["findings"][0]["severity"] = "CRITICAL"
        self.write("review/review.json", document)
        report = self.path().run()
        self.assertEqual(report.outcome, "REJECT")
        self.assertEqual(report.stopped_at, "REVIEW & REPAIR")


class ControlledExitCodeTests(unittest.TestCase):
    def test_every_outcome_has_a_documented_non_zero_code(self) -> None:
        self.assertEqual(EXIT_CODES["PASS"], 0)
        for outcome in ("BLOCKED", "REVIEW_REQUIRED", "SUPERVISOR_DECISION_REQUIRED",
                        "FAIL", "REJECT"):
            with self.subTest(outcome=outcome):
                self.assertNotEqual(EXIT_CODES[outcome], 0)
        self.assertEqual(len(set(EXIT_CODES.values())), len(EXIT_CODES))

    def test_the_cli_returns_non_zero_when_a_producer_must_act(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "job").mkdir()
            code = fast_path.main(["--job-root", str(tmp / "job"), "--job-id", "cli-empty"])
            self.assertEqual(code, EXIT_CODES["BLOCKED"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_broken_job_root_is_a_controlled_failure(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "job").mkdir()
            (tmp / "job" / "source_inventory.json").write_text("{not json", encoding="utf-8")
            code = fast_path.main(["--job-root", str(tmp / "job"), "--job-id", "cli-bad"])
            self.assertEqual(code, EXIT_CODES["FAIL"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class CliCompletionTests(ChainFixture):
    @unittest.skipUnless(media_probe.have_tools(), "real media is required")
    def test_the_cli_returns_zero_only_when_complete(self) -> None:
        self.assertEqual(fast_path.main(["--job-root", str(self.root), "--job-id", self.job_id]),
                         EXIT_CODES["SUPERVISOR_DECISION_REQUIRED"])
        self.release()
        self.assertEqual(fast_path.main(["--job-root", str(self.root), "--job-id", self.job_id]), 0)


if __name__ == "__main__":
    unittest.main()
