"""Typography Art Direction — the Premium Minimal baseline, as enforceable rules.

What this module is
-------------------
The Third SKU's typography was designed by hand three times (V1, Work V2, then the
accepted "Premium Minimal A") before a human Producer locked A as the project baseline.
This module turns that locked decision into something the *next* SKU can reuse: a small set
of rules a job must satisfy, plus a controlled zone system that decides where text may sit.

The distinction the whole module exists to keep
-----------------------------------------------
**Art Direction Rules** generalise across SKUs. They are the constants in this file.

**Adaptive Parameters** do not. Font family, colours, sizes, exact coordinates, line breaks
and animation values are the *current implementation* of A on the Third SKU. They live in a
job-scoped :class:`ArtDirectionProfile`, never as module constants, because a parameter that
becomes a cross-SKU default is one SKU's art direction silently applied to another — the
same rule the rest of this repository already applies to geometry and audio.

What is deliberately NOT here
-----------------------------
No machine learning, no vision model, no template marketplace, no scoring. "Premium" is not
compressed into a 0-100 number; the reviewer reports named checks with evidence, and a human
judges. Free per-shot positioning is not representable at all: a layout must name a zone,
and the zone must come from this file's closed set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


#: The locked baseline. Recorded here because it is a governance fact, not a tunable.
ART_DIRECTION_BASELINE = "Typography Art Direction A v1"
BASELINE_STATUS = "LOCKED"

#: Two separate claims, and only one of them is settled. The *rules* generalise and are
#: locked. Exact reproduction of the approved A *pixels* is not claimed, because A's two
#: artifacts disagree about their own sizes (the ASS spec and the overlay renderer differ by
#: about 1.12x) and which one produced the accepted frames is unknown. Stated as constants
#: so the distinction is assertable rather than living only in prose.
ART_DIRECTION_RULES = "LOCKED"
REFERENCE_PIXEL_REPRODUCTION = "UNRESOLVED"

# --------------------------------------------------------------------------- roles

#: Narrative roles a typography event may declare. These are broader than the editorial
#: text roles in ``typography.TEXT_ROLES`` (hook/feature/cta) because the accepted A
#: treatment distinguishes a body *selling point* from general body text.
NARRATIVE_ROLES = ("HOOK", "BODY_SELLING_POINT", "CTA")

#: The role that carries the most position-consistency obligation.
BODY_ROLE = "BODY_SELLING_POINT"

# --------------------------------------------------------------------------- zones

#: A small, closed set. A layout names one of these; it cannot name arbitrary coordinates.
ZONE_NAMES = (
    "UPPER_LEFT",
    "UPPER_CENTER",
    "UPPER_RIGHT",
    "MID_LEFT",
    "MID_CENTER",
    "LOWER_LEFT",
)

#: Which zone a role prefers. The body default is the stability anchor: every body event
#: uses it unless that individual event has a real conflict.
DEFAULT_ZONE_FOR_ROLE = {
    "HOOK": "UPPER_LEFT",
    "BODY_SELLING_POINT": "UPPER_LEFT",
    "CTA": "UPPER_CENTER",
}

#: Ordered fallbacks. The order is part of the art direction: prefer staying in the upper
#: band, then move down only as far as necessary, and never leave the safe area.
FALLBACK_CHAIN_FOR_ROLE = {
    "HOOK": ("UPPER_CENTER", "MID_LEFT", "LOWER_LEFT"),
    "BODY_SELLING_POINT": ("MID_LEFT", "UPPER_RIGHT", "LOWER_LEFT"),
    "CTA": ("MID_CENTER", "UPPER_LEFT", "LOWER_LEFT"),
}


class TypographyArtDirectionError(ValueError):
    """Raised when a layout cannot be expressed inside the art direction."""


def _fraction(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypographyArtDirectionError(f"{label} must be a number")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise TypographyArtDirectionError(f"{label} must be within 0..1")
    return round(number, 6)


def _non_empty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypographyArtDirectionError(f"{label} must be a non-empty string")
    return value


def _words(lines: Iterable[str]) -> tuple[str, ...]:
    """The words of a text block, with line breaks and spacing normalised away.

    Line breaking is an open visual parameter, so text preservation is judged on the word
    sequence: the same words, in the same order, with nothing added or dropped.
    """

    return tuple(" ".join(str(line) for line in lines).split())


@dataclass(frozen=True)
class Rect:
    """A normalised rectangle. Everything spatial is normalised so it transfers."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        _fraction(self.x, "x")
        _fraction(self.y, "y")
        _fraction(self.width, "width")
        _fraction(self.height, "height")
        if self.width <= 0 or self.height <= 0:
            raise TypographyArtDirectionError("a rectangle must have a positive area")
        if self.x + self.width > 1.0 + 1e-9 or self.y + self.height > 1.0 + 1e-9:
            raise TypographyArtDirectionError("a rectangle must lie inside the canvas")

    @property
    def x1(self) -> float:
        return self.x + self.width

    @property
    def y1(self) -> float:
        return self.y + self.height

    def intersects(self, other: "Rect", *, tolerance: float = 0.0) -> bool:
        """True when the two rectangles share area. Touching edges do not count."""

        return (
            self.x + tolerance < other.x1
            and other.x + tolerance < self.x1
            and self.y + tolerance < other.y1
            and other.y + tolerance < self.y1
        )

    def pixels(self, canvas_width: int, canvas_height: int) -> tuple[int, int, int, int]:
        return (
            int(round(self.x * canvas_width)),
            int(round(self.y * canvas_height)),
            int(round(self.width * canvas_width)),
            int(round(self.height * canvas_height)),
        )


