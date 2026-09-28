"""Commercial Copy v1: what this piece actually says, and what it is allowed to say.

Where this sits
---------------
    Commercial Intelligence  ->  Selected Commercial Strategy  ->  Commercial Copy
                                                                 ->  TTS / Audio / Timeline / Editing

Commercial Copy answers one question: *given that this variant has already decided how to
sell, how should this video actually express it?* It does not decide how the video should
be sold. It cannot change the strategy it binds: if the selected strategy cannot be
executed, the copy is BLOCKED and says so, rather than quietly selling something else.

Two layers, one artifact
------------------------
Every speech segment carries both layers, and they are deliberately not the same field:

    SEMANTIC INTENT        language-independent: what this segment is allowed to mean
    LOCALIZED SPOKEN COPY  the natural wording in the target language

Localization controls **how to say it**, never **what may be said**. It may not add a
product fact, a claim, a promised result, a compatibility promise, or a consumer-research
conclusion that the semantic intent did not already carry.

What this module is, and is not
-------------------------------
It is the contract and the deterministic half: parse, validate, bind, derive, diff. It is
**not** a copywriter. There is no template, no phrase bank, no generator and no model call
here, and there is deliberately no ``SYSTEM_GENERATED`` authoring mode, because no system
generation capability exists at this baseline. Copy is authored by an Agent or a human and
validated by this module, and the artifact records exactly that.

The back-check is a recorded judgement, not natural language understanding
----------------------------------------------------------------------------
After localization there is a formal **semantic back-check**: did the localised line add a
claim, expand one, drop a qualifier, turn a possibility into a certainty, or invent a
product fact? Python cannot answer that by reading Indonesian, and this contract does not
pretend it can. What the contract *does* enforce mechanically is that the question is asked
for every speech segment exactly once, and that the verdict is **derived** from the recorded
findings rather than asserted beside them: any finding that admits an exceedance forces
``FAIL``, and the stored verdict must equal the derived one. An artifact therefore cannot
record "this line added a claim" and still read ``READY``.

What the boundaries are, and where they live
--------------------------------------------
This artifact carries **no** second copy of the facts, evidence or claim boundary. It binds
the strategy document by ``{ref, sha256}``, names the selected variant, and repeats only the
two boundary references that have authorities of their own. ``validate_commercial_copy``
then binds it to the actual strategy: the same fact and evidence revisions, a declared
variant, the same market, and only claim references the selected variant selected. The
claim boundary travels with the bound strategy, and that is recorded as a limitation rather
than hidden: at this baseline it has no standalone artifact of its own.

Speech budget, not timing
-------------------------
A segment may carry a **soft** time budget - a target and an acceptable range - because the
copy layer has to know roughly how much it can say. It may not carry anything frame-accurate:
exact placement, frame counts and compiled timelines belong to the timeline and audio
stages. Every number in this contract is a duration in seconds, named ``*_seconds``; any
other number anywhere is refused.

Designed silence is not an empty track
--------------------------------------
A ``DESIGNED_SILENCE`` segment means there is no voice-over there, and that a visual
carries the moment instead. It must state what continues (``bed_note``), it must cite the
evidence that carries it, and it carries no localised line. This contract has no way to
express "mute the track", because that is not what it means: the environment and evidence
sound continue. Mixing is not this layer's decision.

Status
------
CONTRACT_ONLY and NOT_WIRED, following ``planning_evidence.v1``, ``commercial_strategy.v1``
and ``commercial_intelligence.v1``: the shape is defined, validated and tested, and nothing
in production writes or reads one yet. No producer is registered and the frozen production
chain is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Callable, Mapping, Sequence, TypeVar

from .artifact_reference import (
    ArtifactReference,
    ArtifactReferenceError,
    parse_artifact_reference,
)
from .commercial_intelligence import (
    CONTEXT_SOURCES,
    UNSPECIFIED_PLATFORM,
    claim_availability,
)
from .commercial_strategy import (
    CommercialStrategy,
    CommercialStrategyContractError,
    StrategyAuthor,
)


SCHEMA_VERSION = "commercial_copy.v1"

#: Canonical workspace-relative location suggested for this artifact. It stays in the
#: strategy domain because it belongs to the intelligence/strategy/copy lineage and does
#: **not** replace the legacy ``copy/commercial_units.json`` production artifact.
CANONICAL_REF = "strategy/commercial_copy.json"

#: Honest implementation state. The shape is defined and validated; nothing in production
#: writes or reads one yet, and no producer is registered for the artifact.
IMPLEMENTATION = "CONTRACT_ONLY"

#: Wiring status, in the production chain manifest's vocabulary.
WIRING_STATUS = "NOT_WIRED"

#: The Skill this artifact is authored under. Recorded in the artifact so a reader can tell
#: which role produced it; the specification lives in ``docs/skills/commercial-copy-v1.md``.
SKILL_NAME = "commercial-copy"
SKILL_VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")

#: The validator this artifact records having been checked against.
VALIDATOR_NAME = "commercial_copy.validate_commercial_copy"

#: Closed vocabulary this contract owns: whether a segment speaks or is deliberately silent.
DELIVERY = ("SPEECH", "DESIGNED_SILENCE")

#: Status. Stored and verified against the derivation rather than asserted: see
#: :attr:`CommercialCopy.status`.
STATUSES = ("READY", "BLOCKED")

#: How the copy was authored. There is deliberately no ``SYSTEM_GENERATED``: no system
#: generation capability exists at this baseline, so an artifact may not claim one.
AUTHORING_MODES = ("AGENT_AUTHORED", "HUMAN_AUTHORED")

#: The back-check questions. Each is answered for every speech segment, and any ``true``
#: forces a ``FAIL``.
BACK_CHECK_FLAGS = (
    "adds_claim",
    "expands_claim",
    "drops_qualifier",
    "possibility_as_certainty",
    "unauthorised_product_fact",
)

#: The back-check verdict vocabulary.
BACK_CHECK_VERDICTS = ("PASS", "FAIL")

#: Why a copy could not be produced. Closed, so a blockage is comparable across jobs.
BLOCK_REASON_CODES = (
    "STRATEGY_NOT_EXECUTABLE",
    "STRATEGY_REQUIRES_UNSUPPORTED_CLAIM",
    "CLAIM_FORBIDDEN_BY_BOUNDARY",
    "CONDITIONAL_CLAIM_UNSATISFIED",
    "REQUIRED_EVIDENCE_ABSENT",
    "INPUT_ARTIFACTS_CONTRADICT",
    "OUT_OF_ALLOWED_SEMANTIC_SCOPE",
    "BUDGET_IMPOSSIBLE",
)

#: Where a blockage has to be resolved. Each names an upstream area, never this layer.
RETURN_TARGETS = (
    "COMMERCIAL_INTELLIGENCE",
    "COMMERCIAL_STRATEGY",
    "PRODUCT_FACTS",
    "VISUAL_EVIDENCE",
    "CLAIM_BOUNDARY",
)

#: A logical identifier: letters, digits, and the separators ``. _ : -``.
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

#: The only numeric fields this contract may carry are durations.
_SECONDS_SUFFIX = "_seconds"

_DOCUMENT_KEYS = (
    "schema_version",
    "copy_id",
    "context",
    "strategy",
    "boundaries",
    "segments",
    "semantic_back_check",
    "blocking",
    "status",
    "provenance",
)
_CONTEXT_KEYS = ("market", "language", "platform", "platform_source")
_STRATEGY_KEYS = ("ref", "sha256", "variant_id")
_BOUNDARY_KEYS = ("product_facts", "visual_evidence_boundary")
_SEGMENT_KEYS = (
    "segment_id",
    "copy_job",
    "delivery",
    "semantic_intent",
    "claim_refs",
    "evidence_refs",
    "budget",
    "localized",
    "designed_silence",
)
_BUDGET_KEYS = ("target_seconds", "acceptable_min_seconds", "acceptable_max_seconds")
_LOCALIZED_KEYS = ("language", "line")
_SILENCE_KEYS = ("reason", "bed_note")
_BACK_CHECK_KEYS = ("findings",)
_FINDING_KEYS = (
    "segment_id",
    "adds_claim",
    "expands_claim",
    "drops_qualifier",
    "possibility_as_certainty",
    "unauthorised_product_fact",
    "detail",
    "verdict",
)
_BLOCKING_KEYS = (
    "segment_id",
    "reason_code",
    "reason",
    "claim_ref",
    "missing",
    "return_to",
)
_PROVENANCE_KEYS = (
    "authoring_mode",
    "authored_by",
    "skill",
    "validation",
    "based_on",
)
_SKILL_KEYS = ("name", "version")
_VALIDATION_KEYS = ("validator",)
_AUTHOR_KEYS = ("actor", "producer_id")


class CommercialCopyContractError(ValueError):
    """Raised when a Commercial Copy cannot be consumed safely."""


# --------------------------------------------------------------------------- plumbing
#
# Per-module plumbing, the existing convention here. The domain types - strategy, facts,
# evidence, claims, the claim-availability derivation - are imported, so those keep one
# implementation rather than three.


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise CommercialCopyContractError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise CommercialCopyContractError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise CommercialCopyContractError(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise CommercialCopyContractError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or _TOKEN_PATTERN.fullmatch(value) is None:
        raise CommercialCopyContractError(
            f"{label} must be a logical identifier matching {_TOKEN_PATTERN.pattern!r}"
        )
    return value


def _line(value: object, label: str) -> str:
    """One line of text: a spoken line, an intent or a reason - never a transcript."""

    if not isinstance(value, str) or not value.strip():
        raise CommercialCopyContractError(f"{label} must be a non-empty string")
    if "\n" in value or "\r" in value:
        raise CommercialCopyContractError(
            f"{label} must be a single line, not a multi-line block"
        )
    return value


def _optional_line(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _line(value, label)


def _token_list(
    value: object, label: str, *, allow_empty: bool = True
) -> tuple[str, ...]:
    items = _array(value, label)
    if not items and not allow_empty:
        raise CommercialCopyContractError(f"{label} must not be empty")
    tokens = tuple(_token(raw, f"{label}[{index}]") for index, raw in enumerate(items))
    _distinct(tokens, label)
    return tokens


def _line_list(
    value: object, label: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    items = _array(value, label)
    if not items and not allow_empty:
        raise CommercialCopyContractError(f"{label} must not be empty")
    lines = tuple(_line(raw, f"{label}[{index}]") for index, raw in enumerate(items))
    _distinct(lines, label)
    return lines


def _distinct(values: Sequence[str], label: str) -> None:
    seen: set[str] = set()
    repeats: list[str] = []
    for value in values:
        if value in seen:
            repeats.append(value)
        seen.add(value)
    if repeats:
        raise CommercialCopyContractError(
            f"{label} must not repeat: {', '.join(sorted(set(repeats)))}"
        )


def _seconds(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CommercialCopyContractError(
            f"{label} must be a duration in seconds (a number)"
        )
    number = float(value)
    if number <= 0:
        raise CommercialCopyContractError(f"{label} must be greater than zero")
    return number


def _reject_unexpected_numbers(document: object, label: str = "commercial copy") -> None:
    """Every number in this contract is a duration, and nothing else may be numeric.

    This is what keeps a fabricated precision - a score, a confidence, a predicted
    performance - out of an artifact that has no performance data behind it. A time budget
    is planning information and is allowed; it is named ``*_seconds``.
    """

    if isinstance(document, dict):
        for key, value in document.items():
            _reject_unexpected_numbers(value, f"{label}.{key}")
        return
    if isinstance(document, list):
        for index, value in enumerate(document):
            _reject_unexpected_numbers(value, f"{label}[{index}]")
        return
    if isinstance(document, bool) or document is None or isinstance(document, str):
        return
    if isinstance(document, (int, float)):
        leaf = label.split(".")[-1]
        if not leaf.endswith(_SECONDS_SUFFIX):
            raise CommercialCopyContractError(
                f"{label} is numeric but not a duration; the only numbers this contract "
                f"may carry are seconds, named '*{_SECONDS_SUFFIX}'"
            )


_T = TypeVar("_T")


def _parse_reference(value: object, label: str) -> ArtifactReference:
    try:
        return parse_artifact_reference(value, label=label)
    except ArtifactReferenceError as exc:
        raise CommercialCopyContractError(str(exc)) from exc


# ------------------------------------------------------------------- context blocks


@dataclass(frozen=True)
class CopyContext:
    """The market and language this copy speaks, and the platform context if known."""

    market: str
    language: str
    platform: str
    platform_source: str

    def __post_init__(self) -> None:
        _token(self.market, "context.market")
        _token(self.language, "context.language")
        _token(self.platform, "context.platform")
        if self.platform_source not in CONTEXT_SOURCES:
            raise CommercialCopyContractError(
                f"context.platform_source must be one of: {', '.join(CONTEXT_SOURCES)}"
            )
        if self.platform_source == "UNSPECIFIED":
            if self.platform != UNSPECIFIED_PLATFORM:
                raise CommercialCopyContractError(
                    "context.platform_source is UNSPECIFIED, so context.platform must be "
                    f"{UNSPECIFIED_PLATFORM!r}"
                )
        elif self.platform == UNSPECIFIED_PLATFORM:
            raise CommercialCopyContractError(
                f"context.platform {UNSPECIFIED_PLATFORM!r} must be recorded with "
                "platform_source UNSPECIFIED"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "market": self.market,
            "language": self.language,
            "platform": self.platform,
            "platform_source": self.platform_source,
        }


@dataclass(frozen=True)
class StrategyBinding:
    """The selected strategy variant this copy executes, bound by revision."""

    ref: str
    sha256: str
    variant_id: str

    def __post_init__(self) -> None:
        try:
            ArtifactReference(self.ref, self.sha256)
        except ArtifactReferenceError as exc:
            raise CommercialCopyContractError(str(exc)) from exc
        _token(self.variant_id, "strategy.variant_id")

    @property
    def reference(self) -> ArtifactReference:
        return ArtifactReference(self.ref, self.sha256)

    def as_dict(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "sha256": self.sha256,
            "variant_id": self.variant_id,
        }


@dataclass(frozen=True)
class BoundaryBindings:
    """The boundary revisions this copy obeys.

    Only the two blocks that have authorities of their own are bound here. The claim
    boundary travels with the bound strategy, which is recorded as a limitation in the
    contract document rather than papered over with a reference that does not exist.
    """

    product_facts: ArtifactReference
    visual_evidence_boundary: ArtifactReference

    def as_dict(self) -> dict[str, object]:
        return {
            "product_facts": self.product_facts.as_dict(),
            "visual_evidence_boundary": self.visual_evidence_boundary.as_dict(),
        }


@dataclass(frozen=True)
class SpeechBudget:
    """A soft time budget: enough for the copy layer to know how much it can say.

    Deliberately not a timeline. There is no frame count here, no placement, and no
    duration authority: the timeline and audio stages own exact time.
    """

    target_seconds: float
    acceptable_min_seconds: float
    acceptable_max_seconds: float

    def __post_init__(self) -> None:
        low = _seconds(self.acceptable_min_seconds, "budget.acceptable_min_seconds")
        high = _seconds(self.acceptable_max_seconds, "budget.acceptable_max_seconds")
        target = _seconds(self.target_seconds, "budget.target_seconds")
        if low > high:
            raise CommercialCopyContractError(
                "budget.acceptable_min_seconds must not exceed "
                "budget.acceptable_max_seconds"
            )
        if not low <= target <= high:
            raise CommercialCopyContractError(
                "budget.target_seconds must lie inside the acceptable range"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "target_seconds": self.target_seconds,
            "acceptable_min_seconds": self.acceptable_min_seconds,
            "acceptable_max_seconds": self.acceptable_max_seconds,
        }


@dataclass(frozen=True)
class DesignedSilence:
    """No voice-over here, and something else carries the moment instead.

    ``bed_note`` is required because the point of this segment type is that the track is
    *not* empty: the environment and evidence sound continue, and the visual does the work.
    """

    reason: str
    bed_note: str

    def __post_init__(self) -> None:
        _line(self.reason, "designed_silence.reason")
        _line(self.bed_note, "designed_silence.bed_note")

    def as_dict(self) -> dict[str, object]:
        return {"reason": self.reason, "bed_note": self.bed_note}


@dataclass(frozen=True)
class LocalizedLine:
    """The natural wording in the target language, for one speech segment."""

    language: str
    line: str

    def __post_init__(self) -> None:
        _token(self.language, "localized.language")
        _line(self.line, "localized.line")

    def as_dict(self) -> dict[str, object]:
        return {"language": self.language, "line": self.line}


@dataclass(frozen=True)
class CopySegment:
    """One stable unit of the copy, with both layers.

    ``segment_id`` is a caller-owned stable identity, never an array position: a segment
    may be reordered or removed without any other segment's identity changing.
    """

    segment_id: str
    copy_job: str
    delivery: str
    semantic_intent: str
    claim_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    budget: SpeechBudget
    localized: LocalizedLine | None = None
    designed_silence: DesignedSilence | None = None

    def __post_init__(self) -> None:
        _token(self.segment_id, "segment.segment_id")
        _token(self.copy_job, "segment.copy_job")
        _line(self.semantic_intent, "segment.semantic_intent")
        if self.delivery not in DELIVERY:
            raise CommercialCopyContractError(
                f"segment.delivery must be one of: {', '.join(DELIVERY)}"
            )
        if not isinstance(self.budget, SpeechBudget):
            raise CommercialCopyContractError("segment.budget must be a SpeechBudget")
        if self.delivery == "SPEECH":
            if self.localized is None:
                raise CommercialCopyContractError(
                    f"segment {self.segment_id!r} is SPEECH, so it must carry a localized "
                    "line"
                )
            if self.designed_silence is not None:
                raise CommercialCopyContractError(
                    f"segment {self.segment_id!r} is SPEECH and must not declare designed "
                    "silence"
                )
        else:
            if self.designed_silence is None:
                raise CommercialCopyContractError(
                    f"segment {self.segment_id!r} is DESIGNED_SILENCE, so it must say why "
                    "and what continues"
                )
            if self.localized is not None:
                raise CommercialCopyContractError(
                    f"segment {self.segment_id!r} is DESIGNED_SILENCE and must not carry a "
                    "localized line; silence here means no voice-over, not a missing line"
                )
            if not self.evidence_refs:
                raise CommercialCopyContractError(
                    f"segment {self.segment_id!r} is DESIGNED_SILENCE, so a visual carries "
                    "it and it must cite the evidence that does"
                )

    @property
    def is_speech(self) -> bool:
        return self.delivery == "SPEECH"

    @property
    def is_designed_silence(self) -> bool:
        return self.delivery == "DESIGNED_SILENCE"

    def as_dict(self) -> dict[str, object]:
        return {
            "segment_id": self.segment_id,
            "copy_job": self.copy_job,
            "delivery": self.delivery,
            "semantic_intent": self.semantic_intent,
            "claim_refs": list(self.claim_refs),
            "evidence_refs": list(self.evidence_refs),
            "budget": self.budget.as_dict(),
            "localized": None if self.localized is None else self.localized.as_dict(),
            "designed_silence": None
            if self.designed_silence is None
            else self.designed_silence.as_dict(),
        }


@dataclass(frozen=True)
class BackCheckFinding:
    """The recorded answer to the semantic back-check for one speech segment.

    The verdict is derived from the flags and then verified against the stored value, so a
    finding cannot admit an exceedance and still read ``PASS``.
    """

    segment_id: str
    adds_claim: bool
    expands_claim: bool
    drops_qualifier: bool
    possibility_as_certainty: bool
    unauthorised_product_fact: bool
    detail: str | None
    verdict: str

    def __post_init__(self) -> None:
        _token(self.segment_id, "finding.segment_id")
        for flag in BACK_CHECK_FLAGS:
            value = getattr(self, flag)
            if not isinstance(value, bool):
                raise CommercialCopyContractError(f"finding.{flag} must be a boolean")
        _optional_line(self.detail, "finding.detail")
        expected = self.derived_verdict
        if self.verdict != expected:
            raise CommercialCopyContractError(
                f"finding for segment {self.segment_id!r} states verdict "
                f"{self.verdict!r}, but the recorded flags derive {expected!r}; the "
                "back-check verdict is derived from the findings, not asserted beside them"
            )
        if expected == "FAIL" and self.detail is None:
            raise CommercialCopyContractError(
                f"finding for segment {self.segment_id!r} fails the back-check, so it must "
                "state what exceeded the semantic intent"
            )

    @property
    def exceeds(self) -> bool:
        return any(getattr(self, flag) for flag in BACK_CHECK_FLAGS)

    @property
    def derived_verdict(self) -> str:
        return "FAIL" if self.exceeds else "PASS"

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"segment_id": self.segment_id}
        for flag in BACK_CHECK_FLAGS:
            payload[flag] = getattr(self, flag)
        payload["detail"] = self.detail
        payload["verdict"] = self.verdict
        return payload


@dataclass(frozen=True)
class BlockingCondition:
    """Why a copy could not be produced, and which upstream area has to move."""

    reason_code: str
    reason: str
    missing: tuple[str, ...]
    return_to: str
    segment_id: str | None = None
    claim_ref: str | None = None

    def __post_init__(self) -> None:
        if self.reason_code not in BLOCK_REASON_CODES:
            raise CommercialCopyContractError(
                f"blocking.reason_code must be one of: {', '.join(BLOCK_REASON_CODES)}"
            )
        _line(self.reason, "blocking.reason")
        if self.return_to not in RETURN_TARGETS:
            raise CommercialCopyContractError(
                f"blocking.return_to must be one of: {', '.join(RETURN_TARGETS)}"
            )
        if self.segment_id is not None:
            _token(self.segment_id, "blocking.segment_id")
        if self.claim_ref is not None:
            _token(self.claim_ref, "blocking.claim_ref")

    def as_dict(self) -> dict[str, object]:
        return {
            "segment_id": self.segment_id,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "claim_ref": self.claim_ref,
            "missing": list(self.missing),
            "return_to": self.return_to,
        }


@dataclass(frozen=True)
class CopyProvenance:
    """Who authored this copy, under which skill, validated against which contract.

    There is no ``SYSTEM_GENERATED`` authoring mode, because no system generation exists:
    an artifact may not claim a capability the repository does not have.
    """

    authoring_mode: str
    authored_by: StrategyAuthor
    skill_name: str
    skill_version: str
    validator: str
    based_on: tuple[ArtifactReference, ...]

    def __post_init__(self) -> None:
        if self.authoring_mode not in AUTHORING_MODES:
            raise CommercialCopyContractError(
                f"provenance.authoring_mode must be one of: {', '.join(AUTHORING_MODES)}; "
                "there is no system-generated mode because no such capability exists"
            )
        if self.skill_name != SKILL_NAME:
            raise CommercialCopyContractError(
                f"provenance.skill.name must be {SKILL_NAME!r}"
            )
        if SKILL_VERSION_PATTERN.fullmatch(self.skill_version) is None:
            raise CommercialCopyContractError(
                "provenance.skill.version must look like 1.0.0"
            )
        if self.validator != VALIDATOR_NAME:
            raise CommercialCopyContractError(
                f"provenance.validation.validator must be {VALIDATOR_NAME!r}"
            )
        if not self.based_on:
            raise CommercialCopyContractError(
                "provenance.based_on must name the artifact revisions this copy was "
                "authored against"
            )
        _distinct([item.ref for item in self.based_on], "provenance.based_on")

    def reference_for(self, ref: str) -> ArtifactReference | None:
        for item in self.based_on:
            if item.ref == ref:
                return item
        return None

    def as_dict(self) -> dict[str, object]:
        return {
            "authoring_mode": self.authoring_mode,
            "authored_by": self.authored_by.as_dict(),
            "skill": {"name": self.skill_name, "version": self.skill_version},
            "validation": {"validator": self.validator},
            "based_on": [item.as_dict() for item in self.based_on],
        }


@dataclass(frozen=True)
class CommercialCopy:
    """One validated Commercial Copy: the strategy it executes, in the market's words."""

    copy_id: str
    context: CopyContext
    strategy: StrategyBinding
    boundaries: BoundaryBindings
    segments: tuple[CopySegment, ...]
    back_check: tuple[BackCheckFinding, ...]
    blocking: tuple[BlockingCondition, ...]
    status: str
    provenance: CopyProvenance

    def __post_init__(self) -> None:
        _token(self.copy_id, "copy_id")
        _distinct([item.segment_id for item in self.segments], "segments.segment_id")
        object.__setattr__(
            self,
            "segments",
            tuple(sorted(self.segments, key=lambda item: item.segment_id)),
        )
        object.__setattr__(
            self,
            "back_check",
            tuple(sorted(self.back_check, key=lambda item: item.segment_id)),
        )
        self._assert_back_check_is_complete()
        self._assert_blocking_is_actionable()
        self._assert_status_matches_derivation()
        self._assert_provenance_binds_the_boundaries()

    # ------------------------------------------------------------------ invariants

    @property
    def speech_segment_ids(self) -> tuple[str, ...]:
        return tuple(item.segment_id for item in self.segments if item.is_speech)

    @property
    def silence_segment_ids(self) -> tuple[str, ...]:
        return tuple(
            item.segment_id for item in self.segments if item.is_designed_silence
        )

    @property
    def failed_findings(self) -> tuple[BackCheckFinding, ...]:
        return tuple(item for item in self.back_check if item.verdict == "FAIL")

    @property
    def derived_status(self) -> str:
        """READY only when nothing is blocked and no finding failed the back-check."""

        if self.blocking or self.failed_findings:
            return "BLOCKED"
        return "READY"

    def _assert_back_check_is_complete(self) -> None:
        """Every speech segment is asked about exactly once; silence is not asked about."""

        asked = [item.segment_id for item in self.back_check]
        _distinct(asked, "semantic_back_check.findings.segment_id")
        missing = sorted(set(self.speech_segment_ids) - set(asked))
        if missing:
            raise CommercialCopyContractError(
                "semantic_back_check is incomplete: no finding for speech segment(s) "
                + ", ".join(missing)
            )
        unexpected = sorted(set(asked) - set(self.speech_segment_ids))
        if unexpected:
            raise CommercialCopyContractError(
                "semantic_back_check has finding(s) for segment(s) that are not speech: "
                + ", ".join(unexpected)
                + "; designed silence carries no line to check"
            )

    def _assert_blocking_is_actionable(self) -> None:
        """A blockage names what is missing and where it has to be resolved."""

        known = {item.segment_id for item in self.segments}
        for condition in self.blocking:
            if condition.segment_id is not None and condition.segment_id not in known:
                raise CommercialCopyContractError(
                    f"blocking condition references segment {condition.segment_id!r}, "
                    "which this copy does not declare"
                )
            if not condition.missing:
                raise CommercialCopyContractError(
                    "a blocking condition must state what is missing"
                )

    def _assert_status_matches_derivation(self) -> None:
        if self.status not in STATUSES:
            raise CommercialCopyContractError(
                f"status must be one of: {', '.join(STATUSES)}"
            )
        derived = self.derived_status
        if self.status != derived:
            raise CommercialCopyContractError(
                f"status is recorded as {self.status!r} but the artifact derives "
                f"{derived!r}; status is derived from the blocking conditions and the "
                "back-check, not asserted"
            )
        if derived == "READY" and not self.segments:
            raise CommercialCopyContractError(
                "a READY copy must declare at least one segment"
            )

    def _assert_provenance_binds_the_boundaries(self) -> None:
        for label, reference in (
            ("boundaries.product_facts", self.boundaries.product_facts),
            (
                "boundaries.visual_evidence_boundary",
                self.boundaries.visual_evidence_boundary,
            ),
        ):
            declared = self.provenance.reference_for(reference.ref)
            if declared is None:
                raise CommercialCopyContractError(
                    f"provenance.based_on does not name {label}.ref {reference.ref!r}"
                )
            if declared.sha256 != reference.sha256:
                raise CommercialCopyContractError(
                    f"provenance.based_on disagrees with {label}.sha256 for "
                    f"{reference.ref!r}"
                )

    # ---------------------------------------------------------------------- output

    def segment(self, segment_id: str) -> CopySegment:
        for item in self.segments:
            if item.segment_id == segment_id:
                return item
        raise CommercialCopyContractError(f"unknown segment_id {segment_id!r}")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "copy_id": self.copy_id,
            "context": self.context.as_dict(),
            "strategy": self.strategy.as_dict(),
            "boundaries": self.boundaries.as_dict(),
            "segments": [item.as_dict() for item in self.segments],
            "semantic_back_check": {
                "findings": [item.as_dict() for item in self.back_check]
            },
            "blocking": [item.as_dict() for item in self.blocking],
            "status": self.status,
            "provenance": self.provenance.as_dict(),
        }


