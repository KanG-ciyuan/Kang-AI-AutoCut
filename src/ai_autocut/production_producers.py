"""Deterministic production steps: artifacts that follow from other artifacts.

These are the artifacts whose content is *determined* by things the job has already
approved — a locked timeline, a placement, a loudness policy. They need no judgement, only
arithmetic and the project's own rules, so they belong in code rather than in an agent.

Everything here reads the job's own artifacts and policies. Nothing here knows what product
it is working on, what the copy says, or what happened on any previous job. A Third-SKU
creative choice that leaked into this module would become every future SKU's default, which
is the failure this repository already guards against in geometry and typography.

Where a value genuinely is a creative choice — where the music sits, what the water sounds
like — this module does not invent one. It composes what the job declared and leaves the
rest to the authoring boundary.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from . import execution_adapters, fast_path, producer_registry


class ProductionProducerError(ValueError):
    """Raised when a deterministic producer cannot derive its artifact."""


#: Audio policy that is not a creative choice. The mix priority is the repository's own
#: rule (VO > evidence sound > BGM) and the ceilings come from the loudness policy.
DEFAULT_MASTER_OUT = "audio/audio_master.wav"
DEFAULT_ASSEMBLY_OUT = "preview/preview.mp4"

#: Gain staging defaults, in dB. These express the mix PRIORITY rather than a taste call:
#: voice loudest, evidence sound under it, music under that. A job may override any of them
#: in audio/mix_policy.json, which is how a SKU states its own balance without editing code.
PRIORITY_GAINS_DB = {"voice": 0.0, "evidence": -6.0, "music": -14.0}


def _read_json(path: Path, label: str) -> Any:
    if not path.is_file():
        raise ProductionProducerError(f"missing {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionProducerError(f"cannot read {label}: {exc}") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write atomically: a failed producer must not leave a half-written artifact behind.

    A partially written request would read as a valid one on the next run, which is how
    stale output becomes trusted output.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        temporary.replace(path)
    except BaseException:
        # Leaving a temporary behind would let a later run mistake debris for progress.
        temporary.unlink(missing_ok=True)
        raise


def _duration_from_timeline(root: Path, *, fps: int = 30) -> float:
    """The locked duration, from the job's own timeline artifact.

    The timeline is frame-based (``end_frame_exclusive`` at the job's fps), because the
    repository keeps every boundary in frames and never in seconds. A seconds-based window
    is also accepted so an older or alternative shape still resolves rather than failing.
    """

    timeline = _read_json(root / "edit" / "timeline_ranges.json", "timeline ranges")
    rate = int(timeline.get("fps") or fps or 30)
    ranges = timeline.get("ranges") or timeline.get("units") or []
    end = 0.0
    for entry in ranges:
        if not isinstance(entry, Mapping):
            continue
        if isinstance(entry.get("end_frame_exclusive"), (int, float)):
            end = max(end, float(entry["end_frame_exclusive"]) / rate)
        elif isinstance(entry.get("end_frame"), (int, float)):
            end = max(end, float(entry["end_frame"]) / rate)
        else:
            window = (entry.get("timeline_seconds") or entry.get("window")
                      or entry.get("seconds"))
            if isinstance(window, (list, tuple)) and len(window) == 2:
                end = max(end, float(window[1]))
            elif isinstance(window, Mapping):
                end = max(end, float(window.get("end", 0.0)))
    if end <= 0.0:
        raise ProductionProducerError(
            "cannot determine the locked duration from edit/timeline_ranges.json: no "
            "end_frame_exclusive, end_frame or seconds window was found")
    return round(end, 3)


def _mix_policy(root: Path) -> dict[str, float]:
    """Job-level overrides, or the repository's priority staging."""

    path = root / "audio" / "mix_policy.json"
    gains = dict(PRIORITY_GAINS_DB)
    if path.is_file():
        declared = _read_json(path, "mix policy").get("gains_db") or {}
        for key, value in declared.items():
            if key in gains:
                gains[key] = float(value)
    return gains


# --------------------------------------------------------------------------- audio


def audio_asset_roles(root: Path) -> dict[str, list[Path]]:
    """Classify this job's local audio assets by the role the mix priority gives them.

    Classification is by the job's own directory layout, which the audio boundary already
    establishes, so no file is guessed and no naming convention is invented here.
    """

    roles: dict[str, list[Path]] = {"voice": [], "music": [], "evidence": []}
    placed = sorted((root / "assets" / "vo_placed").glob("*.wav"))
    roles["voice"] = placed
    for folder, role in (("generated", None),):
        base = root / "assets" / folder
        if not base.is_dir():
            continue
        for path in sorted(base.iterdir()):
            if not path.is_file():
                continue
            name = path.name.upper()
            if "BGM" in name or "MUSIC" in name:
                roles["music"].append(path)
            elif "WATER" in name or "AMBIENCE" in name or "SFX" in name:
                roles["evidence"].append(path)
    return roles


def author_audio_request(root: Path | str) -> bool:
    """Author ``audio/audio_request.json`` from the job's placement and its assets.

    This is the artifact whose absence stopped the Third SKU at BUILD THE AUDIO. Its content
    is fully determined: where each voice line goes comes from ``audio/placement.json``,
    which assets exist comes from the job's own asset folders, and the loudness targets come
    from policy. There is no creative decision in it, which is why it is a producer rather
    than a gate.

    Returns False when a genuinely required input is absent, so the orchestrator can report
    an honest gate instead of writing a request that would fail later.
    """

    root = Path(root)
    placement_path = root / "audio" / "placement.json"
    if not placement_path.is_file():
        return False
    placement = _read_json(placement_path, "audio placement")
    segments = placement.get("segments") or []
    if not segments:
        return False

    roles = audio_asset_roles(root)
    gains = _mix_policy(root)
    assets: list[dict[str, Any]] = []

    # VOICE -- one asset per placed segment, positioned by the approved placement.
    voiced: dict[str, float] = {}
    for segment in segments:
        segment_id = str(segment.get("segment_id", ""))
        for path in roles["voice"]:
            if path.stem == segment_id:
                voiced[segment_id] = float(segment.get("start_seconds", 0.0))
                assets.append({
                    "path": str(path.relative_to(root)),
                    "start_seconds": round(float(segment.get("start_seconds", 0.0)), 3),
                    "gain_db": gains["voice"],
                    "role": "voice",
                })
                break
    if not assets:
        # No per-segment cuts. Fall back to a single continuous voice master placed at the
        # top, which is how a job whose voice has not been cut yet is still mixable. The
        # names searched are the ones the audio boundary itself establishes; nothing is
        # guessed and no file is invented.
        candidates: list[Path] = []
        for pattern in ("VO_*", "voice.*", "vo.*", "voice_*", "*voice*"):
            candidates += [p for p in sorted((root / "assets").glob(pattern)) if p.is_file()]
        if not candidates:
            return False
        master = candidates[-1]
        assets.append({"path": str(master.relative_to(root)), "start_seconds": 0.0,
                       "gain_db": gains["voice"], "role": "voice",
                       "note": "continuous master, not cut per segment"})

    # MUSIC -- one bed, from the job's own generated assets.
    for path in roles["music"][:1]:
        assets.append({"path": str(path.relative_to(root)), "start_seconds": 0.0,
                       "gain_db": gains["music"], "role": "music"})

    # EVIDENCE -- water/ambience, placed only where the job declared a window for it.
    windows = placement.get("evidence_windows") or []
    for window in windows:
        start = float(window.get("start_seconds", 0.0))
        for path in roles["evidence"][:1]:
            assets.append({"path": str(path.relative_to(root)),
                           "start_seconds": round(start, 3),
                           "gain_db": float(window.get("gain_db", gains["evidence"])),
                           "role": "evidence"})
            break

    duration = float(placement.get("duration_seconds") or _duration_from_timeline(root))
    targets = (placement.get("loudness") or {})
    request = {
        "schema_version": "audio_request.v1",
        "job_id": root.name,
        "assets": assets,
        "out": DEFAULT_MASTER_OUT,
        "duration_seconds": round(duration, 3),
        "target_lufs": float(targets.get("target_lufs", -14.0)),
        "true_peak_ceiling_dbtp": float(targets.get("true_peak_ceiling_dbtp", -1.5)),
        "mix_priority": ["voice", "evidence", "music"],
        "notes": ("Authored deterministically from audio/placement.json and this job's own "
                  "assets. Gains express the repository's mix priority; override them in "
                  "audio/mix_policy.json rather than editing code."),
    }
    _write_json(root / "audio" / "audio_request.json", request)
    return True


# --------------------------------------------------------------------------- assemble


def author_assemble_request(root: Path | str) -> bool:
    """Author ``assemble/assemble_request.json`` from the picture and audio masters."""

    root = Path(root)
    picture = root / "typography" / "typography_master.mp4"
    if not picture.is_file():
        picture = root / "picture" / "picture_master.mp4"
    audio = root / DEFAULT_MASTER_OUT
    if not picture.is_file() or not audio.is_file():
        return False
    request = {
        "schema_version": "assemble_request.v1",
        "job_id": root.name,
        "picture": str(picture.relative_to(root)),
        "audio": str(audio.relative_to(root)),
        "out": DEFAULT_ASSEMBLY_OUT,
        # The adapter accepts exactly REMUX or RE_ENCODE. Picture and audio are already
        # mastered at this point, so the master is muxed rather than re-encoded.
        "method": "REMUX",
        "notes": ("Picture and audio are already mastered; assembly muxes them and records "
                  "measured QA. No re-encode of picture content."),
    }
    _write_json(root / "assemble" / "assemble_request.json", request)
    return True


#: artifact -> deterministic producer. The orchestrator reads this table; anything absent
#: falls through to the authoring boundary and is reported as such.
DETERMINISTIC_PRODUCERS: dict[str, Callable[[Path], bool]] = {
    "audio/audio_request.json": author_audio_request,
    "assemble/assemble_request.json": author_assemble_request,
}


__all__ = [
    "DEFAULT_ASSEMBLY_OUT",
    "DEFAULT_MASTER_OUT",
    "DETERMINISTIC_PRODUCERS",
    "PRIORITY_GAINS_DB",
    "ProductionProducerError",
    "audio_asset_roles",
    "author_assemble_request",
    "author_audio_request",
]