@dataclass(frozen=True)
class Zone:
    """A named band of the canvas that text may occupy."""

    name: str
    rect: Rect
    alignment: str

    def __post_init__(self) -> None:
        if self.name not in ZONE_NAMES:
            raise TypographyArtDirectionError(
                f"unknown zone {self.name!r}; expected one of: {', '.join(ZONE_NAMES)}"
            )
        if self.alignment not in ("left", "center"):
            raise TypographyArtDirectionError("alignment must be 'left' or 'center'")
        if self.name.endswith("_LEFT") and self.alignment != "left":
            raise TypographyArtDirectionError(f"{self.name} must be left aligned")
        if self.name.endswith("_CENTER") and self.alignment != "center":
            raise TypographyArtDirectionError(f"{self.name} must be centre aligned")


#: The shipped zone set. Bands, not points: text is anchored to a band so a longer line in
#: another language still lands in the same place.
ZONES: Mapping[str, Zone] = {
    "UPPER_LEFT": Zone("UPPER_LEFT", Rect(0.055, 0.085, 0.845, 0.115), "left"),
    "UPPER_CENTER": Zone("UPPER_CENTER", Rect(0.055, 0.085, 0.890, 0.115), "center"),
    "UPPER_RIGHT": Zone("UPPER_RIGHT", Rect(0.100, 0.085, 0.845, 0.115), "left"),
    "MID_LEFT": Zone("MID_LEFT", Rect(0.055, 0.300, 0.845, 0.115), "left"),
    "MID_CENTER": Zone("MID_CENTER", Rect(0.055, 0.300, 0.890, 0.115), "center"),
    "LOWER_LEFT": Zone("LOWER_LEFT", Rect(0.055, 0.560, 0.845, 0.115), "left"),
}


@dataclass(frozen=True)
class EvidenceRegion:
    """A part of the picture the typography must not cover.

    Supplied by the job from its own reconnaissance. This module never infers one: a
    made-up product region would make every overlap check meaningless.
    """

    label: str
    rect: Rect

    def __post_init__(self) -> None:
        _non_empty(self.label, "an evidence region needs a label")


#: Labels the reviewer treats as protected evidence, in the priority order the repository
#: already uses for text placement conflicts.


@dataclass(frozen=True)
class PlatformSafeZone:
    """The chrome a platform draws over the video, as insets plus an optional rail."""

    top: float = 0.055
    bottom: float = 0.145
    left: float = 0.035
    right: float = 0.035
    action_rail: Rect | None = None

    def keep_out(self) -> tuple[Rect, ...]:
        regions = [
            Rect(0.0, 0.0, 1.0, self.top),
            Rect(0.0, 1.0 - self.bottom, 1.0, self.bottom),
            Rect(0.0, 0.0, self.left, 1.0),
            Rect(1.0 - self.right, 0.0, self.right, 1.0),
        ]
        if self.action_rail is not None:
            regions.append(self.action_rail)
        return tuple(regions)


