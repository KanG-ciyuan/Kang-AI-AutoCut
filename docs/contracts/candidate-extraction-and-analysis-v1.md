# Candidate Extraction and Analysis v1

- **Contracts:** `candidate_window_proposal.v1`, `candidate_analysis_request.v1`,
  `candidate_analysis_response.v1`, `claim_envelope.v1`, `candidate_extraction.v1`,
  `candidate_measurements.v1`, `candidate_segmentations.v1`
- **Produced contract:** `candidate_evidence.v1` (Phase 1, unchanged)
- **Implementation:** `src/ai_autocut/candidate_extraction.py`,
  `src/ai_autocut/candidate_analysis.py`
- **Frame evidence:** `analysis/candidate_frame_evidence.json` (+ `analysis/frames/`),
  implemented in `src/ai_autocut/candidate_frame_evidence.py`
- **Live validation harness:** `scripts/phase25_live_validation.py` (opt-in, never
  part of the offline suite). It is the only producer of frame evidence; the analysis
  stage neither requires nor parses that artifact, so Candidate Evidence can be
  produced without one.
- **Canonical fixtures:** `tests/fixtures/phase2_identity_catalog_v1.json`,
  `phase2_candidate_measurements_v1.json`, `phase2_candidate_segmentations_v1.json`,
  `phase2_candidate_window_proposal_v1.json`, `phase2_claim_envelope_v1.json`,
  `phase2_candidate_analysis_response_v1.json`
- **Mode:** `VNEXT_SHADOW` (see `producer_registry.py`)
- **Status:** implemented and tested in shadow. **Not wired into production.**

## What this stage is, and where it stops

```
source_inventory
  -> measured PTS / timebase
  -> visual segmentation
  -> candidate-window proposal        (analyzer, through the authoring seam)
  -> Candidate Identity               (identity.py, unchanged)
  -> Candidate Pool                   (candidate_pool.v1, unchanged)
  -> structured multimodal analysis   (provider adapter, through the same seam)
  -> candidate_evidence.v1            <- this stage ends here
```

Nothing downstream consumes Candidate Evidence. No hook is generated or selected,
no sequence is planned, no timeline is compiled, and no render happens. There is
no production wiring: the eight-stage fast path neither writes nor requires any
artifact in this document.

## What a Candidate is

A Candidate is a source window that can carry an observable action, an observable
result, a product state, or a commercial evidence opportunity. It is **not a scene
cut**: a cut is where the picture changes, a Candidate is where something can be
shown and judged.

Only four window rules are allowed in v1.

| Rule | Allowed when | Deterministic check |
| --- | --- | --- |
| `SINGLE_SEGMENT` | one complete visual segment | the window equals its segment exactly |
| `ADJACENT_MERGE` | one observable action continues across the join | at most 4 adjacent segments; the window equals their union; the action's onset is in the first segment, its result is in the last, and it straddles an internal boundary |
| `ACTION_SAFE_WINDOW` | the shortest window that still shows the action and its result | the window equals exactly `[action_onset, result_end_exclusive)` |
| `SHORTER_ACTION_WINDOW` | a shorter window that still reads completely | inside its declared parent window, strictly shorter, and still passing the action check |

A shorter window is a **new Candidate Identity**. Nothing in this stage trims an
existing Candidate, and `editing_plan.v1` gains no trim field: a shorter interval
has to exist as a distinct Candidate first.

## The analyzer proposes, the boundary validator disposes

A window may be proposed by an analyzer. It has no authority over the outcome.
Every proposal is checked against the registered Material, the measured
timestamps, the visual segmentation, the action chronology, and the identity
contract. Nothing guesses a "close enough" time.

Rejection is an outcome, not a deletion. Every proposal ends as either an accepted
Candidate Identity or a recorded rejection code:

