"""Commercial Strategy v1: what this piece argues, as a formal artifact.

Why this exists
---------------
The chain ``Market -> Consumer Insight -> Commercial Strategy -> Commercial Copy`` had a
producer for its last link only: ``copy/commercial_units.json`` is authored by
``copy-planner``. The two links before it had no artifact at all, so a commercial strategy
could be decided without anything recording it. A reviewer could not answer "what was A
arguing, and where does it differ from C?" without watching three videos and guessing.

What this module is
-------------------
The contract. It parses, validates, renders and diffs one Commercial Strategy document.
It does not *generate* one: no model, no provider, no network, no media, no creative
logic, no hooks, no copy. A producer - a human, an Agent, or a future Commercial
Intelligence module - authors the document, and this module decides whether the document
is well formed enough to be consumed once a consumer is wired.

Four layers are kept apart on purpose, because collapsing them is how a strategy becomes
a claim the footage cannot support:

===========================  ==========================================  =================
Layer                        Question it answers                          Where it lives
===========================  ==========================================  =================
PRODUCT FACT                 what the product is                          ``product_facts``
CONSUMER INSIGHT             what the producer believes about the buyer    ``consumer_insight``
COMMERCIAL CLAIM             what the piece may assert                    ``claim_boundary``
FINAL COPY                   the words that will be spoken                NOT IN THIS CONTRACT
===========================  ==========================================  =================

There is deliberately no field for final copy, voice-over lines, subtitles, or the CTA
wording. A document that carries one is refused for an unsupported key. This contract
carries *direction*; the copy remains ``copy-planner``'s artifact.

Evidence safety
---------------
A strategy may not promote a claim the material cannot support:

* every ``ALLOWED`` claim must name a Product Fact this document's own permitted list
  holds, so a claim cannot be invented into existence by declaring it;
* an ``ALLOWED`` claim that also names evidence must name evidence this document marks
  ``PRESENT`` - a claim resting on ``ABSENT`` evidence is refused, which is what keeps a
  product fact the footage does not show at ``CONDITIONAL``;
* a variant may only USE claims that are ``ALLOWED``: using a ``CONDITIONAL`` claim as
  though its condition held is refused, and a ``FORBIDDEN`` claim can never be used;
* :func:`validate_against_product_facts` re-binds the document to the authoritative
  permitted-fact list a caller actually read.

Recorded limitation
-------------------
Like ``artifact_reference``, this contract does not read files and does not resolve paths.
It proves that a claim references a permitted fact *as this document declares it*, and
that the fact document is bound by ``{ref, sha256}``. It cannot prove that the referenced
bytes still match, and it does not decide that a stale strategy is still valid. A consumer
that needs that must call ``validate_reference_binding`` on the artifact it actually read.

Status
------
CONTRACT_ONLY and NOT_WIRED, following the precedent this repository already set for
``planning_evidence.v1``: the shape is defined, validated and tested, and **nothing in
production writes or reads one yet**. No producer is registered for the artifact, no
production stage requires it, and the frozen production chain is untouched. The honest
status is recorded here, in the JSON schema, and in ``docs/contracts/``, so a validated
contract is never mistaken for a shipped capability.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Mapping, Sequence

from .artifact_reference import (
    ArtifactReference,
    ArtifactReferenceError,
    parse_artifact_reference,
    validate_logical_ref,
    validate_sha256,
)
from .intervention_ledger import ACTORS


SCHEMA_VERSION = "commercial_strategy.v1"

#: Canonical workspace-relative location suggested for this artifact.
CANONICAL_REF = "strategy/commercial_strategy.json"

#: Honest implementation state. The shape is defined and validated; nothing in production
#: writes or reads one yet, and no producer is registered for the artifact.
IMPLEMENTATION = "CONTRACT_ONLY"

#: Wiring status, in the production chain manifest's vocabulary: no stage requires this
#: artifact, so it is not reachable from the fast path.
WIRING_STATUS = "NOT_WIRED"

#: The closed vocabulary this contract owns. A claim is in exactly one of these states.
CLAIM_STATES = ("ALLOWED", "CONDITIONAL", "FORBIDDEN")

#: Whether the material can currently show what an evidence item describes.
EVIDENCE_PRESENCE = ("PRESENT", "ABSENT")

#: A logical identifier: letters, digits, and the separators ``. _ : -``. This is the
#: vocabulary ``candidate_evidence.v1`` already uses, so the two contracts agree on what
#: an identifier looks like. Markets, platforms, objectives, persuasion jobs and every id
#: are caller-owned values, so no example value is hardcoded here as an enum.
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

_DOCUMENT_KEYS = (
    "schema_version",
    "strategy_id",
    "market",
    "platform",
    "objective",
    "product",
    "target_consumer",
    "consumer_insight",
    "product_facts",
    "visual_evidence_boundary",
    "claim_boundary",
    "variants",
    "provenance",
)
_PRODUCT_KEYS = ("name",)
_INSIGHT_KEYS = ("insight_id", "statement")
_FACT_KEYS = ("ref", "sha256", "allowed_fact_refs")
_EVIDENCE_KEYS = ("ref", "sha256", "items")
_EVIDENCE_ITEM_KEYS = ("evidence_id", "statement", "presence")
_CLAIM_BOUNDARY_KEYS = ("allowed", "conditional", "forbidden")
_ALLOWED_CLAIM_KEYS = ("claim_id", "statement", "product_fact_ref", "evidence_ref")
_CONDITIONAL_CLAIM_KEYS = (
    "claim_id",
    "statement",
    "product_fact_ref",
    "requires_evidence_ref",
    "condition",
)
_FORBIDDEN_CLAIM_KEYS = ("claim_id", "statement", "reason")
_VARIANT_KEYS = (
    "variant_id",
    "persuasion_job",
    "hook_strategy",
    "copy_direction",
    "cta_direction",
    "claims_used",
)
_PROVENANCE_KEYS = ("authored_by", "based_on")
_AUTHOR_KEYS = ("actor", "producer_id")

#: The per-variant fields a benchmark may vary. Everything else is document level, which is
#: how "the variants share one market, one evidence boundary and one claim boundary" is
#: enforced structurally rather than merely promised in prose.
VARIANT_STRATEGY_FIELDS = (
    "persuasion_job",
    "hook_strategy",
    "copy_direction",
    "cta_direction",
    "claims_used",
)


class CommercialStrategyContractError(ValueError):
    """Raised when a Commercial Strategy cannot be consumed safely."""


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise CommercialStrategyContractError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise CommercialStrategyContractError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise CommercialStrategyContractError(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise CommercialStrategyContractError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or _TOKEN_PATTERN.fullmatch(value) is None:
        raise CommercialStrategyContractError(
            f"{label} must be a logical identifier matching "
            f"{_TOKEN_PATTERN.pattern!r}"
        )
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CommercialStrategyContractError(f"{label} must be a non-empty string")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)


def _text_list(value: object, label: str) -> tuple[str, ...]:
    items = _array(value, label)
    if not items:
        raise CommercialStrategyContractError(f"{label} must not be empty")
    return tuple(
        _text(raw, f"{label}[{index}]") for index, raw in enumerate(items)
    )


def _token_list(value: object, label: str) -> tuple[str, ...]:
    items = _array(value, label)
    return tuple(
        _token(raw, f"{label}[{index}]") for index, raw in enumerate(items)
    )


def _distinct(values: Sequence[str], label: str) -> None:
    seen: set[str] = set()
    repeats: list[str] = []
    for value in values:
        if value in seen:
            repeats.append(value)
        seen.add(value)
    if repeats:
        raise CommercialStrategyContractError(
            f"{label} must not repeat: {', '.join(sorted(set(repeats)))}"
        )


def _reference(mapping: Mapping[str, object], keys: Sequence[str], label: str) -> ArtifactReference:
    try:
        return ArtifactReference(
            validate_logical_ref(mapping[keys[0]], f"{label}.{keys[0]}"),
            validate_sha256(mapping[keys[1]], f"{label}.{keys[1]}"),
        )
    except ArtifactReferenceError as exc:
        raise CommercialStrategyContractError(str(exc)) from exc


@dataclass(frozen=True)
class ConsumerInsight:
    """What the producer believes about the buyer. A belief, never a claim.

    An insight id is not a claim id and cannot be used as one: no field of this contract
    accepts an insight as something the video may assert.
    """

    insight_id: str
    statement: str

    def __post_init__(self) -> None:
        _token(self.insight_id, "consumer_insight.insight_id")
        _text(self.statement, "consumer_insight.statement")

    def as_dict(self) -> dict[str, object]:
        return {"insight_id": self.insight_id, "statement": self.statement}


@dataclass(frozen=True)
class ProductFactBinding:
    """The permitted commercial facts, plus the artifact that states them.

    Deliberately the same shape as ``candidate_evidence.ProductFacts`` - the same three
    keys with the same meaning and the same normalisation. The *shape* is shared so the
    repository has one fact vocabulary rather than two; the *authority* is the referenced
    document, which is why this binding carries ``ref`` and ``sha256``.

    This is a bound snapshot, not a second fact system: a claim can only be ALLOWED if it
    names a fact this list holds, and the list itself is pinned to the document it was
    taken from. It does not read that document; see the module docstring.
    """

    ref: str
    sha256: str
    allowed_fact_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        try:
            validate_logical_ref(self.ref, "product_facts.ref")
            validate_sha256(self.sha256, "product_facts.sha256")
        except ArtifactReferenceError as exc:
            raise CommercialStrategyContractError(str(exc)) from exc
        facts = _token_list(
            list(self.allowed_fact_refs), "product_facts.allowed_fact_refs"
        )
        if not facts:
            raise CommercialStrategyContractError(
                "product_facts.allowed_fact_refs must not be empty"
            )
        _distinct(facts, "product_facts.allowed_fact_refs")
        object.__setattr__(self, "allowed_fact_refs", tuple(sorted(facts)))

    @property
    def reference(self) -> ArtifactReference:
        return ArtifactReference(self.ref, self.sha256)

    def permits(self, fact_ref: str) -> bool:
        return fact_ref in self.allowed_fact_refs

    def as_dict(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "sha256": self.sha256,
            "allowed_fact_refs": list(self.allowed_fact_refs),
        }


@dataclass(frozen=True)
class EvidenceItem:
    """One thing the material can or cannot currently show."""

    evidence_id: str
    statement: str
    presence: str

    def __post_init__(self) -> None:
        _token(self.evidence_id, "evidence_item.evidence_id")
        _text(self.statement, "evidence_item.statement")
        if self.presence not in EVIDENCE_PRESENCE:
            raise CommercialStrategyContractError(
                f"evidence_item.presence must be one of: {', '.join(EVIDENCE_PRESENCE)}"
            )

    @property
    def is_present(self) -> bool:
        return self.presence == "PRESENT"

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "statement": self.statement,
            "presence": self.presence,
        }


@dataclass(frozen=True)
class EvidenceBoundary:
    """What the current material can prove, and what it cannot, as one bound document."""

    ref: str
    sha256: str
    items: tuple[EvidenceItem, ...]

    def __post_init__(self) -> None:
        try:
            validate_logical_ref(self.ref, "visual_evidence_boundary.ref")
            validate_sha256(self.sha256, "visual_evidence_boundary.sha256")
        except ArtifactReferenceError as exc:
            raise CommercialStrategyContractError(str(exc)) from exc
        if not self.items:
            raise CommercialStrategyContractError(
                "visual_evidence_boundary.items must not be empty"
            )
        _distinct(
            [item.evidence_id for item in self.items],
            "visual_evidence_boundary.items",
        )

    @property
    def reference(self) -> ArtifactReference:
        return ArtifactReference(self.ref, self.sha256)

    def presence_of(self, evidence_id: str) -> str | None:
        for item in self.items:
            if item.evidence_id == evidence_id:
                return item.presence
        return None

    def as_dict(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "sha256": self.sha256,
            "items": [item.as_dict() for item in self.items],
        }


@dataclass(frozen=True)
class AllowedClaim:
    """A claim the piece may make, and the fact plus evidence it rests on."""

    claim_id: str
    statement: str
    product_fact_ref: str
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        _token(self.claim_id, "allowed_claim.claim_id")
        _text(self.statement, "allowed_claim.statement")
        _token(self.product_fact_ref, "allowed_claim.product_fact_ref")
        _optional_text(self.evidence_ref, "allowed_claim.evidence_ref")

    def as_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "product_fact_ref": self.product_fact_ref,
            "evidence_ref": self.evidence_ref,
        }


@dataclass(frozen=True)
class ConditionalClaim:
    """A claim that is only meaningful once its condition holds.

    An unproven product fact belongs here rather than in ``allowed``: a fact can exist
    while the material does not yet show it.
    """

    claim_id: str
    statement: str
    product_fact_ref: str
    condition: str
    requires_evidence_ref: str | None = None

    def __post_init__(self) -> None:
        _token(self.claim_id, "conditional_claim.claim_id")
        _text(self.statement, "conditional_claim.statement")
        _token(self.product_fact_ref, "conditional_claim.product_fact_ref")
        _text(self.condition, "conditional_claim.condition")
        _optional_text(
            self.requires_evidence_ref, "conditional_claim.requires_evidence_ref"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "product_fact_ref": self.product_fact_ref,
            "requires_evidence_ref": self.requires_evidence_ref,
            "condition": self.condition,
        }


@dataclass(frozen=True)
class ForbiddenClaim:
    """A claim the piece may never make, with the reason recorded."""

    claim_id: str
    statement: str
    reason: str

    def __post_init__(self) -> None:
        _token(self.claim_id, "forbidden_claim.claim_id")
        _text(self.statement, "forbidden_claim.statement")
        _text(self.reason, "forbidden_claim.reason")

    def as_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ClaimBoundary:
    """The three claim states. A claim id lives in exactly one of them."""

    allowed: tuple[AllowedClaim, ...]
    conditional: tuple[ConditionalClaim, ...]
    forbidden: tuple[ForbiddenClaim, ...]

    def __post_init__(self) -> None:
        claim_ids = [claim.claim_id for claim in self.allowed]
        claim_ids += [claim.claim_id for claim in self.conditional]
        claim_ids += [claim.claim_id for claim in self.forbidden]
        if not claim_ids:
            raise CommercialStrategyContractError(
                "claim_boundary must state at least one claim; a boundary that says "
                "nothing is not a boundary"
            )
        # One id in two states is a contradiction, and a contradiction is how a forbidden
        # claim would be smuggled back in as an allowed one.
        _distinct(claim_ids, "claim_boundary.claim_id")

    @property
    def allowed_ids(self) -> tuple[str, ...]:
        return tuple(claim.claim_id for claim in self.allowed)

    @property
    def conditional_ids(self) -> tuple[str, ...]:
        return tuple(claim.claim_id for claim in self.conditional)

    @property
    def forbidden_ids(self) -> tuple[str, ...]:
        return tuple(claim.claim_id for claim in self.forbidden)

    def state_of(self, claim_id: str) -> str | None:
        for state, ids in (
            ("ALLOWED", self.allowed_ids),
            ("CONDITIONAL", self.conditional_ids),
            ("FORBIDDEN", self.forbidden_ids),
        ):
            if claim_id in ids:
                return state
        return None

    def as_dict(self) -> dict[str, object]:
        return {
            "allowed": [claim.as_dict() for claim in self.allowed],
            "conditional": [claim.as_dict() for claim in self.conditional],
            "forbidden": [claim.as_dict() for claim in self.forbidden],
        }


@dataclass(frozen=True)
class StrategyVariant:
    """One version of the piece: the fields a benchmark is allowed to vary."""

    variant_id: str
    persuasion_job: str
    hook_strategy: str
    copy_direction: tuple[str, ...]
    cta_direction: str
    claims_used: tuple[str, ...]

    def __post_init__(self) -> None:
        _token(self.variant_id, "variant.variant_id")
        _token(self.persuasion_job, "variant.persuasion_job")
        _text(self.hook_strategy, "variant.hook_strategy")
        object.__setattr__(
            self,
            "copy_direction",
            _text_list(list(self.copy_direction), "variant.copy_direction"),
        )
        _text(self.cta_direction, "variant.cta_direction")
        used = _token_list(list(self.claims_used), "variant.claims_used")
        _distinct(used, "variant.claims_used")
        object.__setattr__(self, "claims_used", used)

    def as_dict(self) -> dict[str, object]:
        return {
            "variant_id": self.variant_id,
            "persuasion_job": self.persuasion_job,
            "hook_strategy": self.hook_strategy,
            "copy_direction": list(self.copy_direction),
            "cta_direction": self.cta_direction,
            "claims_used": list(self.claims_used),
        }


@dataclass(frozen=True)
class StrategyAuthor:
    """Who produced the strategy, in the ledger's own actor vocabulary."""

    actor: str
    producer_id: str

    def __post_init__(self) -> None:
        if self.actor not in ACTORS:
            raise CommercialStrategyContractError(
                f"provenance.authored_by.actor must be one of: {', '.join(ACTORS)}"
            )
        _token(self.producer_id, "provenance.authored_by.producer_id")

    def as_dict(self) -> dict[str, object]:
        return {"actor": self.actor, "producer_id": self.producer_id}