#: A portrait TikTok-shaped keep-out, used when a job states nothing. It is a *shape*, not
#: art direction, which is why a default is acceptable here and not for font or colour.
DEFAULT_PLATFORM_SAFE_ZONE = PlatformSafeZone()


@dataclass(frozen=True)
class TypographyEvent:
    """One on-screen text event, expressed inside the zone system."""

    event_id: str
    narrative_role: str
    text_lines: tuple[str, ...]
    start_seconds: float
    end_seconds: float
    zone_name: str
    emphasis_terms: tuple[str, ...] = ()
    background_plate: str = "NONE"
    motion: str = "FADE_AND_SETTLE"

    def __post_init__(self) -> None:
        _non_empty(self.event_id, "event_id")
        if self.narrative_role not in NARRATIVE_ROLES:
            raise TypographyArtDirectionError(
                f"narrative_role must be one of: {', '.join(NARRATIVE_ROLES)}"
            )
        if self.zone_name not in ZONE_NAMES:
            raise TypographyArtDirectionError(
                f"zone_name must be one of: {', '.join(ZONE_NAMES)}; free positioning is "
                "not representable"
            )
        if not self.text_lines:
            raise TypographyArtDirectionError("an event must carry at least one line")
        for index, line in enumerate(self.text_lines):
            _non_empty(line, f"text_lines[{index}]")
        if self.end_seconds <= self.start_seconds:
            raise TypographyArtDirectionError("an event must be a non-empty interval")
        if self.background_plate not in PLATE_KINDS:
            raise TypographyArtDirectionError(
                f"background_plate must be one of: {', '.join(PLATE_KINDS)}"
            )
        if self.motion not in MOTION_KINDS:
            raise TypographyArtDirectionError(
                f"motion must be one of: {', '.join(MOTION_KINDS)}"
            )


#: Permitted backing devices. A large dark information plate is what the premium minimal
#: direction exists to avoid, so it is nameable but reported.
PLATE_KINDS = ("NONE", "ACCENT_RULE", "LIGHT_SCRIM", "HEAVY_PLATE")

#: Motion vocabulary. Every entry serves reading; nothing here is decorative.
MOTION_KINDS = ("NONE", "FADE", "FADE_AND_SETTLE", "SETTLE")

#: How many words in one event may carry emphasis. A's reference profile emphasises one
#: keyword per line; more than two turns a line into decoration.
MAX_EMPHASIS_TERMS = 2


# --------------------------------------------------------------- zone selection


@dataclass(frozen=True)
class ZoneDecision:
    """Why an event ended up in the zone it did."""

    event_id: str
    narrative_role: str
    zone_name: str
    is_default: bool
    fallback_index: int
    conflicts: tuple[str, ...] = ()


def zone_conflicts(
    zone_name: str,
    *,
    evidence: Sequence[EvidenceRegion] = (),
    platform: PlatformSafeZone = DEFAULT_PLATFORM_SAFE_ZONE,
) -> tuple[str, ...]:
    """Every reason this zone is not usable, in a stable order.

    A zone conflicts when it covers protected evidence, or when it reaches into the
    chrome the platform draws over the video.
    """

    if zone_name not in ZONE_NAMES:
        raise TypographyArtDirectionError(f"unknown zone {zone_name!r}")
    rect = ZONES[zone_name].rect
    reasons: list[str] = []
    for region in evidence:
        if rect.intersects(region.rect):
            reasons.append(f"covers {region.label}")
    for index, keep_out in enumerate(platform.keep_out()):
        if rect.intersects(keep_out):
            reasons.append(f"enters platform keep-out region {index}")
    return tuple(reasons)


