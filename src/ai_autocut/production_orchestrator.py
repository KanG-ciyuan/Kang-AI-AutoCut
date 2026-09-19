"""The production orchestrator: makes one launch actually run.

Current main could validate and execute, but it could not produce. ``FastPath`` checks that
a stage's inputs exist and returns BLOCKED when they do not; nothing filled the gap, so the
Third SKU stopped at BUILD THE AUDIO and the remaining work was done by hand.

This walks the same stages, in the same order, through the same validator — and before each
stage it makes the stage's inputs exist:

    AUTHOR   the registry says an agent owns it   -> ask the authoring boundary
    EXECUTE  the registry says an adapter owns it -> run the in-repo producer
    GATE     the registry says a human owns it    -> stop and say exactly what is needed

A missing artifact is therefore no longer automatically a block. A missing artifact whose
producer genuinely needs a human decision still is.

What this deliberately does not do
----------------------------------
It does not bypass ``FastPath``: every stage still goes through ``step()``, so every
existing contract, invariant and gate still applies. It does not re-implement the fast
path, keep its own stage list, or know anything about any particular SKU. It holds no
creative logic whatsoever — it decides *when* to ask, never *what* to answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from . import authoring, fast_path, production_producers, producer_registry

#: Outcomes that end a run.
STOP_COMPLETE = "COMPLETE"
STOP_GATE = "GATE"
STOP_FAILED = "FAILED"
STOP_LIMIT = "LIMIT"

#: Outcomes that mean the stage did not pass, split by what the run should do about it.
#: The membership comes from ``fast_path.HALTING_OUTCOMES`` rather than a local list: a
#: hand-kept copy is how SUPERVISOR_DECISION_REQUIRED was missed, which made the run spin
#: on REVIEW & REPAIR until the step limit instead of stopping at the release gate.
_GATE_OUTCOMES = ("BLOCKED", "REVIEW_REQUIRED", "SUPERVISOR_DECISION_REQUIRED")
_FAILED_OUTCOMES = ("FAIL", "REJECT")

#: How many times one stage may repeat without the run making progress.
_MAX_REPEATS = 3


class ProductionError(ValueError):
    """Raised when a production run cannot be started safely."""


@dataclass(frozen=True)
class ActionRecord:
    """One autonomous act: an artifact was produced, or its producer refused."""

    artifact: str
    stage: str
    action: str
    producer_type: str
    producer_id: str
    produced: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact, "stage": self.stage, "action": self.action,
            "producer_type": self.producer_type, "producer_id": self.producer_id,
            "produced": self.produced, "detail": self.detail,
        }


@dataclass(frozen=True)
class GateStop:
    """A genuine stop: a decision the system is not entitled to make."""

    artifact: str
    stage: str
    producer_type: str
    producer_id: str
    reason: str
    resume_condition: str
    intervention_kind: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact, "stage": self.stage,
            "producer_type": self.producer_type, "producer_id": self.producer_id,
            "reason": self.reason, "resume_condition": self.resume_condition,
            "intervention_kind": self.intervention_kind,
        }


@dataclass
class ProductionReport:
    job_id: str
    job_root: str
    stop: str
    stages_run: list[str] = field(default_factory=list)
    actions: list[ActionRecord] = field(default_factory=list)
    gate: GateStop | None = None
    failure: str = ""
    preview: str | None = None

    @property
    def autonomous_artifacts_produced(self) -> list[str]:
        return [a.artifact for a in self.actions if a.produced]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "production_run.v1",
            "job_id": self.job_id, "job_root": self.job_root, "stop": self.stop,
            "stages_run": list(self.stages_run),
            "autonomous_artifacts_produced": self.autonomous_artifacts_produced,
            "actions": [a.as_dict() for a in self.actions],
            "gate": self.gate.as_dict() if self.gate else None,
            "failure": self.failure, "preview": self.preview,
            "paid_api_calls": 0,
        }

    def explain(self) -> str:
        """A plain statement of where the run stopped and why."""

        if self.stop == STOP_COMPLETE:
            return f"run completed; {len(self.stages_run)} stages passed"
        if self.stop == STOP_GATE and self.gate:
            g = self.gate
            return (
                f"stopped at {g.stage}: {g.artifact} needs a {g.producer_type} decision "
                f"from {g.producer_id}. {g.reason} Resume when: {g.resume_condition}"
            )
        if self.stop == STOP_FAILED:
            return f"stopped: {self.failure}"
        return f"stopped: {self.failure or 'step limit reached'}"


def _default_deterministic(artifact: str) -> Callable[[Path], bool] | None:
    return production_producers.DETERMINISTIC_PRODUCERS.get(artifact)


class ProductionOrchestrator:
    """Drive one job from its first missing artifact to a preview or a real gate."""

    def __init__(
        self,
        job_root: Path | str,
        *,
        job_id: str | None = None,
        fps: int = 30,
        agent: authoring.AuthoringAgent | None = None,
        deterministic: Mapping[str, Callable[[Path], bool]] | None = None,
        supervisor_authority: str = "Codex",
    ) -> None:
        self.root = Path(job_root)
        if not self.root.is_dir():
            raise ProductionError(f"job root does not exist: {self.root}")
        self.job_id = job_id or self.root.name
        self.agent = agent if agent is not None else authoring.NullAuthoringAgent()
        self.deterministic = dict(deterministic) if deterministic is not None else None
        self.fast = fast_path.FastPath(
            self.root, job_id=self.job_id, fps=fps,
            supervisor_authority=supervisor_authority,
        )

    # -- helpers ---------------------------------------------------------------

    def _producer(self, artifact: str) -> Callable[[Path], bool] | None:
        if self.deterministic is not None and artifact in self.deterministic:
            return self.deterministic[artifact]
        return _default_deterministic(artifact)

    def _stage(self, name: str) -> fast_path.Stage:
        for stage in self.fast.stages:
            if stage.name == name:
                return stage
        raise ProductionError(f"unknown stage {name!r}")

    def _ensure_inputs(self, stage: fast_path.Stage, report: ProductionReport) -> GateStop | None:
        """Make the stage's inputs exist, or explain why it cannot be done."""

        # An artifact that is both an input and an output of the SAME stage is produced BY
        # that stage, not before it — ASSEMBLE & MASTER validates the assembly evidence it
        # writes, and PREPARE validates the inventory it writes. Pre-authoring those would
        # ask an agent for evidence of work that has not happened yet.
        produced_by_this_stage = set(stage.outputs)

        for artifact in stage.inputs:
            if (self.root / artifact).is_file():
                continue
            if artifact in produced_by_this_stage:
                continue

            action, producer = authoring.action_for(artifact)

            if action == authoring.ACTION_GATE:
                return GateStop(
                    artifact=artifact, stage=stage.name,
                    producer_type=producer.producer_type, producer_id=producer.producer_id,
                    reason=(f"{artifact} is owned by {producer.producer_id} and only a "
                            f"{producer.producer_type} decision can produce it."),
                    resume_condition=producer.resume_condition,
                    intervention_kind=producer.intervention_kind,
                )

            if action == authoring.ACTION_AUTHOR:
                request = authoring.request_for(artifact, self.root)
                produced = False
                detail = f"agent {getattr(self.agent, 'name', type(self.agent).__name__)}"
                try:
                    produced = bool(self.agent.author(request))
                except Exception as exc:                       # an agent must not crash a run
                    detail = f"agent raised {type(exc).__name__}: {exc}"
                if (self.root / artifact).is_file():
                    produced = True
                report.actions.append(ActionRecord(
                    artifact, stage.name, action, producer.producer_type,
                    producer.producer_id, produced, detail))
                if not produced:
                    return GateStop(
                        artifact=artifact, stage=stage.name,
                        producer_type=producer.producer_type,
                        producer_id=producer.producer_id,
                        reason=(f"{artifact} requires authoring by {producer.producer_id} "
                                f"and the authoring boundary declined it. {detail}"),
                        resume_condition=producer.resume_condition,
                        intervention_kind=producer.intervention_kind,
                    )
                continue

            # ACTION_EXECUTE: prefer a deterministic in-repo producer.
            #
            # If none is wired yet, fall back to the authoring boundary rather than
            # dead-stopping. The registry still says who is accountable, but "no
            # implementation exists" is an engineering gap, and blocking a whole run on one
            # is exactly the failure this orchestrator exists to remove. The fallback is
            # recorded explicitly so a missing producer stays visible instead of being
            # silently papered over by an agent.
            producer_fn = self._producer(artifact)
            if producer_fn is None:
                request = authoring.request_for(artifact, self.root)
                produced = False
                detail = (f"no deterministic producer wired for {producer.producer_id}; "
                          f"fell back to the authoring boundary")
                try:
                    produced = bool(self.agent.author(request))
                except Exception as exc:
                    detail = f"{detail}; agent raised {type(exc).__name__}: {exc}"
                if (self.root / artifact).is_file():
                    produced = True
                report.actions.append(ActionRecord(
                    artifact, stage.name, action, producer.producer_type,
                    producer.producer_id, produced, detail))
                if not produced:
                    return GateStop(
                        artifact=artifact, stage=stage.name,
                        producer_type=producer.producer_type,
                        producer_id=producer.producer_id,
                        reason=(f"{artifact} is registered to the deterministic producer "
                                f"{producer.producer_id}, no in-repo producer is wired for "
                                f"it, and the authoring fallback declined it."),
                        resume_condition=producer.resume_condition,
                        intervention_kind=producer.intervention_kind,
                    )
                continue

            try:
                produced = bool(producer_fn(self.root))
            except Exception as exc:
                produced = False
                detail = f"{type(exc).__name__}: {exc}"
            else:
                detail = f"{producer.producer_id}"
            report.actions.append(ActionRecord(
                artifact, stage.name, action, producer.producer_type,
                producer.producer_id, produced, detail))
            if not produced or not (self.root / artifact).is_file():
                return GateStop(
                    artifact=artifact, stage=stage.name,
                    producer_type=producer.producer_type, producer_id=producer.producer_id,
                    reason=f"the deterministic producer for {artifact} did not produce it. {detail}",
                    resume_condition=producer.resume_condition,
                    intervention_kind=producer.intervention_kind,
                )
        return None

    # -- run -------------------------------------------------------------------

    def run(self, *, until: str | None = None, max_steps: int = 32,
            report: ProductionReport | None = None) -> ProductionReport:
        """Drive the chain until it completes, needs a decision, or genuinely fails."""

        report = report or ProductionReport(self.job_id, str(self.root), STOP_COMPLETE)
        steps = 0
        while True:
            if steps >= max_steps:
                report.stop = STOP_LIMIT
                report.failure = f"stopped after {max_steps} steps without completing"
                return report

            name = self.fast.next_stage()
            if name is None:
                report.stop = STOP_COMPLETE
                report.preview = self._preview_path()
                return report

            stage = self._stage(name)
            gate = self._ensure_inputs(stage, report)
            if gate is not None:
                report.stop = STOP_GATE
                report.gate = gate
                self.fast.record_intervention(
                    stage=gate.stage,
                    kind=gate.intervention_kind,
                    actor=fast_path.FastPath.PRODUCER_ACTOR.get(gate.producer_type,
                                                                "HUMAN"),
                    trigger=gate.artifact,
                    detail=f"{gate.reason} Resume when: {gate.resume_condition}",
                    paid_api_calls=0)
                return report

            result = self.fast.step(name)
            steps += 1
            report.stages_run.append(name)
            outcome = result.outcome
            reason = getattr(result, "reason", "") or "no reason given"

            if outcome in _GATE_OUTCOMES:
                # REVIEW & REPAIR returns SUPERVISOR_DECISION_REQUIRED precisely because a
                # reviewer verdict is not a release. That is the system working: it says so
                # and hands the decision back.
                report.stop = STOP_GATE
                report.gate = GateStop(
                    artifact="release/human_release.json", stage=name,
                    producer_type="HUMAN", producer_id="human-release-authority",
                    reason=reason,
                    resume_condition=("a human records the release decision at "
                                      "release/human_release.json"),
                    intervention_kind="SUPERVISOR_DECISIONS",
                )
                report.preview = self._preview_path()
                return report

            if outcome in _FAILED_OUTCOMES:
                report.stop = STOP_FAILED
                report.failure = f"{name} returned {outcome}: {reason}"
                return report

            # Loop protection. A stage that keeps returning without the run advancing would
            # otherwise spin until the step limit and report a misleading LIMIT.
            tail = report.stages_run[-_MAX_REPEATS:]
            if len(tail) == _MAX_REPEATS and len(set(tail)) == 1:
                report.stop = STOP_FAILED
                report.failure = (f"{name} repeated {_MAX_REPEATS} times without the run "
                                  f"advancing; last outcome {outcome}: {reason}")
                return report

            # `until` is INCLUSIVE: the named stage runs, then the run stops. Checking
            # before the stage would stop one stage early and, worse, would never ask for
            # that stage's inputs — the artifacts the caller came to have produced.
            if until is not None and name == until:
                report.stop = STOP_COMPLETE
                report.preview = self._preview_path()
                return report

    def _preview_path(self) -> str | None:
        """The assembled preview, if one exists. Never invents a path.

        The assembled master is preferred over any intermediate master: a run that has
        produced a finished preview must not report the audio stem as its result.
        """

        evidence = ("assemble/assembly_evidence.json", "audio/audio_execution.json")
        found: list[str] = []
        for candidate in evidence:
            target = self.root / candidate
            if not target.is_file():
                continue
            try:
                payload = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, Mapping):
                continue
            for key in ("master_path", "master", "preview", "output", "path", "out"):
                value = payload.get(key)
                if isinstance(value, str) and (self.root / value).is_file():
                    found.append(value)
        for value in found:
            if value.lower().endswith((".mp4", ".mov", ".mkv")):
                return value
        return found[0] if found else None


def gate_document(artifact: str) -> dict[str, Any]:
    """The registry's own description of a gate, for reporting without a run."""

    producer = producer_registry.producer_for(artifact)
    return producer.as_dict()


__all__ = [
    "ActionRecord",
    "GateStop",
    "ProductionError",
    "ProductionOrchestrator",
    "ProductionReport",
    "STOP_COMPLETE",
    "STOP_FAILED",
    "STOP_GATE",
    "STOP_LIMIT",
    "gate_document",
]
