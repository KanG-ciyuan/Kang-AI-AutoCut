# Kang AI-AutoCut

**Local-first AI Commercial Video Editing System**

本地优先的 AI 电商广告自动剪辑系统

Kang AI-AutoCut turns authorized product footage into a reviewable commercial edit
and a validated delivery master. It runs entirely on a local machine, keeps every
creative judgement explicit, and refuses to report success it cannot measure.

## Project Status

| | |
|---|---|
| Frozen baseline | `pre-third-sku-blind-v1` → `b65a73b53040bd1ff5defe25e624a28f623b6847` |
| Freeze status | `CLOSED_AND_FROZEN` |
| Exam validity | `PASS_WITH_EXPLICIT_PRODUCER_GATES` |
| Next planned run | Third-SKU blind exam — **not started** |

A working **gated production control path** exists and has produced a real,
independently verified delivery master. It is not an unattended one-click editor,
and it does not claim to be.

## What It Does

A commercial video is a sequence of decisions: which shots carry the product, how
long each needs to be understood, what the voice must explain that the picture
cannot, and when silence is the right answer. Those decisions are usually made by
a person, per video.

This system makes them **explicit, recorded and auditable**:

- every stage of the production is a declared stage with a declared input;
- every input artifact has exactly one named producer;
- every stage either passes with measured evidence or stops and names who must act;
- nothing reaches delivery without a human release decision.

The result is a production process that can be inspected, resumed, and repeated —
rather than a conversation that produced a video once.

## What It Can Do Today

**Automatic and verified by the chain:**

| Capability | Evidence |
|---|---|
| Source ingestion and immutable inventory | per-file SHA-256, verified before use |
| Measured-PTS → CFR analysis-grid mapping | verified against a real variable-frame-rate source |
| Visual segmentation of raw media | runs on the analysis grid the engine decodes |
| Timeline range validation against observable action | refuses a cut that misses onset or result |
| Source-range extraction | every range resolved from a measured timestamp |
| Picture execution | produces a real video artifact, re-measured afterwards |
| Commercial narration coverage | runs **before** any paid voice generation |
| Typography execution | real rendered output from the job's own layout and fonts |
| Audio mixing and mastering | real mix with measured loudness, true peak and clipping |
| Packaging and final master | `final/master.mp4` plus measured technical QA |
| Review contract and release verdict | all dimensions judged once, verdict derived |
| Targeted repair planning | scope-locked to the affected layer |
| Human release gate | a distinct decision that names the master it approves |
| Intervention ledger | written automatically when a gate halts a run |

**Explicitly not automatic** — these run, but the artifact they consume is authored
per job (see *Explicit Producer Gates* and *Known Limitations*):

| Capability | What is still authored |
|---|---|
| Read-only picture measurement | no measurement tool ships in this repository |
| Product authenticity protection | same; its tolerance checks have not run on real data |
| KEEP / REVIEW / CORRECT decision | the decision runs; nothing here acts on a `CORRECT` |
| Audio program verification (FIT / SYNC / RHYTHM) | the VO placement it consumes is authored |

Also absent by design: an automated commercial reviewer, generic backend compilers,
an artifact registry, and a job queue.

## Explicit Producer Gates

This is the central design property, and the reason a run sometimes **stops**.

A **producer** is whoever creates a required input. Every artifact has exactly one,
of four declared kinds:

| Kind | Meaning |
|---|---|
| `AUTO` | the control path writes it |
| `CODEX` | a Supervisor/agent authors it under a stated contract |
| `HUMAN` | a person authors or approves it |
| `ADAPTER` | a job-scoped execution adapter produces it |

When a required artifact is missing, the run stops with a **producer gate** that
records: which artifact, which producer, the input contract, the output contract,
the procedure, the evidence required, and what must become true to resume.

> **A gate is not a failure.** It is the system declining to invent a creative
> decision, or to claim work it did not do. A run that stops at `BLOCKED` with a
> named producer is behaving correctly.