@dataclass(frozen=True)
class StrategyProvenance:
    """Auditable external provenance, and nothing else.

    No timestamp: the document must render identically from identical input, and when an
    author acted belongs to ``intervention_ledger.jsonl``. No prompt, no reasoning, no
    provider transcript - only who authored it and which revisions it was authored against.
    """

    authored_by: StrategyAuthor
    based_on: tuple[ArtifactReference, ...]

    def __post_init__(self) -> None:
        if not self.based_on:
            raise CommercialStrategyContractError(
                "provenance.based_on must name the artifact(s) this strategy was authored "
                "against"
            )
        _distinct([reference.ref for reference in self.based_on], "provenance.based_on")

    def reference_for(self, ref: str) -> ArtifactReference | None:
        for reference in self.based_on:
            if reference.ref == ref:
                return reference
        return None

    def as_dict(self) -> dict[str, object]:
        return {
            "authored_by": self.authored_by.as_dict(),
            "based_on": [reference.as_dict() for reference in self.based_on],
        }


@dataclass(frozen=True)
class CommercialStrategy:
    """One validated Commercial Strategy document."""

    strategy_id: str
    market: str
    platform: str
    objective: str
    product_name: str
    target_consumer: str
    consumer_insight: tuple[ConsumerInsight, ...]
    product_facts: ProductFactBinding
    visual_evidence_boundary: EvidenceBoundary
    claim_boundary: ClaimBoundary
    variants: tuple[StrategyVariant, ...]
    provenance: StrategyProvenance

    def __post_init__(self) -> None:
        _token(self.strategy_id, "strategy_id")
        _token(self.market, "market")
        _token(self.platform, "platform")
        _token(self.objective, "objective")
        _text(self.product_name, "product.name")
        _text(self.target_consumer, "target_consumer")
        if not self.consumer_insight:
            raise CommercialStrategyContractError("consumer_insight must not be empty")
        _distinct(
            [insight.insight_id for insight in self.consumer_insight],
            "consumer_insight.insight_id",
        )
        if not self.variants:
            raise CommercialStrategyContractError("variants must not be empty")
        _distinct([variant.variant_id for variant in self.variants], "variant_id")
        self._assert_claims_are_supported()
        self._assert_variants_use_allowed_claims_only()
        self._assert_provenance_binds_the_declared_artifacts()

    # ------------------------------------------------------------------ invariants

    def _assert_claims_are_supported(self) -> None:
        """A claim may not be promoted past what the contract can stand behind."""

        facts = self.product_facts
        boundary = self.visual_evidence_boundary

        for claim in self.claim_boundary.allowed:
            if not facts.permits(claim.product_fact_ref):
                raise CommercialStrategyContractError(
                    f"allowed claim {claim.claim_id!r} names Product Fact "
                    f"{claim.product_fact_ref!r}, which product_facts does not permit"
                )
            if claim.evidence_ref is None:
                continue
            presence = boundary.presence_of(claim.evidence_ref)
            if presence is None:
                raise CommercialStrategyContractError(
                    f"allowed claim {claim.claim_id!r} references evidence "
                    f"{claim.evidence_ref!r}, which visual_evidence_boundary does not declare"
                )
            if presence != "PRESENT":
                raise CommercialStrategyContractError(
                    f"allowed claim {claim.claim_id!r} rests on evidence "
                    f"{claim.evidence_ref!r}, which the material records as {presence}; a "
                    "claim the material cannot show may not be ALLOWED"
                )

        for conditional in self.claim_boundary.conditional:
            if not facts.permits(conditional.product_fact_ref):
                raise CommercialStrategyContractError(
                    f"conditional claim {conditional.claim_id!r} names Product Fact "
                    f"{conditional.product_fact_ref!r}, which product_facts does not permit"
                )
            if conditional.requires_evidence_ref is None:
                continue
            if boundary.presence_of(conditional.requires_evidence_ref) is None:
                raise CommercialStrategyContractError(
                    f"conditional claim {conditional.claim_id!r} references evidence "
                    f"{conditional.requires_evidence_ref!r}, which visual_evidence_boundary "
                    "does not declare"
                )

    def _assert_variants_use_allowed_claims_only(self) -> None:
        """The one door: a variant lists the claims it intends to make."""

        for variant in self.variants:
            for claim_id in variant.claims_used:
                state = self.claim_boundary.state_of(claim_id)
                if state == "ALLOWED":
                    continue
                if state == "CONDITIONAL":
                    raise CommercialStrategyContractError(
                        f"variant {variant.variant_id!r} uses conditional claim "
                        f"{claim_id!r} as though its condition held; a conditional claim "
                        "may only be used once the evidence it requires exists"
                    )
                if state == "FORBIDDEN":
                    raise CommercialStrategyContractError(
                        f"variant {variant.variant_id!r} uses forbidden claim {claim_id!r}; "
                        "a forbidden claim may never be used by a variant"
                    )
                raise CommercialStrategyContractError(
                    f"variant {variant.variant_id!r} uses claim {claim_id!r}, which "
                    "claim_boundary does not declare"
                )

    def _assert_provenance_binds_the_declared_artifacts(self) -> None:
        """Provenance must name the exact revisions the strategy was authored against."""

        for label, reference in (
            ("product_facts", self.product_facts.reference),
            ("visual_evidence_boundary", self.visual_evidence_boundary.reference),
        ):
            declared = self.provenance.reference_for(reference.ref)
            if declared is None:
                raise CommercialStrategyContractError(
                    f"provenance.based_on does not name {label}.ref {reference.ref!r}"
                )
            if declared.sha256 != reference.sha256:
                raise CommercialStrategyContractError(
                    f"provenance.based_on disagrees with {label}.sha256 for "
                    f"{reference.ref!r}"
                )

    # ---------------------------------------------------------------------- output

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "strategy_id": self.strategy_id,
            "market": self.market,
            "platform": self.platform,
            "objective": self.objective,
            "product": {"name": self.product_name},
            "target_consumer": self.target_consumer,
            "consumer_insight": [
                insight.as_dict() for insight in self.consumer_insight
            ],
            "product_facts": self.product_facts.as_dict(),
            "visual_evidence_boundary": self.visual_evidence_boundary.as_dict(),
            "claim_boundary": self.claim_boundary.as_dict(),
            "variants": [variant.as_dict() for variant in self.variants],
            "provenance": self.provenance.as_dict(),
        }

    def variant(self, variant_id: str) -> StrategyVariant:
        for variant in self.variants:
            if variant.variant_id == variant_id:
                return variant
        raise CommercialStrategyContractError(f"unknown variant_id {variant_id!r}")


