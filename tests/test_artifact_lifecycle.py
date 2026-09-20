"""Case E — a closed synthetic job, and the retention rule that follows it.

A Work-produced variant and a DSH-produced variant must not have different
retention behaviour merely because a different Agent created them. The only inputs
to retention are the job's lifecycle state and each artifact's production role, so
these tests never mention an Agent at all.

Case E  a closed synthetic job -> authoritative outputs are distinguishable
                                  from regenerable intermediates

The classification is also checked against the failure it exists to prevent: a
`.mp4` that is a Final Master must not be condemned for its extension, and a `.png`
that is final evidence must not be condemned for its own.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.ai_autocut.artifact_lifecycle import (
    AUTHORITATIVE,
    REGENERABLE,
    STATE_ACCEPTED,
    STATE_ACTIVE,
    STATE_CLOSED,
    STATE_FINAL_REVIEW,
    ArtifactLifecycleError,
    UNCERTAIN,
    authoritative_artifacts,
    build_closeout_report,
    classify_artifact,
    is_prunable_state,
    pruning_candidates,
)


def write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


class SyntheticClosedJob:
    """A deliberately tiny job: two authoritative artifacts, four regenerable ones."""

    def __init__(self, root: Path) -> None:
        self.root = root
        write(root / "final" / "MASTER.mp4", b"M" * 4096)
        write(root / "record" / "producer_brief.md", b"brief")
        write(root / "metadata" / "manifest.json", b"{}")
        write(root / "frames" / "frame_0001.png", b"f" * 2048)
        write(root / "frames" / "frame_0002.png", b"g" * 2048)
        write(root / "proxy" / "proxy.mp4", b"p" * 1024)
        write(root / "scratch" / "ffmpeg_tmp.mov", b"s" * 512)
        write(root / "preview" / "preview.before-producer-repair-v3.mp4", b"v" * 1024)


class ClosedJobClassificationTestCase(unittest.TestCase):
    """Case E — the closed job's authoritative and regenerable sets are separable."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name) / "job"
        SyntheticClosedJob(self.root)
        self.report = build_closeout_report(self.root, state=STATE_CLOSED)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def classification_of(self, suffix: str) -> str:
        for entry in self.report.entries:
            if entry.path.endswith(suffix):
                return entry.classification
        raise AssertionError(f"no artifact ending {suffix!r} in the report")

    def test_case_e_the_master_is_authoritative(self) -> None:
        self.assertEqual(self.classification_of("MASTER.mp4"), AUTHORITATIVE)

    def test_case_e_the_brief_is_authoritative(self) -> None:
        self.assertEqual(self.classification_of("producer_brief.md"), AUTHORITATIVE)

    def test_case_e_frame_dumps_are_regenerable(self) -> None:
        self.assertEqual(self.classification_of("frame_0001.png"), REGENERABLE)
        self.assertEqual(self.classification_of("frame_0002.png"), REGENERABLE)

    def test_case_e_proxies_and_scratch_are_regenerable(self) -> None:
        self.assertEqual(self.classification_of("proxy.mp4"), REGENERABLE)
        self.assertEqual(self.classification_of("ffmpeg_tmp.mov"), REGENERABLE)

    def test_case_e_a_superseded_preview_is_regenerable(self) -> None:
        self.assertEqual(
            self.classification_of("preview.before-producer-repair-v3.mp4"), REGENERABLE
        )

    def test_case_e_an_unidentified_role_is_retained(self) -> None:
        self.assertEqual(self.classification_of("manifest.json"), UNCERTAIN)
        self.assertIn(
            "metadata/manifest.json",
            [entry.path for entry in self.report.entries if entry.classification == UNCERTAIN],
        )

    def test_case_e_authoritative_and_prunable_sets_do_not_overlap(self) -> None:
        authoritative = {entry.path for entry in authoritative_artifacts(self.report)}
        prunable = {entry.path for entry in pruning_candidates(self.report)}
        self.assertEqual(authoritative & prunable, set())
        self.assertTrue(authoritative)
        self.assertTrue(prunable)

    def test_case_e_extension_is_never_the_reason(self) -> None:
        """A .mp4 in final/ and a .mp4 in proxy/ must classify differently."""

        master = next(e for e in self.report.entries if e.path.endswith("MASTER.mp4"))
        proxy = next(e for e in self.report.entries if e.path.endswith("proxy.mp4"))
        self.assertEqual(master.classification, AUTHORITATIVE)
        self.assertEqual(proxy.classification, REGENERABLE)
        self.assertNotIn("extension", master.reason)
        self.assertNotIn("extension", proxy.reason)

    def test_case_e_prunable_bytes_exclude_authoritative_bytes(self) -> None:
        authoritative_bytes = self.report.bytes_for(AUTHORITATIVE)
        self.assertGreater(authoritative_bytes, 0)
        self.assertLess(self.report.prunable_bytes, self.report.bytes_for("REGENERABLE") + 1)
        self.assertGreater(self.report.prunable_bytes, 0)


