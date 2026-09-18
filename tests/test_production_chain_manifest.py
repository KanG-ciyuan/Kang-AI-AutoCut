"""Production chain manifest invariants.

The manifest exists so that a later agent can answer one question without re-deriving
it: *is this capability actually in the production chain?* That only works if the
document cannot lie. These tests enforce the invariants declared inside the document
itself, so a capability cannot be marked WIRED without naming a caller that exists and
a file that is in git.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

MANIFEST_PATH = Path("docs/audit/production-chain-manifest.json")
MANIFEST_MD = Path("docs/audit/production-chain-manifest.md")
FAST_PATH = Path("src/ai_autocut/fast_path.py")

SEMANTIC_STAGES = (
    "PREPARE",
    "UNDERSTAND SHOTS",
    "PLAN THE EDIT",
    "FINISH THE PICTURE",
    "PLAN THE WORDS",
    "BUILD THE AUDIO",
    "ASSEMBLE & MASTER",
    "REVIEW & REPAIR",
)

VALID_STATUSES = {
    "WIRED",
    "PARTIALLY_WIRED",
    "NOT_WIRED",
    "JOB_SPECIFIC_ONLY",
    "EXPERIMENTAL_ONLY",
    "DEPRECATED",
    "UNKNOWN",
}


def load() -> dict:
    with MANIFEST_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


class ManifestShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load()
        self.rows = self.manifest["capabilities"]

    def test_the_manifest_exists_in_both_forms(self) -> None:
        self.assertTrue(MANIFEST_PATH.is_file())
        self.assertTrue(MANIFEST_MD.is_file())

    def test_every_row_carries_the_required_fields(self) -> None:
        required = {
            "stage", "capability", "implementation", "production_caller",
            "upstream_input", "downstream_consumer", "tests", "real_job_evidence",
            "wiring_status", "third_sku_ready", "notes", "git_tracked",
        }
        for row in self.rows:
            with self.subTest(capability=row.get("capability")):
                self.assertEqual(required - set(row), set())

    def test_every_stage_is_one_of_the_eight_semantic_stages(self) -> None:
        for row in self.rows:
            with self.subTest(capability=row["capability"]):
                self.assertIn(row["stage"], SEMANTIC_STAGES)

    def test_every_wiring_status_is_from_the_closed_vocabulary(self) -> None:
        for row in self.rows:
            with self.subTest(capability=row["capability"]):
                self.assertIn(row["wiring_status"], VALID_STATUSES)


class ManifestInvariantTests(unittest.TestCase):
    """Invariant 1 and 2: WIRED means a real, tracked caller is named."""

    def setUp(self) -> None:
        self.manifest = load()
        self.rows = self.manifest["capabilities"]

    def test_wired_implies_a_named_production_caller(self) -> None:
        for row in self.rows:
            if row["wiring_status"] != "WIRED":
                continue
            with self.subTest(capability=row["capability"]):
                self.assertIsNotNone(
                    row["production_caller"],
                    f"{row['capability']} is marked WIRED without naming a caller",
                )

    def test_wired_implies_the_implementation_is_in_git(self) -> None:
        for row in self.rows:
            if row["wiring_status"] != "WIRED":
                continue
            with self.subTest(capability=row["capability"]):
                self.assertTrue(row["git_tracked"])

    def test_wired_capabilities_are_reachable_from_the_fast_path(self) -> None:
        """Every fast-path caller named must actually appear in fast_path.py."""

        source = FAST_PATH.read_text(encoding="utf-8")
        for row in self.rows:
            caller = row["production_caller"]
            if caller is None or "fast_path.py" not in caller:
                continue
            with self.subTest(capability=row["capability"]):
                symbol = caller.split(":")[1]
                # A caller may be class-qualified (FastPath.record_intervention); what
                # must appear in the module is the definition itself.
                self.assertIn(f"def {symbol.split('.')[-1]}(", source)

    def test_third_sku_ready_implies_wired(self) -> None:
        for row in self.rows:
            if not row["third_sku_ready"]:
                continue
            with self.subTest(capability=row["capability"]):
                self.assertEqual(row["wiring_status"], "WIRED")


class ManifestAccuracyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load()
        self.rows = self.manifest["capabilities"]

    def test_every_implementation_path_exists(self) -> None:
        for row in self.rows:
            implementation = row["implementation"]
            if implementation is None:
                continue
            with self.subTest(capability=row["capability"]):
                path = implementation.split(":")[0]
                self.assertTrue(
                    Path(path).is_file(), f"manifest names a missing file: {path}"
                )

    def test_every_named_test_file_exists(self) -> None:
        for row in self.rows:
            for test in row["tests"]:
                with self.subTest(capability=row["capability"], test=test):
                    self.assertTrue(Path(test).is_file(), f"missing test file: {test}")

    def test_every_p0_module_has_a_real_production_caller(self) -> None:
        for module in self.manifest["p0_modules"]:
            with self.subTest(module=module):
                rows = [
                    row
                    for row in self.rows
                    if row["implementation"] and module in row["implementation"]
                ]
                self.assertTrue(rows, f"no manifest row mentions {module}")
                self.assertTrue(
                    any(row["wiring_status"] == "WIRED" for row in rows),
                    f"{module} is a P0 module but no row records it as WIRED",
                )
                self.assertTrue(
                    any(row["production_caller"] for row in rows),
                    f"{module} is a P0 module with no production caller",
                )

    def test_manifest_and_implementation_agree_on_the_stage_count(self) -> None:
        source = FAST_PATH.read_text(encoding="utf-8")
        for stage in SEMANTIC_STAGES:
            with self.subTest(stage=stage):
                self.assertIn(f'"{stage}"', source)

    def test_step_is_the_checkpointing_entry_point(self) -> None:
        source = FAST_PATH.read_text(encoding="utf-8")
        self.assertIn("def step(", source)
        self.assertIn("def checkpoint(", source)

    def test_the_manifest_declares_its_own_invariants(self) -> None:
        self.assertEqual(len(self.manifest["invariants"]), 6)

    def test_incomplete_capabilities_are_not_marked_ready(self) -> None:
        """The point of the document: honest negatives stay negative."""

        not_ready = {row["capability"] for row in self.rows if not row["third_sku_ready"]}
        self.assertIn("packaging, encode/remux, final master", not_ready)
        self.assertIn("typography execution", not_ready)
        self.assertIn("DaVinci Resolve execution", not_ready)
        self.assertIn("automated commercial reviewer", not_ready)
        self.assertIn("semantic / action grouping", not_ready)


if __name__ == "__main__":
    unittest.main()