A `CODEX` or `HUMAN` producer is legitimate. The goal is reproducibility, not
autonomy. What is not allowed is a hidden manual step that nobody recorded.

## Production Flow

Eight semantic stages. A gate may stop the run between any two of them.

```
                    ┌─────────────────────────────────────────┐
                    │  Raw product footage + product identity  │
                    └────────────────────┬────────────────────┘
                                         │
   1  PREPARE              source inventory, immutable digests
                                         │
   2  UNDERSTAND SHOTS     measured PTS → CFR analysis grid
                                         │   segmentation, comprehension
   3  PLAN THE EDIT        range validation against observable action
                                         │
   4  FINISH THE PICTURE   source-range extraction, measurement, decision
                                         │   ── picture execution adapter ──
   5  PLAN THE WORDS       narration coverage  ──▶ before any paid voice
                                         │   ── typography executor ──
   6  BUILD THE AUDIO      program verification (FIT / SYNC / RHYTHM)
                                         │   ── audio render adapter ──
   7  ASSEMBLE & MASTER    ── packaging adapter ──▶  final/master.mp4
                                         │   measured QA: frames, black, freeze,
                                         │   loudness, true peak
   8  REVIEW & REPAIR      review contract ──▶ derived verdict
                                         │   ── HUMAN RELEASE (names the master) ──
                                         ▼
                              Delivery master, released

   ── ── ▶  a producer gate may stop the run at any stage boundary
```

The control path knows which stage comes next, which capability must run, and
whether execution may continue. It never resolves a gate, never repairs on its own,
and never substitutes for the Supervisor.

**Outcomes and exit codes:**

| Outcome | Exit | Meaning |
|---|---|---|
| `PASS` | 0 | stage completed with its artifacts |
| `BLOCKED` | 3 | a named producer must act |
| `REVIEW_REQUIRED` | 4 | a wired capability refused; a human decides |
| `SUPERVISOR_DECISION_REQUIRED` | 5 | a judgement or approval belongs to the Supervisor |
| `FAIL` | 6 | the stage ran and produced an unacceptable result |
| `REJECT` | 7 | a CRITICAL finding; returns to planning |

## Quick Verification

The suite is offline. `tests/` needs no network; the execution proof needs FFmpeg
and Pillow and generates its own media.

```sh
# Full regression — offline, no media required
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests

# End-to-end execution proof: produces and independently verifies a real master
python3 scripts/run_pre_exam_proof.py --job-root /tmp/pre-exam-proof

# Initialize a fresh commercial job (generic: no fixed file count, no built-in product)
python3 -m src.ai_autocut.job_foundation \
    --job-id <job-id> --product-name '<Product Name>' \
    --source-root <media-dir> --workspace <job-dir>

# Run the production control path
python3 -m src.ai_autocut.fast_path --job-root <job-dir>

# Run one execution boundary for a job
python3 -m src.ai_autocut.execution_adapters --job-root <job-dir> --boundary picture
```

The proof is deliberately two-phase, because that is the real workflow: it stops at
the human release gate, writes the release naming the **verified** master, then
resumes to completion. It fails if the master is deleted or altered.

Full instructions: [`docs/audit/execution-runbook.md`](docs/audit/execution-runbook.md).

## Architecture

| Document | Contents |
|---|---|
| [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md) | interaction model, maturity, design constraints |
| [`docs/architecture/supervisor-authority.md`](docs/architecture/supervisor-authority.md) | the Codex boundary |
| [`docs/architecture/backend-neutral-timeline.md`](docs/architecture/backend-neutral-timeline.md) | one timeline, three backends |
| [`docs/architecture/operations.md`](docs/architecture/operations.md) | path roles, ASCII staging, verification rule |
| [`docs/contracts/`](docs/contracts/) | frozen contracts |
| [`docs/policies/`](docs/policies/) | editing, shot, typography, audio, review policy |
| [`docs/decisions/`](docs/decisions/) | architecture decision records |
| [`docs/audit/production-chain-manifest.md`](docs/audit/production-chain-manifest.md) | per-capability wiring and readiness |
| [`docs/audit/execution-runbook.md`](docs/audit/execution-runbook.md) | how to run every boundary |
| [`docs/audit/gate-g0-history.md`](docs/audit/gate-g0-history.md) | how this baseline was reached |

