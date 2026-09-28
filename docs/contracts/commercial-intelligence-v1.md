# Commercial Intelligence v1 Contract

- **Schema:** `commercial_intelligence.v1`
- **Implementation:** `src/ai_autocut/commercial_intelligence.py`
- **Schema file:** `schemas/commercial_intelligence/commercial_intelligence.v1.schema.json`
- **Contract demonstration:** `examples/strategy/indonesia-faucet-filter-candidates.json`
- **Artifact path:** `strategy/commercial_intelligence.json`
- **Producer:** none registered — nothing in production writes this artifact
- **Status:** `CONTRACT_ONLY` / `NOT_WIRED` (`IMPLEMENTATION`, `WIRING_STATUS`)
- **Precedent:** `planning_evidence.v1` and `commercial_strategy.v1`
- **Upstream of:** `commercial_strategy.v1`

## Purpose and boundary

Commercial Strategy v1 records what one piece argues, but it is a *decision* document: it
holds the variants that were chosen. Nothing recorded the step before the choice — why
those candidates were on the table, which consumer belief each one rests on, and which
commercially attractive ideas the material cannot currently support.

This contract is that step:

```text
WHAT MAY THE CONSUMER CARE ABOUT?       consumer_hypotheses
  x WHAT IS TRUE ABOUT THE PRODUCT?     product_facts
  x WHAT CAN THE FOOTAGE PROVE?         visual_evidence_boundary
  x WHAT ARE WE ALLOWED TO CLAIM?       claim_boundary
                  =
          STRATEGY CANDIDATES             candidates
                  +
  IDEAS BLOCKED BY MISSING EVIDENCE       blocked_opportunities
```

It is not copy, not a hook, not market research, not a shot plan, and not a selection. It
carries candidates; the choice belongs to a later human, supervisor or experiment.

## System contract vs Agent intelligence

A passing validation must never be read as the system having generated a strategy. The
boundary is explicit:

| SYSTEM CONTRACT / VALIDATION | AGENT INTELLIGENCE / AUTHORING |
|---|---|
| shape and enum validation | which consumer beliefs are worth hypothesising |
| reference integrity | which persuasion job a version is doing |
| viability rules | the hook strategy and the copy direction |
| deterministic claim unavailability | the rationale for choosing an angle |
| deterministic unlock analysis | spotting an opportunity worth pursuing |

There is no candidate-generation entry point in the module. Python here cannot invent
consumer psychology, and the contract does not pretend otherwise.

## Data model

```json
{
  "schema_version": "commercial_intelligence.v1",
  "candidate_set_id": "<token>",
  "context": {
    "product": { "name": "..." },
    "market": "<token>",
    "platform": "<token>",
    "platform_source": "DECLARED | UNSPECIFIED",
    "objective": "<token>",
    "objective_source": "DECLARED | DEFAULTED"
  },
  "product_facts": { "ref": "...", "sha256": "<sha256>", "allowed_fact_refs": ["..."] },
  "visual_evidence_boundary": { "ref": "...", "sha256": "<sha256>", "items": [ "..." ] },
  "claim_boundary": { "allowed": [ "..." ], "conditional": [ "..." ], "forbidden": [ "..." ] },
  "consumer_hypotheses": [
    { "hypothesis_id": "...", "statement": "...", "support": "DIRECT|CONTEXTUAL|INFERRED",
      "basis_ref": null }
  ],
  "candidates": [
    { "candidate_id": "...", "persuasion_job": "...", "hypothesis_refs": ["..."],
      "product_fact_refs": ["..."], "evidence_refs": ["..."], "claims_used": ["..."],
      "hook_strategy": "...", "copy_direction": ["..."], "cta_direction": "...",
      "rationale": "...", "limitations": ["..."] }
  ],
  "blocked_opportunities": [
    { "opportunity_id": "...", "statement": "...", "persuasion_job": "...",
      "claim_ref": "...", "blocked_by": "...", "missing": ["..."], "next_action": "..." }
  ],
  "provenance": { "authored_by": { "actor": "...", "producer_id": "..." },
                  "based_on": [ { "ref": "...", "sha256": "<sha256>" } ] }
}
```

The three boundary blocks — `product_facts`, `visual_evidence_boundary`, `claim_boundary` —
are **not redefined here**. They use the same key vocabulary, the same dataclasses and the
same parsers as `commercial_strategy.v1` (`parse_product_facts`,
`parse_evidence_boundary`, `parse_claim_boundary`), and they are pinned by `{ref, sha256}`
to the same authorities. There is one fact/evidence/claim implementation in this
repository, not two.

`persuasion_job` and every identifier are caller-owned tokens, not enums: hardcoding a
persuasion vocabulary would make one job's creative taxonomy every future job's default.

## Consumer hypotheses are not market facts

When supplying a job to Commercial Copy, distinguish the hypothesized buying concern
from the product benefit actually permitted by the boundary. The authoring preferences in
`docs/skills/commercial-copy-v1.md`, section 9, help express that relationship; they do not
verify an insight or authorize a claim. Do not choose an unsupported result merely because
it would make a stronger hook.

V1 performs no external market research, so a hypothesis must never be presented as
verified market knowledge. Support reuses the repository's existing
`candidate_evidence.ClaimSupport` vocabulary unchanged, and the rule is mechanical:

- `DIRECT` **requires** a `basis_ref`: the strongest level is citable only;
- `CONTEXTUAL` and `INFERRED` **must not** name one.

