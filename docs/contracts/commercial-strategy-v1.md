# Commercial Strategy v1 Contract

- **Schema:** `commercial_strategy.v1`
- **Implementation:** `src/ai_autocut/commercial_strategy.py`
- **Schema file:** `schemas/commercial_strategy/commercial_strategy.v1.schema.json`
- **Contract demonstration:** `examples/strategy/indonesia-faucet-filter-abc.json`
- **Artifact path:** `strategy/commercial_strategy.json`
- **Producer:** none registered — nothing in production writes this artifact
- **Status:** `CONTRACT_ONLY` / `NOT_WIRED` (`IMPLEMENTATION`, `WIRING_STATUS`)
- **Precedent:** `planning_evidence.v1` — a validated shape with no production writer or reader

## Purpose and boundary

Copy authors use the calibrated guidance in `docs/skills/commercial-copy-v1.md`, section 9,
to express the selected argument as a buyer-relevant recommendation. Style preferences
do not override this strategy or its claim boundary. If an approved job changes the facts,
reconcile its boundary explicitly; historical demonstration fixtures are not silently updated.

A Commercial Strategy records **what one piece argues**: the market it addresses, the
consumer the producer believes it is speaking to, the insights behind the argument, the
product facts it may rest on, what the current material can and cannot show, which claims
are permitted, and which strategic task each version of the piece is doing.

It is not copy, not a script, not a hook, not market research, not consumer research, not a
timeline, and not a release decision. It carries direction; the words are authored later.

Four layers are kept apart, because collapsing them is how a strategy becomes a claim the
footage cannot support:

```text
PRODUCT FACT      what the product is                        product_facts
CONSUMER INSIGHT  what the producer believes about the buyer consumer_insight
COMMERCIAL CLAIM  what the piece may assert                  claim_boundary
FINAL COPY        the words that will be spoken              NOT IN THIS CONTRACT
```

There is deliberately **no field for final copy, voice-over lines, subtitles, or CTA
wording**. A document that carries one is refused for an unsupported key. Nothing in this
contract generates anything: no model, no provider, no network, no media, no creative
logic.

## Data model

```json
{
  "schema_version": "commercial_strategy.v1",
  "strategy_id": "<token>",
  "market": "<token>",
  "platform": "<token>",
  "objective": "<token>",
  "product": { "name": "..." },
  "target_consumer": "...",
  "consumer_insight": [ { "insight_id": "...", "statement": "..." } ],
  "product_facts": {
    "ref": "brief/product_facts.json",
    "sha256": "<sha256>",
    "allowed_fact_refs": ["..."]
  },
  "visual_evidence_boundary": {
    "ref": "evidence/visual-evidence-boundary.json",
    "sha256": "<sha256>",
    "items": [ { "evidence_id": "...", "statement": "...", "presence": "PRESENT|ABSENT" } ]
  },
  "claim_boundary": {
    "allowed": [
      { "claim_id": "...", "statement": "...", "product_fact_ref": "...", "evidence_ref": null }
    ],
    "conditional": [
      { "claim_id": "...", "statement": "...", "product_fact_ref": "...",
        "requires_evidence_ref": null, "condition": "..." }
    ],
    "forbidden": [ { "claim_id": "...", "statement": "...", "reason": "..." } ]
  },
  "variants": [
    { "variant_id": "A", "persuasion_job": "...", "hook_strategy": "...",
      "copy_direction": ["..."], "cta_direction": "...", "claims_used": ["..."] }
  ],
  "provenance": {
    "authored_by": { "actor": "CODEX_SUPERVISOR|HUMAN|AUTOMATED_REPAIR", "producer_id": "..." },
    "based_on": [ { "ref": "...", "sha256": "<sha256>" } ]
  }
}
```

The document has exactly the keys above. Unknown or missing keys are contract errors.
`evidence_ref` and `requires_evidence_ref` are required keys that may be `null`, which is
this repository's existing idiom for an optional value.

### Closed vocabularies and caller-owned values

The contract owns three closed vocabularies, because it is the project that gives them
meaning: `CLAIM_STATES` (`ALLOWED`, `CONDITIONAL`, `FORBIDDEN`), `EVIDENCE_PRESENCE`
(`PRESENT`, `ABSENT`), and the author `actor` vocabulary, which is reused unchanged from
`intervention_ledger.ACTORS`.

`market`, `platform`, `objective`, `persuasion_job` and every identifier are **caller-owned
tokens**. They are deliberately not enums. Hardcoding a persuasion list such as EXPLAIN /
RELATE / DEMONSTRATE would make one job's creative taxonomy every future job's default,
which is the failure this repository already guards against in geometry, typography and
sync tolerance.

### Document level vs variant level

