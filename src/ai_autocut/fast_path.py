"""The eight-stage Production Fast Path — the authoritative production control path.

What this is
------------
One control path that knows, for a job: **which semantic stage comes next, which
capability must run in it, which artifacts must exist, and whether execution may
continue.** It is a *control* path, not an intelligence: it makes no creative
decision, repairs nothing on its own, and never substitutes for the Supervisor.

What this is not
----------------
It is not a one-command autonomous editor, and it does not claim to be. A stage with
no adapter returns ``SUPERVISOR_DECISION_REQUIRED`` rather than passing quietly, so an
unbuilt capability shows up as an explicit stop instead of a green light.

Why it exists
-------------
The Gate G.0 audit found capabilities that were implemented, tested and then never
called by any production path: ``timebase.py``, ``narration_coverage.py``,
``audio_program.py`` and the whole ``review``/repair contract. Every one of them had
passing unit tests, which is exactly why unit tests could not catch it.

The guard is structural. Each :class:`Stage` **declares** its capability, its inputs
and its outputs, and every :class:`StageResult` **records the capability that actually
ran**. A stage that reports ``PASS`` without naming a capability is a wiring failure by
construction, and ``tests/test_fast_path_wiring.py`` fails if a declared capability
loses its caller.

Stage outcomes
--------------
``PASS``                        the stage completed and its artifacts exist
``REVIEW_REQUIRED``             a wired capability refused; a human decides
``SUPERVISOR_DECISION_REQUIRED`` a capability is unbuilt or a judgement is the Supervisor's
``BLOCKED``                     an input or the environment is missing
``FAIL``                        the stage ran and produced an unacceptable result

``REVIEW_REQUIRED`` and ``SUPERVISOR_DECISION_REQUIRED`` **always stop the run.**
Nothing here resolves them, retries them, or works around them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import (
    audio_plan,
    audio_program,
    editing_intelligence,
    intervention_ledger,
    job_foundation,
    narration_coverage,
    picture_decision,
    picture_measurement,
    product_protection,
    review,
    shot_understanding,
    timebase_adapter,
    typography_adapter,
)
from .paths import assert_ascii_safe

STATE_FILENAME = "fast_path_state.json"
ARTIFACT_REFERENCES_FILENAME = "artifact_references.json"

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
    "REVIEW_REQUIRED",
    "SUPERVISOR_DECISION_REQUIRED",
    "BLOCKED",
    "FAIL",
)

#: Fast-path outcome -> the low-level ``job_foundation`` state it is recorded as.
#: The low-level vocabulary is execution detail underneath the semantic lifecycle.
OUTCOME_TO_LOW_LEVEL_STATE = {
    "PASS": "PASS",
    "REVIEW_REQUIRED": "NEEDS_REVIEW",
    "SUPERVISOR_DECISION_REQUIRED": "NEEDS_REVIEW",
    "BLOCKED": "FAILED",
    "FAIL": "FAILED",
}

#: Outcomes that halt the run. The orchestrator never resolves them itself.
HALTING_OUTCOMES = (
    "REVIEW_REQUIRED",
    "SUPERVISOR_DECISION_REQUIRED",
    "BLOCKED",
    "FAIL",
)


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
    #: Cross-cutting invariants applied to work inside this stage, in addition to the
    #: stage's headline capability. ``timebase_adapter`` belongs here rather than as a
    #: single stage's capability, because it governs *every* source-range conversion
    #: rather than being one step of one stage.
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
                raise FastPathError(
                    f"invariant {invariant!r} must be a dotted path"
                )


#: The declarative control table. This is the single place that decides which
#: capability a stage must run, which is what stops a stage being quietly skipped.
STAGES: tuple[Stage, ...] = (
    Stage(
        name="PREPARE",
        low_level=("PREPARE",),
        capability="job_foundation.verify_source_immutability",
        inputs=("source_inventory.json",),
        outputs=("source_inventory.json",),
        note="source inventory is immutable; a job that was never initialized stops here",
    ),
    Stage(
        name="UNDERSTAND SHOTS",
        low_level=("ANALYZE", "CANDIDATE_SHOT_POOL", "MATERIAL_COVERAGE"),
        capability="shot_understanding.analyse_placements",
        inputs=("shots/placements.json",),
        outputs=("shots/shot_understanding.json",),
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
        inputs=("picture/measurements.json",),
        outputs=("picture/picture_finishing.json",),
        note=(
            "read-only measurement and decision. Every source range declared in "
            "picture/source_ranges.json is executed through the timebase adapter, "
            "which is the only authorised source-range path. DaVinci execution is an "
            "adapter boundary and is not performed here"
        ),
        invariants=("timebase_adapter.TimebaseAdapter.execute",),
    ),
    Stage(
        name="PLAN THE WORDS",
        low_level=("PLAN_THE_WORDS",),
        capability="narration_coverage.assess_narration_coverage",
        inputs=("copy/commercial_units.json",),
        outputs=("copy/narration_coverage.json",),
        note="runs BEFORE any paid voice generation",
    ),
    Stage(
        name="BUILD THE AUDIO",
        low_level=("BUILD_THE_AUDIO",),
        capability="audio_program.assess_program",
        inputs=("audio/placement.json", "audio/sync_expectations.json"),
        outputs=("audio/audio_program.json",),
        note="runs after VO placement and before the final mix is accepted",
    ),
    Stage(
        name="ASSEMBLE & MASTER",
        low_level=("FINAL",),
        capability=None,
        inputs=(),
        outputs=("final/master.json",),
        manual=True,
        note=(
            "no production packaging adapter exists. The repository contains no "
            "packaging code, so this stage stops for a Supervisor rather than "
            "reporting success it did not achieve"
        ),
    ),
    Stage(
        name="REVIEW & REPAIR",
        low_level=("REVIEW", "DELIVERY"),
        capability="review.parse_review",
        inputs=("review/review.json",),
        outputs=("review/verdict.json",),
        note="an incomplete review fails closed; the human gate always applies",
    ),
)

STAGE_BY_NAME = {stage.name: stage for stage in STAGES}

#: The modules the fast path is required to reach. A wiring test asserts each one is
#: declared by some stage, so a refactor that disconnects one fails loudly.
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "outcome": self.outcome,
            "capability": self.capability,
            "artifacts": list(self.artifacts),
            "reason": self.reason,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class RunReport:
    """The outcome of one fast-path run."""

    job_id: str
    results: tuple[StageResult, ...]
    stopped_at: str | None
    completed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "fast_path_run.v1",
            "job_id": self.job_id,
            "completed": self.completed,
            "stopped_at": self.stopped_at,
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
    candidates = [module_name]
    if not module_name.startswith(("ai_autocut", "src.")):
        candidates = [f"ai_autocut.{module_name}", f"src.ai_autocut.{module_name}"]
    elif module_name.startswith("ai_autocut"):
        candidates = [module_name, f"src.{module_name}"]
    module = None
    errors: list[str] = []
    for candidate in candidates:
        try:
            module = importlib.import_module(candidate)
            break
        except ImportError as exc:  # try the next spelling
            errors.append(f"{candidate}: {exc}")
    if module is None:
        raise FastPathError(
            f"cannot import {dotted!r} ({'; '.join(errors)})"
        )
    try:
        attribute = getattr(module, symbol)
    except AttributeError as exc:
        raise FastPathError(
            f"{module.__name__!r} has no symbol {symbol!r} (declared as {dotted!r})"
        ) from exc
    if not callable(attribute):
        raise FastPathError(f"{dotted!r} is not callable")
    return attribute


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
            "schema_version": "fast_path_state.v1",
            "job_id": self.job_id,
            "supervisor_authority": self.supervisor_authority,
            "stages": {name: {"outcome": None, "capability": None} for name in SEMANTIC_STAGES},
            "history": [],
        }

    def next_stage(self) -> str | None:
        """The first stage that has not passed. ``None`` means the run is complete."""

        state = self.state()
        for name in SEMANTIC_STAGES:
            if state["stages"][name]["outcome"] != "PASS":
                return name
        return None

    def checkpoint(self, result: StageResult) -> None:
        state = self.state()
        stage = STAGE_BY_NAME[result.stage]
        state["stages"][result.stage] = {
            "outcome": result.outcome,
            "capability": result.capability,
            "low_level": [
                {"stage": low, "state": OUTCOME_TO_LOW_LEVEL_STATE[result.outcome]}
                for low in stage.low_level
            ],
            "artifacts": list(result.artifacts),
            "reason": result.reason,
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

    # ---- execution -------------------------------------------------------------

    def run_stage(self, name: str) -> StageResult:
        if name not in STAGE_BY_NAME:
            raise FastPathError(f"unknown stage {name!r}")
        runner = getattr(self, f"_stage_{name.lower().replace(' & ', '_').replace(' ', '_')}")
        return runner(STAGE_BY_NAME[name])

    def step(self, name: str) -> StageResult:
        """Run one stage and checkpoint it.

        A stage that ran but was not recorded is the failure mode this whole control
        path exists to prevent, so recording is part of stepping rather than something
        a caller may forget.
        """

        result = self.run_stage(name)
        self.checkpoint(result)
        return result

    def run(self, *, until: str | None = None) -> RunReport:
        results: list[StageResult] = []
        stopped_at: str | None = None
        for name in SEMANTIC_STAGES:
            result = self.step(name)
            results.append(result)
            if result.outcome in HALTING_OUTCOMES:
                stopped_at = name
                break
            if until is not None and name == until:
                break
        return RunReport(
            job_id=self.job_id,
            results=tuple(results),
            stopped_at=stopped_at,
            completed=stopped_at is None and len(results) == len(SEMANTIC_STAGES),
        )

    # ---- stage runners ---------------------------------------------------------

    def _stage_prepare(self, stage: Stage) -> StageResult:
        missing = self._missing_inputs(stage)
        if missing:
            return StageResult(
                stage=stage.name,
                outcome="SUPERVISOR_DECISION_REQUIRED",
                capability=None,
                reason=(
                    "this job is not initialized: "
                    + ", ".join(missing)
                    + " is absent. Job initialization is a Supervisor step and is not "
                    "performed automatically."
                ),
            )
        inventory = self._read("source_inventory.json") or {}
        files = inventory.get("files")
        if not isinstance(files, list) or not files:
            return StageResult(
                stage=stage.name,
                outcome="FAIL",
                capability=stage.capability,
                reason="source_inventory.json carries no files",
            )
        identical = job_foundation.verify_source_immutability(files)
        if not identical:
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
        try:
            placements = [
                shot_understanding.Placement(
                    placement_id=item["placement_id"],
                    source_id=item["source_id"],
                    media_path=item["media_path"],
                    source_in=item["source_in"],
                    source_out_exclusive=item["source_out_exclusive"],
                    timeline_start=item.get("timeline_start", 0),
                    narrative_role=item.get("narrative_role", ""),
                    action_state=item.get("action_state", ""),
                )
                for item in raw
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
        }
        artifact = self._write(stage.outputs[0], document)
        return StageResult(
            stage=stage.name,
            outcome="PASS",
            capability=stage.capability,
            artifacts=(artifact,),
            evidence={"placements": len(analyses)},
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

        # The timebase invariant is enforced here, for every source range this stage
        # is asked to execute. A range is addressed by a measured source timestamp; a
        # source frame index may be recorded but is resolved through the measured PTS
        # table, never by dividing by an assumed frame rate.
        timing_profiles: list[dict[str, Any]] = []
        range_document = self._read("picture/source_ranges.json")
        if isinstance(range_document, Mapping):
            ranges = range_document.get("ranges") or []
            if not isinstance(ranges, list) or not ranges:
                return StageResult(
                    stage=stage.name,
                    outcome="FAIL",
                    capability=stage.capability,
                    reason="picture/source_ranges.json declares no ranges",
                )
            units: list[str] = []
            try:
                for item in ranges:
                    units.append(str(item["unit_id"]))
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
                # adapter. If a future refactor extracts a range some other way, this
                # raises instead of the gap passing unnoticed.
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
                    protection = product_protection.ProtectionResult(
                        **item["protection"]
                    )
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
        artifact = self._write(
            stage.outputs[0],
            {
                "schema_version": "fast_path_picture_finishing.v1",
                "capability": stage.capability,
                "da_vinci_execution": "ADAPTER_BOUNDARY_NOT_PERFORMED",
                "decisions": decisions,
            },
        )
        artifacts = (artifact,)
        if timing_profiles:
            artifacts = ("picture/timing_profile.json", artifact)
        return StageResult(
            stage=stage.name,
            outcome="PASS",
            capability=stage.capability,
            artifacts=artifacts,
            evidence={
                "shots": len(decisions),
                "source_ranges_executed": len(timing_profiles),
                "coordinate_system": timebase_adapter.COORDINATE_SYSTEM,
            },
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
        return StageResult(
            stage=stage.name,
            outcome="PASS",
            capability=stage.capability,
            artifacts=(artifact,),
            evidence={"verdict": report.verdict, "units": len(units)},
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
            # A declared audio design is job-scoped art direction, exactly like the
            # typography layout: the module does not invent reasons for silence, so a
            # gap the job intends must be stated here or it is reported as a defect.
            design = {
                tuple(str(key).split("->", 1)): (str(value[0]), str(value[1]))
                for key, value in (payload.get("design") or {}).items()
            }
            hero_window = payload.get("hero_window")
            # No universal sync tolerance: whatever this job declared, or nothing.
            tolerance = expectations_payload.get("sync_tolerance")
            report = audio_program.assess_program(
                segments,
                slots=slots or None,
                design=design or None,
                hero_window=(
                    (float(hero_window[0]), float(hero_window[1]))
                    if hero_window
                    else None
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
        return StageResult(
            stage=stage.name,
            outcome="PASS",
            capability=stage.capability,
            artifacts=(artifact,),
            evidence={"fit": report.fit, "sync": report.sync, "rhythm": report.rhythm},
        )

    def _stage_assemble_master(self, stage: Stage) -> StageResult:
        """This stage stops. There is no packaging code in this repository."""

        return StageResult(
            stage=stage.name,
            outcome="SUPERVISOR_DECISION_REQUIRED",
            capability=None,
            reason=(
                "no production packaging adapter exists. Assembly, encode/remux, "
                "frame and black-frame validation, audio QA and final master "
                "generation are job-local or manual today, so this stage cannot "
                "report PASS. Supply a packaging adapter, or accept this as an "
                "explicit manual step."
            ),
            evidence={"manual_adapter_required": True},
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
        artifact = self._write(
            stage.outputs[0],
            {
                "schema_version": "fast_path_review_verdict.v1",
                "capability": stage.capability,
                "reviewer_id": parsed.reviewer_id,
                "executor_id": parsed.executor_id,
                "verdict": verdict,
                "requires_human_gate": parsed.requires_human_gate,
                "blocking_dimensions": [
                    finding.dimension for finding in parsed.blocking_findings
                ],
                "repair_layers": list(
                    review.layers_for_repair(
                        review.build_targeted_repair(parsed, ["ALL"])
                    )
                )
                if parsed.blocking_findings
                else [],
            },
        )
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
                evidence={"verdict": verdict},
            )
        return StageResult(
            stage=stage.name,
            outcome="PASS",
            capability=stage.capability,
            artifacts=(artifact,),
            evidence={"verdict": verdict, "human_gate": parsed.requires_human_gate},
        )

    # ---- helpers ---------------------------------------------------------------

    def _blocked(self, stage: Stage, missing: Sequence[str]) -> StageResult:
        return StageResult(
            stage=stage.name,
            outcome="BLOCKED",
            capability=None,
            reason="missing required input(s): " + ", ".join(missing),
            evidence={"missing_inputs": list(missing)},
        )


def _parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the eight-stage Production Fast Path for one job"
    )
    parser.add_argument("--job-root", type=Path, required=True)
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--stage", default=None, help="run only this semantic stage")
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
            result = path.run_stage(args.stage)
            payload: Any = result.as_dict()
        else:
            payload = path.run().as_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except (FastPathError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "HALTING_OUTCOMES",
    "OUTCOMES",
    "OUTCOME_TO_LOW_LEVEL_STATE",
    "REQUIRED_PRODUCTION_MODULES",
    "SEMANTIC_STAGES",
    "STAGES",
    "FastPath",
    "FastPathError",
    "RunReport",
    "Stage",
    "StageResult",
    "main",
    "resolve_capability",
]
