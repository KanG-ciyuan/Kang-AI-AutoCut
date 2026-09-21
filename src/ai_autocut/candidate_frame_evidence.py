"""Frame evidence: which exact frames an analysis is based on, and whether it holds up.

The problem this closes
-----------------------
A multimodal analyzer cannot be trusted to invent source coordinates. "The model
said frames 120-160" is not evidence that anything happened at frames 120-160, and
a DIRECT claim whose provenance nobody can check is exactly the failure Candidate
Evidence exists to prevent.

So the pipeline does the coordinate work and the analyzer does the seeing:

1. **Sample.** For each Candidate, the pipeline decodes the Candidate's own window
   and writes a small set of frames as images, each labelled with its exact decoded
   source frame index and that frame's measured presentation timestamp. The
   analyzer is handed images whose frame numbers are established facts, not
   guesses. Nothing here uses ``select=`` on a raw source: the window is decoded
   and the frames are sliced out by decoded index, which is legitimate for
   *analysis* while remaining forbidden as a *timing* coordinate.
2. **Manifest.** Every image is recorded with its frame index, timestamp, size, and
   SHA-256, so what the analyzer was shown is auditable afterwards.
3. **Audit.** After the answer comes back, every DIRECT claim is checked against
   the real media: the cited frames must exist, lie inside the Candidate, have
   actually been shown to the analyzer, and — where the claim is measurable — the
   cited frames must really show the change the claim describes. That last check is
   supplied by the run as an explicit, reviewable expectation, never inferred from
   the model's own words.

This module performs no semantic analysis. It establishes coordinates, and it
checks claims against pixels.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from pathlib import Path
import subprocess
from typing import Mapping, Sequence

import numpy as np

from .candidate_evidence import CandidateEvidence, ClaimSupport
from .candidate_evidence_v2 import CandidateEvidenceV2
from .candidate_extraction import CandidateExtraction, SOURCE_COORDINATE_SYSTEM


FRAME_EVIDENCE_SCHEMA_VERSION = "candidate_frame_evidence.v1"
FRAME_AUDIT_SCHEMA_VERSION = "candidate_frame_audit.v1"

#: How many frames of one Candidate are shown to the analyzer by default.
DEFAULT_SAMPLE_COUNT = 8
MAX_SAMPLE_COUNT = 32

#: Images are downscaled to this width at most, preserving aspect and parity.
DEFAULT_IMAGE_MAX_WIDTH = 512

#: The sampling rule, named so a reader knows the frames were not chosen by taste.
SAMPLE_STRATEGY = "EVEN_INCLUSIVE_ENDPOINTS"

#: Frame images live under this directory inside the job root.
FRAME_DIRECTORY = "analysis/frames"

#: Where the manifest is written inside the job root.
FRAME_EVIDENCE_ARTIFACT = "analysis/candidate_frame_evidence.json"

#: Contact sheets put every sampled frame of one Candidate into one image, in
#: ascending frame order, so an analyzer can read a whole Candidate at once. The
#: manifest records the tile order, so the sheet is auditable rather than merely
#: convenient.
CONTACT_SHEET_TILE_GAP = 4
CONTACT_SHEET_MAX_COLUMNS = 4
CONTACT_SHEET_BORDER = 2

_LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)


class FrameEvidenceError(ValueError):
    """Raised when frames cannot be sampled, written, or audited."""


class FrameCheckKind(str, Enum):
    """The measurable checks an audit can run. Small on purpose.

    Each kind answers exactly one question, and says which one:

    ``MEAN_LUMINANCE_CHANGE``
        Two **named frames in temporal order**. ``before_frame`` comes first on the
        timeline, so ``INCREASE`` and ``DECREASE`` are directional claims about time:
        the region was darker earlier and lighter later, or the reverse.
    ``ROI_LUMINANCE_SPAN``
        A sweep of the whole cited window. It reports the largest and smallest mean
        the region reaches, which is a **magnitude**: it says the region changes by
        at least ``min_delta`` somewhere in the window, and it says nothing about
        which way time ran. A span check therefore refuses ``INCREASE`` and
        ``DECREASE`` outright, because a magnitude cannot prove a direction.

    The distinction exists because a sweep that reported ``max - min`` was once
    allowed to answer a directional question: a clip that got steadily *darker*
    passed a declared ``INCREASE``. Magnitude and direction are separate claims, so
    they are separate checks.
    """

    MEAN_LUMINANCE_CHANGE = "MEAN_LUMINANCE_CHANGE"
    ROI_LUMINANCE_SPAN = "ROI_LUMINANCE_SPAN"


class ChangeDirection(str, Enum):
    """What a check expects to happen, read according to the check kind.

    For ``MEAN_LUMINANCE_CHANGE`` the direction is temporal: ``INCREASE`` means the
    later frame is brighter than the earlier one. For ``ROI_LUMINANCE_SPAN`` only
    ``ANY`` and ``STABLE`` are meaningful, because a sweep has no temporal order to
    report.
    """

    #: Later is brighter (directional) / the region spans at least min_delta (magnitude).
    INCREASE = "INCREASE"
    #: Later is darker (directional).
    DECREASE = "DECREASE"
    #: The region moves by at least ``min_delta`` in either direction (magnitude),
    #: or differs by at least ``min_delta`` between the two named frames.
    ANY = "ANY"
    #: The region must NOT move by more than ``min_delta``. This is how a run declares
    #: "nothing happens here" as a testable expectation - the check that a beauty bank
    #: claiming a state change would have to survive.
    STABLE = "STABLE"


#: Expectations that assert a direction in time. Only a check with named frames in
#: temporal order may carry one.
DIRECTIONAL_EXPECTATIONS = frozenset(
    {ChangeDirection.INCREASE, ChangeDirection.DECREASE}
)

#: Expectations a magnitude-only sweep may carry.
MAGNITUDE_EXPECTATIONS = frozenset({ChangeDirection.ANY, ChangeDirection.STABLE})


class AuditVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


class CheckStatus(str, Enum):
    """The verdict of the declared checks, and nothing wider than that.

    This is a different question from contract validity, and the two are separate
    axes on purpose. ``validate_candidate_evidence`` answers "is this document
    well formed, are the facts permitted, are the coordinates real?" A document can
    pass all of that and still assert something the footage does not show - Phase
    2.5 proved it with a beauty shot claiming a state change. That case is:

        CONTRACT_VALID = YES   while   DECLARED_CHECK_STATUS = CHECKS_FAILED

    **What a pass means, exactly.** ``CHECKS_PASSED`` means every `DIRECT` assertion
    is covered by a declared check that measured *its own pixel predicate* on the
    cited frames and was satisfied. It does not mean the commercial assertion is
    true, the frame semantics are correct, or the ROI was chosen fairly: a
    hand-picked region and threshold can encode the expected answer. A check result
    is evidence about a statistic, not a proof of meaning.

    An assertion nobody measured is ``NOT_VERIFIED`` rather than quietly assumed
    true.
    """

    #: Every DIRECT assertion is covered by a declared check that passed its own predicate.
    CHECKS_PASSED = "CHECKS_PASSED"
    #: Integrity, bounds, cited-frame, or a declared check failed.
    CHECKS_FAILED = "CHECKS_FAILED"
    #: Nothing failed, and at least one DIRECT assertion has no declared check.
    NOT_VERIFIED = "NOT_VERIFIED"


#: What a check result does and does not establish. Stated once, quoted in reports.
CHECK_SCOPE = (
    "declared checks measure named pixel predicates on cited frames; a pass is not "
    "proof of commercial or semantic truth"
)


def sample_frame_indices(
    start_frame: int, end_frame_exclusive: int, count: int = DEFAULT_SAMPLE_COUNT
) -> tuple[int, ...]:
    """Evenly spaced decoded frame indices, always including both endpoints.

    Deterministic: the same window and count always yield the same frames, so a
    replay shows the analyzer exactly what the first run showed it.
    """

    for label, value in (
        ("start_frame", start_frame),
        ("end_frame_exclusive", end_frame_exclusive),
        ("count", count),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise FrameEvidenceError(f"{label} must be an integer")
    if end_frame_exclusive <= start_frame:
        raise FrameEvidenceError("a Candidate window must be non-empty")
    if count < 2:
        raise FrameEvidenceError("a sample needs at least two frames")
    if count > MAX_SAMPLE_COUNT:
        raise FrameEvidenceError(
            f"a sample may not exceed {MAX_SAMPLE_COUNT} frames per Candidate"
        )
    length = end_frame_exclusive - start_frame
    if length <= count:
        return tuple(range(start_frame, end_frame_exclusive))
    indices = {
        start_frame + round(index * (length - 1) / (count - 1)) for index in range(count)
    }
    return tuple(sorted(indices))


def decode_window_frames(
    source: str,
    start_frame: int,
    end_frame_exclusive: int,
    *,
    width: int | None = None,
    height: int | None = None,
    scale_to_width: int | None = None,
) -> tuple[np.ndarray, int, int]:
    """Decode ``[start, end)`` of a real source and return ``(frames, w, h)``.

    Frames are decoded in order, so index ``i`` of the returned array is decoded
    source frame ``start_frame + i``. The same ``rawvideo`` pattern the rest of
    this repository uses for analysis is reused here; no frame-index *filter* is
    applied to a raw source.
    """

    if end_frame_exclusive <= start_frame:
        raise FrameEvidenceError("a window must be non-empty")
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", source,
        ],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0 or "x" not in probe.stdout:
        raise FrameEvidenceError("the source geometry could not be probed")
    raw = probe.stdout.strip().splitlines()[0].split("x")
    native_width, native_height = int(raw[0]), int(raw[1])

    target_width, target_height = native_width, native_height
    if scale_to_width is not None and scale_to_width < native_width:
        target_width = scale_to_width + (scale_to_width % 2)
        target_height = max(2, round(native_height * target_width / native_width))
        target_height -= target_height % 2
    if width is not None and height is not None:
        target_width, target_height = width, height

    filters = []
    if (target_width, target_height) != (native_width, native_height):
        filters.append(f"scale={target_width}:{target_height}")
    # -ss/-frames:v address the window by decoded position; the timestamps are the
    # source's own because nothing here re-times the stream.
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", source,
        *(["-vf", ",".join(filters)] if filters else []),
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_bytes = target_width * target_height * 3
    wanted = end_frame_exclusive - start_frame
    collected: list[np.ndarray] = []
    try:
        for index in range(end_frame_exclusive):
            raw_frame = process.stdout.read(frame_bytes)
            if len(raw_frame) < frame_bytes:
                break
            if index >= start_frame:
                collected.append(
                    np.frombuffer(raw_frame, dtype=np.uint8).reshape(
                        target_height, target_width, 3
                    )
                )
    finally:
        process.stdout.close()
        process.stderr.close()
        process.wait()
    if len(collected) < wanted:
        raise FrameEvidenceError(
            f"the source holds fewer frames than the window [{start_frame}, "
            f"{end_frame_exclusive}) asks for"
        )
    return np.stack(collected), target_width, target_height


def _write_png(image: np.ndarray, path: Path) -> None:
    height, width = image.shape[0], image.shape[1]
    path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}", "-i", "-",
            "-frames:v", "1", str(path),
        ],
        input=image.tobytes(),
        capture_output=True,
    )
    if result.returncode != 0 or not path.is_file():
        raise FrameEvidenceError("a sampled frame could not be written")


@dataclass(frozen=True)
class SampledFrame:
    """One image, bound to the exact source frame it came from."""

    source_frame: int
    t_seconds: float
    image_relpath: str
    sha256: str
    width: int
    height: int

    def __post_init__(self) -> None:
        if isinstance(self.source_frame, bool) or not isinstance(self.source_frame, int):
            raise FrameEvidenceError("source_frame must be an integer")
        if self.source_frame < 0:
            raise FrameEvidenceError("source_frame must not be negative")
        if not isinstance(self.t_seconds, (int, float)):
            raise FrameEvidenceError("t_seconds must be a measured timestamp")
        if len(self.sha256) != 64:
            raise FrameEvidenceError("a sampled frame records its SHA-256")

    def as_dict(self) -> dict[str, object]:
        return {
            "source_frame": self.source_frame,
            "t_seconds": self.t_seconds,
            "image": self.image_relpath,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class ContactSheet:
    """Every sampled frame of one Candidate in a single image, in frame order."""

    image_relpath: str
    sha256: str
    tile_width: int
    tile_height: int
    columns: int
    rows: int
    tile_frames: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "image": self.image_relpath,
            "sha256": self.sha256,
            "tile_width": self.tile_width,
            "tile_height": self.tile_height,
            "columns": self.columns,
            "rows": self.rows,
            "tile_order_frames": list(self.tile_frames),
        }


@dataclass(frozen=True)
class CandidateFrameEvidence:
    """The frames shown for one Candidate, with their source coordinates."""

    candidate_id: str
    material_id: str
    stream_index: int
    start_frame: int
    end_frame_exclusive: int
    frames: tuple[SampledFrame, ...]
    sample_strategy: str = SAMPLE_STRATEGY
    contact_sheet: ContactSheet | None = None

    def frames_between(self, start_frame: int, end_frame_exclusive: int) -> tuple[int, ...]:
        return tuple(
            frame.source_frame
            for frame in self.frames
            if start_frame <= frame.source_frame < end_frame_exclusive
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "material_id": self.material_id,
            "stream_index": self.stream_index,
            "start_frame": self.start_frame,
            "end_frame_exclusive": self.end_frame_exclusive,
            "sample_strategy": self.sample_strategy,
            "frame_count": len(self.frames),
            "contact_sheet": (
                None if self.contact_sheet is None else self.contact_sheet.as_dict()
            ),
            "frames": [frame.as_dict() for frame in self.frames],
        }


@dataclass(frozen=True)
class FrameEvidenceBundle:
    """Every frame the analyzer was shown for one run."""

    run_id: str
    candidate_pool_id: str
    coordinate_system: str
    candidates: tuple[CandidateFrameEvidence, ...]

    def for_candidate(self, candidate_id: str) -> CandidateFrameEvidence:
        for item in self.candidates:
            if item.candidate_id == candidate_id:
                return item
        raise FrameEvidenceError("candidate_id has no frame evidence in this bundle")

    @property
    def frame_count(self) -> int:
        return sum(len(item.frames) for item in self.candidates)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": FRAME_EVIDENCE_SCHEMA_VERSION,
            "run_id": self.run_id,
            "candidate_pool_id": self.candidate_pool_id,
            "coordinate_system": self.coordinate_system,
            "sample_strategy": SAMPLE_STRATEGY,
            "candidates": [item.as_dict() for item in self.candidates],
            "frame_count": self.frame_count,
        }


def render_frame_evidence(bundle: FrameEvidenceBundle) -> str:
    if not isinstance(bundle, FrameEvidenceBundle):
        raise FrameEvidenceError("bundle must be a FrameEvidenceBundle")
    return json.dumps(bundle.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def build_frame_evidence(
    *,
    run_id: str,
    extraction: CandidateExtraction,
    media_paths: Mapping[str, str],
    job_root: Path | str,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
    image_max_width: int = DEFAULT_IMAGE_MAX_WIDTH,
    contact_sheet: bool = True,
) -> FrameEvidenceBundle:
    """Decode, label, and write the frames for every accepted Candidate.

    ``media_paths`` maps a Material ID to a local readable source. A Candidate
    whose Material has no readable source is refused rather than silently skipped:
    an analyzer cannot be asked about frames nobody supplied.
    """

    if not isinstance(extraction, CandidateExtraction):
        raise FrameEvidenceError("extraction must be a CandidateExtraction")
    root = Path(job_root)
    evidences: list[CandidateFrameEvidence] = []
    for candidate in extraction.candidates:
        source = media_paths.get(candidate.material_id)
        if not source or not Path(source).is_file():
            raise FrameEvidenceError(
                "a Candidate's Material has no readable local source to sample"
            )
        frames, width, height = decode_window_frames(
            source,
            candidate.start_frame,
            candidate.end_frame_exclusive,
            scale_to_width=image_max_width,
        )
        indices = sample_frame_indices(
            candidate.start_frame, candidate.end_frame_exclusive, sample_count
        )
        measured = extraction.measured_for(candidate.candidate_id)
        sampled: list[SampledFrame] = []
        for source_frame in indices:
            image = frames[source_frame - candidate.start_frame]
            relative = (
                f"{FRAME_DIRECTORY}/{candidate.candidate_id}/"
                f"f{source_frame:06d}.png"
            )
            path = root / relative
            _write_png(image, path)
            sampled.append(
                SampledFrame(
                    source_frame=source_frame,
                    t_seconds=round(
                        measured.t_in_seconds
                        + (source_frame - candidate.start_frame)
                        * (measured.duration_seconds / measured.frame_count),
                        6,
                    ),
                    image_relpath=relative,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    width=width,
                    height=height,
                )
            )
        sheet: ContactSheet | None = None
        if contact_sheet:
            tiles = [frames[index - candidate.start_frame] for index in indices]
            composed = build_contact_sheet(tiles)
            sheet_relative = (
                f"{FRAME_DIRECTORY}/{candidate.candidate_id}/contact_sheet.png"
            )
            sheet_path = root / sheet_relative
            _write_png(composed, sheet_path)
            columns = min(CONTACT_SHEET_MAX_COLUMNS, len(indices))
            sheet = ContactSheet(
                image_relpath=sheet_relative,
                sha256=hashlib.sha256(sheet_path.read_bytes()).hexdigest(),
                tile_width=width,
                tile_height=height,
                columns=columns,
                rows=(len(indices) + columns - 1) // columns,
                tile_frames=tuple(indices),
            )
        evidences.append(
            CandidateFrameEvidence(
                candidate_id=candidate.candidate_id,
                material_id=candidate.material_id,
                stream_index=candidate.stream_index,
                start_frame=candidate.start_frame,
                end_frame_exclusive=candidate.end_frame_exclusive,
                frames=tuple(sampled),
                contact_sheet=sheet,
            )
        )
    bundle = FrameEvidenceBundle(
        run_id=run_id,
        candidate_pool_id=extraction.pool.pool_id,
        coordinate_system=SOURCE_COORDINATE_SYSTEM,
        candidates=tuple(evidences),
    )
    manifest = root / FRAME_EVIDENCE_ARTIFACT
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(render_frame_evidence(bundle), encoding="utf-8")
    return bundle


def build_contact_sheet(images: Sequence[np.ndarray], *, gap: int = CONTACT_SHEET_TILE_GAP,
                        border: int = CONTACT_SHEET_BORDER,
                        max_columns: int = CONTACT_SHEET_MAX_COLUMNS) -> np.ndarray:
    """Lay tiles out in ascending frame order, left to right, then downward."""

    if not images:
        raise FrameEvidenceError("a contact sheet needs at least one frame")
    tile_height, tile_width = images[0].shape[0], images[0].shape[1]
    for image in images:
        if image.shape[0] != tile_height or image.shape[1] != tile_width:
            raise FrameEvidenceError("contact sheet tiles must share one geometry")
    columns = min(max_columns, len(images))
    rows = (len(images) + columns - 1) // columns
    cell_width = tile_width + 2 * border
    cell_height = tile_height + 2 * border
    sheet = np.zeros(
        (
            rows * cell_height + (rows - 1) * gap,
            columns * cell_width + (columns - 1) * gap,
            3,
        ),
        dtype=np.uint8,
    )
    sheet[:, :] = 24
    for index, image in enumerate(images):
        row, column = divmod(index, columns)
        top = row * (cell_height + gap)
        left = column * (cell_width + gap)
        sheet[top : top + cell_height, left : left + cell_width] = 255
        sheet[
            top + border : top + border + tile_height,
            left + border : left + border + tile_width,
        ] = image
    return sheet


@dataclass(frozen=True)
class RegionOfInterest:
    """A rectangle in fractions of the frame, so it survives any downscale."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        for label, value in (
            ("x", self.x),
            ("y", self.y),
            ("width", self.width),
            ("height", self.height),
        ):
            if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
                raise FrameEvidenceError(f"region {label} must be a fraction in [0, 1]")
        if self.width <= 0 or self.height <= 0:
            raise FrameEvidenceError("a region must have a positive size")
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise FrameEvidenceError("a region must lie inside the frame")

    def pixels(self, width: int, height: int) -> tuple[slice, slice]:
        left = int(round(self.x * width))
        top = int(round(self.y * height))
        right = max(left + 1, int(round((self.x + self.width) * width)))
        bottom = max(top + 1, int(round((self.y + self.height) * height)))
        return slice(top, bottom), slice(left, right)

    def as_dict(self) -> dict[str, object]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class ProvenanceCheck:
    """One measurable expectation about a DIRECT claim, stated by the run.

    The expectation comes from the job, not from the model: a reviewer writes
    down what the cited frames are supposed to show, and the audit measures
    whether they do.
    """

    candidate_id: str
    product_fact_ref: str
    expectation: ChangeDirection
    min_delta: float
    kind: FrameCheckKind = FrameCheckKind.MEAN_LUMINANCE_CHANGE
    before_frame: int | None = None
    after_frame: int | None = None
    window: tuple[int, int] | None = None
    roi: RegionOfInterest | None = None
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _enum(self.kind, FrameCheckKind, "kind")
        )
        object.__setattr__(
            self,
            "expectation",
            _enum(self.expectation, ChangeDirection, "expectation"),
        )
        if self.min_delta < 0:
            raise FrameEvidenceError("min_delta must not be negative")
        if self.kind is FrameCheckKind.MEAN_LUMINANCE_CHANGE:
            if self.before_frame is None or self.after_frame is None:
                raise FrameEvidenceError(
                    "MEAN_LUMINANCE_CHANGE needs the two frames it compares"
                )
        else:
            if self.window is None:
                raise FrameEvidenceError(
                    "ROI_LUMINANCE_SPAN needs the window it sweeps"
                )
            start, end = self.window
            if end <= start:
                raise FrameEvidenceError("a check window must be non-empty")
            if self.expectation in DIRECTIONAL_EXPECTATIONS:
                raise FrameEvidenceError(
                    "a luminance span measures magnitude, not direction; declare a "
                    "direction with MEAN_LUMINANCE_CHANGE over two named frames"
                )

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "product_fact_ref": self.product_fact_ref,
            "kind": self.kind.value,
            "before_frame": self.before_frame,
            "after_frame": self.after_frame,
            "window": None if self.window is None else list(self.window),
            "expectation": self.expectation.value,
            "min_delta": self.min_delta,
            "region": None if self.roi is None else self.roi.as_dict(),
            "description": self.description,
        }


