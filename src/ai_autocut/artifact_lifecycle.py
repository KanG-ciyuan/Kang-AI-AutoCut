"""Artifact lifecycle: what a closed job keeps, and what it may let go.

The problem this closes
-----------------------
Production intermediates are useful while a job is active and are not automatically
permanent records. Without a stated rule the default is retention, and retention is
how a finished job keeps several gigabytes of regenerable scratch forever. The
project already recorded this as a requirement rather than an implementation: a
staging cache grew to roughly 9.1 GB before a human removed it by hand.

The lifecycle, in one line
--------------------------
    ACTIVE -> FINAL REVIEW -> ACCEPTED -> MASTER LOCKED -> RECORD FINALIZED
           -> ARCHIVE AUTHORITATIVE -> PRUNE REGENERABLE -> CLOSED

Three properties make this Agent-independent
--------------------------------------------
1. **The state, not the Agent, decides.** Retention is a function of the job's
   lifecycle state. A Work-produced variant and a DSH-produced variant follow the
   same rule because neither Agent is consulted.
2. **Nothing is prunable before ``CLOSED``.** Every classification is ``KEEP`` until
   the job reaches the closing state. An active or awaiting-review job cannot be
   pruned by this module even if a caller asks, because the state gate is checked
   before any role is examined.
3. **Uncertain means keep.** Classification is by production *role*, never by file
   extension. A ``.mp4`` may be a Final Master and a ``.png`` may be required
   evidence, so extension is not consulted at all. A path whose role is not
   positively identified is reported ``UNCERTAIN`` and retained.

This module never deletes anything. It produces a classification and a
by-classification byte total; removal is a separate, Producer-approved act. That
split is deliberate: an audit that can delete is an audit nobody can run safely on
a live machine.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable, Mapping, Sequence


#: Classification vocabulary.
AUTHORITATIVE = "AUTHORITATIVE"
REGENERABLE = "REGENERABLE"
UNCERTAIN = "UNCERTAIN"

#: Only artifacts in this class are candidates for removal after a job closes.
PRUNABLE_CLASSIFICATIONS = frozenset({REGENERABLE})

#: Lifecycle states, in order. The order is the contract; a job may not skip
#: forward past ACCEPTED without the Producer review that defines it.
STATE_ACTIVE = "ACTIVE"
STATE_FINAL_REVIEW = "FINAL_REVIEW"
STATE_ACCEPTED = "ACCEPTED"
STATE_MASTER_LOCKED = "MASTER_LOCKED"
STATE_RECORD_FINALIZED = "RECORD_FINALIZED"
STATE_ARCHIVED = "ARCHIVED"
STATE_CLOSED = "CLOSED"

LIFECYCLE_STATES = (
    STATE_ACTIVE,
    STATE_FINAL_REVIEW,
    STATE_ACCEPTED,
    STATE_MASTER_LOCKED,
    STATE_RECORD_FINALIZED,
    STATE_ARCHIVED,
    STATE_CLOSED,
)

#: The only state in which anything is prunable. A single named constant rather
#: than a scattered comparison, so widening retention is one visible edit.
PRUNABLE_STATES = frozenset({STATE_CLOSED})

#: Job-relative directory roles that are unambiguously derived scratch. These hold
#: regenerable material by definition: frames dumped from a master, proxies
#: transcoded for an editor, and tool caches.
#:
#: Deliberately absent: ``renders`` and ``preview``. Both routinely hold the
#: delivered artifact as well as superseded attempts, so neither is a safe role to
#: prune by name. A caller that knows the difference declares it per artifact.
REGENERABLE_ROLES = frozenset(
    {
        "frames",
        "frame_dump",
        "frame_dumps",
        "frames_dump",
        "frame_sequence",
        "frame_sequences",
        "proxy",
        "proxies",
        "proxymedia",
        "proxy_media",
        "optimizedmedia",
        "optimized_media",
        "cache",
        "caches",
        "cacheclip",
        "fusioncache",
        "davincicache",
        "scratch",
        "tmp",
        "temp",
        "ffmpeg",
        "ffmpeg_scratch",
        "analysis_scratch",
        "test_render",
        "test_renders",
        "rejected",
    }
)

#: Job-relative directory roles that hold the record of what was produced and
#: approved. These are archived, never pruned.
AUTHORITATIVE_ROLES = frozenset(
    {
        "final",
        "release",
        "delivery",
        "master",
        "masters",
        "gold",
        "record",
        "records",
        "manifest",
        "manifests",
        "qa",
        "brief",
        "briefs",
        "copy",
        "review",
        "reports",
    }
)

#: Filename markers that identify a superseded revision. Every one of these was
#: observed in real production output, where a repair writes the previous attempt
#: next to the new one instead of overwriting it.
SUPERSEDED_MARKERS = (
    ".before-",
    ".before_",
    "-superseded-",
    "_superseded_",
    ".superseded.",
    ".bak",
    ".old",
    ".prev",
)

#: Duplicate detection hashes files at or above this size. Bulk media, not text.
DUPLICATE_HASH_MIN_BYTES = 1024 * 1024

#: Directory names never descended into when classifying a job workspace.
_SKIP_DIRECTORY_NAMES = frozenset({".git", "__pycache__", ".DS_Store"})


class ArtifactLifecycleError(ValueError):
    """Raised when a lifecycle question is malformed or unsafe to answer."""


@dataclass(frozen=True)
class ArtifactClassification:
    """One artifact's lifecycle class, with the reasoning that produced it."""

    path: str
    size_bytes: int
    classification: str
    reason: str
    sha256: str | None = None

    @property
    def prunable(self) -> bool:
        return self.classification in PRUNABLE_CLASSIFICATIONS

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "classification": self.classification,
            "reason": self.reason,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class CloseoutReport:
    """A read-only classification of one job workspace.

    ``prunable_bytes`` is zero until the job reaches a prunable state, which is what
    makes the active-job protection visible in the report rather than implied by it.
    """

    job_workspace: str
    state: str
    entries: tuple[ArtifactClassification, ...]

    @property
    def prunable(self) -> bool:
        return self.state in PRUNABLE_STATES

    def bytes_for(self, classification: str) -> int:
        return sum(
            entry.size_bytes
            for entry in self.entries
            if entry.classification == classification
        )

    @property
    def prunable_bytes(self) -> int:
        if not self.prunable:
            return 0
        return sum(entry.size_bytes for entry in self.entries if entry.prunable)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "job_closeout.v1",
            "job_workspace": self.job_workspace,
            "state": self.state,
            "prunable_state": self.prunable,
            "totals": {
                "total_bytes": sum(entry.size_bytes for entry in self.entries),
                "authoritative_bytes": self.bytes_for(AUTHORITATIVE),
                "regenerable_bytes": self.bytes_for(REGENERABLE),
                "uncertain_bytes": self.bytes_for(UNCERTAIN),
                "prunable_bytes": self.prunable_bytes,
                "artifact_count": len(self.entries),
            },
            "artifacts": [entry.as_dict() for entry in self.entries],
        }


