"""The Agent authoring boundary.

Six of this project's artifacts cannot be produced deterministically. Deciding which shots
carry the story, what the copy says, or which phrases must land on which evidence are
judgements, not computations. For the Third SKU they were authored by hand, one ad-hoc
script per artifact, and the fast path could only report them missing.

This module is the narrow seam that replaces that. It does not decide anything and it
contains no creative logic: it names the artifacts that need authoring, describes what the
author must satisfy, and hands that to whatever agent is wired in.

The registry already says which artifacts those are, so this module reads it rather than
keeping a second list. That matters: a hand-maintained parallel list is how the two drift.

What this is NOT
----------------
Not a workflow engine, not a queue, not a scheduler. Three classes, one protocol, no state
of its own. The orchestrator decides *when* to author; this decides only *how* to ask.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from . import producer_registry

#: What the orchestrator may do about one artifact.
#:
#: AUTHOR  - an agent must write it; no deterministic producer can
#: EXECUTE - a deterministic in-repo producer can write it from other artifacts
#: GATE    - only a human decision can unblock it
ACTION_AUTHOR = "AUTHOR"
ACTION_EXECUTE = "EXECUTE"
ACTION_GATE = "GATE"

ACTIONS = (ACTION_AUTHOR, ACTION_EXECUTE, ACTION_GATE)

#: producer_type -> how the orchestrator should treat the artifact.
_ACTION_FOR_TYPE = {
    "CODEX": ACTION_AUTHOR,
    "ADAPTER": ACTION_EXECUTE,
    "AUTO": ACTION_EXECUTE,
    "HUMAN": ACTION_GATE,
}


class AuthoringError(ValueError):
    """Raised when an authoring request cannot be made or satisfied."""


@dataclass(frozen=True)
class AuthoringRequest:
    """Everything an authoring agent needs, and nothing about the creative answer."""

    artifact: str
    stage: str
    producer_id: str
    procedure: str
    output_contract: str
    required_inputs: tuple[str, ...]
    job_root: Path

    def present_inputs(self) -> tuple[str, ...]:
        return tuple(item for item in self.required_inputs
                     if (self.job_root / item).is_file())

    def missing_inputs(self) -> tuple[str, ...]:
        return tuple(item for item in self.required_inputs
                     if not (self.job_root / item).is_file())

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "stage": self.stage,
            "producer_id": self.producer_id,
            "procedure": self.procedure,
            "output_contract": self.output_contract,
            "required_inputs": list(self.required_inputs),
            "present_inputs": list(self.present_inputs()),
            "missing_inputs": list(self.missing_inputs()),
            "job_root": str(self.job_root),
        }


@runtime_checkable
class AuthoringAgent(Protocol):
    """The seam. An implementation may be a model, a human, or a test fixture."""

    def author(self, request: AuthoringRequest) -> bool:
        """Author the artifact. Return True only if it now exists and is valid."""


class NullAuthoringAgent:
    """Refuses everything, and says why.

    This is the honest default: with no agent wired, the orchestrator must stop at a real
    gate rather than pretend an artifact was produced.
    """

    def __init__(self, reason: str = "no authoring agent is configured") -> None:
        self.reason = reason

    def author(self, request: AuthoringRequest) -> bool:
        return False


class ScriptedAuthoringAgent:
    """A deterministic agent for tests: a table of artifact -> in-memory payload.

    Writes real files into a real job root, so production paths are exercised for real
    rather than mocked away. Requests it has no entry for are refused, which is what makes
    "the system stops at a genuine gate" testable.
    """

    def __init__(self, payloads: Mapping[str, Any], *, name: str = "scripted") -> None:
        self.payloads = dict(payloads)
        self.name = name
        self.requests: list[AuthoringRequest] = []

    def author(self, request: AuthoringRequest) -> bool:
        self.requests.append(request)
        if request.artifact not in self.payloads:
            return False
        target = request.job_root / request.artifact
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.payloads[request.artifact]
        if isinstance(payload, str):
            target.write_text(payload, encoding="utf-8")
        else:
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        return True


class CommandAuthoringAgent:
    """Runs an external command once per artifact, with the request on stdin.

    The command is a production convenience: it lets a real agent (or a human at a shell)
    satisfy the boundary without this module knowing what that agent is. It is deliberately
    dumb — it does not retry, does not parse model output, and treats any non-zero exit or
    a missing artifact as a refusal.
    """

    def __init__(self, command: str, *, timeout_seconds: float = 1800.0) -> None:
        if not command.strip():
            raise AuthoringError("a command agent needs a command")
        self.command = command
        self.timeout_seconds = timeout_seconds

    def author(self, request: AuthoringRequest) -> bool:
        try:
            completed = subprocess.run(
                self.command, shell=True, input=json.dumps(request.as_dict()),
                capture_output=True, text=True, timeout=self.timeout_seconds,
                cwd=str(request.job_root),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if completed.returncode != 0:
            return False
        return (request.job_root / request.artifact).is_file()


def action_for(artifact: str) -> tuple[str, producer_registry.Producer]:
    """How the orchestrator should treat this artifact, and who owns it.

    The mapping comes from the registry's producer_type, so there is exactly one place that
    says who produces what.
    """

    producer = producer_registry.producer_for(artifact)
    action = _ACTION_FOR_TYPE.get(producer.producer_type)
    if action is None:
        raise AuthoringError(
            f"{artifact!r} has producer_type {producer.producer_type!r}, which no action "
            f"covers; expected one of {', '.join(sorted(_ACTION_FOR_TYPE))}"
        )
    return action, producer


def request_for(artifact: str, job_root: Path | str) -> AuthoringRequest:
    """Build the authoring request for one artifact from its registry entry."""

    _, producer = action_for(artifact)
    return AuthoringRequest(
        artifact=producer.artifact,
        stage=producer.stage,
        producer_id=producer.producer_id,
        procedure=producer.procedure,
        output_contract=producer.output_contract,
        required_inputs=tuple(producer.required_inputs),
        job_root=Path(job_root),
    )


__all__ = [
    "ACTION_AUTHOR",
    "ACTION_EXECUTE",
    "ACTION_GATE",
    "ACTIONS",
    "AuthoringAgent",
    "AuthoringError",
    "AuthoringRequest",
    "CommandAuthoringAgent",
    "NullAuthoringAgent",
    "ScriptedAuthoringAgent",
    "action_for",
    "request_for",
]
