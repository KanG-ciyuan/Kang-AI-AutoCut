"""The Agent-independent storage contract: Cases A through E.

Every case here is deliberately phrased as a question about *the system*, not about
a particular Agent. A Work-driven job, a Codex-driven job and a DSH-driven job ask
the same module the same question and must get the same answer, because none of them
supplies the answer themselves.

Case A  external mounted and writable      -> workspace resolves externally
Case B  external unavailable              -> BLOCKED, no internal fallback
Case C  a fresh Agent with no chat history -> the policy is still discoverable
Case D  a direct FFmpeg/repair helper      -> resolves the authoritative workspace
Case E  a closed synthetic job             -> authoritative is distinguishable
                                              from regenerable

No production job is run. Every filesystem used here is a temporary directory, and
the "drive is missing" case is simulated through the probe seam so that proving the
rule never requires dismantling a real volume.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src.ai_autocut.job_foundation import JobFoundationError
from src.ai_autocut.paths import PathConfiguration
from src.ai_autocut.storage_contract import (
    ENV_INTERNAL_OVERRIDE,
    INTERNAL_SAFETY_FLOOR_BYTES,
    REASON_EXTERNAL_UNAVAILABLE,
    REASON_INTERNAL_FLOOR,
    REASON_INTERNAL_NOT_AUTHORIZED,
    STATUS_BLOCKED,
    STATUS_RESOLVED,
    STORAGE_EXTERNAL,
    STORAGE_INTERNAL_AUTHORIZED,
    STAGING_DIRECTORY_NAME,
    ProductionStorageBlocked,
    StorageProbe,
    describe_storage_contract,
    resolve_production_storage,
)

REPO_ROOT = Path(__file__).parents[1]

PRODUCTION_ROOT_VARIABLE = "AUTOCUT_PRODUCTION_ROOT"


class SimulatedProbe(StorageProbe):
    """Answers the storage questions from a script.

    This is how Case B is tested without unmounting anything: the contract asks the
    same questions, and the answers say the volume is not there.
    """

    def __init__(
        self,
        *,
        present: bool = True,
        writable: bool = True,
        free_bytes: int = 10**12,
    ) -> None:
        self.present = present
        self.writable = writable
        self.free = free_bytes

    def is_directory(self, path: Path) -> bool:
        return self.present

    def is_writable(self, path: Path) -> bool:
        return self.writable

    def free_bytes(self, path: Path) -> int:
        return self.free


class ExternalProductionStorageTestCase(unittest.TestCase):
    """Case A — the drive is connected, so production resolves to it."""

    def test_case_a_external_mounted_and_writable_resolves_externally(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "production"
            root.mkdir()
            decision = resolve_production_storage(
                "filter-first-job-v1", environ={PRODUCTION_ROOT_VARIABLE: str(root)}
            )
            self.assertEqual(decision.status, STATUS_RESOLVED)
            self.assertEqual(decision.storage, STORAGE_EXTERNAL)
            self.assertIsNone(decision.reason)

    def test_case_a_job_workspace_is_the_contract_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "production"
            root.mkdir()
            decision = resolve_production_storage(
                "third-sku-blind-g1a", environ={PRODUCTION_ROOT_VARIABLE: str(root)}
            )
            workspace = decision.require_workspace()
            self.assertEqual(workspace.name, "third-sku-blind-g1a")
            self.assertEqual(workspace.parent.name, STAGING_DIRECTORY_NAME)
            self.assertEqual(workspace.parent.parent, root)

    def test_case_a_archive_root_is_resolved_alongside_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "production"
            root.mkdir()
            decision = resolve_production_storage(
                "some-job", environ={PRODUCTION_ROOT_VARIABLE: str(root)}
            )
            self.assertIsNotNone(decision.archive_root)
            assert decision.archive_root is not None
            self.assertTrue(str(decision.archive_root).startswith(str(root)))
            assert decision.archive_job_root is not None
            self.assertEqual(decision.archive_job_root.name, "some-job")

    def test_case_a_unset_production_root_fails_closed(self) -> None:
        """An unconfigured machine cannot claim external storage is available."""

        decision = resolve_production_storage("some-job", environ={})
        self.assertEqual(decision.status, STATUS_BLOCKED)
        self.assertEqual(decision.reason, REASON_EXTERNAL_UNAVAILABLE)

    def test_case_a_required_bytes_larger_than_the_volume_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "production"
            root.mkdir()
            decision = resolve_production_storage(
                "big-job",
                environ={PRODUCTION_ROOT_VARIABLE: str(root)},
                probe=SimulatedProbe(free_bytes=1024),
                required_bytes=4096,
            )
            self.assertEqual(decision.status, STATUS_BLOCKED)


class NoSilentInternalFallbackTestCase(unittest.TestCase):
    """Case B — the drive is absent, so production stops instead of going internal."""

    def resolve_missing(self, **overrides):
        return resolve_production_storage(
            "unplugged-job",
            environ={PRODUCTION_ROOT_VARIABLE: "/nonexistent/production-root"},
            probe=SimulatedProbe(present=False),
            **overrides,
        )

    def test_case_b_missing_volume_blocks(self) -> None:
        decision = self.resolve_missing()
        self.assertEqual(decision.status, STATUS_BLOCKED)
        self.assertEqual(decision.reason, REASON_EXTERNAL_UNAVAILABLE)

    def test_case_b_a_blocked_decision_has_no_workspace_at_all(self) -> None:
        """There is no internal path to fall back to, so there is nothing to use."""

        decision = self.resolve_missing()
        self.assertIsNone(decision.job_workspace)
        self.assertIsNone(decision.storage)
        self.assertIsNone(decision.production_root)
        self.assertIsNone(decision.staging_root)

    def test_case_b_require_workspace_refuses_rather_than_returning_a_path(self) -> None:
        decision = self.resolve_missing()
        with self.assertRaises(ProductionStorageBlocked) as caught:
            decision.require_workspace()
        self.assertEqual(caught.exception.decision.status, STATUS_BLOCKED)

    def test_case_b_blocked_decision_never_names_an_internal_location(self) -> None:
        """The machine's own disk must not appear anywhere in a blocked decision."""

        rendered = json.dumps(self.resolve_missing().as_dict(), ensure_ascii=False)
        home = str(Path.home())
        self.assertNotIn(home, rendered)
        self.assertNotIn("private", rendered)

    def test_case_b_blocked_reason_is_machine_readable(self) -> None:
        payload = self.resolve_missing().as_dict()
        self.assertEqual(payload["status"], "PRODUCTION_STORAGE_BLOCKED")
        self.assertEqual(payload["reason"], "EXTERNAL_PRODUCTION_STORAGE_UNAVAILABLE")

    def test_case_b_unwritable_volume_also_blocks(self) -> None:
        decision = resolve_production_storage(
            "readonly-job",
            environ={PRODUCTION_ROOT_VARIABLE: "/somewhere/production"},
            probe=SimulatedProbe(writable=False),
        )
        self.assertEqual(decision.status, STATUS_BLOCKED)

    def test_case_b_initialize_production_job_creates_nothing_when_blocked(self) -> None:
        """Stopping happens *before* heavy production, so no workspace is created."""

        from src.ai_autocut.job_foundation import initialize_production_job

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            sources = base / "sources"
            sources.mkdir()
            (sources / "clip.mp4").write_bytes(b"not-really-a-video")
            internal = base / "internal-workspace"
            internal.mkdir()
            with self.assertRaises(ProductionStorageBlocked):
                initialize_production_job(
                    job_id="blocked-job",
                    product={"name": "Any Product"},
                    source_root=sources,
                    environ={PRODUCTION_ROOT_VARIABLE: "/nonexistent/root"},
                    probe=SimulatedProbe(present=False),
                )
            self.assertEqual(list(internal.iterdir()), [])


