# ADR-0007 — Local-first, no cloud infrastructure in Phase 1

- **Status:** Accepted
- **Date:** 2026-09-14

## Context

A system that edits video on one machine invites a familiar expansion: object
storage for media, a database for job state, a queue for workers, a dashboard
for visibility, accounts for access. Each addition is individually reasonable
and collectively fatal to a Phase 1 that has not yet finished its core pipeline.

The validated work ran entirely on a local machine with local media, local
editors, and external AI APIs called directly. No capability depended on cloud
infrastructure.

## Decision

**Phase 1 is local-first.** The stack prefers:

- Python
- FFmpeg / FFprobe
- the local filesystem
- DaVinci Resolve integration
- Jianying editable delivery
- external AI APIs
- deterministic orchestration

SQLite, OpenCV, and PyAV are acceptable **only when a validated need appears**.

## Explicitly not introduced for "future extensibility"

Cloudflare, D1, R2, VPS, Kubernetes, distributed workers, microservices, a large
vector database, a graph database, a web dashboard, user accounts, cloud object
storage, or a server platform.

A capability is introduced when validated Gold work demonstrably depends on it —
not because it might be useful later.

## Consequences

- Job state, artifacts, and media live on the local filesystem under
  `AUTOCUT_WORKSPACE` and `AUTOCUT_MEDIA_ROOT`.
- The repository stays portable: no committed path assumes one machine's layout
  (see `docs/architecture/operations.md`).
- Media never enters Git. Gold records identity and hashes instead.
- Losing the local workspace loses derived media, which is why Gold records
  capture identity and hashes rather than relying on a path being remembered.

## Consequences deliberately accepted

- No multi-machine execution, and no resilience to a machine failing.
- Concurrency is bounded by one machine.
- Cleanup of large staging data is manual until an artifact registry exists.

These are accepted costs, not oversights.

## What this forbids

- Adding cloud infrastructure to solve a Phase 1 problem.
- Introducing a database, queue, or service because the architecture "will need
  it eventually".
- Making the canonical repository depend on a networked service to build or test.
