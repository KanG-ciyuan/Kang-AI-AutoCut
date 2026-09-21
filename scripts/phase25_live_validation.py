#!/usr/bin/env python3
"""Phase 2.5 live semantic validation: real Candidates to a real multimodal analyzer.

This is opt-in and manual. Nothing here runs during the offline test suite.

    python3 scripts/phase25_live_validation.py prepare --workspace <DIR>
    python3 scripts/phase25_live_validation.py finish  --workspace <DIR>

``prepare`` does the deterministic half: it synthesizes purpose-built CFR test
media (never production material), registers it, runs the PROPOSE CANDIDATES
stage, samples each Candidate's frames with exact source frame labels plus a
contact sheet, and writes the analysis request under the v2 analyzer prompt
contract. It then stops at a gate and prints what the analyzer must produce
(exit code 5).

``finish`` does the other half: it takes the answer the analyzer wrote, runs it
through the existing Phase 2 validators through the authoring seam, writes
``candidate_evidence.v1``, and audits every DIRECT claim against the real media.

An analyzer may be supplied as a command (``prepare --analyzer-command CMD``),
which receives the analyst brief on stdin and writes the response artifact. With no
vision-capable analyzer configured, the operator answers between the two calls:
that is the same seam position, filled by a human or an agent instead of a process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ai_autocut import authoring, producer_registry as pr, shot_understanding
from src.ai_autocut.candidate_analysis import (
    ANALYZER_PROMPT_CONTRACT_VERSION,
    STRUCTURED_PROMPT_CONTRACT_VERSION,
    ClaimEnvelope,
    ClaimFact,
    CandidateAnalysisRequest,
    EvidenceStageResult,
    parse_candidate_evidence,
    parse_claim_envelope,
    parse_measurements,
    parse_segmentations,
    prompt_for,
    render_analysis_request,
    render_claim_envelope,
    run_candidate_extraction_stage,
    run_candidate_evidence_stage,
    targets_from_extraction,
)
from src.ai_autocut.candidate_evidence import validate_candidate_evidence
from src.ai_autocut.candidate_extraction import (
    ActionEvidence,
    SegmentSpan,
    SourceMeasurement,
    SourceSegmentation,
    WindowProposal,
    WindowRule,
    extract_candidates,
    render_window_proposals,
)
from src.ai_autocut.candidate_frame_evidence import (
    ChangeDirection,
    FrameCheckKind,
    declared_check_status,
    FRAME_EVIDENCE_ARTIFACT,
    ProvenanceCheck,
    RegionOfInterest,
    audit_frame_provenance,
    render_frame_audit,
)
from src.ai_autocut.identity import IdentityCatalog, identify_material, render_identity_catalog
from src.ai_autocut.timebase_adapter import TimebaseAdapter

FPS = 30
FRAMES = 90
WIDTH = 192
HEIGHT = 144
RUN_ID = "analysisrunv1_phase25live"

#: The four validation clips, named for what they are meant to test.
CLIPS = {
    "A": "wipe-action",
    "B": "similar-wipe",
    "C": "liquid-flow",
    "D": "beauty-product",
}

#: The closed Claim Envelope. Note what is deliberately absent: any hygiene,
#: efficacy, sterilisation, material, or health claim. A model that reaches for one
#: has no permitted fact to attach it to.
ENVELOPE_FACTS = (
    ClaimFact("fact_surface_visible", "a flat surface is visible in the frames"),
    ClaimFact(
        "fact_implement_contact_visible",
        "a wiping implement visibly contacts the surface during the frames",
    ),
    ClaimFact(
        "fact_surface_state_change_visible",
        "the visible state of the surface region changes after the contact",
    ),
    ClaimFact(
        "fact_liquid_flow_visible",
        "liquid is visible moving over the surface during the frames",
    ),
    ClaimFact(
        "fact_product_identity_visible",
        "the product itself is identifiably visible in the frames",
    ),
)

#: Explicit, reviewable expectations the audit measures against the real media.
#: These are written by the job, never derived from the analyzer's own wording.
AUDIT_CHECKS = (
    # The wipe's state change, asserted as a direction in time: the left part of the
    # surface is dark early in the wipe and light once the implement has passed it.
    ProvenanceCheck(
        candidate_id="A-ACTION",
        product_fact_ref="fact_surface_state_change_visible",
        kind=FrameCheckKind.MEAN_LUMINANCE_CHANGE,
        before_frame=20,
        after_frame=58,
        expectation=ChangeDirection.INCREASE,
        min_delta=60.0,
        roi=RegionOfInterest(0.10, 0.30, 0.35, 0.50),
        description=(
            "the left part of the surface must be measurably darker before the wipe "
            "reaches it and lighter afterwards; the dirty-to-clean contrast is about "
            "135 levels, so a real change is well above 60"
        ),
    ),
    # The same claim, with the two frames the other way round in time.
    ProvenanceCheck(
        candidate_id="A-ACTION",
        product_fact_ref="fact_surface_state_change_visible",
        kind=FrameCheckKind.MEAN_LUMINANCE_CHANGE,
        before_frame=20,
        after_frame=87,
        expectation=ChangeDirection.INCREASE,
        min_delta=60.0,
        roi=RegionOfInterest(0.70, 0.30, 0.22, 0.50),
        description=(
            "the right part of the surface, which the implement reaches last, must also "
            "be darker at the start of the window and lighter at the end"
        ),
    ),
    ProvenanceCheck(
        candidate_id="B-ACTION",
        product_fact_ref="fact_surface_state_change_visible",
        kind=FrameCheckKind.MEAN_LUMINANCE_CHANGE,
        before_frame=25,
        after_frame=85,
        expectation=ChangeDirection.INCREASE,
        min_delta=40.0,
        roi=RegionOfInterest(0.55, 0.15, 0.35, 0.30),
        description=(
            "the upper part of the second surface must be darker before the implement "
            "travels down over it and lighter once it has"
        ),
    ),
    ProvenanceCheck(
        candidate_id="C-FLOW",
        product_fact_ref="fact_liquid_flow_visible",
        kind=FrameCheckKind.MEAN_LUMINANCE_CHANGE,
        before_frame=20,
        after_frame=62,
        expectation=ChangeDirection.INCREASE,
        min_delta=15.0,
        roi=RegionOfInterest(0.12, 0.20, 0.76, 0.68),
        description=(
            "the surface must wet as liquid runs over it: measurably darker and drier "
            "when the flow starts, lighter and wet once it has run"
        ),
    ),
    # Guard checks: these assert that nothing happens, so they are magnitude-only.
    ProvenanceCheck(
        candidate_id="A-PRE",
        product_fact_ref="fact_surface_state_change_visible",
        kind=FrameCheckKind.ROI_LUMINANCE_SPAN,
        window=(0, 20),
        expectation=ChangeDirection.STABLE,
        min_delta=8.0,
        roi=RegionOfInterest(0.33, 0.34, 0.34, 0.32),
        description=(
            "the pre-action plate is static: across the whole window the surface region "
            "must not span more than measurement noise, which is what makes it an honest "
            "problem-state window rather than a change"
        ),
    ),
    ProvenanceCheck(
        candidate_id="D-BEAUTY",
        product_fact_ref="fact_surface_state_change_visible",
        kind=FrameCheckKind.ROI_LUMINANCE_SPAN,
        window=(0, 90),
        expectation=ChangeDirection.STABLE,
        min_delta=40.0,
        roi=RegionOfInterest(0.25, 0.15, 0.50, 0.70),
        description=(
            "a beauty bank asserts no effect: nothing in the frame may span more than 40 "
            "levels across the whole window. A beauty shot claiming a surface state change "
            "would fail here, which is the efficacy trap Phase 2.5 found"
        ),
    ),
)

#: Which proposal each check belongs to, resolved to a real Candidate at run time.
CHECK_CANDIDATE_KEYS = {
    "A-ACTION": "wpropv1_live_a_action",
    "A-PRE": "wpropv1_live_a_before",
    "B-ACTION": "wpropv1_live_b_action",
    "C-FLOW": "wpropv1_live_c_flow",
    "D-BEAUTY": "wpropv1_live_d_seg00",
}


# --------------------------------------------------------------------------- media


def _blend(dirty: np.ndarray, clean: np.ndarray, coverage: np.ndarray) -> np.ndarray:
    """Blend a dirty and a clean surface by how much of it has been wiped."""

    return (dirty * (1.0 - coverage) + clean * coverage).astype(np.uint8)


def _noise(rng: np.random.Generator, height: int, width: int, spread: int = 10) -> np.ndarray:
    return rng.integers(-spread, spread + 1, size=(height, width, 3)).astype(np.float64)


def build_clip_a() -> np.ndarray:
    """Two shots: a wide static view of a dirty surface, then a close wipe.

    The hard cut at frame 20 is deliberate: it is a real scene change, so the
    repository's own segmentation engine finds it rather than being told about it.
    """

    rng = np.random.default_rng(20250225)
    frames = np.zeros((FRAMES, HEIGHT, WIDTH, 3), dtype=np.uint8)
    wide_top, wide_bottom, wide_left, wide_right = 52, 92, 64, 128
    wide_dirty = np.full((wide_bottom - wide_top, wide_right - wide_left, 3), 74.0)
    wide_dirty += _noise(rng, wide_bottom - wide_top, wide_right - wide_left, 8)

    top, bottom, left, right = 40, 120, 16, 176
    height, width = bottom - top, right - left
    dirty = np.full((height, width, 3), 70.0)
    dirty += _noise(rng, height, width, 12)
    clean = np.full((height, width, 3), 205.0)

    for index in range(FRAMES):
        if index < 20:
            frame = np.full((HEIGHT, WIDTH, 3), 30.0)
            frame[wide_top:wide_bottom, wide_left:wide_right] = wide_dirty
        else:
            frame = np.full((HEIGHT, WIDTH, 3), 18.0)
            progress = min(1.0, (index - 20) / 50.0)
            coverage = np.clip(
                (progress * width - np.arange(width)) / 8.0, 0.0, 1.0
            )[None, :, None]
            frame[top:bottom, left:right] = _blend(dirty, clean, coverage)
            if index <= 70:
                cloth_x = left + int(progress * width)
                frame[top - 6 : bottom + 6, cloth_x : cloth_x + 22] = 245.0
                frame[top - 6 : bottom + 6, cloth_x : cloth_x + 4] = 160.0
        frames[index] = frame
    return frames


def build_clip_b() -> np.ndarray:
    """Two shots: a wide static view of a second surface, then a top-to-bottom wipe."""

    rng = np.random.default_rng(20250226)
    frames = np.zeros((FRAMES, HEIGHT, WIDTH, 3), dtype=np.uint8)
    wide_top, wide_bottom, wide_left, wide_right = 54, 96, 104, 172
    wide_dirty = np.zeros((wide_bottom - wide_top, wide_right - wide_left, 3))
    wide_dirty[:, :, 0], wide_dirty[:, :, 1], wide_dirty[:, :, 2] = 62.0, 62.0, 88.0
    wide_dirty += _noise(rng, wide_bottom - wide_top, wide_right - wide_left, 7)

    top, bottom, left, right = 16, 128, 96, 180
    height, width = bottom - top, right - left
    dirty = np.zeros((height, width, 3))
    dirty[:, :, 0], dirty[:, :, 1], dirty[:, :, 2] = 58.0, 58.0, 84.0
    dirty += _noise(rng, height, width, 12)
    clean = np.zeros((height, width, 3))
    clean[:, :, 0], clean[:, :, 1], clean[:, :, 2] = 150.0, 172.0, 206.0

    for index in range(FRAMES):
        if index < 25:
            frame = np.full((HEIGHT, WIDTH, 3), 34.0)
            frame[wide_top:wide_bottom, wide_left:wide_right] = wide_dirty
        else:
            frame = np.full((HEIGHT, WIDTH, 3), 20.0)
            progress = min(1.0, (index - 25) / 50.0)
            coverage = np.clip(
                (progress * height - np.arange(height)) / 8.0, 0.0, 1.0
            )[:, None, None]
            frame[top:bottom, left:right] = _blend(dirty, clean, coverage)
            if index <= 75:
                cloth_y = top + int(progress * height)
                frame[cloth_y : cloth_y + 20, left - 6 : right + 6] = 240.0
                frame[cloth_y : cloth_y + 4, left - 6 : right + 6] = 150.0
        frames[index] = frame
    return frames


def build_clip_c() -> np.ndarray:
    """Two shots: a wide static view of a dry surface, then liquid running over it."""

    rng = np.random.default_rng(20250227)
    frames = np.zeros((FRAMES, HEIGHT, WIDTH, 3), dtype=np.uint8)
    wide_top, wide_bottom, wide_left, wide_right = 58, 100, 60, 132
    wide_dry = np.zeros((wide_bottom - wide_top, wide_right - wide_left, 3))
    wide_dry[:, :, 0], wide_dry[:, :, 1], wide_dry[:, :, 2] = 96.0, 100.0, 104.0
    wide_dry += _noise(rng, wide_bottom - wide_top, wide_right - wide_left, 6)

    top, bottom, left, right = 30, 126, 24, 168
    height, width = bottom - top, right - left
    dry = np.zeros((height, width, 3))
    dry[:, :, 0], dry[:, :, 1], dry[:, :, 2] = 92.0, 96.0, 100.0
    wet = dry * 0.62 + np.array([70.0, 92.0, 120.0])
    streak_positions = rng.integers(0, width, size=(FRAMES, 9))

    for index in range(FRAMES):
        if index < 20:
            frame = np.full((HEIGHT, WIDTH, 3), 26.0)
            frame[wide_top:wide_bottom, wide_left:wide_right] = wide_dry
        else:
            frame = np.full((HEIGHT, WIDTH, 3), 16.0)
            progress = min(1.0, (index - 20) / 50.0)
            frame[top:bottom, left:right] = _blend(
                dry, wet, np.full((height, width, 1), progress)
            )
            if index <= 70:
                fall = (index - 20) * 4
                for streak in streak_positions[index]:
                    column = int(streak)
                    head = (fall + int(streak) * 7) % (height + 24)
                    for offset in range(24):
                        row = head - offset
                        if 0 <= row < height:
                            shade = 235 - offset * 6
                            frame[top + row, left + column : left + column + 2] = (
                                shade, shade, 255,
                            )
        frames[index] = frame
    return frames


def build_clip_d() -> np.ndarray:
    """A beauty bank: a smooth, glossy product form turning in soft light.

    Nothing on any surface changes and nothing is being cleaned. It is meant to be
    attractive, and to prove nothing.
    """

    frames = np.zeros((FRAMES, HEIGHT, WIDTH, 3), dtype=np.uint8)
    centre_x, centre_y = WIDTH // 2, HEIGHT // 2
    grid_y, grid_x = np.mgrid[0:HEIGHT, 0:WIDTH]
    for index in range(FRAMES):
        frame = np.full((HEIGHT, WIDTH, 3), 14.0)
        vignette = np.clip(
            1.0 - (np.hypot(grid_x - centre_x, grid_y - centre_y) / 150.0), 0.0, 1.0
        )
        frame += (vignette * 26.0)[:, :, None]
        half_height, half_width = 46, 17
        top, bottom = centre_y - half_height, centre_y + half_height
        rows = np.arange(top, bottom)
        bulge = np.sqrt(
            np.clip(1.0 - ((rows - centre_y) / half_height) ** 2, 0.0, 1.0)
        )
        width_profile = (bulge * half_width).astype(int)
        highlight = 0.5 + 0.5 * np.sin(index / FRAMES * 2 * np.pi)
        for row_index, row in enumerate(rows):
            half = width_profile[row_index]
            if half <= 0:
                continue
            span = np.arange(centre_x - half, centre_x + half)
            if span.size == 0:
                continue
            across = (span - (centre_x - half)) / max(1, 2 * half)
            body = 118.0 + 60.0 * np.clip(1.0 - np.abs(across - 0.32), 0.0, 1.0)
            gloss = (
                90.0
                * highlight
                * np.clip(1.0 - np.abs(across - 0.28 - 0.1 * highlight), 0.0, 1.0)
            )
            value = np.clip(body + gloss, 0.0, 255.0)
            frame[row, span] = np.stack(
                [value * 0.94, value * 0.97, value], axis=-1
            ).astype(np.uint8)
        frame[top - 2 : top + 3, centre_x - 12 : centre_x + 12] = 226
        frames[index] = frame
    return frames


BUILDERS = {
    "A": build_clip_a,
    "B": build_clip_b,
    "C": build_clip_c,
    "D": build_clip_d,
}


def write_clip(frames: np.ndarray, path: Path) -> None:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS), str(path),
    ]
    result = subprocess.run(command, input=frames.tobytes(), capture_output=True)
    if result.returncode != 0 or not path.is_file():
        raise SystemExit(f"ffmpeg could not write {path.name}: {result.stderr[-300:]!r}")


def build_media(media_root: Path) -> dict[str, Path]:
    media_root.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for key, label in CLIPS.items():
        path = media_root / f"clip-{key.lower()}-{label}.mp4"
        if not path.is_file():
            write_clip(BUILDERS[key](), path)
        paths[key] = path
    return paths


# ----------------------------------------------------------------------- prepare


def _segmentation_for(
    measurement: SourceMeasurement, source: Path, *, threshold: float = 30.0
) -> SourceSegmentation:
    """Real visual segmentation of a real file, in measured source frame indices."""

    frame_count, differences = shot_understanding.decode_differences(str(source))
    if frame_count != measurement.frame_count:
        raise SystemExit(
            "the analysis frame space is not the source frame space for this clip"
        )
    boundaries = shot_understanding.detect_boundaries(differences, threshold=threshold)
    segments, _ = shot_understanding.split_into_segments(0, frame_count, boundaries)
    return SourceSegmentation(
        material_id=measurement.material_id,
        stream_index=0,
        segments=tuple(
            SegmentSpan(index, segment.start_frame, segment.end_frame_exclusive)
            for index, segment in enumerate(segments)
        ),
    )


def _segment_containing(segmentation: SourceSegmentation, frame: int) -> SegmentSpan:
    for segment in segmentation.segments:
        if segment.start_frame <= frame < segment.end_frame_exclusive:
            return segment
    return segmentation.segments[-1]


def _proposals_for(
    segmentations: dict[str, SourceSegmentation],
) -> tuple[WindowProposal, ...]:
    """The focused validation set: one action Candidate per action clip, plus
    the untouched-window Candidates that should yield an honest no-support result."""

    sections = {key: value.material_id for key, value in MATERIALS.items()}
    proposals: list[WindowProposal] = []
    # A: the wipe itself, as an action-safe window.
    proposals.append(
        WindowProposal(
            "wpropv1_live_a_action",
            WindowRule.ACTION_SAFE_WINDOW,
            sections["A"],
            0,
            20,
            88,
            "the wipe action and the clean state that follows it",
            (),
            (),
            ActionEvidence(preparation_start=14, action_onset=20, action_completion=70, result_end_exclusive=88),
        )
    )
    # A: the window before the wipe starts, which shows no action at all.
    before = _segment_containing(segmentations["A"], 4)
    proposals.append(
        WindowProposal(
            "wpropv1_live_a_before",
            WindowRule.SINGLE_SEGMENT,
            sections["A"],
            0,
            before.start_frame,
            before.end_frame_exclusive,
            "the surface before anything happens to it",
            (before.segment_index,),
        )
    )
    # B: the similar wipe.
    proposals.append(
        WindowProposal(
            "wpropv1_live_b_action",
            WindowRule.ACTION_SAFE_WINDOW,
            sections["B"],
            0,
            25,
            86,
            "a second wipe of the same kind on another surface",
            (),
            (),
            ActionEvidence(preparation_start=18, action_onset=25, action_completion=75, result_end_exclusive=86),
        )
    )
    # C: the flow, which is different evidence from a wipe.
    proposals.append(
        WindowProposal(
            "wpropv1_live_c_flow",
            WindowRule.ACTION_SAFE_WINDOW,
            sections["C"],
            0,
            20,
            80,
            "liquid running over the surface and wetting it",
            (),
            (),
            ActionEvidence(preparation_start=14, action_onset=20, action_completion=70, result_end_exclusive=80),
        )
    )
    # D: the beauty bank, taken whole.
    for segment in segmentations["D"].segments:
        proposals.append(
            WindowProposal(
                f"wpropv1_live_d_seg{segment.segment_index:02d}",
                WindowRule.SINGLE_SEGMENT,
                sections["D"],
                0,
                segment.start_frame,
                segment.end_frame_exclusive,
                "a product beauty bank with no action in it",
                (segment.segment_index,),
            )
        )
    return tuple(proposals)


MATERIALS: dict[str, object] = {}


def prepare(workspace: Path, sample_count: int, analyzer_command: str | None) -> int:
    job = workspace / "job"
    inputs = workspace / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    paths = build_media(workspace / "media")

    adapter = TimebaseAdapter(fps=FPS)
    materials = {key: identify_material(path) for key, path in paths.items()}
    MATERIALS.clear()
    MATERIALS.update(materials)
    catalog = IdentityCatalog(materials=tuple(materials.values()), candidates=())
    (inputs / "identity_catalog.json").write_text(
        render_identity_catalog(catalog), encoding="utf-8"
    )

    measurements = {
        key: SourceMeasurement.from_source(
            material_id=materials[key].material_id,
            stream_index=0,
            source=str(paths[key]),
            adapter=adapter,
        )
        for key in CLIPS
    }
    (inputs / "measurements.json").write_text(
        json.dumps(
            {
                "schema_version": "candidate_measurements.v1",
                "measurements": [
                    {
                        "material_id": measurement.material_id,
                        "stream_index": 0,
                        "source": measurement.source,
                        "timestamps": list(measurement.timestamps),
                        "fps": FPS,
                    }
                    for measurement in measurements.values()
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    segmentations = {
        key: _segmentation_for(measurements[key], paths[key]) for key in CLIPS
    }
    (inputs / "segmentations.json").write_text(
        json.dumps(
            {
                "schema_version": "candidate_segmentations.v1",
                "segmentations": [
                    {
                        "material_id": segmentation.material_id,
                        "stream_index": 0,
                        "segments": [
                            {
                                "start_frame": segment.start_frame,
                                "end_frame_exclusive": segment.end_frame_exclusive,
                            }
                            for segment in segmentation.segments
                        ],
                    }
                    for segmentation in segmentations.values()
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    proposals = _proposals_for(segmentations)
    (inputs / "proposals.json").write_text(
        render_window_proposals(proposals), encoding="utf-8"
    )
    envelope = ClaimEnvelope(
        ref="brief/claim_envelope.json",
        sha256=hashlib.sha256(b"ai-autocut:phase25:claim-envelope").hexdigest(),
        facts=ENVELOPE_FACTS,
    )
    (inputs / "claim_envelope.json").write_text(
        render_claim_envelope(envelope), encoding="utf-8"
    )

    extraction_result = run_candidate_extraction_stage(
        job_root=job,
        catalog=catalog,
        measurements=tuple(measurements.values()),
        segmentations=tuple(segmentations.values()),
        proposals=proposals,
    )
    extraction = extraction_result.extraction

    from src.ai_autocut.candidate_frame_evidence import build_frame_evidence

    media_paths = {materials[key].material_id: str(paths[key]) for key in CLIPS}
    bundle = build_frame_evidence(
        run_id=RUN_ID,
        extraction=extraction,
        media_paths=media_paths,
        job_root=job,
        sample_count=sample_count,
    )

    request = CandidateAnalysisRequest(
        run_id=RUN_ID,
        candidate_pool_id=extraction.pool.pool_id,
        claim_envelope=envelope,
        targets=targets_from_extraction(extraction),
        prompt_contract_version=STRUCTURED_PROMPT_CONTRACT_VERSION,
        question=prompt_for(STRUCTURED_PROMPT_CONTRACT_VERSION),
    )
    request_text = render_analysis_request(request)
    (job / pr.CANDIDATE_ANALYSIS_REQUEST_ARTIFACT).write_text(request_text, encoding="utf-8")

    candidate_ids = {
        outcome.proposal.proposal_id: outcome.candidate.candidate_id
        for outcome in extraction.outcomes
        if outcome.candidate is not None
    }
    key_to_candidate = {
        "A-ACTION": candidate_ids.get("wpropv1_live_a_action"),
        "A-PRE": candidate_ids.get("wpropv1_live_a_before"),
        "B-ACTION": candidate_ids.get("wpropv1_live_b_action"),
        "C-FLOW": candidate_ids.get("wpropv1_live_c_flow"),
        "D-BEAUTY": candidate_ids.get("wpropv1_live_d_seg00"),
    }

    brief = {
        "run_id": RUN_ID,
        "prompt_contract_version": STRUCTURED_PROMPT_CONTRACT_VERSION,
        "evidence_contract_version": "candidate_evidence.v2",
        "job_root": str(job),
        "request": str(job / pr.CANDIDATE_ANALYSIS_REQUEST_ARTIFACT),
        "frame_evidence": str(job / FRAME_EVIDENCE_ARTIFACT),
        "response_must_be_written_to": str(
            job / pr.CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT
        ),
        "candidates": [
            {
                "proposal_id": outcome.proposal.proposal_id,
                "candidate_id": outcome.candidate.candidate_id,
                "material_id": outcome.candidate.material_id,
                "frames": [outcome.candidate.start_frame, outcome.candidate.end_frame_exclusive],
                "measured_seconds": None if outcome.measured is None else outcome.measured.duration_seconds,
                "contact_sheet": bundle.for_candidate(
                    outcome.candidate.candidate_id
                ).contact_sheet.image_relpath,
            }
            for outcome in extraction.outcomes
            if outcome.candidate is not None
        ],
        "checks": {
            key: candidate for key, candidate in key_to_candidate.items() if candidate
        },
        "extraction": extraction.counts(),
        "rejections": extraction.rejection_counts(),
        "pool_id": extraction.pool.pool_id,
    }
    (workspace / "ANALYZER_BRIEF.json").write_text(
        json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (workspace / "ANALYZER_TASK.md").write_text(
        _analyst_task_markdown(brief, request_text), encoding="utf-8"
    )
    (workspace / "AUDIT_CHECKS.json").write_text(
        json.dumps(
            {
                "checks": [
                    {
                        **check.as_dict(),
                        "candidate_key": CHECK_CANDIDATE_KEYS.get(
                            check.candidate_id, check.candidate_id
                        ),
                    }
                    for check in AUDIT_CHECKS
                ],
                "candidate_ids": brief["checks"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(json.dumps(brief, ensure_ascii=False, indent=2))
    print()
    print(f"ANALYZER GATE: write the response to {job / pr.CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT}")
    print(f"Analyst brief: {workspace / 'ANALYZER_TASK.md'}")
    print(f"Frame manifest: {job / FRAME_EVIDENCE_ARTIFACT}")

    if analyzer_command:
        print(f"running analyzer command: {analyzer_command}")
        result = subprocess.run(
            analyzer_command,
            shell=True,
            input=json.dumps(brief),
            text=True,
            capture_output=True,
            timeout=1800,
        )
        print("analyzer stdout:", result.stdout[-2000:])
        if result.returncode != 0:
            print("analyzer stderr:", result.stderr[-1000:])
            return 6
        return finish(workspace)
    return 5


def _analyst_task_markdown(brief: dict, request_text: str) -> str:
    lines = [
        "# Phase 2.5 analyst task",
        "",
        f"Run identity: `{brief['run_id']}`  ",
        f"Prompt contract: `{brief['prompt_contract_version']}`",
        "",
        "You are the live multimodal analyzer. Read the prompt contract below, then look at",
        "each Candidate's contact sheet and frames, then write the response document to:",
        "",
        f"    {brief['response_must_be_written_to']}",
        "",
        "## Candidates",
        "",
        "| proposal | candidate_id | window (source frames) | seconds | contact sheet |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in brief["candidates"]:
        lines.append(
            f"| {item['proposal_id']} | {item['candidate_id']} | "
            f"{item['frames'][0]}–{item['frames'][1]} | {item['measured_seconds']} | "
            f"{item['contact_sheet']} |"
        )
    lines += [
        "",
        "The frame manifest (`ANALYZER_BRIEF.json` -> `frame_evidence`) records, for every",
        "image, its exact decoded source frame number, measured timestamp, and SHA-256. Cite",
        "only those frame numbers.",
        "",
        "## Prompt contract",
        "",
        "```text",
        request_text and json.loads(request_text)["question"],
        "```",
    ]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------ finish


def finish(workspace: Path) -> int:
    job = workspace / "job"
    inputs = workspace / "inputs"
    envelope = parse_claim_envelope(
        json.loads((inputs / "claim_envelope.json").read_text(encoding="utf-8"))
    )
    catalog = json.loads((inputs / "identity_catalog.json").read_text(encoding="utf-8"))
    from src.ai_autocut.identity import parse_identity_catalog

    identities = parse_identity_catalog(catalog)
    measurements = parse_measurements(
        json.loads((inputs / "measurements.json").read_text(encoding="utf-8"))
    )
    segmentations = parse_segmentations(
        json.loads((inputs / "segmentations.json").read_text(encoding="utf-8"))
    )
    proposals = None
    from src.ai_autocut.candidate_extraction import parse_window_proposals

    proposals = parse_window_proposals(
        json.loads((inputs / "proposals.json").read_text(encoding="utf-8"))
    )
    extraction_result = run_candidate_extraction_stage(
        job_root=job,
        catalog=identities,
        measurements=measurements,
        segmentations=segmentations,
        proposals=proposals,
    )
    extraction = extraction_result.extraction

    response_path = job / pr.CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT
    if not response_path.is_file():
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": "no analyzer response artifact was written",
                    "expected": str(response_path),
                },
                ensure_ascii=False,
            )
        )
        return 3

    stage: EvidenceStageResult = run_candidate_evidence_stage(
        job_root=job,
        extraction=extraction,
        envelope=envelope,
        run_id=RUN_ID,
        prompt_contract_version=STRUCTURED_PROMPT_CONTRACT_VERSION,
        agent=authoring.PrewrittenAuthoringAgent(),
    )

    from src.ai_autocut.candidate_frame_evidence import parse_frame_evidence

    bundle = parse_frame_evidence(
        json.loads((job / FRAME_EVIDENCE_ARTIFACT).read_text(encoding="utf-8"))
    )
    media_paths = {item.material_id: item.source for item in measurements}
    candidate_ids = {
        outcome.proposal.proposal_id: outcome.candidate.candidate_id
        for outcome in extraction.outcomes
        if outcome.candidate is not None
    }
    checks = tuple(
        ProvenanceCheck(
            candidate_id=candidate_ids[CHECK_CANDIDATE_KEYS[check.candidate_id]],
            product_fact_ref=check.product_fact_ref,
            expectation=check.expectation,
            min_delta=check.min_delta,
            kind=check.kind,
            before_frame=check.before_frame,
            after_frame=check.after_frame,
            window=check.window,
            roi=check.roi,
            description=check.description,
        )
        for check in AUDIT_CHECKS
    )
    audit = audit_frame_provenance(
        evidence=stage.evidence,
        bundle=bundle,
        media_paths=media_paths,
        checks=checks,
        job_root=job,
    )
    (job / "analysis/candidate_frame_audit.json").write_text(
        render_frame_audit(audit), encoding="utf-8"
    )

    # Contract validity and evidence truth are separate axes, and the report keeps
    # them separate: a document can satisfy every contract rule and still assert
    # something the media does not show.
    truth = declared_check_status(stage.evidence, audit)
    (job / "analysis/candidate_evidence_truth.json").write_text(
        json.dumps(truth.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report = {
        **stage.as_dict(),
        "contract_validity": {
            "contract": stage.as_dict()["evidence"]["ref"],
            "CONTRACT_VALID": "YES",
            "validated_by": "candidate_evidence.validate_candidate_evidence_v2",
            "entries": stage.as_dict()["evidence"]["entries"],
            "pool_size": stage.as_dict()["evidence"]["pool_size"],
        },
        "declared_check_status": truth.as_dict(),
        "frame_audit": audit.as_dict(),
        "evidence_sha256": hashlib.sha256(stage.evidence_text.encode("utf-8")).hexdigest(),
    }
    (workspace / "LIVE_VALIDATION_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "finish"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--sample-count", type=int, default=8)
    parser.add_argument("--analyzer-command", default=None)
    args = parser.parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if args.mode == "prepare":
        return prepare(workspace, args.sample_count, args.analyzer_command)
    return finish(workspace)


if __name__ == "__main__":
    raise SystemExit(main())