def parse_product_facts(document: object) -> ProductFactBinding:
    """Parse the ``product_facts`` block shared by this contract family.

    Extracted so a second contract can consume the same fact binding rather than
    reimplementing it. One parser means one fact vocabulary, not two.
    """

    facts = _object(document, "product_facts")
    _exact_keys(facts, _FACT_KEYS, "product_facts")
    return ProductFactBinding(
        facts["ref"],  # type: ignore[arg-type]
        facts["sha256"],  # type: ignore[arg-type]
        tuple(
            _token(raw, f"product_facts.allowed_fact_refs[{index}]")
            for index, raw in enumerate(
                _array(facts["allowed_fact_refs"], "product_facts.allowed_fact_refs")
            )
        ),
    )


def parse_evidence_boundary(document: object) -> EvidenceBoundary:
    """Parse the ``visual_evidence_boundary`` block shared by this contract family."""

    evidence = _object(document, "visual_evidence_boundary")
    _exact_keys(evidence, _EVIDENCE_KEYS, "visual_evidence_boundary")
    items: list[EvidenceItem] = []
    for index, raw in enumerate(
        _array(evidence["items"], "visual_evidence_boundary.items")
    ):
        item = _object(raw, f"visual_evidence_boundary.items[{index}]")
        _exact_keys(
            item, _EVIDENCE_ITEM_KEYS, f"visual_evidence_boundary.items[{index}]"
        )
        items.append(
            EvidenceItem(item["evidence_id"], item["statement"], item["presence"])  # type: ignore[arg-type]
        )
    return EvidenceBoundary(
        evidence["ref"],  # type: ignore[arg-type]
        evidence["sha256"],  # type: ignore[arg-type]
        tuple(items),
    )


def parse_claim_boundary(document: object) -> ClaimBoundary:
    """Parse the ``claim_boundary`` block shared by this contract family."""

    claims = _object(document, "claim_boundary")
    _exact_keys(claims, _CLAIM_BOUNDARY_KEYS, "claim_boundary")
    allowed: list[AllowedClaim] = []
    for index, raw in enumerate(_array(claims["allowed"], "claim_boundary.allowed")):
        item = _object(raw, f"claim_boundary.allowed[{index}]")
        _exact_keys(item, _ALLOWED_CLAIM_KEYS, f"claim_boundary.allowed[{index}]")
        allowed.append(
            AllowedClaim(
                item["claim_id"],  # type: ignore[arg-type]
                item["statement"],  # type: ignore[arg-type]
                item["product_fact_ref"],  # type: ignore[arg-type]
                item["evidence_ref"],  # type: ignore[arg-type]
            )
        )
    conditional: list[ConditionalClaim] = []
    for index, raw in enumerate(
        _array(claims["conditional"], "claim_boundary.conditional")
    ):
        item = _object(raw, f"claim_boundary.conditional[{index}]")
        _exact_keys(item, _CONDITIONAL_CLAIM_KEYS, f"claim_boundary.conditional[{index}]")
        conditional.append(
            ConditionalClaim(
                item["claim_id"],  # type: ignore[arg-type]
                item["statement"],  # type: ignore[arg-type]
                item["product_fact_ref"],  # type: ignore[arg-type]
                item["condition"],  # type: ignore[arg-type]
                item["requires_evidence_ref"],  # type: ignore[arg-type]
            )
        )
    forbidden: list[ForbiddenClaim] = []
    for index, raw in enumerate(_array(claims["forbidden"], "claim_boundary.forbidden")):
        item = _object(raw, f"claim_boundary.forbidden[{index}]")
        _exact_keys(item, _FORBIDDEN_CLAIM_KEYS, f"claim_boundary.forbidden[{index}]")
        forbidden.append(
            ForbiddenClaim(
                item["claim_id"],  # type: ignore[arg-type]
                item["statement"],  # type: ignore[arg-type]
                item["reason"],  # type: ignore[arg-type]
            )
        )
    return ClaimBoundary(tuple(allowed), tuple(conditional), tuple(forbidden))


