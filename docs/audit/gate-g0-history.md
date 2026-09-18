# Gate G.0 — Engineering History

**Purpose.** This is an index of how the frozen pre-exam baseline was reached. It
exists so the development history does not have to live in `README.md`.

It is a summary, not an evidence dump. The per-capability record is
[`production-chain-manifest.md`](production-chain-manifest.md); the operational
instructions are in [`execution-runbook.md`](execution-runbook.md).

## Final accepted baseline

```
tag             pre-third-sku-blind-v1
target commit   b65a73b53040bd1ff5defe25e624a28f623b6847
gate status     CLOSED_AND_FROZEN
exam validity   PASS_WITH_EXPLICIT_PRODUCER_GATES
third SKU       NOT STARTED
```

## Why the gate existed

Two real SKUs had been produced, but an audit found a gap between *capability
existing* and *capability being used*: several modules were implemented, had
passing unit tests, and were never called by any production path. Two independent
inspections then rejected the first attempted baseline as not yet exam-valid.

The gate's purpose was therefore narrow: make a Third-SKU blind run **reproducible**
and **honest** before running it. It was explicitly not a push toward full autonomy.

## Progression

| Phase | What changed |
|---|---|
| G.0 / 1 | Read-only audit. Found the production engine was untracked in Git: HEAD did not describe the system that produced the second SKU. Verified the working tree against the SKU#2 freeze hashes. |
| G.0 / 2A | Design only. Classification of all 28 changed files, an 8-stage lifecycle proposal, and a minimal wiring plan. |
| G.0 / 2B | Baseline recovery commit, then the first wiring: the eight-stage control path, the timebase adapter, contract round-trip repairs, a typography adapter boundary, and an intervention ledger. |
| G.0 / 4 | **Independent inspection rejected the baseline.** It was a validation harness around preconstructed artifacts: artifacts had undefined producers, resume was not real, halted runs exited zero, review was unreachable, and the manifest overstated readiness. Corrected with an artifact producer registry, real resume and downstream invalidation, controlled outcomes and exit codes, a human release gate, and a six-dimension readiness model. |
| G.0 / 6 | **A second independent rejection.** Timebase enforcement was not global, invalidation was not coherent, execution had no real evidence, and assembly could be declared complete against a file that was never created. Corrected with measured master verification, job-scoped execution adapters, and a real proof job. |
| G.0 / 8 | **A third independent rejection, narrowed to two blockers.** The VFR analysis-grid mapping used a raw decoded ordinal where a CFR analysis frame was required; and the registered initialization procedure still routed every fresh job through the Filter-only initializer. Both corrected, each with a real regression. |
| G.0 / 9 | Final acceptance. Tagged and frozen. |

## The two defects that mattered most

**Assembly could be declared complete against nothing.** Verification accepted a
JSON document without opening a file, so a nonexistent path, a fabricated SHA-256,
a fabricated frame count and fabricated audio measurements all passed. It now
recomputes the digest, decodes the frames, reconciles the count against upstream
evidence, detects black and frozen frames, and measures loudness and true peak.

**A measured timestamp was validated and then ignored.** The variable-frame-rate
fix checked the measured PTS and then selected frames with the raw decoded ordinal.
For a source whose first second runs at 10 fps and whose second runs at 30 fps, the
1.0 s content sits at raw index 10 but at analysis frame 30 — so the analysis ran on
the content at 0.333 s. The mapping now derives analysis coordinates from the
measured timestamp on the declared CFR grid, and a real VFR regression asserts the
*temporal content* that was analysed.

## Standing outcomes of the gate

- The engine is in Git, and `HEAD` describes the system that ran.
- Every required artifact has exactly one declared producer.
- A run stops with a named producer rather than inventing a decision.
- Stages that claim to produce media must produce it and be re-measured.
- Readiness requires runtime proof, not implementation.

## What the gate did not do

It did not make the system autonomous. Picture measurement, product-protection
evaluation and audio placement remain authored per job; the `CORRECT` picture
branch has never fired; there is no automated reviewer, no backend compiler, no
artifact registry and no job queue. Those are recorded as limitations rather than
closed, and the manifest lists each capability's true status.
