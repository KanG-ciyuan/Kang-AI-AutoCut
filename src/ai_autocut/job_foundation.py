"""Minimal, local-first state for one resumable production job.

This is deliberately not a workflow platform.  It owns the small set of
runtime records needed to make a real job auditable and resumable before the
analysis and execution stages are implemented.  Runtime manifests may contain
machine paths because they are external job evidence; canonical contracts and
Git-tracked files must not.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Iterable, Mapping, Sequence

from .paths import PathConfiguration, assert_ascii_safe
from .storage_contract import (
    ProductionStorageBlocked,
    StorageDecision,
    StorageProbe,
    resolve_production_storage,
)


JOB_MANIFEST_FILENAME = "job_manifest.json"
PIPELINE_STATE_FILENAME = "pipeline_state.json"
ARTIFACT_REFERENCES_FILENAME = "artifact_references.json"
SOURCE_INVENTORY_FILENAME = "source_inventory.json"
STAGING_QUOTA_BYTES = 5 * 1024 * 1024 * 1024

STAGE_STATES = frozenset({"PENDING", "RUNNING", "PASS", "FAILED", "NEEDS_REVIEW"})

#: Low-level execution/state vocabulary.
#:
#: This is execution detail, not the authoritative production lifecycle. The
#: authoritative lifecycle is the eight-stage Production Fast Path in
#: ``fast_path.py``; these states are the finer-grained record underneath it.
#:
#: ``PLAN_THE_WORDS`` and ``BUILD_THE_AUDIO`` were added because two of the eight
#: semantic stages had no low-level state at all. Without them a copy or audio step
#: could not be recorded, which is how an unrecorded stage becomes an unrun stage.
#: The addition is purely additive: no existing state was removed or renamed.
STAGE_ORDER = (
    "PREPARE",
    "ANALYZE",
    "CANDIDATE_SHOT_POOL",
    "MATERIAL_COVERAGE",
    "EDITING_PLAN",
    "EXECUTABLE_TIMELINE",
    "DAVINCI_EXECUTION",
    "PREVIEW",
    "PLAN_THE_WORDS",
    "BUILD_THE_AUDIO",
    "REVIEW",
    "FINAL",
    "DELIVERY",
)
ARTIFACT_KEYS = (
    "source_inventory",
    "analysis_evidence",
    "candidate_pool",
    "material_coverage",
    "editing_plan",
    "executable_timeline",
    "timing_profile",
    "narration_coverage",
    "audio_program",
    "preview",
    "review",
    "final",
)


class JobFoundationError(ValueError):
    """Raised when job evidence or a state transition is unsafe."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JobFoundationError(f"cannot read job evidence {path.name}") from exc
    if not isinstance(data, dict):
        raise JobFoundationError(f"job evidence {path.name} must be an object")
    return data


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def validate_staging_path(staging_root: Path, quota_bytes: int = STAGING_QUOTA_BYTES) -> dict[str, int | str]:
    if quota_bytes <= 0:
        raise JobFoundationError("staging quota must be positive")
    resolved = staging_root.resolve(strict=False)
    assert_ascii_safe(resolved, role="ascii_staging")
    if staging_root.exists() and not staging_root.is_dir():
        raise JobFoundationError("ascii staging root must be a directory")
    current_usage = directory_size_bytes(staging_root)
    if current_usage > quota_bytes:
        raise JobFoundationError("ascii staging already exceeds its hard quota")
    available = shutil.disk_usage(resolved.parent if resolved.parent.exists() else Path("/")).free
    if available < quota_bytes - current_usage:
        raise JobFoundationError("insufficient internal free space for the staging quota")
    return {
        "configured_path": str(staging_root),
        "realpath": str(resolved),
        "current_usage_bytes": current_usage,
        "available_bytes": available,
        "quota_bytes": quota_bytes,
    }


