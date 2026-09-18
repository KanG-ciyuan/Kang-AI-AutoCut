"""The artifact producer registry.

Independent inspection found that required artifacts had **undefined producers**, which
made the fast path a validation harness around preconstructed artifacts rather than a
runner. These tests hold the fix: every required artifact has exactly one explicit
producer, of a declared kind, and a stage never proceeds or fails vaguely when that
producer has not acted.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from src.ai_autocut import fast_path
from src.ai_autocut.intervention_ledger import INTERVENTION_KINDS
from src.ai_autocut.producer_registry import (
    AUTO_ARTIFACTS,
    PRODUCERS,
    PRODUCER_BY_ARTIFACT,
    PRODUCER_TYPES,
    Producer,
    ProducerRegistryError,
    REQUIRED_INPUT_ARTIFACTS,
    gate_for,
    producer_for,
    registry_document,
)

#: The artifacts the brief requires to be covered.
REQUIRED_COVERAGE = (
    "source_inventory.json",
    "shots/placements.json",
    "edit/timeline_ranges.json",
    "picture/measurements.json",
    "picture/source_ranges.json",
    "copy/commercial_units.json",
    "audio/placement.json",
    "audio/sync_expectations.json",
    "review/review.json",
    "assemble/assembly_evidence.json",
    "release/human_release.json",
)


class CoverageTests(unittest.TestCase):
    def test_every_required_artifact_has_exactly_one_producer(self) -> None:
        for artifact in REQUIRED_COVERAGE:
            with self.subTest(artifact=artifact):
                self.assertIn(artifact, PRODUCER_BY_ARTIFACT)

    def test_no_required_artifact_has_an_unknown_producer(self) -> None:
        for artifact in REQUIRED_COVERAGE:
            with self.subTest(artifact=artifact):
                self.assertIn(producer_for(artifact).producer_type, PRODUCER_TYPES)

    def test_no_artifact_is_registered_twice(self) -> None:
        names = [producer.artifact for producer in PRODUCERS]
        self.assertEqual(len(names), len(set(names)))

    def test_an_unregistered_artifact_is_a_hard_error(self) -> None:
        with self.assertRaises(ProducerRegistryError) as caught:
            producer_for("invented/artifact.json")
        self.assertIn("NO PRODUCER", str(caught.exception))

    def test_auto_artifacts_are_recognised(self) -> None:
        for artifact in AUTO_ARTIFACTS:
            with self.subTest(artifact=artifact):
                self.assertEqual(producer_for(artifact).producer_type, "AUTO")


class ProducerShapeTests(unittest.TestCase):
    def test_every_producer_states_its_full_contract(self) -> None:
        for producer in PRODUCERS:
            with self.subTest(artifact=producer.artifact):
                for field_name in (
                    "artifact", "stage", "producer_type", "producer_id",
                    "required_inputs", "output_contract", "evidence",
                    "intervention_kind", "resume_condition", "procedure",
                ):
                    value = getattr(producer, field_name)
                    self.assertIsNotNone(value)

    def test_every_producer_states_a_procedure(self) -> None:
        """A remembered command is not a procedure."""

        for producer in PRODUCERS:
            with self.subTest(artifact=producer.artifact):
                self.assertGreater(len(producer.procedure.strip()), 40)

    def test_every_producer_states_a_resume_condition(self) -> None:
        for producer in PRODUCERS:
            with self.subTest(artifact=producer.artifact):
                self.assertTrue(producer.resume_condition.strip())

    def test_every_producer_has_evidence_requirements(self) -> None:
        for producer in PRODUCERS:
            with self.subTest(artifact=producer.artifact):
                self.assertTrue(producer.evidence)

    def test_every_producer_declares_a_valid_ledger_kind(self) -> None:
        for producer in PRODUCERS:
            with self.subTest(artifact=producer.artifact):
                self.assertIn(producer.intervention_kind, INTERVENTION_KINDS)

    def test_every_producer_names_a_real_stage(self) -> None:
        for producer in PRODUCERS:
            with self.subTest(artifact=producer.artifact):
                self.assertIn(producer.stage, fast_path.SEMANTIC_STAGES)

    def test_only_auto_producers_avoid_a_gate(self) -> None:
        for producer in PRODUCERS:
            with self.subTest(artifact=producer.artifact):
                self.assertEqual(producer.requires_gate, producer.producer_type != "AUTO")

    def test_an_unknown_producer_type_is_refused(self) -> None:
        with self.assertRaises(ProducerRegistryError):
            Producer(
                artifact="x.json", stage="PREPARE", producer_type="MAGIC",
                producer_id="x", required_inputs=(), output_contract="x",
                validated_by="", evidence=("x",), intervention_kind="SUPERVISOR_DECISIONS",
                resume_condition="x", procedure="a procedure that is long enough to pass",
            )

    def test_a_producer_without_a_procedure_is_refused(self) -> None:
        with self.assertRaises(ProducerRegistryError):
            Producer(
                artifact="x.json", stage="PREPARE", producer_type="CODEX",
                producer_id="x", required_inputs=(), output_contract="x",
                validated_by="", evidence=("x",), intervention_kind="SUPERVISOR_DECISIONS",
                resume_condition="x", procedure="   ",
            )


class GateTests(unittest.TestCase):
    def test_a_gate_names_everything_a_producer_needs(self) -> None:
        gate = gate_for("copy/commercial_units.json", "/tmp/job")
        for key in (
            "producer_type", "producer_id", "required_inputs", "output_contract",
            "evidence", "intervention_kind", "resume_condition", "procedure",
            "missing_artifact", "output_path", "action_required",
        ):
            with self.subTest(key=key):
                self.assertIn(key, gate)

    def test_a_gate_points_at_the_artifact_path(self) -> None:
        gate = gate_for("copy/commercial_units.json", "/tmp/job")
        self.assertEqual(gate["output_path"], "/tmp/job/copy/commercial_units.json")

    def test_a_gate_says_who_must_act(self) -> None:
        gate = gate_for("copy/commercial_units.json", "/tmp/job")
        self.assertIn("CODEX", gate["action_required"])
        self.assertIn("copy-planner", gate["action_required"])

    def test_gating_an_unknown_artifact_is_refused(self) -> None:
        with self.assertRaises(ProducerRegistryError):
            gate_for("nope.json", "/tmp/job")


class StageCoverageTests(unittest.TestCase):
    def test_every_gated_stage_input_has_a_producer(self) -> None:
        """A stage must never declare an input that nothing is responsible for."""

        for stage in fast_path.STAGES:
            for artifact in stage.inputs:
                with self.subTest(stage=stage.name, artifact=artifact):
                    self.assertIsNotNone(producer_for(artifact))

    def test_the_required_input_list_matches_the_gated_artifacts(self) -> None:
        self.assertEqual(
            set(REQUIRED_INPUT_ARTIFACTS),
            {p.artifact for p in PRODUCERS if p.producer_type != "AUTO"},
        )


class RegistryDocumentTests(unittest.TestCase):
    def test_the_document_is_serialisable(self) -> None:
        document = registry_document()
        self.assertEqual(document["schema_version"], "artifact_producer_registry.v1")
        self.assertEqual(len(document["producers"]), len(PRODUCERS))
        self.assertIn("rule", document)

    def test_the_document_states_the_rule(self) -> None:
        document = registry_document()
        self.assertIn("NO PRODUCER", document["rule"])


if __name__ == "__main__":
    unittest.main()
