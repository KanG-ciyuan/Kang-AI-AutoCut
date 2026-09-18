"""C-02 — Commercial narration coverage.

Post-blind learning from the Cushion Puff blind run. Scope is **commercial advertising only**.

The defect this module corrects:

    The system de-duplicated by deleting a FUNCTION, rather than by de-duplicating
    within functions.

Typography summarises; voice explains. Removing the voice because a Title existed removed the
*explanation* function from those scenes, and produced 7.07 seconds of consecutive silence —
43.5% of a conversion-oriented advertisement — of which only a justified hero breath was
defensible.

Three things this module deliberately does **not** do:

* it does not produce a numeric score, a VO percentage, a minimum duration or a maximum silence;
* it does not write, suggest or generate copy — it can say a unit *needs* an explanation, and it
  can say the evidence does not support one, but it never supplies the words;
* it does not create a channel-per-unit rule. Channels **collaborate**.

The unit of analysis is the existing :class:`~ai_autocut.audio_plan.VoEvent`, so a commercial
plan that goes through the frozen audio contract is checked without any new schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .audio_plan import VoEvent
from .review import Finding, deterministic_finding

#: The dimension these findings belong to. The existing one, not a new one.
REVIEW_DIMENSION = "commercial_effectiveness"


class NarrationCoverageError(ValueError):
    """Raised when a commercial narration plan cannot be assessed safely."""


#: Why a voice line exists. Small on purpose: if a line cannot name its role, that is a signal
#: it may not need to exist.
VO_ROLES = (
    "HOOK",
    "CONTEXT",
    "DEMONSTRATION_EXPLANATION",
    "SELLING_POINT_EXPANSION",
    "TRANSITION",
    "DESIRE_RELEVANCE",
    "CTA",
)

#: Roles that carry the selling narrative forward. A piece whose only voice is a CTA has a
#: voice track, but no narration.
CARRYING_ROLES = (
    "HOOK",
    "CONTEXT",
    "DEMONSTRATION_EXPLANATION",
    "SELLING_POINT_EXPANSION",
    "TRANSITION",
    "DESIRE_RELEVANCE",
)

#: Reasons that justify a deliberate silence.
#:
#: Two frozen documents name two of these concepts slightly differently — the principles list
#: `PRODUCTION_SOUND_IMPORTANT` and `CONTRAST_BEFORE_CTA`, while the implementation
#: specification names `PRODUCTION_SOUND_CARRIES_ACTION` and `DELIBERATE_PRE_CTA_CONTRAST`.
#: Both spellings are accepted, because the vocabulary is explicitly not a closed enum and a
#: valid plan must not fail on a naming difference between two of its own authorities.
JUSTIFIED_SILENCE_REASONS = (
    "HERO_VISUAL_CARRIES_MESSAGE",
    "ACTION_RESULT_COMPREHENSION",
    "EMOTIONAL_EMPHASIS",
    "PRODUCT_DESIRE_MOMENT",
    "PRODUCTION_SOUND_IMPORTANT",
    "PRODUCTION_SOUND_CARRIES_ACTION",
    "BGM_TRANSITION",
    "CONTRAST_BEFORE_CTA",
    "DELIBERATE_PRE_CTA_CONTRAST",
)

#: Reasons that do **not** justify silence on their own.
#:
#: A Title summarising a feature says nothing about whether the scene still needs someone to
#: explain why that feature matters. This was the Cushion Puff defect in one line.
WEAK_SILENCE_REASONS = ("TITLE_ALREADY_EXISTS",)

#: The old rule, explicitly rejected.
REJECTED_RULE = "ONE_INFORMATION_CHANNEL_PER_UNIT"


@dataclass(frozen=True)
class CommercialUnit:
    """One commercial unit, and what each channel is doing in it.

    The fields describe *functions*, not content. Nothing here carries copy.
    """

    unit_id: str
    start_seconds: float
    end_seconds: float
    visual_self_explanatory: bool
    carries_new_commercial_information: bool
    has_title: bool
    vo: VoEvent | None = None
    #: False when the voice merely restates the Title's summary. Only meaningful when both
    #: channels are present.
    vo_adds_function_beyond_title: bool = True
    #: False when the product facts and visual evidence cannot support an explanation for this
    #: unit. The coverage check then reports a gap rather than filling it.
    explanation_supported: bool = True

    def __post_init__(self) -> None:
        if not self.unit_id:
            raise NarrationCoverageError("a commercial unit needs an id")
        if self.end_seconds <= self.start_seconds:
            raise NarrationCoverageError(
                f"unit {self.unit_id!r} must be a non-empty interval"
            )
        if self.vo is not None and not isinstance(self.vo, VoEvent):
            raise NarrationCoverageError(
                f"unit {self.unit_id!r} must carry a VoEvent or nothing"
            )

    @property
    def duration_seconds(self) -> float:
        return round(self.end_seconds - self.start_seconds, 4)

    @property
    def has_vo(self) -> bool:
        return self.vo is not None and self.vo.required

    @property
    def is_silent(self) -> bool:
        return not self.has_vo

    @property
    def silence_reason(self) -> str | None:
        return None if self.vo is None else self.vo.silence_reason

    @property
    def vo_role(self) -> str | None:
        return None if self.vo is None else self.vo.purpose


@dataclass(frozen=True)
class CoverageReport:
    """The outcome of one coverage assessment."""

    findings: tuple[Finding, ...]
    units: tuple[CommercialUnit, ...]

    @property
    def blocking(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.blocks_release)

    @property
    def verdict(self) -> str:
        if any(f.severity == "CRITICAL" for f in self.findings):
            return "FAIL"
        if any(f.severity == "FAIL" for f in self.findings):
            return "FAIL"
        if any(f.severity == "WEAK" for f in self.findings):
            return "WARNING"
        return "PASS"

    @property
    def silent_units(self) -> tuple[str, ...]:
        return tuple(u.unit_id for u in self.units if u.is_silent)

    @property
    def spoken_units(self) -> tuple[str, ...]:
        return tuple(u.unit_id for u in self.units if u.has_vo)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "commercial_narration_coverage.v1",
            "dimension": REVIEW_DIMENSION,
            "verdict": self.verdict,
            "spoken_units": list(self.spoken_units),
            "silent_units": list(self.silent_units),
            "findings": [f.as_dict() for f in self.findings],
        }


def _finding(severity: str, claim: str, measured: object) -> Finding:
    return deterministic_finding(REVIEW_DIMENSION, severity, claim=claim, measured=measured)


def _is_dead_zone(unit: CommercialUnit) -> bool:
    """The four frozen conditions. No seconds threshold appears anywhere in this test."""

    return (
        not unit.visual_self_explanatory
        and not unit.carries_new_commercial_information
        and unit.is_silent
        and not _silence_is_justified(unit)
    )


def _silence_is_justified(unit: CommercialUnit) -> bool:
    reason = unit.silence_reason
    return bool(reason) and reason in JUSTIFIED_SILENCE_REASONS


def _silence_is_weak(unit: CommercialUnit) -> bool:
    reason = unit.silence_reason
    return bool(reason) and reason in WEAK_SILENCE_REASONS


def assess_narration_coverage(units: Sequence[CommercialUnit]) -> CoverageReport:
    """Assess whether the narration carries the selling story.

    Qualitative by construction: no score, no percentage, no threshold.
    """

    if not units:
        raise NarrationCoverageError("a coverage assessment needs at least one unit")
    findings: list[Finding] = []
    ordered = sorted(units, key=lambda u: u.start_seconds)

    # --- Q4 / Q6: silence must carry a real reason -------------------------------------
    weak, unjustified = [], []
    for unit in ordered:
        if not unit.is_silent:
            continue
        if _silence_is_weak(unit):
            weak.append(unit.unit_id)
        elif not unit.silence_reason:
            unjustified.append(unit.unit_id)
        elif unit.silence_reason not in JUSTIFIED_SILENCE_REASONS:
            # An unrecognised reason is not a crash. It is a reason a human should read.
            findings.append(_finding(
                "WEAK",
                f"unit {unit.unit_id} is silent for a reason outside the justified vocabulary",
                f"silence_reason={unit.silence_reason!r}"))
    if weak:
        findings.append(_finding(
            "FAIL",
            "a Title existing was treated as sufficient reason for silence; a Title summarises "
            "a feature and does not establish that the scene needs no explanation",
            f"{len(weak)} unit(s): {', '.join(weak)}"))
    if unjustified:
        findings.append(_finding(
            "FAIL",
            "a silent commercial unit states no reason for being silent",
            f"{len(unjustified)} unit(s): {', '.join(unjustified)}"))

    # --- Q1: does the voice actually carry the narrative? ------------------------------
    carrying = [u for u in ordered if u.has_vo and u.vo_role in CARRYING_ROLES]
    if not carrying:
        findings.append(_finding(
            "FAIL",
            "the voice does not carry the selling narrative: no unit carries a role that "
            "advances it",
            f"roles present={[u.vo_role for u in ordered if u.has_vo] or 'none'}"))

    # --- Q2: important scenes under-explained ------------------------------------------
    #
    # Note what is deliberately NOT required here: `visual_self_explanatory`. A self-explanatory
    # visual removes the need to *describe* the scene; it does not remove the need to *explain*
    # why the scene matters. Requiring it would import the old logic this whole correction
    # exists to remove.
    under = [
        u.unit_id for u in ordered
        if u.carries_new_commercial_information
        and u.is_silent
        and not _silence_is_justified(u)
    ]
    if under:
        findings.append(_finding(
            "FAIL",
            "scenes carrying commercial weight have no explanation: the voice is absent and "
            "the silence is not justified, so the selling point is stated by no channel that "
            "can expand it",
            f"{len(under)} unit(s): {', '.join(under)}"))

    # --- Q3: unjustified narrative dead zones ------------------------------------------
    zones, run = [], []
    for unit in ordered:
        if unit.is_silent:
            run.append(unit.unit_id)
            continue
        if run and all(_is_dead_zone(u) for u in ordered
                       if u.unit_id in run):
            zones.append(tuple(run))
        run = []
    if run and all(_is_dead_zone(u) for u in ordered if u.unit_id in run):
        zones.append(tuple(run))
    if zones:
        findings.append(_finding(
            "FAIL",
            "commercial narrative dead zone: the visual is not self-explanatory, no new "
            "commercial information is being communicated, the voice is absent, and the "
            "silence has no justified commercial reason",
            f"{len(zones)} zone(s): {' | '.join(' > '.join(z) for z in zones)}"))

    # --- Q5: a voice line with no function of its own ----------------------------------
    unexplained_roles = [u.unit_id for u in ordered if u.has_vo and u.vo_role not in VO_ROLES]
    if unexplained_roles:
        findings.append(_finding(
            "FAIL",
            "a voice line names no role from the commercial vocabulary, so its reason for "
            "existing cannot be established",
            f"{len(unexplained_roles)} unit(s): {', '.join(unexplained_roles)}"))

    redundant = [
        u.unit_id for u in ordered
        if u.has_vo and u.has_title and not u.vo_adds_function_beyond_title
    ]
    if redundant:
        findings.append(_finding(
            "FAIL",
            "the voice duplicates the Title's function without adding value; channels may "
            "share a selling point but not a function",
            f"{len(redundant)} unit(s): {', '.join(redundant)}"))

    # --- Q7: does the narration progress toward the ask? -------------------------------
    if not any(u.vo_role == "CTA" for u in ordered if u.has_vo):
        findings.append(_finding(
            "WEAK",
            "no voice line carries the call to action, so the narration does not resolve "
            "toward an action",
            "CTA role absent"))

    # --- Q8: evidence safety -----------------------------------------------------------
    unsafe = [
        u.unit_id for u in ordered
        if u.is_silent
        and u.carries_new_commercial_information
        and not u.explanation_supported
    ]
    if unsafe:
        findings.append(_finding(
            "WEAK",
            "these units need an explanation that the product facts and visual evidence do "
            "not support; the gap is reported rather than filled, because more narration does "
            "not authorise a stronger claim",
            f"{len(unsafe)} unit(s): {', '.join(unsafe)}"))

    # --- positive control --------------------------------------------------------------
    if not findings:
        findings.append(_finding(
            "PASS",
            "the narration carries the selling narrative, every silence is justified, and no "
            "channel duplicates another's function",
            f"{len(ordered)} units, {len(carrying)} carrying role(s), "
            f"{len([u for u in ordered if u.is_silent])} justified silence(s)"))
    return CoverageReport(findings=tuple(findings), units=tuple(ordered))


def summary(report: CoverageReport) -> dict[str, object]:
    """A compact, machine-readable summary."""

    return {
        "verdict": report.verdict,
        "units": len(report.units),
        "spoken": len(report.spoken_units),
        "silent": len(report.silent_units),
        "silent_units": list(report.silent_units),
        "justified_silence": [
            u.unit_id for u in report.units if _silence_is_justified(u)
        ],
        "findings_by_severity": {
            s: sum(1 for f in report.findings if f.severity == s)
            for s in ("PASS", "WEAK", "FAIL", "CRITICAL")
        },
        "note": ("no score, no VO percentage, no minimum duration and no maximum silence are "
                 "produced by this assessment"),
    }
