# Kang AI-AutoCut

**Local-first Agentic AI Video Production System**

本地优先的 Agentic AI 视频生产系统

[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3-3776AB)](README.md#installation)
[![FFmpeg](https://img.shields.io/badge/ffmpeg-required-007808)](README.md#installation)
[![Local-first](https://img.shields.io/badge/local--first-yes-4c1)](docs/decisions/ADR-0007-local-first.md)
[![Agent-oriented](https://img.shields.io/badge/agent--oriented-yes-8957e5)](README.md#use-with-an-ai-agent)
[![Tests](https://img.shields.io/badge/tests-1062%20passing-brightgreen)](README.md#installation)
[![macOS](https://img.shields.io/badge/macOS-tested-000000)](README.md#installation)
[![Baseline](https://img.shields.io/badge/baseline-pre--third--SKU-orange)](README.md#frozen-baseline)

*Badges are static and describe the frozen baseline. This repository runs no CI
workflow, and the badge numbers are not live status.*

Kang AI-AutoCut is an Agent-oriented video production system, not an FFmpeg
stitching script. It takes authorized raw footage and a stated creative goal, and
drives the work through **eight production stages** — material understanding,
editing intelligence, narrative planning, timeline construction, picture
finishing, typography, audio, mastering, review and repair — with **human approval
as an explicit gate**.

It runs on your own machine. Your media stays on your disk. Every creative
decision is recorded, and the system refuses to report success it cannot measure.

> **Commercial-first, extensible by design.** Commercial advertising is the first
> production-validated workflow. The architecture is built to expand into broader
> creator and media workflows.

```
Raw Footage
    ↓
Understand  →  Plan  →  Edit
    ↓
Picture  ·  Typography  ·  Audio
    ↓
Assemble & Master
    ↓
Review  →  Repair  →  Human Approval
    ↓
Final Video
```

---

## Why Kang AI-AutoCut

Most AI video tools produce **one video, once**, inside a chat window. Re-running
them gives you a different video, and nothing about the process is inspectable.

Kang AI-AutoCut treats video production as an **engineering pipeline**:

| Ordinary AI video output | Kang AI-AutoCut |
|---|---|
| One-off result, hard to repeat | A reusable workflow you run again |
| Decisions live in a chat log | Every decision is a recorded artifact |
| Failure means starting over | Jobs resume from the stage that stopped |
| "It looks done" is the only check | Output is measured: frames, black frames, freezes, loudness, true peak, master hash |
| A model can silently skip a step | A stage **cannot pass without naming the capability it ran** |
| Human judgement is invisible | Human input happens at named gates, and is logged |
| Your footage is uploaded | Media never leaves the machine |

---

## What You Can Build

**Currently production-validated:**

- **Commercial advertising and e-commerce product video** — the first workflow
  taken end to end, including delivery-master verification.
- **Social-media short-form product content** — vertical, short-duration
  commercial edits, using the same eight stages.

**Direction the architecture is designed to extend into** — *not yet
production-validated*:

- creator and self-media video
- product demonstration and explainer content
- brand and campaign content
- other structured video-production workflows

The system is commercial-first today. Nothing here claims every video category is
already supported, and no content-mode framework exists yet.

---

## How It Works

### What you do

1. **Add raw footage** — point the system at a directory of source video.
2. **State the goal** — product, platform, language, target duration, and what the
   video must and must not claim.
3. **Let the Agent run the pipeline** — it works through the stages and stops when
   it needs you.
4. **Answer the gates** — approve copy, supply a missing artifact, or make a
   creative call.
5. **Approve the final video** — a named human releases the master. That release is
   a separate decision from the review, and it names the exact master it approves.

### What the system does

The production control path executes **eight semantic stages**:

| # | Stage | What happens |
|---|---|---|
| 1 | **PREPARE** | Source inventory with immutable per-file digests |
| 2 | **UNDERSTAND SHOTS** | Media is analysed; measured timestamps map onto a CFR analysis grid to find real visual segments |
| 3 | **PLAN THE EDIT** | Timeline ranges are validated against observable action — a cut that misses the onset or the result is refused |
| 4 | **FINISH THE PICTURE** | Source ranges extracted through the timebase invariant, measured, and a KEEP / REVIEW / CORRECT decision made per shot |
| 5 | **PLAN THE WORDS** | Narration coverage is checked **before** any paid voice work; then screen copy is rendered |
| 6 | **BUILD THE AUDIO** | FIT / SYNC / RHYTHM judged separately; then the mix is built and **measured** |
| 7 | **ASSEMBLE & MASTER** | Delivery master produced, then verified against the file itself |
| 8 | **REVIEW & REPAIR** | All review dimensions judged; verdict derived; human release gate |

### How the two views map

```
USER VIEW                          SYSTEM VIEW (8 stages)
─────────────────────────────      ──────────────────────────────────────
1  add raw footage            →    PREPARE
2  state the goal             →    (job manifest + brief)
3  understand the material    →    UNDERSTAND SHOTS
4  build the editing strategy →    PLAN THE EDIT
5  construct the timeline     →    PLAN THE EDIT
6  finish the picture         →    FINISH THE PICTURE
7  titles / copy / typography →    PLAN THE WORDS
8  voice / music / audio      →    BUILD THE AUDIO
9  assemble and master        →    ASSEMBLE & MASTER
10 review and repair          →    REVIEW & REPAIR
11 human approval             →    REVIEW & REPAIR (human release gate)
12 final video                →    delivered master
```

### Stages stop on purpose

When a required input is missing, the run **stops and names who must act**:

```
   Stage ──▶ [ PRODUCER GATE ] ──▶ Stage
                 │
                 ├─ which artifact is missing
                 ├─ which producer is responsible (AUTO / CODEX / HUMAN / ADAPTER)
                 ├─ the input and output contract
                 ├─ the procedure to follow
                 ├─ the evidence required
                 └─ what must become true to resume
```

**A gate is not a failure.** It is the system declining to invent a creative
decision, or to claim work it did not do. Some stages are automated; others
legitimately need an Agent, a provider adapter, or a person. The language
"generate or prepare", "Agent supplies", and "job-authored when required" is used
deliberately throughout this README.

---

## Current Capabilities

### Available and verified today

| Capability | Notes |
|---|---|
| Source ingestion and immutable inventory | per-file SHA-256, re-verified before use |
| VFR-safe media understanding | measured timestamps mapped to a CFR analysis grid |
| Visual segmentation | runs on the grid the engine actually decodes |
| Timeline range validation | refuses cuts that miss observable action |
| Source-range extraction | every range resolved from a measured timestamp |
| Picture execution | produces a real video artifact, re-measured afterwards |
| Narration coverage | runs before any paid voice generation |
| Typography rendering | real output from the job's own layout and fonts |
| Audio mixing and mastering | real mix, with measured loudness, true peak and clipping |
| Packaging and final master | `final/master.mp4` plus measured technical QA |
| Review contract and release verdict | every dimension judged once; verdict derived, not asserted |
| Targeted repair planning | scope-locked to the affected layer |
| Human release gate | a distinct decision naming the master it approves |
| Intervention ledger | written automatically whenever a gate halts a run |
| Resume and invalidation | resumes at the first incomplete stage; invalidating a stage re-opens everything downstream |
| Master integrity validation | digest recomputed; a deleted or altered master fails verification |

### Gated / job-authored

These run, but the artifact they consume is supplied per job — by an Agent, an
adapter, or a person:

| Capability | What is still supplied |
|---|---|
| Read-only picture measurement | no measurement tool ships in this repository |
| Product authenticity protection | same; its tolerance checks have not yet run on real data |
| KEEP / REVIEW / CORRECT decision | the decision runs; nothing here acts on a `CORRECT` |
| Audio program verification (FIT / SYNC / RHYTHM) | the voice placement it consumes |
| Voice / music generation | supplied by a provider adapter; **not built in** |

### Planned / extensible

Not implemented, and not claimed: an automated commercial reviewer, generic
backend compilers, an artifact registry, a job queue, an unattended one-command
runner, and broader content-mode workflows.

---

## Use with an AI Agent

Kang AI-AutoCut is designed to be **operated with an Agent** — a model that can
act on your filesystem and shell, not a chat-only model.

It is **not tied to any single Agent product**. Compatibility is capability-based:

| The Agent needs to be able to… | Why |
|---|---|
| read repository files | follow `README.md`, `PROJECT_IDENTITY.md`, `AGENTS.md` |
| run shell commands | FFmpeg, FFprobe, Python, the test suite |
| read and write local files | job state, artifacts, media staging |
| execute Python and FFmpeg workflows | every stage is local and deterministic |
| understand structured JSON artifacts | jobs, reviews, evidence, manifests |
| **stop at a Producer Gate** | and ask you, rather than guessing |
| respect the repository's boundaries | media outside Git, no secrets, no machine-bound paths |

Examples of capable Agents include Codex, DeepSeek Harness, Claude Code, and other
coding or computer-use Agents. **These are examples, not requirements or endorsed
integrations.**

**A chat-only model cannot operate this system.** Without filesystem and shell
access it cannot run the pipeline; it can only discuss it.

### Internal governance vs public compatibility

These are different things and both are true:

- **Internally**, the validated production workflow uses **Codex as the
  top-level Supervisor.** Creative authority sits there, and the system is built
  so no deterministic component decides what a video should say.
- **Publicly**, the repository aims to stay **Agent-agnostic** wherever the
  architecture allows. Nothing in the control path is hard-locked to one vendor's
  Agent.

---

## Agent Quick Start

Give a capable coding Agent the repository URL and a prompt like this:

```text
Install Kang AI-AutoCut on this computer using the repository instructions.

Repository: https://github.com/KanG-ciyuan/AI-AutoCut

Before changing anything:
1. Read README.md, PROJECT_IDENTITY.md and AGENTS.md.
2. Check the environment: Python, FFmpeg/FFprobe, and the Python packages the
   code actually imports.
3. Report what is missing. Do not install anything I have not approved.

Then:
4. Configure the local workspace and media root using only logical roles and
   environment variables. Keep media outside Git.
5. Never write an API key, token or credential into any tracked file, log or
   commit.
6. Run the repository self-tests before creating my first video job.

When we start a job:
7. Run the production control path and stop at every Producer Gate.
8. Ask me when a gate needs a human decision or creative approval.
9. Do not invent copy, art direction or claims on my behalf.
```

**What the Agent still has to do by hand.** Installation is *not* fully
automated today: there is no installer, no packaging manifest, and no declared
dependency lockfile. The Agent must inspect the environment, install prerequisites
you approve, and configure local paths. The README below lists exactly what is
verified, and the repository contains no `pyproject.toml` or `requirements.txt` —
that is a known documentation gap, not a hidden step.

---

## Installation

### Verified prerequisites

| Requirement | Status |
|---|---|
| **Python 3** | verified on 3.11.15. The repository declares no minimum version — treat that as a gap. |
| **FFmpeg and FFprobe** | required. Verified on ffmpeg/ffprobe 9.0.1. |
| **`numpy`** | required by the media-understanding module |
| **`Pillow`** | required by the typography execution adapter |
| **macOS** | verified on macOS arm64. Windows and Linux are **not** verified. |

No `pyproject.toml`, `setup.py`, or `requirements.txt` exists, so no version pins
are claimed here. Read the imports rather than trusting a lockfile that is not
there.

### Setup

```sh
git clone https://github.com/KanG-ciyuan/AI-AutoCut.git
cd AI-AutoCut

# Local configuration: resolves environment variables, never machine paths
cp config/examples/autocut.env.example .env.local
# edit .env.local: set AUTOCUT_MEDIA_ROOT and AUTOCUT_WORKSPACE
```

### Verify the installation

```sh
# Full offline regression — no network, no media required
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests

# End-to-end execution proof — builds its own media, produces a real master
python3 scripts/run_pre_exam_proof.py --job-root /tmp/pre-exam-proof
```

The proof is deliberately two-phase: it stops at the human release gate, writes
the release naming the **verified** master, then resumes to completion. It fails
if the master is deleted or altered.

### Your first job

```sh
# 1. Initialize a job (generic: any product, any source count)
python3 -m src.ai_autocut.job_foundation \
    --job-id my-first-job \
    --product-name 'My Product' \
    --source-root /path/to/footage \
    --workspace /path/to/job-workspace

# 2. Run the production control path
python3 -m src.ai_autocut.fast_path --job-root /path/to/job-workspace
```

It will stop at the first Producer Gate and tell you what is needed next.

Full instructions: [`docs/audit/execution-runbook.md`](docs/audit/execution-runbook.md).

---

## Agent & LLM Compatibility

Four different layers are easy to confuse. The system keeps them apart on purpose:

| Layer | What it is | In this project |
|---|---|---|
| **LLM** | a reasoning model | interchangeable, where a model is used at all |
| **Agent** | a model **plus tools** that can act on this repository | required to operate the system |
| **Provider** | an optional external service for generation or intelligence | pluggable; **not built in** |
| **Execution engine** | the deterministic local Python/FFmpeg pipeline | the only thing trusted to report that a step succeeded |

**No vendor lock-in by design.** The control path calls deterministic local
modules. Where a model or provider is involved, it is a producer that supplies an
artifact through a declared contract — so swapping the model or provider does not
change the pipeline.

**But compatibility is a capability question, not a brand question.** A model that
cannot read and write files, run shell commands, or respect a gate cannot operate
this system, however capable it is at reasoning.

---

## Audio & AI Provider Architecture

The current repository performs **local mixing and mastering** on audio assets the
job supplies. It deliberately does **not** call a voice, music or sound-effect
provider. Audio synthesis is not implemented here.

```
External Audio Provider   (future Adapter layer — NOT built in)
        ↓
  generated VO / BGM / SFX assets
        ↓
  job-local audio assets
        ↓
  Audio Program  →  local Mix  →  local Master
                     (measured: loudness, true peak, clipping)
```

**What exists today:** the `BUILD THE AUDIO` stage consumes job-local audio
assets, mixes them with FFmpeg against the job's own targets, and measures the
result. It refuses a mix whose sample peak reaches full scale.

**What does not exist:** any built-in provider integration. There is no
one-click voice generation, and this repository contains no provider client.

**Historical context, labelled accurately.** Voice-over was produced through
**MiniMax `speech-2.8-hd`** during earlier validated production work, and a
predecessor job manifest records **Doubao Seed Audio 1.0**. Both are
**historically evaluated experiments**, recorded in
[`docs/providers/audio-provider.md`](docs/providers/audio-provider.md) — not
current built-in production integrations. Their findings shaped the audio policy;
their clients are not part of this repository.

No key, token or credential value appears anywhere in this repository. Credentials
are referenced by environment variable name only.

---

## Commercial & Production Value

The value is in the architecture, not in a promise about outcomes:

- **A reusable workflow, not a one-off output.** Run the same production process
  on the next product instead of starting a new conversation.
- **Repeatable production.** The same stages, contracts and gates apply to every
  job, so process knowledge accumulates instead of evaporating.
- **Auditable creative decisions.** Every choice is an artifact with evidence, so
  a review can ask *why*, not just *what*.
- **Resumable jobs.** A job stopped by a gate or a failure continues from the
  stage that stopped, rather than from the beginning.
- **Deterministic execution.** Rendering, extraction and measurement are local
  and reproducible; a model's claim is never the evidence.
- **Source material is reusable.** Strong footage can serve multiple variants
  without re-shooting.
- **Structured review and repair.** Repair is targeted to the affected layer, not
  a full regeneration — so an approved edit is not silently replaced.
- **Measurable output validation.** Frame counts, black frames, frozen frames,
  loudness, true peak and the master digest are measured from the file.
- **Human intervention is visible.** The system logs when a gate opened, who
  acted, and when it resolved.
- **Local media ownership.** Footage never has to leave the machine.
- **Provider flexibility.** Generation sits behind a boundary, so a provider
  choice is replaceable.

What this does **not** claim: guaranteed quality, guaranteed conversion or
revenue outcomes, or a guaranteed reduction in editing time. Those are not
established by anything in this repository.

---

## Architecture

| Document | Contents |
|---|---|
| [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md) | interaction model, production control path, maturity |
| [`docs/architecture/supervisor-authority.md`](docs/architecture/supervisor-authority.md) | the Codex Supervisor boundary |
| [`docs/architecture/backend-neutral-timeline.md`](docs/architecture/backend-neutral-timeline.md) | one timeline, three backends |
| [`docs/architecture/operations.md`](docs/architecture/operations.md) | path roles, ASCII staging, verification rule |
| [`docs/contracts/`](docs/contracts/) | frozen contracts |
| [`docs/policies/`](docs/policies/) | editing, shot, typography, audio and review policy |
| [`docs/decisions/`](docs/decisions/) | architecture decision records |
| [`docs/audit/production-chain-manifest.md`](docs/audit/production-chain-manifest.md) | per-capability wiring and readiness |
| [`docs/audit/execution-runbook.md`](docs/audit/execution-runbook.md) | how to run every boundary |
| [`docs/audit/gate-g0-history.md`](docs/audit/gate-g0-history.md) | how the frozen baseline was reached |

### Repository layout

```
src/ai_autocut/          production code
  fast_path.py             the eight-stage control path
  producer_registry.py     every required artifact and its producer
  execution_contracts.py   the four execution boundaries
  execution_adapters.py    job-scoped picture / typography / audio / packaging
  timebase_adapter.py      the source-timestamp invariant
  media_probe.py           measured facts about a real media file
  ...                      contracts, policies, validators

tests/                   offline regression suite
schemas/                 frozen contracts and the Gold manifest
docs/                    architecture, contracts, policies, decisions, audits
scripts/                 the execution proof and the local-env wrapper
examples/                example job shape
config/examples/         configuration template
```

---

## Local-First Design

Local-first is a requirement, not a temporary state. The production control path
and all media processing run on the local machine, using Python, FFmpeg/FFprobe
and the local filesystem, with deterministic orchestration. Approved external AI
APIs may be used for selected intelligence or generation tasks; they are never the
control path. Cloud infrastructure — object storage, server platforms, distributed
workers, dashboards, user accounts — is deliberately absent. See
[ADR-0007](docs/decisions/ADR-0007-local-first.md).

No machine-bound absolute path appears in this repository. Every runtime location
is a logical role resolved from an environment variable; see
[`docs/architecture/operations.md`](docs/architecture/operations.md) and
[`config/examples/autocut.env.example`](config/examples/autocut.env.example).

---

## Current Status

| | |
|---|---|
| Frozen baseline | `pre-third-sku-blind-v1` → `b65a73b53040bd1ff5defe25e624a28f623b6847` |
| Freeze status | `CLOSED_AND_FROZEN` |
| Exam validity | `PASS_WITH_EXPLICIT_PRODUCER_GATES` |
| Next planned production phase | Third-SKU blind exam — **not started** |

A working **gated production control path** exists and has produced a real,
independently verified delivery master. It is not an unattended one-click editor,
and it does not claim to be.

---

## Known Limitations

- **Not an unattended one-command editor.** Producer gates stop the run by design,
  and some need a person or an Agent.
- **No automated commercial reviewer.** The review contract records a judgement; it
  does not produce one.
- **Picture measurement and product protection are job-authored.** No measurement
  tool ships here, and the protection tolerance checks have not yet run on real
  data — the gate has been proven to refuse, not to evaluate.
- **The `CORRECT` picture branch has never fired** in a production run.
- **No built-in audio provider.** Synthesis is not implemented; the pipeline
  consumes job-local assets.
- **Typography proves execution, not art direction.** No screen-copy hierarchy
  planner and no product-obstruction validation; a job supplies its own layout.
- **The execution proof uses generated local audio.** It proves the mixing and
  mastering path, not a real voice performance.
- **No artifact registry and no job queue.** Large staging data is cleaned up by
  hand.
- **No generic backend compilers.** `compile_for_backend` raises for every
  backend; execution happens through job-scoped adapters instead.
- **No declared dependency manifest.** No `pyproject.toml` or lockfile exists.
- **Verified on macOS only.** Windows and Linux are untested.
- **Tracked, unresolved:** run-aware visual segmentation (C-01) and automatic
  selected-range verification ("needs vision").

---

## Roadmap

1. **Run the Third-SKU blind exam against `pre-third-sku-blind-v1`.**
2. Measure final quality, producer-gate frequency, and human intervention.
3. Use the blind-run evidence to decide which remaining job-authored capabilities
   are worth automating next.

The frozen baseline is meant to be examined **as frozen**: no pre-exam automation
work is scheduled ahead of the blind run, so the exam measures the accepted system
rather than a system still moving under it.

---

## Frozen Baseline

```
tag             pre-third-sku-blind-v1
target commit   b65a73b53040bd1ff5defe25e624a28f623b6847
```

**What "frozen" means here:** a reproducible pre-exam baseline exists. The tagged
commit is the exact system that was audited and accepted, so the next exam run can
be compared against a known state rather than a memory of one.

**What it does not mean:** that the product is finished, that every capability is
automated, or that the system is production-complete. Documentation commits may
land on `main` after the tag; the tag itself does not move.

---

## Licence

**Apache-2.0.** The full licence text is at [LICENSE](LICENSE). Rationale, the
no-`NOTICE` decision, and items still open for a later stage are recorded in
[LICENSE_DECISION_PENDING.md](LICENSE_DECISION_PENDING.md).

---

## Canonical Identity

- Project ID: `ai-autocut`
- Default branch: `main`
- Runtime data root: logical role `AUTOCUT_WORKSPACE`
- Media root: logical role `AUTOCUT_MEDIA_ROOT`

The machine-readable identity record is
[PROJECT_IDENTITY.md](PROJECT_IDENTITY.md). Agent entry rules are in
[AGENTS.md](AGENTS.md).
