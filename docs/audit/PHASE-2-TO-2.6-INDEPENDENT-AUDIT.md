# Phase 2 to 2.6 Independent Engineering Audit

Audit date: 2026-09-21  
Mode: read-only independent audit  
Repository: `<repo-root>`  
Expected baseline: `ee14d0cefcb42b53a85c591d8101c288d824583e`

Evidence labels used below:

- **CODE EVIDENCE** — observed in implementation or Git state.
- **TEST EVIDENCE** — independently executed test or focused reproduction.
- **LIVE VALIDATION EVIDENCE** — preserved runtime artifact from a live analyzer run.
- **INFERENCE** — engineering conclusion drawn from the evidence.
- **DSH REPORT CLAIM** — supplied claim, not treated as independent proof.

## 1. Executive Verdict

**Phase 3 readiness: `READY_AFTER_SMALL_FIX`.**  
**Commit readiness: `SMALL_FIX_THEN_COMMIT`.**

**CODE EVIDENCE:** The change set establishes a useful Phase 2 core: deterministic Candidate-window validation, reuse of the existing Candidate identity and Candidate Pool, an explicit analyzer request/response seam, fail-closed Product Fact support, and a structured Evidence successor that removes the need for Phase 3 to parse prose.

**TEST EVIDENCE:** The complete suite passed: `1594 passed, 1409 subtests passed in 126.89s`. Independent adversarial checks nevertheless exposed two correctness defects that the suite does not catch: a broken in-memory v1-to-v2 read path for analyzed entries, and directionally incorrect luminance range checks.

**CODE EVIDENCE:** The declared artifact graph and the executable shadow path are not fully aligned. The registry declares frame evidence as an analyzer input, but `run_candidate_evidence_stage` neither requires nor parses it. The normal CLI can generate Candidate Evidence from a recorded response or scripted agent without any frame manifest. The CLI also consumes caller-supplied measurement tables rather than proving that they came from the source through `TimebaseAdapter`.

**LIVE VALIDATION EVIDENCE:** None was available to this audit. No `LIVE_VALIDATION_REPORT.json`, `ANALYZER_BRIEF.json`, `candidate_frame_evidence.json`, or `candidate_evidence_truth.json` was found in the inspected project workspace. The harness code is inspectable and materially useful, but it is not proof that a real multimodal invocation occurred.

**INFERENCE:** The architecture is good enough to stop inventing Phase 2 infrastructure. It is not good enough to commit as-is because narrow correctness and truthfulness fixes remain. After those fixes, Phase 3 can begin against the v2 authoritative view without waiting for a generic vision-verification platform, production orchestration, or another model vendor.

## 2. Git / Scope Integrity

**CODE EVIDENCE:** The checked-out branch is `main`, and `HEAD` exactly matches `ee14d0cefcb42b53a85c591d8101c288d824583e`.

**CODE EVIDENCE:** Before this report was created, Git showed 27 Phase 2–2.6 paths: 9 modified tracked files and 18 untracked files. No files were staged. `git diff --check` was clean.

Tracked modifications observed:

- `README.md`
- `docs/contracts/candidate-evidence-v1.md`
- `docs/policies/editing-intelligence.md`
- `schemas/README.md`
- `src/ai_autocut/authoring.py`
- `src/ai_autocut/candidate_evidence.py`
- `src/ai_autocut/editing_intelligence.py`
- `src/ai_autocut/producer_registry.py`
- `tests/test_candidate_evidence.py`

Untracked implementation, contract, harness, fixture, and test paths observed:

- `docs/contracts/candidate-evidence-v2.md`
- `docs/contracts/candidate-extraction-and-analysis-v1.md`
- `scripts/phase25_live_validation.py`
- `src/ai_autocut/candidate_analysis.py`
- `src/ai_autocut/candidate_evidence_v2.py`
- `src/ai_autocut/candidate_extraction.py`
- `src/ai_autocut/candidate_frame_evidence.py`
- six `tests/fixtures/phase2_*` files
- five Phase 2/vNext test modules

