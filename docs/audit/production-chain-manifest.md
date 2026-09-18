# Production Chain Manifest

> **The question this document answers:** *is this capability actually in the real
> production chain?*

The machine-readable form is
[`production-chain-manifest.json`](production-chain-manifest.json). Its invariants are
enforced by `tests/test_production_chain_manifest.py`, so this document cannot mark a
capability ready without the runtime behaviour to support it.

## Why this was rewritten

The Phase 2B manifest described readiness with a single flag, and independent inspection
rejected it: capabilities were marked `WIRED` and `third_sku_ready` when the runtime did
not support the claim. A capability could be *implemented* and still be unreachable.

This revision replaces the flag with **six independent dimensions**, and enforces the
relationships between them.

| Dimension | Means |
|---|---|
| `IMPLEMENTED` | the capability's logic exists in this repository |
| `VALIDATOR_WIRED` | a production path calls its validator |
| `PRODUCER_DEFINED` | its required artifact has exactly one registered producer |
| `EXECUTOR_AVAILABLE` | an executor ships here (false ⇒ a job-specific adapter must be supplied) |
| `MANUAL_GATE_DEFINED` | the manual/adapter step is explicit in the registry or the contracts |
| `END_TO_END_REACHABLE` | the fast path reaches this stage and it can PASS once its producers have acted |

## Enforced invariants

1. `WIRED` ⇒ `production_caller` is not null
2. `WIRED` ⇒ `git_tracked` is true
3. `third_sku_ready` ⇒ `END_TO_END_REACHABLE`
4. `third_sku_ready` ⇒ `EXECUTOR_AVAILABLE`
5. `third_sku_ready` ⇒ `PRODUCER_DEFINED`
6. `EXECUTOR_AVAILABLE == false` **and** `PRODUCER_DEFINED == true` ⇒ `MANUAL_GATE_DEFINED`
7. every P0 module has a non-null production caller
8. `implementation` path exists on disk
9. `stage` is one of the eight semantic stages

## Summary

| Stage | Capability | Status | Executor | E2E | Ready |
|---|---|---|---|---|---|
| PREPARE | source ingestion and immutability | `WIRED` | yes | yes | yes |
| PREPARE | material and candidate identity | `NOT_WIRED` | yes | no | no |
| UNDERSTAND SHOTS | placement authoring under the measured timebase | `WIRED` | yes | yes | yes |
| UNDERSTAND SHOTS | visual segmentation | `WIRED` | yes | yes | yes |
| UNDERSTAND SHOTS | semantic / action grouping | `NOT_WIRED` | yes | no | no |
| UNDERSTAND SHOTS | material capacity estimation | `NOT_WIRED` | no | no | no |
| PLAN THE EDIT | action-aware timeline range validation | `WIRED` | yes | yes | yes |
| PLAN THE EDIT | executable timeline contract | `NOT_WIRED` | no | no | no |
| FINISH THE PICTURE | source-range execution under the timebase invariant | `WIRED` | yes | yes | yes |
| FINISH THE PICTURE | read-only picture measurement | `PARTIALLY_WIRED` | **no** | yes | no |
| FINISH THE PICTURE | product authenticity protection | `PARTIALLY_WIRED` | **no** | yes | no |
| FINISH THE PICTURE | KEEP / REVIEW / CORRECT decision | `WIRED` | **no** | yes | no |
| FINISH THE PICTURE | picture execution | `JOB_SPECIFIC_ONLY` | **no** | no | no |
| PLAN THE WORDS | commercial narration coverage | `WIRED` | yes | yes | yes |
| PLAN THE WORDS | spoken duration validation | `NOT_WIRED` | yes | no | no |
| PLAN THE WORDS | typography policy validation | `NOT_WIRED` | no | no | no |
| PLAN THE WORDS | typography execution | `JOB_SPECIFIC_ONLY` | **no** | no | no |
| BUILD THE AUDIO | audio program verification (FIT / SYNC / RHYTHM) | `WIRED` | **no** | yes | no |
| BUILD THE AUDIO | audio plan contract | `NOT_WIRED` | no | no | no |
| BUILD THE AUDIO | audio rendering and mixing | `JOB_SPECIFIC_ONLY` | **no** | no | no |
| ASSEMBLE & MASTER | packaging, encode/remux, final master | `PARTIALLY_WIRED` | **no** | no | no |
| REVIEW & REPAIR | review contract and release verdict | `WIRED` | yes | yes | yes |
| REVIEW & REPAIR | targeted repair planning | `WIRED` | yes | yes | yes |
| REVIEW & REPAIR | human release gate | `WIRED` | yes | yes | yes |
| REVIEW & REPAIR | automated commercial reviewer | `NOT_WIRED` | no | no | no |
| REVIEW & REPAIR | prospective intervention ledger | `WIRED` | yes | yes | yes |

