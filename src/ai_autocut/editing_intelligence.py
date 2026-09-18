"""Small reusable rules for evidence-led timeline trimming.

This module deliberately does not score footage or author an edit.  It makes
two production invariants explicit: a Candidate is an opportunity window, not
the final timeline duration; and a physical action must retain its observable
result before its timeline boundary may be accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EditingIntelligenceError(ValueError):
    """Raised when evidence cannot support a safe timeline decision."""


class NarrativeRole(str, Enum):
    HOOK = "hook"
    IDENTITY = "identity"
    ACTION = "action"
    PROOF = "proof"
    HERO = "hero"
    ENDING = "ending"


@dataclass(frozen=True)
class ActionEvidence:
    """Frame-exact observable phases for one physical action."""

    preparation_start: int
    action_onset: int
    action_completion: int
    result_end_exclusive: int

    def __post_init__(self) -> None:
        values = (
            self.preparation_start,
            self.action_onset,
            self.action_completion,
            self.result_end_exclusive,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise EditingIntelligenceError("action evidence frames must be integers")
        if not (
            self.preparation_start <= self.action_onset
            <= self.action_completion < self.result_end_exclusive
        ):
            raise EditingIntelligenceError("action evidence phases must be chronological")


def useful_action_range(evidence: ActionEvidence) -> tuple[int, int]:
    """Return the shortest action-comprehension range including a result."""

    return evidence.action_onset, evidence.result_end_exclusive


def validate_timeline_range(
    *, role: NarrativeRole, start_frame: int, end_frame_exclusive: int,
    evidence: ActionEvidence | None = None,
) -> None:
    """Reject redundant or incomplete action cuts without prescribing duration."""

    if isinstance(start_frame, bool) or isinstance(end_frame_exclusive, bool):
        raise EditingIntelligenceError("timeline frames must be integers")
    if not isinstance(start_frame, int) or not isinstance(end_frame_exclusive, int):
        raise EditingIntelligenceError("timeline frames must be integers")
    if end_frame_exclusive <= start_frame:
        raise EditingIntelligenceError("timeline range must be non-empty")
    if role in {NarrativeRole.ACTION, NarrativeRole.PROOF, NarrativeRole.HERO}:
        if evidence is None:
            raise EditingIntelligenceError("action-like timeline roles require evidence")
        if start_frame > evidence.action_onset:
            raise EditingIntelligenceError("timeline enters after observable action onset")
        if end_frame_exclusive < evidence.result_end_exclusive:
            raise EditingIntelligenceError("timeline exits before observable result")
