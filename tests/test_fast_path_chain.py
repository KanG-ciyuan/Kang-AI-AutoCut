"""The real production chain, end to end.

The previous phase was rejected because its tests premanufactured every artifact, which
proved that a validator could validate — not that a production chain runs. This file
does the opposite: it starts from an **empty job directory** and creates each required
artifact **only when the corresponding producer gate asks for it**, then resumes.

That is the property under test:

    PREPARE -> gate -> satisfy -> resume -> next stage -> ... -> ASSEMBLE gate
            -> satisfy -> resume -> REVIEW -> human release -> completed

It also proves the four things independent inspection found missing: resume does not
re-execute completed stages, a normal run reaches REVIEW after assembly evidence, a
human release is a distinct act from a reviewer verdict, and failures return controlled
non-zero exit codes.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src.ai_autocut import fast_path
from src.ai_autocut.fast_path import (
    ASSEMBLY_EVIDENCE_ARTIFACT,
    EXIT_CODES,
    HUMAN_RELEASE_ARTIFACT,
    SEMANTIC_STAGES,
    FastPath,
)
from src.ai_autocut.intervention_ledger import InterventionLedger
from src.ai_autocut.review import REVIEWER_DIMENSIONS
from src.ai_autocut.timebase_adapter import SourceRangeExecution, TimebaseAdapter


def _has_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class FakeTimebase:
    """A timebase stand-in that records placement verification and extraction."""

    def __init__(self, *, vfr: bool = False, disagree: bool = False) -> None:
        self.vfr = vfr
        self.disagree = disagree
        self.verified: list[str] = []
        self.executed: list[str] = []

    def assert_placement_timing(self, **kwargs: object) -> dict[str, object]:
        placement_id = str(kwargs["placement_id"])
        declared = kwargs.get("t_in_seconds")
        if declared is None:
            raise ValueError(
                f"placement {placement_id!r} states no t_in_seconds"
            )
        if self.disagree:
            raise ValueError(
                f"placement {placement_id!r} declares t_in_seconds={declared} but the "
                "measured PTS disagrees"
            )
        self.verified.append(placement_id)
        return {
            "placement_id": placement_id,
            "coordinate_system": "SOURCE_PTS_SECONDS -> CFR_TIMELINE_FRAMES",
            "measured_t_in_seconds": float(declared),
            "measured_duration_seconds": 1.0,
            "assumed_cfr_duration_seconds": 1.0,
            "duration_delta_seconds": 0.0,
            "variable_frame_rate": self.vfr,
            "duration_coordinate": "MEASURED_PTS",
        }

    def resolve_from_seconds(self, **kwargs: object) -> mock.Mock:
        resolution = mock.Mock()
        resolution.unit_id = kwargs["unit_id"]
        resolution.as_dict.return_value = {
            "unit_id": kwargs["unit_id"],
            "coordinate_system": "SOURCE_PTS_SECONDS -> CFR_TIMELINE_FRAMES",
            "t_in_seconds": kwargs["t_in_seconds"],
        }
        return resolution

    def execute(self, resolution: mock.Mock, out_path: str) -> SourceRangeExecution:
        self.executed.append(resolution.unit_id)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"fake")
        return SourceRangeExecution(
            unit_id=resolution.unit_id, source="fake.mp4", t_in_seconds=0.0,
            frames_requested=30, frames_produced=30, out_path=out_path,
        )

    def assert_range_coverage(self, unit_ids: object) -> None:
        expected = list(unit_ids)  # type: ignore[arg-type]
        missing = [u for u in expected if u not in self.executed]
        if missing:
            raise ValueError(f"bypass detected for {missing}")


# ---------------------------------------------------------------------------
# Producers. Each one writes exactly one artifact and nothing else.
# ---------------------------------------------------------------------------


def produce_source_inventory(root: Path, media: Path) -> None:
    payload = {
        "schema_version": "source_inventory.v1",
        "files": [
            {
                "source_id": "SKU3-01",
                "filename": media.name,
                "path": str(media),
                "size_bytes": media.stat().st_size,
                "mtime_ns": media.stat().st_mtime_ns,
                "sha256": hashlib.sha256(media.read_bytes()).hexdigest(),
            }
        ],
    }
    write(root, "source_inventory.json", payload)


def produce_placements(root: Path, media: Path) -> None:
    write(
        root,
        "shots/placements.json",
        {
            "placements": [
                {
                    "placement_id": "P01",
                    "source_id": "SKU3-01",
                    "media_path": str(media),
                    "source_in": 0,
                    "source_out_exclusive": 30,
                    "t_in_seconds": 0.0,
                }
            ]
        },
    )


def produce_timeline_ranges(root: Path) -> None:
    write(
        root,
        "edit/timeline_ranges.json",
        {
            "ranges": [
                {
                    "shot_id": "S01",
                    "role": "identity",
                    "start_frame": 0,
                    "end_frame_exclusive": 30,
                }
            ]
        },
    )


def produce_measurements(root: Path) -> None:
    write(
        root,
        "picture/measurements.json",
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
        },
    )


def produce_commercial_units(root: Path) -> None:
    write(
        root,
        "copy/commercial_units.json",
        {
            "units": [
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
            ]
        },
    )


def produce_audio_placement(root: Path) -> None:
    write(
        root,
        "audio/placement.json",
        {
            "segments": [
                {"segment_id": "VO01", "start_seconds": 0.0, "end_seconds": 1.6, "text": "a"},
                {"segment_id": "VO02", "start_seconds": 1.8, "end_seconds": 3.2, "text": "b"},
            ],
            "design": {
                "VO01->VO02": ["INTENTIONAL_SEMANTIC_PAUSE", "a new evidence unit begins"]
            },
        },
    )


def produce_sync_expectations(root: Path) -> None:
    write(
        root,
        "audio/sync_expectations.json",
        {"sync_tolerance": 0.35, "expectations": []},
    )


def produce_assembly_evidence(root: Path) -> None:
    write(
        root,
        ASSEMBLY_EVIDENCE_ARTIFACT,
        {
            "schema_version": "assembly_evidence.v1",
            "master_path": "final/master.mp4",
            "master_sha256": "a" * 64,
            "frame_count": 487,
            "method": "REMUX",
            "black_frames": 0,
            "duplicate_frames": 0,
            "audio": {"integrated_lufs": -13.98, "true_peak_dbtp": -1.51},
        },
    )


def produce_review(root: Path, *, severities: dict[str, str] | None = None) -> None:
    severities = severities or {}
    write(
        root,
        "review/review.json",
        {
            "schema_version": "review.v0",
            "reviewer_id": "reviewer-1",
            "executor_id": "executor-1",
            "findings": [
                {
                    "dimension": dimension,
                    "severity": severities.get(dimension, "PASS"),
                    "detail": f"{dimension} measured",
                    "accepted": False,
                }
                for dimension in REVIEWER_DIMENSIONS
            ],
        },
    )


def produce_human_release(root: Path, *, decision: str = "APPROVED") -> None:
    write(
        root,
        HUMAN_RELEASE_ARTIFACT,
        {
            "schema_version": "human_release.v1",
            "decision": decision,
            "authority": "Kang",
            "review_verdict": "PRODUCTION_READY",
            "statement": "reviewed the master and the review; approved for release",
        },
    )


def write(root: Path, relative: str, payload: object) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def make_media(path: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


class ChainFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "job"
        self.root.mkdir(parents=True, exist_ok=True)
        self.media = make_media(self.tmp / "source.mp4") if _has_ffmpeg() else None
        self.timebase = FakeTimebase()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self) -> FastPath:
        return FastPath(self.root, job_id="sku3-chain", timebase=self.timebase)


@unittest.skipUnless(_has_ffmpeg(), "decodable media is required")
class RealChainTests(ChainFixture):
    """From an empty directory to a completed run, one producer gate at a time."""

    def test_empty_job_gates_at_prepare(self) -> None:
        report = self.path().run()
        self.assertFalse(report.completed)
        self.assertEqual(report.stopped_at, "PREPARE")
        self.assertEqual(report.results[-1].outcome, "BLOCKED")
        gate = report.results[-1].gate
        self.assertIsNotNone(gate)
        self.assertEqual(gate["missing_artifact"], "source_inventory.json")
        self.assertEqual(gate["producer_type"], "CODEX")

    def test_the_chain_runs_one_gate_at_a_time(self) -> None:
        """Each gate names one producer; satisfying it advances exactly one stage."""

        expected = [
            ("source_inventory.json", "PREPARE"),
            ("shots/placements.json", "UNDERSTAND SHOTS"),
            ("edit/timeline_ranges.json", "PLAN THE EDIT"),
            ("picture/measurements.json", "FINISH THE PICTURE"),
            ("copy/commercial_units.json", "PLAN THE WORDS"),
            ("audio/placement.json", "BUILD THE AUDIO"),
            ("audio/sync_expectations.json", "BUILD THE AUDIO"),
            (ASSEMBLY_EVIDENCE_ARTIFACT, "ASSEMBLE & MASTER"),
            ("review/review.json", "REVIEW & REPAIR"),
        ]
        producers = {
            "source_inventory.json": lambda: produce_source_inventory(self.root, self.media),
            "shots/placements.json": lambda: produce_placements(self.root, self.media),
            "edit/timeline_ranges.json": lambda: produce_timeline_ranges(self.root),
            "picture/measurements.json": lambda: produce_measurements(self.root),
            "copy/commercial_units.json": lambda: produce_commercial_units(self.root),
            "audio/placement.json": lambda: produce_audio_placement(self.root),
            "audio/sync_expectations.json": lambda: produce_sync_expectations(self.root),
            ASSEMBLY_EVIDENCE_ARTIFACT: lambda: produce_assembly_evidence(self.root),
            "review/review.json": lambda: produce_review(self.root),
        }

        produced: list[str] = []
        for _ in range(len(expected) + 2):
            report = self.path().run()
            if report.completed or report.outcome == "SUPERVISOR_DECISION_REQUIRED":
                break
            self.assertEqual(report.outcome, "BLOCKED", report.results[-1].reason)
            artifact = report.results[-1].gate["missing_artifact"]
            self.assertIn(artifact, producers, f"unexpected gate for {artifact}")
            producers[artifact]()
            produced.append(artifact)

        self.assertIn(ASSEMBLY_EVIDENCE_ARTIFACT, produced)
        self.assertEqual(produced, [name for name, _ in expected])

    def test_a_normal_run_reaches_review_after_assembly_evidence(self) -> None:
        produce_source_inventory(self.root, self.media)
        produce_placements(self.root, self.media)
        produce_timeline_ranges(self.root)
        produce_measurements(self.root)
        produce_commercial_units(self.root)
        produce_audio_placement(self.root)
        produce_sync_expectations(self.root)
        produce_assembly_evidence(self.root)
        produce_review(self.root)

        report = self.path().run()
        # It stops at the human gate, not at assembly: assembly passed.
        self.assertEqual(report.stopped_at, "REVIEW & REPAIR")
        self.assertEqual(report.outcome, "SUPERVISOR_DECISION_REQUIRED")
        self.assertIn("ASSEMBLE & MASTER", [r.stage for r in report.results])
        assemble = next(r for r in report.results if r.stage == "ASSEMBLE & MASTER")
        self.assertEqual(assemble.outcome, "PASS")

    def test_the_full_chain_completes_only_with_a_human_release(self) -> None:
        produce_source_inventory(self.root, self.media)
        produce_placements(self.root, self.media)
        produce_timeline_ranges(self.root)
        produce_measurements(self.root)
        produce_commercial_units(self.root)
        produce_audio_placement(self.root)
        produce_sync_expectations(self.root)
        produce_assembly_evidence(self.root)
        produce_review(self.root)
        produce_human_release(self.root)

        report = self.path().run()
        self.assertTrue(report.completed, report.as_dict())
        self.assertEqual(report.outcome, "PASS")
        self.assertEqual(report.exit_code, 0)
        self.assertIsNone(report.stopped_at)
        review_result = next(r for r in report.results if r.stage == "REVIEW & REPAIR")
        self.assertEqual(review_result.outcome, "PASS")
        self.assertEqual(review_result.evidence["release_authority"], "Kang")

    def test_the_timebase_verified_every_placement(self) -> None:
        produce_source_inventory(self.root, self.media)
        produce_placements(self.root, self.media)
        self.path().run()
        self.assertEqual(self.timebase.verified, ["P01"])


class ResumeTests(ChainFixture):
    """Resume is real: a completed stage is not executed again."""

    def test_a_completed_stage_is_not_reexecuted_by_a_new_object(self) -> None:
        produce_source_inventory(self.root, self.media or self.tmp / "placeholder")
        if self.media is None:
            (self.tmp / "placeholder").write_bytes(b"placeholder")
            produce_source_inventory(self.root, self.tmp / "placeholder")
        first = self.path()
        self.assertEqual(first.step("PREPARE").outcome, "PASS")

        # A brand new object, as a new process would create.
        second = self.path()
        self.assertEqual(second.completed_stages(), ("PREPARE",))
        self.assertEqual(second.next_stage(), "UNDERSTAND SHOTS")
        report = second.run()
        self.assertNotIn("PREPARE", [r.stage for r in report.results])
        self.assertEqual(report.resumed_from, "UNDERSTAND SHOTS")

    def test_run_resumes_from_the_first_incomplete_stage(self) -> None:
        media = self.media
        if media is None:
            media = self.tmp / "placeholder"
            media.write_bytes(b"placeholder")
        produce_source_inventory(self.root, media)
        path = self.path()
        path.step("PREPARE")
        report = path.run()
        self.assertEqual(report.resumed_from, "UNDERSTAND SHOTS")
        self.assertEqual(report.results[0].stage, "UNDERSTAND SHOTS")

    def test_a_halted_outcome_is_persisted_and_resumes(self) -> None:
        media = self.media
        if media is None:
            media = self.tmp / "placeholder"
            media.write_bytes(b"placeholder")
        produce_source_inventory(self.root, media)
        path = self.path()
        report = path.run()
        self.assertEqual(report.stopped_at, "UNDERSTAND SHOTS")
        state = json.loads((self.root / "fast_path_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["stages"]["PREPARE"]["outcome"], "PASS")
        self.assertEqual(state["stages"]["UNDERSTAND SHOTS"]["outcome"], "BLOCKED")
        self.assertEqual(
            state["stages"]["UNDERSTAND SHOTS"]["gate"]["missing_artifact"],
            "shots/placements.json",
        )

    def test_invalidate_reopens_a_completed_stage(self) -> None:
        media = self.media
        if media is None:
            media = self.tmp / "placeholder"
            media.write_bytes(b"placeholder")
        produce_source_inventory(self.root, media)
        path = self.path()
        path.step("PREPARE")
        path.invalidate("PREPARE", reason="source material replaced")
        self.assertEqual(path.next_stage(), "PREPARE")
        report = path.run()
        self.assertEqual(report.results[0].stage, "PREPARE")

    def test_stage_cli_checkpoints_through_the_same_state_path(self) -> None:
        media = self.media
        if media is None:
            media = self.tmp / "placeholder"
            media.write_bytes(b"placeholder")
        produce_source_inventory(self.root, media)
        code = fast_path.main(
            ["--job-root", str(self.root), "--stage", "PREPARE", "--job-id", "sku3-chain"]
        )
        self.assertEqual(code, 0)
        state = json.loads((self.root / "fast_path_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["stages"]["PREPARE"]["outcome"], "PASS")


class StateReconciliationTests(ChainFixture):
    def test_low_level_states_are_mirrored_into_pipeline_state(self) -> None:
        media = self.media
        if media is None:
            media = self.tmp / "placeholder"
            media.write_bytes(b"placeholder")
        produce_source_inventory(self.root, media)
        path = self.path()
        path.step("PREPARE")
        pipeline = json.loads(
            (self.root / "pipeline_state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(pipeline["stages"]["PREPARE"]["state"], "PASS")
        self.assertEqual(pipeline["schema_version"], "pipeline_state.v1")

    def test_reconciliation_does_not_reset_a_recorded_state(self) -> None:
        media = self.media
        if media is None:
            media = self.tmp / "placeholder"
            media.write_bytes(b"placeholder")
        produce_source_inventory(self.root, media)
        path = self.path()
        path.step("PREPARE")
        first = json.loads((self.root / "pipeline_state.json").read_text(encoding="utf-8"))
        path.reconcile_pipeline_state()
        second = json.loads((self.root / "pipeline_state.json").read_text(encoding="utf-8"))
        self.assertEqual(first["stages"], second["stages"])


class LedgerIntegrationTests(ChainFixture):
    """Gates are recorded because they happened, not because someone remembered."""

    def test_a_producer_gate_is_recorded_automatically(self) -> None:
        self.path().run()
        rows = InterventionLedger(self.root / "intervention_ledger.jsonl").entries()
        self.assertTrue(rows)
        self.assertEqual(rows[0]["stage"], "PREPARE")
        self.assertIn("producer gate:source_inventory.json", rows[0]["detail"])
        self.assertEqual(rows[0]["trigger"], "BLOCKED")

    def test_a_repeated_gate_is_not_double_counted(self) -> None:
        path = self.path()
        path.run()
        path.run()
        rows = InterventionLedger(self.root / "intervention_ledger.jsonl").entries()
        gates = [r for r in rows if "producer gate:source_inventory.json" in str(r["detail"])]
        self.assertEqual(len(gates), 1)

    def test_the_human_release_gate_is_recorded(self) -> None:
        if not _has_ffmpeg():
            self.skipTest("decodable media is required")
        produce_source_inventory(self.root, self.media)
        produce_placements(self.root, self.media)
        produce_timeline_ranges(self.root)
        produce_measurements(self.root)
        produce_commercial_units(self.root)
        produce_audio_placement(self.root)
        produce_sync_expectations(self.root)
        produce_assembly_evidence(self.root)
        produce_review(self.root)
        self.path().run()
        rows = InterventionLedger(self.root / "intervention_ledger.jsonl").entries()
        release_gates = [
            r for r in rows if HUMAN_RELEASE_ARTIFACT in str(r.get("detail", ""))
        ]
        self.assertTrue(release_gates, "the human release gate was not recorded")
        self.assertEqual(release_gates[0]["trigger"], "SUPERVISOR_DECISION_REQUIRED")

    def test_a_reject_is_recorded_as_a_creative_rejection(self) -> None:
        if not _has_ffmpeg():
            self.skipTest("decodable media is required")
        produce_source_inventory(self.root, self.media)
        produce_placements(self.root, self.media)
        produce_timeline_ranges(self.root)
        produce_measurements(self.root)
        produce_commercial_units(self.root)
        produce_audio_placement(self.root)
        produce_sync_expectations(self.root)
        produce_assembly_evidence(self.root)
        produce_review(self.root, severities={"shot_selection": "CRITICAL"})
        self.path().run()
        rows = InterventionLedger(self.root / "intervention_ledger.jsonl").entries()
        self.assertTrue(any(r["kind"] == "CREATIVE_REVIEW_REJECTIONS" for r in rows))


class HumanReleaseGateTests(ChainFixture):
    """A reviewer verdict is not a release."""

    def setUp(self) -> None:
        super().setUp()
        if not _has_ffmpeg():
            self.skipTest("decodable media is required")
        produce_source_inventory(self.root, self.media)
        produce_placements(self.root, self.media)
        produce_timeline_ranges(self.root)
        produce_measurements(self.root)
        produce_commercial_units(self.root)
        produce_audio_placement(self.root)
        produce_sync_expectations(self.root)
        produce_assembly_evidence(self.root)
        produce_review(self.root)

    def test_production_ready_alone_does_not_release(self) -> None:
        report = self.path().run()
        self.assertFalse(report.completed)
        self.assertEqual(report.outcome, "SUPERVISOR_DECISION_REQUIRED")
        state = json.loads((self.root / "fast_path_state.json").read_text(encoding="utf-8"))
        self.assertNotEqual(state["stages"]["REVIEW & REPAIR"]["outcome"], "PASS")

    def test_a_rejected_release_is_a_reject(self) -> None:
        produce_human_release(self.root, decision="REJECTED")
        report = self.path().run()
        self.assertEqual(report.outcome, "REJECT")
        self.assertEqual(report.exit_code, 7)

    def test_a_release_answering_a_different_verdict_is_refused(self) -> None:
        write(
            self.root,
            HUMAN_RELEASE_ARTIFACT,
            {
                "schema_version": "human_release.v1",
                "decision": "APPROVED",
                "authority": "Kang",
                "review_verdict": "NEEDS_REPAIR",
                "statement": "wrong verdict",
            },
        )
        report = self.path().run()
        self.assertEqual(report.outcome, "FAIL")

    def test_production_ready_with_a_release_passes(self) -> None:
        produce_human_release(self.root)
        report = self.path().run()
        self.assertTrue(report.completed)

    def test_a_critical_finding_returns_reject_not_review(self) -> None:
        produce_review(self.root, severities={"rhythm": "CRITICAL"})
        report = self.path().run()
        self.assertEqual(report.outcome, "REJECT")
        self.assertEqual(report.stopped_at, "REVIEW & REPAIR")


class ControlledExitCodeTests(unittest.TestCase):
    def test_every_outcome_has_a_documented_non_zero_code(self) -> None:
        self.assertEqual(EXIT_CODES["PASS"], 0)
        for outcome in ("BLOCKED", "REVIEW_REQUIRED", "SUPERVISOR_DECISION_REQUIRED", "FAIL", "REJECT"):
            with self.subTest(outcome=outcome):
                self.assertNotEqual(EXIT_CODES[outcome], 0)
        self.assertEqual(len(set(EXIT_CODES.values())), len(EXIT_CODES))

    def test_the_cli_returns_non_zero_when_a_producer_must_act(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            code = fast_path.main(
                ["--job-root", str(tmp / "job"), "--job-id", "sku3-cli"]
            )
            self.assertEqual(code, EXIT_CODES["BLOCKED"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_cli_returns_zero_only_when_complete(self) -> None:
        if not _has_ffmpeg():
            self.skipTest("decodable media is required")
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "job"
            root.mkdir(parents=True)
            media = make_media(tmp / "source.mp4")
            for producer in (
                lambda: produce_source_inventory(root, media),
                lambda: produce_placements(root, media),
                lambda: produce_timeline_ranges(root),
                lambda: produce_measurements(root),
                lambda: produce_commercial_units(root),
                lambda: produce_audio_placement(root),
                lambda: produce_sync_expectations(root),
                lambda: produce_assembly_evidence(root),
                lambda: produce_review(root),
                lambda: produce_human_release(root),
            ):
                producer()
            code = fast_path.main(["--job-root", str(root), "--job-id", "sku3-cli"])
            self.assertEqual(code, 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_broken_job_root_is_a_controlled_failure(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "job").mkdir()
            (tmp / "job" / "source_inventory.json").write_text("{not json", encoding="utf-8")
            code = fast_path.main(["--job-root", str(tmp / "job"), "--job-id", "sku3-bad"])
            self.assertEqual(code, EXIT_CODES["FAIL"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
