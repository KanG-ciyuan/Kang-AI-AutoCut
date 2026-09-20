"""The production storage contract: one authoritative answer to "where does this job write?".

Why this module exists
----------------------
Heavy production media repeatedly landed on the internal system disk because the
location was a *habit* rather than a *contract*: whichever Agent was driving the
job happened to be told, or happened to remember, where renders and frames belong.
Two consequences were measured rather than predicted. A staging cache grew to
roughly 9.1 GB before a human cleaned it by hand, and a later audit found another
multi-gigabyte body of production scratch written to the internal temporary
directory instead of the external production volume.

The fix is not a better-remembered convention. It is a decision the production
system makes and the Agent consumes:

    Agent -> production entry point -> storage preflight -> job workspace -> production

The Agent never invents a path. Any Agent converges on the same workspace, because
the workspace is an output of this module rather than an input from the Agent.

The four rules, in the order they matter
----------------------------------------
1. **External is the only implicit answer.** A resolved production job workspace is
   the stage directory for the job, beneath the configured production root.
2. **No silent internal fallback.** If external production storage is unavailable
   the decision is ``PRODUCTION_STORAGE_BLOCKED`` and production stops *before*
   heavy media is written. It does not quietly write to the internal disk. A
   blocked run is a correct run; it is how the operating Agent learns to tell the
   Producer that the production volume must be connected.
3. **One job at a time may be explicitly authorized internally.** When external
   storage is genuinely unavailable, the Producer may authorize internal production
   for one named job. The authorization names that job and nothing else; there is no
   wildcard and no default-on.
4. **A safety floor protects the internal disk.** Even an authorized internal job
   must leave the configured internal free-space floor intact. Safety is decided
   from measured free space, and a figure that cannot be measured fails closed.

This module performs no directory creation and writes nothing except the
``ensure_job_workspace`` helper, which a caller invokes deliberately. Resolution is
a pure question about the filesystem, which is why it is safe to ask at any time.

Machine independence
--------------------
No location is written into this file. The production root is the logical role
``production_root``, resolved from an environment variable like every other
machine-specific location in this project; see :mod:`src.ai_autocut.paths`. That is
what makes the contract apply equally to Work, Codex, DSH, a future Agent, and a
direct command-line tool.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Mapping, Sequence

from .paths import (
    ENV_PRODUCTION_ROOT,
    ROLE_PRODUCTION_ROOT,
    ROLE_WORKSPACE,
    PathConfiguration,
)


#: Overall verdict. Both values are machine-readable strings by design: an Agent
#: branches on them rather than parsing prose.
STATUS_RESOLVED = "PRODUCTION_STORAGE"
STATUS_BLOCKED = "PRODUCTION_STORAGE_BLOCKED"

#: Which storage a resolved decision selected.
STORAGE_EXTERNAL = "EXTERNAL"
STORAGE_INTERNAL_AUTHORIZED = "INTERNAL_AUTHORIZED"

#: Blocking reasons. ``EXTERNAL_PRODUCTION_STORAGE_UNAVAILABLE`` is the one the
#: operating Agent reports to the Producer: connect the production drive.
REASON_EXTERNAL_UNAVAILABLE = "EXTERNAL_PRODUCTION_STORAGE_UNAVAILABLE"
REASON_EXTERNAL_NOT_WRITABLE = "EXTERNAL_PRODUCTION_STORAGE_NOT_WRITABLE"
REASON_EXTERNAL_INSUFFICIENT_SPACE = "INSUFFICIENT_EXTERNAL_PRODUCTION_SPACE"
REASON_INTERNAL_NOT_AUTHORIZED = "INTERNAL_PRODUCTION_FALLBACK_NOT_AUTHORIZED"
REASON_INTERNAL_UNCONFIGURED = "INTERNAL_PRODUCTION_ROOT_NOT_CONFIGURED"
REASON_INTERNAL_FLOOR = "INTERNAL_SAFETY_FLOOR_WOULD_BE_BREACHED"

#: Directories created beneath the production root. Names are part of the contract
#: and are the same for every Agent; they are not configurable, because two Agents
#: disagreeing about the staging directory name is the defect this module removes.
STAGING_DIRECTORY_NAME = "AI-AutoCut-Staging"
ARCHIVE_DIRECTORY_NAME = "AI-AutoCut-Archive"
ARCHIVE_JOBS_DIRECTORY_NAME = "jobs"

#: Internal free space that must remain after an authorized internal job is placed.
#: A floor rather than a quota: the disk must still be usable by the machine after
#: production finishes.
INTERNAL_SAFETY_FLOOR_BYTES = 30 * 1024 * 1024 * 1024

#: Names exactly one job id that the Producer authorized for internal production.
#: Not a boolean. A boolean switch is how a one-time exception becomes a policy.
ENV_INTERNAL_OVERRIDE = "AUTOCUT_INTERNAL_PRODUCTION_JOB"

#: Exit codes for the module CLI.
EXIT_RESOLVED = 0
EXIT_CONTRACT_ERROR = 1
EXIT_BLOCKED = 3

_USAGE = (
    "usage: python3 -m src.ai_autocut.storage_contract --job-id JOB_ID "
    "[--required-bytes N] [--print-workspace]"
)

_JOB_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-"


class ProductionStorageError(ValueError):
    """Raised when the contract is asked a malformed question."""


class ProductionStorageBlocked(RuntimeError):
    """Raised when production must stop because storage is not safe to use.

    Carries the decision, so a caller reports the reason instead of inventing one.
    """

    def __init__(self, decision: "StorageDecision") -> None:
        self.decision = decision
        detail = decision.reason or REASON_EXTERNAL_UNAVAILABLE
        super().__init__(
            f"{STATUS_BLOCKED}: {detail} (job {decision.job_id!r}); "
            "connect the external production storage, or have the Producer "
            f"authorize internal production for this job via {ENV_INTERNAL_OVERRIDE}"
        )


class StorageProbe:
    """The filesystem questions the contract asks.

    Held as an object rather than called directly so a test can answer them without
    dismantling a real volume. Every method is read-only.
    """

    def is_directory(self, path: Path) -> bool:
        try:
            return Path(path).is_dir()
        except OSError:
            return False

    def is_writable(self, path: Path) -> bool:
        target = Path(path)
        try:
            if target.is_dir():
                return os.access(target, os.W_OK)
            parent = target.parent
            return parent.is_dir() and os.access(parent, os.W_OK)
        except OSError:
            return False

    def free_bytes(self, path: Path) -> int:
        """Free bytes at ``path``, or ``0`` when the figure cannot be measured.

        Zero is the conservative answer: an unmeasurable disk is treated as full,
        so an unreadable volume can never authorize a write.
        """

        target = Path(path)
        try:
            if not target.exists():
                target = target.parent
            return int(shutil.disk_usage(str(target)).free)
        except OSError:
            return 0


@dataclass(frozen=True)
class StorageCheck:
    """One question the preflight asked and the answer it got."""

    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class StorageDecision:
    """The authoritative storage answer for one job.

    ``job_workspace`` is the value every downstream component consumes. A blocked
    decision has ``job_workspace = None`` on purpose: there is no internal path to
    fall back to, so a caller that ignores ``status`` fails on ``None`` rather than
    silently writing somewhere unexpected.
    """

    status: str
    storage: str | None
    reason: str | None
    job_id: str
    checks: tuple[StorageCheck, ...] = ()
    production_root: Path | None = None
    staging_root: Path | None = None
    archive_root: Path | None = None
    job_workspace: Path | None = None
    archive_job_root: Path | None = None

    @property
    def blocked(self) -> bool:
        return self.status == STATUS_BLOCKED

    @property
    def resolved(self) -> bool:
        return self.status == STATUS_RESOLVED

    def require_workspace(self) -> Path:
        """Return the resolved job workspace, or refuse to continue."""

        if self.job_workspace is None:
            raise ProductionStorageBlocked(self)
        return self.job_workspace

    def as_dict(self) -> dict[str, object]:
        """A report-safe mapping. Runtime evidence may carry machine paths."""

        return {
            "status": self.status,
            "storage": self.storage,
            "reason": self.reason,
            "job_id": self.job_id,
            "production_root": _text(self.production_root),
            "staging_root": _text(self.staging_root),
            "archive_root": _text(self.archive_root),
            "job_workspace": _text(self.job_workspace),
            "archive_job_root": _text(self.archive_job_root),
            "checks": [check.as_dict() for check in self.checks],
        }


def _text(value: Path | None) -> str | None:
    return None if value is None else str(value)


def validate_job_id(job_id: object) -> str:
    """Job ids are logical identifiers, and they become a single path component."""

    if not isinstance(job_id, str) or not job_id:
        raise ProductionStorageError("job id must be a non-empty string")
    offending = sorted({character for character in job_id if character not in _JOB_ID_ALPHABET})
    if offending:
        raise ProductionStorageError(
            "job id must be lowercase ASCII letters, digits, and hyphens; "
            f"rejected: {', '.join(repr(item) for item in offending)}"
        )
    if job_id.startswith("-") or job_id.endswith("-"):
        raise ProductionStorageError("job id must not begin or end with a hyphen")
    return job_id


def _require_non_negative(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProductionStorageError(f"{label} must be an integer number of bytes")
    if value < 0:
        raise ProductionStorageError(f"{label} must not be negative")
    return value


def resolve_production_storage(
    job_id: str,
    *,
    config: PathConfiguration | None = None,
    environ: Mapping[str, str] | None = None,
    probe: StorageProbe | None = None,
    required_bytes: int = 0,
    internal_free_floor_bytes: int = INTERNAL_SAFETY_FLOOR_BYTES,
) -> StorageDecision:
    """Decide where ``job_id`` produces, and refuse when that cannot be answered.

    ``required_bytes`` is the caller's own estimate of the heavy media this job will
    write. The default of ``0`` means *no reliable estimate exists*, which is the
    normal case before a job runs; the contract then checks presence and writability
    rather than blocking on an invented number. A caller that genuinely knows the
    figure should pass it.

    ``internal_free_floor_bytes`` is always enforced on the internal path, because
    internal free space is always measurable.
    """

    validate_job_id(job_id)
    _require_non_negative(required_bytes, "required_bytes")
    _require_non_negative(internal_free_floor_bytes, "internal_free_floor_bytes")

    environment: Mapping[str, str] = os.environ if environ is None else environ
    if not isinstance(environment, Mapping):
        raise ProductionStorageError("environ must be a mapping")
    configuration = (
        PathConfiguration.from_environ(environment) if config is None else config
    )
    if not isinstance(configuration, PathConfiguration):
        raise ProductionStorageError("config must be a PathConfiguration")
    active = probe if probe is not None else StorageProbe()
    if not isinstance(active, StorageProbe):
        raise ProductionStorageError("probe must be a StorageProbe")

    checks: list[StorageCheck] = []

    production_root = configuration.get(ROLE_PRODUCTION_ROOT)
    if production_root is None:
        checks.append(
            StorageCheck(
                "external_configured",
                False,
                f"logical role {ROLE_PRODUCTION_ROOT!r} is unset; "
                f"set {ENV_PRODUCTION_ROOT} to the external production storage root",
            )
        )
        return _blocked(
            job_id,
            REASON_EXTERNAL_UNAVAILABLE,
            checks,
            environment,
            required_bytes,
            internal_free_floor_bytes,
            configuration,
            active,
        )
    checks.append(
        StorageCheck("external_configured", True, f"{production_root}")
    )

    if not active.is_directory(production_root):
        checks.append(
            StorageCheck(
                "external_mounted",
                False,
                f"production root is not a mounted directory: {production_root}",
            )
        )
        return _blocked(
            job_id,
            REASON_EXTERNAL_UNAVAILABLE,
            checks,
            environment,
            required_bytes,
            internal_free_floor_bytes,
            configuration,
            active,
        )
    checks.append(StorageCheck("external_mounted", True, f"{production_root}"))

    staging_root = production_root / STAGING_DIRECTORY_NAME
    archive_root = production_root / ARCHIVE_DIRECTORY_NAME

    if not active.is_writable(staging_root):
        checks.append(
            StorageCheck(
                "external_writable",
                False,
                f"staging root is not writable: {staging_root}",
            )
        )
        return _blocked(
            job_id,
            REASON_EXTERNAL_NOT_WRITABLE,
            checks,
            environment,
            required_bytes,
            internal_free_floor_bytes,
            configuration,
            active,
        )
    checks.append(StorageCheck("external_writable", True, f"{staging_root}"))

    free_bytes = active.free_bytes(staging_root)
    if free_bytes < required_bytes:
        checks.append(
            StorageCheck(
                "external_space",
                False,
                f"external free space {free_bytes} B is below the job requirement "
                f"{required_bytes} B",
            )
        )
        return _blocked(
            job_id,
            REASON_EXTERNAL_INSUFFICIENT_SPACE,
            checks,
            environment,
            required_bytes,
            internal_free_floor_bytes,
            configuration,
            active,
        )
    checks.append(
        StorageCheck(
            "external_space",
            True,
            f"{free_bytes} B free, requirement {required_bytes} B",
        )
    )

    job_workspace = staging_root / job_id
    checks.append(
        StorageCheck(
            "job_workspace_resolvable",
            True,
            f"job workspace resolves to {job_workspace}",
        )
    )
    return StorageDecision(
        status=STATUS_RESOLVED,
        storage=STORAGE_EXTERNAL,
        reason=None,
        job_id=job_id,
        checks=tuple(checks),
        production_root=production_root,
        staging_root=staging_root,
        archive_root=archive_root,
        job_workspace=job_workspace,
        archive_job_root=archive_root / ARCHIVE_JOBS_DIRECTORY_NAME / job_id,
    )


def _blocked(
    job_id: str,
    reason: str,
    checks: list[StorageCheck],
    environment: Mapping[str, str],
    required_bytes: int,
    internal_free_floor_bytes: int,
    configuration: PathConfiguration,
    probe: StorageProbe,
) -> StorageDecision:
    """Fail closed, unless the Producer authorized *this* job internally.

    Reaching here always means external production storage was unusable. The
    top-level reason stays the external failure, because that is what the operating
    Agent must report. Whether an internal override was attempted, and why it was
    refused, is recorded as checks.
    """

    authorized = environment.get(ENV_INTERNAL_OVERRIDE, "")
    if isinstance(authorized, str):
        authorized = authorized.strip()

    if authorized != job_id:
        checks.append(
            StorageCheck(
                "internal_override_authorized",
                False,
                f"{ENV_INTERNAL_OVERRIDE} does not name {job_id!r}; "
                "internal production is not authorized for this job",
            )
        )
        return StorageDecision(
            status=STATUS_BLOCKED,
            storage=None,
            reason=reason,
            job_id=job_id,
            checks=tuple(checks),
        )

    checks.append(
        StorageCheck(
            "internal_override_authorized",
            True,
            f"{ENV_INTERNAL_OVERRIDE} authorizes internal production for {job_id!r}",
        )
    )

    internal_root = configuration.get(ROLE_WORKSPACE)
    if internal_root is None:
        checks.append(
            StorageCheck(
                "internal_root_configured",
                False,
                f"logical role {ROLE_WORKSPACE!r} is unset, so an authorized "
                "internal job has no root to produce under",
            )
        )
        return StorageDecision(
            status=STATUS_BLOCKED,
            storage=None,
            reason=REASON_INTERNAL_UNCONFIGURED,
            job_id=job_id,
            checks=tuple(checks),
        )
    checks.append(StorageCheck("internal_root_configured", True, f"{internal_root}"))

    free_bytes = probe.free_bytes(internal_root)
    required_total = required_bytes + internal_free_floor_bytes
    if free_bytes < required_total:
        checks.append(
            StorageCheck(
                "internal_safety_floor",
                False,
                f"internal free space {free_bytes} B cannot absorb {required_bytes} B "
                f"and still leave the {internal_free_floor_bytes} B floor",
            )
        )
        return StorageDecision(
            status=STATUS_BLOCKED,
            storage=None,
            reason=REASON_INTERNAL_FLOOR,
            job_id=job_id,
            checks=tuple(checks),
        )
    checks.append(
        StorageCheck(
            "internal_safety_floor",
            True,
            f"{free_bytes} B free; floor {internal_free_floor_bytes} B preserved",
        )
    )

    job_workspace = internal_root / job_id
    checks.append(
        StorageCheck(
            "job_workspace_resolvable",
            True,
            f"job workspace resolves to {job_workspace} (internal, authorized)",
        )
    )
    return StorageDecision(
        status=STATUS_RESOLVED,
        storage=STORAGE_INTERNAL_AUTHORIZED,
        reason=None,
        job_id=job_id,
        checks=tuple(checks),
        job_workspace=job_workspace,
    )


def ensure_job_workspace(decision: StorageDecision) -> Path:
    """Create and return the resolved job workspace.

    The only writing operation in this module, and it is never called implicitly: a
    blocked decision raises before any directory exists.
    """

    workspace = decision.require_workspace()
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def describe_storage_contract(
    *,
    config: PathConfiguration | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Describe the policy itself, so a fresh Agent can discover the rule.

    This answers "where does production write, and what happens when the drive is
    missing?" without running a job and without reading anybody's chat history.
    """

    environment: Mapping[str, str] = os.environ if environ is None else environ
    configuration = (
        PathConfiguration.from_environ(environment) if config is None else config
    )
    production_root = configuration.get(ROLE_PRODUCTION_ROOT)
    return {
        "contract": "kang-ai-autocut-storage-contract",
        "authority": "src/ai_autocut/storage_contract.py",
        "production_root_role": ROLE_PRODUCTION_ROOT,
        "production_root_variable": ENV_PRODUCTION_ROOT,
        "production_root": _text(production_root),
        "staging_directory": STAGING_DIRECTORY_NAME,
        "archive_directory": ARCHIVE_DIRECTORY_NAME,
        "job_workspace_pattern": (
            f"<{ENV_PRODUCTION_ROOT}>/{STAGING_DIRECTORY_NAME}/<job-id>"
        ),
        "resolution_order": [
            "EXTERNAL when the production root is mounted and writable",
            "BLOCKED when it is not; production does not continue internally",
            f"INTERNAL_AUTHORIZED only when {ENV_INTERNAL_OVERRIDE} names this exact "
            "job and the internal safety floor survives",
        ],
        "blocked_reason": REASON_EXTERNAL_UNAVAILABLE,
        "internal_override_variable": ENV_INTERNAL_OVERRIDE,
        "internal_safety_floor_bytes": INTERNAL_SAFETY_FLOOR_BYTES,
        "silent_internal_fallback": False,
    }