def parse_commercial_strategy(document: object) -> CommercialStrategy:
    """Parse and fully validate one Commercial Strategy. Fail closed, never repair."""

    mapping = _object(document, "commercial strategy")
    _exact_keys(mapping, _DOCUMENT_KEYS, "commercial strategy")
    if mapping["schema_version"] != SCHEMA_VERSION:
        raise CommercialStrategyContractError(
            f"schema_version must be {SCHEMA_VERSION!r}"
        )

    product = _object(mapping["product"], "product")
    _exact_keys(product, _PRODUCT_KEYS, "product")

    insights: list[ConsumerInsight] = []
    for index, raw in enumerate(_array(mapping["consumer_insight"], "consumer_insight")):
        item = _object(raw, f"consumer_insight[{index}]")
        _exact_keys(item, _INSIGHT_KEYS, f"consumer_insight[{index}]")
        insights.append(ConsumerInsight(item["insight_id"], item["statement"]))  # type: ignore[arg-type]

    product_facts = parse_product_facts(mapping["product_facts"])
    boundary = parse_evidence_boundary(mapping["visual_evidence_boundary"])
    claim_boundary = parse_claim_boundary(mapping["claim_boundary"])

    variants: list[StrategyVariant] = []
    for index, raw in enumerate(_array(mapping["variants"], "variants")):
        item = _object(raw, f"variants[{index}]")
        _exact_keys(item, _VARIANT_KEYS, f"variants[{index}]")
        variants.append(
            StrategyVariant(
                item["variant_id"],  # type: ignore[arg-type]
                item["persuasion_job"],  # type: ignore[arg-type]
                item["hook_strategy"],  # type: ignore[arg-type]
                tuple(_text_list(item["copy_direction"], f"variants[{index}].copy_direction")),
                item["cta_direction"],  # type: ignore[arg-type]
                tuple(_token_list(item["claims_used"], f"variants[{index}].claims_used")),
            )
        )

    provenance = _object(mapping["provenance"], "provenance")
    _exact_keys(provenance, _PROVENANCE_KEYS, "provenance")
    author = _object(provenance["authored_by"], "provenance.authored_by")
    _exact_keys(author, _AUTHOR_KEYS, "provenance.authored_by")
    based_on: list[ArtifactReference] = []
    for index, raw in enumerate(_array(provenance["based_on"], "provenance.based_on")):
        based_on.append(
            parse_artifact_reference(
                _object(raw, f"provenance.based_on[{index}]"),
                label=f"provenance.based_on[{index}]",
            )
        )

    return CommercialStrategy(
        strategy_id=mapping["strategy_id"],  # type: ignore[arg-type]
        market=mapping["market"],  # type: ignore[arg-type]
        platform=mapping["platform"],  # type: ignore[arg-type]
        objective=mapping["objective"],  # type: ignore[arg-type]
        product_name=product["name"],  # type: ignore[arg-type]
        target_consumer=mapping["target_consumer"],  # type: ignore[arg-type]
        consumer_insight=tuple(insights),
        product_facts=product_facts,
        visual_evidence_boundary=boundary,
        claim_boundary=claim_boundary,
        variants=tuple(variants),
        provenance=StrategyProvenance(
            StrategyAuthor(author["actor"], author["producer_id"]),  # type: ignore[arg-type]
            tuple(based_on),
        ),
    )


