"""Deterministic Material and Candidate identity for AI-AutoCut.

Material identity is the SHA-256 of the exact file bytes. Candidate identity is
the SHA-256 of a domain-separated canonical JSON object containing only the
material ID, video stream index, and end-exclusive source frame range.

The shared identity catalog is deliberately path-free. Machine-local paths live
in a separate locator document and are accepted only after the file bytes have
been hashed again and matched to the registered Material.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping, Sequence

from .frame_boundary import FrameBoundaryError, SourceRange
from .preflight import SCHEMA_VERSION as BOUNDARY_PREFLIGHT_SCHEMA_VERSION
from .preflight import parse_preflight_document


CATALOG_SCHEMA_VERSION = "material_candidate_identity.v1"
LOCATIONS_SCHEMA_VERSION = "material_locations.v1"

_MATERIAL_PREFIX = "matv1_"
_CANDIDATE_PREFIX = "candv1_"
_CANDIDATE_DOMAIN = b"ai-autocut:candidate:v1\n"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MATERIAL_ID_PATTERN = re.compile(r"matv1_[0-9a-f]{64}\Z")
_CANDIDATE_ID_PATTERN = re.compile(r"candv1_[0-9a-f]{64}\Z")

_CATALOG_KEYS = ("schema_version", "materials", "candidates")
_MATERIAL_KEYS = (
    "material_id",
    "content_sha256",
    "byte_size",
    "media_kind",
)
_CANDIDATE_KEYS = (
    "candidate_id",
    "material_id",
    "stream_index",
    "start_frame",
    "end_frame_exclusive",
)
_LOCATIONS_KEYS = ("schema_version", "locations")
_LOCATION_KEYS = ("material_id", "paths")
_BOUND_SEGMENT_KEYS = (
    "segment_id",
    "material_id",
    "candidate_id",
    "source_range",
    "continuation_group",
    "verified_safe_end_frame_exclusive",
    "planned_record_frame_relative",
)
_SOURCE_RANGE_KEYS = ("start_frame", "end_frame_exclusive")


class IdentityContractError(FrameBoundaryError):
    """Raised when identity data is malformed or internally inconsistent."""


class LocatorResolutionError(IdentityContractError):
    """Raised when a registered Material cannot be resolved byte-for-byte."""


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise IdentityContractError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise IdentityContractError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise IdentityContractError(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise IdentityContractError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


def _non_negative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise IdentityContractError(f"{label} must be a non-negative integer")
    return value


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise IdentityContractError(
            f"{label} must be a lowercase 64-character SHA-256 hex digest"
        )
    return value


def _material_id(value: object, label: str = "material_id") -> str:
    if not isinstance(value, str) or _MATERIAL_ID_PATTERN.fullmatch(value) is None:
        raise IdentityContractError(f"{label} must match matv1_<sha256>")
    return value


def _candidate_id(value: object, label: str = "candidate_id") -> str:
    if not isinstance(value, str) or _CANDIDATE_ID_PATTERN.fullmatch(value) is None:
        raise IdentityContractError(f"{label} must match candv1_<sha256>")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IdentityContractError(f"{label} must be a non-empty string")
    return value


def hash_file_sha256(path: str | Path) -> str:
    """Hash every byte of one regular file without caching or path identity."""

    source = Path(path)
    if not source.is_file():
        raise LocatorResolutionError("material file is missing or is not a regular file")
    digest = hashlib.sha256()
    read_failed = False
    try:
        with source.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError:
        read_failed = True
    if read_failed:
        # Raise outside the except block so a path-bearing OSError is absent
        # from cause, context, and formatted exception chains.
        raise LocatorResolutionError("material file could not be read")
    return digest.hexdigest()


def _file_size(path: Path, error_message: str) -> int:
    size: int | None = None
    try:
        size = path.stat().st_size
    except OSError:
        pass
    if size is None:
        # Do not retain a path-bearing OSError in the exception chain.
        raise LocatorResolutionError(error_message)
    return size


def material_id_from_sha256(content_sha256: str) -> str:
    return _MATERIAL_PREFIX + _sha256(content_sha256, "content_sha256")


@dataclass(frozen=True)
class MaterialIdentity:
    material_id: str
    content_sha256: str
    byte_size: int
    media_kind: str = "video"

    def __post_init__(self) -> None:
        digest = _sha256(self.content_sha256, "content_sha256")
        if _material_id(self.material_id) != material_id_from_sha256(digest):
            raise IdentityContractError(
                "material_id does not match the registered content_sha256"
            )
        _non_negative_integer(self.byte_size, "byte_size")
        if self.media_kind != "video":
            raise IdentityContractError(
                "material_candidate_identity.v1 supports media_kind='video' only"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "material_id": self.material_id,
            "content_sha256": self.content_sha256,
            "byte_size": self.byte_size,
            "media_kind": self.media_kind,
        }


def identify_material(path: str | Path) -> MaterialIdentity:
    """Create a Material identity from exact bytes; path metadata is excluded."""

    source = Path(path)
    digest = hash_file_sha256(source)
    size = _file_size(source, "material file metadata could not be read")
    return MaterialIdentity(material_id_from_sha256(digest), digest, size)


def canonical_candidate_identity_json(
    material_id: str,
    stream_index: int,
    start_frame: int,
    end_frame_exclusive: int,
) -> str:
    """Return the exact canonical JSON whose bytes define a Candidate ID."""

    material = _material_id(material_id)
    stream = _non_negative_integer(stream_index, "stream_index")
    try:
        source_range = SourceRange(start_frame, end_frame_exclusive)
    except FrameBoundaryError as exc:
        raise IdentityContractError(str(exc)) from exc
    identity_fields = {
        "material_id": material,
        "stream_index": stream,
        "start_frame": source_range.start_frame,
        "end_frame_exclusive": source_range.end_frame_exclusive,
    }
    return json.dumps(
        identity_fields,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def candidate_id_for(
    material_id: str,
    stream_index: int,
    start_frame: int,
    end_frame_exclusive: int,
) -> str:
    canonical = canonical_candidate_identity_json(
        material_id, stream_index, start_frame, end_frame_exclusive
    )
    digest = hashlib.sha256(_CANDIDATE_DOMAIN + canonical.encode("utf-8")).hexdigest()
    return _CANDIDATE_PREFIX + digest


@dataclass(frozen=True)
class CandidateIdentity:
    candidate_id: str
    material_id: str
    stream_index: int
    start_frame: int
    end_frame_exclusive: int

    def __post_init__(self) -> None:
        supplied_id = _candidate_id(self.candidate_id)
        expected_id = candidate_id_for(
            self.material_id,
            self.stream_index,
            self.start_frame,
            self.end_frame_exclusive,
        )
        if supplied_id != expected_id:
            raise IdentityContractError(
                "candidate_id does not match its canonical identity fields"
            )

    @classmethod
    def create(
        cls,
        material_id: str,
        stream_index: int,
        start_frame: int,
        end_frame_exclusive: int,
    ) -> "CandidateIdentity":
        return cls(
            candidate_id_for(
                material_id, stream_index, start_frame, end_frame_exclusive
            ),
            material_id,
            stream_index,
            start_frame,
            end_frame_exclusive,
        )

    @property
    def source_range(self) -> SourceRange:
        return SourceRange(self.start_frame, self.end_frame_exclusive)

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "material_id": self.material_id,
            "stream_index": self.stream_index,
            "start_frame": self.start_frame,
            "end_frame_exclusive": self.end_frame_exclusive,
        }


@dataclass(frozen=True)
class IdentityCatalog:
    materials: tuple[MaterialIdentity, ...]
    candidates: tuple[CandidateIdentity, ...]

    def __post_init__(self) -> None:
        material_ids = [item.material_id for item in self.materials]
        candidate_ids = [item.candidate_id for item in self.candidates]
        if len(material_ids) != len(set(material_ids)):
            raise IdentityContractError("duplicate material_id in catalog")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise IdentityContractError("duplicate candidate_id in catalog")
        known_materials = set(material_ids)
        for candidate in self.candidates:
            if candidate.material_id not in known_materials:
                raise IdentityContractError(
                    "candidate references a material_id that is not in the catalog"
                )

    def material(self, material_id: str) -> MaterialIdentity:
        requested = _material_id(material_id)
        for material in self.materials:
            if material.material_id == requested:
                return material
        raise IdentityContractError("unknown material_id")

    def candidate(self, candidate_id: str) -> CandidateIdentity:
        requested = _candidate_id(candidate_id)
        for candidate in self.candidates:
            if candidate.candidate_id == requested:
                return candidate
        raise IdentityContractError("unknown candidate_id")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "materials": [
                item.as_dict()
                for item in sorted(self.materials, key=lambda item: item.material_id)
            ],
            "candidates": [
                item.as_dict()
                for item in sorted(self.candidates, key=lambda item: item.candidate_id)
            ],
        }


def parse_identity_catalog(document: object) -> IdentityCatalog:
    mapping = _object(document, "identity catalog")
    _exact_keys(mapping, _CATALOG_KEYS, "identity catalog")
    if mapping["schema_version"] != CATALOG_SCHEMA_VERSION:
        raise IdentityContractError(
            f"schema_version must be {CATALOG_SCHEMA_VERSION!r}"
        )

    materials: list[MaterialIdentity] = []
    for index, raw in enumerate(_array(mapping["materials"], "materials")):
        item = _object(raw, f"materials[{index}]")
        _exact_keys(item, _MATERIAL_KEYS, f"materials[{index}]")
        materials.append(
            MaterialIdentity(
                material_id=item["material_id"],  # type: ignore[arg-type]
                content_sha256=item["content_sha256"],  # type: ignore[arg-type]
                byte_size=item["byte_size"],  # type: ignore[arg-type]
                media_kind=item["media_kind"],  # type: ignore[arg-type]
            )
        )

    candidates: list[CandidateIdentity] = []
    for index, raw in enumerate(_array(mapping["candidates"], "candidates")):
        item = _object(raw, f"candidates[{index}]")
        _exact_keys(item, _CANDIDATE_KEYS, f"candidates[{index}]")
        candidates.append(
            CandidateIdentity(
                candidate_id=item["candidate_id"],  # type: ignore[arg-type]
                material_id=item["material_id"],  # type: ignore[arg-type]
                stream_index=item["stream_index"],  # type: ignore[arg-type]
                start_frame=item["start_frame"],  # type: ignore[arg-type]
                end_frame_exclusive=item["end_frame_exclusive"],  # type: ignore[arg-type]
            )
        )
    return IdentityCatalog(tuple(materials), tuple(candidates))


def render_identity_catalog(catalog: IdentityCatalog) -> str:
    if not isinstance(catalog, IdentityCatalog):
        raise IdentityContractError("catalog must be an IdentityCatalog")
    return json.dumps(
        catalog.as_dict(), ensure_ascii=False, sort_keys=True, indent=2
    ) + "\n"


@dataclass(frozen=True)
class MaterialLocation:
    material_id: str
    paths: tuple[str, ...]

    def __post_init__(self) -> None:
        _material_id(self.material_id)
        if not self.paths:
            raise IdentityContractError("locator paths must not be empty")
        for index, path in enumerate(self.paths):
            _required_text(path, f"locator paths[{index}]")
        if len(self.paths) != len(set(self.paths)):
            raise IdentityContractError("duplicate path in locator entry")

    def as_dict(self) -> dict[str, object]:
        return {"material_id": self.material_id, "paths": sorted(self.paths)}


@dataclass(frozen=True)
class MaterialLocations:
    locations: tuple[MaterialLocation, ...]

    def __post_init__(self) -> None:
        material_ids = [item.material_id for item in self.locations]
        if len(material_ids) != len(set(material_ids)):
            raise IdentityContractError("duplicate material_id in locator document")

    def location(self, material_id: str) -> MaterialLocation:
        requested = _material_id(material_id)
        for location in self.locations:
            if location.material_id == requested:
                return location
        raise LocatorResolutionError("no locator is registered for material_id")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": LOCATIONS_SCHEMA_VERSION,
            "locations": [
                item.as_dict()
                for item in sorted(self.locations, key=lambda item: item.material_id)
            ],
        }


def parse_material_locations(document: object) -> MaterialLocations:
    mapping = _object(document, "material locations")
    _exact_keys(mapping, _LOCATIONS_KEYS, "material locations")
    if mapping["schema_version"] != LOCATIONS_SCHEMA_VERSION:
        raise IdentityContractError(
            f"schema_version must be {LOCATIONS_SCHEMA_VERSION!r}"
        )
    locations: list[MaterialLocation] = []
    for index, raw in enumerate(_array(mapping["locations"], "locations")):
        item = _object(raw, f"locations[{index}]")
        _exact_keys(item, _LOCATION_KEYS, f"locations[{index}]")
        raw_paths = _array(item["paths"], f"locations[{index}].paths")
        locations.append(
            MaterialLocation(
                material_id=item["material_id"],  # type: ignore[arg-type]
                paths=tuple(raw_paths),  # type: ignore[arg-type]
            )
        )
    return MaterialLocations(tuple(locations))


def render_material_locations(locations: MaterialLocations) -> str:
    if not isinstance(locations, MaterialLocations):
        raise IdentityContractError("locations must be MaterialLocations")
    return json.dumps(
        locations.as_dict(), ensure_ascii=False, sort_keys=True, indent=2
    ) + "\n"


def resolve_material_path(
    material_id: str,
    catalog: IdentityCatalog,
    locations: MaterialLocations,
) -> Path:
    """Resolve a local path only after hashing its complete contents again."""

    material = catalog.material(material_id)
    location = locations.location(material.material_id)
    verified: list[Path] = []
    for raw_path in location.paths:
        path = Path(raw_path)
        if not path.is_file():
            continue
        observed_hash = hash_file_sha256(path)
        observed_size = _file_size(
            path, "located material metadata could not be read"
        )
        if (
            observed_hash != material.content_sha256
            or observed_size != material.byte_size
        ):
            raise LocatorResolutionError(
                "located file does not match the registered Material identity"
            )
        verified.append(path)
    if not verified:
        raise LocatorResolutionError("all registered material locations are missing")
    return verified[0]


def _parse_bound_source_range(value: object, label: str) -> SourceRange:
    mapping = _object(value, label)
    _exact_keys(mapping, _SOURCE_RANGE_KEYS, label)
    try:
        return SourceRange(
            mapping["start_frame"],  # type: ignore[arg-type]
            mapping["end_frame_exclusive"],  # type: ignore[arg-type]
        )
    except FrameBoundaryError as exc:
        raise IdentityContractError(f"{label} is invalid: {exc}") from exc


def bind_boundary_preflight(
    catalog: IdentityCatalog, segments: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    """Validate identity-bound segments and emit boundary_preflight.v1 input.

    This is an upstream adapter. It does not change or extend the frozen
    boundary_preflight.v1 schema.
    """

    if not isinstance(catalog, IdentityCatalog):
        raise IdentityContractError("catalog must be an IdentityCatalog")
    if isinstance(segments, (str, bytes)) or not isinstance(segments, Sequence):
        raise IdentityContractError("segments must be a sequence")
    if not segments:
        raise IdentityContractError("segments must not be empty")

    output_segments: list[dict[str, object]] = []
    for index, raw in enumerate(segments):
        item = _object(raw, f"segments[{index}]")
        allowed = set(_BOUND_SEGMENT_KEYS)
        unknown = sorted(set(item) - allowed)
        required = {"segment_id", "material_id", "candidate_id", "source_range"}
        missing = sorted(required - set(item))
        if unknown:
            raise IdentityContractError(
                f"segments[{index}] has unsupported key(s): {', '.join(unknown)}"
            )
        if missing:
            raise IdentityContractError(
                f"segments[{index}] is missing required key(s): {', '.join(missing)}"
            )

        material = catalog.material(item["material_id"])  # type: ignore[arg-type]
        candidate = catalog.candidate(item["candidate_id"])  # type: ignore[arg-type]
        source_range = _parse_bound_source_range(
            item["source_range"], f"segments[{index}].source_range"
        )
        if candidate.material_id != material.material_id:
            raise IdentityContractError(
                f"segments[{index}] Candidate does not belong to its Material"
            )
        if source_range != candidate.source_range:
            raise IdentityContractError(
                f"segments[{index}] source_range does not match its Candidate identity"
            )

        output: dict[str, object] = {
            "segment_id": item["segment_id"],
            "source_id": material.material_id,
            "candidate_id": candidate.candidate_id,
            "source_range": {
                "start_frame": source_range.start_frame,
                "end_frame_exclusive": source_range.end_frame_exclusive,
            },
        }
        for optional in (
            "continuation_group",
            "verified_safe_end_frame_exclusive",
            "planned_record_frame_relative",
        ):
            if optional in item:
                output[optional] = item[optional]
        output_segments.append(output)

    document: dict[str, object] = {
        "schema_version": BOUNDARY_PREFLIGHT_SCHEMA_VERSION,
        "segments": output_segments,
    }
    parse_preflight_document(document)
    return document
