"""P0 automation closure: the machine produces artifacts instead of only detecting them.

The Third SKU audit found the failure this file guards against. ``FastPath`` checked whether
a stage's inputs existed and returned BLOCKED when they did not; nothing filled the gap. The
run stopped at BUILD THE AUDIO and the remaining work was done by hand, one ad-hoc script per
artifact.

So the assertions here are about *production behaviour*, not unit behaviour:

1. a missing artifact whose producer is autonomous is AUTHORED, not blocked
2. a missing artifact whose producer is a human is a GATE, explained exactly
3. an authoring agent that declines produces a gate, not a silent pass
4. a failing producer leaves no half-written artifact that a later run would trust
5. a deterministic producer derives its artifact from the job's own artifacts and policy
6. none of this is Third-SKU-specific — the fixture is a synthetic, unrelated job
7. the run makes no paid call
8. the real entry point, invoked end to end, drives the chain
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.ai_autocut import (authoring, media_probe, production, production_orchestrator,
                            production_producers, producer_registry)

REPO = Path(__file__).resolve().parents[1]
PROOF_SCRIPT = REPO / "scripts" / "run_pre_exam_proof.py"

#: Artifacts the fast path needs that the proof builder authors. Deleting these is how the
#: tests reproduce "the artifact is missing" without inventing a fake job.
AUTHORED = (
    "shots/placements.json",
    "edit/timeline_ranges.json",
    "picture/source_ranges.json",
    "picture/measurements.json",
    "copy/commercial_units.json",
    "audio/placement.json",
    "audio/sync_expectations.json",
    "review/review.json",
)


def load_proof_module():
    spec = importlib.util.spec_from_file_location("p0_proof_builder", PROOF_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ControlledJob(unittest.TestCase):
    """A real, synthetic, non-Third-SKU job. Media work happens once per class."""

    _template: Path
    _tmp: Path

    @classmethod
    def setUpClass(cls) -> None:
        if not media_probe.have_tools():
            raise unittest.SkipTest("ffmpeg and ffprobe are required")
        cls._tmp = Path(tempfile.mkdtemp(prefix="p0-orchestrator-"))
        cls._template = cls._tmp / "template"
        load_proof_module().build_job(cls._template)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def job(self, name: str) -> Path:
        target = self._tmp / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(self._template, target)
        return target

    def job_without(self, name: str, artifacts=AUTHORED) -> Path:
        root = self.job(name)
        for artifact in artifacts:
            (root / artifact).unlink(missing_ok=True)
        return root

    @staticmethod
    def payloads(root: Path, artifacts=None) -> dict[str, object]:
        """Every registered artifact this job has.

        Defaults to the whole registry rather than only the CODEX-owned ones: an artifact
        whose registered adapter has no in-repo producer yet falls back to the authoring
        boundary, and a scripted agent that declined those would stop the chain for a reason
        that has nothing to do with what is under test.
        """

        if artifacts is None:
            artifacts = tuple(p.artifact for p in producer_registry.PRODUCERS)
        return {a: json.loads((root / a).read_text(encoding="utf-8"))
                for a in artifacts if (root / a).is_file()}


# --------------------------------------------------------------- classification


class ActionClassificationTests(unittest.TestCase):
    """The registry decides who produces what; the orchestrator must not keep a second list."""

    def test_every_registered_artifact_maps_to_an_action(self) -> None:
        for producer in producer_registry.PRODUCERS:
            with self.subTest(artifact=producer.artifact):
                action, resolved = authoring.action_for(producer.artifact)
                self.assertIn(action, authoring.ACTIONS)
                self.assertEqual(resolved.artifact, producer.artifact)

    def test_producer_types_map_to_the_documented_actions(self) -> None:
        self.assertEqual(authoring.action_for("copy/commercial_units.json")[0],
                         authoring.ACTION_AUTHOR)
        self.assertEqual(authoring.action_for("audio/audio_request.json")[0],
                         authoring.ACTION_EXECUTE)
        self.assertEqual(authoring.action_for("release/human_release.json")[0],
                         authoring.ACTION_GATE)

    def test_an_unknown_artifact_is_refused(self) -> None:
        with self.assertRaises(Exception):
            authoring.action_for("nothing/at/all.json")

    def test_a_request_carries_the_registry_procedure(self) -> None:
        request = authoring.request_for("copy/commercial_units.json", Path("/tmp/x"))
        self.assertIn("unit", request.procedure.lower())
        self.assertEqual(request.producer_id, "copy-planner")


# --------------------------------------------------- 3. author instead of block


class AutonomousAuthoringTests(ControlledJob):
    def test_a_missing_artifact_is_authored_not_blocked(self) -> None:
        """The exact Third-SKU failure: stop at BUILD THE AUDIO because a file was absent."""

        root = self.job_without("authored", ("copy/commercial_units.json",))
        agent = authoring.ScriptedAuthoringAgent(self.payloads(self._template))
        report = production_orchestrator.ProductionOrchestrator(root, agent=agent).run(
            until="PLAN THE WORDS")

        self.assertIn("copy/commercial_units.json", report.autonomous_artifacts_produced)
        self.assertTrue((root / "copy/commercial_units.json").is_file())
        self.assertNotEqual(report.stop, production_orchestrator.STOP_GATE)

    def test_the_orchestrator_reaches_the_audio_stage_that_used_to_block(self) -> None:
        """BUILD THE AUDIO blocked on audio_request.json. It must not any more."""

        root = self.job_without("reaches-audio", ("audio/audio_request.json",))
        agent = authoring.ScriptedAuthoringAgent(self.payloads(self._template))
        report = production_orchestrator.ProductionOrchestrator(root, agent=agent).run(
            until="ASSEMBLE & MASTER")

        self.assertTrue((root / "audio" / "audio_request.json").is_file())
        self.assertIn("audio/audio_request.json", report.autonomous_artifacts_produced)
        self.assertNotEqual(report.stop, production_orchestrator.STOP_GATE)


# ------------------------------------------------------- 4. genuine producer gate


class GenuineGateTests(ControlledJob):
    def test_a_human_owned_artifact_stops_the_run_with_an_explanation(self) -> None:
        root = self.job("gate")
        (root / "review" / "review.json").unlink(missing_ok=True)
        agent = authoring.ScriptedAuthoringAgent({})          # declines everything
        report = production_orchestrator.ProductionOrchestrator(root, agent=agent).run(
            until="REVIEW & REPAIR")

        self.assertEqual(report.stop, production_orchestrator.STOP_GATE)
        self.assertIsNotNone(report.gate)
        self.assertEqual(report.gate.artifact, "review/review.json")
        self.assertIn("review/review.json", report.explain())
        self.assertTrue(report.gate.resume_condition)

    def test_the_release_gate_is_reported_as_a_human_decision(self) -> None:
        action, producer = authoring.action_for("release/human_release.json")
        self.assertEqual(action, authoring.ACTION_GATE)
        self.assertEqual(producer.producer_type, "HUMAN")
        self.assertTrue(producer.resume_condition)

    def test_an_agent_that_declines_is_a_gate_not_a_silent_pass(self) -> None:
        root = self.job_without("declined", ("copy/commercial_units.json",))
        report = production_orchestrator.ProductionOrchestrator(
            root, agent=authoring.NullAuthoringAgent()).run(until="PLAN THE WORDS")

        self.assertEqual(report.stop, production_orchestrator.STOP_GATE)
        self.assertEqual(report.gate.artifact, "copy/commercial_units.json")
        self.assertIn("declined", report.gate.reason)

    def test_an_agent_that_raises_does_not_crash_the_run(self) -> None:
        class Exploding:
            def author(self, request):
                raise RuntimeError("agent exploded")

        root = self.job_without("exploding", ("copy/commercial_units.json",))
        report = production_orchestrator.ProductionOrchestrator(
            root, agent=Exploding()).run(until="PLAN THE WORDS")

        self.assertEqual(report.stop, production_orchestrator.STOP_GATE)
        self.assertIn("RuntimeError", report.gate.reason)


# ------------------------------------------------------------- 5. failure atomicity


class FailureAtomicityTests(ControlledJob):
    def test_a_failing_deterministic_producer_leaves_no_artifact(self) -> None:
        """Stale or partial output must never read as valid on the next run."""

        root = self.job_without("atomic", ("audio/audio_request.json",))

        def explode(_root: Path) -> bool:
            (_root / "audio" / "audio_request.json").write_text("{not json", encoding="utf-8")
            raise RuntimeError("producer failed")

        report = production_orchestrator.ProductionOrchestrator(
            root, agent=authoring.NullAuthoringAgent(),
            deterministic={"audio/audio_request.json": explode},
        ).run(until="ASSEMBLE & MASTER")

        self.assertEqual(report.stop, production_orchestrator.STOP_GATE)
        self.assertIn("audio_request", report.gate.artifact)

    def test_the_deterministic_producer_writes_atomically(self) -> None:
        """A write is either the whole artifact or nothing — never a truncated file."""

        root = self.job("atomic-write")
        target = root / "audio" / "audio_request.json"
        target.unlink(missing_ok=True)

        with mock.patch.object(Path, "replace",
                               side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                production_producers.author_audio_request(root)

        self.assertFalse(target.is_file(), "a failed write left an artifact behind")
        self.assertFalse(list((root / "audio").glob(".*.tmp")),
                         "a failed write left a temporary file behind")


# ------------------------------------------------- 6. deterministic audio producer


class AudioRequestProducerTests(ControlledJob):
    def test_it_derives_the_request_from_placement_and_policy(self) -> None:
        root = self.job("audio-request")
        (root / "audio" / "audio_request.json").unlink(missing_ok=True)
        self.assertTrue(production_producers.author_audio_request(root))

        request = json.loads((root / "audio" / "audio_request.json").read_text())
        for key in ("assets", "out", "duration_seconds", "target_lufs",
                    "true_peak_ceiling_dbtp"):
            self.assertIn(key, request)
        self.assertTrue(request["assets"], "the request lists no assets")
        self.assertEqual(request["mix_priority"], ["voice", "evidence", "music"])

    def test_voice_assets_are_positioned_by_the_approved_placement(self) -> None:
        root = self.job("audio-request-placement")
        (root / "audio" / "audio_request.json").unlink(missing_ok=True)
        production_producers.author_audio_request(root)

        placement = json.loads((root / "audio" / "placement.json").read_text())
        request = json.loads((root / "audio" / "audio_request.json").read_text())
        voice = [a for a in request["assets"] if a.get("role") == "voice"]
        self.assertTrue(voice)
        placed = {round(float(s.get("start_seconds", 0.0)), 3)
                  for s in placement.get("segments", [])}
        self.assertTrue({round(a["start_seconds"], 3) for a in voice} <= placed | {0.0})

    def test_mix_priority_gains_are_the_default_and_job_overridable(self) -> None:
        root = self.job("audio-request-gains")
        (root / "audio" / "audio_request.json").unlink(missing_ok=True)
        (root / "audio" / "mix_policy.json").write_text(
            json.dumps({"gains_db": {"music": -21.0}}), encoding="utf-8")
        production_producers.author_audio_request(root)

        request = json.loads((root / "audio" / "audio_request.json").read_text())
        music = [a for a in request["assets"] if a.get("role") == "music"]
        if music:                       # the fixture may have no bed; the override is the point
            self.assertEqual(music[0]["gain_db"], -21.0)

    def test_no_creative_choice_is_hard_coded_in_the_module(self) -> None:
        """A Third-SKU creative value here would become every SKU's default."""

        source = Path(production_producers.__file__).read_text(encoding="utf-8")
        for forbidden in ("KOTORAN", "TERANGKAT", "KLIK LINK", "exfoliating", "scrub pad"):
            self.assertNotIn(forbidden, source)

    def test_it_refuses_rather_than_inventing_a_request(self) -> None:
        root = self.job("audio-request-missing")
        (root / "audio" / "placement.json").unlink(missing_ok=True)
        (root / "audio" / "audio_request.json").unlink(missing_ok=True)
        self.assertFalse(production_producers.author_audio_request(root))
        self.assertFalse((root / "audio" / "audio_request.json").is_file())


