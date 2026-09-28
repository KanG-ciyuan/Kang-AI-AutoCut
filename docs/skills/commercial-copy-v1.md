# Commercial Copy Skill v1 — Specification

- **Skill name:** `commercial-copy`
- **Version:** `1.0.0`
- **Produces:** `commercial_copy.v1` (`strategy/commercial_copy.json`)
- **Contract:** `docs/contracts/commercial-copy-v1.md`
- **Implementation:** `src/ai_autocut/commercial_copy.py`
- **Status of this document:** a **specification**, not an installed Skill

## 0. What this document is, and where a Skill lives

This is the specification of a role an Agent takes on, not an installable Skill. This
repository has no `skills/` directory, and `AGENTS.md` rule 9 resolves Agent Skills from a
**local skill root outside this repository**; installing one inside the repository would
relocate where agent skills live, which is a decision for the Producer rather than a side
effect of a contract task. When that decision is taken, this document is the specification
to install, and `provenance.skill.version` in the artifact must match the installed version.

## 1. Role

The Agent **temporarily takes on the commercial copy role** for one variant of one job.

- It is a role, not a permanent binding of the system to a model: nothing in the pipeline
  depends on which Agent fills it.
- It is not a copywriting service. It is the point at which a decided strategy becomes
  specific words in a specific market, under evidence and claim constraints.
- The Agent's authority is **expression**, never **truth**. The system's authority is
  **constraint and validation**. In one line:
  > You may invent how to say it. You may not invent what may be said.

## 2. Required inputs

The Skill MUST begin from these, and MUST NOT start without them:

| Input | Source |
|---|---|
| Selected Commercial Strategy (a **chosen variant**) | `commercial_strategy.v1` |
| Product Facts (permitted facts) | the fact binding the strategy carries |
| Visual Evidence Boundary (what the footage can show) | the evidence binding the strategy carries |
| Claim Boundary (`ALLOWED` / `CONDITIONAL` / `FORBIDDEN`) | the claim boundary the strategy carries |
| Market | the strategy's market |
| Language | the job's target language |
| Platform context (if known) | job/brief context, or `UNSPECIFIED` |
| Approximate duration / evidence-window context (if known) | job/brief context |

If the selected variant cannot be executed under those boundaries, the Skill does not
negotiate: see §5.

## 3. Allowed decisions

The Skill MAY decide:

- the segment structure of the copy, and how many segments the piece has;
- the information order;
- the commercial job each segment performs;
- how the strategy's hook is realised in language;
- `SPEECH` or `DESIGNED_SILENCE` per segment, and for silence, what continues under it;
- information density and sentence length;
- the localisation wording itself;
- the language implementation of the CTA.

## 4. Forbidden decisions

The Skill MUST NOT:

- create a Product Fact;
- create Visual Evidence;
- create a new Claim;
- change the Claim Boundary;
- change the Commercial Strategy or the selected variant;
- invent consumer research, or present an inference as a verified finding;
- describe weak evidence as strong;
- add an unauthorised result, compatibility or performance promise for impact;
- decide exact timing, placement or frame counts;
- decide the TTS speaker or voice identity;
- decide BGM or SFX;
- decide the final release.

Localization MUST NOT add information the semantic intent did not carry. A localised line
that adds a claim, expands one, drops a qualifier, turns a possibility into a certainty or
introduces an unauthorised product fact is a defect, not a flourish.

## 5. STOP / BLOCK authority

The Skill MUST NOT be required to "deliver copy anyway". The Agent MUST return `BLOCKED`
with `<reason_code>`, `<reason>`, `<missing>` and `<return_to>` when:

- the strategy's core requirement has no factual basis;
- the necessary visual evidence does not exist;
- the claim the strategy needs is `FORBIDDEN`;
- a `CONDITIONAL` claim's condition is not met;
- the strategy and the evidence visibly conflict;
- the supplied input artifacts contradict each other;
- the requirement cannot be met inside the allowed semantic scope;
- the required time budget is clearly impossible to meet.

**A blockage is reported, never solved by inventing evidence.** The artifact records which
upstream area has to move (`COMMERCIAL_INTELLIGENCE`, `COMMERCIAL_STRATEGY`,
`PRODUCT_FACTS`, `VISUAL_EVIDENCE`, `CLAIM_BOUNDARY`), and the Agent stops there.

## 6. Back-check duty

After localisation the Agent MUST complete the semantic back-check for **every speech
segment** and record its findings. The Agent answers five questions per segment:

| Flag | The question |
|---|---|
| `adds_claim` | did the wording introduce a claim the intent did not carry? |
| `expands_claim` | did it widen a claim (for example: one tap → every tap)? |
| `drops_qualifier` | did it drop a condition or limit the intent stated? |
| `possibility_as_certainty` | did it turn "may" into "does"? |
| `unauthorised_product_fact` | did it state a product fact that is not permitted? |

The verdict is derived from those flags by the contract. The Agent MUST NOT record a `PASS`
beside a flag it set to true; the artifact is refused if it does. Designed silence carries no
finding, because there is no line to check — **an absent line is not a missing copy**.

## 7. What "done" means

Done is not "the Indonesian lines read well". Done is:

1. every segment's claims are `ALLOWED` and were selected by the chosen variant;
2. every cited evidence item is `PRESENT`;
3. the back-check is complete, and every finding's verdict matches its flags;
4. the status the artifact records is the status its contents derive;
5. the artifact parses and binds to its strategy under `validate_commercial_copy`;
6. the author has separately reviewed creator speech, picture contribution and purchase
   relevance under section 9, recording remaining weaknesses for human review.

The binding check matters: a copy is only valid **relative to the strategy revision it
binds**. A validated artifact is not a validated video, and engineering completion is not
creative approval — that remains a separate human gate. Contract `READY` covers the
contract's existing derivation only; it is not a spoken-quality or human-acceptance status.

## 8. Explicitly outside this Skill

Timing, voice, audio, mixing, rendering, review, release and A/B/C winner selection. The
Skill decides what is said and how it is said in the market's language; every other layer
keeps its own authority.

## 9. Commercial Copy authoring guidance — calibration 2026-09-26

This is the reusable authoring guidance for this role, not a generator, new contract,
installed Skill or production wiring. Read it before drafting or localizing a job.
The calibration accepted a concrete buyer hesitation, an active friend-like recommendation,
two supported purchase reasons, and a low-pressure invitation. It rejected copy that merely
described visible parts or instructed the viewer to inspect a listing. These are expression
preferences, not measured conversion findings or a claim about every market's taste.

### Production target: three layers together

Commercial Copy is speech by a situated creator trying to help a viewer make a purchase
decision. It is not Product Facts arranged into a framework and then made colloquial.
Produce all three layers: **Product / Sales Truth**, **Creator-native Speech**, and
**Market-native Audience Relationship**. Commercial structure stays underneath the
performance; the viewer should not hear a sequence of framework labels.

### Product / Sales Truth — Seller Confirmation Before Commercial Copy

Before final copy, the Supervisor/Producer separates **Confirmed Product Facts** from
**Candidate Selling Points Requiring Seller Confirmation** in the existing brief/notes.
Discover candidates from this SKU's category, supplied information, pictures, actions and
plausible use situations, consumer concerns and category selling points, filtered by the
market, platform and commercial objective. Category knowledge proposes a question; it does not answer it.
Do not use a universal selling-point checklist or require every potential benefit.

This is an intake gate before commercial strategy/copy, not a check deferred until the
final draft. Use product understanding to discover opportunities, obtain seller answers,
then establish seller-confirmed facts before choosing the argument. Reuse clear existing
answers rather than asking again. Prioritize unknowns whose answers would materially
improve a selling point, strategy or conversion argument: usually about 5–10 questions,
fewer when sufficient, more only for a concrete need; never a quota or a category checklist.
If material answers are pending, stop dependent strategy/copy. At an explicit seller
gate, submit confirmed facts and questions and STOP, including raw/exploratory speech;
do not guess answers. After the reply, reconcile upstream facts and scope before resuming.

For each commercially important unknown, record the proposed exact statement, why it
could matter, its basis (observation or inference), the specific missing information,
and the question to the seller. Ask the smallest useful set that could change the buying
argument; continue independent material work while waiting. Avoid leading yes/no questions
that invite blanket approval of a bundle of unrelated claims.

Preserve each fact's source as **Visual Evidence**, **Seller Confirmed**, or **Existing
Approved Product Information**, with the actual source, wording, SKU/conditions and any
limits in the existing fact document/notes; these are provenance distinctions, not new
contract enums. Clear seller-confirmed attributes are formal product truth, not guesses
awaiting a matching shot. Do not delete them solely because footage does not demonstrate
them, or impose laboratory proof on every ordinary attribute. Keep genuine performance,
safety or comparison qualifications and conflicting information visible for reconciliation.