**DSH REPORT CLAIM:** Approximately 27 files were changed or untracked.  
**CODE EVIDENCE:** This count was independently confirmed before adding this audit report.

**CODE EVIDENCE:** No changed path belongs to V01–V05 outputs, Production Records, Fourth SKU work, release machinery, Hook generation, Sequence Planning, or timeline compilation. No commit, push, merge, rebase, stash, reset, render, release, or production mutation was performed by this audit.

**CODE EVIDENCE:** Phase 1 semantics were changed only in the reported identifier validation sites and associated tests/docs. The corrected identifier character class is consistent with the already documented intent; no Phase 1 schema shape or support-class semantics changed.

## 3. Actual Architecture

The actual flow is:

1. A caller supplies `SourceMeasurement`, segmentation, identity catalog, and optionally Candidate-window proposals.
2. If proposals are absent, `candidate_extraction` can request them through the existing authoring-agent boundary; the deterministic segmentation helper is not automatically selected by the stage.
3. Every accepted proposal passes structural, timebase, segment-boundary, and timeline-range validation before an existing `CandidateIdentity` is created.
4. Accepted identities become the existing canonical `CandidatePool`; rejected proposals remain explicit rejection records.
5. `candidate_analysis` builds one request per pool, uses the existing `AuthoringAgent`/`CommandAuthoringAgent` seam, validates the response, and produces Candidate Evidence v1 or v2.
6. `candidate_frame_evidence` is a separate sampling/provenance facility. The live harness invokes it, but the generic analysis stage does not enforce it.

**CODE EVIDENCE:** There is one Candidate identity system: the pre-existing `CandidateIdentity` type is reused. There is one Candidate Pool: the pre-existing `CandidatePool` is reused and exact membership is checked.

**CODE EVIDENCE:** Semantic authority is mostly singular. The analyzer proposes observations; deterministic code controls identity, bounds, allowed Product Facts, support classes, response completeness, and contract validity. The optional pixel audit is a second truth signal, but it does not author Candidate Evidence.

**CODE EVIDENCE:** Legacy and vNext producer resolution are explicitly isolated. The legacy resolver refuses vNext producers and the vNext resolver refuses legacy producers. This is genuine registry isolation, not only a naming convention.

**CODE EVIDENCE:** The provider boundary is genuinely reusable because it extends the existing authoring request/agent abstraction rather than introducing another agent framework.

**CODE EVIDENCE:** There are, however, parallel upstream representations: new Candidate measurement and segmentation documents sit beside existing source-inventory, timebase, and shot-understanding artifacts. No production adapter makes those representations equivalent. The producer registry describes a more connected artifact graph than the executable shadow CLI currently implements.

**INFERENCE:** The core Candidate/Evidence design is coherent. The surrounding artifact choreography is not yet one executable system; it is a library path, a registry declaration, and a purpose-built validation harness that overlap without being identical.

## 4. Phase 2 Capability

### Genuinely implemented

**CODE EVIDENCE:** Proposal boundaries must resolve to measured frame/timestamp entries and pass deterministic chronology and timeline-range validation. There is no hidden range clamping or automatic correction.

**CODE EVIDENCE:** Invalid proposals receive explicit rejection codes. A missing analyzer entry becomes an explicit failure entry rather than silently removing a Candidate. Pool/evidence membership is validated.

**CODE EVIDENCE:** Product Facts are bounded by a caller-provided Claim Envelope. Unknown references and unsupported support classes fail closed. Confidence cannot promote an unsupported fact.

**CODE EVIDENCE:** Evidence records observations and possible commercial roles; they do not select order, keep/drop decisions, trim decisions, a Hook, or a sequence. No hidden Phase 3 planning decision was found in the Evidence contract.

**TEST EVIDENCE:** Strong tests cover real VFR measurement behavior, deterministic bounds, rejection codes, exact pool membership, fabricated fact references, support promotion, missing provider entries, frame-hash tampering, missing source frames, and legacy isolation.

