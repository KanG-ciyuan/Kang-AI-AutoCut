"""Minimal local, video-only execution for one validated Editing Plan."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import json
from pathlib import Path
import subprocess
from typing import Mapping, Sequence

from .candidate_pool import CandidatePool, parse_candidate_pool
from .editing_plan import EditingPlan, bind_plan_boundary_preflight, parse_editing_plan, validate_editing_plan
from .identity import IdentityCatalog, MaterialLocations, parse_identity_catalog, parse_material_locations, resolve_material_path
from .preflight import build_report, parse_preflight_document, run_preflight


class LocalPreviewError(ValueError):
    """Raised when a local preview cannot be safely produced or verified."""


@dataclass(frozen=True)
class VideoProbe:
    codec_name: str
    width: int
    height: int
    fps: Fraction
    decoded_frame_count: int
    duration_seconds: float


@dataclass(frozen=True)
class LocalPreviewResult:
    preview_path: Path
    ffmpeg_command: tuple[str, ...]
    expected_frame_count: int
    expected_duration_seconds: float
    output: VideoProbe


_RUNTIME_FILES = {
    "catalog": "identity_catalog.json",
    "locations": "material_locations.json",
    "pool": "candidate_pool.json",
    "plan": "editing_plan.json",
    "preflight": "boundary_preflight_input.json",
    "report": "boundary_preflight_report.json",
}


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalPreviewError("runtime document is missing or malformed") from exc


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LocalPreviewError(f"{label} must be a positive integer")
    return value


def _positive_frame_count(value: object) -> int:
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    return _positive_integer(value, "decoded frame count")


def _fraction(value: object, label: str) -> Fraction:
    if not isinstance(value, str):
        raise LocalPreviewError(f"{label} is missing or malformed")
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise LocalPreviewError(f"{label} is missing or malformed") from exc
    if result <= 0:
        raise LocalPreviewError(f"{label} must be positive")
    return result


def probe_video(path: Path, stream_index: int, ffprobe_binary: str) -> VideoProbe:
    """Return frame-counted video facts, refusing missing or ambiguous streams."""

    command = (
        ffprobe_binary,
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        f"v:{stream_index}",
        "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate,nb_read_frames",
        "-of",
        "json",
        str(path),
    )
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise LocalPreviewError("ffprobe could not be started") from exc
    if completed.returncode != 0:
        raise LocalPreviewError("ffprobe rejected the media")
    try:
        payload = json.loads(completed.stdout)
        streams = payload["streams"]
        if not isinstance(streams, list) or len(streams) != 1:
            raise ValueError("expected exactly one selected stream")
        stream = streams[0]
        if not isinstance(stream, Mapping) or stream.get("codec_type") != "video":
            raise ValueError("selected stream is not video")
        frame_count = _positive_frame_count(stream.get("nb_read_frames"))
        duration = float(payload["format"]["duration"])
        if duration <= 0:
            raise ValueError("duration")
        return VideoProbe(
            codec_name=str(stream["codec_name"]),
            width=_positive_integer(stream.get("width"), "video width"),
            height=_positive_integer(stream.get("height"), "video height"),
            fps=_fraction(stream.get("avg_frame_rate"), "video frame rate"),
            decoded_frame_count=frame_count,
            duration_seconds=duration,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LocalPreviewError("ffprobe did not provide reliable video facts") from exc


def build_filter_graph(candidates: Sequence[object]) -> str:
    """Build the deterministic frame-based trim/setpts/concat graph."""

    if not candidates:
        raise LocalPreviewError("editing plan must contain at least one Candidate")
    parts: list[str] = []
    labels: list[str] = []
    for position, candidate in enumerate(candidates):
        try:
            stream_index = candidate.stream_index
            start = candidate.start_frame
            end = candidate.end_frame_exclusive
        except AttributeError as exc:
            raise LocalPreviewError("resolved Candidate is malformed") from exc
        label = f"v{position}"
        parts.append(
            f"[0:v:{stream_index}]trim=start_frame={start}:end_frame={end},"
            f"setpts=PTS-STARTPTS[{label}]"
        )
        labels.append(f"[{label}]")
    parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[vout]")
    return ";".join(parts)


def _load_and_validate_runtime(runtime_dir: Path) -> tuple[
    IdentityCatalog, MaterialLocations, CandidatePool, EditingPlan, tuple[object, ...]
]:
    documents = {name: _read_json(runtime_dir / filename) for name, filename in _RUNTIME_FILES.items()}
    try:
        catalog = parse_identity_catalog(documents["catalog"])
        locations = parse_material_locations(documents["locations"])
        pool = parse_candidate_pool(documents["pool"])
        plan = parse_editing_plan(documents["plan"])
        candidates = validate_editing_plan(plan, pool, catalog)
        prepared_segments = parse_preflight_document(documents["preflight"])
        prepared_report = build_report(run_preflight(prepared_segments))
        if documents["report"] != prepared_report:
            raise LocalPreviewError("prepared Boundary Preflight report does not match its input")
        if not prepared_report["passed"] or prepared_report["issues"]:
            raise LocalPreviewError("Boundary Preflight reported issue(s)")
        if documents["preflight"] != bind_plan_boundary_preflight(plan, pool, catalog):
            raise LocalPreviewError("prepared Boundary Preflight input does not match the Plan chain")
        return catalog, locations, pool, plan, candidates
    except LocalPreviewError:
        raise
    except (ValueError, TypeError) as exc:
        raise LocalPreviewError("runtime documents failed contract validation") from exc


def execute_local_preview(
    runtime_dir: str | Path,
    preview_path: str | Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
) -> LocalPreviewResult:
    """Validate the frozen chain, render one video-only MP4, then verify it."""

    runtime = Path(runtime_dir)
    output_path = Path(preview_path)
    catalog, locations, _pool, _plan, candidates = _load_and_validate_runtime(runtime)
    material_ids = {candidate.material_id for candidate in candidates}
    stream_indexes = {candidate.stream_index for candidate in candidates}
    if len(material_ids) != 1 or stream_indexes != {0}:
        raise LocalPreviewError("minimal local preview supports one Material video stream 0")
    material_id = next(iter(material_ids))
    try:
        source_path = resolve_material_path(material_id, catalog, locations)
    except ValueError as exc:
        raise LocalPreviewError("Material locator verification failed") from exc
    if source_path.resolve() == output_path.resolve():
        raise LocalPreviewError("preview output must not overwrite source media")
    source_probe = probe_video(source_path, 0, ffprobe_binary)
    if any(candidate.end_frame_exclusive > source_probe.decoded_frame_count for candidate in candidates):
        raise LocalPreviewError("Candidate frame range exceeds decoded source media")
    expected_frames = sum(
        candidate.end_frame_exclusive - candidate.start_frame for candidate in candidates
    )
    expected_duration = float(Fraction(expected_frames, 1) / source_probe.fps)
    if output_path.exists():
        raise LocalPreviewError("preview output already exists")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = (
        ffmpeg_binary,
        "-hide_banner",
        "-nostdin",
        "-n",
        "-i",
        str(source_path),
        "-filter_complex",
        build_filter_graph(candidates),
        "-map",
        "[vout]",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    )
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise LocalPreviewError("ffmpeg could not be started") from exc
    if completed.returncode != 0:
        raise LocalPreviewError("ffmpeg failed to generate the preview")
    if not output_path.is_file():
        raise LocalPreviewError("ffmpeg reported success but preview is missing")
    output_probe = probe_video(output_path, 0, ffprobe_binary)
    if output_probe.decoded_frame_count != expected_frames:
        raise LocalPreviewError("preview decoded frame count does not match the Editing Plan")
    if (output_probe.width, output_probe.height, output_probe.fps) != (
        source_probe.width,
        source_probe.height,
        source_probe.fps,
    ):
        raise LocalPreviewError("preview video geometry does not match the source stream")
    if abs(output_probe.duration_seconds - expected_duration) > float(1 / source_probe.fps):
        raise LocalPreviewError("preview duration does not match the Editing Plan")
    return LocalPreviewResult(
        preview_path=output_path,
        ffmpeg_command=command,
        expected_frame_count=expected_frames,
        expected_duration_seconds=expected_duration,
        output=output_probe,
    )