def _enum(value: object, member_type: type[Enum], label: str) -> object:
    choices = ", ".join(member.name for member in member_type)
    if not isinstance(value, str):
        raise FrameEvidenceError(f"{label} must be one of: {choices}")
    try:
        return member_type(value)
    except ValueError as exc:
        raise FrameEvidenceError(f"{label} must be one of: {choices}") from exc


@dataclass(frozen=True)
class ProvenanceFinding:
    check: ProvenanceCheck
    measured_before: float | None
    measured_after: float | None
    delta: float | None
    verdict: AuditVerdict
    detail: str
    extreme_frames: tuple[int, int] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            **self.check.as_dict(),
            "measured_before": self.measured_before,
            "measured_after": self.measured_after,
            "delta": self.delta,
            "extreme_frames": (
                None if self.extreme_frames is None else list(self.extreme_frames)
            ),
            "verdict": self.verdict.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class FrameAudit:
    """What the audit found. ``ok`` is the single reviewable answer."""

    candidate_id: str = ""
    findings: tuple[ProvenanceFinding, ...] = ()
    direct_claims: int = 0
    direct_claims_with_supplied_frame: int = 0
    direct_claims_without_supplied_frame: tuple[str, ...] = ()
    direct_claims_outside_bounds: tuple[str, ...] = ()
    frames_missing_or_changed: tuple[str, ...] = ()
    content_checks_passed: int = 0
    content_checks_failed: int = 0
    content_checks_not_run: int = 0

    @property
    def ok(self) -> bool:
        return not (
            self.direct_claims_without_supplied_frame
            or self.direct_claims_outside_bounds
            or self.frames_missing_or_changed
            or self.content_checks_failed
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": FRAME_AUDIT_SCHEMA_VERSION,
            "ok": self.ok,
            "direct_claims": self.direct_claims,
            "direct_claims_with_supplied_frame": self.direct_claims_with_supplied_frame,
            "direct_claims_without_supplied_frame": list(
                self.direct_claims_without_supplied_frame
            ),
            "direct_claims_outside_bounds": list(self.direct_claims_outside_bounds),
            "frames_missing_or_changed": list(self.frames_missing_or_changed),
            "content_checks_passed": self.content_checks_passed,
            "content_checks_failed": self.content_checks_failed,
            "content_checks_not_run": self.content_checks_not_run,
            "findings": [finding.as_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class EvidenceTruth:
    """The evidence-truth verdict, with the coverage that produced it."""

    status: CheckStatus
    detail: str
    direct_claims: int
    checked_direct_claims: int
    unverified_direct_claims: tuple[str, ...] = ()
    failed_direct_claims: tuple[str, ...] = ()
    scope: str = CHECK_SCOPE

    @property
    def ok(self) -> bool:
        return self.status is CheckStatus.CHECKS_PASSED

    def as_dict(self) -> dict[str, object]:
        return {
            "declared_check_status": self.status.value,
            "scope": self.scope,
            "detail": self.detail,
            "direct_claims": self.direct_claims,
            "checked_direct_claims": self.checked_direct_claims,
            "unverified_direct_claims": list(self.unverified_direct_claims),
            "failed_direct_claims": list(self.failed_direct_claims),
        }


def declared_check_status(evidence: object, audit: FrameAudit) -> EvidenceTruth:
    """Turn an audit into the declared-check verdict for one document.

    A `DIRECT` assertion counts as checked only when a declared check measured the
    same Candidate and Product Fact and passed its own predicate. Everything else is
    reported: failures explicitly, and unchecked assertions as unverified rather
    than true. Nothing here claims more than the checks measured - see
    :data:`CHECK_SCOPE`.
    """

    if not isinstance(evidence, (CandidateEvidence, CandidateEvidenceV2)):
        raise FrameEvidenceError(
            "evidence must be a Candidate Evidence document, under either version"
        )
    if not isinstance(audit, FrameAudit):
        raise FrameEvidenceError("audit must be a FrameAudit")

    unchecked = list(audit.direct_claims_without_supplied_frame)
    unchecked.extend(audit.direct_claims_outside_bounds)
    unchecked.extend(audit.frames_missing_or_changed)

    passed = {
        (finding.check.candidate_id, finding.check.product_fact_ref)
        for finding in audit.findings
        if finding.verdict is AuditVerdict.PASS
    }
    failed = {
        (finding.check.candidate_id, finding.check.product_fact_ref)
        for finding in audit.findings
        if finding.verdict is AuditVerdict.FAIL
    }
    direct: list[tuple[str, str]] = []
    for entry in evidence.entries:
        for claim in entry.claims or ():
            if claim.support is ClaimSupport.DIRECT:
                direct.append((entry.candidate_id, claim.product_fact_ref))

    failed_claims = [f"{c}:{f}" for c, f in direct if (c, f) in failed]
    unverified_claims = [
        f"{c}:{f}" for c, f in direct if (c, f) not in passed and (c, f) not in failed
    ]
    checked = len(direct) - len(failed_claims) - len(unverified_claims)

    if failed_claims or unchecked or audit.content_checks_failed:
        reasons = []
        if failed_claims:
            reasons.append("a declared check failed for " + ", ".join(failed_claims))
        if unchecked:
            reasons.append("provenance could not be tied to shown frames")
        if audit.frames_missing_or_changed:
            reasons.append("a shown frame no longer matches its recorded hash")
        return EvidenceTruth(
            status=CheckStatus.CHECKS_FAILED,
            detail="; ".join(reasons),
            direct_claims=len(direct),
            checked_direct_claims=checked,
            unverified_direct_claims=tuple(unverified_claims),
            failed_direct_claims=tuple(failed_claims),
        )
    if unverified_claims:
        return EvidenceTruth(
            status=CheckStatus.NOT_VERIFIED,
            detail=(
                "the contract accepted these DIRECT assertions and their cited frames were "
                "shown to the analyzer, but no declared check measured whether the media "
                "supports them: " + ", ".join(unverified_claims)
            ),
            direct_claims=len(direct),
            checked_direct_claims=checked,
            unverified_direct_claims=tuple(unverified_claims),
        )
    return EvidenceTruth(
        status=CheckStatus.CHECKS_PASSED,
        detail=(
            "every DIRECT assertion is covered by a declared check that measured its own "
            "predicate and passed; this is not proof of commercial or semantic truth"
            if direct
            else "no DIRECT assertion was made, so there is no declared check to report"
        ),
        direct_claims=len(direct),
        checked_direct_claims=checked,
    )


def evidence_truth_status(evidence: object, audit: FrameAudit) -> EvidenceTruth:
    """Deprecated alias for :func:`declared_check_status`.

    The earlier name promised more than a pixel check can deliver - "evidence truth"
    reads as semantic or commercial truth. New code should call
    :func:`declared_check_status` and read ``CheckStatus``.
    """

    return declared_check_status(evidence, audit)


def render_frame_audit(audit: FrameAudit) -> str:
    if not isinstance(audit, FrameAudit):
        raise FrameEvidenceError("audit must be a FrameAudit")
    return json.dumps(audit.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _mean_luminance(
    source: str, frame: int, roi: RegionOfInterest | None
) -> float:
    frames, width, height = decode_window_frames(source, frame, frame + 1)
    return _luminance_of(frames[0], width, height, roi)


def _luminance_of(
    image: np.ndarray, width: int, height: int, roi: RegionOfInterest | None
) -> float:
    values = image.astype(np.float64)
    if roi is not None:
        rows, columns = roi.pixels(width, height)
        values = values[rows, columns]
    return round(float((values @ _LUMA_WEIGHTS).mean()), 6)


def _run_span_check(
    source: str, check: ProvenanceCheck
) -> ProvenanceFinding:
    """Sweep the cited window and report the span the region reaches.

    The verdict is about magnitude only. It says the region moves by at least
    ``min_delta`` somewhere in the window (``ANY``), or that it never moves more
    than ``min_delta`` (``STABLE``). It cannot say which way time ran, and
    ``ProvenanceCheck`` refuses to let it try.
    """

    assert check.window is not None  # enforced by ProvenanceCheck
    start, end = check.window
    frames, width, height = decode_window_frames(source, start, end)
    means = [
        _luminance_of(frames[index], width, height, check.roi)
        for index in range(frames.shape[0])
    ]
    lowest = min(range(len(means)), key=lambda index: means[index])
    highest = max(range(len(means)), key=lambda index: means[index])
    span = round(means[highest] - means[lowest], 6)
    if check.expectation is ChangeDirection.STABLE:
        satisfied = span <= check.min_delta
        expectation_text = f"the region to stay within {check.min_delta} overall"
    else:
        satisfied = span >= check.min_delta
        expectation_text = (
            f"the region to span at least {check.min_delta} somewhere in the window"
        )
    return ProvenanceFinding(
        check=check,
        measured_before=means[lowest],
        measured_after=means[highest],
        delta=span,
        verdict=AuditVerdict.PASS if satisfied else AuditVerdict.FAIL,
        extreme_frames=(start + lowest, start + highest),
        detail=(
            f"across frames [{start}, {end}) the cited region ranged from "
            f"{means[lowest]} (frame {start + lowest}) to {means[highest]} "
            f"(frame {start + highest}), a span of {span}; the run expected "
            f"{expectation_text}. A span is a magnitude: this verdict makes no "
            f"claim about direction in time"
        ),
    )


def _run_change_check(
    source: str, check: ProvenanceCheck
) -> ProvenanceFinding:
    """Compare two named frames in temporal order. This one is directional."""

    assert check.before_frame is not None and check.after_frame is not None
    before = _mean_luminance(source, check.before_frame, check.roi)
    after = _mean_luminance(source, check.after_frame, check.roi)
    delta = round(after - before, 6)
    if check.expectation is ChangeDirection.STABLE:
        satisfied = abs(delta) <= check.min_delta
        expectation_text = f"the region to stay within {check.min_delta}"
    elif check.expectation is ChangeDirection.DECREASE:
        satisfied = -delta >= check.min_delta
        expectation_text = f"a fall of at least {check.min_delta}"
    elif check.expectation is ChangeDirection.INCREASE:
        satisfied = delta >= check.min_delta
        expectation_text = f"a rise of at least {check.min_delta}"
    else:
        satisfied = abs(delta) >= check.min_delta
        expectation_text = f"a change of at least {check.min_delta} either way"
    return ProvenanceFinding(
        check=check,
        measured_before=before,
        measured_after=after,
        delta=delta,
        verdict=AuditVerdict.PASS if satisfied else AuditVerdict.FAIL,
        extreme_frames=(check.before_frame, check.after_frame),
        detail=(
            f"the cited region measured {before} in frame {check.before_frame} and "
            f"{after} in frame {check.after_frame}, a change of {delta}; the run "
            f"expected {expectation_text}"
        ),
    )


def audit_frame_provenance(
    *,
    evidence: CandidateEvidence,
    bundle: FrameEvidenceBundle,
    media_paths: Mapping[str, str],
    checks: Sequence[ProvenanceCheck] = (),
    job_root: Path | str | None = None,
) -> FrameAudit:
    """Check every DIRECT claim against the frames and the media.

    Three questions, in order:

    1. **Integrity.** Do the images the analyzer was shown still hash to what the
       manifest recorded?
    2. **Coordinate honesty.** Does every DIRECT provenance range lie inside its
       Candidate, and did the analyzer actually see a frame inside it? A range
       nobody was shown is a citation of frames the answer cannot rest on.
    3. **Substance.** For each expectation the run supplied, do the cited pixels
       really show the change claimed?
    """

    if not isinstance(evidence, (CandidateEvidence, CandidateEvidenceV2)):
        raise FrameEvidenceError(
            "evidence must be a Candidate Evidence document, under either version"
        )
    if not isinstance(bundle, FrameEvidenceBundle):
        raise FrameEvidenceError("bundle must be a FrameEvidenceBundle")

    changed: list[str] = []
    if job_root is not None:
        root = Path(job_root)
        for candidate in bundle.candidates:
            for frame in candidate.frames:
                path = root / frame.image_relpath
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != frame.sha256:
                    changed.append(f"{candidate.candidate_id}:{frame.source_frame}")
            if candidate.contact_sheet is not None:
                sheet_path = root / candidate.contact_sheet.image_relpath
                if (
                    not sheet_path.is_file()
                    or hashlib.sha256(sheet_path.read_bytes()).hexdigest()
                    != candidate.contact_sheet.sha256
                ):
                    changed.append(f"{candidate.candidate_id}:contact_sheet")

    findings: list[ProvenanceFinding] = []
    direct_claims = 0
    with_supplied = 0
    without_supplied: list[str] = []
    outside_bounds: list[str] = []

    for entry in evidence.entries:
        candidate_frames: CandidateFrameEvidence | None
        try:
            candidate_frames = bundle.for_candidate(entry.candidate_id)
        except FrameEvidenceError:
            candidate_frames = None
        for claim in entry.claims or ():
            if claim.support is not ClaimSupport.DIRECT:
                continue
            direct_claims += 1
            label = f"{entry.candidate_id}:{claim.product_fact_ref}"
            inside = True
            saw_frame = False
            for source_range in claim.provenance:
                if candidate_frames is not None and (
                    source_range.start_frame < candidate_frames.start_frame
                    or source_range.end_frame_exclusive
                    > candidate_frames.end_frame_exclusive
                ):
                    inside = False
                if candidate_frames is not None and candidate_frames.frames_between(
                    source_range.start_frame, source_range.end_frame_exclusive
                ):
                    saw_frame = True
            if not inside:
                outside_bounds.append(label)
            elif saw_frame:
                with_supplied += 1
            else:
                without_supplied.append(label)

    for check in checks:
        source = media_paths.get(_material_for(bundle, check.candidate_id))
        if not source or not Path(source).is_file():
            findings.append(
                ProvenanceFinding(
                    check=check,
                    measured_before=None,
                    measured_after=None,
                    delta=None,
                    verdict=AuditVerdict.NOT_RUN,
                    detail="the Material has no readable local source to measure",
                )
            )
            continue
        if check.kind is FrameCheckKind.ROI_LUMINANCE_SPAN:
            findings.append(_run_span_check(source, check))
        else:
            findings.append(_run_change_check(source, check))

    passed = sum(1 for item in findings if item.verdict is AuditVerdict.PASS)
    failed = sum(1 for item in findings if item.verdict is AuditVerdict.FAIL)
    not_run = sum(1 for item in findings if item.verdict is AuditVerdict.NOT_RUN)
    return FrameAudit(
        findings=tuple(findings),
        direct_claims=direct_claims,
        direct_claims_with_supplied_frame=with_supplied,
        direct_claims_without_supplied_frame=tuple(without_supplied),
        direct_claims_outside_bounds=tuple(outside_bounds),
        frames_missing_or_changed=tuple(changed),
        content_checks_passed=passed,
        content_checks_failed=failed,
        content_checks_not_run=not_run,
    )


def _material_for(bundle: FrameEvidenceBundle, candidate_id: str) -> str:
    for candidate in bundle.candidates:
        if candidate.candidate_id == candidate_id:
            return candidate.material_id
    return ""


def parse_frame_evidence(document: object) -> FrameEvidenceBundle:
    """Parse a frame evidence manifest with exact-key validation."""

    mapping = _object(document, "frame evidence")
    _exact_keys(
        mapping,
        (
            "schema_version",
            "run_id",
            "candidate_pool_id",
            "coordinate_system",
            "sample_strategy",
            "candidates",
            "frame_count",
        ),
        "frame evidence",
    )
    if mapping["schema_version"] != FRAME_EVIDENCE_SCHEMA_VERSION:
        raise FrameEvidenceError(
            f"schema_version must be {FRAME_EVIDENCE_SCHEMA_VERSION!r}"
        )
    candidates: list[CandidateFrameEvidence] = []
    for position, raw in enumerate(_array(mapping["candidates"], "candidates")):
        item = _object(raw, f"candidates[{position}]")
        _exact_keys(
            item,
            (
                "candidate_id",
                "material_id",
                "stream_index",
                "start_frame",
                "end_frame_exclusive",
                "sample_strategy",
                "frame_count",
                "contact_sheet",
                "frames",
            ),
            f"candidates[{position}]",
        )
        frames: list[SampledFrame] = []
        for index, raw_frame in enumerate(
            _array(item["frames"], f"candidates[{position}].frames")
        ):
            frame = _object(
                raw_frame, f"candidates[{position}].frames[{index}]"
            )
            _exact_keys(
                frame,
                ("source_frame", "t_seconds", "image", "sha256", "width", "height"),
                f"candidates[{position}].frames[{index}]",
            )
            frames.append(
                SampledFrame(
                    source_frame=frame["source_frame"],  # type: ignore[arg-type]
                    t_seconds=frame["t_seconds"],  # type: ignore[arg-type]
                    image_relpath=frame["image"],  # type: ignore[arg-type]
                    sha256=frame["sha256"],  # type: ignore[arg-type]
                    width=frame["width"],  # type: ignore[arg-type]
                    height=frame["height"],  # type: ignore[arg-type]
                )
            )
        raw_sheet = item["contact_sheet"]
        sheet: ContactSheet | None = None
        if raw_sheet is not None:
            sheet_item = _object(raw_sheet, f"candidates[{position}].contact_sheet")
            _exact_keys(
                sheet_item,
                (
                    "image",
                    "sha256",
                    "tile_width",
                    "tile_height",
                    "columns",
                    "rows",
                    "tile_order_frames",
                ),
                f"candidates[{position}].contact_sheet",
            )
            sheet = ContactSheet(
                image_relpath=sheet_item["image"],  # type: ignore[arg-type]
                sha256=sheet_item["sha256"],  # type: ignore[arg-type]
                tile_width=sheet_item["tile_width"],  # type: ignore[arg-type]
                tile_height=sheet_item["tile_height"],  # type: ignore[arg-type]
                columns=sheet_item["columns"],  # type: ignore[arg-type]
                rows=sheet_item["rows"],  # type: ignore[arg-type]
                tile_frames=tuple(
                    _array(
                        sheet_item["tile_order_frames"],
                        f"candidates[{position}].contact_sheet.tile_order_frames",
                    )
                ),  # type: ignore[arg-type]
            )
        candidates.append(
            CandidateFrameEvidence(
                candidate_id=item["candidate_id"],  # type: ignore[arg-type]
                material_id=item["material_id"],  # type: ignore[arg-type]
                stream_index=item["stream_index"],  # type: ignore[arg-type]
                start_frame=item["start_frame"],  # type: ignore[arg-type]
                end_frame_exclusive=item["end_frame_exclusive"],  # type: ignore[arg-type]
                frames=tuple(frames),
                sample_strategy=item["sample_strategy"],  # type: ignore[arg-type]
                contact_sheet=sheet,
            )
        )
    return FrameEvidenceBundle(
        run_id=mapping["run_id"],  # type: ignore[arg-type]
        candidate_pool_id=mapping["candidate_pool_id"],  # type: ignore[arg-type]
        coordinate_system=mapping["coordinate_system"],  # type: ignore[arg-type]
        candidates=tuple(candidates),
    )


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise FrameEvidenceError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise FrameEvidenceError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise FrameEvidenceError(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise FrameEvidenceError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )
