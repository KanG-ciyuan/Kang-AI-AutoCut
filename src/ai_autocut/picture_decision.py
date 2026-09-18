"""B3-B / B3-C — the KEEP / REVIEW / CORRECT decision, and conservative match intent.

Three outcomes, and the first is a success:

    KEEP     assessed and deliberately left alone
    REVIEW   a real discontinuity exists, but confidence or risk forbids acting alone
    CORRECT  a bounded correction is justified, and product protection has cleared it

Two laws govern the whole module.

**KEEP is first-class.** The First Job's own record says *"Unchanged cuts are a valid
outcome."* A production run in which every shot is KEEP has succeeded, and any design in which
that is a failure has quietly re-created "every shot must receive correction".

**Product protection is a veto, not an input.** ``CORRECT`` is reachable only through a
protection result that explicitly authorises it. This is why the module is written after
protection rather than before it: a correction that can exist before anything can reject it is
a correction that will eventually ship.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .picture_measurement import (
    DIMENSIONS,
    REPORTING_LEVEL,
    PairComparison,
    ShotMeasurement,
)
from .product_protection import PASS as PROTECTION_PASS
from .product_protection import ProductEvidence, ProtectionResult, assess_protection

#: Decision outcomes.
KEEP = "KEEP"
REVIEW = "REVIEW"
CORRECT = "CORRECT"
OUTCOMES = (KEEP, REVIEW, CORRECT)

#: Dimensions a conservative correction may address. One per correction.
CORRECTION_DIMENSIONS = ("luminance", "cast", "saturation", "contrast", "sharpness")

#: A difference at or below this multiple of the reporting level is marginal: the benefit of
#: correcting it is comparable to the risk, so the conservative answer is KEEP.
MARGINAL_FACTOR = 1.25

#: A difference above this multiple is too large to be a matching problem. The shots may not
#: belong next to each other, which is an editing observation rather than a colour one.
LARGE_FACTOR = 3.0

#: Semantic correction directions. Deliberately named as intent, never as a parameter.
DIRECTIONS_BY_DIMENSION: Mapping[str, tuple[str, str]] = {
    "luminance": ("lift_luminance", "lower_luminance"),
    "cast": ("reduce_warm_cast", "reduce_cool_cast"),
    "saturation": ("reduce_saturation", "lift_saturation"),
    "contrast": ("reduce_contrast", "lift_contrast"),
    "sharpness": ("soften_excessive_sharpness", "restore_soft_detail"),
}

#: Relationship tiers whose discontinuity a correction may legitimately address. Unrelated
#: shots are excluded on purpose: they are expected to differ.
CORRECTABLE_TIERS = ("SAME_SEMANTIC_UNIT", "SAME_SCENE", "SAME_PRODUCT")


class PictureDecisionError(ValueError):
    """Raised when a decision cannot be reached safely."""


@dataclass(frozen=True)
class CorrectionIntent:
    """What should change, in words. Carries **no** Resolve parameter value.

    Actual numbers are produced at execution time and recorded as evidence of what was done,
    never as a reusable default. The First Job's numbers are forbidden as presets.
    """

    target_shot_id: str
    reference_shot_id: str
    dimension: str
    direction: str
    reason: str
    bound: str

    def __post_init__(self) -> None:
        if self.dimension not in CORRECTION_DIMENSIONS:
            raise PictureDecisionError(
                f"dimension must be one of: {', '.join(CORRECTION_DIMENSIONS)}"
            )
        if self.direction not in DIRECTIONS_BY_DIMENSION[self.dimension]:
            raise PictureDecisionError(
                f"direction {self.direction!r} is not valid for {self.dimension!r}; "
                f"expected one of {DIRECTIONS_BY_DIMENSION[self.dimension]}"
            )
        for label, value in (("reason", self.reason), ("bound", self.bound)):
            if not isinstance(value, str) or not value.strip():
                raise PictureDecisionError(f"a correction intent must state its {label}")
        if self.target_shot_id == self.reference_shot_id:
            raise PictureDecisionError(
                "a correction moves a shot toward a neighbour, so the reference must be a "
                "different shot"
            )

    @property
    def touches_multiple_dimensions(self) -> bool:
        """False by construction: one intent addresses one dimension."""

        return False

    def as_dict(self) -> dict[str, object]:
        return {
            "target_shot_id": self.target_shot_id,
            "reference_shot_id": self.reference_shot_id,
            "dimension": self.dimension,
            "direction": self.direction,
            "reason": self.reason,
            "bound": self.bound,
        }


@dataclass(frozen=True)
class ShotDecision:
    """The decision for one shot, with everything that produced it."""

    shot_id: str
    outcome: str
    reason: str
    confidence: str
    evidence: Mapping[str, object]
    dimension: str | None = None
    intent: CorrectionIntent | None = None
    protection: ProtectionResult | None = None

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise PictureDecisionError(f"outcome must be one of: {', '.join(OUTCOMES)}")
        if self.outcome == CORRECT:
            if self.intent is None or self.dimension is None:
                raise PictureDecisionError(
                    "a CORRECT decision must name its dimension and carry its intent"
                )
            if self.protection is None or not self.protection.may_correct:
                raise PictureDecisionError(
                    "a CORRECT decision requires a product-protection result that "
                    "authorises it; without one the decision must be REVIEW"
                )

    @property
    def is_correct(self) -> bool:
        return self.outcome == CORRECT

    def as_dict(self) -> dict[str, object]:
        return {
            "shot_id": self.shot_id,
            "outcome": self.outcome,
            "reason": self.reason,
            "confidence": self.confidence,
            "dimension": self.dimension,
            "evidence": dict(self.evidence),
            "intent": None if self.intent is None else self.intent.as_dict(),
            "protection": None if self.protection is None else self.protection.as_dict(),
        }


def _excess(delta: float, level: float) -> float:
    return abs(delta) / level if level > 0 else 0.0


def _direction_for(dimension: str, delta: float) -> str:
    positive, negative = DIRECTIONS_BY_DIMENSION[dimension]
    return positive if delta > 0 else negative


def decide_shot(
    *,
    shot: ShotMeasurement,
    pair: PairComparison | None,
    contains_product: bool,
    protection: ProtectionResult | None,
) -> ShotDecision:
    """Decide one shot. Conservative by construction; KEEP is the default destination.

    Every CORRECT decision carries a protection result, including when the shot holds no
    product: in that case the gate is still consulted and says so explicitly. A correction
    can therefore never be authorised by protection that was never asked for.
    """

    # The gate is always consulted. A shot with no product gets an explicit PASS from the
    # gate rather than a missing result, so the artifact always shows why it was allowed.
    if protection is None and not contains_product:
        protection = assess_protection(ProductEvidence(
            shot_id=shot.shot_id, contains_product=False, region=None, before=shot,
        ))

    evidence: dict[str, object] = {
        "tier": None if pair is None else pair.tier,
        "sensitivity": None if pair is None else pair.sensitivity,
        "deltas": {} if pair is None else dict(pair.deltas),
        "above_reporting_level": [] if pair is None else list(pair.above_reporting_level),
        "measurement_confidence": shot.confidence,
        "contains_product": contains_product,
        "product_region_available": shot.has_product_region,
    }

    # 1. Nothing before it to be continuous with.
    if pair is None:
        return ShotDecision(
            shot_id=shot.shot_id, outcome=KEEP, confidence=shot.confidence,
            reason="this is the first shot, so there is no neighbour to match against",
            evidence=evidence,
        )

    # 2. Unrelated shots are expected to differ. A large difference here is the picture
    #    being what it is, not a defect.
    if pair.tier not in CORRECTABLE_TIERS:
        return ShotDecision(
            shot_id=shot.shot_id, outcome=KEEP, confidence=shot.confidence,
            reason=(f"these shots are {pair.tier}, so a visible difference between them is "
                    "expected rather than a continuity defect"),
            evidence=evidence,
        )

    # 3. Nothing measured crossed the reporting level for this pair's relationship.
    if not pair.above_reporting_level:
        return ShotDecision(
            shot_id=shot.shot_id, outcome=KEEP, confidence=shot.confidence,
            reason="no measured difference crossed the reporting level for this relationship",
            evidence=evidence,
        )

    # 4. The dimension with the largest excess over its reporting level decides.
    level = REPORTING_LEVEL[pair.sensitivity]
    dimension = max(DIMENSIONS,
                    key=lambda name: _excess(pair.deltas.get(name, 0.0), level[name]))
    excess = _excess(pair.deltas.get(dimension, 0.0), level[dimension])
    delta = pair.deltas.get(dimension, 0.0)
    evidence["selected_dimension"] = dimension
    evidence["excess_over_reporting_level"] = round(excess, 4)

    # 5. A difference this large is not a matching problem. Recording it as one would be
    #    using colour to repair an edit.
    if excess > LARGE_FACTOR:
        return ShotDecision(
            shot_id=shot.shot_id, outcome=REVIEW, confidence=shot.confidence,
            reason=(f"the {dimension} difference is {excess:.1f}x the reporting level for "
                    f"{pair.tier}; a correction this large is not a conservative match, and "
                    "these shots may not belong adjacent to each other"),
            evidence=evidence,
        )

    # 6. Marginal benefit. When the improvement is comparable to the risk, keep.
    if excess <= MARGINAL_FACTOR:
        return ShotDecision(
            shot_id=shot.shot_id, outcome=KEEP, confidence=shot.confidence,
            reason=(f"the {dimension} difference is only {excess:.2f}x the reporting level, "
                    "so the benefit of correcting it is comparable to the risk of "
                    "correcting it"),
            evidence=evidence,
        )

    # 7. A low-confidence reading never authorises a correction.
    if shot.confidence == "LOW":
        return ShotDecision(
            shot_id=shot.shot_id, outcome=KEEP, confidence=shot.confidence,
            reason=("the measurement confidence is too low to justify changing a shot"),
            evidence=evidence,
        )

    # 8. Product protection is the veto. With a product present and no authorising result,
    #    the answer is REVIEW, never CORRECT.
    if contains_product:
        if protection is None:
            return ShotDecision(
                shot_id=shot.shot_id, outcome=REVIEW, confidence=shot.confidence,
                reason=("this shot carries product and no product-protection result was "
                        "produced, so no correction may proceed"),
                evidence=evidence,
            )
        if not protection.may_correct:
            return ShotDecision(
                shot_id=shot.shot_id, outcome=REVIEW, confidence=protection.confidence,
                reason=(f"product protection returned {protection.outcome}: "
                        f"{protection.reason}"),
                evidence=evidence, protection=protection,
            )

    intent = CorrectionIntent(
        target_shot_id=shot.shot_id,
        reference_shot_id=pair.previous_shot_id,
        dimension=dimension,
        direction=_direction_for(dimension, delta),
        reason=(f"{dimension} differs from the neighbouring shot by {abs(delta):.2f} "
                f"({excess:.1f}x the reporting level for {pair.tier})"),
        bound="minor",
    )
    return ShotDecision(
        shot_id=shot.shot_id, outcome=CORRECT, confidence=shot.confidence,
        reason=(f"the {dimension} difference is {excess:.1f}x the reporting level for "
                f"{pair.tier}, and product protection cleared the correction"),
        evidence=evidence, dimension=dimension, intent=intent, protection=protection,
    )


def summarise(decisions: list[ShotDecision] | tuple[ShotDecision, ...]) -> dict[str, object]:
    """A compact record of a decision pass. An all-KEEP pass is a success."""

    if not decisions:
        raise PictureDecisionError("a decision pass needs at least one decision")
    return {
        "shots_decided": len(decisions),
        "keep": sum(1 for d in decisions if d.outcome == KEEP),
        "review": sum(1 for d in decisions if d.outcome == REVIEW),
        "correct": sum(1 for d in decisions if d.outcome == CORRECT),
        "all_keep": all(d.outcome == KEEP for d in decisions),
        "decisions": [d.as_dict() for d in decisions],
    }
