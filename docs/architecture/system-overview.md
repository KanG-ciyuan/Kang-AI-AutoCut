# System Overview

AI-AutoCut is a local-first AI professional video editing system. It turns
authorized source material into reviewable editing decisions and validated video
outputs while keeping human approval explicit.

## Long-term interaction model

```
User
  -> Codex Supervisor                (the only top-level supervisor)
  -> deterministic local production system
  -> execution backends / AI providers
  -> Reviewer                       (independent of the executor)
  -> Final MP4 + optional editable project
```

Codex owns intelligent decisions. The program owns deterministic execution.
Those two responsibilities are not mixed: no deterministic component decides
what a video should say, and no language model is trusted to report that a
deterministic step succeeded.

## Repository and data boundary

Git holds source code, tests, schemas, small licensed fixtures, documentation,
reproducible configuration templates, and verified decision records.

Raw media, generated media, renders, previews, caches, model weights, local
environments, credentials, and other large or regenerable runtime data stay
outside Git and are referenced by identity and hash only. See
`schemas/gold_manifest/` for the reference pattern and
`docs/architecture/operations.md` for the path configuration contract.

## Current maturity

**Gold Knowledge Baseline / Pre-Pipeline.**

Validated and inherited into this repository:

- Frame Boundary Kernel, Boundary Preflight v1, Material / Candidate Identity v1
- Editing Plan v1 (frozen at commit `the Editing Plan v1 freeze commit in canonical history`; the repository HEAD may be later)
- Editing Intelligence principles and reviewer dimensions
- DaVinci Resolve as the primary automated visual execution backend
- Jianying as the editable delivery / human takeover layer
- Shot-aware Typography policy
- Conservative Color Match strategy
- Audio Intelligence concepts and the continuous-voice-over rule
- Reviewer / Repair separation of duties

**Not** complete, and not claimed:

- automatic raw-media Shot Intelligence
- a ONE COMMAND end-to-end pipeline
- a production stage runner, resume/retry, artifact registry, or job queue
- full production automation

Given thirty raw videos, product information, a platform, a language, and a
target duration, this system **cannot** yet produce a final MP4 in one command.
The stages above were validated through human-driven experiment runs, not
through an automated pipeline.

## Design constraints

Local-first is a requirement, not a temporary state. Phase 1 prefers Python,
FFmpeg/FFprobe, the local filesystem, DaVinci Resolve integration, Jianying
editable delivery, external AI APIs, and deterministic orchestration.

Cloud infrastructure is deliberately absent: no object storage, no server
platform, no distributed workers, no microservices, no web dashboard, no user
accounts. A capability is only introduced when validated Gold work demonstrably
depends on it.

## Related documents

- `docs/architecture/supervisor-authority.md` — the Codex boundary
- `docs/architecture/backend-neutral-timeline.md` — one timeline, three backends
- `docs/architecture/operations.md` — path configuration and staging rules
- `docs/decisions/` — architecture decision records
- `docs/gold/filter-gold-v1.md` — the validated Gold result
