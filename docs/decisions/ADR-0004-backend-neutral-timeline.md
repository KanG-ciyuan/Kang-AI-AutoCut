# ADR-0004 — One backend-neutral Executable Timeline

- **Status:** Accepted
- **Date:** 2026-09-14

## Context

Three execution routes were validated: FFmpeg for deterministic local rendering,
DaVinci Resolve for automated visual execution, and Jianying for editable
delivery. Each has a different native representation — a filter graph, a project
object model, and an encrypted draft file.

If editing decisions were stored in any one of those dialects, the other two
would become lossy conversions, and the decision layer would inherit one
backend's limitations.

## Decision

Editing decisions are expressed once, in a backend-neutral, frame-canonical
**Executable Timeline**. The three backends are **compilers** that consume it.

```
Editing Plan -> Executable Timeline -> Backend Compiler
```

DaVinci JSON and Jianying JSON are never the contract. They are compiler
outputs.

## Consequences

- The contract is frame-canonical, with the frame rate as an exact rational.
  Seconds-based fields are contract errors, not values to round.
- Placement is strictly contiguous: no gap, no overlap. A gap is not a warning
  in an execution plan; it is an undefined region of the output.
- `source_id` is a logical identity, never a path. Machine-bound paths cannot
  enter the decision layer.
- Adding a backend adds a compiler. It does not change the contract.

## Status

The contract and its invariants are **VALIDATED**. Every compiler is
**NOT_IMPLEMENTED**, and `compile_for_backend` raises rather than returning a
plausible-looking timeline. Recording this honestly matters more than the
appearance of a finished adapter layer: a validated contract is real progress,
and pretending it ships compilers is not.

## What this forbids

- Storing editing decisions in a DaVinci or Jianying native format.
- Adding a backend by extending the contract with a backend-specific field.
- Returning a partial or best-effort compiled timeline.
