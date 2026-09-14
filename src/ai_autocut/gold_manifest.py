"""``gold_manifest.v1`` — the lightweight, media-free Gold record.

A Gold Manifest states what was actually validated, by which immutable
artifact, and how far that artifact has been reconciled with the canonical
repository. It is deliberately a *record*, not a build manifest:

* it never stores media bytes, media directories, or provider dumps;
* it stores exactly one SHA-256 per artifact, plus logical metadata;
* every asset reference is a bare filename plus a storage class, so the
  document stays machine-independent.

The manifest is also a governance object. It cannot claim a frozen or
released state by itself: promotion is an explicit, separately reviewed act.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping, Sequence

from .paths import looks_like_machine_path


SCHEMA_VERSION = "gold_manifest.v1"

# Gold lifecycle states. ``FROZEN`` is reserved for an explicit upper-review
# decision; automated writeback must never promote a manifest into it.
GOLD_STATUSES = (
    "PASS_WITH_RECONCILIATION_REQUIRED",
    "RECONCILED",
    "FROZEN",
    "SUPERSEDED",
    "REJECTED",
)

GOLD_ID_STATUSES = ("PROVISIONAL_INTERNAL", "CONFIRMED")

ASSET_STATUSES = (
    "EXTERNAL_ASSET_NOT_YET_RECONCILED",
    "EXTERNAL_ASSET_VERIFIED",
    "EXTERNAL_ASSET_MISSING",
)

STORAGE_CLASSES = (
    "EXTERNAL_WORKSPACE",
    "LOCAL_RUNTIME",
    "LEGACY_RD_WORKSPACE",
    "REPOSITORY",
)

TEXT_ROLES = ("hook", "feature", "cta")

VOICE_OVER_STRATEGIES = (
    "CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS",
    "INDEPENDENT_PER_SENTENCE",
)

VISUAL_AUTHORITY_ROLES = ("FINAL_FROZEN_VISUAL_SOURCE", "CANDIDATE", "SUPERSEDED")

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_GOLD_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}\Z")
_SAFE_FILENAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

_MANIFEST_KEYS = (
    "schema_version",
    "gold_id",
    "gold_id_status",
    "status",
    "timeline",
    "editorial_text",
    "voice_over",
    "visual_authority",
    "color_strategy",
    "typography_strategy",
    "audio_strategy",
    "master",
    "loudness",
    "external_assets",
    "reconciliation",
)
_TIMELINE_KEYS = ("frames", "fps", "duration_seconds", "width", "height")
_TEXT_KEYS = ("role", "lines")
_VOICE_OVER_KEYS = ("strategy", "lines")
_VOICE_LINE_KEYS = ("id", "text")
_VISUAL_KEYS = ("role", "filename", "sha256", "frames", "has_audio")
_MASTER_KEYS = ("master_id", "filename", "sha256", "frames", "duration_seconds", "selected")
_ASSET_KEYS = ("logical_role", "filename", "sha256", "storage_class", "asset_status")
_LOUDNESS_KEYS = ("reference", "measured")
_LOUDNESS_VALUE_KEYS = ("integrated_lufs", "true_peak_dbtp")
_RECONCILIATION_KEYS = ("asset_status", "canonical_status", "notes")

# 518 / 30 == 17.2666...; declared durations are allowed this much slack.
_DURATION_TOLERANCE_SECONDS = 1e-4


class GoldManifestContractError(ValueError):
    """Raised when a Gold Manifest cannot be trusted as a record."""


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise GoldManifestContractError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise GoldManifestContractError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise GoldManifestContractError(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise GoldManifestContractError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoldManifestContractError(f"{label} must be a non-empty string")
    if looks_like_machine_path(value):
        raise GoldManifestContractError(
            f"{label} is a machine-bound path; Gold records must stay machine-independent"
        )
    return value


def _enum(value: object, allowed: Sequence[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise GoldManifestContractError(
            f"{label} must be one of: {', '.join(allowed)}"
        )
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GoldManifestContractError(f"{label} must be a positive integer")
    return value


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GoldManifestContractError(f"{label} must be a number")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise GoldManifestContractError(f"{label} must be a finite number")
    return number


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise GoldManifestContractError(f"{label} must be 64 lowercase hex characters")
    return value


def _safe_filename(value: object, label: str) -> str:
    if not isinstance(value, str) or _SAFE_FILENAME_PATTERN.fullmatch(value) is None:
        raise GoldManifestContractError(
            f"{label} must be a bare filename without a directory component"
        )
    return value


def sha256_of_file(path: object, *, chunk_size: int = 1 << 20) -> str:
    """Hash a file's exact bytes so a record can be checked against reality."""

    from pathlib import Path

    if not isinstance(path, (str, Path)):
        raise GoldManifestContractError("path must be a path")
    target = Path(path)
    digest = hashlib.sha256()
    try:
        with target.open("rb") as handle:
            while True:
                block = handle.read(chunk_size)
                if not block:
                    break
                digest.update(block)
    except OSError as exc:
        raise GoldManifestContractError("asset could not be read for hashing") from exc
    return digest.hexdigest()


