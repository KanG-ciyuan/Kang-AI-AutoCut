"""Artifact references for companion contracts.

A companion artifact (Candidate Evidence, Hook Decision, Planning Evidence) must
state which other artifact it was derived from and which exact bytes it saw. This
module holds that one convention so three contracts do not invent three of them.

The convention already exists in this repository: a logical artifact name plus
the SHA-256 of its bytes. ``artifact_references.v1`` maps logical names to files,
``assembly_evidence.v1`` binds ``master_sha256`` to the file on disk, and
``gold_manifest.v1`` binds ``sha256`` to each visual authority. There is no URI
scheme here and none is added: a reference is a ``{"ref", "sha256"}`` pair whose
``ref`` is a workspace-relative logical path.

The pair is deliberately not a capability. It proves that a document was written
against one exact revision of another document; it does not read files, resolve
paths, delete anything, or decide that a stale producer output is still valid.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping, Sequence


#: Keys of one artifact reference object. Any other key is a contract error.
REFERENCE_KEYS = ("ref", "sha256")

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")

#: A logical reference is a workspace-relative POSIX path ending in ``.json``.
#:
#: Each segment must start with an alphanumeric character, so a rooted absolute
#: path, a parent traversal (``..``), a home shortcut (``~``), a Windows
#: separator, a drive letter, or an embedded space can never satisfy the pattern.
#: Machine-bound locations must not enter a contract at all.
_LOGICAL_REF_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*\.json\Z"
)


class ArtifactReferenceError(ValueError):
    """Raised when an artifact reference is malformed or no longer matches."""


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ArtifactReferenceError(f"{label} must be a JSON object")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise ArtifactReferenceError(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise ArtifactReferenceError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


def validate_logical_ref(value: object, label: str = "ref") -> str:
    """Return one workspace-relative logical artifact path, or fail closed."""

    if not isinstance(value, str) or _LOGICAL_REF_PATTERN.fullmatch(value) is None:
        raise ArtifactReferenceError(
            f"{label} must be a workspace-relative path ending in .json"
        )
    return value


def validate_sha256(value: object, label: str = "sha256") -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ArtifactReferenceError(
            f"{label} must be a lowercase 64-character SHA-256 hex digest"
        )
    return value


def canonical_text_sha256(text: object) -> str:
    """Hash one already-rendered artifact exactly as it would be written."""

    if not isinstance(text, str):
        raise ArtifactReferenceError("artifact text must be a string")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ArtifactReference:
    """One logical artifact name bound to the SHA-256 of its exact bytes."""

    ref: str
    sha256: str

    def __post_init__(self) -> None:
        validate_logical_ref(self.ref)
        validate_sha256(self.sha256)

    def as_dict(self) -> dict[str, object]:
        return {"ref": self.ref, "sha256": self.sha256}

    def matches_text(self, text: object) -> bool:
        return canonical_text_sha256(text) == self.sha256


def artifact_reference(ref: object, text: object) -> ArtifactReference:
    """Build the reference for one rendered artifact document."""

    return ArtifactReference(
        validate_logical_ref(ref), canonical_text_sha256(text)
    )


def parse_artifact_reference(
    document: object,
    *,
    label: str = "reference",
    expected_ref: object | None = None,
) -> ArtifactReference:
    mapping = _object(document, label)
    _exact_keys(mapping, REFERENCE_KEYS, label)
    reference = ArtifactReference(mapping["ref"], mapping["sha256"])  # type: ignore[arg-type]
    if expected_ref is not None:
        if reference.ref != validate_logical_ref(expected_ref, f"{label}.ref"):
            raise ArtifactReferenceError(
                f"{label}.ref is not the expected artifact for this binding"
            )
    return reference


def validate_reference_binding(
    reference: ArtifactReference,
    text: object,
    *,
    label: str = "reference",
) -> None:
    """Fail closed when a referenced artifact is stale or was never that revision."""

    if not isinstance(reference, ArtifactReference):
        raise ArtifactReferenceError(f"{label} must be an ArtifactReference")
    if not reference.matches_text(text):
        raise ArtifactReferenceError(
            f"{label} does not match the supplied artifact bytes"
        )


def render_artifact_reference(reference: ArtifactReference) -> str:
    """Canonical one-line JSON for embedding a reference inside another document."""

    if not isinstance(reference, ArtifactReference):
        raise ArtifactReferenceError("reference must be an ArtifactReference")
    return json.dumps(reference.as_dict(), ensure_ascii=False, sort_keys=True)
