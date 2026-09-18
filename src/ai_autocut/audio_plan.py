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

#: What the music is being asked to do in a section. These are *intents*, not levels:
#: the executor decides the actual gain against whatever else is in the mix and reports
#: the measured result as evidence. Concrete values belong to one job and are never
#: promoted into this contract.
#:
#: ``HOLD``   stay where it is
#: ``YIELD``  give way to something with a higher claim on attention
#: ``RETURN`` come back after yielding
#: ``RAMP``   move between levels across a transition rather than jumping
BGM_INTENTS = ("HOLD", "YIELD", "RETURN", "RAMP")

#: How a level change is executed. ``RAMP`` is the default because an instant step is
#: what makes music appear to drop out; a ``STEP`` is allowed only with a stated reason.
BGM_TRANSITIONS = ("RAMP", "STEP")

#: The default transition, chosen so an unstated change is eased rather than abrupt.
DEFAULT_BGM_TRANSITION = "RAMP"

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
class VoEvent:
    """One planned voice line.

    The line binds to a **semantic unit**, never to an absolute timestamp: a timeline
    that shifts by a frame would otherwise leave the voice describing a shot that is no
    longer on screen. Resolving the unit to seconds is the executor's job.
    """

    vo_id: str
    purpose: str
    semantic_unit: str
    required: bool = True
    silence_reason: str | None = None
    window_seconds: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        _shot_id(self.vo_id)
        if not isinstance(self.purpose, str) or not self.purpose.strip():
            raise AudioPlanPolicyError("a voice event must state its purpose")
        _shot_id(self.semantic_unit)
        if not isinstance(self.required, bool):
            raise AudioPlanPolicyError("required must be a boolean")
        if not self.required:
            if not isinstance(self.silence_reason, str) or not self.silence_reason.strip():
                raise AudioPlanPolicyError(
                    f"voice slot {self.vo_id!r} is not required, so it must state why it "
                    "is deliberately left empty; a hero may be silent, but not by accident"
                )
        elif self.silence_reason is not None:
            raise AudioPlanPolicyError(
                "a required voice event cannot also declare a silence reason"
            )
        if self.window_seconds is not None:
            start, end = self.window_seconds
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                raise AudioPlanPolicyError("a voice window must be a numeric pair")
            if start < 0 or end <= start:
                raise AudioPlanPolicyError("a voice window must be a non-empty range")
            if self.required and (end - start) <= 0:
                raise AudioPlanPolicyError("a required voice event needs a real window")

    @property
    def window_duration(self) -> float | None:
        if self.window_seconds is None:
            return None
        return round(self.window_seconds[1] - self.window_seconds[0], 4)

    def as_dict(self) -> dict[str, object]:
        return {
            "vo_id": self.vo_id,
            "purpose": self.purpose,
            "semantic_unit": self.semantic_unit,
            "required": self.required,
            "silence_reason": self.silence_reason,
            "window_seconds": list(self.window_seconds) if self.window_seconds else None,
        }


@dataclass(frozen=True)
class BgmSection:
    """What the music should do in one structural section.

    Carries intent and a transition shape. It deliberately carries **no gain**: the
    executor computes the level from the intent and the rest of the mix, and reports the
    measured value as evidence.
    """

    section: str
    intent: str
    transition: str = DEFAULT_BGM_TRANSITION
    transition_seconds: float = 0.0
    step_reason: str | None = None

    def __post_init__(self) -> None:
        _enum(self.section, BGM_STRUCTURE, "section")
        _enum(self.intent, BGM_INTENTS, "intent")
        _enum(self.transition, BGM_TRANSITIONS, "transition")
        if self.transition_seconds < 0:
            raise AudioPlanPolicyError("transition_seconds cannot be negative")
        if self.transition == "STEP":
            if not isinstance(self.step_reason, str) or not self.step_reason.strip():
                raise AudioPlanPolicyError(
                    f"section {self.section!r} asks for an instant step, which must state "
                    "why an eased transition is not appropriate"
                )
        elif self.step_reason is not None:
            raise AudioPlanPolicyError(
                "a ramped section does not need a step reason"
            )
        if self.transition == "RAMP" and self.transition_seconds <= 0:
            raise AudioPlanPolicyError(
                f"section {self.section!r} ramps, so it must state how long the ramp is"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "section": self.section,
            "intent": self.intent,
            "transition": self.transition,
            "transition_seconds": self.transition_seconds,
            "step_reason": self.step_reason,
        }