`UNREGISTERED_MATERIAL`, `MEASURED_TIMEBASE_UNAVAILABLE`, `UNKNOWN_STREAM`,
`EMPTY_RANGE`, `OUT_OF_MATERIAL_BOUNDS`, `UNKNOWN_SEGMENT`,
`SEGMENT_NOT_ADJACENT`, `MERGE_TOO_WIDE`, `WINDOW_NOT_A_SEGMENT`,
`WINDOW_NOT_THE_MERGE`, `PARENT_SEGMENT_REQUIRED`, `NOT_SHORTER_THAN_PARENT`,
`ACTION_REQUIRED`, `ACTION_CHRONOLOGY_INVALID`, `ACTION_ONSET_EXCLUDED`,
`RESULT_TRUNCATED`, `ACTION_NOT_CROSSING_BOUNDARY`, `WINDOW_NOT_ACTION_SAFE`,
`DUPLICATE_IDENTITY`, `IDENTITY_CONTRACT_REJECTED`.

Proposal order is meaningful and is preserved: two proposals for the same window
produce one Candidate, and the first proposal wins.

## Measured time, not assumed time

Coverage, bounds, and duration come from the source's measured presentation
timestamps, never from `frame_index / fps`. On a variable-frame-rate source those
differ, and the difference is a defect this repository has already paid for once.

`SourceMeasurement` obtains its table from `timebase_adapter.TimebaseAdapter`, and
its duration rule matches `measured_duration_seconds` exactly — asserted on real
media by test, so the two cannot drift apart. A Candidate window records
`t_in_seconds`, the real `duration_seconds`, and `variable_frame_rate`, and states
its coordinate system (`SOURCE_PTS_SECONDS`) so a reader never has to guess which
clock a frame number is on.

## The one question an analyzer may answer

The task supplies a **Claim Envelope**. The analyzer may answer

> "what evidence do these frames provide for the claims in this envelope?"

and may not answer

> "here is something else the product could claim".

A commercial claim must name a Product Fact the envelope permits. A claim against
a fact the envelope does not contain is refused, and the Candidate is recorded as
`ANALYSIS_FAILED` with that reason — the pipeline does not quietly delete the
offending claim, and it does not quietly accept it either. A visual observation
with no matching Product Fact is exactly what the refusal is for: under the v1
`candidate_evidence.v1` contract, a claim is a commercial claim, so a purely
visual observation with no permitted fact behind it cannot be upgraded into claim
support. That is recorded as a `CONTRACT_GAP_CANDIDATE` rather than patched by
widening the schema.

## Failure is visible, never a disappearance

Every Pool member has exactly one entry in the produced evidence:

- the analyzer's analysis,
- the analyzer's own `UNKNOWN` or `ANALYSIS_FAILED` answer, kept as reported, or
- a pipeline-recorded failure with a reason.

Two failure levels are distinguished. A **response-level** failure means the answer
cannot be attributed to the request at all — wrong schema, a different run, Pool,
prompt contract, or request revision, an unrequested Candidate, or a field the core
contract does not define. Every Candidate is then recorded `ANALYSIS_FAILED` with
that reason. An **entry-level** failure — a malformed payload, a provider-specific
key inside an entry, or a claim outside the envelope — fails only that Candidate;
the others survive, and the counters expose the pattern.

A provider that never answers, answers with unreadable JSON, times out, or raises
is a provider failure: every Candidate is still present and still says so.

## Analyzer prompt contract

The instruction an analyzer answers under is versioned, and the version it declares
must match the version the request was rendered under:

| Version | What it adds | Produces |
| --- | --- | --- |
| `candidate_evidence_prompt.v1` | the original Phase 2 question, kept so recorded answers stay replayable | `candidate_evidence.v1` |
| `candidate_evidence_prompt.v2` | the evidence ladder, the prohibitions, and the frame-coordinate rule (Phase 2.5) | `candidate_evidence.v1` |
| `candidate_evidence_prompt.v3` | the structured observation fields and their rules (Phase 2.6) | `candidate_evidence.v2` |