class ActiveJobProtectionTestCase(unittest.TestCase):
    """An active job is protected by its state, not by the caller's restraint."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name) / "job"
        SyntheticClosedJob(self.root)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_an_active_job_has_nothing_prunable(self) -> None:
        report = build_closeout_report(self.root, state=STATE_ACTIVE)
        self.assertEqual(pruning_candidates(report), ())
        self.assertEqual(report.prunable_bytes, 0)

    def test_every_artifact_is_retained_while_the_job_is_not_closed(self) -> None:
        for state in (STATE_ACTIVE, STATE_FINAL_REVIEW, STATE_ACCEPTED):
            with self.subTest(state=state):
                report = build_closeout_report(self.root, state=state)
                self.assertEqual(report.prunable_bytes, 0)
                self.assertTrue(
                    all(entry.classification == UNCERTAIN for entry in report.entries)
                )

    def test_the_active_decision_is_explained_in_the_reason(self) -> None:
        report = build_closeout_report(self.root, state=STATE_ACTIVE)
        frame = next(e for e in report.entries if e.path.endswith("frame_0001.png"))
        self.assertIn("not prunable", frame.reason)

    def test_only_the_closed_state_permits_pruning(self) -> None:
        self.assertTrue(is_prunable_state(STATE_CLOSED))
        for state in (STATE_ACTIVE, STATE_FINAL_REVIEW, STATE_ACCEPTED):
            with self.subTest(state=state):
                self.assertFalse(is_prunable_state(state))

    def test_an_unknown_state_is_refused(self) -> None:
        with self.assertRaises(ArtifactLifecycleError):
            build_closeout_report(self.root, state="ALMOST_DONE")


class DeclaredRolePrecedenceTestCase(unittest.TestCase):
    """The manifest outranks every heuristic, in both directions."""

    def test_a_declared_role_promotes_a_scratch_looking_path(self) -> None:
        classification, reason = classify_artifact(
            "frames/FINAL-EVIDENCE.png", declared_role=AUTHORITATIVE
        )
        self.assertEqual(classification, AUTHORITATIVE)
        self.assertIn("manifest", reason)

    def test_a_declared_role_demotes_a_record_looking_path(self) -> None:
        classification, _ = classify_artifact(
            "final/superseded-attempt.mp4", declared_role=REGENERABLE
        )
        self.assertEqual(classification, REGENERABLE)

    def test_an_unrecognised_declared_role_is_uncertain(self) -> None:
        classification, _ = classify_artifact("x.bin", declared_role="probably-fine")
        self.assertEqual(classification, UNCERTAIN)


class DuplicateArtifactTestCase(unittest.TestCase):
    """Byte-identical duplicates are the one regenerable case proven by content."""

    def test_an_identical_duplicate_is_regenerable_and_the_original_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "job"
            payload = b"D" * (2 * 1024 * 1024)
            write(root / "selected" / "clip_a.mov", payload)
            write(root / "selected_copy" / "clip_a.mov", payload)
            report = build_closeout_report(root, state=STATE_CLOSED)
            kept = next(e for e in report.entries if e.path.endswith("selected/clip_a.mov"))
            duplicate = next(
                e for e in report.entries if e.path.endswith("selected_copy/clip_a.mov")
            )
            self.assertEqual(kept.classification, UNCERTAIN)
            self.assertEqual(duplicate.classification, REGENERABLE)
            self.assertIn("duplicate", duplicate.reason)

    def test_duplicates_are_not_collapsed_while_the_job_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "job"
            payload = b"D" * (2 * 1024 * 1024)
            write(root / "selected" / "clip_a.mov", payload)
            write(root / "selected_copy" / "clip_a.mov", payload)
            report = build_closeout_report(root, state=STATE_ACTIVE)
            self.assertEqual(report.prunable_bytes, 0)
            self.assertTrue(
                all(entry.sha256 is None for entry in report.entries),
                "an active job must not even hash for duplicate detection",
            )


class ClassifyContractTestCase(unittest.TestCase):
    def test_an_absolute_artifact_path_is_refused(self) -> None:
        with self.assertRaises(ArtifactLifecycleError):
            classify_artifact("/somewhere/else/clip.mp4")

    def test_a_missing_job_workspace_is_refused(self) -> None:
        with self.assertRaises(ArtifactLifecycleError):
            build_closeout_report(Path("/nonexistent/job"))

    def test_a_clean_job_reports_zero_prunable_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "job"
            write(root / "final" / "MASTER.mp4", b"M" * 1024)
            report = build_closeout_report(root, state=STATE_CLOSED)
            self.assertEqual(report.prunable_bytes, 0)
            self.assertEqual(len(authoritative_artifacts(report)), 1)

    def test_the_report_is_serialisable_and_declares_its_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "job"
            SyntheticClosedJob(root)
            payload = build_closeout_report(root, state=STATE_CLOSED).as_dict()
            self.assertEqual(payload["schema_version"], "job_closeout.v1")
            self.assertEqual(payload["state"], STATE_CLOSED)
            self.assertTrue(payload["prunable_state"])
            self.assertIn("prunable_bytes", payload["totals"])


if __name__ == "__main__":
    unittest.main()
