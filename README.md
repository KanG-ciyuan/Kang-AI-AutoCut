# AI-AutoCut

A **local-first AI professional video editing system**. It turns authorized
source material into reviewable editing decisions and validated video outputs,
while keeping human approval and creative quality review explicit.

## Current stage

**Gold Knowledge Baseline / Pre-Pipeline.**

This repository holds validated knowledge, frozen contracts, and offline tests.
It does **not** hold a working end-to-end production pipeline.

To state the concrete limit plainly:

> Given thirty raw videos, product information, a platform, a language, and a
> target duration, this system **cannot** yet produce a final MP4 in one command.

The individual capabilities below were validated through human-driven experiment
runs. They have not been assembled into an unattended pipeline.

## What has been validated

| Capability | State |
|---|---|
| Editing Intelligence principles and reviewer dimensions | policy recorded |
| Frame Boundary Kernel, Boundary Preflight, Material / Candidate Identity | implemented, tested |
| Editing Plan v1 | frozen at commit `the Editing Plan v1 freeze commit in canonical history` — the repository HEAD may be later |
| DaVinci Resolve as primary visual execution backend | decided ([ADR-0002](docs/decisions/ADR-0002-davinci-primary-visual-execution.md)) |
| Jianying editable delivery / human takeover | decided ([ADR-0003](docs/decisions/ADR-0003-jianying-editable-delivery.md)) |
| Conservative Color Match strategy | decided ([ADR-0005](docs/decisions/ADR-0005-conservative-color-match.md)) |
| Shot-aware Typography policy | policy validated, placement not implemented |
| Audio Intelligence concepts, continuous voice-over | policy validated |
| Reviewer / Repair separation of duties | contract validated |
| Filter Gold v1 result | recorded, `PASS_WITH_RECONCILIATION_REQUIRED` |

## What is not complete

- **automatic raw-media Shot Intelligence** — no extractor exists
- **a ONE COMMAND pipeline** — does not exist
- **Production Stage Runner** — not implemented
- **Resume / Retry** — not implemented
- **Artifact Registry** — not implemented; large staging data is cleaned up by hand
- **Multi-job Queue** — not implemented
- **Full Production Automation** — not achieved
- **backend compilers** (FFmpeg, DaVinci, Jianying) — `NOT_IMPLEMENTED`
- **automatic typography placement** — `NOT_IMPLEMENTED`

Nothing in this repository is production-ready, fully automated, or a
one-click professional editor. Those descriptions would be false today.

## Canonical identity

- Project ID: `ai-autocut`
- Default branch: `main`
- Runtime data root: logical role `AUTOCUT_WORKSPACE`
- Media root: logical role `AUTOCUT_MEDIA_ROOT`

No machine-bound absolute path appears in this repository. Every runtime
location resolves from an environment variable — see
[docs/architecture/operations.md](docs/architecture/operations.md) and
[config/examples/autocut.env.example](config/examples/autocut.env.example).

The machine-readable identity record is [PROJECT_IDENTITY.md](PROJECT_IDENTITY.md).
Agent entry rules are in [AGENTS.md](AGENTS.md).

## Running the offline tests

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

The suite is offline and dependency-free. It validates the frozen contracts, the
Gold manifest, and the path-hygiene rule.

## Offline boundary preflight

`src/ai_autocut/preflight.py` exposes the committed multi-segment boundary guard
as an offline JSON entry point:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m src.ai_autocut.preflight INPUT.json
```

Contract: [docs/contracts/boundary-preflight-v1.md](docs/contracts/boundary-preflight-v1.md).
Preflight accepts canonical integer frames only — second-based fields such as
`source_in_seconds` are rejected rather than rounded. Exit codes: `0` passed,
`1` contract or runtime error, `2` valid input with boundary business issues.

## Gold record

[schemas/gold_manifest/filter-gold-v1.json](schemas/gold_manifest/filter-gold-v1.json)
records the validated Gold result: a 518-frame, 30 fps, 17.266667 s vertical
edit, its selected master and hashes, and its reconciliation state.

The record stores a logical role, a bare filename, a SHA-256, and a storage
class — never a path and never the bytes. Large media never belongs in Git, so
that is a standing boundary rather than an open item. What is still open is
placement: the verified master has not yet been moved to the long-term Gold
media root. Narrative:
[docs/gold/filter-gold-v1.md](docs/gold/filter-gold-v1.md).

## Design constraints

Local-first is a requirement, not a temporary state. Phase 1 uses Python,
FFmpeg/FFprobe, the local filesystem, DaVinci Resolve, Jianying, external AI
APIs, and deterministic orchestration. Cloud infrastructure — object storage,
server platforms, distributed workers, dashboards, user accounts — is
deliberately absent. See [ADR-0007](docs/decisions/ADR-0007-local-first.md).

## Repository and data boundary

Git holds source code, tests, schemas, small licensed fixtures, documentation,
configuration templates, and verified decision records.

Raw media, generated media, renders, previews, caches, model weights, local
environments, credentials, and secrets stay outside Git, and no real secret
value appears in any tracked file.

Engineering validation proves technical properties — reproducibility, decoding,
duration, dimensions, audio tracks, overlays. It does **not** by itself prove
that a video has passed human content or creative review. Those remain separate
gates.

## Licence

**Apache-2.0.** The full licence text is at [LICENSE](LICENSE). Rationale, the
no-`NOTICE` decision, and the items still open for a later stage are recorded in
[LICENSE_DECISION_PENDING.md](LICENSE_DECISION_PENDING.md).