def _walk_for_machine_paths(value: object, label: str) -> None:
    if isinstance(value, str):
        if looks_like_machine_path(value):
            raise GoldManifestContractError(
                f"{label} contains a machine-bound path; Gold records must stay "
                "machine-independent"
            )
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _walk_for_machine_paths(item, f"{label}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk_for_machine_paths(item, f"{label}[{index}]")


@dataclass(frozen=True)
class EditorialTextEvent:
    role: str
    lines: tuple[str, ...]

    def __post_init__(self) -> None:
        _enum(self.role, TEXT_ROLES, "editorial_text.role")
        if not self.lines:
            raise GoldManifestContractError("editorial_text.lines must not be empty")
        for index, line in enumerate(self.lines):
            _text(line, f"editorial_text.lines[{index}]")

    def as_dict(self) -> dict[str, object]:
        return {"role": self.role, "lines": list(self.lines)}


@dataclass(frozen=True)
class VoiceOverLine:
    id: str
    text: str

    def __post_init__(self) -> None:
        _text(self.id, "voice_over.lines[].id")
        _text(self.text, "voice_over.lines[].text")

    def as_dict(self) -> dict[str, object]:
        return {"id": self.id, "text": self.text}


@dataclass(frozen=True)
class VoiceOverRecord:
    strategy: str
    lines: tuple[VoiceOverLine, ...]

    def __post_init__(self) -> None:
        _enum(self.strategy, VOICE_OVER_STRATEGIES, "voice_over.strategy")
        if not self.lines:
            raise GoldManifestContractError("voice_over.lines must not be empty")

    def as_dict(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "lines": [line.as_dict() for line in self.lines],
        }


@dataclass(frozen=True)
class GoldAssetReference:
    logical_role: str
    filename: str
    sha256: str
    storage_class: str
    asset_status: str

    def __post_init__(self) -> None:
        _text(self.logical_role, "external_assets[].logical_role")
        _safe_filename(self.filename, "external_assets[].filename")
        _sha256(self.sha256, "external_assets[].sha256")
        _enum(self.storage_class, STORAGE_CLASSES, "external_assets[].storage_class")
        _enum(self.asset_status, ASSET_STATUSES, "external_assets[].asset_status")

    def as_dict(self) -> dict[str, object]:
        return {
            "logical_role": self.logical_role,
            "filename": self.filename,
            "sha256": self.sha256,
            "storage_class": self.storage_class,
            "asset_status": self.asset_status,
        }


@dataclass(frozen=True)
class VisualAuthority:
    role: str
    filename: str
    sha256: str
    frames: int
    has_audio: bool

    def __post_init__(self) -> None:
        _enum(self.role, VISUAL_AUTHORITY_ROLES, "visual_authority.role")
        _safe_filename(self.filename, "visual_authority.filename")
        _sha256(self.sha256, "visual_authority.sha256")
        _positive_int(self.frames, "visual_authority.frames")
        if not isinstance(self.has_audio, bool):
            raise GoldManifestContractError("visual_authority.has_audio must be a boolean")

    def as_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "filename": self.filename,
            "sha256": self.sha256,
            "frames": self.frames,
            "has_audio": self.has_audio,
        }


