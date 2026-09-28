# Commercial Copy v1 Contract

- **Schema:** `commercial_copy.v1`
- **Implementation:** `src/ai_autocut/commercial_copy.py`
- **Schema file:** `schemas/commercial_copy/commercial_copy.v1.schema.json`
- **Contract demonstration:** `examples/strategy/indonesia-faucet-filter-copy-{a,b,c}.json`, `…-copy-result-first-blocked.json`
- **Artifact path:** `strategy/commercial_copy.json`
- **Producer:** none registered — nothing in production writes this artifact
- **Status:** `CONTRACT_ONLY` / `NOT_WIRED` (`IMPLEMENTATION`, `WIRING_STATUS`)
- **Precedent:** `planning_evidence.v1`, `commercial_strategy.v1`, `commercial_intelligence.v1`
- **Upstream of:** TTS / Audio / Timeline / Editing
- **Downstream of:** a **selected variant** of `commercial_strategy.v1`
- **Skill specification:** `docs/skills/commercial-copy-v1.md`

## Purpose and boundary

Authoring and localization must also follow the HARD RULES and STYLE RULES in
`docs/skills/commercial-copy-v1.md`, section 9. Those guide the human/Agent author;
they add no schema fields, runtime generator or automatic quality judgement. A passing
structure comparison or semantic flag check does not establish compelling sales copy.

Commercial Copy answers one question: *given that this variant has already decided how to
sell, how should this video actually express it?* It does not decide how the video should be
sold, and it may not change the strategy it binds.

```text
Commercial Intelligence
        ↓
Selected Commercial Strategy
        ↓
Commercial Copy                      ← this contract
        ↓
TTS / Audio / Timeline / Editing
```

It is not a campaign plan, not a timeline, not a TTS script, not a voice decision, not a
mixing decision and not a release decision.

## Two layers, one artifact

| Layer | Field | What it is |
|---|---|---|
| **Semantic Copy Plan** | `segments[].semantic_intent` | language-independent: what this segment is **allowed to mean** |
| **Localized Spoken Copy** | `segments[].localized.line` | the natural wording in the target language |

Localization controls **how to say it**, never **what may be said**. A localised line may not
add a product fact, a claim, a promised result, a compatibility promise or a
consumer-research conclusion that the semantic intent did not already carry.

## Data model

```json
{
  "schema_version": "commercial_copy.v1",
  "copy_id": "<token>",
  "context": { "market": "...", "language": "...",
               "platform": "...", "platform_source": "DECLARED|DEFAULTED|UNSPECIFIED" },
  "strategy": { "ref": "...", "sha256": "<sha256>", "variant_id": "A" },
  "boundaries": { "product_facts": { "ref": "...", "sha256": "..." },
                  "visual_evidence_boundary": { "ref": "...", "sha256": "..." } },
  "segments": [
    { "segment_id": "S01", "copy_job": "...", "delivery": "SPEECH|DESIGNED_SILENCE",
      "semantic_intent": "...", "claim_refs": [ "..." ], "evidence_refs": [ "..." ],
      "budget": { "target_seconds": 2.2, "acceptable_min_seconds": 1.8,
                  "acceptable_max_seconds": 2.6 },
      "localized": null, "designed_silence": null }
  ],
  "semantic_back_check": { "findings": [ "..." ] },
  "blocking": [ "..." ],
  "status": "READY|BLOCKED",
  "provenance": { "authoring_mode": "AGENT_AUTHORED|HUMAN_AUTHORED",
                  "authored_by": { "actor": "...", "producer_id": "..." },
                  "skill": { "name": "commercial-copy", "version": "1.0.0" },
                  "validation": { "validator": "commercial_copy.validate_commercial_copy" },
                  "based_on": [ "..." ] }
}
```

## Strategy binding: the copy executes, it does not re-decide

`validate_commercial_copy(copy, strategy)` binds the document to the strategy it claims to
execute, and refuses:

- a different **boundary revision** than the strategy's own — one boundary, not a fork;
- a **variant** the strategy does not declare;
- a different **market** than the strategy was declared for;
- a **claim** the selected variant did not select (the copy may not add one);
- a **claim** the claim boundary does not permit: `FORBIDDEN` or an unresolved
  `CONDITIONAL` claim is refused outright;
- a **fact** the product-facts binding does not permit;
- **evidence** the boundary does not declare, or declares `ABSENT`;
- a claim used without citing the evidence that claim rests on.

If the selected strategy cannot be executed, the copy is `BLOCKED`. It is never quietly
replaced by a different strategy.

## Semantic back-check

After localization there is a formal back-check: did the localised line add a claim, expand
one, drop a qualifier, turn a possibility into a certainty, or invent a product fact?

