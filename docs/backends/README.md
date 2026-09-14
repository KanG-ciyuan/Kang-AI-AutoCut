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
every backend rather than returning a partial result.

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
| Backend compilers | not implemented |
| Backend adapters and guards | not implemented here |

The backend *decisions* are recorded and the *contract* they must satisfy is
validated. The adapters that were exercised during the historical experiments
have not been migrated, and this repository does not claim them.