def build_source_inventory(source_root: Path) -> list[dict[str, Any]]:
    if not source_root.is_dir():
        raise JobFoundationError("source root must be an existing directory")
    files = sorted(item for item in source_root.iterdir() if item.is_file() and item.suffix.lower() == ".mp4")
    if len(files) != 16:
        raise JobFoundationError(f"Filter first job requires exactly 16 MP4 files, found {len(files)}")
    inventory: list[dict[str, Any]] = []
    for index, source in enumerate(files, start=1):
        stat = source.stat()
        inventory.append(
            {
                "source_id": f"FILTER-{index:02d}",
                "filename": source.name,
                "path": str(source.resolve()),
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_of_file(source),
            }
        )
    return inventory


def verify_source_immutability(inventory: Iterable[Mapping[str, Any]]) -> bool:
    for item in inventory:
        path = Path(str(item["path"]))
        if not path.is_file() or path.stat().st_size != item["size_bytes"]:
            return False
        if sha256_of_file(path) != item["sha256"]:
            return False
    return True


def _empty_state(job_id: str) -> dict[str, Any]:
    return {
        "schema_version": "pipeline_state.v1",
        "job_id": job_id,
        "updated_at": _utc_now(),
        "stages": {stage: {"state": "PENDING", "evidence": []} for stage in STAGE_ORDER},
        "history": [],
    }


@dataclass
class JobFoundation:
    root: Path

    @property
    def manifest_path(self) -> Path:
        return self.root / JOB_MANIFEST_FILENAME

    @property
    def state_path(self) -> Path:
        return self.root / PIPELINE_STATE_FILENAME

    @property
    def artifact_references_path(self) -> Path:
        return self.root / ARTIFACT_REFERENCES_FILENAME

    @property
    def source_inventory_path(self) -> Path:
        return self.root / SOURCE_INVENTORY_FILENAME

    def state(self) -> dict[str, Any]:
        return _read_json(self.state_path)

    def resume_stage(self) -> str | None:
        state = self.state()
        for stage in STAGE_ORDER:
            if state["stages"][stage]["state"] != "PASS":
                return stage
        return None

    def save_state(self, state: Mapping[str, Any]) -> None:
        """Persist a state document this object's owner has already modified.

        The production fast path uses this to reflect an invalidation into the low-level
        record. It is deliberately a method rather than a module-level private helper so
        a caller can reconcile state without reaching into internals.
        """

        _write_json_atomic(self.state_path, state)

    def transition(self, stage: str, target: str, *, evidence: Mapping[str, Any] | None = None) -> None:
        if stage not in STAGE_ORDER or target not in STAGE_STATES:
            raise JobFoundationError("unknown stage or state")
        state = self.state()
        current = state["stages"][stage]["state"]
        if current == "PASS":
            raise JobFoundationError("a PASS stage is immutable; resume from its artifact")
        if target == "RUNNING":
            previous = STAGE_ORDER[: STAGE_ORDER.index(stage)]
            if any(state["stages"][item]["state"] != "PASS" for item in previous):
                raise JobFoundationError("cannot run a stage before prior stages pass")
        if target == "PASS" and current != "RUNNING":
            raise JobFoundationError("only a RUNNING stage may pass")
        if target == "FAILED" and current not in {"RUNNING", "NEEDS_REVIEW"}:
            raise JobFoundationError("only an active stage may fail")
        if target == "NEEDS_REVIEW" and current != "RUNNING":
            raise JobFoundationError("only a RUNNING stage may need review")
        entry = state["stages"][stage]
        entry["state"] = target
        if evidence is not None:
            entry["evidence"].append(dict(evidence))
        state["history"].append({"at": _utc_now(), "stage": stage, "from": current, "to": target, "evidence": evidence})
        state["updated_at"] = _utc_now()
        _write_json_atomic(self.state_path, state)


def ensure_state(root: Path, job_id: str) -> JobFoundation:
    """Return a JobFoundation for ``root``, creating an empty state when absent.

    Used by the production fast path to reconcile its semantic stages into the
    low-level state record. It never overwrites an existing state: a recorded stage is
    evidence and is not reset.
    """

    foundation = JobFoundation(Path(root))
    if not foundation.state_path.exists():
        foundation.root.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(foundation.state_path, _empty_state(job_id))
    return foundation