### Implemented only behind a caller trust boundary

**CODE EVIDENCE:** The CLI parses a supplied measurement JSON. It checks shape and monotonicity but does not remeasure the referenced source, verify its bytes against the material identity, or prove the table was produced by `TimebaseAdapter`. Therefore “measured timebase” is an input assertion in the generic shadow path, not an independently enforced property.

**CODE EVIDENCE:** The segmentation helper can deterministically propose single-segment windows, but the main extraction stage does not automatically invoke it. The live harness uses manually specified Candidate-window proposals. A general semantic Candidate-proposal provider is not shipped.

**CODE EVIDENCE:** Analyzer action boundaries and semantic observations are model judgments. Structural validity is checked; correspondence to the actual pixels is not generically proven. This is acceptable for multimodal semantic judgment, but it must not be described as deterministic media truth.

**CODE EVIDENCE:** `proposals_from_segmentation` silently skips an out-of-range segment instead of emitting a rejection/skip record. Candidate disappearance is explicit for supplied analyzer proposals but not fully explicit in this deterministic helper.

**INFERENCE:** Phase 2 delivers a strong shadow contract and deterministic safety perimeter, not an autonomous Material-to-Evidence production pipeline. Phase 3 can consume its validated fixtures/API, but production integration later must remove or explicitly document the upstream trust boundary.

## 5. Live Validation Reality Check

Classification for the claim “the system can use a real multimodal model to turn real Candidate visuals into structured Candidate Evidence”:

**`INSUFFICIENT EVIDENCE`**

**DSH REPORT CLAIM:** A vision model analyzed real Candidate frame samples through the harness.

**CODE EVIDENCE:** The harness can generate purpose-built CFR media, identify and segment it, extract individual sampled frames, create contact sheets, record source frame numbers/timestamps/hashes, call an optional analyzer command, pass the returned JSON through the normal authoring seam via a prewritten agent, and run a separate audit.

**CODE EVIDENCE:** The Candidate-window proposals and expected pixel checks in this harness are hand-authored for the synthetic clips. The media are decoded files if the harness is run, but they are purpose-built validation footage rather than production SKU footage.

**LIVE VALIDATION EVIDENCE:** No persisted request, analyzer response, provider invocation record, frame manifest, truth report, or live-validation report was available. Code capable of invoking a command is not evidence that it did so.

**INFERENCE:** The harness design is useful but presently unverified as a historical live run. Even with preserved artifacts, the result would be `USEFUL BUT LIMITED EVIDENCE`, because the same implementation effort designed the synthetic scenes, expected checks, and evaluator. It would demonstrate seam compatibility and basic model usefulness, not independent semantic accuracy or general SKU transfer.

No independent vendor model is required before Phase 3. The minimum adequate closure is one replayable preserved run containing the exact sampled inputs, request/prompt version, raw analyzer response, response hash, validated output, and run report. A second provider would add breadth, not resolve the current missing-evidence problem.

## 6. Phase 2.6 Review

### A. Identifier regex

**CODE EVIDENCE:** The old character class `[A-Za-z0-9._:-_]` treated `:-_` as a range. It excluded the intended hyphen while admitting unintended ASCII punctuation such as `[`, `\\`, `]`, and `^`.

**CODE EVIDENCE:** The replacement `[A-Za-z0-9._:-]` is correct because the hyphen is last and therefore literal. Tests cover intended hyphens and formerly admitted punctuation.

**INFERENCE:** `candidate_evidence.v1` does not need a version bump. This is a validator bug fix that restores the already stated identifier semantics; it does not change the intended data contract.

### B. `candidate_evidence.v2`

**CODE EVIDENCE:** The v1 gap is real. `visible_action` and `visible_result` are free text, so Phase 3 would need brittle text parsing to distinguish “no action,” “not recorded,” problem state, result state, and state change.

**INFERENCE:** Structured observations are useful and a successor version is justified because v1 is explicitly frozen against field/vocabulary changes. A small authoritative projection for Phase 3 is preferable to parsing prose.

