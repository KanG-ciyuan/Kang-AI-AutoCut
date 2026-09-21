"""Structured Candidate Analysis: the provider boundary, and Candidate Evidence.

Candidate Extraction answers *where* a Candidate is. This module asks *what is in
it*, and turns the answer into the Phase 1 companion contract
``candidate_evidence.v1``.

The one question an analyzer may answer
---------------------------------------
The task supplies a **Claim Envelope**: the Product Facts this job is allowed to
use. The analyzer may only answer

    "what evidence do these frames provide for the claims in this envelope?"

and may never answer

    "here is something else the product could claim".

A Product Fact the envelope does not permit is refused, and the Candidate is
recorded as ``ANALYSIS_FAILED`` with that reason. Refusing is deliberate: quietly
dropping the offending claim would be the pipeline editing the analyzer's answer,
and quietly accepting it would be the analyzer writing the commercial claim.

Where the provider lives
------------------------
The core depends on a structured request/response contract and on the existing
authoring seam in :mod:`authoring` — never on a provider SDK. A real multimodal
analyzer is a job-scoped adapter invoked through the seam
(``CommandAuthoringAgent``); a deterministic test provider is the existing
``ScriptedAuthoringAgent``; a recorded structured response is a fixture file. No
provider-specific field may enter the core contract: an unexpected key inside an
entry fails that entry, and an unexpected key at the top level fails the response.

What this module does not do
----------------------------
It does not generate hooks, select hooks, plan a sequence, compile a timeline,
render, approve, or release. Candidate Evidence is where this stage stops.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence, Union

from . import authoring, producer_registry
from .artifact_reference import (
    ArtifactReference,
    ArtifactReferenceError,
    artifact_reference,
    parse_artifact_reference,
    validate_reference_binding,
    validate_logical_ref,
    validate_sha256,
)
from .candidate_evidence import (
    CANONICAL_REF as CANDIDATE_EVIDENCE_CANONICAL_REF,
    SCHEMA_VERSION as CANDIDATE_EVIDENCE_SCHEMA_VERSION,
    AnalysisRun,
    CandidateEvidence,
    CandidateEvidenceContractError,
    CandidateEvidenceEntry,
    ClaimSupport,
    EvidenceStatus,
    ProductFacts,
    candidate_evidence_reference,
    parse_candidate_evidence,
    render_candidate_evidence,
    validate_candidate_evidence,
)
from .candidate_extraction import (
    CandidateExtraction,
    CandidateExtractionError,
    MeasuredWindow,
    SegmentSpan,
    SourceMeasurement,
    SourceSegmentation,
    SOURCE_COORDINATE_SYSTEM,
    WindowProposal,
    extract_candidates,
    parse_window_proposals,
    render_extraction,
)
from .candidate_evidence_v2 import (
    SCHEMA_VERSION as CANDIDATE_EVIDENCE_V2_SCHEMA_VERSION,
    OBSERVABLE_STATE_MEANINGS,
    CandidateEvidenceEntryV2,
    CandidateEvidenceV2,
    entry_payload_without_v2_keys,
    observations_v2_from_payload,
    render_candidate_evidence_v2,
    validate_candidate_evidence_v2,
)
from .candidate_pool import CandidatePool, render_candidate_pool
from .identity import IdentityCatalog, parse_identity_catalog


REQUEST_SCHEMA_VERSION = "candidate_analysis_request.v1"
RESPONSE_SCHEMA_VERSION = "candidate_analysis_response.v1"
ENVELOPE_SCHEMA_VERSION = "claim_envelope.v1"
MEASUREMENTS_SCHEMA_VERSION = "candidate_measurements.v1"
SEGMENTATIONS_SCHEMA_VERSION = "candidate_segmentations.v1"
REPORT_SCHEMA_VERSION = "candidate_evidence_report.v1"

#: The original Phase 2 prompt contract, kept because the Phase 2 fixtures were
#: produced under it and a recorded answer must stay replayable against its own
#: contract version.
PROMPT_CONTRACT_VERSION = "candidate_evidence_prompt.v1"

#: The one question the analyzer is asked under v1. Stated in the request so the
#: provider contract is explicit rather than remembered.
ANALYSIS_QUESTION = (
    "For each Candidate, report only what its cited frames show, and state for each "
    "Product Fact in the Claim Envelope whether those frames show it DIRECTLY, are "
    "CONTEXTUAL to it, or whether support is INFERRED. Do not introduce a Product Fact "
    "that is not in the envelope, and do not present inference as direct visual proof."
)

#: The Phase 2.5 prompt contract: narrow, evidence-only, and explicit about the
#: ladder from what is visible to what may not be claimed.
ANALYZER_PROMPT_CONTRACT_VERSION = "candidate_evidence_prompt.v2"

ANALYZER_PROMPT_V2 = """You are a visual evidence analyst for one short commercial video. You are NOT a
copywriter: you do not write advertising text, and you do not decide what the product
should claim.

You are given a Claim Envelope: the complete list of Product Facts this job permits. It
is closed. You may report only what the supplied frames show about those facts.

For every Candidate you are given, answer in exactly one of these five registers, and
never blur them:

- OBSERVATION    what is visibly present in the frames (objects, motion, state, framing,
                 lighting, legibility). An observation needs no Product Fact.
- DIRECT         the cited frames themselves demonstrate the Product Fact. Say DIRECT
                 only when a viewer looking at those exact frames would see it happen.
                 Cite the source frame numbers that show it, using only the frame
                 numbers supplied in the frame evidence manifest.
- CONTEXTUAL     the surrounding visual context is consistent with the Product Fact but
                 does not demonstrate it. It is not proof and must not be reported as
                 DIRECT.
- INFERRED       the conclusion requires reasoning beyond the picture. Mark it INFERRED
                 no matter how confident you are.
- UNSUPPORTED    the Product Fact is not supported by these frames at all. Do not claim
                 it: either omit the claim, or report the Candidate honestly as UNKNOWN
                 with a rationale.

Hard rules:

1. Never introduce a Product Fact that is not in the Claim Envelope. There is no fact
   for it, so there is no claim to make. If something visible has no matching Product
   Fact, describe it as an OBSERVATION only.
2. Never upgrade INFERRED or CONTEXTUAL to DIRECT because confidence is high. Support
   class is a property of what the frames show, not of how sure you feel.
3. Never claim a result you cannot see. If the frames end before a result is visible,
   report the action without it and say so.
4. Never assume the product works from how it looks. Appearance, packaging, gloss, and
   build quality are observations, not evidence of effect.
5. A beauty or hero shot of the product is not efficacy evidence. It may be visually
   excellent and still support no DIRECT claim at all; report it that way.
6. Never invent, estimate, or interpolate source frame numbers. Cite only frames that
   appear in the frame evidence manifest, inside the Candidate window you were given.
7. Every Candidate in the request must appear exactly once in your answer, either
   analysed, or with status UNKNOWN or ANALYSIS_FAILED and a rationale. Never silently
   omit one, and never answer about a Candidate that was not requested.