def initialize_filter_job(
    *, job_id: str, source_root: Path, workspace: Path, staging_root: Path, media_root: Path, davinci_path: Path,
    quota_bytes: int = STAGING_QUOTA_BYTES,
) -> JobFoundation:
    if not job_id or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in job_id):
        raise JobFoundationError("job id must be lowercase ASCII letters, digits, and hyphens")
    if workspace.exists():
        raise JobFoundationError("job workspace already exists; refusing to overwrite evidence")
    if _is_within(workspace, source_root) or _is_within(staging_root, source_root):
        raise JobFoundationError("workspace and staging must never be inside immutable source material")
    staging = validate_staging_path(staging_root, quota_bytes)
    if not davinci_path.is_dir():
        raise JobFoundationError("configured DaVinci application path is unavailable")
    inventory = build_source_inventory(source_root)
    workspace.mkdir(parents=True)
    staging_root.mkdir(parents=True, exist_ok=True)
    foundation = JobFoundation(workspace)
    _write_json_atomic(foundation.source_inventory_path, {"schema_version": "source_inventory.v1", "source_root": str(source_root.resolve()), "files": inventory})
    _write_json_atomic(
        foundation.manifest_path,
        {
            "schema_version": "filter_job.v1",
            "job_id": job_id,
            "created_at": _utc_now(),
            "product": {"name": "Faucet Filter", "localized_name": "水龙头过滤器"},
            "brief": {
                "platform": "TikTok", "language": "Indonesian", "aspect_ratio": "9:16", "target_duration_seconds": {"minimum": 15, "maximum": 20},
                "commercial_objective": "Show the product, usage, adjustable water direction, and faucet-size purchase check.",
                "allowed_facts": ["attaches to the faucet end", "water passes through a transparent cylinder", "water direction is adjustable", "usable for everyday sink rinsing", "check faucet-end size before purchase"],
                "forbidden_claims": ["direct drinking", "sterilization", "chemical removal", "pH improvement", "fixed filter material or layer count", "filtration efficiency", "water-saving percentage", "fits every faucet", "fixed service life"],
                "cta": "购买前确认水龙头末端尺寸。",
            },
            "source": {"inventory": SOURCE_INVENTORY_FILENAME, "count": len(inventory), "exclusions": ["vacuum bottle", "comb", "AdFlow tests", "_恢复候选", "Gold media", "Gold editing plan", "Gold executable timeline"]},
            "runtime": {"external_workspace": str(workspace.resolve()), "media_root": str(media_root.resolve()), "ascii_staging": staging, "staging_quota_bytes": quota_bytes, "audio_provider": "Doubao Seed Audio 1.0", "davinci_application": str(davinci_path.resolve())},
        },
    )
    _write_json_atomic(foundation.state_path, _empty_state(job_id))
    _write_json_atomic(foundation.artifact_references_path, {"schema_version": "artifact_references.v1", "job_id": job_id, "artifacts": {key: None for key in ARTIFACT_KEYS}})
    foundation.transition("PREPARE", "RUNNING", evidence={"kind": "source_immutability_precheck", "passed": verify_source_immutability(inventory)})
    foundation.transition("PREPARE", "PASS", evidence={"kind": "source_inventory", "path": SOURCE_INVENTORY_FILENAME, "files": len(inventory)})
    return foundation


#: Media extensions a generic commercial SKU can start from. A job may narrow this,
#: but the default is not derived from any single SKU.
SUPPORTED_SOURCE_SUFFIXES = (".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi")


def discover_sources(
    source_root: Path, suffixes: Iterable[str] = SUPPORTED_SOURCE_SUFFIXES
) -> list[Path]:
    """Every supported media file directly inside ``source_root``, in stable order.

    No count is assumed. A SKU with one source and a SKU with four hundred take the
    same path, which is the point of a generic initializer.
    """

    if not source_root.is_dir():
        raise JobFoundationError("source root must be an existing directory")
    wanted = {suffix.lower() for suffix in suffixes}
    return sorted(
        item
        for item in source_root.iterdir()
        if item.is_file() and item.suffix.lower() in wanted
    )