The prompt contract a request is rendered under decides which evidence version the
stage validates, so a v1 answer cannot satisfy a v3 request, and an analyzer that
emits the structured fields cannot be accepted under the older contract.

`candidate_evidence_prompt.v2` requires the analyzer to answer in exactly one of five
registers — `OBSERVATION`, `DIRECT`, `CONTEXTUAL`, `INFERRED`, `UNSUPPORTED` — and
prohibits: introducing a Product Fact that is not in the envelope; upgrading inference
or context to `DIRECT` because confidence is high; claiming a result that is not on
screen; assuming the product works from how it looks; treating a beauty or hero shot as
efficacy evidence; inventing or interpolating source frame numbers; and silently omitting
a Candidate. It states the exact entry shape the answer must take.

The request carries the chosen contract's text in its `question` field, so the analyzer
receives its instructions through the same document it is answering, and the recorded
`prompt_contract_version` in the evidence is the contract that was actually used.

## Frame evidence: how exact source coordinates are established

**Scope.** Frame evidence is produced by the opt-in live-validation harness, not by
the shadow stage. The stage does not require it, and the producer registry no longer
declares it as an analyzer input: declaring a runtime requirement that the code does
not enforce would imply that every analyzer saw traceable media, which is not true of
a recorded or scripted answer. When the harness is used, the manifest is what makes a
run's inputs reviewable.



An analyzer must never invent source coordinates. Before it is asked anything, the
pipeline decodes each Candidate's own window, samples evenly spaced frames **including
both endpoints** (`EVEN_INCLUSIVE_ENDPOINTS`), writes each as an image named by its exact
decoded source frame, records that frame's measured timestamp and SHA-256, and composes a
contact sheet per Candidate whose tile order is recorded in the manifest.

```
analysis/candidate_frame_evidence.json      the manifest: image -> source frame -> PTS -> sha256
analysis/frames/<candidate_id>/f000020.png  one image per sampled frame
analysis/frames/<candidate_id>/contact_sheet.png
```

No frame-index filter is applied to a raw source: the window is decoded and frames are
sliced out by decoded index. That is legitimate for *analysis* while a frame index remains
forbidden as a *timing* coordinate, which is the distinction the repository already draws.

## Frame-provenance audit

After the answer comes back, `audit_frame_provenance` asks three questions and fails
closed on any of them:

1. **Integrity** — do the images still hash to what the manifest recorded?
2. **Coordinate honesty** — does every `DIRECT` provenance range lie inside its Candidate,
   and did the analyzer actually see a frame inside it? A citation of frames nobody was
   shown is a citation the answer cannot rest on.
3. **Substance** — for each expectation the *job* declared, do the cited pixels really show
   the change claimed? The expectation is written by the run, never inferred from the
   model's wording, and `ROI_LUMINANCE_RANGE` sweeps the whole cited window and reports the
   extreme frames, so a verdict cannot depend on which two frames somebody picked.

A check that no clip can satisfy fails, by construction, which is what makes the audit a
test rather than a formality.

**What a result means.** Each kind answers one question and no more.
`MEAN_LUMINANCE_CHANGE` compares two named frames in temporal order, so it is
directional. `ROI_LUMINANCE_SPAN` sweeps a window and reports a magnitude, so it
refuses `INCREASE`/`DECREASE` outright: a magnitude has no temporal order and cannot
answer a direction. A passing result is scoped to its own pixel predicate — a
hand-picked region and threshold can encode the expected answer — so the status is
reported as `CHECKS_PASSED` / `CHECKS_FAILED` / `NOT_VERIFIED`, never as semantic or
commercial truth.

## Provider boundary

The core depends on the request/response contract and on the existing authoring
seam (`authoring.py`) — never on a provider SDK. The same seam serves a real
adapter, a deterministic test provider, and a recorded answer:

| Role | Implementation |
| --- | --- |
| real analyzer | `authoring.CommandAuthoringAgent` running a job-scoped adapter |
| an agent or human answering between runs | `authoring.PrewrittenAuthoringAgent` (asserts the artifact exists; validates nothing itself) |
| deterministic test provider | `authoring.ScriptedAuthoringAgent` (existing) |
| recorded answer | a response fixture passed as `response_document` |
| refusing provider | `authoring.NullAuthoringAgent` |

The request is always written to the job root first, so an answer is bound to a
request that exists on disk, and a recorded answer stays replayable against it.

No provider-specific field can enter the core contract: an unexpected key inside
an entry fails that entry, and an unexpected key at the top level fails the
response.

## Artifacts

All paths are declared in `producer_registry.py` under `VNEXT_SHADOW`.

| Artifact | Producer | Contract |
| --- | --- | --- |
| `analysis/candidate_window_proposal.json` | analyzer adapter | `candidate_window_proposal.v1` |
| `analysis/candidate_extraction.json` | stage (AUTO) | `candidate_extraction.v1` |
| `analysis/candidate_pool.json` | stage (AUTO) | `candidate_pool.v1` (unchanged) |
| `analysis/candidate_frame_evidence.json` | **live-validation harness (opt-in)**, never a stage output | `candidate_frame_evidence.v1` |
| `analysis/candidate_analysis_request.json` | stage (AUTO) | `candidate_analysis_request.v1` |
| `analysis/candidate_analysis_response.json` | analyzer adapter | `candidate_analysis_response.v1` |
| `analysis/candidate_evidence.json` | stage (AUTO) | `candidate_evidence.v1` (unchanged) |

Run the shadow stage with:

```
python3 -m src.ai_autocut.candidate_analysis --job-root <PATH> --stage propose \
    --measurements <measured.json> --segmentations <segments.json> \
    --catalog <material_candidate_identity.json> [--proposals <proposals.json>]

python3 -m src.ai_autocut.candidate_analysis --job-root <PATH> --stage analyze \
    --measurements <measured.json> --segmentations <segments.json> \
    --catalog <material_candidate_identity.json> --envelope <claim_envelope.json> \
    [--response <recorded-response.json> | --agent-command '<COMMAND>']
```

Exit codes follow the repository convention: `0` complete, `3` blocked, `6` failed.

## Mode isolation

`LEGACY` and `VNEXT_SHADOW` have separate registries on purpose. The legacy
resolver (`producer_registry.producer_for`) still raises for every shadow artifact,
no legacy stage declares one as an input or output, and the shadow resolver refuses
a legacy artifact. A legacy run therefore cannot start depending on Candidate
Evidence by accident, and a shadow run cannot write a frozen production contract.

## What Phase 3 may consume

Phase 3 receives `authoritative_evidence_view(evidence)`, which carries structured
fields only. Hook Planning may branch on:

- `action_presence` — including `NO_ACTION`, which is now a positive statement;
- `observable_states` — the finite visual vocabulary;
- `claims` — Product-Fact-bound support classes with frame provenance;
- `provenance`, `action_evidence`, `confidence`, `evidence_type`, and the enumerated
  observation fields.

It may **not** derive planning truth from `rationale`, `observations.visible_action`,
`observations.visible_result`, `claims[].note`, or `risks[].note`. Those fields carry
`NON_AUTHORITATIVE_EXPLANATORY_TEXT`: they may explain a structured decision and may
never create one. A required premise that exists only in prose is
`NOT_MACHINE_SUPPORTED` until the contract represents it structurally, and
`check_machine_support` is the gate that says so — from structured truth, never from
a sentence.

## Not implemented here

No hook generation or selection, no sequence planning, no semantic dedup decision,
no `WHY_KEEP`/`WHY_TRIM`, no timeline compilation, no copy, audio, render, or
assembly, no approval or release, no provider ensemble or fallback, no vector
database, and no second identity system, Pool, or agent framework.