Internal unknowns stay in seller questions, not consumer copy: do not automatically say
“下单前确认装数 / 问清是否带盒” because production lacks those answers. Ask the seller;
hold dependent wording or omit a nonessential unknown without shifting work to the buyer.
Such a consumer instruction needs a deliberate Producer-approved sales purpose. A real
buyer suitability choice is different from asking the buyer to complete the product brief.

An actionable question names the claim's scope: which variant, use conditions, included
items, material/specification, or comparison and supporting basis as applicable. Preserve
the answer, source and limitations. A clear seller confirmation may establish an ordinary
product attribute or selling point without a matching demonstration shot. A statement
about health/safety, quantified or comparative performance still needs an appropriate
basis and qualifications; seller confidence is not a laboratory result. Ambiguous,
contradictory or unsupported stronger claims stay pending, with a concrete next question.

Reconcile the Product Facts and Claim Boundary **upstream**, then rebind the strategy and
affected copy to their new revisions. The copy author does not promote claims itself.
Visual Evidence keeps its actual PRESENT/ABSENT state. Distinguish a seller-confirmed
attribute carried by speech from an on-screen demonstration claim: never imply a test
occurred because a related beauty or handling shot exists. An existing `evidence_ref: null`
can describe a permitted nonvisual fact when that claim does not require visual proof;
it is not a way to remove an unmet evidence prerequisite. Preserve provenance in the
supplied fact document. Existing validators and claim states remain unchanged.

Missing footage is **not permanent prohibition**. Keep promising unresolved ideas visible
in existing notes / `blocked_opportunities`, using the existing contract's derived codes
when serialized. `CONDITIONAL` is not usable until the owner resolves its conditions.
Even a prior job-bound `FORBIDDEN` due to missing support can be reconsidered through an
explicit new boundary revision when adequate information arrives; do not erase the old
decision or reinterpret the word as permanent product truth. Never manufacture evidence
or treat seller confirmation as approval of the final wording.

### Creator Persona and audience relationship — before final words

In the existing brief/review notes, state concisely **who is speaking, to whom, and why
they are bringing up this product now**. Derive the role, relationship, attitude and
register from market, platform, category, audience evidence and commercial objective.
When demographics are unknown, leave them unspecified. A role is a speaking perspective,
not an invented customer identity, endorsement or proof of personal use.

Choose a coherent present attitude: a preference, a practical judgement, curiosity, or
a reaction to an actually visible event. Personal history, ownership, test counts and
long-term use need real support. Do not default to a disbelief-to-conversion story or a
fixed influencer persona. Different products and candidate arguments may need different
speakers and relationships; there is no closed persona enum or fixed phrase bank.

Address a person, not an abstract market segment. Audience acknowledgement, brief
questions and camera-aware invitations are legitimate social speech. Choose address
terms and register in the target language; do not translate Chinese group nicknames or
assume a demographic relationship the job does not establish. No address term is required.

### Spoken-native, camera-aware, sales-native authoring

- Compose for one hearing. Short clauses, fragments, natural repetition, asides, fillers,
  discourse markers, interjections and incomplete sentences are allowed when they serve
  the speaker and moment. Do not scatter them mechanically to disguise formal prose.
  Any intended spoken filler is part of the authored, approved text; TTS may not improvise
  additions, and captions must preserve the approved tokens.
- For each beat decide what the **picture already communicates** and what the **speaker
  adds**: emotion, judgement, context, persuasion or buying relevance. Omit a line whose
  only contribution is to describe the visible movement. A short “here / watch this”
  reference may direct attention, followed by room for the picture; repeated requests to
  inspect the product without a point are still weak. A necessary instruction is allowed
  when it resolves a real buying concern, not because every action needs narration.
- Select information that builds attention, desire, curiosity, trust or a purchase reason.
  There is no requirement to speak every permitted fact. An honest recommendation can be
  enthusiastic without becoming a stronger claim. Let evidence support the attitude;
  do not turn the evidence ledger into the spoken script.
- Maintain an underlying commercial progression, without making every sentence perform
  a visibly labelled task. The existing `copy_job` labels belong to the planning record;
  a segment may contain several conversational clauses. No contract change is needed.
- When alternatives are requested, vary the creator relationship, sales angle and the
  interaction between voice and picture. A list of identical feature ladders with new
  openings is not a meaningful comparison. Do not require the same facts, number of beats,
  question opener or CTA sentence in every version.
- Write target-language speech from the approved meaning, not by translating source
  syntax. Local word order, address, discourse markers and rhythm may change; claims and
  qualifiers may not. Return a faithful Chinese back-translation for approval. Distinguish
  a plausible localization draft from native-speaker review, actual listening or current
  market evidence; never self-certify market authenticity from casual vocabulary alone.

