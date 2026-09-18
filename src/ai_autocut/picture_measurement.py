"""B3-A — read-only picture measurement.

This module measures. It does not correct, propose, or decide, and it never writes to a
source file: every FFmpeg invocation here reads media and discards its output with ``-f
null``.

The law it is built around:

    Statistical Difference != Visual Defect

There is no perfect global target, so nothing here compares a shot to an ideal. Measurements
are always **relative**: a shot against the shot it is adjacent to, weighted by how
continuous the viewer experiences that pair to be.

Numbers in the output are real measurements only. Nothing is scored, ranked or rated.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import subprocess
import tempfile
from typing import Mapping, Sequence

#: How continuous the viewer experiences a pair of shots. Categorical, never numeric.
SAME_SEMANTIC_UNIT = "SAME_SEMANTIC_UNIT"
SAME_SCENE = "SAME_SCENE"
SAME_PRODUCT = "SAME_PRODUCT"
UNRELATED = "UNRELATED"
RELATIONSHIP_TIERS = (SAME_SEMANTIC_UNIT, SAME_SCENE, SAME_PRODUCT, UNRELATED)

#: How much a difference in a pair is worth reporting. Named levels, not coefficients.
SENSITIVITY_BY_TIER = {
    SAME_SEMANTIC_UNIT: "HIGH",
    SAME_SCENE: "HIGH",
    SAME_PRODUCT: "MEDIUM",
    UNRELATED: "LOW",
}

CONFIDENCES = ("LOW", "MEDIUM", "HIGH")

#: The dimensions measured. Each has a consumer in the decision or protection stage.
DIMENSIONS = ("luminance", "cast", "saturation", "contrast", "sharpness")

#: Reporting levels per sensitivity tier, in the units each metric is measured in.
#:
#: These say "worth looking at", never "correct this". A difference above the level is a
#: candidate for a decision, and most candidates are expected to end as KEEP.
REPORTING_LEVEL = {
    "HIGH": {"luminance": 6.0, "cast": 4.0, "saturation": 6.0, "contrast": 14.0,
             "sharpness": 1.5},
    "MEDIUM": {"luminance": 10.0, "cast": 7.0, "saturation": 10.0, "contrast": 22.0,
               "sharpness": 2.5},
    "LOW": {"luminance": 16.0, "cast": 11.0, "saturation": 16.0, "contrast": 34.0,
            "sharpness": 4.0},
}

#: Edge-detection raster. Fixed so that edge energy is comparable between shots.
_EDGE_WIDTH = 320


class PictureMeasurementError(ValueError):
    """Raised when a picture measurement cannot be taken safely."""


def _ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise PictureMeasurementError("ffmpeg is required for picture measurement")
    return found


@dataclass(frozen=True)
class ProductRegion:
    """A rectangle of interest, normalised to the frame.

    Supplied by the caller or derived from existing evidence. This module never invents one.
    """

    x: float
    y: float
    width: float
    height: float
    source: str = "unspecified"

    def __post_init__(self) -> None:
        for label, value in (("x", self.x), ("y", self.y),
                             ("width", self.width), ("height", self.height)):
            if not 0.0 <= value <= 1.0:
                raise PictureMeasurementError(f"region {label} must be within 0..1")
        if self.width <= 0 or self.height <= 0:
            raise PictureMeasurementError("a product region must have a positive area")
        if self.x + self.width > 1.0 + 1e-9 or self.y + self.height > 1.0 + 1e-9:
            raise PictureMeasurementError("a product region must lie inside the frame")

    def as_crop_filter(self, width: int, height: int) -> str:
        """An FFmpeg crop expression, snapped to even pixels."""

        w = max(2, int(round(self.width * width)) // 2 * 2)
        h = max(2, int(round(self.height * height)) // 2 * 2)
        x = max(0, min(int(round(self.x * width)), width - w))
        y = max(0, min(int(round(self.y * height)), height - h))
        return f"crop={w}:{h}:{x}:{y}"


@dataclass(frozen=True)
class ShotMeasurement:
    """What one shot measures. Every value is a real reading."""

    shot_id: str
    start_seconds: float
    duration_seconds: float
    luminance: float
    cast_u: float
    cast_v: float
    saturation: float
    contrast: float
    sharpness: float
    product_region: ProductRegion | None
    product_luminance: float | None
    product_saturation: float | None
    product_contrast: float | None
    confidence: str

    @property
    def cast(self) -> float:
        """Distance from neutral in the chroma plane. 128,128 is neutral."""

        return round(((self.cast_u - 128.0) ** 2 + (self.cast_v - 128.0) ** 2) ** 0.5, 4)

    @property
    def has_product_region(self) -> bool:
        return self.product_region is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "shot_id": self.shot_id,
            "start_seconds": self.start_seconds,
            "duration_seconds": self.duration_seconds,
            "luminance": self.luminance,
            "cast": self.cast,
            "saturation": self.saturation,
            "contrast": self.contrast,
            "sharpness": self.sharpness,
            "product_region": (None if self.product_region is None
                               else {"x": self.product_region.x, "y": self.product_region.y,
                                     "width": self.product_region.width,
                                     "height": self.product_region.height,
                                     "source": self.product_region.source}),
            "product_luminance": self.product_luminance,
            "product_saturation": self.product_saturation,
            "product_contrast": self.product_contrast,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class PairComparison:
    """One shot measured relative to the shot before it."""

    previous_shot_id: str
    shot_id: str
    tier: str
    sensitivity: str
    deltas: Mapping[str, float]
    above_reporting_level: tuple[str, ...]
    largest: str | None

    @property
    def is_reported(self) -> bool:
        return bool(self.above_reporting_level)

    def as_dict(self) -> dict[str, object]:
        return {
            "previous_shot_id": self.previous_shot_id,
            "shot_id": self.shot_id,
            "tier": self.tier,
            "sensitivity": self.sensitivity,
            "deltas": dict(self.deltas),
            "above_reporting_level": list(self.above_reporting_level),
            "largest": self.largest,
        }


@dataclass(frozen=True)
class PictureMeasurement:
    """The measurement artifact. Read-only stage output."""

    shots: tuple[ShotMeasurement, ...]
    pairs: tuple[PairComparison, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "picture_measurement.v1",
            "shots": [s.as_dict() for s in self.shots],
            "pairs": [p.as_dict() for p in self.pairs],
        }


# ------------------------------------------------------------------ measurement


def _signalstats(path: str, *, start: float, duration: float, extra: str = "",
                 width: int | None = None) -> dict[str, float]:
    """Read signal statistics for one window. Output is discarded, never written."""

    if duration <= 0:
        raise PictureMeasurementError("a measured window must have a positive duration")
    chain = []
    if width is not None:
        chain.append(f"scale={width}:-2")
    if extra:
        chain.append(extra)
    chain.append("signalstats")
    chain.append("metadata=print:file=-")
    command = [
        _ffmpeg(), "-hide_banner", "-nostats",
        "-ss", f"{start:.6f}", "-t", f"{duration:.6f}", "-i", path,
        "-vf", ",".join(chain), "-f", "null", "-",
    ]
    process = subprocess.run(command, capture_output=True, text=True)
    values: dict[str, float] = {}
    for line in process.stdout.splitlines():
        if "=" not in line or "signalstats" not in line:
            continue
        key, _, raw = line.partition("=")
        name = key.rsplit(".", 1)[-1]
        try:
            values[name] = float(raw)
        except ValueError:
            continue
    if not values:
        raise PictureMeasurementError(
            f"no signal statistics for {os.path.basename(path)} at {start:.3f}s"
        )
    return values


def _probe_dimensions(path: str) -> tuple[int, int]:
    process = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
        capture_output=True, text=True, check=True,
    )
    raw = process.stdout.strip().splitlines()[0]
    width, _, height = raw.partition("x")
    return int(width), int(height)


def _confidence_for(duration: float, has_region: bool | None) -> str:
    """Short windows give unstable readings; a missing product region lowers trust."""

    if duration < 0.4:
        base = "LOW"
    elif duration < 1.0:
        base = "MEDIUM"
    else:
        base = "HIGH"
    if has_region is False and base == "HIGH":
        return "MEDIUM"
    if has_region is False and base == "MEDIUM":
        return "LOW"
    return base


def measure_shot(
    path: str,
    *,
    shot_id: str,
    start_seconds: float,
    duration_seconds: float,
    product_region: ProductRegion | None = None,
) -> ShotMeasurement:
    """Measure one shot. Read-only: no file is created or modified."""

    if not os.path.isfile(path):
        raise PictureMeasurementError(f"no such media file: {path}")
    if not shot_id:
        raise PictureMeasurementError("a measured shot needs an id")

    overall = _signalstats(path, start=start_seconds, duration=duration_seconds)
    edge = _signalstats(path, start=start_seconds, duration=duration_seconds,
                        extra="edgedetect=low=0.05:high=0.15", width=_EDGE_WIDTH)

    luminance = round(overall.get("YAVG", 0.0), 4)
    contrast = round(overall.get("YMAX", 0.0) - overall.get("YMIN", 0.0), 4)
    saturation = round(overall.get("SATAVG", 0.0), 4)
    sharpness = round(edge.get("YAVG", 0.0), 4)

    product_luminance: float | None = None
    product_saturation: float | None = None
    product_contrast: float | None = None
    if product_region is not None:
        width, height = _probe_dimensions(path)
        region = _signalstats(path, start=start_seconds, duration=duration_seconds,
                              extra=product_region.as_crop_filter(width, height))
        product_luminance = round(region.get("YAVG", 0.0), 4)
        product_saturation = round(region.get("SATAVG", 0.0), 4)
        product_contrast = round(region.get("YMAX", 0.0) - region.get("YMIN", 0.0), 4)

    return ShotMeasurement(
        shot_id=shot_id,
        start_seconds=round(start_seconds, 4),
        duration_seconds=round(duration_seconds, 4),
        luminance=luminance,
        cast_u=round(overall.get("UAVG", 128.0), 4),
        cast_v=round(overall.get("VAVG", 128.0), 4),
        saturation=saturation,
        contrast=contrast,
        sharpness=sharpness,
        product_region=product_region,
        product_luminance=product_luminance,
        product_saturation=product_saturation,
        product_contrast=product_contrast,
        confidence=_confidence_for(duration_seconds, None if product_region is None else True),
    )


# ------------------------------------------------------------------ relationship


def tier_for(
    *,
    same_semantic_unit: bool = False,
    same_scene: bool = False,
    same_product: bool = False,
) -> str:
    """Derive the pair relationship from metadata that already exists.

    No graph is built. A pair either shares a semantic unit, a scene or a product, or it is
    unrelated, and that is read off the timeline and Batch 1's semantic groups.
    """

    if same_semantic_unit:
        return SAME_SEMANTIC_UNIT
    if same_scene:
        return SAME_SCENE
    if same_product:
        return SAME_PRODUCT
    return UNRELATED


def sensitivity_for(tier: str) -> str:
    if tier not in RELATIONSHIP_TIERS:
        raise PictureMeasurementError(
            f"tier must be one of: {', '.join(RELATIONSHIP_TIERS)}"
        )
    return SENSITIVITY_BY_TIER[tier]


def compare_shots(previous: ShotMeasurement, current: ShotMeasurement,
                  *, tier: str) -> PairComparison:
    """Measure one shot against the shot before it. Relative, never against an ideal."""

    sensitivity = sensitivity_for(tier)
    deltas = {
        "luminance": round(current.luminance - previous.luminance, 4),
        "cast": round(current.cast - previous.cast, 4),
        "saturation": round(current.saturation - previous.saturation, 4),
        "contrast": round(current.contrast - previous.contrast, 4),
        "sharpness": round(current.sharpness - previous.sharpness, 4),
    }
    levels = REPORTING_LEVEL[sensitivity]
    above = tuple(
        name for name in DIMENSIONS if abs(deltas[name]) >= levels[name]
    )
    largest = None
    if deltas:
        largest = max(DIMENSIONS, key=lambda name: abs(deltas[name]) / levels[name])
    return PairComparison(
        previous_shot_id=previous.shot_id,
        shot_id=current.shot_id,
        tier=tier,
        sensitivity=sensitivity,
        deltas=deltas,
        above_reporting_level=above,
        largest=largest,
    )


@dataclass(frozen=True)
class ShotWindow:
    """One shot to measure: where it is and how it relates to the shot before it."""

    shot_id: str
    path: str
    start_seconds: float
    duration_seconds: float
    product_region: ProductRegion | None = None
    same_semantic_unit: bool = False
    same_scene: bool = False
    same_product: bool = False


def measure_sequence(windows: Sequence[ShotWindow]) -> PictureMeasurement:
    """Measure a whole sequence and compare each shot with the one before it."""

    if not windows:
        raise PictureMeasurementError("a sequence needs at least one shot")
    shots: list[ShotMeasurement] = []
    pairs: list[PairComparison] = []
    for index, window in enumerate(windows):
        measured = measure_shot(
            window.path, shot_id=window.shot_id,
            start_seconds=window.start_seconds,
            duration_seconds=window.duration_seconds,
            product_region=window.product_region,
        )
        shots.append(measured)
        if index == 0:
            continue
        tier = tier_for(same_semantic_unit=window.same_semantic_unit,
                        same_scene=window.same_scene,
                        same_product=window.same_product)
        pairs.append(compare_shots(shots[index - 1], measured, tier=tier))
    return PictureMeasurement(shots=tuple(shots), pairs=tuple(pairs))