def build_generic_source_inventory(
    source_root: Path, suffixes: Iterable[str] = SUPPORTED_SOURCE_SUFFIXES
) -> list[dict[str, Any]]:
    """Identify every discovered source. Zero usable media is an error, not an empty job."""

    files = discover_sources(source_root, suffixes)
    if not files:
        raise JobFoundationError(
            "no supported source media found in "
            f"{source_root} (looked for: {', '.join(sorted(set(suffixes)))})"
        )
    inventory: list[dict[str, Any]] = []
    for index, source in enumerate(files, start=1):
        stat = source.stat()
        inventory.append(
            {
                "source_id": f"SRC-{index:03d}",
                "filename": source.name,
                "path": str(source.resolve()),
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_of_file(source),
            }
        )
    return inventory


def _enforce_storage_decision(
    decision: StorageDecision, workspace: Path, job_id: str
) -> None:
    """Refuse a workspace that the storage contract did not resolve.

    Passing a decision in is how a caller proves it asked the production system
    where to write, rather than choosing a location itself. A decision naming a
    different job, or naming no workspace at all, is a contract violation and not a
    warning: the whole point of the storage contract is that the workspace has one
    authority.
    """

    if decision.job_id != job_id:
        raise JobFoundationError(
            f"storage decision is for job {decision.job_id!r}, not {job_id!r}"
        )
    if decision.blocked:
        raise JobFoundationError(
            "production storage is blocked "
            f"({decision.reason}); production must not begin"
        )
    resolved = decision.job_workspace
    if resolved is None:
        raise JobFoundationError("storage decision resolved no job workspace")
    if Path(workspace).resolve(strict=False) != Path(resolved).resolve(strict=False):
        raise JobFoundationError(
            "workspace must be the storage-contract-resolved job workspace; "
            "a caller may not substitute its own location for heavy production media"
        )


