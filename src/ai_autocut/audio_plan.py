"""Audio Intelligence policy: event state, mix role, VO strategy, and repair.

Two ideas carry most of the weight here, and they are deliberately kept apart:

* **Event state** describes what the picture is actually doing.
* **Mix role** describes how loud and how present a sound should be.

A sound can be an event and still be a bed, and a bed can be an event. Treating
the two as one axis is what produces water noise under a dry shot, so the model
keeps them orthogonal and checks that they agree with the visual evidence.

The *policy and its rules* are validated here. Synthesis, mixing, and mastering
are **NOT_IMPLEMENTED** in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence


SCHEMA_VERSION = "audio_plan.v0"

#: Audio is planned, mixed, and mastered by separate later stages.
IMPLEMENTATION = "NOT_IMPLEMENTED"

#: What the picture is doing. ``OFF`` is a real, expected value.
EVENT_STATES = ("OFF", "ONSET", "FLOW", "IMPACT", "DECAY")

#: How present a sound is in the mix. Independent of :data:`EVENT_STATES`.
MIX_ROLES = ("BED", "EVIDENCE", "HERO")

#: A non-``OFF`` event is required before a sound may take a non-``BED`` role.
_ACTIVE_STATES = ("ONSET", "FLOW", "IMPACT", "DECAY")

#: Mix priority, highest first. Voice always wins.
MIX_PRIORITY = ("VO", "EVIDENCE", "BGM")

#: BGM is structurally edited rather than laid end to end.
BGM_STRUCTURE = ("HOOK_INTRO", "PRODUCT_BUILD", "USAGE_LIFT", "CTA_RESOLVE")

#: Voice strategy. One continuous performance is cut into segments, because the
#: same prompt does not reliably reproduce the same sampled speaker.
VO_STRATEGIES = (
    "CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS",
    "INDEPENDENT_PER_SENTENCE",
)
DEFAULT_VO_STRATEGY = "CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS"

#: Gold reference loudness. A reference, not a universal platform law.
GOLD_REFERENCE_LOUDNESS = {"integrated_lufs": -16.0, "true_peak_dbtp": -1.4}
GOLD_REFERENCE_IS_UNIVERSAL = False

_SHOT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class AudioPlanPolicyError(ValueError):
    """Raised when an audio plan contradicts the visual evidence or the mix law."""


def _shot_id(value: object) -> str:
    if not isinstance(value, str) or _SHOT_ID_PATTERN.fullmatch(value) is None:
        raise AudioPlanPolicyError("shot_id is malformed")
    return value


def _enum(value: object, allowed: Sequence[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise AudioPlanPolicyError(f"{label} must be one of: {', '.join(allowed)}")
    return value


@dataclass(frozen=True)
class WaterEvent:
    """One shot's water evidence and the role it plays in the mix."""

    shot_id: str
    has_water_evidence: bool
    event_state: str
    mix_role: str

    def __post_init__(self) -> None:
        _shot_id(self.shot_id)
        if not isinstance(self.has_water_evidence, bool):
            raise AudioPlanPolicyError("has_water_evidence must be a boolean")
        state = _enum(self.event_state, EVENT_STATES, "event_state")
        role = _enum(self.mix_role, MIX_ROLES, "mix_role")
        if not self.has_water_evidence and state != "OFF":
            raise AudioPlanPolicyError(
                f"shot {self.shot_id!r} has no water evidence, so its event state "
                "must be OFF; a dry visual shot never carries water sound"
            )
        if role != "BED" and state not in _ACTIVE_STATES:
            raise AudioPlanPolicyError(
                f"shot {self.shot_id!r} assigns mix role {role} to an inactive "
                "event state; a sound cannot lead the mix while nothing happens"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "shot_id": self.shot_id,
            "has_water_evidence": self.has_water_evidence,
            "event_state": self.event_state,
            "mix_role": self.mix_role,
        }