@dataclass(frozen=True)
class AudioPlan:
    vo_strategy: str
    water_events: tuple[WaterEvent, ...]
    bgm_structure: tuple[str, ...]
    sound_bridges: tuple[SoundBridge, ...] = ()
    vo_events: tuple[VoEvent, ...] = ()
    bgm_sections: tuple[BgmSection, ...] = ()

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
        seen_vo: set[str] = set()
        for event in self.vo_events:
            if not isinstance(event, VoEvent):
                raise AudioPlanPolicyError("vo_events must contain VoEvent values")
            if event.vo_id in seen_vo:
                raise AudioPlanPolicyError(f"duplicate vo_id: {event.vo_id!r}")
            seen_vo.add(event.vo_id)
        seen_section: set[str] = set()
        for section in self.bgm_sections:
            if not isinstance(section, BgmSection):
                raise AudioPlanPolicyError("bgm_sections must contain BgmSection values")
            if section.section in seen_section:
                raise AudioPlanPolicyError(
                    f"bgm section {section.section!r} is described more than once"
                )
            seen_section.add(section.section)
        _assert_structural_bgm(self.bgm_structure)

    @property
    def required_vo(self) -> tuple[VoEvent, ...]:
        """Voice events that must be present in the mix."""

        return tuple(event for event in self.vo_events if event.required)

    @property
    def silent_slots(self) -> tuple[VoEvent, ...]:
        """Slots deliberately left without voice, each with a stated reason."""

        return tuple(event for event in self.vo_events if not event.required)

    @property
    def dry_shots(self) -> tuple[str, ...]:
        """Shots with no water evidence, which therefore carry no water sound."""

        return tuple(
            event.shot_id for event in self.water_events if not event.has_water_evidence
        )

    def as_dict(self) -> dict[str, object]:
        """Serialise to the ``audio_plan.v0`` instance shape.

        The document carries exactly the fields the schema declares. Module status is not
        part of an instance: the schema records it in its description and ``x-policy``, and
        ``IMPLEMENTATION`` remains importable. Emitting it here is what used to make
        ``as_dict()`` output unparseable by this module's own parser.
        """

        return {
            "schema_version": SCHEMA_VERSION,
            "vo_strategy": self.vo_strategy,
            "water_events": [event.as_dict() for event in self.water_events],
            "bgm_structure": list(self.bgm_structure),
            "sound_bridges": [bridge.as_dict() for bridge in self.sound_bridges],
            "vo_events": [event.as_dict() for event in self.vo_events],
            "bgm_sections": [section.as_dict() for section in self.bgm_sections],
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
    # The first five are required; the last two are the additive extension and are
    # optional, so a plan written before the extension still parses unchanged.
    required_keys = (
        "schema_version",
        "vo_strategy",
        "water_events",
        "bgm_structure",
        "sound_bridges",
    )
    optional_keys = ("vo_events", "bgm_sections")
    allowed = required_keys + optional_keys
    unknown = sorted(set(document) - set(allowed))
    missing = sorted(set(required_keys) - set(document))
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

    raw_vo = document.get("vo_events", [])
    if not isinstance(raw_vo, list):
        raise AudioPlanPolicyError("vo_events must be an array")
    vo_keys = ("vo_id", "purpose", "semantic_unit", "required", "silence_reason",
               "window_seconds")
    vo_events: list[VoEvent] = []
    for index, raw in enumerate(raw_vo):
        label = f"vo_events[{index}]"
        if not isinstance(raw, Mapping):
            raise AudioPlanPolicyError(f"{label} must be a JSON object")
        item_unknown = sorted(set(raw) - set(vo_keys))
        if item_unknown:
            raise AudioPlanPolicyError(
                f"{label} has unsupported key(s): {', '.join(item_unknown)}"
            )
        window = raw.get("window_seconds")
        vo_events.append(VoEvent(
            vo_id=raw.get("vo_id"),  # type: ignore[arg-type]
            purpose=raw.get("purpose"),  # type: ignore[arg-type]
            semantic_unit=raw.get("semantic_unit"),  # type: ignore[arg-type]
            required=raw.get("required", True),  # type: ignore[arg-type]
            silence_reason=raw.get("silence_reason"),  # type: ignore[arg-type]
            window_seconds=(tuple(window) if isinstance(window, list) and len(window) == 2
                            else None),  # type: ignore[arg-type]
        ))

    raw_sections = document.get("bgm_sections", [])
    if not isinstance(raw_sections, list):
        raise AudioPlanPolicyError("bgm_sections must be an array")
    section_keys = ("section", "intent", "transition", "transition_seconds", "step_reason")
    bgm_sections: list[BgmSection] = []
    for index, raw in enumerate(raw_sections):
        label = f"bgm_sections[{index}]"
        if not isinstance(raw, Mapping):
            raise AudioPlanPolicyError(f"{label} must be a JSON object")
        item_unknown = sorted(set(raw) - set(section_keys))
        if item_unknown:
            raise AudioPlanPolicyError(
                f"{label} has unsupported key(s): {', '.join(item_unknown)}"
            )
        bgm_sections.append(BgmSection(
            section=raw.get("section"),  # type: ignore[arg-type]
            intent=raw.get("intent"),  # type: ignore[arg-type]
            transition=raw.get("transition", DEFAULT_BGM_TRANSITION),  # type: ignore[arg-type]
            transition_seconds=raw.get("transition_seconds", 0.0),  # type: ignore[arg-type]
            step_reason=raw.get("step_reason"),  # type: ignore[arg-type]
        ))

    return AudioPlan(
        vo_strategy=document["vo_strategy"],  # type: ignore[arg-type]
        water_events=tuple(events),
        bgm_structure=tuple(raw_bgm),  # type: ignore[arg-type]
        sound_bridges=tuple(bridges),
        vo_events=tuple(vo_events),
        bgm_sections=tuple(bgm_sections),
    )
