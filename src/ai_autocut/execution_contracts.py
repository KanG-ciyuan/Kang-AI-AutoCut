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

from pathlib import Path

from .intervention_ledger import INTERVENTION_KINDS
from .media_probe import (
    MediaProbeError,
    count_black_frames,
    count_duplicate_frames,
    measure_loudness,
    probe_streams,
    resolve_media_path,
    sha256_of_file,
)
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


def _verify_assembly_evidence(
    document: object,
    *,
    job_root: str | Path | None = None,
    expected_frame_count: int | None = None,
    loudness_target_lufs: float | None = None,
    true_peak_ceiling_dbtp: float | None = None,
) -> dict[str, object]:
    """Verify the **actual master file**, not a claim about it.

    Independent inspection found that this accepted a JSON document without opening
    anything: a nonexistent path, a fabricated SHA256, a fabricated frame count and
    fabricated audio measurements all passed. Every value below is now measured from the
    bytes on disk, and every supplied value is reconciled against the measurement.

    It refuses, in order:

    * a missing or unreadable master
    * a supplied ``master_sha256`` that does not match the recomputed digest
    * a supplied ``frame_count`` that does not match the decoded count
    * a decoded count that does not match an expected upstream count
    * any black frame
    * a freeze: three or more consecutive identical decoded frames
    * a master with no audio stream, or with unmeasurable loudness
    * clipping, per the project's accepted contract
    """

    if not isinstance(document, Mapping):
        raise ExecutionContractError("assembly evidence must be a JSON object")
    missing = [key for key in ASSEMBLY_REQUIRED_KEYS if key not in document]
    if missing:
        raise ExecutionContractError(
            "assembly evidence is missing required evidence: " + ", ".join(missing)
        )

    path = resolve_media_path(document["master_path"], job_root=job_root)
    if not path.is_file():
        raise ExecutionContractError(f"assembly evidence names a master that does not exist: {path}")

    supplied_sha = document["master_sha256"]
    if not isinstance(supplied_sha, str) or len(supplied_sha) != 64:
        raise ExecutionContractError(
            "assembly evidence must carry a full 64-character sha256 of the master"
        )
    measured_sha = sha256_of_file(path)
    if measured_sha != supplied_sha:
        raise ExecutionContractError(
            "the supplied master_sha256 does not match the file on disk "
            f"(supplied {supplied_sha[:16]}..., measured {measured_sha[:16]}...)"
        )

    measured = probe_streams(path)
    if not measured["has_audio"]:
        raise ExecutionContractError("the master has no audio stream")

    supplied_frames = document["frame_count"]
    if not isinstance(supplied_frames, int) or isinstance(supplied_frames, bool) or supplied_frames <= 0:
        raise ExecutionContractError("assembly evidence must state a positive frame count")
    decoded_frames = measured["frame_count"]
    if decoded_frames is None:
        raise ExecutionContractError("the master's frame count could not be measured")
    if decoded_frames != supplied_frames:
        raise ExecutionContractError(
            f"the supplied frame count {supplied_frames} does not match the decoded "
            f"count {decoded_frames}"
        )
    if expected_frame_count is not None and decoded_frames != expected_frame_count:
        raise ExecutionContractError(
            f"the master holds {decoded_frames} frames but the upstream evidence "
            f"expected {expected_frame_count}"
        )

    method = document["method"]
    if method not in ("REMUX", "RE_ENCODE"):
        raise ExecutionContractError(
            f"assembly method {method!r} must be REMUX or RE_ENCODE"
        )

    black_frames = count_black_frames(path)
    if black_frames > 0:
        raise ExecutionContractError(
            f"the master contains {black_frames} black frame(s); a black frame is a "
            "defect, not a pass"
        )
    duplicates = count_duplicate_frames(path)
    if duplicates > 0:
        raise ExecutionContractError(
            f"the master contains {duplicates} frozen frame(s): three or more "
            "consecutive identical decoded frames"
        )

    loudness = measure_loudness(path)
    true_peak = loudness["true_peak_dbtp"]
    sample_peak = loudness.get("sample_peak_dbfs")
    if sample_peak is not None and sample_peak >= 0.0:
        raise ExecutionContractError(
            f"the master clips: sample peak {sample_peak:.2f} dBFS is at or above full scale"
        )
    if true_peak_ceiling_dbtp is not None and true_peak > true_peak_ceiling_dbtp:
        raise ExecutionContractError(
            f"true peak {true_peak:.2f} dBTP exceeds the ceiling "
            f"{true_peak_ceiling_dbtp:.2f} dBTP"
        )

    claimed_audio = document["audio"]
    if not isinstance(claimed_audio, Mapping) or "integrated_lufs" not in claimed_audio:
        raise ExecutionContractError(
            "assembly evidence must carry measured audio loudness (integrated_lufs)"
        )
    if abs(float(claimed_audio["integrated_lufs"]) - loudness["integrated_lufs"]) > 0.5:
        raise ExecutionContractError(
            f"the supplied integrated loudness {float(claimed_audio['integrated_lufs']):.2f} "
            f"does not match the measured {loudness['integrated_lufs']:.2f} LUFS"
        )
    if loudness_target_lufs is not None and abs(
        loudness["integrated_lufs"] - loudness_target_lufs
    ) > 1.0:
        raise ExecutionContractError(
            f"measured loudness {loudness['integrated_lufs']:.2f} LUFS is more than 1 LU "
            f"from the job's target {loudness_target_lufs:.2f} LUFS"
        )

    return {
        "verified_contract": "assemble_master",
        "master_path": str(path),
        "master_sha256": measured_sha,
        "frame_count": decoded_frames,
        "fps": measured["fps"],
        "width": measured["width"],
        "height": measured["height"],
        "duration_seconds": measured["duration_seconds"],
        "video_codec": measured["video_codec"],
        "audio_codec": measured["audio_codec"],
        "method": method,
        "black_frames": black_frames,
        "duplicate_frames": duplicates,
        "integrated_lufs": loudness["integrated_lufs"],
        "true_peak_dbtp": true_peak,
        "sample_peak_dbfs": sample_peak,
        "measured": True,
    }


def verify_assembly_evidence(
    document: object,
    *,
    job_root: str | Path | None = None,
    expected_frame_count: int | None = None,
    loudness_target_lufs: float | None = None,
    true_peak_ceiling_dbtp: float | None = None,
) -> dict[str, object]:
    """Verify the actual master, converting any measurement failure into a contract result.

    A missing tool, an unreadable file or a malformed path is a contract failure, not an
    exception escaping to the caller.
    """

    try:
        return _verify_assembly_evidence(
            document,
            job_root=job_root,
            expected_frame_count=expected_frame_count,
            loudness_target_lufs=loudness_target_lufs,
            true_peak_ceiling_dbtp=true_peak_ceiling_dbtp,
        )
    except MediaProbeError as exc:
        raise ExecutionContractError(f"the master could not be measured: {exc}") from exc


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