**Eight capabilities are ready. Eighteen are not.** Several are `WIRED` — their validator
runs in production — while still not being *ready*, because the executor that would act
on their output does not ship here. `KEEP / REVIEW / CORRECT decision` is the clearest
case: the decision runs, but nothing in this repository acts on a `CORRECT`.

## `full_chain_completable_today: false`

No executor ships for picture execution, typography execution, audio rendering or
assembly. Each is an **explicit adapter gate with a published contract**, so the chain is
reproducible but not completable without a job-specific adapter.

That is the honest headline. The run stops and names who must act; it does not pretend.

## Every artifact has a producer

`src/ai_autocut/producer_registry.py` assigns each required artifact exactly one producer:
`AUTO`, `CODEX`, `HUMAN` or `ADAPTER`. **No required artifact has NO PRODUCER or UNKNOWN
PRODUCER**, and that is asserted by test.

| Artifact | Producer | Type |
|---|---|---|
| `source_inventory.json` | `job_foundation.initialize_filter_job` | CODEX |
| `shots/placements.json` | placement author | CODEX |
| `edit/timeline_ranges.json` | edit planner | CODEX |
| `picture/measurements.json` | picture measurement adapter | ADAPTER |
| `picture/source_ranges.json` | source-range author | CODEX |
| `copy/commercial_units.json` | copy planner | CODEX |
| `audio/placement.json` | VO placement adapter | ADAPTER |
| `audio/sync_expectations.json` | sync expectation author | CODEX |
| `assemble/assembly_evidence.json` | packaging adapter | ADAPTER |
| `review/review.json` | reviewer | CODEX |
| `release/human_release.json` | human release authority | HUMAN |

A `CODEX` or `HUMAN` producer is legitimate. The goal of this work is reproducibility,
not autonomy. **Hidden manual reconstruction is what is not allowed**: every gate names
its input contract, output contract, procedure, evidence requirement, checkpoint and
ledger obligation.

## Execution contracts

Picture execution, typography execution, audio rendering and assembly each declare a
contract in `src/ai_autocut/execution_contracts.py`: producer type, required input,
expected output, procedure, validation, evidence, resume condition and ledger
obligation. A job-specific adapter is allowed; a hidden remembered command is not.

## The timebase invariant is global

```
SOURCE coordinate   = measured PTS timestamp in seconds
TIMELINE coordinate = CFR frame index
```

It governs **every** active production path that converts a source range into timeline
frames:

- **placement coordinates** (`assert_placement_timing`) — every placement must state a
  measured `t_in_seconds`; a coordinate derived from `frame_index / fps` is refused
  before segmentation runs;
- **source-range execution** (`execute` + `assert_range_coverage`) — a unit executed
  without passing through the adapter fails the run.

Two legacy paths are classified rather than left ambiguous:

- `local_preview.build_filter_graph` selects source frames with
  `trim=start_frame`, the exact Second SKU defect shape. It is **excluded from Third-SKU
  production** by an enforceable guard, and retained for local preview only.