## Local-First Design

Local-first is a requirement, not a temporary state. The system uses Python,
FFmpeg/FFprobe, the local filesystem, and external AI APIs, with deterministic
orchestration. Cloud infrastructure — object storage, server platforms, distributed
workers, dashboards, user accounts — is deliberately absent. See
[ADR-0007](docs/decisions/ADR-0007-local-first.md).

No machine-bound absolute path appears in this repository. Every runtime location is
a logical role resolved from an environment variable; see
[`docs/architecture/operations.md`](docs/architecture/operations.md) and
[`config/examples/autocut.env.example`](config/examples/autocut.env.example).

## Repository Structure

```
src/ai_autocut/     production code
  fast_path.py          the eight-stage control path
  producer_registry.py  every required artifact and its producer
  execution_contracts.py  the four execution boundaries
  execution_adapters.py   job-scoped picture / typography / audio / packaging
  timebase_adapter.py     the source-timestamp invariant
  media_probe.py          measured facts about a real media file
  ...                     contracts, policies and validators

tests/              offline regression suite
schemas/            frozen contracts and the Gold manifest
docs/               architecture, contracts, policies, decisions, audits
scripts/            the execution proof and the local-env wrapper
examples/           example job shape
config/examples/    configuration template
```

## Frozen Baseline

```
tag             pre-third-sku-blind-v1
target commit   b65a73b53040bd1ff5defe25e624a28f623b6847
```

**What "frozen" means here:** a reproducible pre-exam baseline exists. The tagged
commit is the exact system that was audited and accepted, so the next exam run can
be compared against a known state rather than a memory of one.

**What it does not mean:** that the product is finished, that every capability is
automated, or that the system is production-complete. Several capabilities remain
job-authored by design, and the limitation list below is the honest summary.

## Known Limitations

- **Not an unattended one-command editor.** Producer gates stop the run, by design,
  and some of them need a person or an agent.
- **No automated commercial reviewer.** The review contract records a judgement; it
  does not produce one.
- **Picture measurement and product protection are job-authored.** No measurement
  tool ships here, and the protection tolerance checks have not yet run on real
  data — the gate has been proven to refuse, not to evaluate.
- **The `CORRECT` branch has never fired** in a production run.
- **Typography proves execution, not art direction.** There is no screen-copy
  hierarchy planner and no product-obstruction validation; a job supplies its own
  layout and fonts.
- **The execution proof uses generated local audio.** Real voice performance and
  music generation are not proven by it — it proves the mixing and mastering path.
- **No artifact registry and no job queue.** Large staging data is still cleaned up
  by hand.
- **Generic backend compilers are not implemented.** `compile_for_backend` raises
  for every backend; execution happens through job-scoped adapters instead.
- **Tracked, unresolved:** run-aware visual segmentation (C-01) and automatic
  selected-range verification ("needs vision").

## Roadmap

1. Close the remaining job-authored artifacts behind shipped adapters, starting with
   picture measurement.
2. Run the Third-SKU blind exam against this frozen baseline.
3. Decide, on that evidence, which limitations are worth automating next.

## Licence

**Apache-2.0.** The full licence text is at [LICENSE](LICENSE). Rationale, the
no-`NOTICE` decision, and items still open for a later stage are recorded in
[LICENSE_DECISION_PENDING.md](LICENSE_DECISION_PENDING.md).

## Canonical Identity

- Project ID: `ai-autocut`
- Default branch: `main`
- Runtime data root: logical role `AUTOCUT_WORKSPACE`
- Media root: logical role `AUTOCUT_MEDIA_ROOT`

The machine-readable identity record is
[PROJECT_IDENTITY.md](PROJECT_IDENTITY.md). Agent entry rules are in
[AGENTS.md](AGENTS.md).