def parse_commercial_copy(document: object) -> CommercialCopy:
    """Parse and fully validate one Commercial Copy. Fail closed, never repair.

    This validates the document on its own terms. Whether its references are permitted by
    the strategy it binds is :func:`validate_commercial_copy`'s job, exactly as
    ``validate_editing_plan`` binds a plan to its pool.
    """

    _reject_unexpected_numbers(document)
    mapping = _object(document, "commercial copy")
    _exact_keys(mapping, _DOCUMENT_KEYS, "commercial copy")
    if mapping["schema_version"] != SCHEMA_VERSION:
        raise CommercialCopyContractError(
            f"schema_version must be {SCHEMA_VERSION!r}"
        )

    raw_context = _object(mapping["context"], "context")
    _exact_keys(raw_context, _CONTEXT_KEYS, "context")
    context = CopyContext(
        market=raw_context["market"],  # type: ignore[arg-type]
        language=raw_context["language"],  # type: ignore[arg-type]
        platform=raw_context["platform"],  # type: ignore[arg-type]
        platform_source=raw_context["platform_source"],  # type: ignore[arg-type]
    )

    raw_strategy = _object(mapping["strategy"], "strategy")
    _exact_keys(raw_strategy, _STRATEGY_KEYS, "strategy")
    strategy = StrategyBinding(
        ref=raw_strategy["ref"],  # type: ignore[arg-type]
        sha256=raw_strategy["sha256"],  # type: ignore[arg-type]
        variant_id=raw_strategy["variant_id"],  # type: ignore[arg-type]
    )

    raw_boundaries = _object(mapping["boundaries"], "boundaries")
    _exact_keys(raw_boundaries, _BOUNDARY_KEYS, "boundaries")
    boundaries = BoundaryBindings(
        product_facts=_parse_reference(
            raw_boundaries["product_facts"], "boundaries.product_facts"
        ),
        visual_evidence_boundary=_parse_reference(
            raw_boundaries["visual_evidence_boundary"],
            "boundaries.visual_evidence_boundary",
        ),
    )

    segments: list[CopySegment] = []
    for index, raw in enumerate(_array(mapping["segments"], "segments")):
        item = _object(raw, f"segments[{index}]")
        _exact_keys(item, _SEGMENT_KEYS, f"segments[{index}]")
        raw_budget = _object(item["budget"], f"segments[{index}].budget")
        _exact_keys(raw_budget, _BUDGET_KEYS, f"segments[{index}].budget")
        budget = SpeechBudget(
            target_seconds=raw_budget["target_seconds"],  # type: ignore[arg-type]
            acceptable_min_seconds=raw_budget["acceptable_min_seconds"],  # type: ignore[arg-type]
            acceptable_max_seconds=raw_budget["acceptable_max_seconds"],  # type: ignore[arg-type]
        )
        localized: LocalizedLine | None = None
        if item["localized"] is not None:
            raw_localized = _object(item["localized"], f"segments[{index}].localized")
            _exact_keys(raw_localized, _LOCALIZED_KEYS, f"segments[{index}].localized")
            localized = LocalizedLine(
                language=raw_localized["language"],  # type: ignore[arg-type]
                line=raw_localized["line"],  # type: ignore[arg-type]
            )
            if localized.language != context.language:
                raise CommercialCopyContractError(
                    f"segments[{index}].localized.language must be the copy's language "
                    f"{context.language!r}, not {localized.language!r}"
                )
        silence: DesignedSilence | None = None
        if item["designed_silence"] is not None:
            raw_silence = _object(
                item["designed_silence"], f"segments[{index}].designed_silence"
            )
            _exact_keys(
                raw_silence, _SILENCE_KEYS, f"segments[{index}].designed_silence"
            )
            silence = DesignedSilence(
                reason=raw_silence["reason"],  # type: ignore[arg-type]
                bed_note=raw_silence["bed_note"],  # type: ignore[arg-type]
            )
        segments.append(
            CopySegment(
                segment_id=item["segment_id"],  # type: ignore[arg-type]
                copy_job=item["copy_job"],  # type: ignore[arg-type]
                delivery=item["delivery"],  # type: ignore[arg-type]
                semantic_intent=item["semantic_intent"],  # type: ignore[arg-type]
                claim_refs=tuple(
                    _token_list(item["claim_refs"], f"segments[{index}].claim_refs")
                ),
                evidence_refs=tuple(
                    _token_list(item["evidence_refs"], f"segments[{index}].evidence_refs")
                ),
                budget=budget,
                localized=localized,
                designed_silence=silence,
            )
        )

    raw_back_check = _object(mapping["semantic_back_check"], "semantic_back_check")
    _exact_keys(raw_back_check, _BACK_CHECK_KEYS, "semantic_back_check")
    findings: list[BackCheckFinding] = []
    for index, raw in enumerate(
        _array(raw_back_check["findings"], "semantic_back_check.findings")
    ):
        label = f"semantic_back_check.findings[{index}]"
        item = _object(raw, label)
        _exact_keys(item, _FINDING_KEYS, label)
        findings.append(
            BackCheckFinding(
                segment_id=item["segment_id"],  # type: ignore[arg-type]
                adds_claim=item["adds_claim"],  # type: ignore[arg-type]
                expands_claim=item["expands_claim"],  # type: ignore[arg-type]
                drops_qualifier=item["drops_qualifier"],  # type: ignore[arg-type]
                possibility_as_certainty=item["possibility_as_certainty"],  # type: ignore[arg-type]
                unauthorised_product_fact=item["unauthorised_product_fact"],  # type: ignore[arg-type]
                detail=item["detail"],  # type: ignore[arg-type]
                verdict=item["verdict"],  # type: ignore[arg-type]
            )
        )

    blocking: list[BlockingCondition] = []
    for index, raw in enumerate(_array(mapping["blocking"], "blocking")):
        label = f"blocking[{index}]"
        item = _object(raw, label)
        _exact_keys(item, _BLOCKING_KEYS, label)
        blocking.append(
            BlockingCondition(
                segment_id=item["segment_id"],  # type: ignore[arg-type]
                reason_code=item["reason_code"],  # type: ignore[arg-type]
                reason=item["reason"],  # type: ignore[arg-type]
                claim_ref=item["claim_ref"],  # type: ignore[arg-type]
                missing=tuple(_line_list(item["missing"], f"{label}.missing")),
                return_to=item["return_to"],  # type: ignore[arg-type]
            )
        )

    raw_provenance = _object(mapping["provenance"], "provenance")
    _exact_keys(raw_provenance, _PROVENANCE_KEYS, "provenance")
    author = _object(raw_provenance["authored_by"], "provenance.authored_by")
    _exact_keys(author, _AUTHOR_KEYS, "provenance.authored_by")
    skill = _object(raw_provenance["skill"], "provenance.skill")
    _exact_keys(skill, _SKILL_KEYS, "provenance.skill")
    validation = _object(raw_provenance["validation"], "provenance.validation")
    _exact_keys(validation, _VALIDATION_KEYS, "provenance.validation")
    based_on: list[ArtifactReference] = []
    for index, raw in enumerate(_array(raw_provenance["based_on"], "provenance.based_on")):
        based_on.append(
            _parse_reference(raw, f"provenance.based_on[{index}]")
        )

    return CommercialCopy(
        copy_id=mapping["copy_id"],  # type: ignore[arg-type]
        context=context,
        strategy=strategy,
        boundaries=boundaries,
        segments=tuple(segments),
        back_check=tuple(findings),
        blocking=tuple(blocking),
        status=mapping["status"],  # type: ignore[arg-type]
        provenance=CopyProvenance(
            authoring_mode=raw_provenance["authoring_mode"],  # type: ignore[arg-type]
            authored_by=StrategyAuthor(
                author["actor"], author["producer_id"]  # type: ignore[arg-type]
            ),
            skill_name=skill["name"],  # type: ignore[arg-type]
            skill_version=skill["version"],  # type: ignore[arg-type]
            validator=validation["validator"],  # type: ignore[arg-type]
            based_on=tuple(based_on),
        ),
    )