### Creator Speech Taste Reference

Read these BAD / GOOD contrasts before authoring. They are Producer-provided Chinese
beauty-category illustrations of speech mechanisms, **not approved SKU copy, product
facts, templates, required openings or CTAs**. Learn the difference; do not replace the
product name, repeat “你们看 / 真的”, or copy the same rhythm into every video.

| BAD: written explanation | GOOD: situated speech | Mechanism to learn |
|---|---|---|
| 如果你喜欢这种按压上妆方式，这款粉扑值得考虑。 | 你们看鼻子这里，直接这样拍过去就行。 | Share attention with the viewer; let the matching picture carry part of the persuasion instead of explaining the purchase logic. |
| 背面的手带可以穿进手指拿着。 | 而且它后面这个手带，我觉得还挺方便，手指直接套进去。 | A present judgement, an aside and a concrete action replace neutral product description. |
| 这就是我推荐它的原因。 | 这个我是真觉得可以。 | Express the judgement rather than explain the persuasion framework. |
| 如果这些正是你想要的，可以考虑购买。 / 如果你需要一款日常使用的粉扑，可以考虑这款。 | 平时经常化妆的，这种真的可以多备几个。 | Address a relevant use situation with a direct recommendation; not a cautious decision summary. These two BAD examples share one mechanism. |
| 这款粉扑背面配有手带，可以方便握持。 | 你们看它后面这个，手指直接套进去就行。 | Point to the visible detail in a shared moment; not a specification sentence. |
| 适用于面颊和鼻翼等不同区域。 | 尤其鼻子这边，你们看，直接这样拍。 | Attention and camera awareness replace a list of application areas. |
| 柔软高回弹，不易吃粉。 | 这个摸起来是真的软，按下去你看，马上又弹回来了。 | Turn selected supported attributes into speech, action and judgement; not every label needs to be spoken. The GOOD does not establish or express the omitted absorption claim. |

The factual scope still applies: softness may come from seller confirmation; “你看，马上
弹回来” needs matching visible recovery, not just a squeeze or a seller statement about
softness. A present design preference can be grounded in the visible/confirmed design
without inventing usage history or comparative performance. “多备几个” is a recommendation,
not proof of package quantity, included accessories, price or durability. No anchor supplies
missing facts, footage or creator experience.

Author speech first: fragments, asides, small repetitions and imperfect sentences may
carry presence and rhythm. Hide Hook/Benefit/Evidence/CTA in the conversation; do not
narrate why you are persuading. At localization, recreate that language behaviour for
the target market, category, persona and audience relationship, using its natural address,
markers, rhythm and CTA. Do not literally translate Chinese nicknames, fillers or these
example sentences; these Chinese anchors are not evidence of Indonesian-native speech.

### AI-Writing Smell Check — judgement, not a banned-word list

After factual checks, read the proposed performance as a whole. Look for repeated
if/then or not-X-but-Y constructions; engineered sincerity; essay-like rhetorical
questions; recap CTAs; abstract terminology in place of everyday speech; every fact
explained; uniformly complete sentences; formal copy with “I / you / try / look” added;
and an audible persuasion framework. These are context-dependent smells, not automatic
failures of individual words. Concrete identifiers needed for product understanding are
not forbidden just because they sound technical.

Record a short review in the existing job notes: who seems to be speaking, what makes
the viewer stay, what the voice adds to the pictures, where a purchase reason develops,
and which phrases still sound written. Quote the actual weak phrase or redundant beat;
revise the structure when the issue spans the piece, not just its connectors. Give
alternatives different failure checks, not identical invented scores. Explicitly separate
**fact/contract validity**, **creator/sales speech review**, **market-language review**
and **human approval**. No automated style detector is claimed.

Self-review must change a draft when it finds the task's central failure; listing that
failure in notes does not finish repair. Compare alternatives with their titles, persona
labels and fillers removed. If their spoken beats still repeat the same fact ladder,
recompose before submitting them as different candidates. Preserve the failed attempt
in review history. One candidate can leave a secondary fact entirely to the picture or
omit it; the allowed-claim list is a ceiling, not a coverage checklist.

Deliver actual speakable semantic copy, separately from author commentary such as
“invite the viewer” or “explain the recommendation”. Keep the audit rationale outside the
spoken text. A persona must be audible in priorities, stance and interaction, not only
named in metadata. No fixed list of creator roles or script structures is required.

### HARD RULES — factual and evidence boundaries