`market`, `platform`, `objective`, `product`, `target_consumer`, `consumer_insight`,
`product_facts`, `visual_evidence_boundary` and `claim_boundary` are **document level**.
Only `variant_id`, `persuasion_job`, `hook_strategy`, `copy_direction`, `cta_direction` and
`claims_used` are **variant level** (`VARIANT_STRATEGY_FIELDS`).

This is what makes a strategy comparison meaningful: a set of variants argued to the same
market cannot silently drift onto a different evidence boundary or a different permitted
fact list, because there is nowhere in the document to put such a drift. Two markets in one
job are two documents and two jobs.

## Evidence safety

A strategy may not be used to bypass the evidence boundary.

1. Every `ALLOWED` claim must name a Product Fact that this document's own
   `allowed_fact_refs` holds. A claim cannot be invented into existence by declaring it.
2. An `ALLOWED` claim that also names evidence must name evidence this document marks
   `PRESENT`. A claim resting on `ABSENT` evidence is refused, which is exactly what keeps a
   permitted product fact the footage does not show at `CONDITIONAL`.
3. A variant may only use claims that are `ALLOWED`. `claims_used` naming a `CONDITIONAL`
   claim is refused, because using it as though its condition held is the bypass; naming a
   `FORBIDDEN` claim is refused; naming an undeclared claim is refused.
4. `validate_against_product_facts(strategy, allowed_fact_refs)` re-binds the document to
   the authoritative permitted-fact list a caller actually read, and refuses a document
   whose declared list or claims reach outside it.

A `claim_id` appearing in two of the three claim lists is a contradiction and is refused.
That is the mechanical reason a forbidden claim cannot be smuggled back in as an allowed one.

## Provenance

`provenance.authored_by` records who produced the document, using the intervention ledger's
own actor vocabulary. `provenance.based_on` names the exact revisions the strategy was
authored against and must include both `product_facts.ref` and
`visual_evidence_boundary.ref`, with matching `sha256` values.

The document carries **no timestamp**, because identical input must render identical bytes;
when an author acted belongs to `intervention_ledger.jsonl`. It carries **no prompt, no
provider transcript, no rationale and no reasoning** — only auditable external provenance.

## Variant identity and comparison

`variant_id` is a stable, unique token per variant. `strategy_differences(strategy)`
returns the shared fields, each variant's own strategy fields, and the list of fields that
actually differ. A reviewer answers "how are A, B and C different?" from the document
rather than by watching three videos and guessing.

## Recorded limitation

Like `artifact_reference`, this contract does not read files and does not resolve paths. It
proves that a claim references a permitted fact **as this document declares it**, and that
the fact document is pinned by `{ref, sha256}`. It cannot prove the referenced bytes still
match, and it does not decide that a stale strategy is still valid. A consumer that needs
that must call `validate_reference_binding` on the artifact it actually read.

There is, at this baseline, **no canonical Product Facts artifact in the legacy production
chain**: the permitted facts reach the chain through the Producer Brief and the human
Creative Copy Approval gate. `product_facts.ref` therefore names a document the Producer
supplies, and the strong binding described in `validate_against_product_facts` is enforced
whenever a caller supplies the authority. This is recorded rather than hidden.

## Status: contract only, not wired

`IMPLEMENTATION = "CONTRACT_ONLY"`, `WIRING_STATUS = "NOT_WIRED"`. This follows the
precedent this repository already set for `planning_evidence.v1`: the shape is defined,
validated and tested, and **nothing in production writes or reads one yet**.

Concretely, at this baseline:

- **No producer is registered.**
  `producer_registry.producer_for("strategy/commercial_strategy.json")` raises
  `NO PRODUCER`, and `mode_of` reports no owner. `PRODUCERS` is scoped to artifacts the
  fast path requires, and `tests/test_fast_path_chain.py` enforces that deleting any
  registered artifact produces a producer gate naming it. Registering this artifact would
  therefore require wiring it into a fast-path stage — a change to the frozen production
  control path. Rather than attach a false claim to the registry, the artifact is not
  registered at all.
- **No writer and no reader.** No stage requires it; no module reads it.
- **The production chain is untouched.** `fast_path.py`, the execution adapters and the
  other contract modules are unchanged by this work.

The intended future consumer is `copy-planner` (`copy/commercial_units.json`), and the
intended producer is a Supervisor/Agent author of a kind the registry already defines.
Neither is claimed here. When that wiring is proposed it belongs in the existing registry —
exactly one producer for the artifact, plus the artifact as a reviewed stage input. A third
mode, scope or registry is deliberately not the mechanism for it, and this contract adds
none.

## Compatibility rule

Version 1 is closed. Field changes require a separately reviewed version. This contract
adds no market engine, consumer research, model call, provider, copy generator, hook
generator, TTS, video pipeline change, executable timeline compiler, reviewer, database,
queue, UI, or artifact beyond the one document it defines.
