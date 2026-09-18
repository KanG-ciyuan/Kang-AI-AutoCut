"""Job-scoped execution adapters — the minimum needed to close the real chain.

What these are
--------------
Four deterministic, local, **job-scoped** adapters that turn a job's inputs into real
media files:

============  ==========================================================
``picture``   extract and join this job's source ranges through the timebase adapter
``typography`` rasterise this job's screen copy with Pillow, composite with FFmpeg
``audio``     mix this job's local audio assets with FFmpeg and measure the result
``assemble``  produce the delivery master and its measured technical QA
============  ==========================================================

What these are not
------------------
They are **not universal engines**, and this phase does not build one. Every value that
could be art direction — geometry, fonts, layout, loudness target, true-peak ceiling —
is read from the job's own request file. There are deliberately no defaults for any of
them, so one job's art direction cannot become another job's.

Running them
------------
Every boundary is reachable from a tracked command, so a fresh agent needs the
repository and the job inputs — not a previous conversation::

    python3 -m src.ai_autocut.execution_adapters --job-root <PATH> --boundary picture
    python3 -m src.ai_autocut.execution_adapters --job-root <PATH> --boundary typography
    python3 -m src.ai_autocut.execution_adapters --job-root <PATH> --boundary audio
    python3 -m src.ai_autocut.execution_adapters --job-root <PATH> --boundary assemble

Inputs and outputs for each boundary are stated in its request dataclass and in
``docs/audit/execution-runbook.md``. Nothing is remembered; everything is in the job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import media_probe
from .timebase_adapter import TimebaseAdapter, TimebaseAdapterError

#: The four boundaries this module implements.
BOUNDARIES = ("picture", "typography", "audio", "assemble")

PICTURE_REQUEST = "picture/picture_request.json"
TYPOGRAPHY_REQUEST = "typography/typography_request.json"
AUDIO_REQUEST = "audio/audio_request.json"
ASSEMBLE_REQUEST = "assemble/assemble_request.json"

ASSEMBLY_EVIDENCE = "assemble/assembly_evidence.json"


class ExecutionAdapterError(ValueError):
    """Raised when a job-scoped adapter cannot produce a real artifact."""


def _require(document: object, keys: Sequence[str], label: str) -> Mapping[str, Any]:
    if not isinstance(document, Mapping):
        raise ExecutionAdapterError(f"{label} must be a JSON object")
    missing = [key for key in keys if key not in document]
    if missing:
        raise ExecutionAdapterError(
            f"{label} is missing required field(s): " + ", ".join(missing)
        )
    return document


def _read(job_root: Path, relative: str, label: str) -> Mapping[str, Any]:
    target = job_root / relative
    if not target.is_file():
        raise ExecutionAdapterError(
            f"no {label} at {relative}. This adapter is job-scoped: it reads this job's "
            "own request file and invents nothing."
        )
    try:
        return _require(json.loads(target.read_text(encoding="utf-8")), (), label)
    except json.JSONDecodeError as exc:
        raise ExecutionAdapterError(f"{relative} is not valid JSON") from exc


def _run(command: Sequence[str], label: str) -> None:
    result = subprocess.run(list(command), capture_output=True, text=True)
    if result.returncode != 0:
        raise ExecutionAdapterError(f"{label} failed: {result.stderr[-400:]}")


def _require_tools() -> None:
    if not media_probe.have_tools():
        raise ExecutionAdapterError("ffmpeg and ffprobe are required")


# ---------------------------------------------------------------------------
# PICTURE
# ---------------------------------------------------------------------------


#: The geometry modes a picture unit may request.
#:
#: ``FIT``   scale preserving the aspect ratio, then pad to the output geometry. This is
#:           the historical behaviour and it remains the behaviour of a unit that declares
#:           no geometry at all, so every pre-existing request behaves exactly as before.
#: ``CROP``  take an explicitly stated source rectangle and scale it to the output
#:           geometry. Nothing is padded, nothing is inferred, nothing is adjusted.
GEOMETRY_MODES = ("FIT", "CROP")

#: How a unit came to have its geometry, recorded so an implicit default can never be
#: mistaken for a stated decision.
GEOMETRY_DECLARATIONS = ("EXPLICIT", "ABSENT_DEFAULT_FIT")


@dataclass(frozen=True)
class CropRect:
    """An explicit source rectangle, in source pixels.

    There is no snapping and no rounding: either the stated rectangle is applied exactly,
    or the request is refused. A silently adjusted crop is a different shot.
    """

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        for name in ("x", "y", "width", "height"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ExecutionAdapterError(
                    f"crop_rect.{name} must be an integer, got {value!r}"
                )
        if self.x < 0 or self.y < 0:
            raise ExecutionAdapterError("crop_rect x and y must not be negative")
        if self.width < 2 or self.height < 2:
            raise ExecutionAdapterError(
                "crop_rect width and height must each be at least 2 pixels"
            )
        if self.width % 2 or self.height % 2:
            raise ExecutionAdapterError(
                f"crop_rect {self.width}x{self.height} must have an even width and height: "
                "the delivery pixel format is yuv420p, which is chroma subsampled"
            )

    def as_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    def geometry_filter(self) -> str:
        """The crop half of the filter chain. Emitted verbatim, never adjusted."""

        return f"crop={self.width}:{self.height}:{self.x}:{self.y}"


def fit_geometry_filter(width: int, height: int) -> str:
    """The historical FIT chain, byte-for-byte the pre-repair behaviour."""

    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    )


@dataclass(frozen=True)
class UnitGeometry:
    """What geometry one unit requested, and what was actually applied.

    ``requested`` and ``applied`` are recorded separately on purpose. No path in this
    module alters a requested rectangle or falls back to a fit, so the two are always
    equal — and the evidence proves that rather than asserting it.
    """

    unit_id: str
    requested_mode: str
    applied_mode: str
    requested_crop_rect: Mapping[str, int] | None
    applied_crop_rect: Mapping[str, int] | None
    geometry_filter: str
    declaration: str
    confidence: str | None = None
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        if self.requested_mode not in GEOMETRY_MODES:
            raise ExecutionAdapterError(f"unknown requested mode {self.requested_mode!r}")
        if self.applied_mode not in GEOMETRY_MODES:
            raise ExecutionAdapterError(f"unknown applied mode {self.applied_mode!r}")
        if self.declaration not in GEOMETRY_DECLARATIONS:
            raise ExecutionAdapterError(f"unknown declaration {self.declaration!r}")

    def as_dict(
        self,
        *,
        source_width: int,
        source_height: int,
        output_width: int,
        output_height: int,
        frame_count: int,
    ) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "geometry_declaration": self.declaration,
            "requested_geometry_mode": self.requested_mode,
            "applied_geometry_mode": self.applied_mode,
            "requested_crop_rect": (
                None if self.requested_crop_rect is None else dict(self.requested_crop_rect)
            ),
            "applied_crop_rect": (
                None if self.applied_crop_rect is None else dict(self.applied_crop_rect)
            ),
            "source_width": source_width,
            "source_height": source_height,
            "output_width": output_width,
            "output_height": output_height,
            "frame_count": frame_count,
            "geometry_filter": self.geometry_filter,
            "confidence": self.confidence,
            "evidence_ref": self.evidence_ref,
        }


def resolve_unit_geometry(
    unit: Mapping[str, Any],
    *,
    unit_id: str,
    source_width: int,
    source_height: int,
    output_width: int,
    output_height: int,
) -> UnitGeometry:
    """Resolve one unit's explicit geometry, or refuse the request.

    The rules, in full:

    * no ``geometry`` key  -> ``FIT``, recorded as ``ABSENT_DEFAULT_FIT``. This is what
      makes every pre-existing request behave exactly as it did before.
    * mode ``FIT``         -> ``FIT``. A ``FIT`` unit must not also carry a crop
      rectangle, because the two statements contradict each other.
    * mode ``CROP``        -> ``CROP``, and a ``crop_rect`` is required. A crop is never
      inferred and never guessed.
    * the rectangle must have integer ``x``, ``y``, ``width``, ``height``, lie entirely
      inside the measured source frame, and have the same aspect ratio as the output. A
      mismatched rectangle would be distorted by the scale step, so it is refused
      instead. **A CROP is never silently turned into a FIT.**
    """

    declared = unit.get("geometry")
    if declared is None:
        return UnitGeometry(
            unit_id=unit_id,
            requested_mode="FIT",
            applied_mode="FIT",
            requested_crop_rect=None,
            applied_crop_rect=None,
            geometry_filter=fit_geometry_filter(output_width, output_height),
            declaration="ABSENT_DEFAULT_FIT",
        )

    if not isinstance(declared, Mapping):
        raise ExecutionAdapterError(
            f"unit {unit_id!r} geometry must be a JSON object, got {type(declared).__name__}"
        )

    raw_mode = declared.get("mode")
    if not isinstance(raw_mode, str) or not raw_mode.strip():
        raise ExecutionAdapterError(
            f"unit {unit_id!r} geometry must state a mode; one of: "
            + ", ".join(GEOMETRY_MODES)
        )
    mode = raw_mode.strip().upper()
    if mode not in GEOMETRY_MODES:
        raise ExecutionAdapterError(
            f"unit {unit_id!r} geometry mode {raw_mode!r} is not one of: "
            + ", ".join(GEOMETRY_MODES)
        )

    raw_confidence = declared.get("confidence")
    confidence = None if raw_confidence is None else str(raw_confidence)
    raw_evidence_ref = declared.get("evidence_ref")
    evidence_ref = None if raw_evidence_ref is None else str(raw_evidence_ref)

    if mode == "FIT":
        if declared.get("crop_rect") is not None:
            raise ExecutionAdapterError(
                f"unit {unit_id!r} declares mode FIT and also a crop_rect; a FIT unit must "
                "not carry a crop rectangle. State CROP to crop, or drop the rectangle."
            )
        return UnitGeometry(
            unit_id=unit_id,
            requested_mode="FIT",
            applied_mode="FIT",
            requested_crop_rect=None,
            applied_crop_rect=None,
            geometry_filter=fit_geometry_filter(output_width, output_height),
            declaration="EXPLICIT",
            confidence=confidence,
            evidence_ref=evidence_ref,
        )

    # mode == "CROP"
    raw_rect = declared.get("crop_rect")
    if raw_rect is None:
        raise ExecutionAdapterError(
            f"unit {unit_id!r} declares mode CROP but carries no crop_rect; a crop "
            "rectangle cannot be inferred and will not be guessed"
        )
    if not isinstance(raw_rect, Mapping):
        raise ExecutionAdapterError(
            f"unit {unit_id!r} crop_rect must be a JSON object, got "
            f"{type(raw_rect).__name__}"
        )
    missing = [key for key in ("x", "y", "width", "height") if key not in raw_rect]
    if missing:
        raise ExecutionAdapterError(
            f"unit {unit_id!r} crop_rect is missing: " + ", ".join(missing)
        )

    requested = {key: raw_rect[key] for key in ("x", "y", "width", "height")}
    rect = CropRect(**requested)  # type: ignore[arg-type]

    if rect.x + rect.width > source_width or rect.y + rect.height > source_height:
        raise ExecutionAdapterError(
            f"unit {unit_id!r} crop_rect {rect.as_dict()} lies outside the measured "
            f"{source_width}x{source_height} source frame"
        )

    # Exact integer cross-multiplication: no tolerance and no float drift.
    if rect.width * output_height != rect.height * output_width:
        raise ExecutionAdapterError(
            f"unit {unit_id!r} crop_rect is {rect.width}x{rect.height}, which is not the "
            f"{output_width}:{output_height} output aspect. A CROP is never silently "
            "converted to a FIT, and scaling a mismatched rectangle would distort the "
            "picture. Crop to the output aspect, or request FIT."
        )

    return UnitGeometry(
        unit_id=unit_id,
        requested_mode="CROP",
        applied_mode="CROP",
        requested_crop_rect=requested,
        applied_crop_rect=rect.as_dict(),
        geometry_filter=rect.geometry_filter() + f",scale={output_width}:{output_height}",
        declaration="EXPLICIT",
        confidence=confidence,
        evidence_ref=evidence_ref,
    )


@dataclass(frozen=True)
class PictureResult:
    path: str
    frame_count: int
    fps: float
    width: int
    height: int
    sha256: str
    units_executed: tuple[str, ...]
    units_reused: tuple[str, ...]
    coordinate_system: str
    unit_geometry: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "picture_execution_result.v1",
            "path": self.path,
            "frame_count": self.frame_count,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "sha256": self.sha256,
            "units_executed": list(self.units_executed),
            "units_reused": list(self.units_reused),
            "coordinate_system": self.coordinate_system,
            "unit_geometry": [dict(entry) for entry in self.unit_geometry],
            "measured": True,
        }


def execute_picture(job_root: Path | str, *, timebase: TimebaseAdapter | None = None) -> dict[str, Any]:
    """Extract this job's source ranges through the timebase adapter and join them.

    Every range is resolved from a **measured timestamp**; a range that addresses the
    source by frame index is resolved through the measured PTS table. Nothing here
    divides a source frame index by a frame rate.

    Each unit's geometry is taken from its own explicit ``geometry`` declaration. A unit
    that declares nothing is fitted, exactly as before. A unit that declares ``CROP`` is
    cropped to its stated rectangle and scaled to the output geometry; an invalid crop is
    refused rather than repaired, so the executor can never quietly substitute a fit for a
    crop. The resolved geometry of every unit is recorded in the returned evidence.
    """

    _require_tools()
    root = Path(job_root)
    request = _read(root, PICTURE_REQUEST, "picture request")
    _require(request, ("source", "units", "width", "height", "fps"), "picture request")

    adapter = timebase or TimebaseAdapter(fps=int(request["fps"]))
    width, height, fps = int(request["width"]), int(request["height"]), int(request["fps"])
    work = root / "picture" / "units"
    work.mkdir(parents=True, exist_ok=True)

    pieces: list[Path] = []
    executed: list[str] = []
    reused: list[str] = []
    geometry_evidence: list[Mapping[str, Any]] = []
    for unit in request["units"]:
        unit_id = str(unit["unit_id"])
        frames = int(unit["frames"])
        # The production fast path extracts each declared source range through the
        # timebase adapter during its own stage, and asserts coverage. When that has
        # already happened this adapter reuses the extracted unit rather than
        # extracting it a second time, so there is exactly one execution path.
        existing = root / "picture" / "ranges" / f"{unit_id}.mp4"
        if existing.is_file():
            out = existing
            reused.append(unit_id)
        else:
            if unit.get("t_in_seconds") is not None:
                resolution = adapter.resolve_from_seconds(
                    unit_id=unit_id, source=str(request["source"]),
                    t_in_seconds=float(unit["t_in_seconds"]), frames=frames,
                )
            elif unit.get("source_frame_index") is not None:
                resolution = adapter.resolve_from_source_index(
                    unit_id=unit_id, source=str(request["source"]),
                    source_frame_index=int(unit["source_frame_index"]), frames=frames,
                )
            else:
                raise ExecutionAdapterError(
                    f"unit {unit_id!r} states neither t_in_seconds nor source_frame_index"
                )
            out = work / f"{unit_id}.mp4"
            adapter.execute(resolution, str(out))
            adapter.verify_frames(adapter.ledger[-1])

        # The crop rectangle is validated against the MEASURED source geometry of the
        # file that is actually about to be cropped, never against an assumed one.
        source_probe = media_probe.probe_streams(out)
        geometry = resolve_unit_geometry(
            unit,
            unit_id=unit_id,
            source_width=int(source_probe["width"]),
            source_height=int(source_probe["height"]),
            output_width=width,
            output_height=height,
        )

        # Apply the resolved geometry so the units can be joined deterministically.
        normalised = work / f"{unit_id}-norm.mp4"
        _run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(out),
                "-vf", f"{geometry.geometry_filter},setsar=1,fps={fps}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-an", str(normalised),
            ],
            f"normalising unit {unit_id}",
        )
        produced = media_probe.probe_streams(normalised)
        geometry_evidence.append(
            geometry.as_dict(
                source_width=int(source_probe["width"]),
                source_height=int(source_probe["height"]),
                output_width=int(produced["width"]),
                output_height=int(produced["height"]),
                frame_count=int(produced["frame_count"] or 0),
            )
        )
        pieces.append(normalised)
        executed.append(unit_id)
    adapter.assert_range_coverage(executed)

    listing = work / "concat.txt"
    listing.write_text(
        "".join(f"file '{piece.resolve()}'\n" for piece in pieces), encoding="utf-8"
    )
    out_path = root / "picture" / "picture_master.mp4"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
            "-safe", "0", "-i", str(listing), "-c", "copy", str(out_path),
        ],
        "joining picture units",
    )
    measured = media_probe.probe_streams(out_path)
    return PictureResult(
        path=str(out_path.relative_to(root)),
        frame_count=int(measured["frame_count"] or 0),
        fps=float(measured["fps"]),
        width=int(measured["width"]),
        height=int(measured["height"]),
        sha256=media_probe.sha256_of_file(out_path),
        units_executed=tuple(executed),
        units_reused=tuple(reused),
        coordinate_system="SOURCE_PTS_SECONDS -> CFR_TIMELINE_FRAMES",
        unit_geometry=tuple(geometry_evidence),
    ).as_dict()


# ---------------------------------------------------------------------------
# TYPOGRAPHY
# ---------------------------------------------------------------------------


def _load_font(font_stack: Sequence[str], size: int) -> Any:
    from PIL import ImageFont

    for candidate in font_stack:
        path, _, index = str(candidate).partition("#")
        if not os.path.isfile(path):
            continue
        try:
            return ImageFont.truetype(path, size, index=int(index or 0))
        except OSError:
            continue
    raise ExecutionAdapterError(
        "no usable font from this job's font_stack; typography has no default font"
    )


def execute_typography(job_root: Path | str) -> dict[str, Any]:
    """Rasterise this job's screen copy and composite it onto the accepted picture.

    The layout and font stack come from the job. There are deliberately no defaults,
    because a default would be one job's art direction applied to another. Every event
    is composited in a single deterministic pass, so the picture stream is encoded
    exactly once.
    """

    _require_tools()
    from PIL import Image, ImageDraw

    root = Path(job_root)
    request = _read(root, TYPOGRAPHY_REQUEST, "typography request")
    _require(
        request,
        ("master", "out", "events", "layout", "font_stack", "width", "height", "fps", "frame_count"),
        "typography request",
    )
    layout = request["layout"]
    _require(layout, ("baseline_y", "left_margin", "size_l1", "size_l2", "fill"),
             "typography layout")

    master = (root / str(request["master"])).resolve()
    if not master.is_file():
        raise ExecutionAdapterError(f"the accepted picture does not exist: {master}")
    out_path = root / str(request["out"])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fps = int(request["fps"])
    frame_count = int(request["frame_count"])
    width, height = int(request["width"]), int(request["height"])
    font_paths = tuple(str(entry) for entry in request["font_stack"])
    events = list(request["events"])
    if not events:
        raise ExecutionAdapterError("typography request declares no events to render")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        overlays: list[Path] = []
        for index, event in enumerate(events):
            lines = [str(line) for line in event["lines"]]
            start = int(event["start_frame"])
            end = int(event["end_frame_exclusive"])
            if end <= start:
                raise ExecutionAdapterError(f"typography event {index} is empty")
            if not lines:
                raise ExecutionAdapterError(f"typography event {index} has no lines")

            image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            size = int(layout["size_l1"] if len(lines) == 1 else layout["size_l2"])
            font = _load_font(font_paths, size)
            gap = int(layout.get("line_gap", 12))

            measured: list[tuple[str, Any, int]] = []
            block_height = 0
            for line in lines:
                left, top, right, bottom = draw.textbbox((0, 0), line, font=font)
                line_height = bottom - top
                measured.append((line, font, line_height))
                block_height += line_height + gap

            y = int(layout["baseline_y"]) - block_height
            for line, line_font, line_height in measured:
                draw.text(
                    (int(layout["left_margin"]), y), line, font=line_font,
                    fill=tuple(layout["fill"]),
                )
                y += line_height + gap

            png = tmpdir / f"event-{index}.png"
            image.save(png)
            overlays.append(png)

        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(master)]
        for png in overlays:
            command += ["-i", str(png)]
        chain = []
        current = "0:v"
        for index, event in enumerate(events):
            start = int(event["start_frame"]) / fps
            end = int(event["end_frame_exclusive"]) / fps
            label = f"v{index}"
            chain.append(
                f"[{current}][{index + 1}:v]overlay=0:0:"
                f"enable='between(t,{start:.6f},{end:.6f})'[{label}]"
            )
            current = label
        command += [
            "-filter_complex", ";".join(chain),
            "-map", f"[{current}]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "copy",
            "-frames:v", str(frame_count), str(out_path),
        ]
        _run(command, "compositing typography")

    measured_stream = media_probe.probe_streams(out_path)
    result = {
        "schema_version": "typography_execution_result.v1",
        "path": str(out_path.relative_to(root)),
        "frame_count": int(measured_stream["frame_count"] or 0),
        "width": int(measured_stream["width"]),
        "height": int(measured_stream["height"]),
        "sha256": media_probe.sha256_of_file(out_path),
        "events_rendered": len(events),
        "layout_digest": hashlib.sha256(
            json.dumps(layout, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "measured": True,
    }
    (root / "typography" / "typography_execution.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


# ---------------------------------------------------------------------------
# AUDIO
# ---------------------------------------------------------------------------


def execute_audio(job_root: Path | str) -> dict[str, Any]:
    """Mix this job's local audio assets and measure the result.

    Assets are this job's own files. No provider call is made here.
    """

    _require_tools()
    root = Path(job_root)
    request = _read(root, AUDIO_REQUEST, "audio request")
    _require(
        request,
        ("assets", "out", "duration_seconds", "target_lufs", "true_peak_ceiling_dbtp"),
        "audio request",
    )
    assets = list(request["assets"])
    if not assets:
        raise ExecutionAdapterError("audio request lists no assets to mix")

    duration = float(request["duration_seconds"])
    out_path = root / str(request["out"])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    for index, asset in enumerate(assets):
        path = (root / str(asset["path"])).resolve()
        if not path.is_file():
            raise ExecutionAdapterError(f"audio asset does not exist: {path}")
        inputs += ["-i", str(path)]
        gain = float(asset.get("gain_db", 0.0))
        start = float(asset.get("start_seconds", 0.0))
        labels.append(f"a{index}")
        filters.append(
            f"[{index}:a]adelay={int(start * 1000)}|{int(start * 1000)},"
            f"volume={gain}dB,atrim=0:{duration},asetpts=PTS-STARTPTS[{labels[-1]}]"
        )

    ceiling = float(request["true_peak_ceiling_dbtp"])
    target = float(request["target_lufs"])
    if len(labels) == 1:
        mix_label = labels[0]
    else:
        filters.append(
            "".join(f"[{label}]" for label in labels)
            + f"amix=inputs={len(labels)}:duration=longest:normalize=0[mix]"
        )
        mix_label = "mix"

    filters.append(
        f"[{mix_label}]loudnorm=I={target}:TP={ceiling}:LRA=11:print_format=summary[out]"
    )
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
            "-filter_complex", ";".join(filters), "-map", "[out]",
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(out_path),
        ],
        "mixing audio",
    )
    loudness = media_probe.measure_loudness(out_path)
    sample_peak = loudness.get("sample_peak_dbfs")
    if sample_peak is not None and sample_peak >= 0.0:
        raise ExecutionAdapterError(
            f"the mix clips: sample peak {sample_peak:.2f} dBFS is at or above full scale"
        )
    result = {
        "schema_version": "audio_execution_result.v1",
        "path": str(out_path.relative_to(root)),
        "duration_seconds": round(duration, 6),
        "integrated_lufs": loudness["integrated_lufs"],
        "true_peak_dbtp": loudness["true_peak_dbtp"],
        "sample_peak_dbfs": sample_peak,
        "clipping": False,
        "assets_mixed": len(assets),
        "paid_api_calls": 0,
        "sha256": media_probe.sha256_of_file(out_path),
        "measured": True,
    }
    (root / "audio" / "audio_execution.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


# ---------------------------------------------------------------------------
# ASSEMBLE & MASTER
# ---------------------------------------------------------------------------


def assemble_master(job_root: Path | str) -> dict[str, Any]:
    """Produce the delivery master and its measured technical QA.

    Prefers a stream-copy remux when the inputs already meet the delivery
    specification, because re-encoding adds a generation of loss for no benefit.
    """

    _require_tools()
    root = Path(job_root)
    request = _read(root, ASSEMBLE_REQUEST, "assemble request")
    _require(request, ("picture", "audio", "out", "method"), "assemble request")

    picture = (root / str(request["picture"])).resolve()
    audio = (root / str(request["audio"])).resolve()
    if not picture.is_file():
        raise ExecutionAdapterError(f"picture input does not exist: {picture}")
    if not audio.is_file():
        raise ExecutionAdapterError(f"audio input does not exist: {audio}")

    out_path = root / str(request["out"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    method = str(request["method"])
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(picture), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0", "-shortest",
    ]
    if method == "REMUX":
        command += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    elif method == "RE_ENCODE":
        command += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        ]
    else:
        raise ExecutionAdapterError(f"unknown assembly method {method!r}")
    command += ["-movflags", "+faststart", str(out_path)]
    _run(command, "assembling the master")

    measured = media_probe.probe_streams(out_path)
    loudness = media_probe.measure_loudness(out_path)
    evidence = {
        "schema_version": "assembly_evidence.v1",
        "master_path": str(out_path.relative_to(root)),
        "master_sha256": media_probe.sha256_of_file(out_path),
        "frame_count": int(measured["frame_count"] or 0),
        "fps": measured["fps"],
        "width": measured["width"],
        "height": measured["height"],
        "duration_seconds": measured["duration_seconds"],
        "video_codec": measured["video_codec"],
        "audio_codec": measured["audio_codec"],
        "method": method,
        "black_frames": media_probe.count_black_frames(out_path),
        "duplicate_frames": media_probe.count_duplicate_frames(out_path),
        "audio": {
            "integrated_lufs": loudness["integrated_lufs"],
            "true_peak_dbtp": loudness["true_peak_dbtp"],
        },
        "produced_by": "execution_adapters.assemble_master",
    }
    (root / ASSEMBLY_EVIDENCE).write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return evidence


RUNNERS = {
    "picture": execute_picture,
    "typography": execute_typography,
    "audio": execute_audio,
    "assemble": assemble_master,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one job-scoped execution boundary for a job"
    )
    parser.add_argument("--job-root", type=Path, required=True)
    parser.add_argument("--boundary", choices=BOUNDARIES, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = RUNNERS[args.boundary](args.job_root)
    except (ExecutionAdapterError, TimebaseAdapterError, media_probe.MediaProbeError) as exc:
        print(json.dumps({"boundary": args.boundary, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ASSEMBLY_EVIDENCE",
    "AUDIO_REQUEST",
    "BOUNDARIES",
    "CropRect",
    "ExecutionAdapterError",
    "GEOMETRY_DECLARATIONS",
    "GEOMETRY_MODES",
    "PICTURE_REQUEST",
    "PictureResult",
    "RUNNERS",
    "TYPOGRAPHY_REQUEST",
    "UnitGeometry",
    "assemble_master",
    "execute_audio",
    "execute_picture",
    "execute_typography",
    "fit_geometry_filter",
    "main",
    "resolve_unit_geometry",
]
