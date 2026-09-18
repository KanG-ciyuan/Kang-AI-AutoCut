"""Production chain manifest invariants.

The manifest exists so a later agent can answer one question without re-deriving it:
*is this capability actually in the production chain?*

Phase 2B answered that with a single readiness flag, and independent inspection rejected
it: capabilities claimed ``WIRED`` and ``third_sku_ready`` whose runtime behaviour did
not support the claim. This revision replaces the flag with six independent dimensions
and enforces the relationships between them, so *implemented* can no longer be read as
*reachable*, and a manual gate can no longer be read as an executor.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from src.ai_autocut import execution_contracts, fast_path, producer_registry

MANIFEST_PATH = Path("docs/audit/production-chain-manifest.json")
MANIFEST_MD = Path("docs/audit/production-chain-manifest.md")

DIMENSIONS = (
    "IMPLEMENTED",
    "VALIDATOR_WIRED",
    "PRODUCER_DEFINED",
    "EXECUTOR_AVAILABLE",
    "MANUAL_GATE_DEFINED",
    "END_TO_END_REACHABLE",
)

VALID_STATUSES = {
    "WIRED", "PARTIALLY_WIRED", "NOT_WIRED", "JOB_SPECIFIC_ONLY",
    "EXPERIMENTAL_ONLY", "DEPRECATED", "UNKNOWN",
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

    def test_the_schema_is_the_corrected_revision(self) -> None:
        self.assertEqual(self.manifest["schema_version"], "production_chain_manifest.v3")

    def test_every_row_carries_the_required_fields(self) -> None:
        required = {
            "stage", "capability", "implementation", "git_tracked", "production_caller",
            "wiring_status", "producer", "producer_type", "dimensions", "third_sku_ready",
            "notes",
        }
        for row in self.rows:
            with self.subTest(capability=row.get("capability")):
                self.assertEqual(required - set(row), set())

    def test_every_row_declares_all_six_dimensions(self) -> None:
        for row in self.rows:
            with self.subTest(capability=row["capability"]):
                self.assertEqual(set(row["dimensions"]), set(DIMENSIONS))

    def test_every_stage_is_one_of_the_eight_semantic_stages(self) -> None:
        for row in self.rows:
            with self.subTest(capability=row["capability"]):
                self.assertIn(row["stage"], fast_path.SEMANTIC_STAGES)

    def test_every_wiring_status_is_from_the_closed_vocabulary(self) -> None:
        for row in self.rows:
            with self.subTest(capability=row["capability"]):
                self.assertIn(row["wiring_status"], VALID_STATUSES)


class ManifestInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load()
        self.rows = self.manifest["capabilities"]

    def test_the_manifest_declares_its_invariants(self) -> None:
        self.assertEqual(len(self.manifest["invariants"]), 9)

    def test_wired_implies_a_named_production_caller(self) -> None:
        for row in self.rows:
            if row["wiring_status"] != "WIRED":
                continue
            with self.subTest(capability=row["capability"]):
                self.assertIsNotNone(row["production_caller"])

    def test_wired_implies_the_implementation_is_in_git(self) -> None:
        for row in self.rows:
            if row["wiring_status"] != "WIRED":
                continue
            with self.subTest(capability=row["capability"]):
                self.assertTrue(row["git_tracked"])

    def test_third_sku_ready_implies_end_to_end_reachable(self) -> None:
        """The correction that matters: ready means reachable, not merely written."""

        for row in self.rows:
            if not row["third_sku_ready"]:
                continue
            with self.subTest(capability=row["capability"]):
                self.assertTrue(row["dimensions"]["END_TO_END_REACHABLE"])

    def test_third_sku_ready_implies_an_executor_exists(self) -> None:
        for row in self.rows:
            if not row["third_sku_ready"]:
                continue
            with self.subTest(capability=row["capability"]):
                self.assertTrue(row["dimensions"]["EXECUTOR_AVAILABLE"])

    def test_third_sku_ready_implies_the_producer_is_defined(self) -> None:
        for row in self.rows:
            if not row["third_sku_ready"]:
                continue
            with self.subTest(capability=row["capability"]):
                self.assertTrue(row["dimensions"]["PRODUCER_DEFINED"])

    def test_a_missing_executor_requires_an_explicit_manual_gate(self) -> None:
        """Where something is expected to produce the artifact but no executor ships,
        the gate must be explicit. A capability nothing is expected to produce (no
        producer, no executor) is simply not built, and needs no gate to say so."""

        for row in self.rows:
            dims = row["dimensions"]
            if dims["EXECUTOR_AVAILABLE"] or not dims["PRODUCER_DEFINED"]:
                continue
            with self.subTest(capability=row["capability"]):
                self.assertTrue(dims["MANUAL_GATE_DEFINED"])

    def test_wired_capabilities_are_reachable_from_the_fast_path(self) -> None:
        source = Path("src/ai_autocut/fast_path.py").read_text(encoding="utf-8")
        for row in self.rows:
            caller = row["production_caller"]
            if caller is None or "fast_path.py" not in caller:
                continue
            with self.subTest(capability=row["capability"]):
                symbol = caller.split(":")[1]
                self.assertIn(f"def {symbol.split('.')[-1]}(", source)

    def test_every_reachable_capability_names_a_producer_type(self) -> None:
        from src.ai_autocut.producer_registry import PRODUCER_TYPES

        for row in self.rows:
            if row["producer"] is None and row["producer_type"] is None:
                continue
            with self.subTest(capability=row["capability"]):
                self.assertIn(row["producer_type"], PRODUCER_TYPES)

    def test_every_named_producer_is_registered(self) -> None:
        for row in self.rows:
            if row["producer"] is None:
                continue
            with self.subTest(capability=row["capability"]):
                producer = producer_registry.producer_for(row["producer"])
                self.assertEqual(producer.producer_type, row["producer_type"])

    def test_the_full_chain_claim_is_backed_by_a_runtime_proof(self) -> None:
        """Completable is claimed only because a real master was produced and measured."""

        self.assertTrue(self.manifest["full_chain_completable_today"])
        proof = self.manifest["runtime_proof"]
        self.assertEqual(proof["master_path"], "final/master.mp4")
        self.assertIn("run_pre_exam_proof.py", proof["command"])
        evidence = proof["evidence"]
        self.assertGreater(evidence["frames"], 0)
        self.assertEqual(evidence["black_frames"], 0)
        self.assertEqual(evidence["duplicate_frames"], 0)

    def test_readiness_requires_an_executor_and_reachability(self) -> None:
        """The Phase 6 rule: no capability is ready on implementation alone."""

        for row in self.rows:
            if not row["third_sku_ready"]:
                continue
            with self.subTest(capability=row["capability"]):
                self.assertTrue(row["dimensions"]["EXECUTOR_AVAILABLE"])
                self.assertTrue(row["dimensions"]["END_TO_END_REACHABLE"])
                self.assertIsNotNone(row["producer"])


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
                self.assertTrue(Path(path).is_file(), f"manifest names a missing file: {path}")

    def test_every_p0_module_has_a_real_production_caller(self) -> None:
        for module in self.manifest["p0_modules"]:
            with self.subTest(module=module):
                rows = [
                    row for row in self.rows
                    if row["implementation"] and module in row["implementation"]
                ]
                self.assertTrue(rows, f"no manifest row mentions {module}")
                self.assertTrue(
                    any(row["wiring_status"] == "WIRED" for row in rows),
                    f"{module} is a P0 module but no row records it as WIRED",
                )

    def test_unbuilt_capabilities_are_not_marked_ready(self) -> None:
        not_ready = {row["capability"] for row in self.rows if not row["third_sku_ready"]}
        for capability in (
            "automated commercial reviewer",
            "semantic / action grouping",
            "material capacity estimation",
            "spoken duration validation",
            "typography policy validation",
            "audio plan contract",
            "executable timeline contract",
            "material and candidate identity",
            "read-only picture measurement",
            "product authenticity protection",
        ):
            with self.subTest(capability=capability):
                self.assertIn(capability, not_ready)

    def test_the_four_execution_boundaries_are_ready_and_runtime_proven(self) -> None:
        """Phase 6: these four are ready because the chain produced and verified output."""

        for capability in (
            "picture execution",
            "typography execution",
            "audio rendering and mixing",
            "packaging, encode/remux, final master",
        ):
            with self.subTest(capability=capability):
                row = next(r for r in self.rows if r["capability"] == capability)
                self.assertTrue(row["third_sku_ready"])
                self.assertTrue(row["dimensions"]["EXECUTOR_AVAILABLE"])
                self.assertTrue(row["dimensions"]["END_TO_END_REACHABLE"])
                self.assertIn("Runtime-proven", row["notes"])

    def test_implemented_alone_does_not_imply_reachable(self) -> None:
        """The specific Phase 2B error, guarded by construction."""

        offenders = [
            row["capability"]
            for row in self.rows
            if row["dimensions"]["IMPLEMENTED"]
            and not row["dimensions"]["END_TO_END_REACHABLE"]
        ]
        self.assertTrue(
            offenders,
            "at least one implemented-but-unreachable capability should exist; if this "
            "is empty the manifest may be overstating reachability",
        )

    def test_the_manifest_agrees_with_the_execution_contracts(self) -> None:
        names = {c.name for c in execution_contracts.CONTRACTS}
        self.assertEqual(names, {"picture", "typography", "audio", "assemble_master"})
        notes = " ".join(row["notes"] for row in self.rows)
        for name in names:
            with self.subTest(contract=name):
                self.assertIn(name, notes)

    def test_the_manifest_agrees_with_the_producer_registry(self) -> None:
        known = set(producer_registry.REQUIRED_INPUT_ARTIFACTS) | set(
            producer_registry.AUTO_ARTIFACTS
        )
        named = {row["producer"] for row in self.rows if row["producer"]}
        self.assertTrue(
            named <= known,
            f"manifest names producers the registry does not know: {sorted(named - known)}",
        )
        for artifact in named:
            with self.subTest(artifact=artifact):
                producer_registry.producer_for(artifact)


if __name__ == "__main__":
    unittest.main()