def initialize_job(
    *,
    job_id: str,
    product: Mapping[str, Any],
    source_root: Path,
    workspace: Path,
    media_root: Path | None = None,
    staging_root: Path | None = None,
    davinci_path: Path | None = None,
    source_suffixes: Iterable[str] = SUPPORTED_SOURCE_SUFFIXES,
    quota_bytes: int = STAGING_QUOTA_BYTES,
    storage_decision: StorageDecision | None = None,
) -> JobFoundation:
    """Initialize one generic commercial job.

    This is the Third-SKU producer contract for ``source_inventory.json``. It requires
    only what a fresh commercial SKU actually has: an id, a product identity, and a
    directory of source media.

    It deliberately does **not** require a fixed file count, a Filter identity, or any
    SKU#1 or SKU#2 value. ``initialize_filter_job`` is kept unchanged for historical
    compatibility, and nothing here changes its behaviour.

    ``workspace`` is the caller's already-decided location, which keeps this function
    usable by a caller that legitimately holds a workspace. Production callers should
    use :func:`initialize_production_job` instead and let the storage contract decide.
    When ``storage_decision`` is supplied, this function enforces that ``workspace``
    is the location that decision resolved.

    .. note::
       **Future deprecation candidate — not deprecated in this change.**

       Accepting ``workspace`` from the caller is the last remaining place where a
       caller can name a production location itself instead of asking the storage
       contract. It is deliberately retained for now: ``production.ensure_job`` and
       the offline test suite both depend on it, and breaking either to remove a
       parameter would trade a storage guarantee for a test-suite regression.

       The intended sequence, when the Producer schedules it, is: (1) route
       ``production.ensure_job`` through :func:`initialize_production_job`, (2) give
       the offline suite a storage-resolved temporary root, (3) only then remove the
       parameter. Until step 3, treat ``workspace`` as a compatibility path and prefer
       ``initialize_production_job`` for anything that is real production.
    """

    if not job_id or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in job_id
    ):
        raise JobFoundationError(
            "job id must be lowercase ASCII letters, digits, and hyphens"
        )
    if not isinstance(product, Mapping):
        raise JobFoundationError("product identity must be a mapping")
    name = product.get("name")
    if not isinstance(name, str) or not name.strip():
        raise JobFoundationError(
            "a generic job must state its product identity; product.name is required"
        )
    if storage_decision is not None:
        _enforce_storage_decision(storage_decision, workspace, job_id)
    if workspace.exists():
        raise JobFoundationError(
            "job workspace already exists; refusing to overwrite evidence"
        )
    if _is_within(workspace, source_root):
        raise JobFoundationError(
            "workspace must never be inside immutable source material"
        )

    staging: dict[str, Any] | None = None
    if staging_root is not None:
        if _is_within(staging_root, source_root):
            raise JobFoundationError(
                "staging must never be inside immutable source material"
            )
        staging = validate_staging_path(staging_root, quota_bytes)
    if davinci_path is not None and not davinci_path.is_dir():
        raise JobFoundationError("configured DaVinci application path is unavailable")

    inventory = build_generic_source_inventory(source_root, source_suffixes)
    workspace.mkdir(parents=True)
    foundation = JobFoundation(workspace)
    _write_json_atomic(
        foundation.source_inventory_path,
        {
            "schema_version": "source_inventory.v1",
            "source_root": str(source_root.resolve()),
            "supported_suffixes": sorted({s.lower() for s in source_suffixes}),
            "files": inventory,
        },
    )
    runtime: dict[str, Any] = {"external_workspace": str(workspace.resolve())}
    if media_root is not None:
        runtime["media_root"] = str(media_root.resolve())
    if staging is not None:
        runtime["ascii_staging"] = staging
        runtime["staging_quota_bytes"] = quota_bytes
    if davinci_path is not None:
        runtime["davinci_application"] = str(davinci_path.resolve())
    _write_json_atomic(
        foundation.manifest_path,
        {
            "schema_version": "job_manifest.v2",
            "job_id": job_id,
            "created_at": _utc_now(),
            "product": dict(product),
            "source": {
                "inventory": SOURCE_INVENTORY_FILENAME,
                "count": len(inventory),
                "source_root": str(source_root.resolve()),
            },
            "runtime": runtime,
        },
    )
    _write_json_atomic(foundation.state_path, _empty_state(job_id))
    _write_json_atomic(
        foundation.artifact_references_path,
        {
            "schema_version": "artifact_references.v1",
            "job_id": job_id,
            "artifacts": {key: None for key in ARTIFACT_KEYS},
        },
    )
    foundation.transition(
        "PREPARE",
        "RUNNING",
        evidence={
            "kind": "source_immutability_precheck",
            "passed": verify_source_immutability(inventory),
        },
    )
    foundation.transition(
        "PREPARE",
        "PASS",
        evidence={
            "kind": "source_inventory",
            "path": SOURCE_INVENTORY_FILENAME,
            "files": len(inventory),
        },
    )
    return foundation