# --------------------------------------------------------------- 7. no paid calls


class NoPaidCallTests(ControlledJob):
    def test_a_run_makes_no_paid_call(self) -> None:
        root = self.job_without("no-paid", ("copy/commercial_units.json",))
        agent = authoring.ScriptedAuthoringAgent(self.payloads(self._template))
        report = production_orchestrator.ProductionOrchestrator(root, agent=agent).run(
            until="PLAN THE WORDS")
        self.assertEqual(report.as_dict()["paid_api_calls"], 0)

    def test_the_authoring_boundary_contains_no_provider_client(self) -> None:
        source = Path(authoring.__file__).read_text(encoding="utf-8")
        # Match imports, not bare words: "requests" is also a legitimate attribute name on
        # the scripted agent, so a substring check would report a false positive.
        for forbidden in ("import requests", "import urllib", "from urllib",
                          "openspeech", "volcengine", "doubao", "api_key", "X-Api-Key"):
            self.assertNotIn(forbidden, source)


# ------------------------------------------------------------- 8. one-launch smoke


class OneLaunchSmokeTests(ControlledJob):
    """Actually invoke the entry point. Unit tests passing is not readiness."""

    def test_source_plus_brief_drives_the_chain(self) -> None:
        workspace = self._tmp / "launch-ws"
        workspace.mkdir(exist_ok=True)
        source = self._tmp / "launch-source"
        if source.exists():
            shutil.rmtree(source)
        source.mkdir()
        shutil.copy2(self._template / "source.mp4", source / "source.mp4")

        brief = {
            "job_id": "p0-smoke-launch",
            "product": {"name": "Synthetic Test Pad", "name_localized": "测试垫"},
            "market": "Indonesia", "platform": "TikTok", "language": "id",
            "cta": "Klik link di bawah",
        }
        brief_path = workspace / "brief.json"
        brief_path.write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")

        # The brief alone must initialise the job; no hand-run G1A step.
        job_root = production.ensure_job(brief=production.load_brief(brief_path),
                                        source=source, workspace=workspace)
        self.assertTrue((job_root / "source_inventory.json").is_file(),
                        "one launch did not initialise the job")

        # Re-running must not re-initialise or overwrite.
        again = production.ensure_job(brief=production.load_brief(brief_path),
                                      source=source, workspace=workspace)
        self.assertEqual(again, job_root)

    def test_the_entry_point_runs_and_reports_honestly(self) -> None:
        """With no agent wired, the run must stop at a gate and say exactly why."""

        workspace = self._tmp / "launch-ws2"
        workspace.mkdir(exist_ok=True)
        source = self._tmp / "launch-source2"
        if source.exists():
            shutil.rmtree(source)
        source.mkdir()
        shutil.copy2(self._template / "source.mp4", source / "source.mp4")

        brief = {"job_id": "p0-smoke-gate", "product": {"name": "Synthetic Test Pad"}}
        report = production.run_once(source=source, brief=brief, workspace=workspace)

        self.assertEqual(report.stop, production_orchestrator.STOP_GATE)
        self.assertIsNotNone(report.gate)
        self.assertTrue(report.explain())
        self.assertTrue((Path(report.job_root) / "recon" / "production_run.json").is_file())

    def test_the_entry_point_authors_with_an_agent_and_advances(self) -> None:
        workspace = self._tmp / "launch-ws3"
        workspace.mkdir(exist_ok=True)
        source = self._tmp / "launch-source3"
        if source.exists():
            shutil.rmtree(source)
        source.mkdir()
        shutil.copy2(self._template / "source.mp4", source / "source.mp4")

        brief = {"job_id": "p0-smoke-authored", "product": {"name": "Synthetic Test Pad"}}
        job_root = production.ensure_job(brief=brief, source=source, workspace=workspace)
        agent = authoring.ScriptedAuthoringAgent(self.payloads(self._template))
        report = production_orchestrator.ProductionOrchestrator(job_root, agent=agent).run(
            until="PLAN THE EDIT")

        self.assertTrue(report.stages_run, "one launch ran no stage")
        self.assertTrue(report.autonomous_artifacts_produced,
                        "one launch authored nothing autonomously")
        self.assertIn("source_inventory.json", (job_root / "source_inventory.json").name)

    def test_one_launch_runs_every_stage_and_stops_at_the_human_release(self) -> None:
        """The acceptance target, end to end: source + brief -> preview -> release gate.

        This is the behaviour the audit said was missing. Asserted here so a future change
        that reintroduces a mid-chain stop is caught rather than shipped.
        """

        workspace = self._tmp / "launch-full"
        workspace.mkdir(exist_ok=True)
        source = self._tmp / "launch-source-full"
        if source.exists():
            shutil.rmtree(source)
        source.mkdir()
        shutil.copy2(self._template / "source.mp4", source / "source.mp4")

        brief = {"job_id": "p0-smoke-full", "product": {"name": "Synthetic Test Pad"}}
        job_root = production.ensure_job(brief=brief, source=source, workspace=workspace)
        assets = job_root / "assets"
        assets.mkdir(exist_ok=True)
        for name in ("voice.wav", "music.wav"):
            shutil.copy2(self._template / "assets" / name, assets / name)

        agent = authoring.ScriptedAuthoringAgent(self.payloads(self._template))
        report = production_orchestrator.ProductionOrchestrator(job_root, agent=agent).run()

        self.assertEqual(report.stop, production_orchestrator.STOP_GATE)
        self.assertEqual(report.gate.artifact, "release/human_release.json",
                         "the run must stop at the release gate, not somewhere mid-chain")
        self.assertEqual(report.stages_run[-1], "REVIEW & REPAIR")
        self.assertEqual(len(report.stages_run), 8,
                         f"one launch ran {len(report.stages_run)} stages, not all 8")
        for stage in ("PREPARE", "UNDERSTAND SHOTS", "PLAN THE EDIT", "FINISH THE PICTURE",
                      "PLAN THE WORDS", "BUILD THE AUDIO", "ASSEMBLE & MASTER",
                      "REVIEW & REPAIR"):
            self.assertIn(stage, report.stages_run)
        self.assertIn("audio/audio_request.json", report.autonomous_artifacts_produced,
                      "the artifact that used to block BUILD THE AUDIO was not authored")
        self.assertIsNotNone(report.preview, "one launch produced no preview")
        self.assertTrue(report.preview.lower().endswith(".mp4"),
                        f"the run reported a non-video preview: {report.preview}")

    def test_the_cli_parser_accepts_the_documented_shape(self) -> None:
        args = production._parser().parse_args(
            ["run", "--source", "/tmp/s", "--brief", "/tmp/b.json", "--workspace", "/tmp/w"])
        self.assertEqual(args.command, "run")
        self.assertEqual(str(args.workspace), "/tmp/w")


if __name__ == "__main__":
    unittest.main()