@dataclass(frozen=True)
class MasterRecord:
    master_id: str
    filename: str
    sha256: str
    frames: int
    duration_seconds: float
    selected: bool

    def __post_init__(self) -> None:
        _text(self.master_id, "master.master_id")
        _safe_filename(self.filename, "master.filename")
        _sha256(self.sha256, "master.sha256")
        _positive_int(self.frames, "master.frames")
        if _finite_number(self.duration_seconds, "master.duration_seconds") <= 0:
            raise GoldManifestContractError("master.duration_seconds must be positive")
        if not isinstance(self.selected, bool):
            raise GoldManifestContractError("master.selected must be a boolean")

    def as_dict(self) -> dict[str, object]:
        return {
            "master_id": self.master_id,
            "filename": self.filename,
            "sha256": self.sha256,
            "frames": self.frames,
            "duration_seconds": self.duration_seconds,
            "selected": self.selected,
        }


def _loudness_pair(value: object, label: str) -> dict[str, float]:
    mapping = _object(value, label)
    _exact_keys(mapping, _LOUDNESS_VALUE_KEYS, label)
    integrated = _finite_number(mapping["integrated_lufs"], f"{label}.integrated_lufs")
    peak = _finite_number(mapping["true_peak_dbtp"], f"{label}.true_peak_dbtp")
    if integrated >= 0:
        raise GoldManifestContractError(f"{label}.integrated_lufs must be negative")
    if peak > 0:
        raise GoldManifestContractError(f"{label}.true_peak_dbtp must not be positive")
    return {"integrated_lufs": integrated, "true_peak_dbtp": peak}


@dataclass(frozen=True)
class GoldManifest:
    gold_id: str
    gold_id_status: str
    status: str
    timeline: Mapping[str, object]
    editorial_text: tuple[EditorialTextEvent, ...]
    voice_over: VoiceOverRecord
    visual_authority: VisualAuthority
    color_strategy: Mapping[str, object]
    typography_strategy: Mapping[str, object]
    audio_strategy: Mapping[str, object]
    master: MasterRecord
    loudness: Mapping[str, Mapping[str, float]]
    external_assets: tuple[GoldAssetReference, ...]
    reconciliation: Mapping[str, object]

    @property
    def frames(self) -> int:
        return int(self.timeline["frames"])  # type: ignore[arg-type]

    @property
    def fps(self) -> float:
        return float(self.timeline["fps"])  # type: ignore[arg-type]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "gold_id": self.gold_id,
            "gold_id_status": self.gold_id_status,
            "status": self.status,
            "timeline": dict(self.timeline),
            "editorial_text": [event.as_dict() for event in self.editorial_text],
            "voice_over": self.voice_over.as_dict(),
            "visual_authority": self.visual_authority.as_dict(),
            "color_strategy": dict(self.color_strategy),
            "typography_strategy": dict(self.typography_strategy),
            "audio_strategy": dict(self.audio_strategy),
            "master": self.master.as_dict(),
            "loudness": {key: dict(value) for key, value in self.loudness.items()},
            "external_assets": [asset.as_dict() for asset in self.external_assets],
            "reconciliation": dict(self.reconciliation),
        }


def _parse_timeline(value: object) -> dict[str, object]:
    mapping = _object(value, "timeline")
    _exact_keys(mapping, _TIMELINE_KEYS, "timeline")
    frames = _positive_int(mapping["frames"], "timeline.frames")
    fps = _finite_number(mapping["fps"], "timeline.fps")
    if fps <= 0:
        raise GoldManifestContractError("timeline.fps must be positive")
    duration = _finite_number(mapping["duration_seconds"], "timeline.duration_seconds")
    expected = frames / fps
    if abs(duration - expected) > _DURATION_TOLERANCE_SECONDS:
        raise GoldManifestContractError(
            f"timeline.duration_seconds does not match frames/fps "
            f"({frames}/{fps} = {expected:.6f})"
        )
    return {
        "frames": frames,
        "fps": fps,
        "duration_seconds": duration,
        "width": _positive_int(mapping["width"], "timeline.width"),
        "height": _positive_int(mapping["height"], "timeline.height"),
    }