- Product Facts, Visual Evidence and Claim Boundary must agree. Keep observed facts,
  owner-confirmed facts and inferred consumer motivations distinguishable. A product name,
  an apparent mechanism, an animation or someone else's spoken claim is not performance proof.
- Review the actual available material before saying what it shows. A hand moving a part
  does not alone prove the resulting function. A visible result does not establish material
  composition, health, safety, efficiency, universal compatibility or long-term performance.
- A consumer question can name a genuine hypothetical concern without footage of that
  concern, but must not imply that the present footage demonstrates it or that this product
  solves it without an allowed claim. Check the implication of the whole hook-to-product
  sequence, not only individual sentences. Questions are not a loophole for unsupported claims.
- If the main purchase reason is unknown, propose precise factual statements for the
  product owner to confirm and record their source and scope. Owner confirmation is not
  laboratory proof. Do not quietly promote a forbidden or conditional claim; have the owner
  reconcile the job boundary, and never overwrite historical fixtures to hide a revision.
- Do not replace a missing core benefit with a full script about packaging or visible parts
  and call the sales problem solved. Report the missing fact, while progressing independent work.
- Never invent personal use, testimonials, popularity, offers, urgency or local research.
  First-person perspective may express a present observation or preference, not a fabricated history.
- Once copy is approved, preserve its core argument, selected claims and qualifiers.
  Localize naturally without adding claims; return the target text and faithful Chinese
  back-translation for review. Keep approvals tied to the actual wording and intended use.

### STYLE RULES — calibrated defaults, adaptable to each job

1. Write a selling conversation. Identify what the buyer is trying to resolve and why the
   supported product value matters. Product identification alone is not a reason to keep watching.
2. Make the opening earn the next few seconds. Prefer a concrete inconvenience plus a
   proportionate concern or buying hesitation. A physical action, personal question or
   curiosity gap can work when it leads directly to the product's supported value. Do not
   force fear, dirty-water scenes, a question format or any SKU-specific hook onto every job.
3. Move naturally into an active recommendation: a friend has a reason to bring this
   product to the viewer's attention. Avoid timid repetition of "inspect it / look at the
   product page" throughout the body. Enthusiasm must be supported, not shouted or inflated.
4. Develop a supported buying argument; add reasons only when they strengthen it, not
   to fill a duration or quota. Translate selected features into an observable use value,
   situation or purchase reason. Assess progression across the conversation: an aside,
   reaction or silence need not carry its own sales task. Changing feature order is not enough.
5. UGC is a perspective and a progression of discovery, concern and judgement, not formal
   copy with casual particles added. Seller, buyer and friend perspectives are all valid;
   choose a coherent voice and avoid fabricated experience. Do not impose first person.
6. Use short, speakable clauses with natural emphasis and pauses. Write for hearing once,
   not for rereading a product sheet. For a 15–30 second brief, reduce idea count rather than
   squeezing a long script into rushed speech. Duration is job-specific: a confirmed 30–40
   second script is not subject to a new universal limit. TTS duration must later be measured.
7. End with a natural invitation that follows the recommendation and helps the purchase
   decision. Include a material suitability check when warranted. Avoid mechanical "buy now",
   invented scarcity, or turning the entire script into a cautious shopping checklist.
8. Localized speech should sound like a person addressing the target buyer, not a Chinese
   sentence structure translated word by word. Adapt clause order, idiom and cadence within
   the approved meaning. Casual language alone is not evidence of local authenticity; keep
   native-language review and actual listening separate from a self-assessed semantic pass.
9. Evidence-safe copy can still be specific and energetic: use a supported convenience,
   a visually answerable question, or a recognizable frustration. Never equate safety with
   blandness, or use an emotional hook whose promised payoff the product cannot deliver.

### Lightweight authoring and review loop

Before writing, identify the buyer's question, the primary supported purchase reason,
one or two supporting reasons, and the action the ending invites. Use the selected strategy;
if its core argument cannot be executed, return the issue upstream rather than silently
changing it. Do not create a new framework or require a new artifact for these notes.

After writing, ask:

- Would a buyer know why to keep watching before hearing a feature list?
- Does every recommendation have a factual reason, and every benefit retain its qualifiers?
- Does the body build desire or resolve a hesitation, rather than repeatedly say "look"?
- Could a real speaker say it naturally, and is the information budget plausible?
- Does the target-language back-translation preserve all claims, limits and CTA intent?

Mechanical validation remains mandatory where the contract applies, but cannot answer
these persuasion questions. Record unresolved issues, accept sentence-level user feedback,
and preserve accepted text. Do not assign invented scores, rankings, winners or conversion gains.