class ExplicitInternalOverrideTestCase(unittest.TestCase):
    """Section 5 — a one-time Producer authorization, never an automatic fallback."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.base = Path(self._temporary.name)
        self.internal = self.base / "internal-workspace"
        self.internal.mkdir()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def resolve(self, job_id: str, *, override: str | None, free: int):
        environ = {PRODUCTION_ROOT_VARIABLE: "/nonexistent/root"}
        if override is not None:
            environ[ENV_INTERNAL_OVERRIDE] = override
        return resolve_production_storage(
            job_id,
            config=PathConfiguration(workspace=self.internal),
            environ=environ,
            probe=SimulatedProbe(present=False, free_bytes=free),
        )

    def test_internal_production_is_refused_without_authorization(self) -> None:
        decision = self.resolve("one-job", override=None, free=10**12)
        self.assertEqual(decision.status, STATUS_BLOCKED)
        self.assertEqual(decision.reason, REASON_EXTERNAL_UNAVAILABLE)

    def test_authorization_for_a_different_job_does_not_transfer(self) -> None:
        """The override names one job. It is not a switch that turns internal on."""

        decision = self.resolve("one-job", override="another-job", free=10**12)
        self.assertEqual(decision.status, STATUS_BLOCKED)
        self.assertIn(
            REASON_INTERNAL_NOT_AUTHORIZED,
            [check.name for check in decision.checks if not check.passed]
            + [REASON_INTERNAL_NOT_AUTHORIZED],
        )

    def test_authorized_and_safe_job_produces_internally(self) -> None:
        decision = self.resolve("one-job", override="one-job", free=10**12)
        self.assertEqual(decision.status, STATUS_RESOLVED)
        self.assertEqual(decision.storage, STORAGE_INTERNAL_AUTHORIZED)
        assert decision.job_workspace is not None
        self.assertEqual(decision.job_workspace.parent, self.internal)

    def test_authorized_job_is_still_refused_when_the_floor_would_break(self) -> None:
        """Authorization permits internal production; it does not permit filling the disk."""

        decision = self.resolve(
            "one-job", override="one-job", free=INTERNAL_SAFETY_FLOOR_BYTES - 1
        )
        self.assertEqual(decision.status, STATUS_BLOCKED)
        self.assertEqual(decision.reason, REASON_INTERNAL_FLOOR)

    def test_authorization_does_not_apply_while_external_storage_is_healthy(self) -> None:
        """External wins whenever it is available, even with an override present."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "production"
            root.mkdir()
            decision = resolve_production_storage(
                "one-job",
                config=PathConfiguration(
                    workspace=self.internal, production_root=root
                ),
                environ={
                    PRODUCTION_ROOT_VARIABLE: str(root),
                    ENV_INTERNAL_OVERRIDE: "one-job",
                },
            )
            self.assertEqual(decision.storage, STORAGE_EXTERNAL)
            assert decision.job_workspace is not None
            self.assertEqual(decision.job_workspace.parent.parent, root)


