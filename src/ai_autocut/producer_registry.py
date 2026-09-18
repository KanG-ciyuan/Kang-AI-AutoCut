"""Artifact producer registry.

The problem this closes
-----------------------
The Gate G.0 Phase 2B fast path declared its input artifacts but never said **who
produces them**. Independent inspection found the consequence: required artifacts had
undefined producers, so the "pipeline" only ran when someone had already hand-built
every input. That is a validation harness, not a production chain.

The rule here
-------------
Every required artifact has exactly **one** explicit producer, and that producer is one
of four declared kinds:

``AUTO``     the fast path itself writes it
``CODEX``    a Codex/Supervisor producer authors it under a stated contract
``HUMAN``    a human authors or approves it
``ADAPTER``  a job-specific execution adapter produces it

**No required artifact may have NO PRODUCER or UNKNOWN PRODUCER.** A ``CODEX`` or
``HUMAN`` producer is legitimate — the goal of this work is reproducibility, not
autonomy — but only when its input contract, output contract, procedure, evidence
requirement, checkpoint and intervention logging are all explicit and tracked.

This registry deliberately does **not** invent algorithms to remove human involvement.
It makes the human step explicit, gated, recorded and resumable.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

from .intervention_ledger import INTERVENTION_KINDS

#: The four declared producer kinds.
PRODUCER_TYPES = ("AUTO", "CODEX", "HUMAN", "ADAPTER")

#: Every artifact the fast path requires, and who produces it. Order follows the eight
#: semantic stages so a reader can walk the chain.
PRODUCERS: tuple["Producer", ...] = ()


@dataclass(frozen=True)
class Producer:
    """One artifact and the single producer responsible for it."""

    artifact: str
    stage: str
    producer_type: str
    producer_id: str
    #: Artifacts that must exist before this producer can act.
    required_inputs: tuple[str, ...]
    #: The contract the output must satisfy (schema name, or an in-repo validator).
    output_contract: str
    #: Which in-repo validator, if any, checks the output. Empty means none exists yet,
    #: which is itself recorded rather than glossed.
    validated_by: str
    #: What the producer must leave behind for the output to count as evidence.
    evidence: tuple[str, ...]
    #: The ledger kind recorded when this producer gate is raised.
    intervention_kind: str
    #: What must become true for the run to resume past this gate.
    resume_condition: str
    #: The explicit procedure. A remembered command is not a procedure.
    procedure: str

    def __post_init__(self) -> None:
        if self.producer_type not in PRODUCER_TYPES:
            raise ProducerRegistryError(
                f"unknown producer_type {self.producer_type!r}; expected one of: "
                + ", ".join(PRODUCER_TYPES)
            )
        if not self.artifact or not self.producer_id:
            raise ProducerRegistryError("a producer needs an artifact and an id")
        if self.intervention_kind not in INTERVENTION_KINDS:
            raise ProducerRegistryError(
                f"unknown intervention_kind {self.intervention_kind!r}"
            )
        if not self.procedure.strip():
            raise ProducerRegistryError(
                f"{self.artifact!r} must state its procedure explicitly"
            )

    @property
    def requires_gate(self) -> bool:
        """True when a human/Codex/adapter must act before the stage can run."""

        return self.producer_type != "AUTO"

    def as_dict(self) -> dict[str, object]:
        return {
            "artifact": self.artifact,
            "stage": self.stage,
            "producer_type": self.producer_type,
            "producer_id": self.producer_id,
            "required_inputs": list(self.required_inputs),
            "output_contract": self.output_contract,
            "validated_by": self.validated_by,
            "evidence": list(self.evidence),
            "intervention_kind": self.intervention_kind,
            "resume_condition": self.resume_condition,
            "procedure": self.procedure,
        }


class ProducerRegistryError(ValueError):
    """Raised when an artifact has no producer, or a producer is malformed."""


def _p(**kwargs: object) -> Producer:
    return Producer(**kwargs)  # type: ignore[arg-type]


PRODUCERS = (
    _p(
        artifact="source_inventory.json",
        stage="PREPARE",
        producer_type="CODEX",
        producer_id="job_foundation.initialize_job",
        required_inputs=(),
        output_contract="source_inventory.v1",
        validated_by="job_foundation.verify_source_immutability",
        evidence=(
            "per-file sha256, size_bytes and mtime_ns for every discovered source",
            "the product identity the job states",
        ),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="source_inventory.json exists and every listed file still matches its sha256",
        procedure=(
            "python3 -m src.ai_autocut.job_foundation --job-id <ID> --product-name "
            "'<PRODUCT>' --source-root <DIR> --workspace <DIR>. This is the GENERIC "
            "initializer: it discovers supported media in the directory and assumes no "
            "file count and no product. Zero discoverable media is a controlled error. "
            "The historical Filter path remains available behind --filter and is not the "
            "Third-SKU contract."
        ),
    ),
    _p(
        artifact="shots/placements.json",
        stage="UNDERSTAND SHOTS",
        producer_type="CODEX",
        producer_id="placement-author",
        required_inputs=("source_inventory.json",),
        output_contract="placements.v1 (placement_id, source_id, media_path, source_in, source_out_exclusive, t_in_seconds)",
        validated_by="timebase_adapter.TimebaseAdapter.assert_placement_timing",
        evidence=(
            "one entry per source",
            "t_in_seconds is the MEASURED source timestamp",
        ),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="every placement declares t_in_seconds that agrees with the measured PTS table",
        procedure=(
            "For each source in source_inventory.json write one placement covering its full "
            "decoded range. source_in/source_out_exclusive are decoded frame indices used for "
            "segmentation; t_in_seconds is the authoritative source coordinate and is read from "
            "ffprobe pts_time, never computed as frame_index/fps."
        ),
    ),
    _p(
        artifact="edit/timeline_ranges.json",
        stage="PLAN THE EDIT",
        producer_type="CODEX",
        producer_id="edit-planner",
        required_inputs=("shots/shot_understanding.json",),
        output_contract="timeline_ranges.v1 (shot_id, role, start_frame, end_frame_exclusive, evidence?)",
        validated_by="editing_intelligence.validate_timeline_range",
        evidence=("action-like roles carry preparation/onset/completion/result evidence",),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="every range is accepted by validate_timeline_range",
        procedure=(
            "Choose ranges from the segmentation artifact. A range whose role is action, proof "
            "or hero must carry ActionEvidence; the validator refuses a cut that enters after "
            "the observable onset or exits before the observable result."
        ),
    ),
    _p(
        artifact="picture/measurements.json",
        stage="FINISH THE PICTURE",
        producer_type="CODEX",
        producer_id="picture-measurement-author",
        required_inputs=("edit/editing_plan.json",),
        output_contract="picture_measurements.v1 (shots[] with measurement + contains_product + optional protection)",
        validated_by="picture_measurement.ShotMeasurement",
        evidence=("per-shot signalstats measurement", "protection outcome or UNAVAILABLE"),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="every shot carries a measurement accepted by ShotMeasurement",
        procedure=(
            "Run the read-only measurement adapter over the selected source ranges. Every "
            "FFmpeg invocation reads media and discards output; no correction is applied here. "
            "Where no reliable product region can be supplied, record protection as UNAVAILABLE "
            "rather than inventing one."
        ),
    ),
    _p(
        artifact="picture/source_ranges.json",
        stage="FINISH THE PICTURE",
        producer_type="CODEX",
        producer_id="source-range-author",
        required_inputs=("edit/editing_plan.json",),
        output_contract="source_ranges.v1 (unit_id, source, t_in_seconds | source_frame_index, frames)",
        validated_by="timebase_adapter.TimebaseAdapter",
        evidence=("every unit resolves to a measured PTS timestamp",),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="every unit resolves, executes and passes assert_range_coverage",
        procedure=(
            "Express each source range as a timestamp in seconds (preferred) or as a source "
            "frame index, which the adapter resolves through the measured PTS table. The "
            "adapter refuses a range that is not reproducible."
        ),
    ),
    _p(
        artifact="copy/commercial_units.json",
        stage="PLAN THE WORDS",
        producer_type="CODEX",
        producer_id="copy-planner",
        required_inputs=("edit/editing_plan.json",),
        output_contract="commercial_units.v1 (CommercialUnit fields incl. the four caller judgements)",
        validated_by="narration_coverage.assess_narration_coverage",
        evidence=(
            "every unit states visual_self_explanatory, carries_new_commercial_information, "
            "vo_adds_function_beyond_title and explanation_supported",
            "every silence names a reason",
        ),
        intervention_kind="COPY_INTERVENTIONS",
        resume_condition="narration coverage returns PASS",
        procedure=(
            "Author one unit per commercial beat. The four judgement fields are creative "
            "decisions and must be stated; the fast path refuses a unit that omits them rather "
            "than defaulting them. A silent unit carries a non-required VoEvent with a "
            "silence_reason."
        ),
    ),
    _p(
        artifact="audio/placement.json",
        stage="BUILD THE AUDIO",
        producer_type="ADAPTER",
        producer_id="vo-placement-adapter",
        required_inputs=("copy/narration_coverage.json",),
        output_contract="audio_placement.v1 (segments[], slots?, design?, hero_window?, final_segment?)",
        validated_by="audio_program.assess_program",
        evidence=("placed segment start/end per line", "declared design for every intended pause"),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="every line is placed and the program is approvable",
        procedure=(
            "Place each voice line on the timeline and declare the design for any pause you "
            "intend. An undeclared pause is reported as a defect: the module does not invent a "
            "reason for silence."
        ),
    ),
    _p(
        artifact="audio/sync_expectations.json",
        stage="BUILD THE AUDIO",
        producer_type="CODEX",
        producer_id="sync-expectation-author",
        required_inputs=("audio/placement.json",),
        output_contract="sync_expectations.v1 (expectations[], sync_tolerance?)",
        validated_by="audio_program.check_sync",
        evidence=("every expectation names the evidence window it must land on",),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="a job-specific tolerance is supplied, or SYNC is accepted as REVIEW_REQUIRED",
        procedure=(
            "State which selling phrases must land on which evidence, and supply a tolerance "
            "derived from this piece. There is no universal tolerance: omit it and the program "
            "returns REVIEW_REQUIRED rather than borrowing another job's number."
        ),
    ),
    _p(
        artifact="picture/picture_request.json",
        stage="FINISH THE PICTURE",
        producer_type="ADAPTER",
        producer_id="picture-execution-adapter",
        required_inputs=("edit/editing_plan.json",),
        output_contract=(
            "picture_request.v1 (source, units[unit_id,t_in_seconds|source_frame_index,frames, "
            "geometry?], width, height, fps); geometry is optional per unit and is "
            "{mode: FIT} or {mode: CROP, crop_rect:{x,y,width,height}, confidence?, "
            "evidence_ref?}; an absent geometry means FIT"
        ),
        validated_by="execution_adapters.execute_picture",
        evidence=(
            "every unit resolved from a measured timestamp and executed through the timebase adapter",
            "a real video file with measured frame count, geometry and sha256",
            "per unit: requested and applied geometry mode, requested and applied crop "
            "rectangle, source and output geometry, and the frame count",
        ),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="the picture adapter produced a real video artifact whose measurements were taken from the file",
        procedure=(
            "python3 -m src.ai_autocut.execution_adapters --job-root <PATH> --boundary picture. "
            "The adapter reads this job's own request file and writes picture/picture_master.mp4; "
            "it is job-scoped and ships no default geometry or art direction."
        ),
    ),
    _p(
        artifact="typography/typography_request.json",
        stage="PLAN THE WORDS",
        producer_type="ADAPTER",
        producer_id="typography-executor",
        required_inputs=("copy/narration_coverage.json",),
        output_contract=(
            "typography_request.v1 (master, out, events[lines,start_frame,end_frame_exclusive], "
            "layout, font_stack, width, height, fps, frame_count)"
        ),
        validated_by="execution_adapters.execute_typography",
        evidence=(
            "this job's own layout and font stack, with no defaults",
            "a real rendered video file with measured frame count and sha256",
        ),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="the typography executor produced a real rendered artifact",
        procedure=(
            "python3 -m src.ai_autocut.execution_adapters --job-root <PATH> --boundary typography. "
            "layout and font_stack are required fields: there is no default layout or font, because "
            "a default would be one job's art direction applied to another."
        ),
    ),
    _p(
        artifact="audio/audio_request.json",
        stage="BUILD THE AUDIO",
        producer_type="ADAPTER",
        producer_id="audio-render-adapter",
        required_inputs=("copy/narration_coverage.json",),
        output_contract=(
            "audio_request.v1 (assets[path,gain_db,start_seconds], out, duration_seconds, "
            "target_lufs, true_peak_ceiling_dbtp)"
        ),
        validated_by="execution_adapters.execute_audio",
        evidence=(
            "a real mixed audio file with measured integrated loudness, true peak and sample peak",
            "an explicit no-clipping result",
        ),
        intervention_kind="VO_GENERATIONS",
        resume_condition="the audio adapter produced a real mix whose loudness and peak were measured from the file",
        procedure=(
            "python3 -m src.ai_autocut.execution_adapters --job-root <PATH> --boundary audio. "
            "Assets are this job's own local files; this adapter makes no provider call."
        ),
    ),
    _p(
        artifact="assemble/assemble_request.json",
        stage="ASSEMBLE & MASTER",
        producer_type="ADAPTER",
        producer_id="packaging-adapter",
        required_inputs=("typography/typography_execution.json", "audio/audio_execution.json"),
        output_contract="assemble_request.v1 (picture, audio, out, method: REMUX|RE_ENCODE)",
        validated_by="execution_adapters.assemble_master",
        evidence=(
            "a real delivery master at final/master.mp4",
            "measured assembly evidence written to assemble/assembly_evidence.json",
        ),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="the packaging adapter produced a real master and its measured evidence",
        procedure=(
            "python3 -m src.ai_autocut.execution_adapters --job-root <PATH> --boundary assemble. "
            "Prefer REMUX when the inputs already meet the delivery specification."
        ),
    ),
    _p(
        artifact="assemble/assembly_evidence.json",
        stage="ASSEMBLE & MASTER",
        producer_type="ADAPTER",
        producer_id="packaging-adapter",
        required_inputs=("picture/picture_finishing.json", "audio/audio_program.json"),
        output_contract="assembly_evidence.v1 (master_path, sha256, frames, method, qa[])",
        validated_by="execution_contracts.verify_against_contract",
        evidence=(
            "final master path and sha256",
            "frame count and method (remux or re-encode)",
            "black-frame and duplicate-frame QA",
            "audio loudness and true peak",
        ),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="assembly evidence exists and satisfies the assemble_master contract",
        procedure=(
            "Assemble the accepted picture and audio into a delivery master and record the "
            "measured QA. No packaging engine ships in this repository; a job supplies its own "
            "adapter. The stage does not pass without this evidence."
        ),
    ),
    _p(
        artifact="review/review.json",
        stage="REVIEW & REPAIR",
        producer_type="CODEX",
        producer_id="reviewer",
        required_inputs=("assemble/assembly_evidence.json",),
        output_contract="review.v0 (reviewer_id, executor_id, findings[13 dimensions])",
        validated_by="review.parse_review",
        evidence=(
            "every dimension judged exactly once",
            "reviewer_id differs from executor_id",
            "every finding carries its measurement",
        ),
        intervention_kind="CREATIVE_REVIEW_REJECTIONS",
        resume_condition="the review parses and its derived verdict is PRODUCTION_READY",
        procedure=(
            "Judge all thirteen dimensions exactly once. An incomplete review is a contract "
            "rejection, not a partial release. The verdict is derived from the findings and "
            "cannot be asserted."
        ),
    ),
    _p(
        artifact="release/human_release.json",
        stage="REVIEW & REPAIR",
        producer_type="HUMAN",
        producer_id="human-release-authority",
        required_inputs=("review/verdict.json",),
        output_contract="human_release.v1 (decision, authority, review_verdict, statement)",
        validated_by="fast_path.parse_human_release",
        evidence=(
            "a named human authority",
            "the review verdict it is answering",
            "an explicit statement",
        ),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="a human release decision exists and approves the reviewed verdict",
        procedure=(
            "A human records the final release decision after reading the review. This is a "
            "separate act from the review: PRODUCTION_READY from a reviewer is not a release "
            "and never auto-releases."
        ),
    ),
)

PRODUCER_BY_ARTIFACT: Mapping[str, Producer] = {p.artifact: p for p in PRODUCERS}

#: Artifacts the fast path requires as *inputs* to its stages. Every one of these must
#: have a producer, and that is asserted by test.
REQUIRED_INPUT_ARTIFACTS = tuple(
    p.artifact for p in PRODUCERS if p.producer_type != "AUTO"
)

#: Artifacts the fast path writes itself. Listed so the registry is complete rather
#: than only covering the gated inputs.
AUTO_ARTIFACTS = (
    "shots/shot_understanding.json",
    "edit/editing_plan.json",
    "picture/timing_profile.json",
    "picture/picture_finishing.json",
    "copy/narration_coverage.json",
    "audio/audio_program.json",
    "review/verdict.json",
    "fast_path_state.json",
    "intervention_ledger.jsonl",
)


def producer_for(artifact: str) -> Producer:
    """The single producer for an artifact. Unknown artifacts are a hard error."""

    normalized = str(artifact).lstrip("./")
    if normalized in PRODUCER_BY_ARTIFACT:
        return PRODUCER_BY_ARTIFACT[normalized]
    if normalized in AUTO_ARTIFACTS:
        return Producer(
            artifact=normalized,
            stage="*",
            producer_type="AUTO",
            producer_id="fast_path",
            required_inputs=(),
            output_contract="fast_path stage output",
            validated_by="",
            evidence=(),
            intervention_kind="SUPERVISOR_DECISIONS",
            resume_condition="written by the stage that owns it",
            procedure="The fast path writes this artifact as part of the owning stage.",
        )
    raise ProducerRegistryError(
        f"artifact {artifact!r} has NO PRODUCER. Every required artifact must be "
        "registered explicitly; an unknown artifact may not be produced implicitly."
    )


def gate_for(artifact: str, job_root: Path | str, *, missing_inputs: tuple[str, ...] = ()) -> dict[str, object]:
    """Build the explicit gate a caller must satisfy before a stage may run.

    This is what the fast path returns instead of proceeding silently: exactly which
    artifact is missing, who is responsible for it, what it must contain, what evidence
    it must leave, which ledger kind it records, and what has to become true to resume.
    """

    producer = producer_for(artifact)
    gate = producer.as_dict()
    gate["gate"] = "PRODUCER_REQUIRED"
    gate["missing_artifact"] = producer.artifact
    gate["missing_inputs"] = list(missing_inputs)
    gate["job_root"] = str(Path(job_root))
    gate["output_path"] = str(Path(job_root) / producer.artifact)
    gate["action_required"] = (
        f"{producer.producer_type} producer {producer.producer_id!r} must write "
        f"{producer.artifact} before this stage can run"
    )
    return gate


def registry_document() -> dict[str, object]:
    return {
        "schema_version": "artifact_producer_registry.v1",
        "producer_types": list(PRODUCER_TYPES),
        "rule": (
            "every required artifact has exactly one explicit producer; no required "
            "artifact may have NO PRODUCER or UNKNOWN PRODUCER"
        ),
        "gated_artifacts": list(REQUIRED_INPUT_ARTIFACTS),
        "auto_artifacts": list(AUTO_ARTIFACTS),
        "producers": [producer.as_dict() for producer in PRODUCERS],
    }


__all__ = [
    "AUTO_ARTIFACTS",
    "PRODUCERS",
    "PRODUCER_BY_ARTIFACT",
    "PRODUCER_TYPES",
    "Producer",
    "ProducerRegistryError",
    "REQUIRED_INPUT_ARTIFACTS",
    "gate_for",
    "producer_for",
    "registry_document",
]