def render_commercial_strategy(strategy: CommercialStrategy) -> str:
    """Canonical one-document rendering. Identical input renders identical bytes."""

    if not isinstance(strategy, CommercialStrategy):
        raise CommercialStrategyContractError("strategy must be a CommercialStrategy")
    return json.dumps(
        strategy.as_dict(), ensure_ascii=False, sort_keys=True, indent=2
    ) + "\n"


def validate_against_product_facts(
    strategy: CommercialStrategy, allowed_fact_refs: Sequence[object]
) -> None:
    """Re-bind the strategy to the authoritative permitted-fact list.

    The two-artifact pattern the repository already uses: :func:`parse_commercial_strategy`
    validates the document alone, and this binds it to the facts document a caller actually
    read. Both the document's declared list and every claim's reference must be inside the
    authority, so a drifted snapshot cannot outlive the facts it was taken from. It cannot
    check that the reference still hashes to the authority; a caller that has the bytes
    should call ``validate_reference_binding`` first.
    """

    if not isinstance(strategy, CommercialStrategy):
        raise CommercialStrategyContractError("strategy must be a CommercialStrategy")
    authority = {
        _token(raw, f"allowed_fact_refs[{index}]")
        for index, raw in enumerate(allowed_fact_refs)
    }
    if not authority:
        raise CommercialStrategyContractError("allowed_fact_refs must not be empty")
    outside = sorted(set(strategy.product_facts.allowed_fact_refs) - authority)
    if outside:
        raise CommercialStrategyContractError(
            "product_facts declares fact(s) the authority does not permit: "
            + ", ".join(outside)
        )
    for claim in list(strategy.claim_boundary.allowed) + list(
        strategy.claim_boundary.conditional
    ):
        if claim.product_fact_ref not in authority:
            raise CommercialStrategyContractError(
                f"claim {claim.claim_id!r} names Product Fact "
                f"{claim.product_fact_ref!r}, which the authority does not permit"
            )