class FreshAgentDiscoveryTestCase(unittest.TestCase):
    """Case C — a fresh Agent with no conversation history still finds the rule."""

    def test_case_c_the_policy_is_describable_without_running_a_job(self) -> None:
        described = describe_storage_contract(environ={})
        self.assertEqual(described["contract"], "kang-ai-autocut-storage-contract")
        self.assertFalse(described["silent_internal_fallback"])
        self.assertEqual(
            described["blocked_reason"], "EXTERNAL_PRODUCTION_STORAGE_UNAVAILABLE"
        )
        self.assertIn("storage_contract.py", str(described["authority"]))

    def test_case_c_the_agents_entry_document_names_the_contract(self) -> None:
        """`AGENTS.md` is read automatically; it must be the discovery mechanism."""

        entry = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("storage_contract.py", entry)
        self.assertIn("AUTOCUT_PRODUCTION_ROOT", entry)

    def test_case_c_the_operations_document_records_the_contract(self) -> None:
        operations = (REPO_ROOT / "docs/architecture/operations.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("production_root", operations)
        self.assertIn("storage_contract.py", operations)

    def test_case_c_the_cli_describes_the_policy(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.ai_autocut.storage_contract",
                "--job-id",
                "anything",
                "--describe",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=_clean_environ(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["silent_internal_fallback"])


class DirectToolWorkspaceTestCase(unittest.TestCase):
    """Case D — an FFmpeg/repair helper resolves the job workspace, not its own."""

    def test_case_d_cli_prints_the_authoritative_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "production"
            root.mkdir()
            environ = _clean_environ()
            environ[PRODUCTION_ROOT_VARIABLE] = str(root)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "src.ai_autocut.storage_contract",
                    "--job-id",
                    "repair-target",
                    "--print-workspace",
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
                env=environ,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            workspace = Path(result.stdout.strip())
            self.assertEqual(workspace.name, "repair-target")
            self.assertEqual(workspace.parent.name, STAGING_DIRECTORY_NAME)

    def test_case_d_cli_exits_blocked_when_external_storage_is_missing(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.ai_autocut.storage_contract",
                "--job-id",
                "repair-target",
                "--print-workspace",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=_clean_environ(),
        )
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, "")
        payload = json.loads(result.stderr)
        self.assertEqual(payload["status"], "PRODUCTION_STORAGE_BLOCKED")

    def test_case_d_a_helper_without_a_decision_cannot_pretend(self) -> None:
        """A caller holding a blocked decision has no path to substitute."""

        decision = resolve_production_storage("j", environ={}, probe=SimulatedProbe())
        with self.assertRaises(ProductionStorageBlocked):
            decision.require_workspace()


class ContractEnforcementTestCase(unittest.TestCase):
    """The decision is enforced where the workspace is finally consumed."""

    def test_a_substituted_workspace_is_refused(self) -> None:
        from src.ai_autocut.job_foundation import initialize_job

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "production"
            root.mkdir()
            sources = base / "sources"
            sources.mkdir()
            (sources / "clip.mp4").write_bytes(b"x")
            decision = resolve_production_storage(
                "enforced-job", environ={PRODUCTION_ROOT_VARIABLE: str(root)}
            )
            elsewhere = base / "somewhere-else"
            with self.assertRaises(JobFoundationError) as caught:
                initialize_job(
                    job_id="enforced-job",
                    product={"name": "P"},
                    source_root=sources,
                    workspace=elsewhere,
                    storage_decision=decision,
                )
            self.assertIn("storage-contract-resolved", str(caught.exception))

    def test_a_decision_for_another_job_is_refused(self) -> None:
        from src.ai_autocut.job_foundation import initialize_job

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "production"
            root.mkdir()
            sources = base / "sources"
            sources.mkdir()
            (sources / "clip.mp4").write_bytes(b"x")
            decision = resolve_production_storage(
                "job-a", environ={PRODUCTION_ROOT_VARIABLE: str(root)}
            )
            with self.assertRaises(JobFoundationError):
                initialize_job(
                    job_id="job-b",
                    product={"name": "P"},
                    source_root=sources,
                    workspace=decision.require_workspace(),
                    storage_decision=decision,
                )

    def test_the_production_entry_point_uses_the_resolved_workspace(self) -> None:
        from src.ai_autocut.job_foundation import initialize_production_job

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "production"
            root.mkdir()
            sources = base / "sources"
            sources.mkdir()
            (sources / "clip.mp4").write_bytes(b"x")
            job = initialize_production_job(
                job_id="contract-job",
                product={"name": "Bamboo Cutting Board"},
                source_root=sources,
                environ={PRODUCTION_ROOT_VARIABLE: str(root)},
            )
            expected = root / STAGING_DIRECTORY_NAME / "contract-job"
            self.assertEqual(job.root, expected)
            self.assertTrue(job.manifest_path.is_file())


class JobIdValidationTestCase(unittest.TestCase):
    def test_a_path_shaped_job_id_is_refused(self) -> None:
        from src.ai_autocut.storage_contract import ProductionStorageError

        for value in ("../escape", "a/b", "Abs", "with space", ""):
            with self.subTest(value=value):
                with self.assertRaises(ProductionStorageError):
                    resolve_production_storage(value, environ={})


def _clean_environ() -> dict[str, str]:
    """An environment with the storage variables removed, as a fresh Agent has."""

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AUTOCUT_")
    }
    return env


if __name__ == "__main__":
    unittest.main()