**CODE EVIDENCE:** v2 reuses the v1 parser for its base record, so it is not a full copy of v1 validation. It nevertheless adds substantial migration, compatibility-view, vocabulary, and serialization machinery for two new semantic dimensions.

**TEST EVIDENCE:** `read_candidate_evidence(v1_object)` is broken for any analyzed v1 entry. It wraps the v1 entry with `observations=None`, then the v2 invariant requires analyzed entries to have observations. JSON migration succeeds; the advertised shared object/JSON read path does not.

**INFERENCE:** Compatibility is partly premature because v1 has no demonstrated production corpus or deployed consumer. Keep JSON read compatibility if useful for fixtures, but do not grow a general migration framework. Either correctly define how analyzed v1 maps to an “unknown/not recorded” v2 observation or stop promising in-memory v1-object migration.

**INFERENCE:** The vocabulary mixes general cross-SKU concepts (`PROBLEM_STATE_VISIBLE`, `STATE_CHANGE_VISIBLE`, `PRODUCT_IDENTITY_VISIBLE`, `HUMAN_USE_VISIBLE`) with mechanism-specific concepts from the synthetic test (`CONTACT_VISIBLE`, `FLOW_VISIBLE`, `CLEAN_STATE_VISIBLE`). Phase 3 should treat the general layer as authoritative and specialized observations as advisory. Do not add a new enum member for each product mechanism.

### C. Contract safety versus evidence truth

**CODE EVIDENCE:** The frame manifest, exact source-frame reference, timestamp, and SHA-256 integrity checks are useful provenance. They can prove what images were presented and detect later mutation.

**CODE EVIDENCE:** `ProvenanceCheck`, luminance/range checks, and `EvidenceTruthStatus` are optional, job-authored validation machinery. They do not generically verify semantic Product Facts.

**TEST EVIDENCE:** A focused decreasing-luminance reproduction showed that a 200→100 sequence passes `INCREASE` and fails `DECREASE` in `_run_range_check`. The implementation uses `max - min`, losing temporal direction; the non-range mean-luminance `INCREASE` branch also uses an absolute delta.

**INFERENCE:** A hand-selected ROI and threshold can itself encode the expected answer. Passing such a check proves a pixel statistic changed, not that the commercial assertion is true. Calling the result globally `VERIFIED` overstates its scope.

Minimum machinery needed before Phase 3:

1. Candidate/pool/run-bound sampled-frame manifest.
2. Exact source-frame numbers or PTS plus image hashes.
3. Exact prompt/request version and raw response hash.
4. An explicit semantic status that means “model observed from these frames,” not “deterministically proven true.”

Contact sheets are a useful review convenience. Generic ROI/luminance verification and an expanding deterministic check taxonomy are not Phase 3 prerequisites.

## 7. Test Quality

**TEST EVIDENCE:** The full suite passed with `1594 passed, 1409 subtests passed`. Test count is not used as the verdict.

Genuinely strong protection includes:

- real decoded VFR source/timebase cases;
- deterministic boundary and invalid-range rejection;
- Candidate identity and exact pool membership;
- fail-closed Product Fact references and support classes;
- missing-provider-entry behavior;
- frame-source/hash/tamper failures;
- legacy/vNext resolver isolation.

Self-validation and design-locking risks include:

- fixtures authored to mirror the new schema and synthetic story;
- round-trip and serialization assertions that cannot test semantic truth;
- documentation substring tests;
- producer-registry assertions that do not prove runtime preconditions are enforced;
- a live harness outside the regular suite with no preserved run artifact;
- only dark-to-light direction examples, allowing reversed semantics to escape;
- a v1-to-v2 test shape that misses analyzed in-memory v1 objects.

**INFERENCE:** The tests protect substantial real safety behavior, not merely DSH's design. They also overstate integration completeness because registry declarations, serialization, and purpose-built fixtures pass while two public-path correctness errors and the absent frame-evidence runtime gate remain undetected.