Answer with the response document the request asks for: one entry per Candidate, whose
fields are exactly candidate_id, status, observations, action_evidence, claims,
evidence_type, confidence, provenance, role_affinities, risks, rationale. Keep rationale
to one or two sentences of plain description. Report confidence as your own calibrated
number between 0.0 and 1.0; it never changes a support class.
"""

#: The Phase 2.6 prompt contract: v2 plus the structured observation fields, for
#: producing a ``candidate_evidence.v2`` document.
STRUCTURED_PROMPT_CONTRACT_VERSION = "candidate_evidence_prompt.v3"

#: The vocabulary section is generated from the contract's own enum, so the words an
#: analyzer is given and the codes the validator accepts cannot drift apart.
_STRUCTURED_VOCABULARY_TEXT = "\n".join(
    f"- {code}: {meaning}" for code, meaning in sorted(OBSERVABLE_STATE_MEANINGS.items())
)

STRUCTURED_OBSERVATION_INSTRUCTIONS = f"""\
Beyond the entry fields, you must also fill two structured observation fields. They exist
because an analysis that cannot say "there was no action here" or "the surface is visibly
in its problem state" in machine-readable form forces every later stage to read prose, and
prose is not truth.

Inside observations, add:

action_presence, exactly one of:
- ACTION_PRESENT: an observable action happens within these frames.
- NO_ACTION: these frames positively show no action. Say this when the shot is static,
  when nothing is contacted, and when nothing changes. It is a statement about the
  footage, not a gap in your answer.
- NOT_RECORDED: you did not judge it. Do not use this to avoid deciding.

observable_states, a list drawn only from this closed vocabulary:
{_STRUCTURED_VOCABULARY_TEXT}

Rules for the structured fields:

1. They are observations, never claims. No code asserts an effect, and none may be used
   as if it did. "CLEAN_STATE_VISIBLE" says a surface looks clear; it does not say the
   product works, and it is not a substitute for a Product Fact.
2. Never derive a claim from an observation. A claim still requires a Product Fact from
   the Claim Envelope, exactly as before.
3. Any event code (CONTACT_VISIBLE, FLOW_VISIBLE, STATE_CHANGE_VISIBLE,
   BEFORE_AFTER_RELATION_VISIBLE) requires action_presence ACTION_PRESENT and the action
   evidence that shows it.
4. If an entry is not ANALYZED, both fields are null with the rest of the payload.
5. List only what these frames show. If a state is not visible, leave it out rather than
   listing it because it is probably true.
