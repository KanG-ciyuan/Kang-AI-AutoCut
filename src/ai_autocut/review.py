"""Reviewer and Repair contract.

The governing rule is that a Reviewer is not the executor repeating its own
success claim. A review is an independent, dimension-by-dimension judgement,
and its output is a severity per dimension plus one release verdict.

Repair follows from a review and is targeted: the smallest affected range is
repaired, and regenerating the whole video is refused by default.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence


SCHEMA_VERSION = "review.v0"

#: Release gating is layered. Independence is a property of the arrangement,
#: not of any single model's confidence.
REVIEW_GATES = ("DETERMINISTIC_QA", "INDEPENDENT_AI_REVIEW", "HUMAN_FINAL_GATE")

#: Severity scale, weakest to strongest.
SEVERITIES = ("PASS", "WEAK", "FAIL", "CRITICAL")

#: Release verdicts.
RELEASE_VERDICTS = ("PRODUCTION_READY", "NEEDS_REPAIR", "REJECT")

#: The dimensions a review must judge. Each is answered exactly once.
REVIEWER_DIMENSIONS = (
    "shot_selection",
    "action_boundary",
    "shot_relationship",
    "narrative_progression",
    "rhythm",
    "multi_source_remix",
    "information_density",
    "visual_continuity",
    "effect_judgment",
    "commercial_effectiveness",
)

#: A WEAK finding may be released only when it is explicitly accepted. FAIL and
#: CRITICAL can never be accepted away.
_ACCEPTABLE_SEVERITIES = ("WEAK",)

_FINDING_KEYS = ("dimension", "severity", "detail", "accepted")
_REVIEW_KEYS = ("schema_version", "reviewer_id", "executor_id", "findings")

_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class ReviewContractError(ValueError):
    """Raised when a review cannot support a release decision."""


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise ReviewContractError(f"{label} is malformed")
    return value


@dataclass(frozen=True)
class Finding:
    dimension: str
    severity: str
    detail: str
    accepted: bool = False

    def __post_init__(self) -> None:
        if self.dimension not in REVIEWER_DIMENSIONS:
            raise ReviewContractError(
                f"unknown review dimension {self.dimension!r}; expected one of: "
                + ", ".join(REVIEWER_DIMENSIONS)
            )
        if self.severity not in SEVERITIES:
            raise ReviewContractError(
                f"severity must be one of: {', '.join(SEVERITIES)}"
            )
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise ReviewContractError("a finding must state its evidence")
        if not isinstance(self.accepted, bool):
            raise ReviewContractError("accepted must be a boolean")
        if self.accepted and self.severity not in _ACCEPTABLE_SEVERITIES:
            raise ReviewContractError(
                f"a {self.severity} finding cannot be accepted; only "
                + "/".join(_ACCEPTABLE_SEVERITIES)
                + " findings may be dispositioned this way"
            )

    @property
    def blocks_release(self) -> bool:
        return not self.accepted and self.severity != "PASS"

    def as_dict(self) -> dict[str, object]:
        return {
            "dimension": self.dimension,
            "severity": self.severity,
            "detail": self.detail,
            "accepted": self.accepted,
        }


@dataclass(frozen=True)
class Review:
    reviewer_id: str
    executor_id: str
    findings: tuple[Finding, ...]

    def __post_init__(self) -> None:
        reviewer = _identifier(self.reviewer_id, "reviewer_id")
        executor = _identifier(self.executor_id, "executor_id")
        if reviewer == executor:
            raise ReviewContractError(
                "a review is not the executor's own success claim; reviewer_id and "
                "executor_id must differ"
            )
        if not isinstance(self.findings, tuple) or not self.findings:
            raise ReviewContractError("findings must be a non-empty tuple")
        seen: set[str] = set()
        for finding in self.findings:
            if not isinstance(finding, Finding):
                raise ReviewContractError("findings must contain Finding values")
            if finding.dimension in seen:
                raise ReviewContractError(
                    f"dimension {finding.dimension!r} is judged more than once"
                )
            seen.add(finding.dimension)
        # Completeness is part of the contract, not a nicety. A review that
        # judges only the dimensions it happens to like is not a review, and it
        # must never reach a release verdict. Missing dimensions fail closed
        # here, so `verdict` is unreachable for an incomplete review.
        missing = tuple(
            dimension for dimension in REVIEWER_DIMENSIONS if dimension not in seen
        )
        if missing:
            raise ReviewContractError(
                "a review must judge every dimension exactly once; missing: "
                + ", ".join(missing)
            )

    @property
    def blocking_findings(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.blocks_release)

    @property
    def worst_severity(self) -> str:
        return max(self.findings, key=lambda f: SEVERITIES.index(f.severity)).severity

    @property
    def verdict(self) -> str:
        """Derive the release verdict from the recorded severities.

        Construction already guarantees a complete review, so this cannot be
        reached with partial findings. The assertion is kept as a second line of
        defence: a release verdict must never be derivable from a review that
        skipped a dimension.
        """

        judged = {finding.dimension for finding in self.findings}
        if judged != set(REVIEWER_DIMENSIONS):
            raise ReviewContractError(
                "a release verdict requires every dimension to be judged exactly once"
            )
        severities = [finding.severity for finding in self.findings]
        if "CRITICAL" in severities:
            return "REJECT"
        if self.blocking_findings:
            return "NEEDS_REPAIR"
        return "PRODUCTION_READY"

    @property
    def requires_human_gate(self) -> bool:
        """Release always passes the human gate; repair never auto-releases."""

        return True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "reviewer_id": self.reviewer_id,
            "executor_id": self.executor_id,
            "verdict": self.verdict,
            "findings": [finding.as_dict() for finding in self.findings],
        }


def parse_review(document: object) -> Review:
    if not isinstance(document, Mapping):
        raise ReviewContractError("review must be a JSON object")
    unknown = sorted(set(document) - set(_REVIEW_KEYS))
    missing = sorted(set(_REVIEW_KEYS) - set(document))
    if unknown:
        raise ReviewContractError(
            f"review has unsupported key(s): {', '.join(unknown)}"
        )
    if missing:
        raise ReviewContractError(
            f"review is missing required key(s): {', '.join(missing)}"
        )
    if document["schema_version"] != SCHEMA_VERSION:
        raise ReviewContractError(f"schema_version must be {SCHEMA_VERSION!r}")

    raw_findings = document["findings"]
    if not isinstance(raw_findings, list):
        raise ReviewContractError("findings must be a JSON array")

    findings: list[Finding] = []
    for index, raw in enumerate(raw_findings):
        label = f"findings[{index}]"
        if not isinstance(raw, Mapping):
            raise ReviewContractError(f"{label} must be a JSON object")
        item_unknown = sorted(set(raw) - set(_FINDING_KEYS))
        item_missing = sorted(set(_FINDING_KEYS) - set(raw))
        if item_unknown:
            raise ReviewContractError(
                f"{label} has unsupported key(s): {', '.join(item_unknown)}"
            )
        if item_missing:
            raise ReviewContractError(
                f"{label} is missing required key(s): {', '.join(item_missing)}"
            )
        findings.append(
            Finding(
                dimension=raw["dimension"],  # type: ignore[arg-type]
                severity=raw["severity"],  # type: ignore[arg-type]
                detail=raw["detail"],  # type: ignore[arg-type]
                accepted=raw["accepted"],  # type: ignore[arg-type]
            )
        )

    return Review(
        reviewer_id=document["reviewer_id"],  # type: ignore[arg-type]
        executor_id=document["executor_id"],  # type: ignore[arg-type]
        findings=tuple(findings),
    )


@dataclass(frozen=True)
class RepairPlan:
    """A targeted repair derived from blocking findings."""

    affected_dimensions: tuple[str, ...]
    affected_shots: tuple[str, ...]
    regenerate_entire_video: bool = False

    def __post_init__(self) -> None:
        if not self.affected_dimensions:
            raise ReviewContractError("a repair plan must name the dimensions it fixes")
        for dimension in self.affected_dimensions:
            if dimension not in REVIEWER_DIMENSIONS:
                raise ReviewContractError(
                    f"unknown review dimension {dimension!r}"
                )
        if not self.affected_shots:
            raise ReviewContractError("a targeted repair must name its affected shots")
        for shot in self.affected_shots:
            _identifier(shot, "affected_shots[]")
        if self.regenerate_entire_video:
            raise ReviewContractError(
                "regenerating the entire video is not an accepted default repair"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "affected_dimensions": list(self.affected_dimensions),
            "affected_shots": list(self.affected_shots),
            "regenerate_entire_video": self.regenerate_entire_video,
        }


def build_targeted_repair(
    review: Review, affected_shots: Sequence[object]
) -> RepairPlan:
    """Derive the smallest repair that clears the blocking findings."""

    if not isinstance(review, Review):
        raise ReviewContractError("review must be a Review")
    if review.verdict == "REJECT":
        raise ReviewContractError(
            "a REJECT review is not repaired by a targeted fix; it returns to planning"
        )
    blocking = review.blocking_findings
    if not blocking:
        raise ReviewContractError("a repair plan requires at least one blocking finding")
    dimensions = tuple(sorted({finding.dimension for finding in blocking}))
    return RepairPlan(
        affected_dimensions=dimensions,
        affected_shots=tuple(_identifier(shot, "affected_shots[]") for shot in affected_shots),
    )


def verdict_rank(verdict: str) -> int:
    """Return how severe a release verdict is, worst last."""

    if verdict not in RELEASE_VERDICTS:
        raise ReviewContractError(
            f"verdict must be one of: {', '.join(RELEASE_VERDICTS)}"
        )
    return RELEASE_VERDICTS.index(verdict)