## 8. Complexity / Overengineering

| Component | Classification | Reason |
|---|---|---|
| `candidate_extraction.py` | **KEEP** | Deterministic range validation, explicit rejection, canonical identity, and Pool construction are core editing safety. Do not add more proposal taxonomies. |
| `candidate_analysis.py` | **SIMPLIFY BEFORE COMMIT** | Keep the provider seam and fail-closed validation; align declared frame inputs with the executable path and stop presenting the registry as enforcement. |
| `candidate_frame_evidence.py` | **KEEP BUT DO NOT EXPAND** | Sampling, exact frame mapping, and hashes are valuable. Pixel-truth checks must remain optional validation support, not a new vision platform. |
| `candidate_evidence_v2.py` | **SIMPLIFY BEFORE COMMIT** | The structured gap is real, but the broken broad migration promise and vocabulary authority need narrowing. |
| Shadow-mode registry additions | **KEEP BUT DO NOT EXPAND** | Explicit isolation and artifacts are useful; another registry layer or more mode-specific duplicate producers is not. Runtime enforcement must not be inferred from metadata. |
| Live-validation script | **KEEP BUT DO NOT EXPAND** | It is a reproducible opt-in integration harness. It is not product runtime and should not accumulate a second orchestration architecture. |
| Frame audit machinery | **SIMPLIFY BEFORE COMMIT** | Preserve manifest/hash provenance. Narrow directional check semantics and truth-status wording; do not generalize luminance checks into semantic verification. |
| v1→v2 migration | **KEEP BUT DO NOT EXPAND** | JSON fixture compatibility is low-cost and useful. Do not build migration infrastructure absent a production v1 corpus; repair or remove the broken object-path promise. |
| Structured observation vocabulary | **SIMPLIFY BEFORE COMMIT** | Keep a small general Phase 3 vocabulary; mark mechanism-specific values advisory and resist per-SKU enum growth. |

**INFERENCE:** The project is near the point where more evidence infrastructure would reduce product velocity. The right next improvement is not another contract or verifier; it is using the existing structured evidence to make and evaluate Hook hypotheses.

## 9. Blockers

### BLOCKER BEFORE COMMIT

1. **Directional audit correctness.** Fix or remove the misleading `INCREASE`/`DECREASE` semantics in range and mean-luminance checks, and add reversed-sequence tests. A result labeled `VERIFIED` must not pass the opposite direction.
2. **v1-object read correctness.** Make `read_candidate_evidence(v1_object)` work for analyzed entries or explicitly reject/remove that supported input form. The public read-path claim and implementation must agree.
3. **Declared versus actual analyzer inputs.** Either make the shadow analyzer stage require and parse the frame manifest it declares, or revise the artifact graph and docs to state that frame evidence is harness-only. The present state creates false assurance that every analyzer saw traceable media.

These are bounded fixes. None requires a redesign of Candidate identity, Candidate Pool, the provider abstraction, or Evidence authoring.

## 10. Small Fixes

### SMALL FIX BEFORE COMMIT

1. Reconcile contradictory documentation: `editing-intelligence.md` simultaneously describes Candidate Evidence as contract-only, shadow-produced, and not generated anywhere. README live-validation wording must distinguish harness capability from preserved live proof.
2. Record out-of-range deterministic segmentation proposals as explicit skips/rejections rather than silently continuing.
3. Narrow the meaning of `EvidenceTruthStatus.VERIFIED` to the exact deterministic predicate checked, or rename/report it as a check result rather than global semantic truth.
4. Define the v2 authority rule: general observations may drive Phase 3; mechanism-specific values are optional descriptive evidence and must not become universal planning prerequisites.

## 11. Deferred Issues

### DEFER

