"""The eight-stage Production Fast Path — the authoritative production control path.

What this is
------------
One control path that knows, for a job: **which semantic stage comes next, which
capability must run in it, which artifact must exist and who produces it, and whether
execution may continue.** It is a *control* path, not an intelligence: it makes no
creative decision, repairs nothing on its own, and never substitutes for the Supervisor.

What this is not
----------------
It is not an autonomous pipeline, and it does not claim to be. Four boundaries — picture
execution, typography execution, audio rendering, and assembly — have no in-repository
executor. Each declares an explicit :mod:`execution_contracts` contract, and the stage
gates on it rather than passing quietly.

Every artifact has a producer
-----------------------------
Independent inspection found that the earlier path declared its inputs but never said
who produced them, which made it a validation harness around preconstructed artifacts
rather than a runner. :mod:`producer_registry` now assigns every required artifact
exactly one explicit producer — ``AUTO``, ``CODEX``, ``HUMAN`` or ``ADAPTER`` — and this
module returns an explicit **producer gate** naming the producer that must act, instead
of proceeding or failing vaguely.

A ``CODEX`` or ``HUMAN`` producer is legitimate. The goal is reproducibility, not
autonomy. Hidden manual reconstruction is what is not allowed.

Stage outcomes
--------------
``PASS``                        the stage completed and its artifacts exist
``BLOCKED``                     a named producer must act before this stage can run
``REVIEW_REQUIRED``             a wired capability refused; a human decides
``SUPERVISOR_DECISION_REQUIRED`` a judgement or approval belongs to the Supervisor
``REJECT``                      a CRITICAL finding; returns to planning, not to repair
``FAIL``                        the stage ran and produced an unacceptable result

Every non-``PASS`` outcome stops the run. Nothing here resolves one, retries it, or
works around it. Each maps to a documented non-zero exit code so a halted run cannot be
mistaken for a success.

Resume
------
``run()`` resumes from the first semantic stage that has not passed. A completed stage
is not re-executed unless it is explicitly invalidated. ``--stage`` goes through the
same checkpoint path, and every outcome is persisted, so a run interrupted by a producer
gate continues from the correct stage once that producer has acted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import (
    audio_plan,
    execution_adapters,
    audio_program,
    editing_intelligence,
    execution_contracts,
    intervention_ledger,
    job_foundation,
    media_probe,
    narration_coverage,
    picture_decision,
    picture_measurement,
    producer_registry,
    product_protection,
    review,
    shot_understanding,
    timebase_adapter,
    typography_adapter,
)
from .paths import assert_ascii_safe

STATE_FILENAME = "fast_path_state.json"
ARTIFACT_REFERENCES_FILENAME = "artifact_references.json"
HUMAN_RELEASE_ARTIFACT = "release/human_release.json"
ASSEMBLY_EVIDENCE_ARTIFACT = "assemble/assembly_evidence.json"
ASSEMBLE_REQUEST_ARTIFACT = "assemble/assemble_request.json"

SEMANTIC_STAGES = (
    "PREPARE",
    "UNDERSTAND SHOTS",
    "PLAN THE EDIT",
    "FINISH THE PICTURE",
    "PLAN THE WORDS",
    "BUILD THE AUDIO",
    "ASSEMBLE & MASTER",
    "REVIEW & REPAIR",
)

OUTCOMES = (
    "PASS",
    "BLOCKED",
    "REVIEW_REQUIRED",
    "SUPERVISOR_DECISION_REQUIRED",
    "REJECT",
    "FAIL",
)

#: Documented process exit codes. A halted run must never look like a success to a
#: caller that only inspects the exit status.
EXIT_CODES = {
    "PASS": 0,
    "BLOCKED": 3,
    "REVIEW_REQUIRED": 4,
    "SUPERVISOR_DECISION_REQUIRED": 5,
    "FAIL": 6,
    "REJECT": 7,
}

#: Fast-path outcome -> the low-level ``job_foundation`` state it is recorded as.
OUTCOME_TO_LOW_LEVEL_STATE = {
    "PASS": "PASS",
    "BLOCKED": "FAILED",
    "REVIEW_REQUIRED": "NEEDS_REVIEW",
    "SUPERVISOR_DECISION_REQUIRED": "NEEDS_REVIEW",
    "REJECT": "FAILED",
    "FAIL": "FAILED",
}

#: Outcomes that halt the run. The orchestrator never resolves them itself.
HALTING_OUTCOMES = tuple(outcome for outcome in OUTCOMES if outcome != "PASS")

#: Human release decisions. A release is a separate act from a review.
RELEASE_DECISIONS = ("APPROVED", "REJECTED")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class FastPathError(ValueError):
    """Raised when the fast path cannot proceed safely."""


@dataclass(frozen=True)
class Stage:
    """One semantic stage and the capability it is required to run."""

    name: str
    low_level: tuple[str, ...]
    capability: str | None
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    manual: bool = False
    note: str = ""
    #: Cross-cutting invariants applied to work inside this stage. ``timebase_adapter``
    #: belongs here rather than as one stage's capability, because it governs *every*
    #: source-range conversion rather than being one step of one stage.
    invariants: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.name not in SEMANTIC_STAGES:
            raise FastPathError(f"unknown semantic stage {self.name!r}")
        if self.manual and self.capability is not None:
            raise FastPathError(
                f"stage {self.name!r} is manual and cannot also declare a capability"
            )
        for invariant in self.invariants:
            if "." not in invariant:
                raise FastPathError(f"invariant {invariant!r} must be a dotted path")


#: The declarative control table. This is the single place that decides which
#: capability a stage must run and which artifacts it consumes, which is what stops a
#: stage being quietly skipped.
STAGES: tuple[Stage, ...] = (
    Stage(
        name="PREPARE",
        low_level=("PREPARE",),
        capability="job_foundation.verify_source_immutability",
        inputs=("source_inventory.json",),
        outputs=("source_inventory.json",),
        note="source inventory is immutable; an uninitialized job gates here",
    ),
    Stage(
        name="UNDERSTAND SHOTS",
        low_level=("ANALYZE", "CANDIDATE_SHOT_POOL", "MATERIAL_COVERAGE"),
        capability="shot_understanding.analyse_placements",
        inputs=("shots/placements.json",),
        outputs=("shots/shot_understanding.json",),
        note=(
            "every placement is verified against the measured PTS table before use, so a "
            "placement coordinate derived from an assumed frame rate is refused"
        ),
        invariants=("timebase_adapter.TimebaseAdapter.assert_placement_timing",),
    ),
    Stage(
        name="PLAN THE EDIT",
        low_level=("EDITING_PLAN", "EXECUTABLE_TIMELINE"),
        capability="editing_intelligence.validate_timeline_range",
        inputs=("edit/timeline_ranges.json",),
        outputs=("edit/editing_plan.json",),
    ),
    Stage(
        name="FINISH THE PICTURE",
        low_level=("DAVINCI_EXECUTION", "PREVIEW"),
        capability="picture_decision.decide_shot",
        inputs=(
            "picture/source_ranges.json",
            "picture/measurements.json",
            "picture/picture_request.json",
        ),
        outputs=("picture/picture_finishing.json",),
        note=(
            "source-range execution is REQUIRED, not optional: a production path that "
            "executes source ranges must go through the timebase adapter, so the ranges "
            "are a declared input a stage cannot skip. Picture execution itself is an "
            "adapter boundary with a published contract"
        ),
        invariants=("timebase_adapter.TimebaseAdapter.execute",),
    ),
    Stage(
        name="PLAN THE WORDS",
        low_level=("PLAN_THE_WORDS",),
        capability="narration_coverage.assess_narration_coverage",
        inputs=("copy/commercial_units.json", "typography/typography_request.json"),
        outputs=("copy/narration_coverage.json", "typography/typography_execution.json"),
        note="runs BEFORE any paid voice generation",
    ),
    Stage(
        name="BUILD THE AUDIO",
        low_level=("BUILD_THE_AUDIO",),
        capability="audio_program.assess_program",
        inputs=(
            "audio/placement.json",
            "audio/sync_expectations.json",
            "audio/audio_request.json",
        ),
        outputs=("audio/audio_program.json", "audio/audio_execution.json"),
        note="runs after VO placement and before the final mix is accepted",
    ),
    Stage(
        name="ASSEMBLE & MASTER",
        low_level=("FINAL",),
        capability="execution_contracts.verify_assembly_evidence",
        inputs=(ASSEMBLE_REQUEST_ARTIFACT, ASSEMBLY_EVIDENCE_ARTIFACT),
        outputs=(ASSEMBLY_EVIDENCE_ARTIFACT,),
        note=(
            "gates on the assemble_master execution contract. No packaging engine ships "
            "in this repository, so a job-specific adapter must supply measured assembly "
            "evidence; the stage does not pass on a claim"
        ),
    ),
    Stage(
        name="REVIEW & REPAIR",
        low_level=("REVIEW", "DELIVERY"),
        capability="review.parse_review",
        inputs=("review/review.json",),
        outputs=("review/verdict.json",),
        note=(
            "an incomplete review fails closed; a CRITICAL finding returns REJECT; and a "
            "reviewer verdict is not a release — a distinct human release decision is "
            "consumed before this stage may pass"
        ),
    ),
)

STAGE_BY_NAME = {stage.name: stage for stage in STAGES}

#: The modules the fast path is required to reach.
REQUIRED_PRODUCTION_MODULES = (
    "narration_coverage",
    "audio_program",
    "review",
    "timebase_adapter",
)


@dataclass(frozen=True)
class StageResult:
    """What a stage did. ``capability`` is the evidence that wiring held."""

    stage: str
    outcome: str
    capability: str | None
    artifacts: tuple[str, ...] = ()
    reason: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
    #: Present when a named producer must act before this stage can run.
    gate: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.stage not in SEMANTIC_STAGES:
            raise FastPathError(f"unknown semantic stage {self.stage!r}")
        if self.outcome not in OUTCOMES:
            raise FastPathError(
                f"unknown outcome {self.outcome!r}; expected one of: "
                + ", ".join(OUTCOMES)
            )
        if self.outcome == "PASS" and not self.capability:
            raise FastPathError(
                f"stage {self.stage!r} cannot PASS without naming the capability it "
                "ran; a silent pass is the failure this control path exists to prevent"
            )

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.outcome]

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stage": self.stage,
            "outcome": self.outcome,
            "capability": self.capability,
            "artifacts": list(self.artifacts),
            "reason": self.reason,
            "evidence": dict(self.evidence),
            "exit_code": self.exit_code,
        }
        if self.gate is not None:
            payload["producer_gate"] = dict(self.gate)
        return payload


@dataclass(frozen=True)
class RunReport:
    """The outcome of one fast-path run."""

    job_id: str
    results: tuple[StageResult, ...]
    stopped_at: str | None
    completed: bool
    resumed_from: str | None = None

    @property
    def outcome(self) -> str:
        if self.completed:
            return "PASS"
        return self.results[-1].outcome if self.results else "FAIL"

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.outcome]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "fast_path_run.v1",
            "job_id": self.job_id,
            "completed": self.completed,
            "outcome": self.outcome,
            "exit_code": self.exit_code,
            "stopped_at": self.stopped_at,
            "resumed_from": self.resumed_from,
            "stages": [result.as_dict() for result in self.results],
        }


def resolve_capability(dotted: str) -> Callable[..., Any]:
    """Resolve ``module.symbol`` to a callable, at call time.

    Resolving late means a renamed or deleted symbol fails loudly at dispatch instead
    of disappearing behind a stale import. Both the installed package path and the
    in-repository ``src.`` path are tried, because the test suite and the job scripts
    import this package differently.
    """

    if not isinstance(dotted, str) or "." not in dotted:
        raise FastPathError(f"capability {dotted!r} must be a dotted path")
    module_name, _, symbol = dotted.rpartition(".")
    if module_name.startswith("ai_autocut"):
        candidates = [module_name, f"src.{module_name}"]
    elif module_name.startswith("src."):
        candidates = [module_name]
    else:
        candidates = [f"ai_autocut.{module_name}", f"src.ai_autocut.{module_name}"]
    module = None
    errors: list[str] = []
    for candidate in candidates:
        try:
            module = importlib.import_module(candidate)
            break
        except ImportError as exc:
            errors.append(f"{candidate}: {exc}")
    if module is None:
        raise FastPathError(f"cannot import {dotted!r} ({'; '.join(errors)})")
    try:
        attribute = getattr(module, symbol)
    except AttributeError as exc:
        raise FastPathError(
            f"{module.__name__!r} has no symbol {symbol!r} (declared as {dotted!r})"
        ) from exc
    if not callable(attribute):
        raise FastPathError(f"{dotted!r} is not callable")
    return attribute


def parse_human_release(document: object) -> dict[str, Any]:
    """Validate a human release decision.

    Deliberately a separate artifact from the review. A reviewer verdict is a judgement
    about the work; a release is a decision to ship it. Merging them is how a machine
    verdict becomes a release nobody made.
    """

    if not isinstance(document, Mapping):
        raise FastPathError("a human release must be a JSON object")
    required = (
        "schema_version",
        "decision",
        "authority",
        "review_verdict",
        "master_sha256",
        "statement",
    )
    missing = [key for key in required if key not in document]
    if missing:
        raise FastPathError(
            "human release is missing required field(s): " + ", ".join(missing)
        )
    decision = document["decision"]
    if decision not in RELEASE_DECISIONS:
        raise FastPathError(
            f"release decision {decision!r} must be one of: "
            + ", ".join(RELEASE_DECISIONS)
        )
    for key in ("authority", "statement", "review_verdict"):
        value = document[key]
        if not isinstance(value, str) or not value.strip():
            raise FastPathError(f"human release field {key!r} must be a non-empty string")
    master_sha = document["master_sha256"]
    if not isinstance(master_sha, str) or len(master_sha) != 64:
        raise FastPathError(
            "a human release must name the verified master by its full 64-character "
            "sha256; a release that does not say which master it approves is not a "
            "release of anything in particular"
        )
    return {
        "decision": decision,
        "authority": document["authority"],
        "review_verdict": document["review_verdict"],
        "master_sha256": master_sha,
        "statement": document["statement"],
    }


class FastPath:
    """Drives the eight semantic stages for one job."""

    def __init__(
        self,
        job_root: Path | str,
        *,
        job_id: str | None = None,
        fps: int = 30,
        supervisor_authority: str = "Codex",
        timebase: Any | None = None,
    ) -> None:
        self.root = Path(job_root)
        self.job_id = job_id or self.root.name
        self.fps = fps
        self.supervisor_authority = supervisor_authority
        # Injectable so a wiring test can prove the stage goes through this boundary
        # without needing real media. The default is the real adapter.
        self.timebase = (
            timebase if timebase is not None else timebase_adapter.TimebaseAdapter(fps=fps)
        )
        self.ledger = intervention_ledger.InterventionLedger(
            self.root / intervention_ledger.LEDGER_FILENAME
        )

    # ---- paths -----------------------------------------------------------------

    def path(self, relative: str) -> Path:
        return self.root / relative

    def _read(self, relative: str) -> Any | None:
        target = self.path(relative)
        if not target.is_file():
            return None
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FastPathError(f"cannot read {relative}: {exc}") from exc

    def _write(self, relative: str, payload: Mapping[str, Any]) -> str:
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
        return relative

    def _missing_inputs(self, stage: Stage) -> tuple[str, ...]:
        return tuple(item for item in stage.inputs if not self.path(item).is_file())

    # ---- planning --------------------------------------------------------------

    @property
    def stages(self) -> tuple[Stage, ...]:
        return STAGES

    def plan(self) -> tuple[str, ...]:
        return SEMANTIC_STAGES

    def state(self) -> dict[str, Any]:
        existing = self._read(STATE_FILENAME)
        if isinstance(existing, dict) and "stages" in existing:
            return existing
        return {
            "schema_version": "fast_path_state.v2",
            "job_id": self.job_id,
            "supervisor_authority": self.supervisor_authority,
            "stages": {
                name: {"outcome": None, "capability": None, "valid": False}
                for name in SEMANTIC_STAGES
            },
            "history": [],
        }

    def next_stage(self) -> str | None:
        """The first stage that has not passed. ``None`` means the run is complete."""

        state = self.state()
        for name in SEMANTIC_STAGES:
            if state["stages"][name]["outcome"] != "PASS":
                return name
        return None

    def completed_stages(self) -> tuple[str, ...]:
        state = self.state()
        return tuple(
            name for name in SEMANTIC_STAGES if state["stages"][name]["outcome"] == "PASS"
        )

    def invalidate(self, stage: str, *, reason: str) -> tuple[str, ...]:
        """Re-open a stage **and everything downstream of it**.

        The semantic stages form a chain: every stage consumes what the one before it
        produced. Re-opening a stage therefore invalidates every later PASS state, not
        just its own. Keeping a downstream PASS after its input changed would let the run
        report a completion that no longer describes the artifacts on disk — the run
        would resume at the *end* and never re-derive the stages that depended on the
        change.

        This is not a third state model: it writes the same ``fast_path_state.json`` the
        run already uses, and the low-level record is reconciled from it.
        """

        if stage not in STAGE_BY_NAME:
            raise FastPathError(f"unknown stage {stage!r}")
        invalidated = SEMANTIC_STAGES[SEMANTIC_STAGES.index(stage):]
        state = self.state()
        for name in invalidated:
            if state["stages"][name]["outcome"] is None and name != stage:
                continue
            state["stages"][name] = {
                "outcome": None,
                "capability": None,
                "valid": False,
                "invalidated": reason,
                "invalidated_because": stage,
            }
            state["history"].append(
                {
                    "stage": name,
                    "outcome": "INVALIDATED",
                    "reason": reason,
                    "caused_by": stage,
                }
            )
        self._write(STATE_FILENAME, state)

        # A PASS recorded in the low-level state must not survive its cause either.
        foundation = job_foundation.ensure_state(self.root, self.job_id)
        pipeline = foundation.state()
        affected_low = {
            low for name in invalidated for low in STAGE_BY_NAME[name].low_level
        }
        for low in job_foundation.STAGE_ORDER:
            if low not in affected_low:
                continue
            if pipeline["stages"][low]["state"] == "PENDING":
                continue
            pipeline["stages"][low]["state"] = "PENDING"
            pipeline["stages"][low]["evidence"].append(
                {"kind": "invalidated_by_fast_path", "stage": stage, "reason": reason}
            )
        pipeline["history"].append(
            {
                "at": _utc_now(),
                "stage": stage,
                "from": "PASS",
                "to": "PENDING",
                "evidence": {"kind": "downstream_invalidation", "reason": reason},
            }
        )
        foundation.save_state(pipeline)
        return tuple(invalidated)

    def checkpoint(self, result: StageResult) -> None:
        state = self.state()
        stage = STAGE_BY_NAME[result.stage]
        previous = state["stages"].get(result.stage)
        state["stages"][result.stage] = {
            "outcome": result.outcome,
            "capability": result.capability,
            "valid": result.outcome == "PASS",
            "low_level": [
                {"stage": low, "state": OUTCOME_TO_LOW_LEVEL_STATE[result.outcome]}
                for low in stage.low_level
            ],
            "artifacts": list(result.artifacts),
            "reason": result.reason,
            "gate": dict(result.gate) if result.gate else None,
        }
        state["history"].append(result.as_dict())
        self._write(STATE_FILENAME, state)

        references = self._read(ARTIFACT_REFERENCES_FILENAME)
        if not isinstance(references, dict):
            references = {
                "schema_version": "artifact_references.v1",
                "job_id": self.job_id,
                "artifacts": {key: None for key in job_foundation.ARTIFACT_KEYS},
            }
        for artifact in result.artifacts:
            references["artifacts"][Path(artifact).stem] = artifact
        self._write(ARTIFACT_REFERENCES_FILENAME, references)

        self.reconcile_pipeline_state()
        self._record_gate(result, previous)

    def reconcile_pipeline_state(self) -> dict[str, Any]:
        """Mirror achieved low-level states into ``pipeline_state.json``.

        The eight semantic stages are the lifecycle; the thirteen low-level states are
        execution detail. They are not competing architectures, so this reconciles one
        into the other rather than keeping a second truth.

        The two vocabularies order ``REVIEW`` and ``FINAL`` differently: the low-level
        order is REVIEW then FINAL, while the semantic order assembles and then reviews.
        So this drains whatever the ordering currently permits after each stage, and
        ``FINAL`` lands once ``REVIEW`` has passed. That is a consequence of the mapping
        and is recorded rather than hidden.
        """

        state = self.state()
        achieved = {
            low
            for name in SEMANTIC_STAGES
            if state["stages"][name]["outcome"] == "PASS"
            for low in STAGE_BY_NAME[name].low_level
            if low in job_foundation.STAGE_ORDER
        }
        foundation = job_foundation.ensure_state(self.root, self.job_id)
        current = foundation.state()
        recorded: list[str] = []
        deferred: list[str] = []
        for index, low in enumerate(job_foundation.STAGE_ORDER):
            if low not in achieved:
                continue
            if current["stages"][low]["state"] == "PASS":
                continue
            # A low-level state may only be recorded once every state before it has
            # passed. The semantic order assembles before it reviews, while the
            # low-level order reviews before it finalizes, so FINAL is deferred until
            # REVIEW has passed. That is a property of the mapping, and it is reported
            # rather than forced.
            predecessors = job_foundation.STAGE_ORDER[:index]
            if any(
                current["stages"][prior]["state"] != "PASS" for prior in predecessors
            ):
                deferred.append(low)
                continue
            if current["stages"][low]["state"] == "PENDING":
                foundation.transition(
                    low, "RUNNING", evidence={"kind": "fast_path_reconciliation"}
                )
            foundation.transition(
                low, "PASS", evidence={"kind": "fast_path_reconciliation"}
            )
            current = foundation.state()
            recorded.append(low)
        return {
            "achieved_low_level_states": sorted(achieved),
            "newly_recorded": recorded,
            "deferred_until_predecessors_pass": deferred,
            "pipeline_state": str(foundation.state_path),
        }

    # ---- interventions ---------------------------------------------------------

    def record_intervention(
        self,
        *,
        stage: str,
        kind: str,
        actor: str,
        detail: str,
        trigger: str,
        paid_api_calls: int = 0,
        before_ref: str | None = None,
        after_ref: str | None = None,
    ) -> dict[str, Any]:
        """Record an intervention at the moment it happens.

        Nothing here reconstructs history. A count that was not recorded when it
        occurred does not exist in the ledger.
        """

        return self.ledger.record(
            intervention_ledger.Intervention(
                job_id=self.job_id,
                stage=stage,
                kind=kind,
                actor=actor,
                trigger=trigger,
                detail=detail,
                before_ref=before_ref,
                after_ref=after_ref,
                paid_api_calls=paid_api_calls,
            )
        )

    #: Producer type -> ledger actor. A CODEX producer is not a human, and an adapter
    #: is automated execution; recording everything as HUMAN is what this mapping fixes.
    PRODUCER_ACTOR = {
        "CODEX": "CODEX_SUPERVISOR",
        "HUMAN": "HUMAN",
        "ADAPTER": "AUTOMATED_REPAIR",
        "AUTO": "AUTOMATED_REPAIR",
    }

    #: Outcomes that stay open until something resolves them, and so are recorded once.
    OPEN_OUTCOMES = ("BLOCKED", "REVIEW_REQUIRED", "SUPERVISOR_DECISION_REQUIRED")

    def _already_open(self, stage: str, marker: str) -> bool:
        """True when this still-open gate was already recorded for this stage.

        A run that halts repeatedly on the same unresolved gate is one intervention, not
        one per attempt.
        """

        for row in self.ledger.entries():
            if row.get("stage") != stage:
                continue
            if marker in str(row.get("detail", "")) and row.get("resolved_at") is None:
                return True
        return False

    def _record_gate(self, result: StageResult, previous: Mapping[str, Any] | None) -> None:
        """Record every system-known intervention, without asking the operator.

        A gate that halted the run is recorded because it halted the run. Recording is
        deduplicated per still-open gate, and the actor is taken from the producer that
        must act rather than defaulting to HUMAN.
        """

        if result.outcome == "PASS":
            self._record_resolution(result, previous)
            return

        if result.outcome not in self.OPEN_OUTCOMES:
            # FAIL and REJECT are terminal events, not open gates: record each one.
            kind = (
                "CREATIVE_REVIEW_REJECTIONS"
                if result.outcome == "REJECT"
                else "SUPERVISOR_DECISIONS"
            )
            self.record_intervention(
                stage=result.stage, kind=kind, actor="CODEX_SUPERVISOR",
                detail=f"{result.outcome}: {result.reason or 'no reason recorded'}",
                trigger=result.outcome,
            )
            return

        if result.gate is not None:
            artifact = str(
                result.gate.get("missing_artifact") or result.gate.get("artifact") or ""
            )
            producer_type = str(result.gate.get("producer_type") or "CODEX")
            marker = f"producer gate:{artifact}"
            if artifact and self._already_open(result.stage, marker):
                return
            self.record_intervention(
                stage=result.stage,
                kind=str(result.gate.get("intervention_kind") or "SUPERVISOR_DECISIONS"),
                actor=self.PRODUCER_ACTOR.get(producer_type, "CODEX_SUPERVISOR"),
                detail=(
                    f"{marker} requires {producer_type} producer "
                    f"{result.gate.get('producer_id')!r}"
                ),
                trigger=result.outcome,
                after_ref=artifact,
            )
            return

        marker = f"{result.outcome}: {result.reason or ''}"
        if self._already_open(result.stage, marker):
            return
        self.record_intervention(
            stage=result.stage,
            kind=(
                "CREATIVE_REVIEW_REJECTIONS"
                if result.outcome == "REVIEW_REQUIRED"
                else "SUPERVISOR_DECISIONS"
            ),
            actor="CODEX_SUPERVISOR",
            detail=marker,
            trigger=result.outcome,
        )

    def _record_resolution(
        self, result: StageResult, previous: Mapping[str, Any] | None
    ) -> None:
        """Record that a previously open gate was resolved, and a release when made."""

        if previous and previous.get("outcome") in self.OPEN_OUTCOMES:
            was = previous.get("outcome")
            detail = previous.get("gate") or {}
            artifact = str(
                detail.get("missing_artifact") or detail.get("artifact") or ""
            )
            self.record_intervention(
                stage=result.stage,
                kind=str(detail.get("intervention_kind") or "SUPERVISOR_DECISIONS"),
                actor=self.PRODUCER_ACTOR.get(
                    str(detail.get("producer_type") or "CODEX"), "CODEX_SUPERVISOR"
                ),
                detail=(
                    f"producer gate resolved:{artifact} — stage {result.stage!r} "
                    f"advanced past {was}"
                    if artifact
                    else f"open gate resolved — stage {result.stage!r} advanced past {was}"
                ),
                trigger="PRODUCER_GATE_RESOLVED",
                before_ref=artifact or None,
            )

        # A successful final human release is a system-known event.
        authority = result.evidence.get("release_authority") if result.evidence else None
        if result.stage == "REVIEW & REPAIR" and authority:
            master = (self._read(ASSEMBLY_EVIDENCE_ARTIFACT) or {}).get("master_sha256")
            self.record_intervention(
                stage=result.stage,
                kind="SUPERVISOR_DECISIONS",
                actor="HUMAN",
                detail=(
                    f"HUMAN_RELEASE_APPROVED by {authority!r} for master "
                    f"{str(master)[:16]}..."
                ),
                trigger="HUMAN_RELEASE_APPROVED",
                after_ref=str(master) if master else None,
            )

    def _record_paid_calls(self, stage: str, execution: Mapping[str, Any]) -> None:
        """Record paid provider calls when the execution reports them."""

        paid = int(execution.get("paid_api_calls") or 0)
        if paid <= 0:
            return
        self.record_intervention(
            stage=stage,
            kind="VO_GENERATIONS",
            actor="AUTOMATED_REPAIR",
            detail=f"{paid} paid API call(s) made during {stage!r}",
            trigger="PAID_API_CALL",
            paid_api_calls=paid,
        )

    # ---- execution -------------------------------------------------------------

    def run_stage(self, name: str) -> StageResult:
        if name not in STAGE_BY_NAME:
            raise FastPathError(f"unknown stage {name!r}")
        runner = getattr(self, f"_stage_{name.lower().replace(' & ', '_').replace(' ', '_')}")
        return runner(STAGE_BY_NAME[name])

    def step(self, name: str) -> StageResult:
        """Run one stage and checkpoint it.

        A stage that ran but was not recorded is the failure mode this control path
        exists to prevent, so recording is part of stepping rather than something a
        caller may forget. The CLI uses this, so ``--stage`` checkpoints identically to
        a full run.
        """

        result = self.run_stage(name)
        self.checkpoint(result)
        return result

    def run(self, *, until: str | None = None, resume: bool = True) -> RunReport:
        """Run from the first incomplete stage.

        ``resume=True`` (the default) skips stages that have already passed. A stage is
        re-executed only after an explicit :meth:`invalidate`.
        """

        state = self.state()
        results: list[StageResult] = []
        stopped_at: str | None = None
        resumed_from = self.next_stage() if resume else SEMANTIC_STAGES[0]
        for name in SEMANTIC_STAGES:
            if resume and state["stages"][name]["outcome"] == "PASS":
                continue
            result = self.step(name)
            results.append(result)
            if result.outcome in HALTING_OUTCOMES:
                stopped_at = name
                break
            if until is not None and name == until:
                break
        completed = stopped_at is None and self.next_stage() is None
        return RunReport(
            job_id=self.job_id,
            results=tuple(results),
            stopped_at=stopped_at,
            completed=completed,
            resumed_from=resumed_from,
        )

    # ---- real artifact verification --------------------------------------------

    def _verify_media_artifact(
        self, relative: str, *, label: str, expected_frames: int | None = None
    ) -> dict[str, Any]:
        """A stage may not PASS on a plan. The file must exist and be measured.

        Every value below is read from the bytes on disk with ffprobe, so a planning
        document alone can never satisfy a stage that claims to have produced media.
        """

        target = self.path(relative)
        if not target.is_file():
            raise FastPathError(f"{label} produced no artifact at {relative}")
        measured = media_probe.probe_streams(target)
        frames = measured["frame_count"]
        if not frames:
            raise FastPathError(f"{label} artifact {relative} has no measurable frames")
        if expected_frames is not None and int(frames) != int(expected_frames):
            raise FastPathError(
                f"{label} artifact {relative} holds {frames} frames where "
                f"{expected_frames} were expected"
            )
        if not measured["width"] or not measured["height"]:
            raise FastPathError(f"{label} artifact {relative} has no measurable geometry")
        if not measured["fps"]:
            raise FastPathError(f"{label} artifact {relative} has no measurable frame rate")
        return {
            "path": relative,
            "frame_count": int(frames),
            "width": int(measured["width"]),
            "height": int(measured["height"]),
            "fps": float(measured["fps"]),
            "duration_seconds": measured["duration_seconds"],
            "video_codec": measured["video_codec"],
            "audio_codec": measured["audio_codec"],
            "has_audio": bool(measured["has_audio"]),
            "sha256": media_probe.sha256_of_file(target),
            "measured": True,
        }

    def _run_adapter(
        self, stage: Stage, boundary: str, request_artifact: str
    ) -> tuple[dict[str, Any] | None, StageResult | None]:
        """Run one job-scoped execution adapter, returning its result or a failure."""

        try:
            result = execution_adapters.RUNNERS[boundary](
                self.root,
                **({"timebase": self.timebase} if boundary == "picture" else {}),
            )
        except (
            execution_adapters.ExecutionAdapterError,
            timebase_adapter.TimebaseAdapterError,
            media_probe.MediaProbeError,
            OSError,
        ) as exc:
            return None, StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=f"execution_adapters.{boundary}",
                reason=(
                    f"the {boundary} adapter could not produce a real artifact from "
                    f"{request_artifact}: {exc}"
                ),
            )
        return dict(result), None

    # ---- gate helpers ----------------------------------------------------------

    def _producer_gate(
        self, stage: Stage, artifact: str, *, missing_inputs: tuple[str, ...] = ()
    ) -> StageResult:
        """Return an explicit gate naming the producer that must act."""

        gate = producer_registry.gate_for(
            artifact, self.root, missing_inputs=missing_inputs
        )
        return StageResult(
            stage=stage.name,
            outcome="BLOCKED",
            capability=None,
            reason=(
                f"{gate['action_required']}. {str(gate['resume_condition']).capitalize()}."
            ),
            gate=gate,
        )

    def _blocked(self, stage: Stage, missing: Sequence[str]) -> StageResult:
        """Gate a stage whose declared input is absent.

        The first missing declared input determines the producer, so a stage never
        reports a vague blockage when the registry knows exactly who must act.
        """

        artifact = missing[0]
        try:
            return self._producer_gate(stage, artifact, missing_inputs=tuple(missing))
        except producer_registry.ProducerRegistryError:
            return StageResult(
                stage=stage.name,
                outcome="BLOCKED",
                capability=None,
                reason="missing required input(s): " + ", ".join(missing),
                evidence={"missing_inputs": list(missing)},
            )

    # ---- stage runners ---------------------------------------------------------

    def _stage_prepare(self, stage: Stage) -> StageResult:
        missing = self._missing_inputs(stage)
        if missing:
            return self._blocked(stage, missing)
        inventory = self._read("source_inventory.json") or {}
        files = inventory.get("files")
        if not isinstance(files, list) or not files:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason="source_inventory.json carries no files",
            )
        if not job_foundation.verify_source_immutability(files):
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason="source material changed since the inventory was taken",
            )
        return StageResult(
            stage=stage.name,
            outcome="PASS",
            capability=stage.capability,
            artifacts=("source_inventory.json",),
            evidence={"sources": len(files)},
        )

    def _stage_understand_shots(self, stage: Stage) -> StageResult:
        missing = self._missing_inputs(stage)
        if missing:
            return self._blocked(stage, missing)
        payload = self._read("shots/placements.json") or {}
        raw = payload.get("placements")
        if not isinstance(raw, list) or not raw:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason="shots/placements.json carries no placements",
            )

        # The invariant applies to placement coordinates, and it must be the coordinate
        # that is actually used. Validating a measured timestamp and then selecting
        # frames with the producer's own frame index would be cosmetic, so the decoded
        # range is DERIVED here from the measured PTS instead of being taken on trust.
        #
        #   SOURCE        = the measured timestamp the producer states
        #   ANALYSIS GRID = decoded indices resolved from that PTS, plus the CFR count
        #   TIMELINE      = CFR frame grid
        timing: list[dict[str, Any]] = []
        resolved: list[dict[str, Any]] = []
        try:
            for item in raw:
                window = self.timebase.resolve_placement_window(
                    placement_id=item["placement_id"],
                    source=item["media_path"],
                    t_in_seconds=(
                        float(item["t_in_seconds"])
                        if item.get("t_in_seconds") is not None
                        else None
                    ),
                    duration_seconds=(
                        float(item["duration_seconds"])
                        if item.get("duration_seconds") is not None
                        else None
                    ),
                    analysis_fps=self.fps,
                )
                timing.append(window)
                resolved.append({**dict(item), **{
                    "source_in": window["source_in"],
                    "source_out_exclusive": window["source_out_exclusive"],
                }})
        except (KeyError, TypeError, ValueError) as exc:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability="timebase_adapter.TimebaseAdapter.resolve_placement_window",
                reason=f"placement coordinates refused: {exc}",
            )

        try:
            placements = [
                shot_understanding.Placement(
                    placement_id=item["placement_id"],
                    source_id=item["source_id"],
                    media_path=item["media_path"],
                    # Resolved from measured PTS above, not the producer's index.
                    source_in=item["source_in"],
                    source_out_exclusive=item["source_out_exclusive"],
                    timeline_start=item.get("timeline_start", 0),
                    narrative_role=item.get("narrative_role", ""),
                    action_state=item.get("action_state", ""),
                )
                for item in resolved
            ]
            analyses = shot_understanding.analyse_placements(placements)
        except (KeyError, TypeError, ValueError) as exc:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason=f"shot understanding refused the placements: {exc}",
            )
        document = {
            "schema_version": "fast_path_shot_understanding.v1",
            "capability": stage.capability,
            "coordinate_system": timebase_adapter.COORDINATE_SYSTEM,
            "analysis_grid": "CFR_DERIVED_FROM_MEASURED_PTS",
            "placements": [
                {
                    "placement_id": analysis.placement_id,
                    "segments": [
                        {
                            "index": index,
                            "start_frame": segment.start_frame,
                            "end_frame_exclusive": segment.end_frame_exclusive,
                        }
                        for index, segment in enumerate(analysis.segments)
                    ],
                }
                for analysis in analyses
            ],
            "placement_timing": timing,
        }
        artifact = self._write(stage.outputs[0], document)
        return StageResult(
            stage=stage.name,
            outcome="PASS",
            capability=stage.capability,
            artifacts=(artifact,),
            evidence={
                "placements": len(analyses),
                "coordinate_system": timebase_adapter.COORDINATE_SYSTEM,
                "variable_frame_rate_sources": sum(
                    1 for entry in timing if entry["variable_frame_rate"]
                ),
            },
        )

    def _stage_plan_the_edit(self, stage: Stage) -> StageResult:
        missing = self._missing_inputs(stage)
        if missing:
            return self._blocked(stage, missing)
        payload = self._read("edit/timeline_ranges.json") or {}
        raw = payload.get("ranges")
        if not isinstance(raw, list) or not raw:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason="edit/timeline_ranges.json carries no ranges",
            )
        accepted: list[dict[str, Any]] = []
        for item in raw:
            try:
                evidence = None
                if item.get("evidence"):
                    evidence = editing_intelligence.ActionEvidence(
                        preparation_start=item["evidence"]["preparation_start"],
                        action_onset=item["evidence"]["action_onset"],
                        action_completion=item["evidence"]["action_completion"],
                        result_end_exclusive=item["evidence"]["result_end_exclusive"],
                    )
                editing_intelligence.validate_timeline_range(
                    role=item["role"],
                    start_frame=item["start_frame"],
                    end_frame_exclusive=item["end_frame_exclusive"],
                    evidence=evidence,
                )
            except (KeyError, TypeError, ValueError) as exc:
                return StageResult(
                    stage=stage.name,
                    outcome="FAIL",
                    capability=stage.capability,
                    reason=f"timeline range {item.get('shot_id', '?')!r} is illegal: {exc}",
                )
            accepted.append(dict(item))
        artifact = self._write(
            stage.outputs[0],
            {
                "schema_version": "fast_path_editing_plan.v1",
                "capability": stage.capability,
                "fps": self.fps,
                "ranges": accepted,
            },
        )
        return StageResult(
            stage=stage.name,
            outcome="PASS",
            capability=stage.capability,
            artifacts=(artifact,),
            evidence={"ranges": len(accepted)},
        )

    def _stage_finish_the_picture(self, stage: Stage) -> StageResult:
        missing = self._missing_inputs(stage)
        if missing:
            return self._blocked(stage, missing)

        timing_profiles: list[dict[str, Any]] = []
        range_document = self._read("picture/source_ranges.json") or {}
        ranges = range_document.get("ranges") or []
        if not isinstance(ranges, list) or not ranges:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason="picture/source_ranges.json declares no ranges",
            )
        units = [str(item["unit_id"]) for item in ranges]
        try:
            for item in ranges:
                if item.get("t_in_seconds") is not None:
                    resolution = self.timebase.resolve_from_seconds(
                        unit_id=item["unit_id"],
                        source=item["source"],
                        t_in_seconds=float(item["t_in_seconds"]),
                        frames=int(item["frames"]),
                    )
                elif item.get("source_frame_index") is not None:
                    resolution = self.timebase.resolve_from_source_index(
                        unit_id=item["unit_id"],
                        source=item["source"],
                        source_frame_index=int(item["source_frame_index"]),
                        frames=int(item["frames"]),
                    )
                else:
                    raise FastPathError(
                        f"unit {item.get('unit_id', '?')!r} states neither "
                        "t_in_seconds nor source_frame_index; a source range "
                        "cannot be addressed without one of them"
                    )
                out_path = str(self.path(f"picture/ranges/{resolution.unit_id}.mp4"))
                self.timebase.execute(resolution, out_path)
                timing_profiles.append(resolution.as_dict())
            # Bypass detection: every declared unit must have gone through the
            # adapter. A future refactor that extracts a range another way leaves
            # the unit unrecorded and this raises instead of the gap passing.
            self.timebase.assert_range_coverage(units)
        except (KeyError, TypeError, ValueError) as exc:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability="timebase_adapter.TimebaseAdapter.execute",
                reason=f"source-range execution refused: {exc}",
            )
        self._write(
            "picture/timing_profile.json",
            {
                "schema_version": "fast_path_timing_profile.v1",
                "coordinate_system": timebase_adapter.COORDINATE_SYSTEM,
                "ranges": timing_profiles,
            },
        )

        payload = self._read("picture/measurements.json") or {}
        raw = payload.get("shots")
        if not isinstance(raw, list) or not raw:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason="picture/measurements.json carries no shots",
            )
        decisions: list[dict[str, Any]] = []
        try:
            for item in raw:
                measurement = dict(item["measurement"])
                region = measurement.get("product_region")
                if isinstance(region, Mapping):
                    measurement["product_region"] = picture_measurement.ProductRegion(
                        **region
                    )
                shot = picture_measurement.ShotMeasurement(**measurement)
                protection = None
                if item.get("protection"):
                    protection = product_protection.ProtectionResult(**item["protection"])
                decision = picture_decision.decide_shot(
                    shot=shot,
                    pair=None,
                    contains_product=bool(item.get("contains_product", False)),
                    protection=protection,
                )
                decisions.append(
                    {
                        "shot_id": shot.shot_id,
                        "outcome": decision.outcome,
                        "reason": decision.reason,
                    }
                )
        except (KeyError, TypeError, ValueError) as exc:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason=f"picture decision refused the measurements: {exc}",
            )
        picture_execution, failure = self._run_adapter(
            stage, "picture", "picture/picture_request.json"
        )
        if failure is not None:
            return failure
        try:
            measured_picture = self._verify_media_artifact(
                str(picture_execution["path"]), label="picture execution"
            )
        except FastPathError as exc:
            return StageResult(
                stage=stage.name, outcome="FAIL",
                capability="execution_adapters.picture", reason=str(exc),
            )
        artifact = self._write(
            stage.outputs[0],
            {
                "schema_version": "fast_path_picture_finishing.v1",
                "capability": stage.capability,
                "picture_execution": picture_execution,
                "execution_contract": execution_contracts.get_contract("picture").as_dict(),
                "decisions": decisions,
            },
        )
        artifacts = [artifact, str(picture_execution["path"])]
        if timing_profiles:
            artifacts.insert(0, "picture/timing_profile.json")
        return StageResult(
            stage=stage.name,
            outcome="PASS",
            capability=stage.capability,
            artifacts=tuple(artifacts),
            evidence={
                "shots": len(decisions),
                "source_ranges_executed": len(timing_profiles),
                "coordinate_system": timebase_adapter.COORDINATE_SYSTEM,
                "picture_artifact": measured_picture,
            },
        )

    def _commercial_unit(self, item: Mapping[str, Any]) -> Any:
        """Build a CommercialUnit, refusing silent defaults on judgement fields.

        ``visual_self_explanatory``, ``carries_new_commercial_information``,
        ``vo_adds_function_beyond_title`` and ``explanation_supported`` are *judgements*,
        not computed facts. Defaulting them would let the production path answer its own
        exam, so a unit that does not state them is refused.
        """

        required = (
            "unit_id",
            "start_seconds",
            "end_seconds",
            "visual_self_explanatory",
            "carries_new_commercial_information",
            "has_title",
            "vo_adds_function_beyond_title",
            "explanation_supported",
        )
        absent = [key for key in required if key not in item]
        if absent:
            raise FastPathError(
                f"commercial unit {item.get('unit_id', '?')!r} omits required caller "
                "judgement(s): "
                + ", ".join(absent)
                + ". These are creative decisions and must be stated, not defaulted."
            )
        vo = None
        if item.get("vo"):
            raw_vo = item["vo"]
            vo = audio_plan.VoEvent(
                vo_id=raw_vo["vo_id"],
                purpose=raw_vo["purpose"],
                semantic_unit=raw_vo["semantic_unit"],
                required=bool(raw_vo.get("required", True)),
                silence_reason=raw_vo.get("silence_reason"),
                window_seconds=(
                    tuple(raw_vo["window_seconds"]) if raw_vo.get("window_seconds") else None
                ),
            )
        return narration_coverage.CommercialUnit(
            unit_id=item["unit_id"],
            start_seconds=float(item["start_seconds"]),
            end_seconds=float(item["end_seconds"]),
            visual_self_explanatory=bool(item["visual_self_explanatory"]),
            carries_new_commercial_information=bool(
                item["carries_new_commercial_information"]
            ),
            has_title=bool(item["has_title"]),
            vo=vo,
            vo_adds_function_beyond_title=bool(item["vo_adds_function_beyond_title"]),
            explanation_supported=bool(item["explanation_supported"]),
        )

    def _stage_plan_the_words(self, stage: Stage) -> StageResult:
        missing = self._missing_inputs(stage)
        if missing:
            return self._blocked(stage, missing)
        payload = self._read("copy/commercial_units.json") or {}
        raw = payload.get("units")
        if not isinstance(raw, list) or not raw:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason="copy/commercial_units.json carries no units",
            )
        try:
            units = [self._commercial_unit(item) for item in raw]
            report = narration_coverage.assess_narration_coverage(units)
        except (KeyError, TypeError, ValueError) as exc:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason=f"narration coverage refused the units: {exc}",
            )
        document = report.as_dict()
        document["summary"] = narration_coverage.summary(report)
        document["capability"] = stage.capability
        document["execution_contract"] = execution_contracts.get_contract(
            "typography"
        ).as_dict()
        artifact = self._write(stage.outputs[0], document)
        if report.verdict != "PASS":
            return StageResult(
                stage=stage.name,
                outcome="REVIEW_REQUIRED",
                capability=stage.capability,
                artifacts=(artifact,),
                reason=(
                    f"narration coverage returned {report.verdict}: the voice does not "
                    "carry the selling narrative. A narrative repair is a creative "
                    "decision and is not performed automatically. Paid voice generation "
                    "must not run until this is resolved."
                ),
                evidence={
                    "verdict": report.verdict,
                    "silent_units": list(report.silent_units),
                    "blocking": len(report.blocking),
                },
            )
        typography_execution, failure = self._run_adapter(
            stage, "typography", "typography/typography_request.json"
        )
        if failure is not None:
            return failure
        try:
            measured_typography = self._verify_media_artifact(
                str(typography_execution["path"]),
                label="typography execution",
                expected_frames=int(typography_execution["frame_count"]),
            )
        except FastPathError as exc:
            return StageResult(
                stage=stage.name, outcome="FAIL",
                capability="execution_adapters.typography", reason=str(exc),
            )
        return StageResult(
            stage=stage.name,
            outcome="PASS",
            capability=stage.capability,
            artifacts=(artifact, str(typography_execution["path"])),
            evidence={
                "verdict": report.verdict,
                "units": len(units),
                "typography_artifact": measured_typography,
            },
        )

    def _stage_build_the_audio(self, stage: Stage) -> StageResult:
        missing = self._missing_inputs(stage)
        if missing:
            return self._blocked(stage, missing)
        payload = self._read("audio/placement.json") or {}
        raw = payload.get("segments")
        if not isinstance(raw, list) or not raw:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason="audio/placement.json carries no placed segments",
            )
        expectations_payload = self._read("audio/sync_expectations.json") or {}
        raw_expectations = expectations_payload.get("expectations") or []
        try:
            segments = [
                audio_program.PlacedSegment(
                    segment_id=item["segment_id"],
                    start_seconds=float(item["start_seconds"]),
                    end_seconds=float(item["end_seconds"]),
                    text=item["text"],
                )
                for item in raw
            ]
            expectations = [
                audio_program.KeywordExpectation(
                    phrase=item["phrase"],
                    segment_id=item["segment_id"],
                    fraction=float(item["fraction"]),
                    evidence_start=float(item["evidence_start"]),
                    evidence_end=float(item["evidence_end"]),
                    evidence_label=item["evidence_label"],
                    measured=bool(item.get("measured", False)),
                )
                for item in raw_expectations
            ]
            slots = {
                key: (float(value[0]), float(value[1]))
                for key, value in (payload.get("slots") or {}).items()
            }
            design = {
                tuple(str(key).split("->", 1)): (str(value[0]), str(value[1]))
                for key, value in (payload.get("design") or {}).items()
            }
            hero_window = payload.get("hero_window")
            tolerance = expectations_payload.get("sync_tolerance")
            report = audio_program.assess_program(
                segments,
                slots=slots or None,
                design=design or None,
                hero_window=(
                    (float(hero_window[0]), float(hero_window[1])) if hero_window else None
                ),
                hero_approach_from=payload.get("hero_approach_from"),
                final_segment=payload.get("final_segment"),
                expectations=expectations or None,
                sync_tolerance=(float(tolerance) if tolerance is not None else None),
            )
        except (KeyError, TypeError, ValueError) as exc:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason=f"audio program refused the placement: {exc}",
            )
        document = report.as_dict()
        document["capability"] = stage.capability
        document["execution_contract"] = execution_contracts.get_contract("audio").as_dict()
        artifact = self._write(stage.outputs[0], document)
        if not report.approved:
            return StageResult(
                stage=stage.name,
                outcome="REVIEW_REQUIRED",
                capability=stage.capability,
                artifacts=(artifact,),
                reason=(
                    f"audio program is not approvable: FIT={report.fit}, "
                    f"SYNC={report.sync}, RHYTHM={report.rhythm}. FIT alone is never "
                    "approval. The final mix must not be accepted until a human "
                    "resolves this."
                ),
                evidence={
                    "fit": report.fit,
                    "sync": report.sync,
                    "rhythm": report.rhythm,
                    "undesigned_silence_seconds": report.undesigned_silence_seconds,
                },
            )
        audio_execution, failure = self._run_adapter(
            stage, "audio", "audio/audio_request.json"
        )
        if failure is not None:
            return failure
        self._record_paid_calls(stage.name, audio_execution)
        audio_path = str(audio_execution["path"])
        if not self.path(audio_path).is_file():
            return StageResult(
                stage=stage.name, outcome="FAIL",
                capability="execution_adapters.audio",
                reason=f"the audio adapter produced no artifact at {audio_path}",
            )
        if audio_execution.get("clipping") is not False:
            return StageResult(
                stage=stage.name, outcome="FAIL",
                capability="execution_adapters.audio",
                reason="the audio adapter did not report an explicit no-clipping result",
            )
        return StageResult(
            stage=stage.name,
            outcome="PASS",
            capability=stage.capability,
            artifacts=(artifact, audio_path),
            evidence={
                "fit": report.fit, "sync": report.sync, "rhythm": report.rhythm,
                "audio_artifact": {
                    "path": audio_path,
                    "duration_seconds": audio_execution.get("duration_seconds"),
                    "integrated_lufs": audio_execution.get("integrated_lufs"),
                    "true_peak_dbtp": audio_execution.get("true_peak_dbtp"),
                    "sample_peak_dbfs": audio_execution.get("sample_peak_dbfs"),
                    "clipping": False,
                    "sha256": audio_execution.get("sha256"),
                },
            },
        )

    def _stage_assemble_master(self, stage: Stage) -> StageResult:
        """Gate on measured assembly evidence from a job-specific adapter.

        The stage does not pass on a claim, and it does not pass because someone ticked a
        box: it passes when evidence satisfying the ``assemble_master`` contract exists.
        Once that evidence is present the run resumes and reaches REVIEW.
        """

        missing = tuple(
            item for item in stage.inputs if not self.path(item).is_file()
        )
        # The evidence is produced by the adapter from the request, so a request
        # without evidence is the adapter's turn, not a missing producer.
        missing = tuple(item for item in missing if item != ASSEMBLY_EVIDENCE_ARTIFACT)
        if missing:
            return self._blocked(stage, missing)
        if not self.path(ASSEMBLY_EVIDENCE_ARTIFACT).is_file():
            produced, failure = self._run_adapter(
                stage, "assemble", ASSEMBLE_REQUEST_ARTIFACT
            )
            if failure is not None:
                return failure
        document = self._read(ASSEMBLY_EVIDENCE_ARTIFACT)

        # Reconcile the master against the upstream evidence this run actually produced.
        # A master whose frame count disagrees with the accepted picture is not this
        # run's master, however good its own measurements are.
        expected_frames: int | None = None
        for candidate in (
            "typography/typography_execution.json",
            "picture/picture_execution.json",
            "picture/picture_finishing.json",
        ):
            upstream = self._read(candidate)
            if isinstance(upstream, Mapping) and upstream.get("frame_count"):
                expected_frames = int(upstream["frame_count"])
                break
        job = self._read("job.json") or self._read("job_manifest.json") or {}
        loudness_target = None
        if isinstance(job, Mapping):
            audio_contract = job.get("audio") or {}
            if isinstance(audio_contract, Mapping):
                loudness_target = audio_contract.get("target_lufs")

        try:
            verified = execution_contracts.verify_assembly_evidence(
                document,
                job_root=self.root,
                expected_frame_count=expected_frames,
                loudness_target_lufs=(
                    float(loudness_target) if loudness_target is not None else None
                ),
            )
        except execution_contracts.ExecutionContractError as exc:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason=(
                    "assembly evidence does not satisfy the assemble_master contract: "
                    f"{exc}"
                ),
            )
        return StageResult(
            stage=stage.name,
            outcome="PASS",
            capability=stage.capability,
            artifacts=(ASSEMBLY_EVIDENCE_ARTIFACT,),
            evidence=verified,
        )

    def _stage_review_repair(self, stage: Stage) -> StageResult:
        missing = self._missing_inputs(stage)
        if missing:
            return self._blocked(stage, missing)

        payload = self._read("review/review.json")
        try:
            parsed = review.parse_review(payload)
        except (TypeError, ValueError) as exc:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason=(
                    f"the review contract refused this document: {exc}. An incomplete "
                    "review is a contract rejection, not a partial release."
                ),
            )
        verdict = parsed.verdict

        def write_verdict(layers: list[str], released: bool = False,
                          authority: str | None = None) -> str:
            document: dict[str, Any] = {
                "schema_version": "fast_path_review_verdict.v1",
                "capability": stage.capability,
                "reviewer_id": parsed.reviewer_id,
                "executor_id": parsed.executor_id,
                "verdict": verdict,
                "requires_human_gate": parsed.requires_human_gate,
                "blocking_dimensions": [
                    finding.dimension for finding in parsed.blocking_findings
                ],
                "repair_layers": layers,
                "released": released,
            }
            if authority is not None:
                document["release_authority"] = authority
            return self._write(stage.outputs[0], document)

        # A CRITICAL finding is not repaired by a targeted fix; it returns to planning.
        # This is checked before repair planning, because the repair contract itself
        # refuses to build a plan for a REJECT review.
        if verdict == "REJECT":
            artifact = write_verdict([])
            return StageResult(
                stage=stage.name,
                outcome="REJECT",
                capability=stage.capability,
                artifacts=(artifact,),
                reason=(
                    "the review carries a CRITICAL finding, so the verdict is REJECT. A "
                    "REJECT is not repaired by a targeted fix; it returns to planning, "
                    "and that decision belongs to the Supervisor."
                ),
                evidence={"verdict": verdict},
            )

        repair_layers: list[str] = []
        if parsed.blocking_findings:
            # Controlled path: a malformed repair plan is a contract result, not an
            # unhandled exception escaping to the caller.
            try:
                plan = review.build_targeted_repair(parsed, ["ALL"])
                repair_layers = list(review.layers_for_repair(plan))
            except (TypeError, ValueError) as exc:
                return StageResult(
                    stage=stage.name,
                    outcome="FAIL",
                    capability="review.build_targeted_repair",
                    reason=f"repair planning refused this review: {exc}",
                )

        artifact = write_verdict(repair_layers)

        if verdict != "PRODUCTION_READY":
            return StageResult(
                stage=stage.name,
                outcome="REVIEW_REQUIRED",
                capability=stage.capability,
                artifacts=(artifact,),
                reason=(
                    f"verdict is {verdict}. Release always passes the human gate and "
                    "repair never auto-releases; neither is resolved here."
                ),
                evidence={"verdict": verdict, "repair_layers": repair_layers},
            )

        # The reviewer says the work is production ready. That is not a release.
        release_document = self._read(HUMAN_RELEASE_ARTIFACT)
        if release_document is None:
            gate = producer_registry.gate_for(HUMAN_RELEASE_ARTIFACT, self.root)
            return StageResult(
                stage=stage.name,
                outcome="SUPERVISOR_DECISION_REQUIRED",
                capability=stage.capability,
                artifacts=(artifact,),
                reason=(
                    "the review verdict is PRODUCTION_READY, but a reviewer verdict is "
                    "not a release. A distinct human release decision is required at "
                    f"{HUMAN_RELEASE_ARTIFACT}."
                ),
                evidence={"verdict": verdict},
                gate=gate,
            )
        try:
            release = parse_human_release(release_document)
        except FastPathError as exc:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                artifacts=(artifact,),
                reason=f"the human release document is not usable: {exc}",
            )
        if release["review_verdict"] != verdict:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                artifacts=(artifact,),
                reason=(
                    f"the human release answers verdict {release['review_verdict']!r} "
                    f"but the review now derives {verdict!r}; the release does not "
                    "describe this review."
                ),
            )
        verified_master = (self._read(ASSEMBLY_EVIDENCE_ARTIFACT) or {}).get(
            "master_sha256"
        )
        if verified_master and release["master_sha256"] != verified_master:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                artifacts=(artifact,),
                reason=(
                    "the human release approves master "
                    f"{release['master_sha256'][:16]}... but this run verified "
                    f"{str(verified_master)[:16]}...; the release does not describe the "
                    "master that was assembled"
                ),
            )
        if release["decision"] == "REJECTED":
            return StageResult(
                stage=stage.name,
                outcome="REJECT",
                capability=stage.capability,
                artifacts=(artifact,),
                reason=(
                    f"the human release authority {release['authority']!r} rejected "
                    f"release: {release['statement']}"
                ),
                evidence={"verdict": verdict, "authority": release["authority"]},
            )

        # Mark the verdict document as released without rewriting its verdict.
        artifact = write_verdict(repair_layers, True, release["authority"])
        return StageResult(
            stage=stage.name,
            outcome="PASS",
            capability=stage.capability,
            artifacts=(artifact, HUMAN_RELEASE_ARTIFACT),
            evidence={
                "verdict": verdict,
                "human_gate": parsed.requires_human_gate,
                "release_authority": release["authority"],
            },
        )


def _parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the eight-stage Production Fast Path for one job"
    )
    parser.add_argument("--job-root", type=Path, required=True)
    parser.add_argument("--job-id", default=None)
    parser.add_argument(
        "--stage",
        default=None,
        choices=SEMANTIC_STAGES,
        help="run one semantic stage; it checkpoints exactly like a full run",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="re-execute from PREPARE instead of resuming at the first incomplete stage",
    )
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--ascii-staging-check",
        action="store_true",
        help="verify the job root is ASCII-safe before running",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.ascii_staging_check:
            assert_ascii_safe(args.job_root.resolve(), role="job_root")
        path = FastPath(args.job_root, job_id=args.job_id, fps=args.fps)
        if args.stage:
            result = path.step(args.stage)
            payload: Any = result.as_dict()
            code = result.exit_code
        else:
            report = path.run(resume=not args.no_resume)
            payload = report.as_dict()
            code = report.exit_code
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return code
    except (FastPathError, ValueError) as exc:
        print(
            json.dumps(
                {"error": str(exc), "outcome": "FAIL", "exit_code": EXIT_CODES["FAIL"]},
                ensure_ascii=False,
            )
        )
        return EXIT_CODES["FAIL"]


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ASSEMBLY_EVIDENCE_ARTIFACT",
    "EXIT_CODES",
    "HALTING_OUTCOMES",
    "HUMAN_RELEASE_ARTIFACT",
    "OUTCOMES",
    "OUTCOME_TO_LOW_LEVEL_STATE",
    "RELEASE_DECISIONS",
    "REQUIRED_PRODUCTION_MODULES",
    "SEMANTIC_STAGES",
    "STAGES",
    "FastPath",
    "FastPathError",
    "RunReport",
    "Stage",
    "StageResult",
    "main",
    "parse_human_release",
    "resolve_capability",
]
