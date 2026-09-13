# AI-AutoCut

AI-AutoCut is the canonical engineering repository for Kang's AI-assisted automatic precision-editing system. It is intended to turn authorized source material into reviewable editing plans, previews, and validated video outputs while keeping human approval and creative quality review explicit.

## Current stage

This repository contains the canonical baseline plus a minimal, dependency-free Frame Boundary Kernel and sanitized regression evidence inherited with explicit provenance. No Real Engineering Pilot has started.

## Canonical identity

- Project ID: `ai-autocut`
- Canonical repository: `<repo-root>`
- Default branch: `main`
- Runtime data root proposed for future use: `$AUTOCUT_WORKSPACE` (outside Git; not created by this bootstrap)

The machine-readable identity record is [PROJECT_IDENTITY.md](PROJECT_IDENTITY.md). Agent entry rules are in [AGENTS.md](AGENTS.md).

## Project boundaries

- **AdFlow is separate.** AdFlow is an independent historical Web/SaaS project. Any future connection must use a versioned file contract or API; the projects do not share engineering identity.
- **OpenMontage is separate.** OpenMontage is an independent third-party reference implementation and capability candidate, not this repository's source of truth. Code-level reuse requires interface, dependency, and license review first.
- **kang-agent-collab is separate.** AI-AutoCut may serve as a real pilot testbed for that collaboration Skill, but it does not contain or extend the Skill.
- **Historical editing work remains in place.** Existing `editing-intelligence-v1-phase1`, `filter-v4-*`, and related experiments are Historical Source / Inheritance Candidates. They have not been copied, moved, renamed, deleted, or committed here.

## Current inherited kernel

`src/ai_autocut/frame_boundary.py` provides exact frame conversion, end-exclusive source ranges, relative placement geometry, timeline-start protection, auditable candidate/source-boundary checks, and editor-independent read-back verification. Run its offline regression suite with:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

The historical sources and migration boundary are recorded in `docs/provenance/historical-inheritance-2026-09-13.md`. This kernel is a verified foundation only; it does not mean the Real Engineering Pilot has started.

## Offline boundary preflight

`src/ai_autocut/preflight.py` exposes the committed multi-segment boundary guard as an offline JSON entry point. Run it from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m src.ai_autocut.preflight INPUT.json
```

The input document uses `schema_version: "boundary_preflight.v1"` and carries canonical integer frames only — second-based fields such as `source_in_seconds` are rejected rather than rounded.

```json
{
  "schema_version": "boundary_preflight.v1",
  "segments": [
    {
      "segment_id": "S06",
      "candidate_id": "C16",
      "source_id": "SRC-B",
      "source_range": { "start_frame": 530, "end_frame_exclusive": 605 },
      "verified_safe_end_frame_exclusive": 605
    }
  ]
}
```

The process writes a deterministic JSON report to stdout and exits with:

- `0` — input valid, boundary preflight passed
- `1` — input format, schema, contract, or runtime error
- `2` — input valid, but the boundary guard found boundary business issues

A guard finding is reported as data on stdout, not as a program failure; a malformed document is reported on stderr and never as a guard finding.

## Repository and data boundary

Git should hold source code, tests, schemas, small licensed fixtures, documentation, reproducible configuration templates, and verified decision or validation records. Raw media, generated media, renders, previews, caches, model weights, local environments, credentials, and other large or regenerable runtime data stay outside Git.

Engineering validation proves technical properties such as reproducibility, decoding, duration, dimensions, audio tracks, and required overlays. It does not by itself prove that a video has passed Kang's content or creative quality review.
