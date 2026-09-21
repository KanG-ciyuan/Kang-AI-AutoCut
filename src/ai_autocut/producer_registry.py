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


# ---------------------------------------------------------------------------
# Mode-scoped artifact ownership
# ---------------------------------------------------------------------------
#
# Two modes exist, and neither may quietly become the other:
#
# ``LEGACY``
#     The eight-stage production fast path above. It owns ``PRODUCERS`` and
#     ``AUTO_ARTIFACTS`` and it has never heard of Candidate Evidence.
# ``VNEXT_SHADOW``
#     Editing Intelligence vNext in shadow. It extracts Candidates from measured
#     material, requests structured multimodal analysis through the authoring
#     seam, and produces ``candidate_evidence.v1`` for validation and review.
#
# The two registries are deliberately separate values rather than one registry
# with a mode column. Separating them is what makes the isolation checkable:
# :func:`producer_for` — the resolver every legacy caller uses — still raises for
# a vNext artifact, so a legacy stage cannot start depending on one by accident.
# A run in ``LEGACY`` mode does not produce, require, read, or validate a single
# vNext artifact.

MODE_LEGACY = "LEGACY"
MODE_VNEXT_SHADOW = "VNEXT_SHADOW"
MODES = (MODE_LEGACY, MODE_VNEXT_SHADOW)

#: The stages the shadow mode runs, in order.
VNEXT_SHADOW_STAGES = ("PROPOSE CANDIDATES", "ANALYZE CANDIDATES")

#: The window proposal an analyzer adapter writes. Declared here so identity,
#: extraction, and analysis all read one name.
CANDIDATE_WINDOW_PROPOSAL_ARTIFACT = "analysis/candidate_window_proposal.json"
#: The deterministic request the pipeline writes for the analyzer.
CANDIDATE_ANALYSIS_REQUEST_ARTIFACT = "analysis/candidate_analysis_request.json"
#: The structured multimodal response an analyzer adapter writes.
CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT = "analysis/candidate_analysis_response.json"
#: What extraction accepted, rejected, and pooled.
CANDIDATE_EXTRACTION_ARTIFACT = "analysis/candidate_extraction.json"
#: The frames an analyzer was actually shown, bound to exact source frame numbers.
#: Frame images live beside it under ``analysis/frames/``.
CANDIDATE_FRAME_EVIDENCE_ARTIFACT = "analysis/candidate_frame_evidence.json"
#: The immutable Candidate Pool for this job.
CANDIDATE_POOL_ARTIFACT = "analysis/candidate_pool.json"
#: The Phase 1 companion contract, written by the analysis stage.
CANDIDATE_EVIDENCE_ARTIFACT = "analysis/candidate_evidence.json"