def strategy_differences(strategy: CommercialStrategy) -> dict[str, object]:
    """What the variants share, and exactly where they differ.

    This is the answer to "how are A, B and C actually different", produced from the
    document rather than by watching three videos. Nothing here guesses: every differing
    field is reported with each variant's own value.
    """

    if not isinstance(strategy, CommercialStrategy):
        raise CommercialStrategyContractError("strategy must be a CommercialStrategy")
    shared = {
        "market": strategy.market,
        "platform": strategy.platform,
        "objective": strategy.objective,
        "product_name": strategy.product_name,
        "target_consumer": strategy.target_consumer,
        "target_consumer_insight_ids": sorted(
            insight.insight_id for insight in strategy.consumer_insight
        ),
        "product_facts": strategy.product_facts.reference.as_dict(),
        "visual_evidence_boundary": strategy.visual_evidence_boundary.reference.as_dict(),
        "allowed_claim_ids": sorted(strategy.claim_boundary.allowed_ids),
        "conditional_claim_ids": sorted(strategy.claim_boundary.conditional_ids),
        "forbidden_claim_ids": sorted(strategy.claim_boundary.forbidden_ids),
    }
    per_variant = {
        variant.variant_id: variant.as_dict() for variant in strategy.variants
    }
    differing: list[str] = []
    for field_name in VARIANT_STRATEGY_FIELDS:
        values = {
            variant.variant_id: variant.as_dict()[field_name]
            for variant in strategy.variants
        }
        if len({json.dumps(value, sort_keys=True) for value in values.values()}) > 1:
            differing.append(field_name)
    return {
        "schema_version": "commercial_strategy_diff.v1",
        "strategy_id": strategy.strategy_id,
        "shared": shared,
        "variants": per_variant,
        "differing_fields": sorted(differing),
        "identical_fields": sorted(set(VARIANT_STRATEGY_FIELDS) - set(differing)),
    }


__all__ = [
    "CANONICAL_REF",
    "CLAIM_STATES",
    "CommercialStrategy",
    "CommercialStrategyContractError",
    "ConditionalClaim",
    "ConsumerInsight",
    "EvidenceBoundary",
    "EvidenceItem",
    "EVIDENCE_PRESENCE",
    "ForbiddenClaim",
    "IMPLEMENTATION",
    "AllowedClaim",
    "ClaimBoundary",
    "ProductFactBinding",
    "SCHEMA_VERSION",
    "StrategyAuthor",
    "StrategyProvenance",
    "StrategyVariant",
    "VARIANT_STRATEGY_FIELDS",
    "WIRING_STATUS",
    "parse_claim_boundary",
    "parse_commercial_strategy",
    "parse_evidence_boundary",
    "parse_product_facts",
    "render_commercial_strategy",
    "strategy_differences",
    "validate_against_product_facts",
]