def select_zone(
    narrative_role: str,
    *,
    event_id: str = "",
    evidence: Sequence[EvidenceRegion] = (),
    platform: PlatformSafeZone = DEFAULT_PLATFORM_SAFE_ZONE,
    preferred_zone: str | None = None,
) -> ZoneDecision:
    """Choose a zone deterministically: default first, then the role's fallbacks.

    There is no searching. The default is used whenever it is safe, a fallback is used only
    when a real conflict exists, and if nothing fits the layout is refused rather than
    placed somewhere arbitrary.
    """

    if narrative_role not in NARRATIVE_ROLES:
        raise TypographyArtDirectionError(
            f"narrative_role must be one of: {', '.join(NARRATIVE_ROLES)}"
        )
    if preferred_zone is not None and preferred_zone not in ZONE_NAMES:
        raise TypographyArtDirectionError(f"unknown zone {preferred_zone!r}")

    default = DEFAULT_ZONE_FOR_ROLE[narrative_role]

    if preferred_zone is not None:
        conflicts = zone_conflicts(preferred_zone, evidence=evidence, platform=platform)
        if not conflicts:
            return ZoneDecision(event_id, narrative_role, preferred_zone,
                                preferred_zone == default,
                                _fallback_index(narrative_role, preferred_zone))

    conflicts = zone_conflicts(default, evidence=evidence, platform=platform)
    if not conflicts:
        return ZoneDecision(event_id, narrative_role, default, True, 0)

    for index, candidate in enumerate(FALLBACK_CHAIN_FOR_ROLE[narrative_role], start=1):
        reasons = zone_conflicts(candidate, evidence=evidence, platform=platform)
        if not reasons:
            return ZoneDecision(event_id, narrative_role, candidate, False, index,
                                conflicts)

    raise TypographyArtDirectionError(
        f"no zone is free of conflicts for {narrative_role}: default {default} "
        f"({', '.join(conflicts)}). The art direction does not permit placing text "
        "anywhere else; move the shot, the evidence or the event."
    )


def _fallback_index(narrative_role: str, zone_name: str) -> int:
    chain = FALLBACK_CHAIN_FOR_ROLE[narrative_role]
    return chain.index(zone_name) + 1 if zone_name in chain else 0


@dataclass(frozen=True)
class LayoutPlan:
    """Resolved events, plus WHY each one landed where it did."""

    events: tuple[TypographyEvent, ...]
    decisions: tuple[ZoneDecision, ...]

    def decision_for(self, event_id: str) -> ZoneDecision | None:
        return next((d for d in self.decisions if d.event_id == event_id), None)


def plan_layout(
    events: Sequence[TypographyEvent],
    *,
    evidence: Sequence[EvidenceRegion] = (),
    evidence_by_event: Mapping[str, Sequence[EvidenceRegion]] | None = None,
    platform: PlatformSafeZone = DEFAULT_PLATFORM_SAFE_ZONE,
) -> LayoutPlan:
    """Resolve every event's zone, keeping one visual anchor for the body.

    Body events inherit the zone the body has already established, so the body keeps a
    single anchor across the piece. A body event may still take a fallback — but only
    because *that* event has a real conflict, never because it was measured differently.

    Evidence differs from shot to shot, so ``evidence_by_event`` carries each event's own
    regions and takes precedence over the shared ``evidence`` list. Passing one global set
    would make a conflict in a single shot look like a conflict in all of them.
    """

    resolved: list[TypographyEvent] = []
    decisions: list[ZoneDecision] = []
    body_anchor: str | None = None
    per_event = evidence_by_event or {}

    for event in events:
        local = tuple(per_event.get(event.event_id, evidence))

        if event.narrative_role == BODY_ROLE and body_anchor is not None:
            if not zone_conflicts(body_anchor, evidence=local, platform=platform):
                resolved.append(_with_zone(event, body_anchor))
                decisions.append(ZoneDecision(
                    event.event_id, event.narrative_role, body_anchor,
                    body_anchor == DEFAULT_ZONE_FOR_ROLE[BODY_ROLE],
                    _fallback_index(BODY_ROLE, body_anchor),
                    ("inherits the established body anchor",)))
                continue

        decision = select_zone(event.narrative_role, event_id=event.event_id,
                               evidence=local, platform=platform)
        if event.narrative_role == BODY_ROLE and body_anchor is None:
            body_anchor = decision.zone_name
        resolved.append(_with_zone(event, decision.zone_name))
        decisions.append(decision)

    return LayoutPlan(tuple(resolved), tuple(decisions))


def _with_zone(event: TypographyEvent, zone_name: str) -> TypographyEvent:
    if event.zone_name == zone_name:
        return event
    return TypographyEvent(
        event_id=event.event_id, narrative_role=event.narrative_role,
        text_lines=event.text_lines, start_seconds=event.start_seconds,
        end_seconds=event.end_seconds, zone_name=zone_name,
        emphasis_terms=event.emphasis_terms, background_plate=event.background_plate,
        motion=event.motion,
    )


def body_anchor_zones(events: Sequence[TypographyEvent]) -> tuple[str, ...]:
    """The distinct zones body events occupy, in first-seen order."""

    seen: list[str] = []
    for event in events:
        if event.narrative_role == BODY_ROLE and event.zone_name not in seen:
            seen.append(event.zone_name)
    return tuple(seen)


# ---------------------------------------------------------------- job-scoped profile


@dataclass(frozen=True)
class ArtDirectionProfile:
    """One job's *parameters*. These are not rules and must not become module defaults.

    The rule set above is what generalises. Everything in here — font, colours, sizes,
    animation, and any zone geometry override — is A's current implementation on one SKU,
    and the next SKU is expected to state its own.
    """

    profile_id: str
    baseline: str
    status: str
    canvas_width: int
    canvas_height: int
    fps: int
    font_stack: tuple[str, ...]
    font_index: int | None = None
    warm_white: tuple[int, int, int, int] = (247, 243, 234, 255)
    accent: tuple[int, int, int, int] = (216, 183, 122, 255)
    stroke: tuple[int, int, int, int] = (16, 16, 16, 190)
    emphasis_sizes: Mapping[str, int] = field(default_factory=dict)
    zone_overrides: Mapping[str, Rect] = field(default_factory=dict)
    platform: PlatformSafeZone = DEFAULT_PLATFORM_SAFE_ZONE

    def __post_init__(self) -> None:
        _non_empty(self.profile_id, "profile_id")
        if not self.font_stack:
            raise TypographyArtDirectionError("a profile must state its own font stack")
        if self.canvas_width <= 0 or self.canvas_height <= 0:
            raise TypographyArtDirectionError("canvas must be positive")
        for name in self.zone_overrides:
            if name not in ZONE_NAMES:
                raise TypographyArtDirectionError(f"unknown zone override {name!r}")


    def zones(self) -> Mapping[str, Zone]:
        merged = dict(ZONES)
        for name, rect in self.zone_overrides.items():
            merged[name] = Zone(name, rect, ZONES[name].alignment)
        return merged

    def zone_rect(self, zone_name: str) -> Rect:
        return self.zones()[zone_name].rect


def profile_from_document(document: object) -> ArtDirectionProfile:
    """Load a job's profile. Missing art direction is refused, never defaulted.

    ``font_stack`` and ``font_index`` may be stated at the top level or nested under a
    ``font`` block, because a profile reads better grouped by family/weight while the
    dataclass wants a flat stack. Both spellings are accepted; neither is defaulted.
    """

    if not isinstance(document, Mapping):
        raise TypographyArtDirectionError("a profile must be a mapping")
    if "profile_id" not in document:
        raise TypographyArtDirectionError("a profile must state 'profile_id'")
    if "canvas" not in document:
        raise TypographyArtDirectionError("a profile must state 'canvas'")
    font_block = document.get("font") or {}
    if not isinstance(font_block, Mapping):
        raise TypographyArtDirectionError("font must be a mapping")
    stack = document.get("font_stack", font_block.get("font_stack"))
    if not stack:
        raise TypographyArtDirectionError("a profile must state 'font_stack'")
    index = document.get("font_index", font_block.get("font_index"))
    canvas = document["canvas"]
    if not isinstance(canvas, Mapping):
        raise TypographyArtDirectionError("canvas must be a mapping")
    colours = document.get("colours") or {}
    overrides = {
        name: Rect(**rect) for name, rect in (document.get("zone_overrides") or {}).items()
    }
    return ArtDirectionProfile(
        profile_id=str(document["profile_id"]),
        baseline=str(document.get("baseline", ART_DIRECTION_BASELINE)),
        status=str(document.get("status", BASELINE_STATUS)),
        canvas_width=int(canvas["width"]), canvas_height=int(canvas["height"]),
        fps=int(canvas.get("fps", 30)),
        font_stack=tuple(str(entry) for entry in stack),
        font_index=(None if index is None else int(index)),
        warm_white=tuple(colours.get("warm_white", (247, 243, 234, 255))),  # type: ignore[arg-type]
        accent=tuple(colours.get("accent", (216, 183, 122, 255))),  # type: ignore[arg-type]
        stroke=tuple(colours.get("stroke", (16, 16, 16, 190))),  # type: ignore[arg-type]
        emphasis_sizes=dict(document.get("emphasis_sizes") or {}),
        zone_overrides=overrides,
    )


