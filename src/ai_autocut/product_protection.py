"""B3-D — product protection. A hard gate, not an advisory check.

The law:

    PRODUCT AUTHENTICITY > PERFECT BACKGROUND MATCH

A correction that improves background continuity while measurably degrading the product is
**rejected**, and the accepted outcome is ``KEEP_ORIGINAL`` — even though the background then
does not reach its statistically best state. That trade was measured in the First Job: the
aggressive variant converged 42% against the conservative 39%, and the extra three points cost
product fidelity.

Three rules make this a gate rather than a report:

* a correction may proceed only when this module returns ``PASS``;
* a missing product region is **never** treated as an empty or an unprotected one — it is
  ``UNAVAILABLE``, and ``UNAVAILABLE`` can never authorise a correction;
* a tolerance may not be widened in order to let a correction through.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .picture_measurement import ProductRegion, ShotMeasurement

#: Outcomes of the gate.
PASS = "PASS"
REJECT = "REJECT"
UNAVAILABLE = "UNAVAILABLE"
OUTCOMES = (PASS, REJECT, UNAVAILABLE)

class ProductProtectionError(ValueError):
    """Raised when protection cannot be assessed safely."""


@dataclass(frozen=True)
class ProtectionTolerance:
    """How far the product may move before the change is a product change."""

    colour: float = 6.0
    luminance: float = 8.0
    saturation: float = 8.0
    contrast_retention: float = 0.75

    def __post_init__(self) -> None:
        for label, value in (("colour", self.colour), ("luminance", self.luminance),
                             ("saturation", self.saturation)):
            if value <= 0:
                raise ProductProtectionError(f"{label} tolerance must be positive")
        if not 0.0 < self.contrast_retention <= 1.0:
            raise ProductProtectionError(
                "contrast_retention is a fraction of the original detail, so it must be "
                "greater than 0 and at most 1"
            )


#: How far the product may move by default. Starting values, stated explicitly so they can be
#: reviewed. They are **not** the First Job's correction numbers, and they carry no claim to
#: being universal: they describe how far a product may drift before what is on screen is a
#: different product.
DEFAULT_TOLERANCE = ProtectionTolerance()


@dataclass(frozen=True)
class ProtectionCheck:
    """One measured before/after check."""

    name: str
    passed: bool
    measured: float
    allowed: float
    detail: str


@dataclass(frozen=True)
class ProductEvidence:
    """What is known about the product in one shot, before and after a correction."""

    shot_id: str
    contains_product: bool
    region: ProductRegion | None
    before: ShotMeasurement
    after: ShotMeasurement | None = None

    def __post_init__(self) -> None:
        if not self.shot_id:
            raise ProductProtectionError("protection evidence needs a shot id")
        if self.contains_product and self.region is None and self.after is not None:
            # An after-measurement with no region means a correction was assessed against
            # something other than the product. Refuse rather than guess.
            raise ProductProtectionError(
                f"shot {self.shot_id!r} has no product region, so a correction cannot be "
                "assessed against the product"
            )


@dataclass(frozen=True)
class ProtectionResult:
    """The gate's verdict for one shot."""

    shot_id: str
    outcome: str
    confidence: str
    checks: tuple[ProtectionCheck, ...]
    reason: str
    missing_region: bool = False

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ProductProtectionError(
                f"outcome must be one of: {', '.join(OUTCOMES)}"
            )

    @property
    def may_correct(self) -> bool:
        """Only a PASS authorises a correction. Everything else is a refusal."""

        return self.outcome == PASS and not self.missing_region

    @property
    def failed_checks(self) -> tuple[ProtectionCheck, ...]:
        return tuple(c for c in self.checks if not c.passed)

    def as_dict(self) -> dict[str, object]:
        return {
            "shot_id": self.shot_id,
            "outcome": self.outcome,
            "confidence": self.confidence,
            "may_correct": self.may_correct,
            "missing_region": self.missing_region,
            "reason": self.reason,
            "checks": [{"name": c.name, "passed": c.passed, "measured": c.measured,
                        "allowed": c.allowed, "detail": c.detail} for c in self.checks],
        }


