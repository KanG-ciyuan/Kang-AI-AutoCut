"""Immutable, task-scoped Candidate Pool snapshots for AI-AutoCut.

A Candidate Pool is only a stable set of existing Candidate Identity records
that Planning may use for one task. It deliberately stores no media facts,
analysis, ranking, approval, or selection state.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping, Sequence

from .identity import CandidateIdentity, IdentityCatalog


SCHEMA_VERSION = "candidate_pool.v1"

_POOL_PREFIX = "poolv1_"
_POOL_DOMAIN = b"ai-autocut:candidate-pool:v1\n"
_CANDIDATE_ID_PATTERN = re.compile(r"candv1_[0-9a-f]{64}\Z")
_POOL_ID_PATTERN = re.compile(r"poolv1_[0-9a-f]{64}\Z")
_POOL_KEYS = ("schema_version", "pool_id", "entries")
_ENTRY_KEYS = ("candidate_id",)


class CandidatePoolContractError(ValueError):
    """Raised when a Candidate Pool cannot be consumed safely."""


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise CandidatePoolContractError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise CandidatePoolContractError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise CandidatePoolContractError(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise CandidatePoolContractError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


def _candidate_id(value: object, label: str = "candidate_id") -> str:
    if not isinstance(value, str) or _CANDIDATE_ID_PATTERN.fullmatch(value) is None:
        raise CandidatePoolContractError(f"{label} must match candv1_<sha256>")
    return value


def _pool_id(value: object, label: str = "pool_id") -> str:
    if not isinstance(value, str) or _POOL_ID_PATTERN.fullmatch(value) is None:
        raise CandidatePoolContractError(f"{label} must match poolv1_<sha256>")
    return value


def _sorted_candidate_ids(candidate_ids: Sequence[object]) -> tuple[str, ...]:
    if isinstance(candidate_ids, (str, bytes)) or not isinstance(candidate_ids, Sequence):
        raise CandidatePoolContractError("candidate_ids must be a sequence")
    values = tuple(
        _candidate_id(value, f"candidate_ids[{index}]")
        for index, value in enumerate(candidate_ids)
    )
    if len(values) != len(set(values)):
        raise CandidatePoolContractError("duplicate candidate_id in pool")
    return tuple(sorted(values))


def canonical_pool_identity_json(candidate_ids: Sequence[object]) -> str:
    """Return canonical member-set JSON used to derive the Pool identity."""

    return json.dumps(
        list(_sorted_candidate_ids(candidate_ids)),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def pool_id_for(candidate_ids: Sequence[object]) -> str:
    """Derive one immutable Pool ID from its sorted Candidate member set."""

    canonical = canonical_pool_identity_json(candidate_ids)
    digest = hashlib.sha256(_POOL_DOMAIN + canonical.encode("utf-8")).hexdigest()
    return _POOL_PREFIX + digest


@dataclass(frozen=True)
class CandidatePoolEntry:
    candidate_id: str

    def __post_init__(self) -> None:
        _candidate_id(self.candidate_id)

    def as_dict(self) -> dict[str, object]:
        return {"candidate_id": self.candidate_id}


@dataclass(frozen=True)
class CandidatePool:
    pool_id: str
    entries: tuple[CandidatePoolEntry, ...]

    def __post_init__(self) -> None:
        supplied_id = _pool_id(self.pool_id)
        candidate_ids = tuple(entry.candidate_id for entry in self.entries)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise CandidatePoolContractError("duplicate candidate_id in pool")
        expected_id = pool_id_for(candidate_ids)
        if supplied_id != expected_id:
            raise CandidatePoolContractError(
                "pool_id does not match its canonical Candidate member set"
            )

    @classmethod
    def create(cls, candidate_ids: Sequence[object]) -> "CandidatePool":
        normalized = _sorted_candidate_ids(candidate_ids)
        return cls(
            pool_id_for(normalized),
            tuple(CandidatePoolEntry(candidate_id) for candidate_id in normalized),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "pool_id": self.pool_id,
            "entries": [
                entry.as_dict()
                for entry in sorted(self.entries, key=lambda entry: entry.candidate_id)
            ],
        }


def parse_candidate_pool(document: object) -> CandidatePool:
    mapping = _object(document, "candidate pool")
    _exact_keys(mapping, _POOL_KEYS, "candidate pool")
    if mapping["schema_version"] != SCHEMA_VERSION:
        raise CandidatePoolContractError(f"schema_version must be {SCHEMA_VERSION!r}")

    entries: list[CandidatePoolEntry] = []
    for index, raw in enumerate(_array(mapping["entries"], "entries")):
        item = _object(raw, f"entries[{index}]")
        _exact_keys(item, _ENTRY_KEYS, f"entries[{index}]")
        entries.append(CandidatePoolEntry(item["candidate_id"]))
    return CandidatePool(mapping["pool_id"], tuple(entries))


def render_candidate_pool(pool: CandidatePool) -> str:
    if not isinstance(pool, CandidatePool):
        raise CandidatePoolContractError("pool must be a CandidatePool")
    return json.dumps(pool.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def validate_candidate_pool(pool: CandidatePool, catalog: IdentityCatalog) -> None:
    """Fail closed unless every Pool member exists in the supplied Identity Catalog."""

    if not isinstance(pool, CandidatePool):
        raise CandidatePoolContractError("pool must be a CandidatePool")
    if not isinstance(catalog, IdentityCatalog):
        raise CandidatePoolContractError("catalog must be an IdentityCatalog")
    for entry in pool.entries:
        try:
            catalog.candidate(entry.candidate_id)
        except ValueError as exc:
            raise CandidatePoolContractError(
                "pool references an unknown candidate_id"
            ) from exc


def validate_candidate_membership(
    candidate_pool_id: object,
    candidate_id: object,
    pool: CandidatePool,
    catalog: IdentityCatalog,
) -> CandidateIdentity:
    """Validate a Pool, then return one member's existing Candidate Identity."""

    requested_pool_id = _pool_id(candidate_pool_id, "candidate_pool_id")
    requested_candidate_id = _candidate_id(candidate_id)
    if not isinstance(pool, CandidatePool):
        raise CandidatePoolContractError("pool must be a CandidatePool")
    if requested_pool_id != pool.pool_id:
        raise CandidatePoolContractError("candidate_pool_id does not match the supplied pool")
    validate_candidate_pool(pool, catalog)
    if requested_candidate_id not in {entry.candidate_id for entry in pool.entries}:
        raise CandidatePoolContractError("candidate_id is not a member of the pool")
    try:
        return catalog.candidate(requested_candidate_id)
    except ValueError as exc:
        raise CandidatePoolContractError("candidate_id is unknown to the catalog") from exc