def render_decision(decision: StorageDecision) -> str:
    """Render a decision as deterministic JSON text."""

    return json.dumps(decision.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Ask the contract directly. Used by Agents and by direct tool operations."""

    import argparse

    parser = argparse.ArgumentParser(
        prog="python3 -m src.ai_autocut.storage_contract",
        description=(
            "Resolve the authoritative production workspace for one job. Exits 0 when "
            "storage is resolved, 3 when production is blocked."
        ),
    )
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--required-bytes", type=int, default=0)
    parser.add_argument(
        "--print-workspace",
        action="store_true",
        help="print only the resolved workspace path, for shell substitution",
    )
    parser.add_argument(
        "--describe",
        action="store_true",
        help="describe the storage policy instead of resolving a job",
    )
    args = parser.parse_args(argv)

    if args.describe:
        sys.stdout.write(
            json.dumps(
                describe_storage_contract(), ensure_ascii=False, sort_keys=True, indent=2
            )
            + "\n"
        )
        return EXIT_RESOLVED

    try:
        decision = resolve_production_storage(
            args.job_id, required_bytes=args.required_bytes
        )
    except ProductionStorageError as exc:
        print(f"storage contract error: {exc}", file=sys.stderr)
        return EXIT_CONTRACT_ERROR

    if decision.blocked:
        print(render_decision(decision), file=sys.stderr, end="")
        return EXIT_BLOCKED

    if args.print_workspace:
        sys.stdout.write(f"{decision.require_workspace()}\n")
    else:
        sys.stdout.write(render_decision(decision))
    return EXIT_RESOLVED


if __name__ == "__main__":
    raise SystemExit(main())