def assess_protection(
    evidence: ProductEvidence,
    *,
    tolerance: ProtectionTolerance = DEFAULT_TOLERANCE,
) -> ProtectionResult:
    """Decide whether a correction protected the product.

    The order of the branches is the priority order.
    """

    # 1. No product in this shot: there is nothing to protect. This is PASS, and it is
    #    stated rather than assumed, because "no product" and "product we cannot see" are
    #    different facts.
    if not evidence.contains_product:
        return ProtectionResult(
            shot_id=evidence.shot_id, outcome=PASS, confidence="HIGH", checks=(),
            reason="this shot carries no product, so no product can be damaged",
        )

    # 2. Product present but no reliable region: refuse. There is no fifth option in which
    #    the region is guessed.
    if evidence.region is None:
        return ProtectionResult(
            shot_id=evidence.shot_id, outcome=UNAVAILABLE, confidence="LOW", checks=(),
            reason=("this shot contains product but no reliable product region was "
                    "supplied, so protection cannot be demonstrated; the correction may "
                    "not proceed and the missing region is recorded as evidence"),
            missing_region=True,
        )

    # 3. Region present but no after-measurement: nothing has been corrected yet, so the
    #    gate reports that protection is available, not that it passed a correction.
    if evidence.after is None:
        return ProtectionResult(
            shot_id=evidence.shot_id, outcome=UNAVAILABLE, confidence="MEDIUM", checks=(),
            reason=("a product region is available, but no corrected measurement exists "
                    "yet, so no protection claim can be made"),
        )

    before, after = evidence.before, evidence.after
    if before.product_luminance is None or after.product_luminance is None:
        raise ProductProtectionError(
            f"shot {evidence.shot_id!r} has a region but no product measurement"
        )

    checks: list[ProtectionCheck] = []

    colour_drift = _product_colour_distance(before, after)
    checks.append(ProtectionCheck(
        "product_colour_drift", colour_drift <= tolerance.colour, round(colour_drift, 4),
        tolerance.colour,
        f"product colour moved {colour_drift:.3f} against a tolerance of "
        f"{tolerance.colour:g}",
    ))

    luminance_drift = abs(after.product_luminance - before.product_luminance)
    checks.append(ProtectionCheck(
        "product_luminance_drift", luminance_drift <= tolerance.luminance,
        round(luminance_drift, 4), tolerance.luminance,
        f"product luminance moved {luminance_drift:.3f} against a tolerance of "
        f"{tolerance.luminance:g}",
    ))

    before_sat = before.product_saturation or 0.0
    after_sat = after.product_saturation or 0.0
    saturation_drift = abs(after_sat - before_sat)
    checks.append(ProtectionCheck(
        "product_saturation_drift", saturation_drift <= tolerance.saturation,
        round(saturation_drift, 4), tolerance.saturation,
        f"product saturation moved {saturation_drift:.3f} against a tolerance of "
        f"{tolerance.saturation:g}",
    ))

    before_contrast = before.product_contrast or 0.0
    after_contrast = after.product_contrast or 0.0
    retention = (after_contrast / before_contrast) if before_contrast > 0 else 1.0
    checks.append(ProtectionCheck(
        "product_recognisability_retention",
        retention >= tolerance.contrast_retention, round(retention, 4),
        tolerance.contrast_retention,
        f"the product region kept {retention * 100:.1f}% of its original contrast, which "
        f"is the detail it needs to stay identifiable",
    ))

    failed = [c for c in checks if not c.passed]
    if failed:
        names = ", ".join(c.name for c in failed)
        return ProtectionResult(
            shot_id=evidence.shot_id, outcome=REJECT,
            confidence=before.confidence, checks=tuple(checks),
            reason=(f"the correction damaged the product: {names}. Background continuity "
                    "does not outrank product authenticity, so the correction is rejected "
                    "and the original is kept."),
        )
    return ProtectionResult(
        shot_id=evidence.shot_id, outcome=PASS, confidence=before.confidence,
        checks=tuple(checks),
        reason="every product measure stayed inside tolerance",
    )


def _product_colour_distance(before: ShotMeasurement, after: ShotMeasurement) -> float:
    """Distance the product's colour moved, in the same units the cast is measured in."""

    du = after.cast_u - before.cast_u
    dv = after.cast_v - before.cast_v
    return (du * du + dv * dv) ** 0.5


def summarise(results: Sequence[ProtectionResult]) -> dict[str, object]:
    """A compact record of a protection pass, including every refusal."""

    if not results:
        raise ProductProtectionError("a protection pass needs at least one result")
    return {
        "shots_assessed": len(results),
        "passed": sum(1 for r in results if r.outcome == PASS),
        "rejected": sum(1 for r in results if r.outcome == REJECT),
        "unavailable": sum(1 for r in results if r.outcome == UNAVAILABLE),
        "missing_region": [r.shot_id for r in results if r.missing_region],
        "may_correct": [r.shot_id for r in results if r.may_correct],
        "results": [r.as_dict() for r in results],
    }
