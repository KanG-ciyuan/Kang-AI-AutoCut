# ADR-0001 — Codex is the only top-level supervisor

- **Status:** Accepted
- **Date:** 2026-09-14
- **Supersedes:** the implicit assumption that any capable model could supervise

## Context

Production work is delegated across several models and agents. Each is capable
of generating plausible editing decisions. Without a single authority, the
system accumulates several partly-overlapping decision makers, and a release
becomes something any participant can declare.

The historical work already depended on a single supervising role that read job
state, chose which stage ran next, inspected evidence, and authorized repair and
release. That arrangement is the decision; this record makes it structural.

## Decision

**Codex is the only top-level supervisor.**

DeepSeek Harness, Claude Code, and comparable systems are engineering workers
with a bounded scope granted by the supervisor. A worker must not override a
supervisor decision, change architecture independently, declare a release
independently, or push production changes independently.

The division of labour:

| Responsibility | Owner |
|---|---|
| Intelligent decision | Codex supervisor |
| Deterministic execution | Program code |
| Independent judgement | Reviewer |
| Final acceptance | Human |

## Consequences

- Every production path must be reachable by a supervisor reading job state.
  A stage that only a human can trigger is a gap, not a design.
- Authority is enforced by refusal in code, not merely documented:
  `gold_manifest.assert_not_promoted`, `review.Review`'s reviewer/executor
  separation, and the `NotImplementedError` guards.
- A worker reporting success is not evidence. Deterministic verification is.

## What this forbids

- A second top-level supervisor.
- A worker promoting a Gold record to `FROZEN`.
- A worker declaring `PRODUCTION_READY`.
- A worker bypassing review by reviewing its own output.