def render_commercial_copy(copy: CommercialCopy) -> str:
    """Canonical one-document rendering. Identical input renders identical bytes."""

    if not isinstance(copy, CommercialCopy):
        raise CommercialCopyContractError("copy must be a CommercialCopy")
    return json.dumps(
        copy.as_dict(), ensure_ascii=False, sort_keys=True, indent=2
    ) + "\n"


def validate_commercial_copy(
    copy: CommercialCopy, strategy: CommercialStrategy
) -> None:
    """Bind one copy to the strategy it executes, and refuse anything the boundaries deny.

    The two-artifact pattern this repository already uses: :func:`parse_commercial_copy`
    validates the document alone; this proves it against the strategy it claims to execute.
    A copy may not change the strategy - not its market, not its boundaries, not its
    selected claims - and it may not lean on evidence the material does not have.
    """

    if not isinstance(copy, CommercialCopy):
        raise CommercialCopyContractError("copy must be a CommercialCopy")
    if not isinstance(strategy, CommercialStrategy):
        raise CommercialCopyContractError("strategy must be a CommercialStrategy")

    # 1. Same boundary revisions: one boundary, not a fork of it.
    for label, bound, declared in (
        (
            "product_facts",
            copy.boundaries.product_facts,
            strategy.product_facts.reference,
        ),
        (
            "visual_evidence_boundary",
            copy.boundaries.visual_evidence_boundary,
            strategy.visual_evidence_boundary.reference,
        ),
    ):
        if bound.as_dict() != declared.as_dict():
            raise CommercialCopyContractError(
                f"copy boundaries.{label} is {bound.as_dict()!r} but the strategy binds "
                f"{declared.as_dict()!r}; a copy may not bind a different boundary revision"
            )

    # 2. The variant it claims to execute must exist, and the market must match.
    try:
        variant = strategy.variant(copy.strategy.variant_id)
    except CommercialStrategyContractError as exc:
        raise CommercialCopyContractError(str(exc)) from exc
    if copy.context.market != strategy.market:
        raise CommercialCopyContractError(
            f"copy context.market is {copy.context.market!r} but the strategy was declared "
            f"for {strategy.market!r}"
        )

    claim_boundary = strategy.claim_boundary
    evidence_boundary = strategy.visual_evidence_boundary
    for segment in copy.segments:
        label = f"segment {segment.segment_id!r}"
        for claim_id in segment.claim_refs:
            state = claim_boundary.state_of(claim_id)
            if state is None:
                raise CommercialCopyContractError(
                    f"{label} references claim {claim_id!r}, which the bound claim "
                    "boundary does not declare"
                )
            if state == "FORBIDDEN":
                raise CommercialCopyContractError(
                    f"{label} references forbidden claim {claim_id!r}; a copy may never "
                    "make a claim the boundary forbids"
                )
            if state == "CONDITIONAL":
                raise CommercialCopyContractError(
                    f"{label} references conditional claim {claim_id!r}; a copy may not use "
                    "it before the evidence its condition requires exists"
                )
            if claim_id not in variant.claims_used:
                raise CommercialCopyContractError(
                    f"{label} references claim {claim_id!r}, which the selected variant "
                    f"{variant.variant_id!r} did not select; a copy may not add a claim the "
                    "strategy did not choose"
                )
            claim = next(
                item for item in claim_boundary.allowed if item.claim_id == claim_id
            )
            if not strategy.product_facts.permits(claim.product_fact_ref):
                raise CommercialCopyContractError(
                    f"{label} rests on Product Fact {claim.product_fact_ref!r}, which "
                    "product_facts does not permit"
                )
            if (
                claim.evidence_ref is not None
                and claim.evidence_ref not in segment.evidence_refs
            ):
                raise CommercialCopyContractError(
                    f"{label} uses claim {claim_id!r} but does not cite evidence "
                    f"{claim.evidence_ref!r} that the claim rests on"
                )
        for evidence_id in segment.evidence_refs:
            presence = evidence_boundary.presence_of(evidence_id)
            if presence is None:
                raise CommercialCopyContractError(
                    f"{label} references evidence {evidence_id!r}, which the bound "
                    "evidence boundary does not declare"
                )
            if presence != "PRESENT":
                raise CommercialCopyContractError(
                    f"{label} treats evidence {evidence_id!r} as available, but the "
                    f"material records it as {presence}"
                )

    # 3. A blockage that names a claim must agree with what the boundaries say about it.
    for condition in copy.blocking:
        if condition.claim_ref is None:
            continue
        availability = claim_availability(
            condition.claim_ref, claim_boundary, evidence_boundary
        )
        if availability.available:
            raise CommercialCopyContractError(
                f"copy is blocked on claim {condition.claim_ref!r}, but the boundaries "
                "permit it; a permitted claim is not a reason to block"
            )
        undeclared = sorted(set(availability.missing) - set(condition.missing))
        if undeclared:
            raise CommercialCopyContractError(
                f"blocking condition on claim {condition.claim_ref!r} does not declare the "
                "derived missing item(s): " + ", ".join(undeclared)
            )


