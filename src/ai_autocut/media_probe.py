"""Measured facts about a real media file.

Every function here reads bytes from disk with ffprobe or ffmpeg. Nothing infers a
value from a config, a plan, or a sibling document. That is the point: the Gate G.0
Phase 5 inspection found that assembly could be declared complete against a
nonexistent path and a fabricated hash, because verification never opened the file.

This module exists so that "verified" means *measured*.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence

#: Exit-code-free failure type so callers can turn a bad file into a contract result.
class MediaProbeError(ValueError):
    """Raised when a media file cannot be measured."""


def have_tools(ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> bool:
    return bool(shutil.which(ffmpeg) and shutil.which(ffprobe))


def _run(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), capture_output=True, text=True)


def _require_file(path: str | Path) -> Path:
    target = Path(path)
    if not target.is_file():
        raise MediaProbeError(f"no such media file: {target}")
    return target


def sha256_of_file(path: str | Path) -> str:
    """The real digest of the real bytes. Never a caller-supplied value."""

    target = _require_file(path)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_streams(path: str | Path, *, ffprobe: str = "ffprobe") -> dict[str, Any]:
    """Measured stream facts: frames, fps, geometry, codecs, duration."""

    target = _require_file(path)
    result = _run(
        [
            ffprobe, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(target),
        ]
    )
    if result.returncode != 0:
        raise MediaProbeError(f"ffprobe failed for {target}: {result.stderr[-300:]}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaProbeError(f"ffprobe produced unreadable output for {target}") from exc

    video = next(
        (s for s in payload.get("streams", []) if s.get("codec_type") == "video"), None
    )
    audio = next(
        (s for s in payload.get("streams", []) if s.get("codec_type") == "audio"), None
    )
    if video is None:
        raise MediaProbeError(f"{target} has no video stream")

    def _fraction(value: str | None) -> float:
        if not value or "/" not in value:
            return 0.0
        numerator, _, denominator = value.partition("/")
        try:
            top, bottom = float(numerator), float(denominator)
        except ValueError:
            return 0.0
        return round(top / bottom, 6) if bottom else 0.0

    frames = video.get("nb_frames")
    if frames in (None, "N/A"):
        counted = count_frames(target, ffprobe=ffprobe)
        frames = counted if counted > 0 else None
    try:
        frame_count = int(frames) if frames is not None else None
    except (TypeError, ValueError):
        frame_count = None

    duration = payload.get("format", {}).get("duration")
    return {
        "path": str(target),
        "size_bytes": target.stat().st_size,
        "frame_count": frame_count,
        "fps": _fraction(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "video_codec": video.get("codec_name"),
        "pix_fmt": video.get("pix_fmt"),
        "duration_seconds": round(float(duration), 6) if duration else None,
        "has_audio": audio is not None,
        "audio_codec": (audio or {}).get("codec_name"),
        "audio_channels": int((audio or {}).get("channels") or 0) or None,
        "audio_sample_rate": int((audio or {}).get("sample_rate") or 0) or None,
    }


def count_frames(path: str | Path, *, ffprobe: str = "ffprobe") -> int:
    """Decoded frame count. ``-1`` when it cannot be measured."""

    result = _run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames",
            "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path),
        ]
    )
    token = result.stdout.strip().splitlines()[0].strip() if result.stdout.strip() else ""
    return int(token) if token.isdigit() else -1


#: Section-aware EBU R128 parsing. The ffmpeg summary nests its values under headings,
#: and the label ``Peak`` appears under ``True peak`` — so a flat label match would read
#: the true peak as a sample peak. Each section is parsed separately for that reason.
_E_BUR128_SECTIONS = (
    ("Integrated loudness", "I", "integrated_lufs"),
    ("Loudness range", "LRA", "lra_lu"),
    ("True peak", "Peak", "true_peak_dbtp"),
)
_E_BUR128_SAMPLE_PEAK = re.compile(r"FTPK:\s*(-?\d+(?:\.\d+)?)")


def measure_loudness(path: str | Path, *, ffmpeg: str = "ffmpeg") -> dict[str, float]:
    """Integrated loudness, loudness range, true peak and sample peak, measured.

    Read-only: the filter runs against ``-f null`` so nothing is written. Values come
    from the EBU R128 summary, parsed by section — see the note on the label collision
    above.
    """

    target = _require_file(path)
    result = _run(
        [
            ffmpeg, "-hide_banner", "-nostats", "-i", str(target),
            "-af", "ebur128=peak=true", "-f", "null", "-",
        ]
    )
    text = result.stderr or ""
    if "Summary:" not in text:
        raise MediaProbeError(
            f"could not measure loudness for {target}; ebur128 produced no summary"
        )
    summary = text[text.rfind("Summary:") :]

    values: dict[str, float] = {}
    for heading, label, key in _E_BUR128_SECTIONS:
        marker = f"{heading}:"
        if marker not in summary:
            continue
        section = summary[summary.index(marker) + len(marker) :]
        match = re.search(rf"^\s*{label}\s*:\s*(-?\d+(?:\.\d+)?)", section, re.M)
        if match:
            values[key] = float(match.group(1))

    sample_peaks = _E_BUR128_SAMPLE_PEAK.findall(text)
    if sample_peaks:
        values["sample_peak_dbfs"] = float(sample_peaks[-1])

    if "integrated_lufs" not in values or "true_peak_dbtp" not in values:
        raise MediaProbeError(
            f"could not measure loudness for {target}; the ebur128 summary was "
            "incomplete"
        )
    return values


def count_black_frames(path: str | Path, *, ffmpeg: str = "ffmpeg") -> int:
    """Frames detected as black, using blackdetect over the whole file."""

    target = _require_file(path)
    result = _run(
        [
            ffmpeg, "-hide_banner", "-nostats", "-i", str(target),
            "-vf", "blackdetect=d=0:pix_th=0.10", "-f", "null", "-",
        ]
    )
    return len(re.findall(r"black_start:", result.stderr or ""))


def count_duplicate_frames(path: str | Path, *, ffmpeg: str = "ffmpeg") -> int:
    """Consecutive frames whose decoded pixels are identical.

    Uses per-frame hashes rather than a filter heuristic, matching the project's
    existing "per-frame hash comparison" approach. Three consecutive identical frames
    is the threshold for a freeze, so a two-frame repeat is not reported as one.
    """

    target = _require_file(path)
    result = _run([ffmpeg, "-v", "error", "-i", str(target), "-f", "framemd5", "-"])
    if result.returncode != 0:
        raise MediaProbeError(f"framemd5 failed for {target}: {result.stderr[-300:]}")
    digests: list[str] = []
    for line in result.stdout.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split(",")
        if len(parts) >= 6:
            digests.append(parts[-1].strip())
    duplicates = 0
    run = 1
    for previous, current in zip(digests, digests[1:]):
        if current == previous:
            run += 1
            if run >= 3:
                duplicates += 1
        else:
            run = 1
    return duplicates


def frame_identity(path: str | Path, *, ffmpeg: str = "ffmpeg") -> str:
    """A digest of the decoded stream, for comparing two files frame by frame."""

    target = _require_file(path)
    result = _run([ffmpeg, "-v", "error", "-i", str(target), "-f", "framemd5", "-"])
    if result.returncode != 0:
        raise MediaProbeError(f"framemd5 failed for {target}")
    return hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()


def resolve_media_path(document_path: str | Path, *, job_root: str | Path | None) -> Path:
    """Resolve an evidence path, rejecting anything that escapes the job root."""

    candidate = Path(document_path)
    if not candidate.is_absolute():
        if job_root is None:
            raise MediaProbeError(
                f"evidence path {document_path!r} is relative and no job root was given"
            )
        candidate = Path(job_root) / candidate
    resolved = candidate.resolve()
    if job_root is not None:
        root = Path(job_root).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise MediaProbeError(
                f"evidence path {document_path!r} resolves outside the job root"
            ) from exc
    return resolved


__all__ = [
    "MediaProbeError",
    "count_black_frames",
    "count_duplicate_frames",
    "count_frames",
    "frame_identity",
    "have_tools",
    "measure_loudness",
    "probe_streams",
    "resolve_media_path",
    "sha256_of_file",
]
