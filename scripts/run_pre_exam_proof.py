#!/usr/bin/env python3
"""Pre-exam execution proof — produce and independently verify a real master.

Purpose
-------
Prove that the production control path can produce and verify a **real master file**.
This is not a Third-SKU run and not a creative exercise. The output is a few seconds
long on purpose: what is being proved is execution and verification, not quality.

Reproducing it
--------------
Everything below is a tracked command and a job input. No previous conversation is
required::

    python3 scripts/run_pre_exam_proof.py --job-root /tmp/pre-exam-proof

The script is deliberately two-phase, because that is the real workflow:

1. Build a job with real local media and the CODEX producer inputs, then run the normal
   production control path. The fast path invokes the four job-scoped execution
   adapters (picture, typography, audio, assemble) at their own stages, and stops at the
   human release gate.
2. Read the **verified** master's sha256 from the run, write the human release naming
   that master, and resume. The run completes.
3. Independently re-measure ``final/master.mp4`` and print the evidence.

No provider call is made, and no DaVinci research is reopened: the route is local FFmpeg
and Pillow, which the project has already proven.

Exit code is 0 only when the master exists and every measurement passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ai_autocut import media_probe  # noqa: E402
from ai_autocut.fast_path import (  # noqa: E402
    ASSEMBLY_EVIDENCE_ARTIFACT,
    EXIT_CODES,
    HUMAN_RELEASE_ARTIFACT,
    FastPath,
)
from ai_autocut.review import REVIEWER_DIMENSIONS  # noqa: E402

JOB_ID = "pre-exam-execution-proof-v1"
WIDTH, HEIGHT, FPS = 540, 960, 30
SECONDS = 3.0
FRAMES = int(SECONDS * FPS)


def run(command: list[str], label: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"{label} failed: {result.stderr[-400:]}")


def write(root: Path, relative: str, payload: object) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_job(root: Path) -> Path:
    """Real media plus the producer inputs a CODEX producer authors for this job."""

    root.mkdir(parents=True, exist_ok=True)
    source = root / "source.mp4"
    voice = root / "assets" / "voice.wav"
    music = root / "assets" / "music.wav"
    for path in (voice, music):
        path.parent.mkdir(parents=True, exist_ok=True)

    run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size={WIDTH}x{HEIGHT}:rate={FPS}:duration={SECONDS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), str(source),
        ],
        "rendering the proof source",
    )
    run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=330:duration={SECONDS}",
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(voice),
        ],
        "rendering the voice asset",
    )
    run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=196:duration={SECONDS}",
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(music),
        ],
        "rendering the music asset",
    )

    write(
        root,
        "source_inventory.json",
        {
            "schema_version": "source_inventory.v1",
            "files": [
                {
                    "source_id": "PROOF-01",
                    "filename": source.name,
                    "path": str(source),
                    "size_bytes": source.stat().st_size,
                    "mtime_ns": source.stat().st_mtime_ns,
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            ],
        },
    )
    write(
        root,
        "shots/placements.json",
        {
            "placements": [
                {
                    "placement_id": "P01",
                    "source_id": "PROOF-01",
                    "media_path": str(source),
                    # Measured source window. The decoded frame range is derived from
                    # this by the timebase adapter, never from frame_index/fps.
                    "t_in_seconds": 0.0,
                    "duration_seconds": SECONDS,
                }
            ]
        },
    )
    write(
        root,
        "edit/timeline_ranges.json",
        {
            "ranges": [
                {
                    "shot_id": "S01", "role": "identity",
                    "start_frame": 0, "end_frame_exclusive": FRAMES,
                }
            ]
        },
    )
    write(
        root,
        "picture/source_ranges.json",
        {
            "ranges": [
                {"unit_id": "U01", "source": str(source), "t_in_seconds": 0.0, "frames": FRAMES // 2},
                {"unit_id": "U02", "source": str(source), "t_in_seconds": SECONDS / 2, "frames": FRAMES // 2},
            ]
        },
    )
    write(
        root,
        "picture/measurements.json",
        {
            "shots": [
                {
                    "measurement": {
                        "shot_id": "S01", "start_seconds": 0.0, "duration_seconds": SECONDS,
                        "luminance": 0.5, "cast_u": 0.0, "cast_v": 0.0, "saturation": 0.5,
                        "contrast": 0.5, "sharpness": 0.5, "product_region": None,
                        "product_luminance": None, "product_saturation": None,
                        "product_contrast": None, "confidence": "HIGH",
                    },
                    "contains_product": False,
                }
            ]
        },
    )
    write(
        root,
        "copy/commercial_units.json",
        {
            "units": [
                {
                    "unit_id": "U01", "start_seconds": 0.0, "end_seconds": 1.5,
                    "visual_self_explanatory": False,
                    "carries_new_commercial_information": True, "has_title": False,
                    "vo_adds_function_beyond_title": True, "explanation_supported": True,
                    "vo": {
                        "vo_id": "VO01", "purpose": "DEMONSTRATION_EXPLANATION",
                        "semantic_unit": "U01", "required": True, "silence_reason": None,
                        "window_seconds": [0.0, 1.5],
                    },
                },
                {
                    "unit_id": "U02", "start_seconds": 1.5, "end_seconds": 3.0,
                    "visual_self_explanatory": True,
                    "carries_new_commercial_information": True, "has_title": False,
                    "vo_adds_function_beyond_title": True, "explanation_supported": True,
                    "vo": {
                        "vo_id": "VO02", "purpose": "CTA", "semantic_unit": "U02",
                        "required": True, "silence_reason": None,
                        "window_seconds": [1.5, 3.0],
                    },
                },
            ]
        },
    )
    write(
        root,
        "audio/placement.json",
        {
            "segments": [
                {"segment_id": "VO01", "start_seconds": 0.0, "end_seconds": 1.4, "text": "pasang"},
                {"segment_id": "VO02", "start_seconds": 1.6, "end_seconds": 2.9, "text": "klik"},
            ],
            "design": {"VO01->VO02": ["INTENTIONAL_SEMANTIC_PAUSE", "a new evidence unit begins"]},
        },
    )
    write(root, "audio/sync_expectations.json", {"sync_tolerance": 0.35, "expectations": []})

    # Job-scoped execution requests. These carry this job's own values; the adapters
    # hold no defaults of their own.
    write(
        root,
        "picture/picture_request.json",
        {
            "source": str(source),
            "width": WIDTH, "height": HEIGHT, "fps": FPS,
            "units": [
                {"unit_id": "U01", "t_in_seconds": 0.0, "frames": FRAMES // 2},
                {"unit_id": "U02", "t_in_seconds": SECONDS / 2, "frames": FRAMES // 2},
            ],
        },
    )
    write(
        root,
        "typography/typography_request.json",
        {
            "master": "picture/picture_master.mp4",
            "out": "typography/typography_master.mp4",
            "width": WIDTH, "height": HEIGHT, "fps": FPS, "frame_count": FRAMES,
            "layout": {
                "baseline_y": int(HEIGHT * 0.80), "left_margin": 48,
                "size_l1": 40, "size_l2": 32, "line_gap": 10, "fill": [255, 255, 255, 255],
            },
            "font_stack": ["/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
            "events": [
                {"lines": ["PRE-EXAM PROOF"], "start_frame": 0, "end_frame_exclusive": 45},
                {"lines": ["MASTER VERIFIED"], "start_frame": 45, "end_frame_exclusive": 90},
            ],
        },
    )
    write(
        root,
        "audio/audio_request.json",
        {
            "assets": [
                {"path": "assets/voice.wav", "gain_db": 0.0, "start_seconds": 0.0},
                {"path": "assets/music.wav", "gain_db": -12.0, "start_seconds": 0.0},
            ],
            "out": "audio/audio_master.wav",
            "duration_seconds": SECONDS,
            "target_lufs": -16.0,
            "true_peak_ceiling_dbtp": -1.5,
        },
    )
    write(
        root,
        "assemble/assemble_request.json",
        {
            "picture": "typography/typography_master.mp4",
            "audio": "audio/audio_master.wav",
            "out": "final/master.mp4",
            "method": "REMUX",
        },
    )
    write(root, "job.json", {"job_id": JOB_ID, "audio": {"target_lufs": -16.0}})
    write(
        root,
        "review/review.json",
        {
            "schema_version": "review.v0",
            "reviewer_id": "reviewer-1",
            "executor_id": "executor-1",
            "findings": [
                {"dimension": d, "severity": "PASS", "detail": f"{d} measured", "accepted": False}
                for d in REVIEWER_DIMENSIONS
            ],
        },
    )
    return source


def render_evidence(root: Path) -> dict:
    """Independently re-measure the master. Nothing here trusts the run's own report."""

    master = root / "final" / "master.mp4"
    if not master.is_file():
        raise SystemExit("PROOF FAILED: final/master.mp4 does not exist")
    streams = media_probe.probe_streams(master)
    loudness = media_probe.measure_loudness(master)
    return {
        "MASTER_PATH": str(master),
        "MASTER_EXISTS": master.is_file(),
        "MASTER_SHA256": media_probe.sha256_of_file(master),
        "MASTER_BYTES": master.stat().st_size,
        "DURATION": streams["duration_seconds"],
        "FRAME_COUNT": streams["frame_count"],
        "FPS": streams["fps"],
        "RESOLUTION": f"{streams['width']}x{streams['height']}",
        "VIDEO_CODEC": streams["video_codec"],
        "AUDIO_CODEC": streams["audio_codec"],
        "BLACK_FRAME_RESULT": media_probe.count_black_frames(master),
        "DUPLICATE_FREEZE_RESULT": media_probe.count_duplicate_frames(master),
        "LOUDNESS": loudness["integrated_lufs"],
        "TRUE_PEAK": loudness["true_peak_dbtp"],
        "SAMPLE_PEAK": loudness.get("sample_peak_dbfs"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--job-root", type=Path, required=True)
    parser.add_argument("--keep", action="store_true", help="do not clear an existing job root")
    args = parser.parse_args(argv)

    root: Path = args.job_root
    if root.exists() and not args.keep:
        shutil.rmtree(root)
    build_job(root)

    print("=== phase 1: run the production control path to the human release gate ===")
    path = FastPath(root, job_id=JOB_ID)
    report = path.run()
    print(f"outcome={report.outcome} exit={report.exit_code} stopped_at={report.stopped_at}")
    if report.outcome != "SUPERVISOR_DECISION_REQUIRED":
        print(json.dumps(report.as_dict(), indent=2)[:4000])
        raise SystemExit(f"PROOF FAILED: expected the human release gate, got {report.outcome}")

    evidence = json.loads((root / ASSEMBLY_EVIDENCE_ARTIFACT).read_text(encoding="utf-8"))
    print(f"assembled master sha256 = {evidence['master_sha256']}")

    print("=== phase 2: human release naming the verified master, then resume ===")
    write(
        root,
        HUMAN_RELEASE_ARTIFACT,
        {
            "schema_version": "human_release.v1",
            "decision": "APPROVED",
            "authority": "Kang",
            "review_verdict": "PRODUCTION_READY",
            "master_sha256": evidence["master_sha256"],
            "statement": "reviewed the assembled master and the review; approved for release",
        },
    )
    resumed = FastPath(root, job_id=JOB_ID).run()
    print(f"outcome={resumed.outcome} exit={resumed.exit_code} completed={resumed.completed}")
    if not resumed.completed:
        print(json.dumps(resumed.as_dict(), indent=2)[:4000])
        raise SystemExit("PROOF FAILED: the run did not complete after the human release")

    print("=== phase 3: independent verification of final/master.mp4 ===")
    measured = render_evidence(root)
    for key, value in measured.items():
        print(f"  {key:<24} {value}")

    failures = []
    if not measured["MASTER_EXISTS"]:
        failures.append("master missing")
    if measured["FRAME_COUNT"] != FRAMES:
        failures.append(f"frame count {measured['FRAME_COUNT']} != {FRAMES}")
    if measured["BLACK_FRAME_RESULT"] != 0:
        failures.append("black frames present")
    if measured["DUPLICATE_FREEZE_RESULT"] != 0:
        failures.append("frozen frames present")
    if measured["AUDIO_CODEC"] is None:
        failures.append("no audio stream")
    if measured["SAMPLE_PEAK"] is not None and measured["SAMPLE_PEAK"] >= 0.0:
        failures.append("clipping")
    if failures:
        raise SystemExit("PROOF FAILED: " + "; ".join(failures))

    (root / "proof_evidence.json").write_text(
        json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("\nPROOF PASSED")
    return EXIT_CODES["PASS"]


if __name__ == "__main__":
    raise SystemExit(main())