VNEXT_SHADOW_PRODUCERS: tuple[Producer, ...] = (
    _p(
        artifact=CANDIDATE_WINDOW_PROPOSAL_ARTIFACT,
        stage="PROPOSE CANDIDATES",
        producer_type="ADAPTER",
        producer_id="candidate-window-analyzer",
        required_inputs=("source_inventory.json",),
        output_contract=(
            "candidate_window_proposal.v1 (proposals[proposal_id, rule, material_id, "
            "stream_index, start_frame, end_frame_exclusive, segment_indices, "
            "parent_segment_indices, action_evidence, rationale]); rule is one of "
            "SINGLE_SEGMENT, ADJACENT_MERGE, ACTION_SAFE_WINDOW, SHORTER_ACTION_WINDOW"
        ),
        validated_by="candidate_extraction.validate_proposal",
        evidence=(
            "source frame ranges only; no assumed frame rate",
            "action evidence for every merge, safe window, and shorter window",
        ),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition=(
            "every proposal is accepted or rejected by the boundary validator, and the "
            "rejections are recorded rather than dropped"
        ),
        procedure=(
            "python3 -m src.ai_autocut.candidate_analysis --job-root <PATH> --stage propose "
            "--measurements <measured.json> --segmentations <segments.json> "
            "[--proposals <proposals.json>]. A job supplies its own analyzer adapter; this "
            "repository ships no multimodal client. The analyzer proposes windows, the "
            "deterministic boundary validator disposes of them, and a rejected proposal is "
            "an observable outcome rather than a silently widened window."
        ),
    ),
    _p(
        artifact=CANDIDATE_EXTRACTION_ARTIFACT,
        stage="PROPOSE CANDIDATES",
        producer_type="AUTO",
        producer_id="candidate_extraction.extract_candidates",
        required_inputs=(CANDIDATE_WINDOW_PROPOSAL_ARTIFACT,),
        output_contract="candidate_extraction.v1 (proposals, outcomes, counts, pool_id)",
        validated_by="candidate_extraction.CandidateExtraction",
        evidence=(
            "per-proposal decision with a rejection code or a Candidate Identity",
            "measured window (t_in, real duration, frame count) per accepted Candidate",
        ),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="the extraction document exists and every proposal has a decision",
        procedure=(
            "Written by the PROPOSE CANDIDATES stage from the validated proposals. It "
            "records the accepted Candidates, the rejected proposals with their codes, and "
            "the measured window of each Candidate."
        ),
    ),
    _p(
        artifact=CANDIDATE_POOL_ARTIFACT,
        stage="PROPOSE CANDIDATES",
        producer_type="AUTO",
        producer_id="candidate_pool.CandidatePool.create",
        required_inputs=(CANDIDATE_EXTRACTION_ARTIFACT,),
        output_contract="candidate_pool.v1 (schema_version, pool_id, entries)",
        validated_by="candidate_pool.validate_candidate_pool",
        evidence=("membership only: pool_id plus sorted candidate_id entries",),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="every accepted Candidate is a member and no other Candidate is",
        procedure=(
            "Written by the PROPOSE CANDIDATES stage. The Pool answers membership and "
            "nothing else: adding a label, score, claim, or confidence to it would change "
            "what candidate_pool.v1 means."
        ),
    ),
    _p(
        artifact=CANDIDATE_FRAME_EVIDENCE_ARTIFACT,
        stage="ANALYZE CANDIDATES",
        producer_type="ADAPTER",
        producer_id="live-validation-harness",
        required_inputs=(CANDIDATE_EXTRACTION_ARTIFACT,),
        output_contract=(
            "candidate_frame_evidence.v1 (candidates[].frames[] with source_frame, "
            "t_seconds, image, sha256, width, height)"
        ),
        validated_by="candidate_frame_evidence.parse_frame_evidence",
        evidence=(
            "one image per sampled frame, named by its exact decoded source frame",
            "each frame's measured timestamp and SHA-256",
        ),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition=(
            "every accepted Candidate has sampled frames inside its own window, and each "
            "image hashes to what the manifest recorded"
        ),
        procedure=(
            "python3 scripts/phase25_live_validation.py prepare --workspace <DIR>. This is "
            "an OPT-IN validation artifact, not a stage of the shadow analysis path: the "
            "ANALYZE CANDIDATES stage neither requires nor parses it, and Candidate Evidence "
            "can be produced without one. It exists so a human or an auditor can see exactly "
            "which frames an analyzer was shown, with exact source frame numbers, measured "
            "timestamps and hashes. The Candidate window is decoded and its frames are sliced "
            "out by decoded index, so the frame numbers the analyzer cites are established "
            "coordinates rather than guesses. No raw-source frame-index filter is used: it is "
            "legitimate for analysis, and it is never a timing coordinate."
        ),
    ),
    _p(
        artifact=CANDIDATE_ANALYSIS_REQUEST_ARTIFACT,
        stage="ANALYZE CANDIDATES",
        producer_type="AUTO",
        producer_id="candidate_analysis.build_analysis_request",
        required_inputs=(CANDIDATE_POOL_ARTIFACT,),
        output_contract=(
            "candidate_analysis_request.v1 (run_id, candidate_pool_id, claim_envelope, "
            "candidates with measured windows, prompt_contract_version)"
        ),
        validated_by="candidate_analysis.parse_analysis_request",
        evidence=(
            "the Claim Envelope the analyzer may answer against, and nothing wider",
            "per Candidate: exact source range plus its measured timestamps",
        ),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="the request exists and its claim envelope lists every permitted fact",
        procedure=(
            "Written by the ANALYZE CANDIDATES stage before the analyzer is asked anything. "
            "The request states the one question the analyzer may answer and the exact "
            "Candidate windows it is answering about."
        ),
    ),
    _p(
        artifact=CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT,
        stage="ANALYZE CANDIDATES",
        producer_type="ADAPTER",
        producer_id="candidate-analysis-adapter",
        required_inputs=(CANDIDATE_ANALYSIS_REQUEST_ARTIFACT,),
        output_contract=(
            "candidate_analysis_response.v1 (request reference, run_id, candidate_pool_id, "
            "provider, model, prompt_contract_version, entries[]) where each entry is one "
            "Candidate Evidence entry payload"
        ),
        validated_by="candidate_analysis.parse_analysis_response",
        evidence=(
            "one entry per requested Candidate, or an explicit UNKNOWN / ANALYSIS_FAILED",
            "claim support only for Product Facts the Claim Envelope permits",
        ),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition=(
            "every Pool member is accounted for, and the pipeline records a failure instead "
            "of losing a Candidate"
        ),
        procedure=(
            "python3 -m src.ai_autocut.candidate_analysis --job-root <PATH> --stage analyze "
            "--agent-command '<COMMAND>'. The command receives the authoring request on "
            "stdin and writes the response artifact. A missing or malformed response is "
            "recorded as ANALYSIS_FAILED for every Candidate rather than as a silent gap. "
            "This stage does not require sampled frames: frame evidence is produced by the "
            "opt-in live-validation harness, and the analysis stage neither reads nor "
            "enforces it."
        ),
    ),
    _p(
        artifact=CANDIDATE_EVIDENCE_ARTIFACT,
        stage="ANALYZE CANDIDATES",
        producer_type="AUTO",
        producer_id="candidate_analysis.build_candidate_evidence",
        required_inputs=(CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT, CANDIDATE_POOL_ARTIFACT),
        output_contract="candidate_evidence.v1 (Phase 1 companion contract)",
        validated_by="candidate_evidence.validate_candidate_evidence",
        evidence=(
            "exactly one entry per Pool member, with a status and a rationale",
            "DIRECT claim support bound to frames inside the Candidate's exact range",
        ),
        intervention_kind="SUPERVISOR_DECISIONS",
        resume_condition="validate_candidate_evidence accepts the document for this Pool",
        procedure=(
            "Written by the ANALYZE CANDIDATES stage from the validated response. It is the "
            "end of this stage: Candidate Evidence is produced and validated, and nothing "
            "downstream consumes it yet."
        ),
    ),
)