1. Connect the shadow library to the existing source-inventory/timebase/shot-understanding artifacts so runtime measurements are derived from identified media rather than trusted caller tables. Required before production use, not before starting Phase 3 logic on validated inputs.
2. Add a general Candidate-proposal provider. Current interfaces and deterministic validator are sufficient for Phase 3 development; autonomous proposal quality is a later integration concern.
3. Preserve one replayable live analyzer run and evaluate it against non-synthetic SKU footage before claiming cross-SKU usefulness.
4. Decide whether the normal CLI should expose the v2 prompt/output version. The Python API already permits it, so this does not block Phase 3 implementation.
5. Consolidate new measurement/segmentation representations with existing artifact producers during production orchestration work; do not create another schema merely to bridge them.

## 12. Do Not Build / Do Not Expand

### DO NOT BUILD

- A general computer-vision truth-verification engine.
- A growing ROI/luminance/rule language for every semantic assertion.
- A per-SKU expansion of `observable_states` enums.
- Another Candidate identity, Candidate Pool, semantic-authority layer, agent framework, or vNext-only orchestrator.
- A generic migration platform for a v1 contract without a production corpus.
- More synthetic green-path fixtures as a substitute for preserved raw model responses and adversarial tests.
- A second model/vendor run merely for the appearance of independence before Phase 3.

### KEEP BUT DO NOT EXPAND

- The purpose-built live harness, until it has preserved one replayable run.
- Contact-sheet generation as a human-review convenience.
- The explicit legacy/vNext registry split.
- Optional deterministic checks whose result names remain strictly scoped to the pixel predicate tested.

## 13. Phase 3 Readiness

**Decision: `READY_AFTER_SMALL_FIX`.**

**CODE EVIDENCE:** Phase 3 has the essential information shape: stable Candidate identities, exact accepted Pool membership, allowed Product Fact references, support classes, confidence, visible action/result text, and v2 structured action/state observations.

**INFERENCE:** Hook Hypothesis Selection can start once the three commit blockers are closed. It does not require production source orchestration, a generic deterministic semantic verifier, or a second live model provider. Phase 3 must consume only validated Pool members, treat missing/not-recorded observations distinctly from no-action observations, and retain human review at the Hook selection boundary.

Phase 3 should not consume `VERIFIED` as blanket media truth. It may use contract-valid structured observations as model evidence tied to exact frames, with uncertainty preserved.

## 14. Commit Readiness

**Decision: `SMALL_FIX_THEN_COMMIT`.**

Exact minimum before commit:

1. Correct directional check semantics and add reverse-direction regression tests.
2. Correct or narrow the v1-object-to-v2 read contract and test an analyzed entry.
3. Align frame-evidence registry requirements with the actual shadow analyzer path.
4. Correct contradictory contract/live-validation documentation and truth-status wording.
5. Make deterministic segmentation skips observable.

No schema-wide rewrite is justified. Do not redesign Candidate Extraction, create a new provider abstraction, or delay Phase 3 for broader production integration.

## 15. Risks / Limitations

- **LIVE VALIDATION EVIDENCE:** No preserved live run was available, so this audit cannot verify the provider/model used, images actually transmitted, raw response, or reported live outcome.
- **CODE EVIDENCE:** Generic shadow execution can accept caller-authored measurements and can analyze without an enforced frame manifest. Boundary correctness is strong after input, but input provenance is not end-to-end.
- **INFERENCE:** Synthetic clips and product-specific observation enums may produce optimistic transfer expectations for new SKUs.
- **INFERENCE:** Claim Envelope safety prevents unauthorized support but does not independently prove that the envelope's asserted facts are true; its authority remains an upstream human/business-data responsibility.
- **TEST EVIDENCE:** Passing tests missed two public-path defects. Future acceptance should include adversarial direction, missing-artifact, mismatched-source, and cross-SKU cases rather than more round trips.
- **CODE EVIDENCE:** The current code volume is supportable only if Phase 2 now freezes. Expanding evidence governance before demonstrating better Hook and sequence choices would be disproportionate to the product goal.

Final audit status: `EDITING_INTELLIGENCE_VNEXT_PHASE_2_TO_2.6_INDEPENDENT_AUDIT_COMPLETE`
