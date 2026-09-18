"""Prospective intervention ledger.

The problem this solves
-----------------------
The Second SKU's human-intervention figures were reconstructed after the fact. They
survive as a single summary block whose own note says *"recorded for the trend only;
NOT optimised retroactively"*. Four of the ten values cannot be tied to any artifact
that enumerates them. That is not a criticism of the run — it is a criticism of
recording interventions at the end instead of at the moment they happen.

So this module records an intervention **when it occurs**, appended to
``intervention_ledger.jsonl`` in the job root. Nothing here reconstructs, infers, or
back-fills. A count that is not in the file did not happen.

The kind vocabulary is deliberately identical to the Second SKU baseline field names,
so a Third SKU comparison is a key-by-key subtraction rather than a reinterpretation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Mapping

LEDGER_FILENAME = "intervention_ledger.jsonl"
LEDGER_SCHEMA_VERSION = "intervention_ledger.v1"

#: The closed vocabulary. These are the Second SKU baseline keys, so the two are
#: directly comparable; a new kind is a deliberate decision, not an accident.
INTERVENTION_KINDS = (
    "COPY_INTERVENTIONS",
    "VO_GENERATIONS",
    "BGM_GENERATIONS",
    "SFX_GENERATIONS",
    "VISUAL_RANGE_REPAIRS",
    "TIMELINE_REPAIRS",
    "LOCAL_AUDIO_REPAIRS",
    "CREATIVE_REVIEW_REJECTIONS",
    "SUPERVISOR_DECISIONS",
    "RENDER_TO_ACCEPTED_STEPS",
)

#: Who acted. ``AUTOMATED_REPAIR`` exists so a machine repair is never counted as a
#: human intervention by accident.
ACTORS = ("CODEX_SUPERVISOR", "HUMAN", "AUTOMATED_REPAIR")


class InterventionLedgerError(ValueError):
    """Raised when an entry would corrupt the record."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _non_empty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InterventionLedgerError(f"{label} must be a non-empty string")
    return value


@dataclass(frozen=True)
class Intervention:
    """One intervention, as it happened."""

    job_id: str
    stage: str
    kind: str
    actor: str
    trigger: str
    detail: str
    before_ref: str | None = None
    after_ref: str | None = None
    paid_api_calls: int = 0
    at: str | None = None

    def __post_init__(self) -> None:
        _non_empty(self.job_id, "job_id")
        _non_empty(self.stage, "stage")
        _non_empty(self.detail, "detail")
        _non_empty(self.trigger, "trigger")
        if self.kind not in INTERVENTION_KINDS:
            raise InterventionLedgerError(
                f"unknown intervention kind {self.kind!r}; expected one of: "
                + ", ".join(INTERVENTION_KINDS)
            )
        if self.actor not in ACTORS:
            raise InterventionLedgerError(
                f"unknown actor {self.actor!r}; expected one of: " + ", ".join(ACTORS)
            )
        if not isinstance(self.paid_api_calls, int) or isinstance(self.paid_api_calls, bool):
            raise InterventionLedgerError("paid_api_calls must be an integer")
        if self.paid_api_calls < 0:
            raise InterventionLedgerError("paid_api_calls cannot be negative")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "at": self.at or _utc_now(),
            "job_id": self.job_id,
            "stage": self.stage,
            "kind": self.kind,
            "actor": self.actor,
            "trigger": self.trigger,
            "detail": self.detail,
            "before_ref": self.before_ref,
            "after_ref": self.after_ref,
            "paid_api_calls": self.paid_api_calls,
        }


class InterventionLedger:
    """Append-only writer. It can add a line; it cannot rewrite one."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def record(self, intervention: Intervention) -> dict[str, object]:
        if not isinstance(intervention, Intervention):
            raise InterventionLedgerError("intervention must be an Intervention")
        payload = intervention.as_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        # Append and flush to disk immediately: an intervention recorded only in memory
        # is an intervention that can be lost by the very failure it describes.
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return payload

    def entries(self) -> tuple[dict[str, object], ...]:
        if not self.path.exists():
            return ()
        rows: list[dict[str, object]] = []
        for number, raw in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not raw.strip():
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise InterventionLedgerError(
                    f"{self.path.name} line {number} is not valid JSON"
                ) from exc
            if not isinstance(parsed, dict):
                raise InterventionLedgerError(
                    f"{self.path.name} line {number} must be an object"
                )
            rows.append(parsed)
        return tuple(rows)

    def counts(self) -> dict[str, int]:
        """Every kind, present or not. A missing kind counts as zero, explicitly."""

        tally = {kind: 0 for kind in INTERVENTION_KINDS}
        for row in self.entries():
            kind = str(row.get("kind"))
            if kind in tally:
                tally[kind] += 1
        return tally

    def summary(self) -> dict[str, object]:
        rows = self.entries()
        return {
            "schema_version": "intervention_summary.v1",
            "ledger": self.path.name,
            "recorded_at_occurrence": True,
            "total_interventions": len(rows),
            "counts": self.counts(),
            "by_actor": {
                actor: sum(1 for row in rows if row.get("actor") == actor)
                for actor in ACTORS
            },
            "paid_api_calls": sum(int(row.get("paid_api_calls", 0) or 0) for row in rows),
        }


def comparison_against_baseline(
    counts: Mapping[str, int], baseline: Mapping[str, object]
) -> dict[str, object]:
    """Compare a live ledger against the Second SKU baseline, key by key.

    The baseline records a confidence per field. Nothing here upgrades one: a
    ``NOT_VERIFIABLE`` baseline number stays labelled as such, so a delta against it is
    never presented as a measured improvement when the baseline itself is an assertion.
    """

    fields = baseline.get("fields", {})
    if not isinstance(fields, Mapping):
        raise InterventionLedgerError("baseline must carry a 'fields' mapping")
    rows: dict[str, object] = {}
    for kind in INTERVENTION_KINDS:
        entry = fields.get(kind)
        if not isinstance(entry, Mapping):
            rows[kind] = {"sku2": None, "sku3": counts.get(kind, 0), "confidence": "ABSENT"}
            continue
        rows[kind] = {
            "sku2": entry.get("value"),
            "sku3": counts.get(kind, 0),
            "confidence": entry.get("confidence", "UNKNOWN"),
            "comparable": entry.get("confidence") == "VERIFIED",
        }
    return {
        "schema_version": "intervention_comparison.v1",
        "baseline_status": baseline.get("status"),
        "baseline_note": baseline.get("source_note"),
        "fields": rows,
    }


__all__ = [
    "ACTORS",
    "INTERVENTION_KINDS",
    "LEDGER_FILENAME",
    "LEDGER_SCHEMA_VERSION",
    "Intervention",
    "InterventionLedger",
    "InterventionLedgerError",
    "comparison_against_baseline",
]