**This is a recorded judgement, not natural language understanding.** Python cannot read
Indonesian, and this contract does not pretend it can. What it enforces mechanically is:

- exactly one finding per `SPEECH` segment — no segment goes unaudited;
- **no** finding for `DESIGNED_SILENCE`, because there is no line to check;
- the `verdict` is **derived** from the five flags and verified against the stored value, so
  a finding cannot admit an exceedance (`expands_claim: true`) and still read `PASS`;
- a `FAIL` must state what exceeded the intent.

An artifact therefore cannot record "this line added a claim" and still be `READY`.

The boundary case the flags exist for:

```text
SEMANTIC INTENT   the filter attaches at the tap outlet
LOCALIZED (wrong) suitable for every tap, and very easy to install
→ expands_claim: true, adds_claim: true → FAIL
```

## Speech budget, not timing

`budget` is a **soft information budget**: a target and an acceptable range, so the copy
layer knows roughly how much it can say. It carries no frame counts, no placement and no
duration authority. Exact placement belongs to the timeline and audio stages.

Every number in this contract is a duration in seconds named `*_seconds`. Any other numeric
value anywhere in the document is refused, which is what keeps a fabricated precision out of
an artifact that has no performance data behind it.

## Designed silence is not an empty track

`DESIGNED_SILENCE` means **there is no voice-over in that segment** — not that the track is
silent. The moment is carried by the visual, so:

- the segment must carry `designed_silence.reason` (why no voice) and
  `designed_silence.bed_note` (what continues under it);
- it must cite the **evidence** that carries it (`evidence_refs` is required);
- it must **not** carry a localised line — a missing line is not a defect here;
- this contract has **no way to express muting a track**, because that is not what designed
  silence means. Mixing is not this layer's decision.

## Status: derived, not asserted

`status` is `READY` only when `blocking` is empty **and** no back-check finding failed.
Otherwise it is `BLOCKED`. The stored value is verified against that derivation, so an
artifact cannot assert a status its own contents contradict. A `READY` copy must declare at
least one segment; `segments` may be empty only when the copy is `BLOCKED`.

A blocking condition must name its reason code, its reason, what is missing and which
upstream area has to move (`return_to` ∈ `COMMERCIAL_INTELLIGENCE`, `COMMERCIAL_STRATEGY`,
`PRODUCT_FACTS`, `VISUAL_EVIDENCE`, `CLAIM_BOUNDARY`). When it names a claim, the boundaries
must actually not permit it, and any missing item the derivation produces must be declared:
a permitted claim is not a reason to block, and a blockage may not understate what it needs.
**A blockage is never resolved by this layer inventing evidence.**

## Provenance

`provenance` records the authoring mode, who authored it, the Skill and version it was
authored under, the validator it records, and the revisions it was authored against. There is
deliberately **no `SYSTEM_GENERATED` authoring mode**, because no system generation
capability exists at this baseline: the artifact records Agent or human authorship and does
not claim otherwise. Naming a validator is not proof of validation; a consumer must actually
run `validate_commercial_copy`.

## Status: contract only, not wired

`IMPLEMENTATION = "CONTRACT_ONLY"`, `WIRING_STATUS = "NOT_WIRED"`.

- **No producer is registered.** `producer_registry.producer_for("strategy/commercial_copy.json")`
  raises `NO PRODUCER`, and `mode_of` reports no owner.
- **No writer and no reader.** No stage requires it; no module reads it.
- **The production chain is untouched.** `fast_path.py`, the execution adapters and the
  other contracts are unchanged by this work.

## Recorded limitations

1. The back-check is a recorded judgement, not a detector. A dishonest `PASS` is not caught
   by this contract; what it cannot do is admit an exceedance and still read `PASS`.
2. This contract does not read files. `{ref, sha256}` proves which revision a document was
   written against, not that the bytes still match.
3. The **claim boundary has no standalone artifact** at this baseline: it travels with the
   bound strategy, and this contract binds the strategy revision instead. A future revision
   could bind a shared claim-boundary artifact once one exists.
4. The strategy binding in the demonstration fixtures names the demonstration strategy file
   by its real path and SHA-256, so the binding is verifiable. The two boundary hashes are
   illustrative placeholders inherited from the strategy demonstration, which records that
   fact itself.
5. The demonstration fixtures are **hand-authored contract demonstrations**. They are not
   production copy, not benchmark output, and not evidence that automated authoring exists.

## Compatibility rule

Version 1 is closed. Field changes require a separately reviewed version. This contract adds
no copy generator, no template or phrase bank, no model or provider call, no TTS, no voice
identity, no mixing, no timeline compilation, no video rendering, no winner selection, no
market research, no queue, no registry scope and no production wiring.