def _parse_editorial_text(value: object) -> tuple[EditorialTextEvent, ...]:
    events: list[EditorialTextEvent] = []
    for index, raw in enumerate(_array(value, "editorial_text")):
        label = f"editorial_text[{index}]"
        item = _object(raw, label)
        _exact_keys(item, _TEXT_KEYS, label)
        lines = _array(item["lines"], f"{label}.lines")
        events.append(
            EditorialTextEvent(
                _enum(item["role"], TEXT_ROLES, f"{label}.role"),
                tuple(_text(line, f"{label}.lines[{i}]") for i, line in enumerate(lines)),
            )
        )
    if not events:
        raise GoldManifestContractError("editorial_text must not be empty")
    roles = [event.role for event in events]
    if len(roles) != len(set(roles)):
        raise GoldManifestContractError("editorial_text roles must be unique")
    return tuple(events)


def _parse_voice_over(value: object) -> VoiceOverRecord:
    mapping = _object(value, "voice_over")
    _exact_keys(mapping, _VOICE_OVER_KEYS, "voice_over")
    lines: list[VoiceOverLine] = []
    for index, raw in enumerate(_array(mapping["lines"], "voice_over.lines")):
        label = f"voice_over.lines[{index}]"
        item = _object(raw, label)
        _exact_keys(item, _VOICE_LINE_KEYS, label)
        lines.append(VoiceOverLine(item["id"], item["text"]))  # type: ignore[arg-type]
    return VoiceOverRecord(
        _enum(mapping["strategy"], VOICE_OVER_STRATEGIES, "voice_over.strategy"),
        tuple(lines),
    )


def _parse_visual_authority(value: object) -> VisualAuthority:
    mapping = _object(value, "visual_authority")
    _exact_keys(mapping, _VISUAL_KEYS, "visual_authority")
    return VisualAuthority(
        role=mapping["role"],  # type: ignore[arg-type]
        filename=mapping["filename"],  # type: ignore[arg-type]
        sha256=mapping["sha256"],  # type: ignore[arg-type]
        frames=mapping["frames"],  # type: ignore[arg-type]
        has_audio=mapping["has_audio"],  # type: ignore[arg-type]
    )


def _parse_master(value: object) -> MasterRecord:
    mapping = _object(value, "master")
    _exact_keys(mapping, _MASTER_KEYS, "master")
    return MasterRecord(
        master_id=mapping["master_id"],  # type: ignore[arg-type]
        filename=mapping["filename"],  # type: ignore[arg-type]
        sha256=mapping["sha256"],  # type: ignore[arg-type]
        frames=mapping["frames"],  # type: ignore[arg-type]
        duration_seconds=mapping["duration_seconds"],  # type: ignore[arg-type]
        selected=mapping["selected"],  # type: ignore[arg-type]
    )


def _parse_external_assets(value: object) -> tuple[GoldAssetReference, ...]:
    assets: list[GoldAssetReference] = []
    for index, raw in enumerate(_array(value, "external_assets")):
        label = f"external_assets[{index}]"
        item = _object(raw, label)
        _exact_keys(item, _ASSET_KEYS, label)
        assets.append(
            GoldAssetReference(
                logical_role=item["logical_role"],  # type: ignore[arg-type]
                filename=item["filename"],  # type: ignore[arg-type]
                sha256=item["sha256"],  # type: ignore[arg-type]
                storage_class=item["storage_class"],  # type: ignore[arg-type]
                asset_status=item["asset_status"],  # type: ignore[arg-type]
            )
        )
    return tuple(assets)