An inference cannot therefore dress itself up as a finding, and `is_verified` is true only
when a bound citation actually backs the hypothesis. Most V1 hypotheses are expected to be
`INFERRED`, and the artifact says so rather than implying research.

## Candidate viability

A candidate is viable only if every layer supports it. All five rules are enforced on parse:

1. It cites at least one declared consumer hypothesis.
2. Every Product Fact it rests on is permitted by the bound fact document.
3. Every cited Visual Evidence item is declared **and `PRESENT`** — so a permitted product
   fact whose evidence is `ABSENT` cannot appear in a viable candidate.
4. Every claim it uses is `ALLOWED`. A `CONDITIONAL` claim used as though its condition
   held is refused; a `FORBIDDEN` claim can never be used.
5. The facts and evidence it cites must actually cover the claims it uses, so neither list
   is decoration.

A commercially attractive idea that fails these checks is not deleted and not softened: it
belongs in `blocked_opportunities`.

## Blocked opportunities and unlock analysis

`blocked_by` is **derived, never declared freely**. `claim_availability(claim_id,
claim_boundary, evidence_boundary)` computes it from the boundaries:

| Derived reason | Meaning |
|---|---|
| `CLAIM_NOT_DECLARED` | the claim boundary does not declare the claim |
| `CLAIM_FORBIDDEN` | the claim boundary forbids it |
| `CONDITIONAL_EVIDENCE_ABSENT` | conditional, and the evidence it requires is `ABSENT` (the absent id is the derived `missing` item) |
| `CONDITIONAL_NOT_MECHANICALLY_RESOLVED` | conditional with no absent prerequisite: only the claim boundary's owner can promote it |

The document must agree with the derivation: a declared `blocked_by` that differs from the
derived one is refused, an opportunity whose claim is actually `ALLOWED` is refused (it
belongs in `candidates`), and every derived `missing` item must appear in the declared
`missing` list — an author may add more, but may not leave one out.

`unlock_requirements(document)` returns the derived missing items per opportunity with
`grants_claim_use: false`. This is the honest answer to *"what additional footage or
evidence would unlock a stronger commercial strategy?"*. It grants nothing: an unlock
requirement describes missing evidence, it is never permission to make the claim.

## No winner, no fake precision

The contract has **no numeric field at all**: no score, rank, confidence or
expected-performance field exists to be filled in. There is currently no real performance
data behind such a number, so the document offers candidates and states plainly that it
does not know which would perform best. Candidates render ordered by `candidate_id`, which
— as `hook_decision.json` already records about its own ordering — is not a ranking.

`rationale`, `statement`, `hook_strategy` and every other free text is **single-line**.
A block of multi-line prose is how hidden reasoning or a pasted model transcript would
enter an audit artifact, so the shape refuses it instead of trusting a length limit.

## Minimum human input

`resolve_context(product_name, market, platform=None, objective=None)` requires only the
product and the market, because nothing in the repository can derive either:

- `objective` defaults to the project's stable default for commerce
  (`DEFAULT_OBJECTIVE = "DIRECT_CONVERSION"`) and is recorded as `DEFAULTED`;
- `platform` is recorded as `UNSPECIFIED` when the job does not state one. `TikTok` is the
  current production-validated scope, but that is a project fact rather than a universal
  truth, so it is not baked into the contract as a default;
- either may be overridden, and the value is then recorded as `DECLARED`.

Recording the *source* beside the value is the same idiom as
`spoken_duration.RateObservation`, which records `rate_source` beside the rate it derived.
It is what stops an assumed objective from reading as a decision.

## Relationship to Commercial Strategy v1

This contract sits upstream of `commercial_strategy.v1`:

```text
Commercial Intelligence  →  Strategy Candidates  →  human / supervisor / experiment
                                                    selection  →  Commercial Strategy v1
```

The demonstration fixture uses the same market, platform, objective, product, evidence ids,
claim ids and authorities as `examples/strategy/indonesia-faucet-filter-abc.json`, and its
candidates A / B / C correspond to that document's variants A / B / C. The two documents
share one boundary rather than forking it, and a test holds that correspondence.

Wiring this into the production pipeline is **not** part of this contract.

## Recorded limitation

Like `artifact_reference`, this contract does not read files and does not resolve paths. It
proves reference integrity *as the document declares it* and that the authorities are
pinned by `{ref, sha256}`; it cannot prove the referenced bytes still match. The claim
boundary has no standalone authority at this baseline, so this document declares the same
boundary that `commercial_strategy.v1` declares; a future revision may bind both to one
shared claim-boundary artifact.

## Status: contract only, not wired

`IMPLEMENTATION = "CONTRACT_ONLY"`, `WIRING_STATUS = "NOT_WIRED"`.

- **No producer is registered.** `producer_registry.producer_for("strategy/commercial_intelligence.json")`
  raises `NO PRODUCER`, and `mode_of` reports no owner.
- **No writer and no reader.** No stage requires it; no module reads it.
- **The production chain is untouched.** `fast_path.py`, the execution adapters and the
  other contracts are unchanged by this work.

The demonstration fixture is hand-authored **for contract validation**. It is not output
from an automated authoring step, and it must not be read as evidence that automated
authoring exists.

## Compatibility rule

Version 1 is closed. Field changes require a separately reviewed version. This contract
adds no market research engine, no provider or network call, no copy generator, no hook
generator, no scorer, no winner prediction, no CTR/CVR database, no shot or reshoot
planner, no TTS, no video pipeline change, no reviewer, no queue and no registry scope.