def validate_state(state: object) -> str:
    if not isinstance(state, str) or state not in LIFECYCLE_STATES:
        raise ArtifactLifecycleError(
            f"unknown lifecycle state {state!r}; expected one of: "
            + ", ".join(LIFECYCLE_STATES)
        )
    return state


def is_prunable_state(state: str) -> bool:
    """Whether any artifact may be pruned in ``state``."""

    return validate_state(state) in PRUNABLE_STATES


def sha256_of_file(path: Path, *, chunk_bytes: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_bytes), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_superseded(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in SUPERSEDED_MARKERS)


def _role_directories(relative: Path) -> tuple[str, ...]:
    return tuple(part.lower() for part in relative.parts[:-1])


def classify_artifact(
    relative_path: object,
    *,
    declared_role: str | None = None,
    observed_role: str | None = None,
    duplicate_of: str | None = None,
) -> tuple[str, str]:
    """Return ``(classification, reason)`` for one job-relative artifact.

    Precedence is deliberate and narrow:

    1. An explicit ``declared_role`` from the job manifest wins. The manifest is the
       production record; a heuristic must never outrank it.
    2. A byte-identical duplicate of an artifact already retained is regenerable by
       construction, because the retained copy still exists.
    3. A superseded revision in the filename is regenerable.
    4. An unambiguously scratch directory role is regenerable.
    5. Everything else is ``UNCERTAIN`` and is kept. No extension is consulted.
    """

    if not isinstance(relative_path, (str, Path)):
        raise ArtifactLifecycleError("artifact path must be a path")
    relative = Path(relative_path)
    if relative.is_absolute():
        raise ArtifactLifecycleError(
            "artifact path must be relative to the job workspace"
        )
    if not relative.parts:
        raise ArtifactLifecycleError("artifact path must not be empty")

    if declared_role is not None:
        role = str(declared_role).strip().lower()
        if not role:
            raise ArtifactLifecycleError("declared role must not be blank")
        if role == REGENERABLE.lower() or role in REGENERABLE_ROLES:
            return REGENERABLE, f"declared regenerable by the job manifest ({role})"
        if role == AUTHORITATIVE.lower() or role in AUTHORITATIVE_ROLES:
            return AUTHORITATIVE, f"declared authoritative by the job manifest ({role})"
        return UNCERTAIN, f"declared role {role!r} is not a recognised lifecycle role"

    if duplicate_of is not None:
        return REGENERABLE, f"byte-identical duplicate of {duplicate_of}"

    if _is_superseded(relative.name):
        return REGENERABLE, "filename marks a superseded revision"

    if observed_role:
        role = str(observed_role).strip().lower()
        if role in REGENERABLE_ROLES:
            return REGENERABLE, f"scratch directory role {role!r}"
        if role in AUTHORITATIVE_ROLES:
            return AUTHORITATIVE, f"record directory role {role!r}"

    for role in reversed(_role_directories(relative)):
        if role in REGENERABLE_ROLES:
            return REGENERABLE, f"scratch directory role {role!r}"
        if role in AUTHORITATIVE_ROLES:
            return AUTHORITATIVE, f"record directory role {role!r}"

    return UNCERTAIN, "role not positively identified; retained by default"