VNEXT_SHADOW_PRODUCER_BY_ARTIFACT: Mapping[str, Producer] = {
    producer.artifact: producer for producer in VNEXT_SHADOW_PRODUCERS
}

#: vNext artifacts the shadow stage writes itself. Frame evidence is deliberately not
#: here: it is produced by the opt-in live-validation harness, so no stage writes it
#: and no consumer may assume it exists.
VNEXT_SHADOW_AUTO_ARTIFACTS = tuple(
    producer.artifact
    for producer in VNEXT_SHADOW_PRODUCERS
    if producer.producer_type == "AUTO"
)

#: Every artifact the shadow mode owns.
VNEXT_SHADOW_ARTIFACTS = tuple(
    producer.artifact for producer in VNEXT_SHADOW_PRODUCERS
)


class ModeScopeError(ProducerRegistryError):
    """Raised when an artifact is asked for in a mode that does not own it."""


def mode_of(artifact: str) -> str | None:
    """Which mode owns an artifact, or ``None`` when no mode does."""

    normalized = str(artifact).lstrip("./")
    if (
        normalized in PRODUCER_BY_ARTIFACT
        or normalized in AUTO_ARTIFACTS
    ):
        return MODE_LEGACY
    if normalized in VNEXT_SHADOW_PRODUCER_BY_ARTIFACT:
        return MODE_VNEXT_SHADOW
    return None