def initialize_production_job(
    *,
    job_id: str,
    product: Mapping[str, Any],
    source_root: Path,
    config: PathConfiguration | None = None,
    environ: Mapping[str, str] | None = None,
    probe: StorageProbe | None = None,
    required_bytes: int = 0,
    media_root: Path | None = None,
    staging_root: Path | None = None,
    davinci_path: Path | None = None,
    source_suffixes: Iterable[str] = SUPPORTED_SOURCE_SUFFIXES,
    quota_bytes: int = STAGING_QUOTA_BYTES,
) -> JobFoundation:
    """Initialize one production job at the location the storage contract resolves.

    This is the entry point an Agent uses. The Agent states *what* the job is; the
    production system decides *where* it produces. That inversion is the whole
    contract: a Work-produced job, a Codex-produced job and a DSH-produced job reach
    the same workspace because none of them supplies one.

    When the external production root is unavailable this raises
    :class:`~src.ai_autocut.storage_contract.ProductionStorageBlocked` and nothing is
    created. It does not fall back to the internal disk. The exception carries the
    decision, so the operating Agent can tell the Producer that the production drive
    must be connected rather than guessing why production stopped.
    """

    decision = resolve_production_storage(
        job_id,
        config=config,
        environ=environ,
        probe=probe,
        required_bytes=required_bytes,
    )
    workspace = decision.require_workspace()
    return initialize_job(
        job_id=job_id,
        product=product,
        source_root=source_root,
        workspace=workspace,
        media_root=media_root,
        staging_root=staging_root,
        davinci_path=davinci_path,
        source_suffixes=source_suffixes,
        quota_bytes=quota_bytes,
        storage_decision=decision,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize one production job (generic by default)"
    )
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help=(
            "explicit job workspace, for a caller that already holds one. "
            "Production should prefer --production, which resolves the workspace "
            "from the storage contract instead."
        ),
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help=(
            "resolve the job workspace from the storage contract (external "
            "production storage). Blocks instead of falling back to the internal "
            "disk. Mutually exclusive with --workspace."
        ),
    )
    parser.add_argument(
        "--product-name",
        default=None,
        help="product identity for a generic job; required unless --filter is used",
    )
    parser.add_argument("--product-name-localized", default=None)
    parser.add_argument("--media-root", type=Path, default=None)
    parser.add_argument("--staging-root", type=Path, default=None)
    parser.add_argument("--davinci-path", type=Path, default=None)
    parser.add_argument(
        "--filter",
        action="store_true",
        help=(
            "use the historical Filter-first-job initializer (exactly 16 MP4 files, "
            "Faucet Filter identity). Kept for compatibility; not the Third-SKU "
            "producer contract."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.production and args.workspace is not None:
            print(
                "--workspace and --production are mutually exclusive: --production "
                "resolves the workspace from the storage contract, and passing a "
                "workspace as well would replace that decision",
                file=sys.stderr,
            )
            return 2
        if args.production:
            if not args.product_name:
                print(
                    "--product-name is required for a generic job; the product identity "
                    "is a job input, not a built-in",
                    file=sys.stderr,
                )
                return 2
            job = initialize_production_job(
                job_id=args.job_id,
                product={"name": args.product_name},
                source_root=args.source_root,
                media_root=args.media_root,
                staging_root=args.staging_root,
                davinci_path=args.davinci_path,
            )
        elif args.filter:
            missing = [
                name
                for name, value in (
                    ("--media-root", args.media_root),
                    ("--staging-root", args.staging_root),
                    ("--davinci-path", args.davinci_path),
                )
                if value is None
            ]
            if missing:
                print(
                    f"the Filter initializer requires: {', '.join(missing)}",
                    file=sys.stderr,
                )
                return 2
            if args.workspace is None:
                print("--workspace is required unless --production is used", file=sys.stderr)
                return 2
            job = initialize_filter_job(
                job_id=args.job_id,
                source_root=args.source_root,
                workspace=args.workspace,
                staging_root=args.staging_root,
                media_root=args.media_root,
                davinci_path=args.davinci_path,
            )
        else:
            if not args.product_name:
                print(
                    "--product-name is required for a generic job; the product identity "
                    "is a job input, not a built-in",
                    file=sys.stderr,
                )
                return 2
            if args.workspace is None:
                print(
                    "--workspace is required unless --production is used; --production "
                    "resolves it from the storage contract",
                    file=sys.stderr,
                )
                return 2
            product: dict[str, Any] = {"name": args.product_name}
            if args.product_name_localized:
                product["localized_name"] = args.product_name_localized
            job = initialize_job(
                job_id=args.job_id,
                product=product,
                source_root=args.source_root,
                workspace=args.workspace,
                media_root=args.media_root,
                staging_root=args.staging_root,
                davinci_path=args.davinci_path,
            )
        print(
            json.dumps(
                {
                    "job_manifest": str(job.manifest_path),
                    "pipeline_state": str(job.state_path),
                    "resume_stage": job.resume_stage(),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except ProductionStorageBlocked as exc:
        # Machine-readable and on stderr, so a caller branches on the status rather
        # than parsing English. Nothing was created: the workspace was never resolved.
        print(json.dumps(exc.decision.as_dict(), ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 3
    except JobFoundationError as exc:
        print(f"job foundation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