def iter_job_artifacts(job_workspace: object) -> Iterable[Path]:
    """Every file beneath ``job_workspace``, in stable order, skipping caches."""

    if not isinstance(job_workspace, (str, Path)):
        raise ArtifactLifecycleError("job workspace must be a path")
    root = Path(job_workspace)
    if not root.is_dir():
        raise ArtifactLifecycleError("job workspace must be an existing directory")
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRECTORY_NAMES for part in path.parts):
            continue
        yield path


def build_closeout_report(
    job_workspace: object,
    *,
    state: str = STATE_ACTIVE,
    declared_roles: Mapping[str, str] | None = None,
    hash_duplicates: bool = True,
) -> CloseoutReport:
    """Classify a job workspace without modifying it.

    ``state`` defaults to ``ACTIVE``, and in that state every artifact — including
    one a scratch role or a superseded marker would otherwise condemn — is returned
    as ``UNCERTAIN``/keep with the reason recorded. An active job is therefore
    structurally protected rather than protected by the caller remembering to ask.
    """

    active_state = validate_state(state)
    root = Path(job_workspace)
    if not root.is_dir():
        raise ArtifactLifecycleError("job workspace must be an existing directory")
    roles: Mapping[str, str] = {} if declared_roles is None else declared_roles
    if not isinstance(roles, Mapping):
        raise ArtifactLifecycleError("declared_roles must be a mapping")

    prunable_state = active_state in PRUNABLE_STATES
    seen_digests: dict[str, str] = {}
    entries: list[ArtifactClassification] = []

    for path in iter_job_artifacts(root):
        relative = path.relative_to(root)
        key = relative.as_posix()
        try:
            size = path.stat().st_size
        except OSError:
            continue

        digest: str | None = None
        duplicate_of: str | None = None
        if prunable_state and hash_duplicates and size >= DUPLICATE_HASH_MIN_BYTES:
            try:
                digest = sha256_of_file(path)
            except OSError:
                digest = None
            if digest is not None:
                duplicate_of = seen_digests.get(digest)
                if duplicate_of is None:
                    seen_digests[digest] = key

        if not prunable_state:
            classification, reason = (
                UNCERTAIN,
                f"job state {active_state} is not prunable; retained",
            )
        else:
            classification, reason = classify_artifact(
                relative,
                declared_role=roles.get(key),
                duplicate_of=duplicate_of,
            )

        entries.append(
            ArtifactClassification(
                path=key,
                size_bytes=size,
                classification=classification,
                reason=reason,
                sha256=digest,
            )
        )

    return CloseoutReport(
        job_workspace=str(root), state=active_state, entries=tuple(entries)
    )


def authoritative_artifacts(report: CloseoutReport) -> tuple[ArtifactClassification, ...]:
    """The artifacts a closed job must archive externally before it may prune."""

    return tuple(
        entry for entry in report.entries if entry.classification == AUTHORITATIVE
    )


def pruning_candidates(report: CloseoutReport) -> tuple[ArtifactClassification, ...]:
    """Regenerable artifacts, and only when the job state permits pruning."""

    if not report.prunable:
        return ()
    return tuple(entry for entry in report.entries if entry.prunable)