def vnext_producer_for(artifact: str) -> Producer:
    """The single shadow-mode producer for a vNext artifact.

    Mode-scoped on purpose. The legacy resolver stays ignorant of these artifacts
    so no legacy stage can acquire a dependency on one by accident, and this
    resolver refuses a legacy artifact so the shadow mode cannot adopt one and
    start writing a frozen production contract.
    """

    normalized = str(artifact).lstrip("./")
    if normalized in VNEXT_SHADOW_PRODUCER_BY_ARTIFACT:
        return VNEXT_SHADOW_PRODUCER_BY_ARTIFACT[normalized]
    owner = mode_of(normalized)
    if owner == MODE_LEGACY:
        raise ModeScopeError(
            f"artifact {artifact!r} belongs to {MODE_LEGACY}, not {MODE_VNEXT_SHADOW}; "
            "the shadow mode does not write production artifacts"
        )
    raise ModeScopeError(
        f"artifact {artifact!r} has NO PRODUCER in {MODE_VNEXT_SHADOW}. Every required "
        "artifact must be registered explicitly."
    )


def vnext_gate_for(
    artifact: str, job_root: Path | str, *, missing_inputs: tuple[str, ...] = ()
) -> dict[str, object]:
    """Build the explicit shadow-mode gate for one vNext artifact."""

    producer = vnext_producer_for(artifact)
    gate = producer.as_dict()
    gate["gate"] = "PRODUCER_REQUIRED"
    gate["mode"] = MODE_VNEXT_SHADOW
    gate["missing_artifact"] = producer.artifact
    gate["missing_inputs"] = list(missing_inputs)
    gate["job_root"] = str(Path(job_root))
    gate["output_path"] = str(Path(job_root) / producer.artifact)
    gate["action_required"] = (
        f"{producer.producer_type} producer {producer.producer_id!r} must write "
        f"{producer.artifact} before this shadow stage can run"
    )
    return gate


def vnext_registry_document() -> dict[str, object]:
    """The shadow-mode registry, kept separate from the legacy document."""

    return {
        "schema_version": "artifact_producer_registry.v1",
        "mode": MODE_VNEXT_SHADOW,
        "stages": list(VNEXT_SHADOW_STAGES),
        "rule": (
            "every required vNext artifact has exactly one explicit producer in "
            f"{MODE_VNEXT_SHADOW}; a legacy artifact may not be produced by this mode"
        ),
        "artifacts": list(VNEXT_SHADOW_ARTIFACTS),
        "auto_artifacts": list(VNEXT_SHADOW_AUTO_ARTIFACTS),
        "producers": [producer.as_dict() for producer in VNEXT_SHADOW_PRODUCERS],
    }


__all__ = [
    "AUTO_ARTIFACTS",
    "CANDIDATE_ANALYSIS_REQUEST_ARTIFACT",
    "CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT",
    "CANDIDATE_EVIDENCE_ARTIFACT",
    "CANDIDATE_EXTRACTION_ARTIFACT",
    "CANDIDATE_FRAME_EVIDENCE_ARTIFACT",
    "CANDIDATE_POOL_ARTIFACT",
    "CANDIDATE_WINDOW_PROPOSAL_ARTIFACT",
    "MODE_LEGACY",
    "MODE_VNEXT_SHADOW",
    "MODES",
    "ModeScopeError",
    "PRODUCERS",
    "PRODUCER_BY_ARTIFACT",
    "PRODUCER_TYPES",
    "Producer",
    "ProducerRegistryError",
    "REQUIRED_INPUT_ARTIFACTS",
    "VNEXT_SHADOW_ARTIFACTS",
    "VNEXT_SHADOW_AUTO_ARTIFACTS",
    "VNEXT_SHADOW_PRODUCER_BY_ARTIFACT",
    "VNEXT_SHADOW_PRODUCERS",
    "VNEXT_SHADOW_STAGES",
    "gate_for",
    "mode_of",
    "producer_for",
    "registry_document",
    "vnext_gate_for",
    "vnext_producer_for",
    "vnext_registry_document",
]