- `shot_understanding` works in decoded frame indices, which is legitimate for
  segmentation. Its `duration_seconds` is **not** used as a production time coordinate.

## Outcomes and exit codes

| Outcome | Exit code | Meaning |
|---|---|---|
| `PASS` | 0 | the run completed |
| `BLOCKED` | 3 | a named producer must act |
| `REVIEW_REQUIRED` | 4 | a wired capability refused; a human decides |
| `SUPERVISOR_DECISION_REQUIRED` | 5 | a judgement or approval belongs to the Supervisor |
| `FAIL` | 6 | the stage ran and produced an unacceptable result |
| `REJECT` | 7 | a CRITICAL finding; returns to planning |

A reviewer verdict is **not** a release. `PRODUCTION_READY` produces
`SUPERVISOR_DECISION_REQUIRED` until a distinct `release/human_release.json` approves it.

## Known limitations carried here

- **DaVinci.** Not globally classified as unable to render. Resolve rendered five full
  timelines on 2026-09-15/16 with passing pixel validation. The recorded failure is
  specifically a **Fusion Text+ title bake**, never diagnosed and never re-tested.
- **Typography.** The historical SKU#1 `editorial_text_plan.json` is rejected by the
  frozen policy validator for nine unrelated extra keys. Recorded, not repaired.
- **Run-aware segmentation (C-01).** Unresolved; this work addresses the timebase
  *execution* aspect only.
- **Selected-range verification.** The project's own note stands: *"no automated check —
  needs vision."*

## Intervention baseline

The Second SKU baseline is frozen at **`PARTIALLY_VERIFIED`** in
[`sku2-intervention-baseline.json`](sku2-intervention-baseline.json), with a confidence
label on every field. Four values are `PARTIAL` and two are `NOT_VERIFIABLE`. Nothing
here reconstructs or upgrades them.

A Third SKU records interventions **prospectively**: the fast path writes a ledger entry
automatically when a gate halts a run, so the operator is not asked to remember. A count
that was not recorded when it occurred does not exist.

---

# Phase 6 — real execution closure

## Readiness now requires runtime proof

A capability may only claim `third_sku_ready` when its **real execution output is
produced and verified by the chain**. The four execution boundaries now ship as
job-scoped adapters in `src/ai_autocut/execution_adapters.py`, and each is marked
`Runtime-proven` with a note saying what was measured.

`full_chain_completable_today: true`. That claim is backed by the run below, not by an
assertion:

```
python3 scripts/run_pre_exam_proof.py --job-root /tmp/pre-exam-proof
```

## The proof run

| field | value |
|---|---|
| job_id | `pre-exam-execution-proof-v1` |
| master_path | `final/master.mp4` |
| frames | 90 |
| fps | 30.0 |
| resolution | 540x960 |
| video codec | h264 |
| audio codec | aac |
| black frames | 0 |
| duplicate/freeze frames | 0 |
| integrated loudness | -16.0 LUFS |
| true peak | -13.5 dBTP |

The sha256 is deliberately **not** written into this manifest. A hash recorded in a
tracked document is a claim; the proof records it in the job, and a reader reproduces it
by running the command above. `tests/test_real_master_proof.py` asserts that deleting the
master, or re-encoding it in place, makes verification fail.

## What is still not ready, and why

Ten capabilities remain `third_sku_ready: false`. Four of them —
`KEEP / REVIEW / CORRECT decision`, `read-only picture measurement`,
`product authenticity protection` and `audio program verification` — are
`END_TO_END_REACHABLE` but have no shipped executor for the artifact they consume, so a
human or Codex authors it for every job. That is a declared producer gate, not a hidden
one, but it is not automation and is not marked as ready.

`picture/measurements.json` is produced by a **CODEX** author today because no
measurement tool ships here. The picture stage still runs the real decision logic and
still requires a real picture artifact, so the chain is honest about which part is
automated and which part is authored.
