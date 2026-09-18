# Backends

All execution backends consume the single backend-neutral
`executable_timeline.v0` contract — see
`docs/architecture/backend-neutral-timeline.md`.

| Backend | Role | Decision | Compiler |
|---|---|---|---|
| FFmpeg | deterministic local render | — | **NOT_IMPLEMENTED** |
| DaVinci Resolve | primary automated visual execution | [ADR-0002](../decisions/ADR-0002-davinci-primary-visual-execution.md) | **NOT_IMPLEMENTED** |
| Jianying | editable delivery / human takeover | [ADR-0003](../decisions/ADR-0003-jianying-editable-delivery.md) | **NOT_IMPLEMENTED** |

No compiler is implemented. `executable_timeline.compile_for_backend` raises for
every backend rather than returning a partial result. That statement is still
accurate and is not weakened by anything below.

## A compiler is not an execution adapter

Two different things are easy to confuse here, and the distinction matters:

| | Generic backend compiler | Job-scoped execution adapter |
|---|---|---|
| Input | a frozen `executable_timeline.v0` document | that job's own request file |
| Scope | any job, any timeline | one job, stated geometry and values |
| Status | **NOT_IMPLEMENTED** for all three backends | **IMPLEMENTED** |
| Location | `executable_timeline.compile_for_backend` | `src/ai_autocut/execution_adapters.py` |

**A job-scoped execution adapter is not a compiler.** The adapters in
`execution_adapters.py` produce real media for one job — picture assembly,
typography compositing, audio mixing and mastering, and delivery packaging — using
local FFmpeg and Pillow. They read that job's own request file and ship no default
geometry, layout, font, loudness target or true-peak ceiling. They do **not**
consume the backend-neutral timeline contract, and adding one does not move a
backend compiler any closer to existing.

The consequence for a new backend is unchanged: until a compiler exists, a
`executable_timeline.v0` document still cannot be handed to FFmpeg, Resolve or
Jianying by this repository. What exists today is a separate, job-scoped route to a
delivery master, documented in `docs/audit/execution-runbook.md`.

## Shared verification rule

Every backend write is verified the same way:

```
Write -> Read-back -> Render -> Pixel Validation
```

An editor API's `success=true` is a claim, not evidence. This rule exists because
of a measured failure: a write reported success, read back as consistent, and
rendered one frame of pure black. Read-back alone would not have caught it; only
decoding the render did.

## Shared operation rule

Resolve-bound work routes through **ASCII-safe staging**, because Resolve Free
21.0.0 fails silently on non-ASCII I/O paths. See
`docs/architecture/operations.md`.

## What exists today

| Component | Status |
|---|---|
| Frame boundary and placement kernel | implemented, tested |
| Boundary preflight (offline JSON) | implemented, tested |
| Material / Candidate identity | implemented, tested |
| Editing Plan contract | frozen, implemented, tested |
| Executable Timeline contract | validated, tested |
| Backend compilers | **not implemented** |
| DaVinci / Jianying backend adapters and guards | not implemented here |
| Job-scoped execution adapters (FFmpeg, Pillow) | implemented |

The backend *decisions* are recorded and the *contract* they must satisfy is
validated. The DaVinci and Jianying adapters that were exercised during the
historical experiments have not been migrated, and this repository does not claim
them.

The job-scoped execution adapters are a separate route, described above: they
produce real media for one job and do not consume the backend-neutral timeline
contract.
