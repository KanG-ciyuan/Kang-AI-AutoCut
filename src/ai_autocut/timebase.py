"""Source time and timeline time are different coordinate systems.

Post-blind learning, Second SKU (cushion-puff-second-sku-v1).

The failure this prevents
------------------------
A source file's decoded-frame index is **not** 30 x its time when the file is variable frame rate.
Treating ``frame_index / fps`` as a source time produced a repair that built **502 frames instead of
487** and, on a re-run, **66 frames where 67 was expected for the same range** — because the requested
interval sat exactly on a CFR boundary and the encoder rounded either way.

The rule:

    SOURCE coordinate    = PTS timestamp in seconds
    TIMELINE coordinate  = CFR frame index; frame N occupies [N/fps, (N+1)/fps)

A frame index may still be recorded as human evidence. It must **not** be the authoritative execution
coordinate for a source that may be variable frame rate.

Nothing here is product-specific.
"""

from __future__ import annotations

import hashlib
import os
import subprocess

DEFAULT_FPS = 30


class TimebaseError(ValueError):
    """Raised when a source cannot be mapped or extracted deterministically."""


class SourceTiming:
    """What a source's timing actually is, measured rather than assumed."""

    def __init__(self, path: str, fps: int = DEFAULT_FPS) -> None:
        self.path = path
        self.fps = fps
        self.timestamps = frame_table(path)
        deltas: dict[float, int] = {}
        for i in range(len(self.timestamps) - 1):
            d = round(self.timestamps[i + 1] - self.timestamps[i], 5)
            deltas[d] = deltas.get(d, 0) + 1
        self.deltas = deltas

    @property
    def frame_count(self) -> int:
        return len(self.timestamps)

    @property
    def span_seconds(self) -> float:
        return round(self.timestamps[-1] - self.timestamps[0], 4)

    @property
    def nominal(self) -> int:
        """How many frames this span would hold on the timeline grid."""

        return int(round(self.span_seconds * self.fps))

    @property
    def is_variable_frame_rate(self) -> bool:
        expected = 1.0 / self.fps
        return any(abs(d - expected) > 1e-4 for d in self.deltas)

    def timestamp_of(self, index: int) -> float:
        if index < 0 or index >= len(self.timestamps):
            raise TimebaseError(
                f"frame {index} is outside {os.path.basename(self.path)} "
                f"({len(self.timestamps)} frames)")
        return self.timestamps[index]

    def timeline_index(self, timestamp: float) -> int:
        """The timeline frame that a source timestamp lands on."""

        return int(round(timestamp * self.fps))

    def describe(self) -> dict:
        return {"frames": self.frame_count, "span_seconds": self.span_seconds,
                "nominal_frames_at_fps": self.nominal, "fps": self.fps,
                "variable_frame_rate": self.is_variable_frame_rate,
                "dominant_deltas": {str(k): v for k, v in
                                    sorted(self.deltas.items(), key=lambda x: -x[1])[:4]}}


#: Frame timestamp fields to ask FFprobe for, in preference order.
#:
#: ``pts_time`` is asked for first, because the source coordinate is the presentation
#: timestamp and nothing here may substitute a different clock. FFmpeg 4.4.x answers that
#: field with an empty value for *every* frame instead of failing, which used to make this
#: module raise on media that is perfectly readable. ``best_effort_timestamp_time`` is the
#: same measured presentation timestamp - it falls back to a reconstructed value only when
#: a stream states no PTS at all - and it was measured value-for-value identical to
#: ``pts_time`` on FFmpeg 4.4.2, 5.1.2, 6.1.2 and 9.0.1 for both CFR and genuinely
#: variable-frame-rate sources. It is consulted only when the primary field reads nothing,
#: so a modern FFprobe still executes the exact command it always did.
FRAME_TIME_FIELDS = ("pts_time", "best_effort_timestamp_time")


def _probe_frame_times(path: str, field: str) -> list[float]:
    """One FFprobe pass over every frame, reading a single timestamp field."""

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", f"frame={field}", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout
    values: list[float] = []
    for line in out.splitlines():
        token = line.strip().rstrip(",")
        if not token:
            continue
        try:
            values.append(float(token))
        except ValueError:
            pass
    return values


def frame_table(path: str) -> list[float]:
    """Every frame's PTS in seconds. The authoritative source coordinate.

    Frame order and cadence come from the media, never from ``frame_index / fps``. The
    fallback field changes which *name* is asked for, never which clock is read: measured
    presentation timestamps stay authoritative, and variable-frame-rate cadence is
    preserved because the per-frame values are the source's own.
    """

    for field in FRAME_TIME_FIELDS:
        values = _probe_frame_times(path, field)
        if values:
            return values
    raise TimebaseError(f"no frame timestamps readable from {path}")


def extract_timeline_frames(source: str, *, t_in: float, frames: int, out_path: str,
                            fps: int = DEFAULT_FPS, crf: int = 16,
                            preset: str = "medium") -> dict:
    """Produce **exactly** ``frames`` CFR frames starting at source timestamp ``t_in``.

    The ``-frames:v`` cap is the guarantee. It is what makes the output frame count independent of
    the source's timing, which is precisely what a frame-index range failed to do.
    """

    if frames <= 0:
        raise TimebaseError("frames must be positive")
    if t_in < 0:
        raise TimebaseError("t_in cannot be negative")
    duration = frames / fps
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{t_in:.6f}", "-t", f"{duration:.6f}", "-i", source,
         "-vf", f"setpts=PTS-STARTPTS,fps={fps}", "-frames:v", str(frames), "-an",
         "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", out_path],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise TimebaseError(result.stderr[-400:])
    produced = count_frames(out_path)
    if produced != frames:
        raise TimebaseError(
            f"requested {frames} frames but produced {produced} - extraction is not deterministic")
    return {"frames": produced, "duration": round(duration, 6), "path": out_path}


def count_frames(path: str) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=nb_frames", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip()
    return int(out) if out.isdigit() else -1


def decoded_frame_hash(path: str, width: int = 64, height: int = 114) -> str:
    """Hash of the decoded pixels.

    Container metadata can differ between two identical encodes, so byte equality is not the right
    reproducibility test. The decoded frames are.
    """

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={width}:{height}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True).stdout
    return hashlib.sha256(raw).hexdigest()


def assert_reproducible(source: str, *, t_in: float, frames: int, runs: int = 3,
                        fps: int = DEFAULT_FPS) -> dict:
    """Extract the same request several times and prove the result is stable.

    Run this before letting a source range near a locked timeline. A repair that cannot be
    reproduced cannot be trusted to change a locked cut.
    """

    if runs < 2:
        raise TimebaseError("reproducibility needs at least two runs")
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        results = []
        for i in range(runs):
            path = os.path.join(tmp, f"run{i}.mp4")
            extract_timeline_frames(source, t_in=t_in, frames=frames, out_path=path, fps=fps)
            results.append({"frames": count_frames(path),
                            "decoded_hash": decoded_frame_hash(path)})
        counts = {r["frames"] for r in results}
        hashes = {r["decoded_hash"] for r in results}
        return {"runs": runs, "requested_frames": frames,
                "frame_counts": [r["frames"] for r in results],
                "frame_count_stable": len(counts) == 1,
                "decoded_frames_identical": len(hashes) == 1,
                "reproducible": len(counts) == 1 and len(hashes) == 1 and results[0]["frames"] == frames}
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