# ------------------------------------------------------------------- reviewer


@dataclass(frozen=True)
class TypographyFinding:
    """One reviewer result. A named check with evidence — never a score."""

    check: str
    severity: str
    detail: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in ("PASS", "WARNING", "FAIL"):
            raise TypographyArtDirectionError("severity must be PASS, WARNING or FAIL")


#: The checks a typography review must report, in order.
REVIEWER_CHECKS = (
    "text_preserved",
    "safe_margin",
    "platform_safe_zone",
    "clipping",
    "product_overlap",
    "action_overlap",
    "evidence_overlap",
    "role_hierarchy",
    "body_position_consistency",
    "cta_visibility",
    "background_plate",
    "decorative_elements",
    "motion",
    "mobile_readability",
)

#: Minimum text height, as a fraction of canvas height, for legibility at phone scale.
MIN_READABLE_HEIGHT_FRACTION = 0.024

#: A plate covering more than this share of the canvas is no longer "restrained".


def review_typography(
    events: Sequence[TypographyEvent],
    *,
    profile: ArtDirectionProfile,
    locked_lines: Mapping[str, Sequence[str]] | None = None,
    evidence: Sequence[EvidenceRegion] = (),
    measured_line_heights: Mapping[str, float] | None = None,
    decisions: Sequence[ZoneDecision] = (),
) -> tuple[TypographyFinding, ...]:
    """Report the named checks. Warnings and evidence, not a score."""

    findings: list[TypographyFinding] = []
    if not events:
        return (TypographyFinding("text_preserved", "FAIL", "no events to review"),)

    # 1. locked text unchanged.
    #    Compared as a WORD SEQUENCE, not as a line tuple: the brief lists line breaks as an
    #    open visual parameter, and the accepted A treatment re-breaks the approved lines
    #    ("KOTORAN KULIT" / "TERANGKAT" where V1 had one line). Re-breaking is layout;
    #    changing, adding, dropping or reordering a word is not.
    #
    #    This check is ALWAYS reported. A reviewer that silently omits a check it could not
    #    run is worse than one that reports it as unverified, so a missing locked reference
    #    is a WARNING rather than an absent line.
    if locked_lines is None:
        findings.append(TypographyFinding(
            "text_preserved", "WARNING",
            "no locked wording was supplied, so text preservation was not verified",
            {"verified": False}))
    else:
        drifted = [
            event.event_id for event in events
            if event.event_id in locked_lines
            and _words(locked_lines[event.event_id]) != _words(event.text_lines)
        ]
        findings.append(TypographyFinding(
            "text_preserved", "FAIL" if drifted else "PASS",
            "every event carries its locked wording" if not drifted
            else f"{len(drifted)} event(s) changed the locked wording",
            {"drifted": drifted, "verified": True,
             "compared": "word sequence; line breaks are an open visual parameter"}))

    # 2/3/4. safe margin, platform zone, clipping
    margin_fail, platform_fail, clip_fail = [], [], []
    for event in events:
        rect = profile.zone_rect(event.zone_name)
        pixels = rect.pixels(profile.canvas_width, profile.canvas_height)
        if pixels[0] <= 0 or pixels[1] <= 0 or (
            pixels[0] + pixels[2] >= profile.canvas_width
            or pixels[1] + pixels[3] >= profile.canvas_height
        ):
            clip_fail.append(event.event_id)
        if pixels[0] < profile.canvas_width * 0.03 or pixels[2] < profile.canvas_width * 0.5:
            margin_fail.append(event.event_id)
        if any(rect.intersects(k) for k in profile.platform.keep_out()):
            platform_fail.append(event.event_id)
    findings.append(TypographyFinding(
        "safe_margin", "FAIL" if margin_fail else "PASS",
        "every zone keeps a usable side margin" if not margin_fail
        else f"{len(margin_fail)} event(s) have an unusable side margin",
        {"events": margin_fail}))
    findings.append(TypographyFinding(
        "platform_safe_zone", "FAIL" if platform_fail else "PASS",
        "no zone reaches the platform chrome" if not platform_fail
        else f"{len(platform_fail)} event(s) reach the platform chrome",
        {"events": platform_fail}))
    findings.append(TypographyFinding(
        "clipping", "FAIL" if clip_fail else "PASS",
        "no zone runs off the canvas" if not clip_fail
        else f"{len(clip_fail)} event(s) run off the canvas", {"events": clip_fail}))

    # 5/6/7. overlap with protected evidence, by label
    def overlaps_for(labels: Sequence[str]) -> list[str]:
        hits: list[str] = []
        for event in events:
            rect = profile.zone_rect(event.zone_name)
            if any(rect.intersects(r.rect) for r in evidence if r.label in labels):
                hits.append(event.event_id)
        return hits

    for check, labels, what in (
        ("product_overlap", ("product",), "the product"),
        ("action_overlap", ("hand", "action"), "a hand or an action"),
        ("evidence_overlap", ("result", "evidence"), "the result evidence"),
    ):
        hits = overlaps_for(labels)
        findings.append(TypographyFinding(
            check, "FAIL" if hits else "PASS",
            f"no zone covers {what}" if not hits else f"{len(hits)} event(s) cover {what}",
            {"events": hits, "labels": list(labels)}))

    # 8. role hierarchy: HOOK and CTA may outrank BODY, but BODY must not outrank them
    emphasis = [
        event for event in events
        if event.narrative_role in ("HOOK", "CTA") and not event.emphasis_terms
    ]
    findings.append(TypographyFinding(
        "role_hierarchy", "WARNING" if emphasis else "PASS",
        "hook and CTA carry their own emphasis" if not emphasis
        else f"{len(emphasis)} event(s) carry a leading role with no emphasis term",
        {"events": [event.event_id for event in emphasis]}))

    # 9. body position consistency.
    #    A single anchor PASSes. Differing anchors are a WARNING when every deviation is
    #    recorded as conflict-driven — the brief allows a limited fallback on a real
    #    conflict — and a FAIL when a body event moved for no recorded reason, because that
    #    is the per-shot drift the baseline forbids.
    anchors = body_anchor_zones(events)
    unjustified: list[str] = []
    if len(anchors) > 1:
        by_id = {d.event_id: d for d in decisions}
        for event in events:
            if event.narrative_role != BODY_ROLE:
                continue
            if event.zone_name == anchors[0]:
                continue
            decision = by_id.get(event.event_id)
            if decision is None or not decision.conflicts:
                unjustified.append(event.event_id)
    if not anchors:
        severity, detail = "PASS", "no body events declared"
    elif len(anchors) == 1:
        severity, detail = "PASS", f"every body event uses {anchors[0]}"
    elif unjustified:
        severity = "FAIL"
        detail = (f"body events moved without a recorded conflict: "
                  f"{', '.join(unjustified)}")
    else:
        severity = "WARNING"
        detail = (f"body uses {len(anchors)} zones ({', '.join(anchors)}) and every "
                  "deviation is conflict-driven")
    findings.append(TypographyFinding(
        "body_position_consistency", severity, detail,
        {"zones": list(anchors), "unjustified": unjustified}))

    # 10. CTA visibility: the CTA must exist, be last, and hold long enough to read
    ctas = [event for event in events if event.narrative_role == "CTA"]
    problems: list[str] = []
    if not ctas:
        problems.append("no CTA event")
    else:
        last = max(events, key=lambda e: e.end_seconds)
        if last.narrative_role != "CTA":
            problems.append(f"the last event is {last.narrative_role}, not the CTA")
        for cta in ctas:
            if round(cta.end_seconds - cta.start_seconds, 3) < 1.5:
                problems.append(f"{cta.event_id} holds under 1.5 s")
    findings.append(TypographyFinding(
        "cta_visibility", "FAIL" if problems else "PASS",
        "the CTA is present, last and readable" if not problems else "; ".join(problems),
        {"cta_events": [event.event_id for event in ctas]}))

    # 11. background plate restraint
    heavy = [event.event_id for event in events if event.background_plate == "HEAVY_PLATE"]
    findings.append(TypographyFinding(
        "background_plate", "WARNING" if heavy else "PASS",
        "no heavy information plate is used" if not heavy
        else f"{len(heavy)} event(s) use a heavy dark plate, which the baseline avoids",
        {"events": heavy}))

    # 12. decorative excess
    over_emphasised = [
        event.event_id for event in events
        if len(event.emphasis_terms) > MAX_EMPHASIS_TERMS
    ]
    findings.append(TypographyFinding(
        "decorative_elements", "WARNING" if over_emphasised else "PASS",
        f"at most {MAX_EMPHASIS_TERMS} emphasis terms per event" if not over_emphasised
        else f"{len(over_emphasised)} event(s) emphasise more than {MAX_EMPHASIS_TERMS} terms",
        {"events": over_emphasised}))

    # 13. motion restraint
    findings.append(TypographyFinding(
        "motion", "PASS",
        "every event uses a reading-only motion",
        {"motions": sorted({event.motion for event in events})}))

    # 14. mobile readability
    if measured_line_heights:
        small = [
            event_id for event_id, height in measured_line_heights.items()
            if height < profile.canvas_height * MIN_READABLE_HEIGHT_FRACTION
        ]
    else:
        small = []
    findings.append(TypographyFinding(
        "mobile_readability", "WARNING" if small else "PASS",
        "no measured line falls below the phone-scale floor" if not small
        else f"{len(small)} line(s) fall below the phone-scale floor",
        {"events": small,
         "min_height_fraction": MIN_READABLE_HEIGHT_FRACTION,
         "measured": bool(measured_line_heights)}))

    return tuple(findings)