@dataclass(frozen=True)
class SoundBridge:
    """An intentional continuity device. Requires a stated reason."""

    from_shot_id: str
    to_shot_id: str
    continuity_reason: str

    def __post_init__(self) -> None:
        _shot_id(self.from_shot_id)
        _shot_id(self.to_shot_id)
        if self.from_shot_id == self.to_shot_id:
            raise AudioPlanPolicyError("a sound bridge must join two different shots")
        if not isinstance(self.continuity_reason, str) or not self.continuity_reason.strip():
            raise AudioPlanPolicyError(
                "a sound bridge is only allowed with an explicit continuity reason"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "from_shot_id": self.from_shot_id,
            "to_shot_id": self.to_shot_id,
            "continuity_reason": self.continuity_reason,
        }


@dataclass(frozen=True)
class AudioPlan:
    vo_strategy: str
    water_events: tuple[WaterEvent, ...]
    bgm_structure: tuple[str, ...]
    sound_bridges: tuple[SoundBridge, ...] = ()

    def __post_init__(self) -> None:
        _enum(self.vo_strategy, VO_STRATEGIES, "vo_strategy")
        if not isinstance(self.water_events, tuple) or not self.water_events:
            raise AudioPlanPolicyError("water_events must be a non-empty tuple")
        seen: set[str] = set()
        for event in self.water_events:
            if not isinstance(event, WaterEvent):
                raise AudioPlanPolicyError("water_events must contain WaterEvent values")
            if event.shot_id in seen:
                raise AudioPlanPolicyError(f"duplicate shot_id: {event.shot_id!r}")
            seen.add(event.shot_id)
        for bridge in self.sound_bridges:
            if not isinstance(bridge, SoundBridge):
                raise AudioPlanPolicyError("sound_bridges must contain SoundBridge values")
            if bridge.from_shot_id not in seen or bridge.to_shot_id not in seen:
                raise AudioPlanPolicyError(
                    "a sound bridge must reference shots declared in this plan"
                )
        _assert_structural_bgm(self.bgm_structure)

    @property
    def dry_shots(self) -> tuple[str, ...]:
        """Shots with no water evidence, which therefore carry no water sound."""

        return tuple(
            event.shot_id for event in self.water_events if not event.has_water_evidence
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "implementation": IMPLEMENTATION,
            "vo_strategy": self.vo_strategy,
            "water_events": [event.as_dict() for event in self.water_events],
            "bgm_structure": list(self.bgm_structure),
            "sound_bridges": [bridge.as_dict() for bridge in self.sound_bridges],
        }


def _assert_structural_bgm(structure: Sequence[object]) -> None:
    if isinstance(structure, (str, bytes)) or not isinstance(structure, Sequence):
        raise AudioPlanPolicyError("bgm_structure must be a sequence")
    if tuple(structure) != BGM_STRUCTURE:
        raise AudioPlanPolicyError(
            "BGM must be structurally edited through exactly "
            + " -> ".join(BGM_STRUCTURE)
            + "; a single track laid end to end is not accepted"
        )


def mix_rank(role: str) -> int:
    """Return the mix priority rank of one source, highest priority first."""

    if role not in MIX_PRIORITY:
        raise AudioPlanPolicyError(f"role must be one of: {', '.join(MIX_PRIORITY)}")
    return MIX_PRIORITY.index(role)


def ducking_target(role: str) -> str:
    """Return the source that wins when ``role`` competes for level.

    Voice has the highest mix priority, so every other source ducks under it.
    """

    mix_rank(role)
    return MIX_PRIORITY[0]


def assert_creative_pass_before_mastering(creative_pass_passed: object) -> None:
    """Mastering is a separate stage that may only follow a creative PASS."""

    if creative_pass_passed is not True:
        raise AudioPlanPolicyError(
            "mastering requires a completed creative audio PASS; creative judgement "
            "and loudness delivery are separate gates"
        )