def parse_gold_manifest(document: object) -> GoldManifest:
    """Parse and fully validate one ``gold_manifest.v1`` document."""

    _walk_for_machine_paths(document, "gold_manifest")
    mapping = _object(document, "gold manifest")
    _exact_keys(mapping, _MANIFEST_KEYS, "gold manifest")
    if mapping["schema_version"] != SCHEMA_VERSION:
        raise GoldManifestContractError(f"schema_version must be {SCHEMA_VERSION!r}")

    gold_id = mapping["gold_id"]
    if not isinstance(gold_id, str) or _GOLD_ID_PATTERN.fullmatch(gold_id) is None:
        raise GoldManifestContractError(
            "gold_id must be a short lowercase identifier"
        )

    reconciliation = _object(mapping["reconciliation"], "reconciliation")
    _exact_keys(reconciliation, _RECONCILIATION_KEYS, "reconciliation")
    for index, note in enumerate(_array(reconciliation["notes"], "reconciliation.notes")):
        _text(note, f"reconciliation.notes[{index}]")

    timeline = _parse_timeline(mapping["timeline"])
    master = _parse_master(mapping["master"])
    if master.frames != timeline["frames"]:
        raise GoldManifestContractError(
            "master.frames must equal timeline.frames for one Gold record"
        )
    if abs(float(master.duration_seconds) - float(timeline["duration_seconds"])) > (
        _DURATION_TOLERANCE_SECONDS
    ):
        raise GoldManifestContractError(
            "master.duration_seconds must equal timeline.duration_seconds"
        )

    loudness_raw = _object(mapping["loudness"], "loudness")
    _exact_keys(loudness_raw, _LOUDNESS_KEYS, "loudness")

    return GoldManifest(
        gold_id=gold_id,
        gold_id_status=_enum(mapping["gold_id_status"], GOLD_ID_STATUSES, "gold_id_status"),
        status=_enum(mapping["status"], GOLD_STATUSES, "status"),
        timeline=timeline,
        editorial_text=_parse_editorial_text(mapping["editorial_text"]),
        voice_over=_parse_voice_over(mapping["voice_over"]),
        visual_authority=_parse_visual_authority(mapping["visual_authority"]),
        color_strategy=_object(mapping["color_strategy"], "color_strategy"),
        typography_strategy=_object(mapping["typography_strategy"], "typography_strategy"),
        audio_strategy=_object(mapping["audio_strategy"], "audio_strategy"),
        master=master,
        loudness={
            "reference": _loudness_pair(loudness_raw["reference"], "loudness.reference"),
            "measured": _loudness_pair(loudness_raw["measured"], "loudness.measured"),
        },
        external_assets=_parse_external_assets(mapping["external_assets"]),
        reconciliation={
            "asset_status": _enum(
                reconciliation["asset_status"], ASSET_STATUSES, "reconciliation.asset_status"
            ),
            "canonical_status": _text(
                reconciliation["canonical_status"], "reconciliation.canonical_status"
            ),
            "notes": list(reconciliation["notes"]),  # type: ignore[arg-type]
        },
    )


def render_gold_manifest(manifest: GoldManifest) -> str:
    if not isinstance(manifest, GoldManifest):
        raise GoldManifestContractError("manifest must be a GoldManifest")
    return json.dumps(manifest.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def verify_asset_reference(asset: GoldAssetReference, path: object) -> None:
    """Fail unless a located file's exact bytes match the recorded hash."""

    if not isinstance(asset, GoldAssetReference):
        raise GoldManifestContractError("asset must be a GoldAssetReference")
    actual = sha256_of_file(path)
    if actual != asset.sha256:
        raise GoldManifestContractError(
            "located asset bytes do not match the recorded SHA-256"
        )


def assert_not_promoted(manifest: GoldManifest) -> None:
    """Guard: automated writeback may not declare a frozen Gold."""

    if not isinstance(manifest, GoldManifest):
        raise GoldManifestContractError("manifest must be a GoldManifest")
    if manifest.status == "FROZEN":
        raise GoldManifestContractError(
            "FROZEN is an upper-review decision; automation must not set it"
        )
