"""The real execution proof: produce a master and verify it independently.

This is the test the previous phase could not have passed. Its fixtures do not contain
``"a" * 64`` as a hash, and they do not name a master that was never created. They run
the normal production control path against real local media and then **re-measure the
file on disk**.

The proof is deliberately small — three seconds — because what is being proved is
execution and verification, not creative quality.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from src.ai_autocut import media_probe

REPO = Path(__file__).resolve().parents[1]
PROOF_SCRIPT = REPO / "scripts" / "run_pre_exam_proof.py"


def load_proof_module():
    """Load the tracked proof script so the test and the runbook share one builder."""

    spec = importlib.util.spec_from_file_location("pre_exam_proof", PROOF_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(media_probe.have_tools(), "ffmpeg and ffprobe are required")
class RealMasterProofTests(unittest.TestCase):
    def setUp(self) -> None:
        self.proof = load_proof_module()
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "job"
        self.proof.build_job(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_proof_produces_a_real_master(self) -> None:
        code = self.proof.main(["--job-root", str(self.root), "--keep"])
        self.assertEqual(code, 0, "the execution proof did not pass")
        master = self.root / "final" / "master.mp4"
        self.assertTrue(master.is_file(), "final/master.mp4 was not produced")

    def test_the_master_measurements_are_real(self) -> None:
        self.assertEqual(self.proof.main(["--job-root", str(self.root), "--keep"]), 0)
        measured = self.proof.render_evidence(self.root)
        self.assertTrue(measured["MASTER_EXISTS"])
        self.assertEqual(measured["FRAME_COUNT"], self.proof.FRAMES)
        self.assertEqual(measured["FPS"], float(self.proof.FPS))
        self.assertEqual(measured["RESOLUTION"], f"{self.proof.WIDTH}x{self.proof.HEIGHT}")
        self.assertEqual(measured["VIDEO_CODEC"], "h264")
        self.assertEqual(measured["AUDIO_CODEC"], "aac")
        self.assertEqual(measured["BLACK_FRAME_RESULT"], 0)
        self.assertEqual(measured["DUPLICATE_FREEZE_RESULT"], 0)
        self.assertEqual(len(measured["MASTER_SHA256"]), 64)

    def test_the_master_is_deleted_and_the_proof_fails(self) -> None:
        """The proof must fail if the real master is removed."""

        self.assertEqual(self.proof.main(["--job-root", str(self.root), "--keep"]), 0)
        (self.root / "final" / "master.mp4").unlink()
        with self.assertRaises(SystemExit) as caught:
            self.proof.render_evidence(self.root)
        self.assertIn("does not exist", str(caught.exception))

    def test_a_modified_master_fails_verification(self) -> None:
        """The proof must fail if the real master changes after it was verified."""

        self.assertEqual(self.proof.main(["--job-root", str(self.root), "--keep"]), 0)
        master = self.root / "final" / "master.mp4"
        before = media_probe.sha256_of_file(master)
        evidence = json.loads(
            (self.root / "assemble" / "assembly_evidence.json").read_text(encoding="utf-8")
        )
        self.assertEqual(before, evidence["master_sha256"])

        # Re-encode in place: same content, different bytes, different digest.
        tampered = master.with_suffix(".tampered.mp4")
        import subprocess

        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(master),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                "-c:a", "copy", str(tampered),
            ],
            check=True, capture_output=True,
        )
        shutil.move(str(tampered), str(master))
        after = media_probe.sha256_of_file(master)
        self.assertNotEqual(before, after)

        from src.ai_autocut.execution_contracts import (
            ExecutionContractError,
            verify_assembly_evidence,
        )

        with self.assertRaises(ExecutionContractError) as caught:
            verify_assembly_evidence(evidence, job_root=self.root)
        self.assertIn("does not match the file on disk", str(caught.exception))

    def test_the_human_release_names_the_verified_master(self) -> None:
        self.assertEqual(self.proof.main(["--job-root", str(self.root), "--keep"]), 0)
        release = json.loads(
            (self.root / "release" / "human_release.json").read_text(encoding="utf-8")
        )
        evidence = json.loads(
            (self.root / "assemble" / "assembly_evidence.json").read_text(encoding="utf-8")
        )
        self.assertEqual(release["master_sha256"], evidence["master_sha256"])
        self.assertEqual(
            release["master_sha256"], media_probe.sha256_of_file(self.root / "final" / "master.mp4")
        )

    def test_the_run_used_the_real_timebase_adapter(self) -> None:
        """The proof path must not use a fake adapter anywhere."""

        self.assertEqual(self.proof.main(["--job-root", str(self.root), "--keep"]), 0)
        profile = json.loads(
            (self.root / "picture" / "timing_profile.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            profile["coordinate_system"], "SOURCE_PTS_SECONDS -> CFR_TIMELINE_FRAMES"
        )
        self.assertTrue(profile["ranges"])
        for entry in profile["ranges"]:
            self.assertEqual(entry["coordinate_system"], "SOURCE_PTS_SECONDS -> CFR_TIMELINE_FRAMES")

    def test_the_ledger_recorded_the_run_without_operator_action(self) -> None:
        self.assertEqual(self.proof.main(["--job-root", str(self.root), "--keep"]), 0)
        ledger = self.root / "intervention_ledger.jsonl"
        self.assertTrue(ledger.is_file(), "the run recorded no interventions")
        rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertTrue(rows)
        # The human release gate is a system-known event and must be recorded.
        self.assertTrue(
            any("human_release.json" in str(row.get("detail", "")) for row in rows),
            "the human release gate was not recorded automatically",
        )


if __name__ == "__main__":
    unittest.main()