def copy_structure(copy: CommercialCopy) -> tuple[dict[str, object], ...]:
    """The semantic structure of the copy: what each segment does, in order.

    This is the view that makes two copies comparable without reading either language:
    the ordered commercial jobs, the delivery of each, and which evidence each leans on.
    """

    if not isinstance(copy, CommercialCopy):
        raise CommercialCopyContractError("copy must be a CommercialCopy")
    return tuple(
        {
            "segment_id": item.segment_id,
            "copy_job": item.copy_job,
            "delivery": item.delivery,
            "claim_refs": list(item.claim_refs),
            "evidence_refs": list(item.evidence_refs),
            "target_seconds": item.budget.target_seconds,
        }
        for item in copy.segments
    )


def copy_structure_diff(
    left: CommercialCopy, right: CommercialCopy
) -> dict[str, object]:
    """Where two copies differ structurally, so a reviewer does not have to guess.

    A different tone of voice does not show up here, and that is the point: a variant that
    only rewrote another variant's sentences will look identical in this view.
    """

    for label, copy in (("left", left), ("right", right)):
        if not isinstance(copy, CommercialCopy):
            raise CommercialCopyContractError(f"{label} must be a CommercialCopy")
    left_structure = copy_structure(left)
    right_structure = copy_structure(right)
    left_jobs = [item["copy_job"] for item in left_structure]
    right_jobs = [item["copy_job"] for item in right_structure]
    left_delivery = [item["delivery"] for item in left_structure]
    right_delivery = [item["delivery"] for item in right_structure]
    left_claims = {claim for item in left_structure for claim in item["claim_refs"]}
    right_claims = {claim for item in right_structure for claim in item["claim_refs"]}
    left_evidence = {item for entry in left_structure for item in entry["evidence_refs"]}
    right_evidence = {
        item for entry in right_structure for item in entry["evidence_refs"]
    }
    return {
        "schema_version": "commercial_copy_structure_diff.v1",
        "left_copy_id": left.copy_id,
        "right_copy_id": right.copy_id,
        "identical_structure": left_structure == right_structure,
        "job_sequence_differs": left_jobs != right_jobs,
        "delivery_sequence_differs": left_delivery != right_delivery,
        "segment_count_differs": len(left_structure) != len(right_structure),
        "claims_differ": sorted(left_claims) != sorted(right_claims),
        "evidence_differ": sorted(left_evidence) != sorted(right_evidence),
        "left_only_jobs": sorted(set(left_jobs) - set(right_jobs)),
        "right_only_jobs": sorted(set(right_jobs) - set(left_jobs)),
    }


__all__ = [
    "AUTHORING_MODES",
    "BACK_CHECK_FLAGS",
    "BACK_CHECK_VERDICTS",
    "BLOCK_REASON_CODES",
    "BackCheckFinding",
    "BlockingCondition",
    "BoundaryBindings",
    "CANONICAL_REF",
    "CommercialCopy",
    "CommercialCopyContractError",
    "CopyContext",
    "CopyProvenance",
    "CopySegment",
    "DELIVERY",
    "DesignedSilence",
    "IMPLEMENTATION",
    "LocalizedLine",
    "RETURN_TARGETS",
    "SCHEMA_VERSION",
    "SKILL_NAME",
    "STATUSES",
    "SpeechBudget",
    "StrategyBinding",
    "VALIDATOR_NAME",
    "WIRING_STATUS",
    "copy_structure",
    "copy_structure_diff",
    "parse_commercial_copy",
    "render_commercial_copy",
    "validate_commercial_copy",
]
