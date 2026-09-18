"""Shot-aware Typography policy.

Typography in AI-AutoCut is editorial emphasis, not subtitle delivery. The
policy below encodes the rules that survived review:

* every shot is judged against the real objects in it before text is placed;
* product legibility outranks text legibility;
* motion is minimal, and a short list of decorative effects is refused;
* one Beat carries at most one primary text event.

The *policy* is validated here. Automatic placement is **NOT_IMPLEMENTED**:
there is no image analysis in this module and no text is rendered by it.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence


SCHEMA_VERSION = "typography_policy.v0"

#: Explicit implementation state. The policy is trustworthy; the solver is not
#: written yet, and this constant is the honest place to say so.
POLICY_STATUS = "POLICY_VALIDATED_IMPLEMENTATION_PENDING"
PLACEMENT_IMPLEMENTATION = "NOT_IMPLEMENTED"

#: Default visual direction. Premium minimal motion inside a clean product
#: commercial look.
DEFAULT_VISUAL_DIRECTION = "CLEAN_PRODUCT_COMMERCIAL"

#: Editorial text roles. Voice-over subtitles are deliberately absent: burned
#: subtitles that duplicate the VO are not an accepted text role.
TEXT_ROLES = ("hook", "feature", "cta")

#: What a shot must be inspected for before text is placed.
PLACEMENT_CONSIDERATIONS = (
    "product",
    "face",
    "hand",
    "action",
    "water",
    "important_object",
    "avoid_zones",
    "negative_space",
    "visual_density",
    "text_role",
    "safe_area",
    "mobile_preview",
)

#: The subset that must be declared for any releasable text plan. Product and
#: action dominate; text must be checked at phone scale, not only on a monitor.
MINIMUM_CONSIDERATIONS = ("product", "action", "safe_area", "mobile_preview")

#: Priority for resolving a conflict between competing needs, highest first.
#: Text never displaces the product, and decoration never displaces text.
TEXT_PRIORITY = ("product", "action", "text", "decoration")

#: Motion vocabulary that stays premium and minimal.
ALLOWED_MOTION = ("fade", "micro_motion", "easing", "stagger")

#: Decorative motion that is refused by default.
FORBIDDEN_MOTION = (
    "bounce",
    "rotation",
    "glow",
    "particles",
    "arrows",
    "trajectory_lines",
    "stickers",
)

#: At most one emphasized term per event, so a whole line is never dyed.
MAX_EMPHASIS_TERMS = 1

_EVENT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class TypographyPolicyError(ValueError):
    """Raised when a text plan violates the shot-aware typography policy."""


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypographyPolicyError(f"{label} must be a non-empty string")
    return value


def _subset_of(values: Sequence[object], allowed: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypographyPolicyError(f"{label} must be a sequence")
    resolved: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or value not in allowed:
            raise TypographyPolicyError(
                f"{label}[{index}] must be one of: {', '.join(allowed)}"
            )
        if value in resolved:
            raise TypographyPolicyError(f"{label} contains a duplicate entry")
        resolved.append(value)
    return tuple(resolved)


@dataclass(frozen=True)
class TextEvent:
    event_id: str
    role: str
    lines: tuple[str, ...]
    motion: str
    considered_zones: tuple[str, ...]
    emphasis_terms: tuple[str, ...] = ()
    safe_area_verified: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.event_id, str)
            or _EVENT_ID_PATTERN.fullmatch(self.event_id) is None
        ):
            raise TypographyPolicyError("event_id is malformed")
        if self.role not in TEXT_ROLES:
            raise TypographyPolicyError(
                f"role must be one of: {', '.join(TEXT_ROLES)}; burned voice-over "
                "subtitles are not an accepted text role"
            )
        if not self.lines:
            raise TypographyPolicyError("lines must not be empty")
        for index, line in enumerate(self.lines):
            _text(line, f"lines[{index}]")
        if self.motion in FORBIDDEN_MOTION:
            raise TypographyPolicyError(
                f"motion {self.motion!r} is refused by the default visual direction"
            )
        if self.motion not in ALLOWED_MOTION:
            raise TypographyPolicyError(
                f"motion must be one of: {', '.join(ALLOWED_MOTION)}"
            )
        zones = _subset_of(self.considered_zones, PLACEMENT_CONSIDERATIONS, "considered_zones")
        missing = [zone for zone in MINIMUM_CONSIDERATIONS if zone not in zones]
        if missing:
            raise TypographyPolicyError(
                "considered_zones must declare the minimum set; missing: "
                + ", ".join(missing)
            )
        _subset_of(self.emphasis_terms, tuple(self.emphasis_terms), "emphasis_terms")
        if len(self.emphasis_terms) > MAX_EMPHASIS_TERMS:
            raise TypographyPolicyError(
                f"at most {MAX_EMPHASIS_TERMS} emphasized term per text event"
            )
        if not isinstance(self.safe_area_verified, bool):
            raise TypographyPolicyError("safe_area_verified must be a boolean")

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "role": self.role,
            "lines": list(self.lines),
            "motion": self.motion,
            "considered_zones": list(self.considered_zones),
            "emphasis_terms": list(self.emphasis_terms),
            "safe_area_verified": self.safe_area_verified,
        }


@dataclass(frozen=True)
class TypographyPlan:
    visual_direction: str
    events: tuple[TextEvent, ...]

    def __post_init__(self) -> None:
        if self.visual_direction != DEFAULT_VISUAL_DIRECTION:
            raise TypographyPolicyError(
                f"visual_direction must be {DEFAULT_VISUAL_DIRECTION!r} for this policy"
            )
        if not isinstance(self.events, tuple) or not self.events:
            raise TypographyPolicyError("events must be a non-empty tuple")
        seen: set[str] = set()
        for event in self.events:
            if not isinstance(event, TextEvent):
                raise TypographyPolicyError("events must contain TextEvent values")
            if event.event_id in seen:
                raise TypographyPolicyError(f"duplicate event_id: {event.event_id!r}")
            seen.add(event.event_id)
        roles = [event.role for event in self.events]
        if len(roles) != len(set(roles)):
            raise TypographyPolicyError(
                "at most one primary text event per role; a Beat keeps one text event"
            )

    @property
    def status(self) -> str:
        return POLICY_STATUS

    def unreleasable_events(self) -> tuple[str, ...]:
        """Return events that are not yet safe to release."""

        return tuple(
            event.event_id for event in self.events if not event.safe_area_verified
        )

    def as_dict(self) -> dict[str, object]:
        """Serialise to the ``typography_policy.v0`` instance shape.

        The document carries exactly the fields the schema declares. Module status is
        not part of an instance: ``POLICY_STATUS`` and ``PLACEMENT_IMPLEMENTATION`` stay
        importable and remain recorded in the schema's description, and ``self.status``
        still reports it. Emitting them here is what used to make ``as_dict()`` output
        unparseable by this module's own parser.
        """

        return {
            "schema_version": SCHEMA_VERSION,
            "visual_direction": self.visual_direction,
            "events": [event.as_dict() for event in self.events],
        }


def parse_typography_plan(document: object) -> TypographyPlan:
    if not isinstance(document, Mapping):
        raise TypographyPolicyError("typography plan must be a JSON object")
    allowed = ("schema_version", "visual_direction", "events")
    unknown = sorted(set(document) - set(allowed))
    missing = sorted(set(allowed) - set(document))
    if unknown:
        raise TypographyPolicyError(
            f"typography plan has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise TypographyPolicyError(
            f"typography plan is missing required key(s): {', '.join(missing)}"
        )
    if document["schema_version"] != SCHEMA_VERSION:
        raise TypographyPolicyError(f"schema_version must be {SCHEMA_VERSION!r}")

    raw_events = document["events"]
    if not isinstance(raw_events, list):
        raise TypographyPolicyError("events must be a JSON array")
    event_keys = (
        "event_id",
        "role",
        "lines",
        "motion",
        "considered_zones",
        "emphasis_terms",
        "safe_area_verified",
    )
    events: list[TextEvent] = []
    for index, raw in enumerate(raw_events):
        label = f"events[{index}]"
        if not isinstance(raw, Mapping):
            raise TypographyPolicyError(f"{label} must be a JSON object")
        item_unknown = sorted(set(raw) - set(event_keys))
        item_missing = sorted(set(event_keys) - set(raw))
        if item_unknown:
            raise TypographyPolicyError(
                f"{label} has unsupported key(s): {', '.join(item_unknown)}"
            )
        if item_missing:
            raise TypographyPolicyError(
                f"{label} is missing required key(s): {', '.join(item_missing)}"
            )
        lines = raw["lines"]
        zones = raw["considered_zones"]
        emphasis = raw["emphasis_terms"]
        if not isinstance(lines, list) or not isinstance(zones, list) or not isinstance(emphasis, list):
            raise TypographyPolicyError(f"{label} list field is malformed")
        events.append(
            TextEvent(
                event_id=raw["event_id"],  # type: ignore[arg-type]
                role=raw["role"],  # type: ignore[arg-type]
                lines=tuple(lines),  # type: ignore[arg-type]
                motion=raw["motion"],  # type: ignore[arg-type]
                considered_zones=tuple(zones),  # type: ignore[arg-type]
                emphasis_terms=tuple(emphasis),  # type: ignore[arg-type]
                safe_area_verified=raw["safe_area_verified"],  # type: ignore[arg-type]
            )
        )
    return TypographyPlan(
        visual_direction=document["visual_direction"],  # type: ignore[arg-type]
        events=tuple(events),
    )


def priority_rank(need: str) -> int:
    """Return the conflict-priority rank of one competing need, lowest first."""

    if need not in TEXT_PRIORITY:
        raise TypographyPolicyError(
            f"need must be one of: {', '.join(TEXT_PRIORITY)}"
        )
    return TEXT_PRIORITY.index(need)


def resolve_conflict(first: str, second: str) -> str:
    """Return whichever need wins when two compete for the same area."""

    return first if priority_rank(first) <= priority_rank(second) else second


def assert_placement_implemented() -> None:
    """Guard for callers that expect automatic placement to exist."""

    raise NotImplementedError(
        "automatic shot-aware text placement is NOT_IMPLEMENTED; the policy is "
        "validated, but no solver produces positions yet"
    )
