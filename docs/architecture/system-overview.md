# System Overview

Kang AI-AutoCut is a local-first AI commercial video editing system. It turns
authorized source material into reviewable editing decisions and validated video
outputs while keeping human approval explicit.

## Long-term interaction model

```
User
  -> Codex Supervisor                (the only top-level supervisor)
  -> deterministic local production system
  -> execution backends / AI providers
  -> Reviewer                       (independent of the executor)
  -> Human release gate             (a separate decision from the review)
  -> Final MP4 + optional editable project
```

Codex owns intelligent decisions. The program owns deterministic execution. Those
two responsibilities are not mixed: no deterministic component decides what a
video should say, and no language model is trusted to report that a deterministic
step succeeded.

## Production control path

The authoritative lifecycle is eight semantic stages, driven by
`src/ai_autocut/fast_path.py`:

```
1 PREPARE            source inventory and immutability
2 UNDERSTAND SHOTS   measured PTS -> CFR analysis grid, segmentation
3 PLAN THE EDIT      timeline range validation against observable action
4 FINISH THE PICTURE source-range extraction, measurement, decision
5 PLAN THE WORDS     narration coverage, then typography execution
6 BUILD THE AUDIO    program verification, then mixing and mastering
7 ASSEMBLE & MASTER  packaging adapter -> delivery master, measured QA
8 REVIEW & REPAIR    review contract -> derived verdict -> human release
```

Two properties of this path matter more than the stage list:

**Every required artifact has exactly one declared producer** — `AUTO`, `CODEX`,
`HUMAN` or `ADAPTER` — registered in `src/ai_autocut/producer_registry.py`. A
missing artifact stops the run with a **producer gate** naming who must act, on
what contract, and what must become true to resume. A gate is not a failure; it is
the system declining to invent a decision or claim work it did not do.

**No stage passes on a plan.** A stage that claims to have produced media must
produce it: the artifact is re-measured from the file on disk, and the delivery
master is verified by recomputing its digest, decoding its frames, and measuring
its audio. A JSON claim is never sufficient.

Outcomes are `PASS`, `BLOCKED`, `REVIEW_REQUIRED`, `SUPERVISOR_DECISION_REQUIRED`,
`REJECT` and `FAIL`, each with a documented process exit code. The control path
never resolves a gate, never repairs on its own, and never substitutes for the
Supervisor.

Per-capability wiring and readiness are recorded in
`docs/audit/production-chain-manifest.md`.

## The timebase invariant

Three coordinate domains are kept distinct, because conflating them corrupts
source ranges:

```
SOURCE        = measured PTS timestamp
ANALYSIS GRID = CFR grid derived from that measured timestamp
TIMELINE      = CFR frame grid
```

A raw decoded frame ordinal is never an analysis coordinate: for a variable frame
rate source the two diverge, and using the ordinal selects the wrong temporal
content. `src/ai_autocut/timebase_adapter.py` enforces this for every placement and
every source-range extraction.

## Repository and data boundary

Git holds source code, tests, schemas, small licensed fixtures, documentation,
reproducible configuration templates, and verified decision records.

Raw media, generated media, renders, previews, caches, model weights, local
environments, credentials, and other large or regenerable runtime data stay
outside Git and are referenced by identity and hash only. See
`schemas/gold_manifest/` for the reference pattern and
`docs/architecture/operations.md` for the path configuration contract.

## Current maturity

**Gated production control path — frozen pre-exam baseline.**

Present and validated:

- the eight-stage production control path, with resume, downstream invalidation,
  explicit producer gates and measured stage outputs
- Frame Boundary Kernel, Boundary Preflight v1, Material / Candidate Identity v1
- Editing Plan v1, the candidate pool contract, and the backend-neutral Executable
  Timeline contract
- Editing Intelligence principles and reviewer dimensions
- Shot-aware Typography policy, with job-scoped execution
- Conservative Color Match strategy
- Audio Intelligence concepts and the continuous-voice-over rule
- Reviewer / Repair separation of duties
- a real end-to-end execution proof that produces and independently verifies a
  delivery master

Frozen baseline: annotated tag `pre-third-sku-blind-v1`, targeting commit
`b65a73b53040bd1ff5defe25e624a28f623b6847`. Gate G.0 is `CLOSED_AND_FROZEN`; exam
validity is `PASS_WITH_EXPLICIT_PRODUCER_GATES`; the Third-SKU blind exam has not
started at this baseline.

**Not** present, and not claimed:

- an unattended one-command end-to-end pipeline
- an automated commercial reviewer
- generic backend compilers; `compile_for_backend` raises for every backend, and
  execution happens through job-scoped adapters instead
- an artifact registry or a job queue
- automatic picture measurement and product-protection evaluation, which are
  authored per job

Several capabilities are reachable but consume artifacts a person or agent authors
for each job. The manifest records each one and whether it is ready; `README.md`
summarizes the distinction, and both should be read before assuming a stage is
fully automated.

## Design constraints

Local-first is a requirement, not a temporary state. The system prefers Python,
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
- `docs/audit/execution-runbook.md` — how to run the control path and each boundary
- `docs/audit/production-chain-manifest.md` — per-capability wiring and readiness
- `docs/audit/gate-g0-history.md` — how the frozen baseline was reached
- `docs/decisions/` — architecture decision records
- `docs/gold/filter-gold-v1.md` — the validated Gold result
