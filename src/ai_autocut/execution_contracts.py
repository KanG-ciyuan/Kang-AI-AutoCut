"""Execution contracts for the four unbuilt boundaries.

What these are
--------------
Picture execution, typography execution, audio rendering/mixing, and assembly are not
implemented in this repository, and this phase does **not** build them. What was missing
was a *reproducible contract* for each: the shape a job-specific adapter must satisfy,
what it must leave behind as evidence, and what has to be true before the run resumes.

A job-specific adapter is allowed. A hidden remembered command is not.

Why they are data
-----------------
Declaring the contract means "you must build a renderer" is a statement a later reader
can check, and "an adapter supplied this" is a claim with a named validator behind it.
The fast path consults these contracts rather than trusting that someone remembered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .intervention_ledger import INTERVENTION_KINDS
from .producer_registry import PRODUCER_TYPES

#: The four boundaries this registry governs.
CONTRACT_NAMES = ("picture", "typography", "audio", "assemble_master")


class ExecutionContractError(ValueError):
    """Raised when an execution contract is malformed or violated."""


@dataclass(frozen=True)
class ExecutionContract:
    """One execution boundary and what an adapter must satisfy to cross it."""

    name: str
    stage: str
    producer_type: str
    producer_id: str
    required_input: tuple[str, ...]
    expected_output: str
    output_evidence: tuple[str, ...]
    procedure: str
    validation: str
    resume_condition: str
    ledger_obligation: str
    intervention_kind: str
    #: True while no in-repository executor exists. The stage must gate, not pass.
    adapter_required: bool

    def __post_init__(self) -> None:
        if self.name not in CONTRACT_NAMES:
            raise ExecutionContractError(f"unknown contract {self.name!r}")
        if self.producer_type not in PRODUCER_TYPES:
            raise ExecutionContractError(
                f"unknown producer_type {self.producer_type!r}"
            )
        if self.intervention_kind not in INTERVENTION_KINDS:
            raise ExecutionContractError(
                f"unknown intervention_kind {self.intervention_kind!r}"
            )
        for field_name in (
            "procedure", "validation", "resume_condition", "ledger_obligation",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ExecutionContractError(
                    f"contract {self.name!r} must state its {field_name}"
                )

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "stage": self.stage,
            "producer_type": self.producer_type,
            "producer_id": self.producer_id,
            "required_input": list(self.required_input),
            "expected_output": self.expected_output,
            "output_evidence": list(self.output_evidence),
            "procedure": self.procedure,
            "validation": self.validation,
            "resume_condition": self.resume_condition,
            "ledger_obligation": self.ledger_obligation,
            "intervention_kind": self.intervention_kind,
            "adapter_required": self.adapter_required,
        }


CONTRACTS: tuple[ExecutionContract, ...] = (
    ExecutionContract(
        name="picture",
        stage="FINISH THE PICTURE",
        producer_type="ADAPTER",
        producer_id="picture-execution-adapter",
        required_input=("editing plan", "measured picture decisions"),
        expected_output="a corrected/rebuilt picture pass, or an explicit no-correction decision",
        output_evidence=(
            "the decision per shot (KEEP / REVIEW / CORRECT)",
            "for any CORRECT: the measured before and after, and the product-protection outcome",
        ),
        procedure=(
            "Read-only measurement runs first. A correction is only authorised where product "
            "protection passed and the measured difference crossed the reporting level. Where no "
            "reliable product region exists, the shot stays KEEP or REVIEW — never CORRECT."
        ),
        validation="picture_decision.decide_shot and product_protection.assess_protection",
        resume_condition="a picture pass artifact exists and its decisions were produced by the validators above",
        ledger_obligation="record a SUPERVISOR_DECISIONS entry when a CORRECT is authorised",
        intervention_kind="SUPERVISOR_DECISIONS",
        adapter_required=True,
    ),
    ExecutionContract(
        name="typography",
        stage="PLAN THE WORDS",
        producer_type="ADAPTER",
        producer_id="typography-executor",
        required_input=("a validated typography plan", "job-scoped layout and font stack"),
        expected_output="the typography composited onto the accepted picture",
        output_evidence=(
            "output path, frame count and geometry",
            "the layout digest the executor used",
        ),
        procedure=(
            "Implement typography_adapter.TypographyExecutor. Supply this job's own layout and "
            "font stack: there is no default, because a default would be one job's art direction "
            "applied to another. A plan event with an unverified safe area must not reach a "
            "renderer."
        ),
        validation="typography_adapter.execute_typography",
        resume_condition="a TypographyResult exists whose frame count and geometry match the request",
        ledger_obligation="record a SUPERVISOR_DECISIONS entry when a job supplies its typography art direction",
        intervention_kind="SUPERVISOR_DECISIONS",
        adapter_required=True,
    ),
    ExecutionContract(
        name="audio",
        stage="BUILD THE AUDIO",
        producer_type="ADAPTER",
        producer_id="audio-render-adapter",
        required_input=("an approvable audio program", "generated voice and music stems"),
        expected_output="a mixed and mastered audio program",
        output_evidence=(
            "measured integrated loudness and true peak",
            "the stem and mix paths",
            "the paid API call count",
        ),
        procedure=(
            "Generate one continuous voice performance and cut it into segments, place it, then "
            "mix against the declared priority. One continuous performance is the default because "
            "the same prompt does not reliably reproduce the same sampled speaker."
        ),
        validation="audio_executor.measure_loudness and audio_executor.validate_mix",
        resume_condition="a mix artifact exists with measured loudness and true peak recorded",
        ledger_obligation="record a VO_GENERATIONS or BGM_GENERATIONS entry per paid generation call",
        intervention_kind="VO_GENERATIONS",
        adapter_required=True,
    ),
    ExecutionContract(
        name="assemble_master",
        stage="ASSEMBLE & MASTER",
        producer_type="ADAPTER",
        producer_id="packaging-adapter",
        required_input=("accepted picture", "accepted audio program"),
        expected_output="a delivery master plus its measured technical QA",
        output_evidence=(
            "master_path and sha256",
            "frame count, and whether the method was remux or re-encode",
            "black-frame and duplicate-frame counts",
            "audio loudness and true peak",
        ),
        procedure=(
            "Prefer a stream-copy remux when the source already meets the delivery "
            "specification: re-encoding adds a generation of loss for no benefit. Record the "
            "measured QA, not an assertion of it."
        ),
        validation="execution_contracts.verify_assembly_evidence",
        resume_condition="assembly/assembly_evidence.json exists and satisfies this contract",
        ledger_obligation="record a SUPERVISOR_DECISIONS entry when a job supplies a packaging adapter",
        intervention_kind="SUPERVISOR_DECISIONS",
        adapter_required=True,
    ),
)

CONTRACT_BY_NAME: Mapping[str, ExecutionContract] = {c.name: c for c in CONTRACTS}

#: Evidence keys that must be present in an assembly evidence document.
ASSEMBLY_REQUIRED_KEYS = (
    "master_path",
    "master_sha256",
    "frame_count",
    "method",
    "black_frames",
    "audio",
)


def get_contract(name: str) -> ExecutionContract:
    if name not in CONTRACT_BY_NAME:
        raise ExecutionContractError(
            f"unknown execution contract {name!r}; expected one of: "
            + ", ".join(CONTRACT_NAMES)
        )
    return CONTRACT_BY_NAME[name]


def verify_assembly_evidence(document: object) -> dict[str, object]:
    """Check an assembly evidence document against the assemble_master contract.

    A stage must not pass on a claim. This returns what was verified so the stage can
    record it, and raises with the specific missing evidence otherwise.
    """

    if not isinstance(document, Mapping):
        raise ExecutionContractError("assembly evidence must be a JSON object")
    missing = [key for key in ASSEMBLY_REQUIRED_KEYS if key not in document]
    if missing:
        raise ExecutionContractError(
            "assembly evidence is missing required evidence: " + ", ".join(missing)
        )
    method = document["method"]
    if method not in ("REMUX", "RE_ENCODE"):
        raise ExecutionContractError(
            f"assembly method {method!r} must be REMUX or RE_ENCODE"
        )
    frame_count = document["frame_count"]
    if not isinstance(frame_count, int) or isinstance(frame_count, bool) or frame_count <= 0:
        raise ExecutionContractError("assembly evidence must state a positive frame count")
    black = document["black_frames"]
    if not isinstance(black, int) or isinstance(black, bool) or black < 0:
        raise ExecutionContractError("assembly evidence must state a black-frame count")
    if black > 0:
        raise ExecutionContractError(
            f"assembly evidence reports {black} black frame(s); a delivery master with a "
            "black frame is a defect, not a pass"
        )
    audio = document["audio"]
    if not isinstance(audio, Mapping) or "integrated_lufs" not in audio:
        raise ExecutionContractError(
            "assembly evidence must carry measured audio loudness (integrated_lufs)"
        )
    sha = document["master_sha256"]
    if not isinstance(sha, str) or len(sha) != 64:
        raise ExecutionContractError(
            "assembly evidence must carry a full 64-character sha256 of the master"
        )
    return {
        "verified_contract": "assemble_master",
        "frame_count": frame_count,
        "method": method,
        "black_frames": black,
        "integrated_lufs": float(audio["integrated_lufs"]),
    }


def contracts_document() -> dict[str, object]:
    return {
        "schema_version": "execution_contracts.v1",
        "rule": (
            "no universal executor ships in this repository; each boundary declares the "
            "contract a job-specific adapter must satisfy"
        ),
        "contracts": [contract.as_dict() for contract in CONTRACTS],
    }


__all__ = [
    "ASSEMBLY_REQUIRED_KEYS",
    "CONTRACTS",
    "CONTRACT_BY_NAME",
    "CONTRACT_NAMES",
    "ExecutionContract",
    "ExecutionContractError",
    "contracts_document",
    "get_contract",
    "verify_assembly_evidence",
]