def assert_targeted_repair(
    *, scope_shots: Sequence[object], regenerate: object = False
) -> tuple[str, ...]:
    """Validate a repair is targeted. Full regeneration is refused by default."""

    if regenerate is True:
        raise AudioPlanPolicyError(
            "regenerating an entire video or voice track is not the default repair; "
            "repair must be scoped to the smallest affected range"
        )
    if isinstance(scope_shots, (str, bytes)) or not isinstance(scope_shots, Sequence):
        raise AudioPlanPolicyError("scope_shots must be a sequence")
    if not scope_shots:
        raise AudioPlanPolicyError("a targeted repair must declare its affected shots")
    return tuple(_shot_id(shot) for shot in scope_shots)


def parse_audio_plan(document: object) -> AudioPlan:
    if not isinstance(document, Mapping):
        raise AudioPlanPolicyError("audio plan must be a JSON object")
    allowed = (
        "schema_version",
        "vo_strategy",
        "water_events",
        "bgm_structure",
        "sound_bridges",
    )
    unknown = sorted(set(document) - set(allowed))
    missing = sorted(set(allowed) - set(document))
    if unknown:
        raise AudioPlanPolicyError(
            f"audio plan has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise AudioPlanPolicyError(
            f"audio plan is missing required key(s): {', '.join(missing)}"
        )
    if document["schema_version"] != SCHEMA_VERSION:
        raise AudioPlanPolicyError(f"schema_version must be {SCHEMA_VERSION!r}")

    raw_events = document["water_events"]
    raw_bridges = document["sound_bridges"]
    raw_bgm = document["bgm_structure"]
    if not isinstance(raw_events, list) or not isinstance(raw_bridges, list):
        raise AudioPlanPolicyError("water_events and sound_bridges must be arrays")
    if not isinstance(raw_bgm, list):
        raise AudioPlanPolicyError("bgm_structure must be an array")

    event_keys = ("shot_id", "has_water_evidence", "event_state", "mix_role")
    events: list[WaterEvent] = []
    for index, raw in enumerate(raw_events):
        label = f"water_events[{index}]"
        if not isinstance(raw, Mapping):
            raise AudioPlanPolicyError(f"{label} must be a JSON object")
        item_unknown = sorted(set(raw) - set(event_keys))
        item_missing = sorted(set(event_keys) - set(raw))
        if item_unknown:
            raise AudioPlanPolicyError(
                f"{label} has unsupported key(s): {', '.join(item_unknown)}"
            )
        if item_missing:
            raise AudioPlanPolicyError(
                f"{label} is missing required key(s): {', '.join(item_missing)}"
            )
        events.append(
            WaterEvent(
                shot_id=raw["shot_id"],  # type: ignore[arg-type]
                has_water_evidence=raw["has_water_evidence"],  # type: ignore[arg-type]
                event_state=raw["event_state"],  # type: ignore[arg-type]
                mix_role=raw["mix_role"],  # type: ignore[arg-type]
            )
        )

    bridge_keys = ("from_shot_id", "to_shot_id", "continuity_reason")
    bridges: list[SoundBridge] = []
    for index, raw in enumerate(raw_bridges):
        label = f"sound_bridges[{index}]"
        if not isinstance(raw, Mapping):
            raise AudioPlanPolicyError(f"{label} must be a JSON object")
        item_unknown = sorted(set(raw) - set(bridge_keys))
        item_missing = sorted(set(bridge_keys) - set(raw))
        if item_unknown:
            raise AudioPlanPolicyError(
                f"{label} has unsupported key(s): {', '.join(item_unknown)}"
            )
        if item_missing:
            raise AudioPlanPolicyError(
                f"{label} is missing required key(s): {', '.join(item_missing)}"
            )
        bridges.append(
            SoundBridge(
                from_shot_id=raw["from_shot_id"],  # type: ignore[arg-type]
                to_shot_id=raw["to_shot_id"],  # type: ignore[arg-type]
                continuity_reason=raw["continuity_reason"],  # type: ignore[arg-type]
            )
        )

    return AudioPlan(
        vo_strategy=document["vo_strategy"],  # type: ignore[arg-type]
        water_events=tuple(events),
        bgm_structure=tuple(raw_bgm),  # type: ignore[arg-type]
        sound_bridges=tuple(bridges),
    )
