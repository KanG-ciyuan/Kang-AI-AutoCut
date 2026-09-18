"""Prospective intervention ledger.

The Second SKU's intervention figures were reconstructed after the run and survive as
one summary block whose own note says they were recorded for the trend only. Four of the
ten cannot be tied to any artifact that enumerates them.

The fix is structural, not analytical: record an intervention when it happens. These
tests hold that property — the ledger appends, it never rewrites, and it never upgrades
the confidence of the historical baseline it is compared against.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from src.ai_autocut.intervention_ledger import (
    ACTORS,
    INTERVENTION_KINDS,
    Intervention,
    InterventionLedger,
    InterventionLedgerError,
    comparison_against_baseline,
)

BASELINE_PATH = Path("docs/audit/sku2-intervention-baseline.json")


def entry(**overrides: object) -> Intervention:
    fields: dict[str, object] = {
        "job_id": "job-1",
        "stage": "PLAN THE WORDS",
        "kind": "COPY_INTERVENTIONS",
        "actor": "CODEX_SUPERVISOR",
        "trigger": "narration_coverage REVIEW_REQUIRED",
        "detail": "rewrote U04 to explain the colour range rather than repeat the title",
    }
    fields.update(overrides)
    return Intervention(**fields)  # type: ignore[arg-type]


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = InterventionLedger(self.tmp / "intervention_ledger.jsonl")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_an_empty_ledger_reads_as_empty(self) -> None:
        self.assertEqual(self.ledger.entries(), ())
        self.assertEqual(self.ledger.summary()["total_interventions"], 0)

    def test_recording_appends_and_survives_a_new_reader(self) -> None:
        self.ledger.record(entry())
        self.ledger.record(entry(kind="VO_GENERATIONS", paid_api_calls=1))
        reopened = InterventionLedger(self.ledger.path)
        self.assertEqual(len(reopened.entries()), 2)

    def test_the_ledger_is_append_only(self) -> None:
        """An earlier line is never rewritten by a later record."""

        first = self.ledger.record(entry(detail="first"))
        self.ledger.record(entry(detail="second"))
        rows = self.ledger.entries()
        self.assertEqual(rows[0]["detail"], "first")
        self.assertEqual(rows[0]["at"], first["at"])

    def test_an_entry_is_timestamped_when_recorded(self) -> None:
        payload = self.ledger.record(entry())
        self.assertTrue(str(payload["at"]).endswith("Z"))

    def test_the_line_is_jsonl(self) -> None:
        self.ledger.record(entry())
        self.ledger.record(entry())
        lines = [
            line
            for line in self.ledger.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertIsInstance(json.loads(line), dict)

    def test_counts_cover_every_kind_including_zeros(self) -> None:
        self.ledger.record(entry())
        counts = self.ledger.counts()
        self.assertEqual(set(counts), set(INTERVENTION_KINDS))
        self.assertEqual(counts["COPY_INTERVENTIONS"], 1)
        self.assertEqual(counts["SUPERVISOR_DECISIONS"], 0)

    def test_interventions_are_attributed_by_actor(self) -> None:
        self.ledger.record(entry())
        self.ledger.record(entry(actor="AUTOMATED_REPAIR"))
        summary = self.ledger.summary()
        self.assertEqual(summary["by_actor"]["CODEX_SUPERVISOR"], 1)
        self.assertEqual(summary["by_actor"]["AUTOMATED_REPAIR"], 1)
        self.assertEqual(summary["by_actor"]["HUMAN"], 0)

    def test_paid_api_calls_are_totalled(self) -> None:
        self.ledger.record(entry(kind="VO_GENERATIONS", paid_api_calls=1))
        self.ledger.record(entry(kind="BGM_GENERATIONS", paid_api_calls=1))
        self.assertEqual(self.ledger.summary()["paid_api_calls"], 2)

    def test_an_unknown_kind_is_refused(self) -> None:
        with self.assertRaises(InterventionLedgerError):
            entry(kind="SOMETHING_ELSE")

    def test_an_unknown_actor_is_refused(self) -> None:
        with self.assertRaises(InterventionLedgerError):
            entry(actor="SOMEONE")

    def test_negative_paid_calls_are_refused(self) -> None:
        with self.assertRaises(InterventionLedgerError):
            entry(paid_api_calls=-1)

    def test_a_blank_detail_is_refused(self) -> None:
        with self.assertRaises(InterventionLedgerError):
            entry(detail="  ")

    def test_a_corrupt_line_is_reported_rather_than_skipped(self) -> None:
        self.ledger.record(entry())
        with self.ledger.path.open("a", encoding="utf-8") as handle:
            handle.write("{not json}\n")
        with self.assertRaises(InterventionLedgerError):
            self.ledger.entries()

    def test_the_vocabulary_matches_the_sku2_baseline_keys(self) -> None:
        """Comparison must be a key-by-key subtraction, not a reinterpretation."""

        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(baseline["fields"]), set(INTERVENTION_KINDS))


class BaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    def test_the_baseline_is_marked_partially_verified(self) -> None:
        self.assertEqual(self.baseline["status"], "PARTIALLY_VERIFIED")

    def test_every_field_carries_a_confidence(self) -> None:
        for key, value in self.baseline["fields"].items():
            with self.subTest(field=key):
                self.assertIn(
                    value["confidence"], ("VERIFIED", "PARTIAL", "NOT_VERIFIABLE")
                )

    def test_the_baseline_is_immutable(self) -> None:
        self.assertTrue(self.baseline["immutable"])

    def test_confidence_is_not_upgraded_by_comparison(self) -> None:
        counts = {kind: 0 for kind in INTERVENTION_KINDS}
        compared = comparison_against_baseline(counts, self.baseline)
        self.assertEqual(compared["baseline_status"], "PARTIALLY_VERIFIED")
        self.assertEqual(
            compared["fields"]["SUPERVISOR_DECISIONS"]["confidence"], "NOT_VERIFIABLE"
        )
        self.assertFalse(compared["fields"]["SUPERVISOR_DECISIONS"]["comparable"])

    def test_verified_fields_are_marked_comparable(self) -> None:
        counts = {kind: 0 for kind in INTERVENTION_KINDS}
        compared = comparison_against_baseline(counts, self.baseline)
        self.assertTrue(compared["fields"]["VO_GENERATIONS"]["comparable"])
        self.assertEqual(compared["fields"]["VO_GENERATIONS"]["sku2"], 2)

    def test_the_unverifiable_values_are_the_ones_the_audit_found(self) -> None:
        unverifiable = {
            key
            for key, value in self.baseline["fields"].items()
            if value["confidence"] == "NOT_VERIFIABLE"
        }
        self.assertEqual(
            unverifiable,
            {"SUPERVISOR_DECISIONS", "RENDER_TO_ACCEPTED_STEPS"},
        )


if __name__ == "__main__":
    unittest.main()