def summarise(findings: Sequence[TypographyFinding]) -> dict[str, Any]:
    """Counts by severity. Deliberately no aggregate score."""

    return {
        "checks": len(findings),
        "pass": sum(1 for f in findings if f.severity == "PASS"),
        "warning": sum(1 for f in findings if f.severity == "WARNING"),
        "fail": sum(1 for f in findings if f.severity == "FAIL"),
        "blocking": [f.check for f in findings if f.severity == "FAIL"],
        "note": ("named checks with evidence; there is no 0-100 typography score, because "
                 "'premium' is not a measurable quantity"),
    }

__all__ = [
    "ART_DIRECTION_BASELINE",
    "ART_DIRECTION_RULES",
    "REFERENCE_PIXEL_REPRODUCTION",
    "ArtDirectionProfile",
    "BASELINE_STATUS",
    "BODY_ROLE",
    "DEFAULT_PLATFORM_SAFE_ZONE",
    "DEFAULT_ZONE_FOR_ROLE",
    "FALLBACK_CHAIN_FOR_ROLE",
    "MAX_EMPHASIS_TERMS",
    "MIN_READABLE_HEIGHT_FRACTION",
    "MOTION_KINDS",
    "NARRATIVE_ROLES",
    "PLATE_KINDS",
    "REVIEWER_CHECKS",
    "Rect",
    "TypographyArtDirectionError",
    "TypographyEvent",
    "TypographyFinding",
    "Zone",
    "ZoneDecision",
    "ZONES",
    "ZONE_NAMES",
    "body_anchor_zones",
    "LayoutPlan",
    "plan_layout",
    "profile_from_document",
    "review_typography",
    "select_zone",
    "summarise",
    "zone_conflicts",
]
