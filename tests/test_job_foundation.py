from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from src.ai_autocut.job_foundation import (
    JobFoundationError,
    STAGING_QUOTA_BYTES,
    initialize_filter_job,
    validate_staging_path,
    verify_source_immutability,
)


class JobFoundationTests(unittest.TestCase):
    def make_sources(self, root: Path) -> Path:
        source = root / "sources"
        source.mkdir()
        for index in range(16):
            (source / f"filter-{index:02d}.mp4").write_bytes(f"filter-{index}".encode())
        return source

    def initialize(self, root: Path):
        source = self.make_sources(root)
        app = root / "DaVinci Resolve.app"
        app.mkdir()
        return initialize_filter_job(
            job_id="filter-first-job-v1",
            source_root=source,
            workspace=root / "external-workspace",
            staging_root=root / "ascii-staging",
            media_root=root / "media-root",
            davinci_path=app,
        )

    def test_initializes_immutable_inventory_and_resume_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job = self.initialize(Path(temporary))
            inventory = json.loads(job.source_inventory_path.read_text(encoding="utf-8"))["files"]
            self.assertEqual(len(inventory), 16)
            self.assertTrue(verify_source_immutability(inventory))
            self.assertEqual(job.resume_stage(), "ANALYZE")
            self.assertEqual(job.state()["stages"]["PREPARE"]["state"], "PASS")

    def test_passed_stage_is_not_rerun_and_failure_evidence_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job = self.initialize(Path(temporary))
            with self.assertRaises(JobFoundationError):
                job.transition("PREPARE", "RUNNING")
            job.transition("ANALYZE", "RUNNING", evidence={"kind": "started"})
            job.transition("ANALYZE", "FAILED", evidence={"kind": "probe_error", "message": "kept"})
            state = job.state()
            self.assertEqual(state["stages"]["ANALYZE"]["state"], "FAILED")
            self.assertEqual(state["stages"]["ANALYZE"]["evidence"][-1]["message"], "kept")

    def test_refuses_wrong_source_count_and_over_quota_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "ascii-staging"
            staging.mkdir()
            (staging / "too-large.bin").write_bytes(b"1234")
            with self.assertRaises(JobFoundationError):
                validate_staging_path(staging, quota_bytes=3)
            source = root / "sources"
            source.mkdir()
            for index in range(15):
                (source / f"filter-{index:02d}.mp4").write_bytes(b"x")
            with self.assertRaises(JobFoundationError):
                initialize_filter_job(job_id="filter-first-job-v1", source_root=source, workspace=root / "workspace", staging_root=root / "staging", media_root=root / "media", davinci_path=root)