"""

ANALYZER_PROMPT_V3 = ANALYZER_PROMPT_V2 + "\n" + STRUCTURED_OBSERVATION_INSTRUCTIONS


@dataclass(frozen=True)
class PromptContract:
    """One versioned instruction, and the evidence version it produces.

    The mapping is explicit rather than implied: an analyzer told to answer with the
    structured observation fields produces a v2 document, and one told nothing about
    them produces a v1 document. The stage reads this to decide which contract it
    will validate against, so a mismatch cannot be papered over.
    """

    version: str
    question: str
    evidence_contract_version: str


#: Every prompt contract this module can ask under, by version.
PROMPT_CONTRACTS: Mapping[str, PromptContract] = {
    PROMPT_CONTRACT_VERSION: PromptContract(
        PROMPT_CONTRACT_VERSION, ANALYSIS_QUESTION, CANDIDATE_EVIDENCE_SCHEMA_VERSION
    ),
    ANALYZER_PROMPT_CONTRACT_VERSION: PromptContract(
        ANALYZER_PROMPT_CONTRACT_VERSION, ANALYZER_PROMPT_V2, CANDIDATE_EVIDENCE_SCHEMA_VERSION
    ),
    STRUCTURED_PROMPT_CONTRACT_VERSION: PromptContract(
        STRUCTURED_PROMPT_CONTRACT_VERSION,
        ANALYZER_PROMPT_V3,
        CANDIDATE_EVIDENCE_V2_SCHEMA_VERSION,
    ),
}


def prompt_contract(version: str) -> PromptContract:
    """The contract record for one prompt contract version."""

    if not isinstance(version, str) or version not in PROMPT_CONTRACTS:
        raise CandidateAnalysisError(
            "unknown prompt contract version; expected one of: "
            + ", ".join(sorted(PROMPT_CONTRACTS))
        )
    return PROMPT_CONTRACTS[version]


def prompt_for(version: str) -> str:
    """The instruction text belonging to one prompt contract version."""

    return prompt_contract(version).question


def evidence_contract_for(prompt_version: str) -> str:
    """The Candidate Evidence version a prompt contract produces."""

    return prompt_contract(prompt_version).evidence_contract_version

#: Entry payload keys, exactly the Phase 1 entry shape.
_ENTRY_KEYS = (
    "candidate_id",
    "status",
    "observations",
    "action_evidence",
    "claims",
    "evidence_type",
    "confidence",
    "provenance",
    "role_affinities",
    "risks",
    "rationale",
)
_REQUEST_KEYS = (
    "schema_version",
    "run_id",
    "candidate_pool_id",
    "prompt_contract_version",
    "question",
    "claim_envelope",
    "candidates",
)
_RESPONSE_KEYS = (
    "schema_version",
    "run_id",
    "candidate_pool_id",
    "provider",
    "model",
    "prompt_contract_version",
    "request",
    "entries",
)
_ENVELOPE_KEYS = ("schema_version", "ref", "sha256", "facts")
_FACT_KEYS = ("ref", "statement")
_TARGET_KEYS = (
    "candidate_id",
    "material_id",
    "stream_index",
    "start_frame",
    "end_frame_exclusive",
    "measured",
)
_MEASURED_KEYS = (
    "t_in_seconds",
    "t_out_seconds",
    "duration_seconds",
    "frame_count",
    "variable_frame_rate",
    "coordinate_system",
)


class CandidateAnalysisError(ValueError):
    """Raised when an analysis cannot be requested, trusted, or produced."""


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise CandidateAnalysisError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise CandidateAnalysisError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    missing = sorted(set(allowed) - set(mapping))
    if unknown:
        raise CandidateAnalysisError(
            f"{label} has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise CandidateAnalysisError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CandidateAnalysisError(f"{label} must be a non-empty string")
    return value


def _token(value: object, label: str) -> str:
    return validate_token(value, label)


def validate_token(value: object, label: str) -> str:
    """A logical token: no paths, no whitespace, bounded length."""

    if not isinstance(value, str) or not value.strip():
        raise CandidateAnalysisError(f"{label} must be a non-empty string")
    if len(value) > 128 or any(character.isspace() for character in value):
        raise CandidateAnalysisError(f"{label} must be a logical token")
    if value.startswith(("/", "~", ".")) or "\\" in value:
        raise CandidateAnalysisError(f"{label} must not be a machine path")
    return value


@dataclass(frozen=True)
class ClaimFact:
    """One permitted Product Fact, with the statement it stands for."""

    ref: str
    statement: str

    def __post_init__(self) -> None:
        _token(self.ref, "claim_envelope.facts[].ref")
        _text(self.statement, "claim_envelope.facts[].statement")

    def as_dict(self) -> dict[str, object]:
        return {"ref": self.ref, "statement": self.statement}


@dataclass(frozen=True)
class ClaimEnvelope:
    """The Product Facts a job permits, and the artifact that states them.

    This is the boundary that stops a model from inventing a commercial claim.
    The analyzer answers *against* this envelope; it never extends it.
    """

    ref: str
    sha256: str
    facts: tuple[ClaimFact, ...]

    def __post_init__(self) -> None:
        try:
            validate_logical_ref(self.ref, "claim_envelope.ref")
            validate_sha256(self.sha256, "claim_envelope.sha256")
        except ArtifactReferenceError as exc:
            raise CandidateAnalysisError(str(exc)) from exc
        facts = tuple(self.facts)
        if not facts:
            raise CandidateAnalysisError(
                "a Claim Envelope must permit at least one Product Fact"
            )
        for position, fact in enumerate(facts):
            if not isinstance(fact, ClaimFact):
                raise CandidateAnalysisError(
                    f"claim_envelope.facts[{position}] must be a ClaimFact"
                )
        refs = [fact.ref for fact in facts]
        if len(set(refs)) != len(refs):
            raise CandidateAnalysisError(
                "a Claim Envelope must not repeat a Product Fact reference"
            )
        object.__setattr__(self, "facts", tuple(sorted(facts, key=lambda item: item.ref)))

    @property
    def allowed_fact_refs(self) -> tuple[str, ...]:
        return tuple(fact.ref for fact in self.facts)

    @property
    def reference(self) -> ArtifactReference:
        return ArtifactReference(self.ref, self.sha256)

    def permits(self, fact_ref: object) -> bool:
        return isinstance(fact_ref, str) and fact_ref in self.allowed_fact_refs

    def statement_for(self, fact_ref: str) -> str:
        for fact in self.facts:
            if fact.ref == fact_ref:
                return fact.statement
        raise CandidateAnalysisError("Product Fact is not in the Claim Envelope")

    def product_facts(self) -> ProductFacts:
        """The Phase 1 ``product_facts`` block this envelope grounds."""

        return ProductFacts(self.ref, self.sha256, self.allowed_fact_refs)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "ref": self.ref,
            "sha256": self.sha256,
            "facts": [fact.as_dict() for fact in self.facts],
        }


def parse_claim_envelope(document: object) -> ClaimEnvelope:
    mapping = _object(document, "claim envelope")
    _exact_keys(mapping, _ENVELOPE_KEYS, "claim envelope")
    if mapping["schema_version"] != ENVELOPE_SCHEMA_VERSION:
        raise CandidateAnalysisError(
            f"schema_version must be {ENVELOPE_SCHEMA_VERSION!r}"
        )
    facts: list[ClaimFact] = []
    for position, raw in enumerate(_array(mapping["facts"], "claim envelope.facts")):
        item = _object(raw, f"claim envelope.facts[{position}]")
        _exact_keys(item, _FACT_KEYS, f"claim envelope.facts[{position}]")
        facts.append(
            ClaimFact(
                ref=item["ref"],  # type: ignore[arg-type]
                statement=item["statement"],  # type: ignore[arg-type]
            )
        )
    return ClaimEnvelope(
        ref=mapping["ref"],  # type: ignore[arg-type]
        sha256=mapping["sha256"],  # type: ignore[arg-type]
        facts=tuple(facts),
    )


def render_claim_envelope(envelope: ClaimEnvelope) -> str:
    if not isinstance(envelope, ClaimEnvelope):
        raise CandidateAnalysisError("envelope must be a ClaimEnvelope")
    return json.dumps(envelope.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


@dataclass(frozen=True)
class AnalysisTarget:
    """One Candidate, and exactly which frames the analyzer is being asked about."""

    candidate_id: str
    material_id: str
    stream_index: int
    start_frame: int
    end_frame_exclusive: int
    measured: MeasuredWindow

    def __post_init__(self) -> None:
        if not isinstance(self.measured, MeasuredWindow):
            raise CandidateAnalysisError("measured must be a MeasuredWindow")

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "material_id": self.material_id,
            "stream_index": self.stream_index,
            "start_frame": self.start_frame,
            "end_frame_exclusive": self.end_frame_exclusive,
            "measured": self.measured.as_dict(),
        }


def targets_from_extraction(extraction: CandidateExtraction) -> tuple[AnalysisTarget, ...]:
    """One target per accepted Candidate, in canonical order."""

    if not isinstance(extraction, CandidateExtraction):
        raise CandidateAnalysisError("extraction must be a CandidateExtraction")
    return tuple(
        AnalysisTarget(
            candidate_id=candidate.candidate_id,
            material_id=candidate.material_id,
            stream_index=candidate.stream_index,
            start_frame=candidate.start_frame,
            end_frame_exclusive=candidate.end_frame_exclusive,
            measured=extraction.measured_for(candidate.candidate_id),
        )
        for candidate in extraction.candidates
    )


@dataclass(frozen=True)
class CandidateAnalysisRequest:
    """The deterministic request: the question, the envelope, and the windows."""

    run_id: str
    candidate_pool_id: str
    claim_envelope: ClaimEnvelope
    targets: tuple[AnalysisTarget, ...]
    prompt_contract_version: str = PROMPT_CONTRACT_VERSION
    question: str = ANALYSIS_QUESTION

    def __post_init__(self) -> None:
        _token(self.run_id, "run_id")
        _text(self.prompt_contract_version, "prompt_contract_version")
        _text(self.question, "question")
        if not isinstance(self.claim_envelope, ClaimEnvelope):
            raise CandidateAnalysisError("claim_envelope must be a ClaimEnvelope")
        for position, target in enumerate(self.targets):
            if not isinstance(target, AnalysisTarget):
                raise CandidateAnalysisError(
                    f"candidates[{position}] must be an AnalysisTarget"
                )
        candidate_ids = [target.candidate_id for target in self.targets]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise CandidateAnalysisError("a request must not repeat a Candidate")
        object.__setattr__(
            self, "targets", tuple(sorted(self.targets, key=lambda item: item.candidate_id))
        )

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(target.candidate_id for target in self.targets)

    def target_for(self, candidate_id: str) -> AnalysisTarget:
        for target in self.targets:
            if target.candidate_id == candidate_id:
                return target
        raise CandidateAnalysisError("candidate_id is not part of this request")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "run_id": self.run_id,
            "candidate_pool_id": self.candidate_pool_id,
            "prompt_contract_version": self.prompt_contract_version,
            "question": self.question,
            "claim_envelope": self.claim_envelope.as_dict(),
            "candidates": [target.as_dict() for target in self.targets],
        }


def render_analysis_request(request: CandidateAnalysisRequest) -> str:
    if not isinstance(request, CandidateAnalysisRequest):
        raise CandidateAnalysisError("request must be a CandidateAnalysisRequest")
    return json.dumps(request.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def request_reference(request: CandidateAnalysisRequest) -> ArtifactReference:
    """The reference an analyzer must echo back so its answer stays bound."""

    return artifact_reference(
        producer_registry.CANDIDATE_ANALYSIS_REQUEST_ARTIFACT,
        render_analysis_request(request),
    )


def parse_analysis_request(document: object) -> CandidateAnalysisRequest:
    mapping = _object(document, "analysis request")
    _exact_keys(mapping, _REQUEST_KEYS, "analysis request")
    if mapping["schema_version"] != REQUEST_SCHEMA_VERSION:
        raise CandidateAnalysisError(
            f"schema_version must be {REQUEST_SCHEMA_VERSION!r}"
        )
    envelope = parse_claim_envelope(mapping["claim_envelope"])
    targets: list[AnalysisTarget] = []
    for position, raw in enumerate(
        _array(mapping["candidates"], "analysis request.candidates")
    ):
        item = _object(raw, f"analysis request.candidates[{position}]")
        _exact_keys(item, _TARGET_KEYS, f"analysis request.candidates[{position}]")
        measured = _object(
            item["measured"], f"analysis request.candidates[{position}].measured"
        )
        _exact_keys(
            measured,
            _MEASURED_KEYS,
            f"analysis request.candidates[{position}].measured",
        )
        if measured["coordinate_system"] != SOURCE_COORDINATE_SYSTEM:
            raise CandidateAnalysisError(
                "a Candidate window must be expressed in measured source PTS seconds"
            )
        targets.append(
            AnalysisTarget(
                candidate_id=item["candidate_id"],  # type: ignore[arg-type]
                material_id=item["material_id"],  # type: ignore[arg-type]
                stream_index=item["stream_index"],  # type: ignore[arg-type]
                start_frame=item["start_frame"],  # type: ignore[arg-type]
                end_frame_exclusive=item["end_frame_exclusive"],  # type: ignore[arg-type]
                measured=MeasuredWindow(
                    t_in_seconds=measured["t_in_seconds"],  # type: ignore[arg-type]
                    t_out_seconds=measured["t_out_seconds"],  # type: ignore[arg-type]
                    duration_seconds=measured["duration_seconds"],  # type: ignore[arg-type]
                    frame_count=measured["frame_count"],  # type: ignore[arg-type]
                    variable_frame_rate=measured["variable_frame_rate"],  # type: ignore[arg-type]
                ),
            )
        )
    return CandidateAnalysisRequest(
        run_id=mapping["run_id"],  # type: ignore[arg-type]
        candidate_pool_id=mapping["candidate_pool_id"],  # type: ignore[arg-type]
        claim_envelope=envelope,
        targets=tuple(targets),
        prompt_contract_version=mapping["prompt_contract_version"],  # type: ignore[arg-type]
        question=mapping["question"],  # type: ignore[arg-type]
    )


#: An entry under either evidence version. Both expose the same read surface
#: (``candidate_id``, ``status``, ``claims``, ``provenance``, ``action_evidence``,
#: ``confidence``, ``evidence_type``, ``risks``), which is what this layer uses.
AnyEvidenceEntry = Union[CandidateEvidenceEntry, CandidateEvidenceEntryV2]

#: An evidence document under either version.
AnyEvidence = Union[CandidateEvidence, CandidateEvidenceV2]


@dataclass(frozen=True)
class EntryOutcome:
    """What became of one Candidate's analysis.

    ``entry`` is never ``None``: the outcome always carries the entry the Candidate
    will have in the evidence document, either its analysis or an
    ``ANALYSIS_FAILED`` placeholder. ``failure`` states why when it is a
    placeholder. There is no third state, and no Candidate is ever absent.
    """

    candidate_id: str
    entry: AnyEvidenceEntry
    failure: str | None = None
    rejected_claims: int = 0
    malformed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.entry, (CandidateEvidenceEntry, CandidateEvidenceEntryV2)):
            raise CandidateAnalysisError(
                "an outcome always carries its Candidate Evidence entry"
            )
        if self.entry.candidate_id != self.candidate_id:
            raise CandidateAnalysisError(
                "an outcome entry must belong to the outcome's Candidate"
            )
        if self.entry.status is EvidenceStatus.ANALYZED:
            if self.failure is not None:
                raise CandidateAnalysisError("an analyzed Candidate states no failure")
            if self.rejected_claims or self.malformed:
                raise CandidateAnalysisError(
                    "an analyzed Candidate was not refused for a claim or a shape"
                )
        elif self.failure is None and (self.rejected_claims or self.malformed):
            raise CandidateAnalysisError(
                "a claim refusal or a malformed payload is a recorded failure"
            )

    @property
    def analyzed(self) -> bool:
        """Whether the analyzer actually analyzed this Candidate.

        A provider may answer ``UNKNOWN`` or ``ANALYSIS_FAILED`` itself. That is a
        legitimate answer, not a pipeline failure: the Candidate is present, says
        so, and carries no ``failure`` reason. ``failure`` records only what the
        pipeline refused or could not obtain.
        """

        return self.entry.status is EvidenceStatus.ANALYZED

    @property
    def status(self) -> EvidenceStatus:
        return self.entry.status


@dataclass(frozen=True)
class CandidateAnalysisResponse:
    """One provider answer, validated against the request it claims to answer."""

    run_id: str
    candidate_pool_id: str
    provider: str
    model: str
    prompt_contract_version: str
    request: ArtifactReference
    outcomes: tuple[EntryOutcome, ...]
    response_failure: str | None = None
    unexpected_entries: int = 0

    def __post_init__(self) -> None:
        for position, outcome in enumerate(self.outcomes):
            if not isinstance(outcome, EntryOutcome):
                raise CandidateAnalysisError(
                    f"entries[{position}] must be an EntryOutcome"
                )
        candidate_ids = [outcome.candidate_id for outcome in self.outcomes]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise CandidateAnalysisError("an answer must not repeat a Candidate")
        object.__setattr__(
            self,
            "outcomes",
            tuple(sorted(self.outcomes, key=lambda item: item.candidate_id)),
        )

    @property
    def analysis_run(self) -> AnalysisRun:
        return AnalysisRun(
            run_id=self.run_id,
            provider=self.provider,
            model=self.model,
            prompt_contract_version=self.prompt_contract_version,
        )

    def outcome_for(self, candidate_id: str) -> EntryOutcome:
        for outcome in self.outcomes:
            if outcome.candidate_id == candidate_id:
                return outcome
        raise CandidateAnalysisError("candidate_id has no outcome")

    def counts(self) -> dict[str, int]:
        counts = {
            "analyzed": 0,
            "unknown": 0,
            "analysis_failed": 0,
            "direct_support": 0,
            "contextual_support": 0,
            "inferred_support": 0,
            "unsupported_claim_rejections": 0,
            "malformed_entries": 0,
            "unexpected_candidate_entries": self.unexpected_entries,
        }
        for outcome in self.outcomes:
            if outcome.entry.status is EvidenceStatus.ANALYZED:
                counts["analyzed"] += 1
            elif outcome.entry.status is EvidenceStatus.UNKNOWN:
                counts["unknown"] += 1
            else:
                counts["analysis_failed"] += 1
            counts["unsupported_claim_rejections"] += outcome.rejected_claims
            if outcome.malformed:
                counts["malformed_entries"] += 1
            for claim in outcome.entry.claims or ():
                if claim.support is ClaimSupport.DIRECT:
                    counts["direct_support"] += 1
                elif claim.support is ClaimSupport.CONTEXTUAL:
                    counts["contextual_support"] += 1
                else:
                    counts["inferred_support"] += 1
        return counts


def _entry_payload_claims(payload: Mapping[str, object]) -> list[object]:
    raw = payload.get("claims")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CandidateAnalysisError("claims must be a JSON array or null")
    return raw


def _v1_entry(
    payload: Mapping[str, object],
    *,
    pool_id: str,
    envelope: ClaimEnvelope,
    analysis_run: AnalysisRun,
) -> CandidateEvidenceEntry:
    """Build one v1 entry through the v1 parser.

    The analyzer's payload is put into a single-entry document and handed to the
    contract's own parser, so every rule — exact keys, vocabulary, chronology,
    confidence bounds, DIRECT provenance, and the field-consistency rules — is
    enforced by the contract itself rather than by a second copy living here.
    """

    document = {
        "schema_version": CANDIDATE_EVIDENCE_SCHEMA_VERSION,
        "candidate_pool_id": pool_id,
        "product_facts": envelope.product_facts().as_dict(),
        "analysis_run": analysis_run.as_dict(),
        "entries": [dict(payload)],
    }
    try:
        return parse_candidate_evidence(document).entries[0]
    except CandidateEvidenceContractError as exc:
        raise CandidateAnalysisError(str(exc)) from exc


def _build_entry(
    payload: Mapping[str, object],
    *,
    pool_id: str,
    envelope: ClaimEnvelope,
    analysis_run: AnalysisRun,
    evidence_contract_version: str = CANDIDATE_EVIDENCE_SCHEMA_VERSION,
) -> AnyEvidenceEntry:
    """Build one entry under the requested evidence version.

    A v2 entry is a validated v1 entry plus the two structured observation
    fields, so the version with more to say reuses the version that was already
    reviewed instead of restating its rules.
    """

    if evidence_contract_version == CANDIDATE_EVIDENCE_SCHEMA_VERSION:
        return _v1_entry(
            payload, pool_id=pool_id, envelope=envelope, analysis_run=analysis_run
        )
    if evidence_contract_version != CANDIDATE_EVIDENCE_V2_SCHEMA_VERSION:
        raise CandidateAnalysisError(
            "unknown evidence contract version; expected one of: "
            + ", ".join(
                sorted(
                    [CANDIDATE_EVIDENCE_SCHEMA_VERSION, CANDIDATE_EVIDENCE_V2_SCHEMA_VERSION]
                )
            )
        )
    base = _v1_entry(
        entry_payload_without_v2_keys(payload),
        pool_id=pool_id,
        envelope=envelope,
        analysis_run=analysis_run,
    )
    try:
        observations = observations_v2_from_payload(payload)
    except CandidateEvidenceContractError as exc:
        raise CandidateAnalysisError(str(exc)) from exc
    try:
        return CandidateEvidenceEntryV2(base=base, observations=observations)
    except CandidateEvidenceContractError as exc:
        raise CandidateAnalysisError(str(exc)) from exc


def _failed_entry(
    candidate_id: str,
    reason: str,
    evidence_contract_version: str = CANDIDATE_EVIDENCE_SCHEMA_VERSION,
) -> AnyEvidenceEntry:
    """A visible failure. The Candidate stays in the document and says why."""

    base = CandidateEvidenceEntry(
        candidate_id=candidate_id,
        status=EvidenceStatus.ANALYSIS_FAILED,
        rationale=reason,
    )
    if evidence_contract_version == CANDIDATE_EVIDENCE_V2_SCHEMA_VERSION:
        return CandidateEvidenceEntryV2(base=base, observations=None)
    return base


def _failure_outcome(
    candidate_id: str,
    reason: str,
    *,
    malformed: bool = False,
    evidence_contract_version: str = CANDIDATE_EVIDENCE_SCHEMA_VERSION,
) -> EntryOutcome:
    return EntryOutcome(
        candidate_id=candidate_id,
        entry=_failed_entry(candidate_id, reason, evidence_contract_version),
        failure=reason,
        malformed=malformed,
    )


def parse_analysis_response(
    document: object,
    *,
    request: CandidateAnalysisRequest,
    request_text: object | None = None,
    evidence_contract_version: str = CANDIDATE_EVIDENCE_SCHEMA_VERSION,
) -> CandidateAnalysisResponse:
    """Validate one provider answer. Fail closed, but never lose a Candidate.

    Two levels of failure are distinguished on purpose:

    ``response`` level
        The answer cannot be attributed to this request at all — wrong schema, a
        different run, Pool, prompt contract, or request revision, an unknown
        Candidate, or a field the core contract does not define. Every Candidate
        is then recorded ``ANALYSIS_FAILED`` with the reason, so the failure is
        visible and the cardinality rule still holds.

    ``entry`` level
        One Candidate's payload is malformed, or asserts a claim outside the
        envelope. That Candidate is recorded ``ANALYSIS_FAILED``; the others
        survive, and the counters expose the pattern.
    """

    if not isinstance(request, CandidateAnalysisRequest):
        raise CandidateAnalysisError("request must be a CandidateAnalysisRequest")
    expected = request.candidate_ids

    def all_failed(reason: str, unexpected: int = 0) -> CandidateAnalysisResponse:
        return CandidateAnalysisResponse(
            run_id=request.run_id,
            candidate_pool_id=request.candidate_pool_id,
            provider="UNKNOWN",
            model="UNKNOWN",
            prompt_contract_version=request.prompt_contract_version,
            request=request_reference(request),
            outcomes=tuple(
                _failure_outcome(item, reason, evidence_contract_version=evidence_contract_version)
                for item in expected
            ),
            response_failure=reason,
            unexpected_entries=unexpected,
        )

    try:
        mapping = _object(document, "analysis response")
        _exact_keys(mapping, _RESPONSE_KEYS, "analysis response")
    except CandidateAnalysisError as exc:
        return all_failed(f"the response is not a usable document: {exc}")

    if mapping["schema_version"] != RESPONSE_SCHEMA_VERSION:
        return all_failed(
            f"the response schema_version must be {RESPONSE_SCHEMA_VERSION!r}"
        )
    if mapping["run_id"] != request.run_id:
        return all_failed("the response answers a different run_id")
    if mapping["candidate_pool_id"] != request.candidate_pool_id:
        return all_failed("the response answers a different Candidate Pool")
    if mapping["prompt_contract_version"] != request.prompt_contract_version:
        return all_failed(
            "the response was produced under a different prompt contract version"
        )

    try:
        declared = parse_artifact_reference(
            mapping["request"],
            label="analysis response.request",
            expected_ref=producer_registry.CANDIDATE_ANALYSIS_REQUEST_ARTIFACT,
        )
    except ArtifactReferenceError as exc:
        return all_failed(f"the response request reference is malformed: {exc}")
    if request_text is not None:
        try:
            validate_reference_binding(
                declared, request_text, label="analysis response.request"
            )
        except ArtifactReferenceError as exc:
            return all_failed(f"the response answers a different request: {exc}")

    try:
        analysis_run = AnalysisRun(
            run_id=_token(mapping["run_id"], "provider metadata run_id"),  # type: ignore[arg-type]
            provider=_token(mapping["provider"], "response.provider"),  # type: ignore[arg-type]
            model=_token(mapping["model"], "response.model"),  # type: ignore[arg-type]
            prompt_contract_version=mapping["prompt_contract_version"],  # type: ignore[arg-type]
        )
    except (CandidateAnalysisError, CandidateEvidenceContractError) as exc:
        return all_failed(f"the response provider metadata is malformed: {exc}")

    raw_entries = _array(mapping["entries"], "analysis response.entries")
    payloads: dict[str, Mapping[str, object]] = {}
    unexpected = 0
    for position, raw in enumerate(raw_entries):
        try:
            item = _object(raw, f"entries[{position}]")
        except CandidateAnalysisError as exc:
            return all_failed(f"the response entries are not usable: {exc}")
        candidate_id = item.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id not in expected:
            unexpected += 1
            continue
        if candidate_id in payloads:
            return all_failed(
                "the response reports the same Candidate more than once"
            )
        payloads[candidate_id] = item

    if unexpected:
        return all_failed(
            "the response reports a Candidate that was not requested",
            unexpected=unexpected,
        )

    outcomes: list[EntryOutcome] = []
    for candidate_id in expected:
        payload = payloads.get(candidate_id)
        if payload is None:
            outcomes.append(
                _failure_outcome(
                    candidate_id,
                    "the analyzer returned no entry for this Candidate; the "
                    "Candidate is recorded as ANALYSIS_FAILED rather than dropped",
                    evidence_contract_version=evidence_contract_version,
                )
            )
            continue
        try:
            _exact_keys(payload, _ENTRY_KEYS, "an entry")
        except CandidateAnalysisError as exc:
            outcomes.append(
                _failure_outcome(
                    candidate_id,
                    "the analyzer payload is not the Candidate Evidence entry "
                    f"shape, so no provider-specific field can enter the contract: {exc}",
                    malformed=True,
                    evidence_contract_version=evidence_contract_version,
                )
            )
            continue
        rejected = 0
        claims = _entry_payload_claims(payload)
        unsupported = False
        for claim in claims:
            if not isinstance(claim, dict) or not request.claim_envelope.permits(
                claim.get("product_fact_ref")
            ):
                unsupported = True
                rejected += 1
        if unsupported:
            outcomes.append(
                EntryOutcome(
                    candidate_id=candidate_id,
                    entry=_failed_entry(
                        candidate_id,
                        "the analyzer asserted a commercial claim that the Claim "
                        "Envelope does not permit; the entry is refused rather than "
                        "edited",
                        evidence_contract_version,
                    ),
                    failure="a claim outside the Claim Envelope",
                    rejected_claims=rejected,
                )
            )
            continue
        try:
            entry = _build_entry(
                payload,
                pool_id=request.candidate_pool_id,
                envelope=request.claim_envelope,
                analysis_run=analysis_run,
                evidence_contract_version=evidence_contract_version,
            )
        except CandidateAnalysisError as exc:
            outcomes.append(
                _failure_outcome(
                    candidate_id,
                    f"the analyzer payload failed the Candidate Evidence contract: {exc}",
                    malformed=True,
                    evidence_contract_version=evidence_contract_version,
                )
            )
            continue
        outcomes.append(EntryOutcome(candidate_id=candidate_id, entry=entry))

    return CandidateAnalysisResponse(
        run_id=analysis_run.run_id,
        candidate_pool_id=request.candidate_pool_id,
        provider=analysis_run.provider,
        model=analysis_run.model,
        prompt_contract_version=analysis_run.prompt_contract_version,
        request=declared,
        outcomes=tuple(outcomes),
        unexpected_entries=unexpected,
    )


def build_candidate_evidence(
    *,
    request: CandidateAnalysisRequest,
    response: CandidateAnalysisResponse,
    extraction: CandidateExtraction,
    evidence_contract_version: str = CANDIDATE_EVIDENCE_SCHEMA_VERSION,
) -> AnyEvidence:
    """Assemble and validate the Phase 1 evidence document.

    The final gate is the Phase 1 validator itself, over the real Pool and the
    extended Identity Catalog, so a produced document is exactly as valid as a
    hand-written one.
    """

    if not isinstance(response, CandidateAnalysisResponse):
        raise CandidateAnalysisError("response must be a CandidateAnalysisResponse")
    if not isinstance(extraction, CandidateExtraction):
        raise CandidateAnalysisError("extraction must be a CandidateExtraction")
    if response.candidate_pool_id != extraction.pool.pool_id:
        raise CandidateAnalysisError(
            "the response answers a different Candidate Pool than this extraction"
        )
    entries = tuple(outcome.entry for outcome in response.outcomes)
    if evidence_contract_version == CANDIDATE_EVIDENCE_V2_SCHEMA_VERSION:
        evidence_v2 = CandidateEvidenceV2(
            candidate_pool_id=extraction.pool.pool_id,
            product_facts=request.claim_envelope.product_facts(),
            analysis_run=response.analysis_run,
            entries=tuple(
                entry
                if isinstance(entry, CandidateEvidenceEntryV2)
                else CandidateEvidenceEntryV2(base=entry, observations=None)
                for entry in entries
            ),
        )
        try:
            validate_candidate_evidence_v2(
                evidence_v2, extraction.pool, extraction.catalog
            )
        except CandidateEvidenceContractError as exc:
            raise CandidateAnalysisError(
                "the produced Candidate Evidence does not satisfy "
                f"candidate_evidence.v2: {exc}"
            ) from exc
        return evidence_v2
    if evidence_contract_version != CANDIDATE_EVIDENCE_SCHEMA_VERSION:
        raise CandidateAnalysisError(
            "unknown evidence contract version: " + str(evidence_contract_version)
        )
    evidence = CandidateEvidence(
        candidate_pool_id=extraction.pool.pool_id,
        product_facts=request.claim_envelope.product_facts(),
        analysis_run=response.analysis_run,
        entries=entries,  # type: ignore[arg-type]
    )
    try:
        validate_candidate_evidence(evidence, extraction.pool, extraction.catalog)
    except CandidateEvidenceContractError as exc:
        raise CandidateAnalysisError(
            f"the produced Candidate Evidence does not satisfy candidate_evidence.v1: {exc}"
        ) from exc
    return evidence


@dataclass(frozen=True)
class ExtractionStageResult:
    """What the PROPOSE CANDIDATES stage produced, and where it came from."""

    extraction: CandidateExtraction
    proposal_source: str
    proposal_failure: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "stage": "PROPOSE CANDIDATES",
            "proposal_source": self.proposal_source,
            "proposal_failure": self.proposal_failure,
            "extraction": self.extraction.counts(),
            "rejection_counts": self.extraction.rejection_counts(),
            "candidate_pool_id": self.extraction.pool.pool_id,
            "candidates": [
                {
                    **candidate.as_dict(),
                    "measured": self.extraction.measured_for(candidate.candidate_id).as_dict(),
                }
                for candidate in self.extraction.candidates
            ],
        }


@dataclass(frozen=True)
class EvidenceStageResult:
    """What the ANALYZE CANDIDATES stage produced, and how to read it."""

    extraction: CandidateExtraction
    request: CandidateAnalysisRequest
    response: CandidateAnalysisResponse
    evidence: AnyEvidence
    evidence_text: str
    response_source: str

    def as_dict(self) -> dict[str, object]:
        reference = evidence_reference(self.evidence)
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "stage": "ANALYZE CANDIDATES",
            "run_id": self.request.run_id,
            "provider": self.response.provider,
            "model": self.response.model,
            "prompt_contract_version": self.response.prompt_contract_version,
            "response_source": self.response_source,
            "response_failure": self.response.response_failure,
            "extraction": self.extraction.counts(),
            "rejection_counts": self.extraction.rejection_counts(),
            "candidate_pool_id": self.extraction.pool.pool_id,
            "analysis": self.response.counts(),
            "evidence": {
                "ref": reference.ref,
                "sha256": reference.sha256,
                "entries": len(self.evidence.entries),
                "pool_size": len(self.extraction.pool.entries),
            },
        }


def evidence_contract_version_of(evidence: AnyEvidence) -> str:
    """Which contract version one evidence document is expressed under."""

    if isinstance(evidence, CandidateEvidenceV2):
        return CANDIDATE_EVIDENCE_V2_SCHEMA_VERSION
    if isinstance(evidence, CandidateEvidence):
        return CANDIDATE_EVIDENCE_SCHEMA_VERSION
    raise CandidateAnalysisError("evidence must be a Candidate Evidence document")


def render_evidence(evidence: AnyEvidence) -> str:
    """Canonical bytes for either evidence version."""

    if isinstance(evidence, CandidateEvidenceV2):
        return render_candidate_evidence_v2(evidence)
    return render_candidate_evidence(evidence)


def evidence_reference(
    evidence: AnyEvidence, ref: object = CANDIDATE_EVIDENCE_CANONICAL_REF
) -> ArtifactReference:
    """The reference binding whichever version was produced."""

    return artifact_reference(ref, render_evidence(evidence))


def _write_json(job_root: Path, artifact: str, payload: str) -> Path:
    target = Path(job_root) / artifact
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")
    return target


def _read_json(job_root: Path, artifact: str) -> object | None:
    path = Path(job_root) / artifact
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run_candidate_extraction_stage(
    *,
    job_root: Path | str,
    catalog: IdentityCatalog,
    measurements: Sequence[object],
    segmentations: Sequence[object],
    agent: authoring.AuthoringAgent | None = None,
    proposals: Sequence[WindowProposal] | None = None,
) -> ExtractionStageResult:
    """Run PROPOSE CANDIDATES: proposal, validation, Pool, and the artifacts.

    ``proposals`` may be supplied directly (a test, a fixture, or a recorded
    analyzer answer). Otherwise the window proposal artifact is requested through
    the authoring seam, and an analyzer that does not answer leaves a recorded
    failure rather than a silent empty result.
    """

    root = Path(job_root)
    proposal_failure: str | None = None
    source = "SUPPLIED_PROPOSALS"
    if proposals is None:
        if agent is None:
            raise CandidateAnalysisError(
                "the PROPOSE CANDIDATES stage needs either proposals or an analyzer agent"
            )
        request = authoring.request_for_vnext(
            producer_registry.CANDIDATE_WINDOW_PROPOSAL_ARTIFACT, root
        )
        try:
            answered = bool(agent.author(request))
        except Exception as exc:  # a broken adapter is a provider failure
            answered = False
            proposal_failure = f"the analyzer adapter raised {type(exc).__name__}"
        source = "AUTHORING_SEAM"
        if not answered:
            proposal_failure = proposal_failure or (
                "the analyzer adapter produced no window proposal"
            )
            proposals = ()
        else:
            try:
                document = _read_json(
                    root, producer_registry.CANDIDATE_WINDOW_PROPOSAL_ARTIFACT
                )
                proposals = parse_window_proposals(document)
            except (OSError, json.JSONDecodeError, CandidateExtractionError) as exc:
                proposal_failure = f"the window proposal is not usable: {exc}"
                proposals = ()

    extraction = extract_candidates(
        catalog=catalog,
        measurements=measurements,  # type: ignore[arg-type]
        segmentations=segmentations,  # type: ignore[arg-type]
        proposals=tuple(proposals),
    )
    _write_json(root, producer_registry.CANDIDATE_EXTRACTION_ARTIFACT, render_extraction(extraction))
    _write_json(
        root,
        producer_registry.CANDIDATE_POOL_ARTIFACT,
        render_candidate_pool(extraction.pool),
    )
    return ExtractionStageResult(
        extraction=extraction,
        proposal_source=source,
        proposal_failure=proposal_failure,
    )


def run_candidate_evidence_stage(
    *,
    job_root: Path | str,
    extraction: CandidateExtraction,
    envelope: ClaimEnvelope,
    run_id: str,
    prompt_contract_version: str = PROMPT_CONTRACT_VERSION,
    agent: authoring.AuthoringAgent | None = None,
    response_document: object | None = None,
) -> EvidenceStageResult:
    """Run ANALYZE CANDIDATES: request, provider answer, evidence, validation.

    The request artifact is always written first, so a provider answer is bound to
    a request that exists on disk. The answer comes either from the authoring seam
    (a real adapter or a scripted agent) or from a supplied recorded document.
    Either way it is validated against the request before anything is produced.

    ``prompt_contract_version`` selects the instruction the analyzer is asked under,
    and the request is rendered from that same contract, so the version a response
    declares and the version it was asked under cannot drift apart.
    """

    root = Path(job_root)
    contract = prompt_contract(prompt_contract_version)
    evidence_version = contract.evidence_contract_version
    targets = targets_from_extraction(extraction)
    request = CandidateAnalysisRequest(
        run_id=run_id,
        candidate_pool_id=extraction.pool.pool_id,
        claim_envelope=envelope,
        targets=targets,
        prompt_contract_version=contract.version,
        question=contract.question,
    )
    request_text = render_analysis_request(request)
    _write_json(root, producer_registry.CANDIDATE_ANALYSIS_REQUEST_ARTIFACT, request_text)

    response_failure: str | None = None
    document: object | None = None
    if response_document is not None:
        source = "SUPPLIED_DOCUMENT"
        document = response_document
    else:
        if agent is None:
            raise CandidateAnalysisError(
                "the ANALYZE CANDIDATES stage needs either a response or an analyzer agent"
            )
        source = "AUTHORING_SEAM"
        request_object = authoring.request_for_vnext(
            producer_registry.CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT, root
        )
        try:
            answered = bool(agent.author(request_object))
        except Exception as exc:  # a broken adapter is a provider failure
            answered = False
            response_failure = f"the analyzer adapter raised {type(exc).__name__}"
        if not answered:
            response_failure = response_failure or (
                "the analyzer adapter produced no response; every Candidate is "
                "recorded as ANALYSIS_FAILED"
            )
        else:
            try:
                document = _read_json(
                    root, producer_registry.CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT
                )
            except (OSError, json.JSONDecodeError) as exc:
                response_failure = f"the analysis response is not readable JSON: {exc}"
                document = None

    if document is None:
        # No answer at all. Every Candidate is recorded as failed, so a provider
        # outage is visible in the evidence rather than being an empty document.
        reason = response_failure or "the analyzer produced no response"
        response = CandidateAnalysisResponse(
            run_id=request.run_id,
            candidate_pool_id=request.candidate_pool_id,
            provider="UNKNOWN",
            model="UNKNOWN",
            prompt_contract_version=request.prompt_contract_version,
            request=request_reference(request),
            outcomes=tuple(
                _failure_outcome(
                    candidate_id, reason, evidence_contract_version=evidence_version
                )
                for candidate_id in request.candidate_ids
            ),
            response_failure=reason,
        )
    else:
        response = parse_analysis_response(
            document,
            request=request,
            request_text=request_text,
            evidence_contract_version=evidence_version,
        )

    evidence = build_candidate_evidence(
        request=request,
        response=response,
        extraction=extraction,
        evidence_contract_version=evidence_version,
    )
    evidence_text = render_evidence(evidence)
    _write_json(root, producer_registry.CANDIDATE_EVIDENCE_ARTIFACT, evidence_text)
    return EvidenceStageResult(
        extraction=extraction,
        request=request,
        response=response,
        evidence=evidence,
        evidence_text=evidence_text,
        response_source=source,
    )


def parse_measurements(document: object) -> tuple[object, ...]:
    """Parse a ``candidate_measurements.v1`` document (measured PTS per stream)."""

    mapping = _object(document, "candidate measurements")
    _exact_keys(mapping, ("schema_version", "measurements"), "candidate measurements")
    if mapping["schema_version"] != MEASUREMENTS_SCHEMA_VERSION:
        raise CandidateAnalysisError(
            f"schema_version must be {MEASUREMENTS_SCHEMA_VERSION!r}"
        )
    measurements = []
    for position, raw in enumerate(_array(mapping["measurements"], "measurements")):
        item = _object(raw, f"measurements[{position}]")
        _exact_keys(
            item,
            ("material_id", "stream_index", "source", "timestamps", "fps"),
            f"measurements[{position}]",
        )
        measurements.append(
            SourceMeasurement(
                material_id=item["material_id"],  # type: ignore[arg-type]
                stream_index=item["stream_index"],  # type: ignore[arg-type]
                source=item["source"],  # type: ignore[arg-type]
                timestamps=tuple(
                    _array(item["timestamps"], f"measurements[{position}].timestamps")
                ),  # type: ignore[arg-type]
                fps=item["fps"],  # type: ignore[arg-type]
            )
        )
    return tuple(measurements)


def parse_segmentations(document: object) -> tuple[object, ...]:
    """Parse a ``candidate_segmentations.v1`` document into visual segments."""

    mapping = _object(document, "candidate segmentations")
    _exact_keys(
        mapping, ("schema_version", "segmentations"), "candidate segmentations"
    )
    if mapping["schema_version"] != SEGMENTATIONS_SCHEMA_VERSION:
        raise CandidateAnalysisError(
            f"schema_version must be {SEGMENTATIONS_SCHEMA_VERSION!r}"
        )
    segmentations = []
    for position, raw in enumerate(
        _array(mapping["segmentations"], "segmentations")
    ):
        item = _object(raw, f"segmentations[{position}]")
        _exact_keys(
            item,
            ("material_id", "stream_index", "segments"),
            f"segmentations[{position}]",
        )
        spans = []
        for index, raw_span in enumerate(
            _array(item["segments"], f"segmentations[{position}].segments")
        ):
            span = _object(
                raw_span, f"segmentations[{position}].segments[{index}]"
            )
            _exact_keys(
                span,
                ("start_frame", "end_frame_exclusive"),
                f"segmentations[{position}].segments[{index}]",
            )
            spans.append(
                SegmentSpan(
                    segment_index=index,
                    start_frame=span["start_frame"],  # type: ignore[arg-type]
                    end_frame_exclusive=span["end_frame_exclusive"],  # type: ignore[arg-type]
                )
            )
        segmentations.append(
            SourceSegmentation(
                material_id=item["material_id"],  # type: ignore[arg-type]
                stream_index=item["stream_index"],  # type: ignore[arg-type]
                segments=tuple(spans),
            )
        )
    return tuple(segmentations)


def _load_json(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    """Shadow-mode entry point. It produces Candidate Evidence and stops there.

    Exit codes follow the repository convention: 0 complete, 3 blocked, 6 failed.
    """

    parser = argparse.ArgumentParser(
        prog="python3 -m src.ai_autocut.candidate_analysis",
        description=(
            "Editing Intelligence vNext shadow stage: extract Candidates and produce "
            "candidate_evidence.v1. It does not generate hooks or plan a sequence."
        ),
    )
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--stage", required=True, choices=("propose", "analyze"))
    parser.add_argument("--measurements", required=True, help="candidate_measurements.v1")
    parser.add_argument("--segmentations", required=True, help="candidate_segmentations.v1")
    parser.add_argument("--catalog", required=True, help="material_candidate_identity.v1")
    parser.add_argument("--proposals", help="candidate_window_proposal.v1 (recorded answer)")
    parser.add_argument("--envelope", help="claim_envelope.v1 (required for --stage analyze)")
    parser.add_argument("--response", help="candidate_analysis_response.v1 (recorded answer)")
    parser.add_argument("--agent-command", help="analyzer adapter command, invoked through the seam")
    parser.add_argument("--run-id", default="analysisrunv1_shadow")
    args = parser.parse_args(argv)

    root = Path(args.job_root)
    try:
        catalog = parse_identity_catalog(_load_json(args.catalog))
        measurements = parse_measurements(_load_json(args.measurements))
        segmentations = parse_segmentations(_load_json(args.segmentations))
    except (OSError, json.JSONDecodeError, CandidateAnalysisError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 3

    agent: authoring.AuthoringAgent | None = (
        authoring.CommandAuthoringAgent(args.agent_command) if args.agent_command else None
    )

    proposals: tuple[WindowProposal, ...] | None = None
    if args.proposals:
        try:
            proposals = parse_window_proposals(_load_json(args.proposals))
        except (OSError, json.JSONDecodeError, CandidateExtractionError) as exc:
            print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
            return 3

    extraction_result = run_candidate_extraction_stage(
        job_root=root,
        catalog=catalog,
        measurements=measurements,
        segmentations=segmentations,
        agent=agent,
        proposals=proposals,
    )
    if args.stage == "propose":
        print(json.dumps(extraction_result.as_dict(), ensure_ascii=False, indent=2))
        return 0

    if not args.envelope:
        print(
            json.dumps(
                {"status": "BLOCKED", "reason": "--stage analyze requires --envelope"},
                ensure_ascii=False,
            )
        )
        return 3
    try:
        envelope = parse_claim_envelope(_load_json(args.envelope))
        response_document = _load_json(args.response) if args.response else None
    except (OSError, json.JSONDecodeError, CandidateAnalysisError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 3

    try:
        analysis = run_candidate_evidence_stage(
            job_root=root,
            extraction=extraction_result.extraction,
            envelope=envelope,
            run_id=args.run_id,
            agent=agent,
            response_document=response_document,
        )
    except CandidateAnalysisError as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)}, ensure_ascii=False))
        return 6
    print(json.dumps(analysis.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
