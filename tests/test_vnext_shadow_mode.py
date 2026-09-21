"""Mode-scoped artifact ownership: LEGACY and VNEXT_SHADOW cannot drift into each other.

The risk this holds shut
------------------------
Phase 2 adds artifacts for Editing Intelligence vNext. If they entered the legacy
registry, the eight-stage production fast path would start requiring Candidate
Evidence, and a shadow experiment would have silently changed production. The two
registries are therefore separate values, and this file asserts the separation in
both directions rather than trusting a comment.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from src.ai_autocut import authoring, fast_path, producer_registry
from src.ai_autocut.candidate_evidence import CANONICAL_REF as CANDIDATE_EVIDENCE_REF


class RegistryShapeTests(unittest.TestCase):
    def test_every_shadow_artifact_has_exactly_one_producer(self) -> None:
        artifacts = [
            producer.artifact for producer in producer_registry.VNEXT_SHADOW_PRODUCERS
        ]
        self.assertEqual(len(artifacts), len(set(artifacts)))
        for artifact in producer_registry.VNEXT_SHADOW_ARTIFACTS:
            with self.subTest(artifact=artifact):
                self.assertEqual(
                    producer_registry.vnext_producer_for(artifact).artifact, artifact
                )

    def test_every_shadow_producer_states_its_full_contract(self) -> None:
        for producer in producer_registry.VNEXT_SHADOW_PRODUCERS:
            with self.subTest(artifact=producer.artifact):
                self.assertGreater(len(producer.procedure.strip()), 40)
                self.assertTrue(producer.resume_condition.strip())
                self.assertTrue(producer.evidence)
                self.assertIn(producer.stage, producer_registry.VNEXT_SHADOW_STAGES)
                self.assertIn(
                    producer.producer_type, producer_registry.PRODUCER_TYPES
                )

    def test_shadow_stages_are_not_legacy_stages(self) -> None:
        for stage in producer_registry.VNEXT_SHADOW_STAGES:
            with self.subTest(stage=stage):
                self.assertNotIn(stage, fast_path.SEMANTIC_STAGES)

    def test_the_two_registries_do_not_overlap(self) -> None:
        legacy = set(producer_registry.PRODUCER_BY_ARTIFACT) | set(
            producer_registry.AUTO_ARTIFACTS
        )
        shadow = set(producer_registry.VNEXT_SHADOW_ARTIFACTS)
        self.assertEqual(legacy & shadow, set())
        self.assertEqual(set(producer_registry.REQUIRED_INPUT_ARTIFACTS) & shadow, set())

    def test_the_legacy_document_is_unchanged_by_the_shadow_registry(self) -> None:
        document = producer_registry.registry_document()
        self.assertEqual(len(document["producers"]), len(producer_registry.PRODUCERS))
        rendered = str(document)
        for artifact in producer_registry.VNEXT_SHADOW_ARTIFACTS:
            self.assertNotIn(artifact, rendered)

    def test_the_shadow_document_is_separate_and_serialisable(self) -> None:
        document = producer_registry.vnext_registry_document()
        self.assertEqual(document["mode"], producer_registry.MODE_VNEXT_SHADOW)
        self.assertEqual(document["artifacts"], list(producer_registry.VNEXT_SHADOW_ARTIFACTS))
        self.assertEqual(len(document["producers"]), len(producer_registry.VNEXT_SHADOW_PRODUCERS))
        self.assertIn("explicit producer", str(document["rule"]))


class ModeIsolationTests(unittest.TestCase):
    def test_the_legacy_resolver_still_refuses_shadow_artifacts(self) -> None:
        for artifact in producer_registry.VNEXT_SHADOW_ARTIFACTS:
            with self.subTest(artifact=artifact):
                with self.assertRaises(producer_registry.ProducerRegistryError) as caught:
                    producer_registry.producer_for(artifact)
                self.assertIn("NO PRODUCER", str(caught.exception))

    def test_the_shadow_resolver_refuses_legacy_artifacts(self) -> None:
        for artifact in (
            "copy/commercial_units.json",
            "release/human_release.json",
            "source_inventory.json",
            "edit/editing_plan.json",
        ):
            with self.subTest(artifact=artifact):
                with self.assertRaises(producer_registry.ModeScopeError):
                    producer_registry.vnext_producer_for(artifact)

    def test_an_unknown_artifact_is_refused_in_both_modes(self) -> None:
        with self.assertRaises(producer_registry.ProducerRegistryError):
            producer_registry.producer_for("invented/artifact.json")
        with self.assertRaises(producer_registry.ModeScopeError):
            producer_registry.vnext_producer_for("invented/artifact.json")

    def test_mode_lookup_names_the_owner(self) -> None:
        self.assertEqual(
            producer_registry.mode_of("source_inventory.json"),
            producer_registry.MODE_LEGACY,
        )
        self.assertEqual(
            producer_registry.mode_of(producer_registry.CANDIDATE_EVIDENCE_ARTIFACT),
            producer_registry.MODE_VNEXT_SHADOW,
        )
        self.assertIsNone(producer_registry.mode_of("invented/artifact.json"))

    def test_no_legacy_stage_requires_a_shadow_artifact(self) -> None:
        shadow = set(producer_registry.VNEXT_SHADOW_ARTIFACTS)
        for stage in fast_path.STAGES:
            for artifact in stage.inputs:
                with self.subTest(stage=stage.name, artifact=artifact):
                    self.assertNotIn(artifact, shadow)
            for artifact in stage.outputs:
                with self.subTest(stage=stage.name, output=artifact):
                    self.assertNotIn(artifact, shadow)

    def test_legacy_authoring_is_unchanged(self) -> None:
        action, producer = authoring.action_for("copy/commercial_units.json")
        self.assertEqual(action, authoring.ACTION_AUTHOR)
        self.assertEqual(producer.producer_id, "copy-planner")
        request = authoring.request_for("copy/commercial_units.json", "/tmp/job")
        self.assertEqual(request.artifact, "copy/commercial_units.json")
        self.assertEqual(request.stage, producer.stage)
        self.assertEqual(request.output_contract, producer.output_contract)

    def test_shadow_authoring_resolves_through_its_own_registry(self) -> None:
        artifact = producer_registry.CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT
        action, producer = authoring.action_for_vnext(artifact)
        self.assertEqual(action, authoring.ACTION_EXECUTE)
        self.assertEqual(producer.producer_type, "ADAPTER")
        request = authoring.request_for_vnext(artifact, "/tmp/shadow-job")
        self.assertEqual(request.artifact, artifact)
        self.assertEqual(
            set(request.required_inputs),
            {producer_registry.CANDIDATE_ANALYSIS_REQUEST_ARTIFACT},
        )
        self.assertEqual(request.stage, "ANALYZE CANDIDATES")

    def test_a_shadow_gate_names_everything_a_producer_needs(self) -> None:
        gate = producer_registry.vnext_gate_for(
            producer_registry.CANDIDATE_WINDOW_PROPOSAL_ARTIFACT, "/tmp/shadow-job"
        )
        for key in (
            "mode",
            "producer_type",
            "producer_id",
            "required_inputs",
            "output_contract",
            "evidence",
            "procedure",
            "missing_artifact",
            "output_path",
            "action_required",
        ):
            with self.subTest(key=key):
                self.assertIn(key, gate)
        self.assertEqual(gate["mode"], producer_registry.MODE_VNEXT_SHADOW)
        self.assertEqual(
            gate["output_path"],
            "/tmp/shadow-job/analysis/candidate_window_proposal.json",
        )

    def test_only_auto_shadow_artifacts_avoid_a_gate(self) -> None:
        for producer in producer_registry.VNEXT_SHADOW_PRODUCERS:
            with self.subTest(artifact=producer.artifact):
                self.assertEqual(
                    producer.requires_gate, producer.producer_type != "AUTO"
                )


class ContractAlignmentTests(unittest.TestCase):
    def test_the_evidence_artifact_is_the_phase_1_canonical_path(self) -> None:
        self.assertEqual(
            producer_registry.CANDIDATE_EVIDENCE_ARTIFACT, CANDIDATE_EVIDENCE_REF
        )
        self.assertEqual(
            producer_registry.CANDIDATE_EVIDENCE_ARTIFACT,
            "analysis/candidate_evidence.json",
        )

    def test_the_shadow_registry_owns_the_candidate_analysis_artifacts(self) -> None:
        self.assertEqual(
            set(producer_registry.VNEXT_SHADOW_ARTIFACTS),
            {
                "analysis/candidate_window_proposal.json",
                "analysis/candidate_analysis_request.json",
                "analysis/candidate_frame_evidence.json",
                "analysis/candidate_analysis_response.json",
                "analysis/candidate_extraction.json",
                "analysis/candidate_pool.json",
                "analysis/candidate_evidence.json",
            },
        )
        self.assertEqual(
            set(producer_registry.VNEXT_SHADOW_AUTO_ARTIFACTS),
            {
                "analysis/candidate_analysis_request.json",
                "analysis/candidate_extraction.json",
                "analysis/candidate_pool.json",
                "analysis/candidate_evidence.json",
            },
        )

    def test_the_analyzer_requires_the_request_and_not_a_frame_manifest(self) -> None:
        """The registry must not claim a runtime requirement the code does not enforce.

        Frame evidence is produced by the opt-in live-validation harness. The
        ANALYZE CANDIDATES stage neither reads nor requires it, so declaring it as an
        analyzer input would have implied that every analyzer saw traceable media.
        """

        producer = producer_registry.vnext_producer_for(
            producer_registry.CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT
        )
        self.assertEqual(
            set(producer.required_inputs),
            {producer_registry.CANDIDATE_ANALYSIS_REQUEST_ARTIFACT},
        )
        self.assertNotIn(
            producer_registry.CANDIDATE_FRAME_EVIDENCE_ARTIFACT,
            producer.required_inputs,
        )

    def test_frame_evidence_is_produced_by_the_harness_not_by_a_stage(self) -> None:
        producer = producer_registry.vnext_producer_for(
            producer_registry.CANDIDATE_FRAME_EVIDENCE_ARTIFACT
        )
        self.assertEqual(producer.producer_type, "ADAPTER")
        self.assertEqual(producer.producer_id, "live-validation-harness")
        self.assertIn(
            "scripts/phase25_live_validation.py", producer.procedure
        )
        self.assertIn("neither requires nor parses it", producer.procedure)
        self.assertNotIn(
            producer_registry.CANDIDATE_FRAME_EVIDENCE_ARTIFACT,
            producer_registry.VNEXT_SHADOW_AUTO_ARTIFACTS,
        )

    def test_the_shadow_registry_does_not_write_a_frozen_production_artifact(self) -> None:
        frozen = {
            "source_inventory.json",
            "shots/placements.json",
            "shots/shot_understanding.json",
            "edit/editing_plan.json",
            "edit/timeline_ranges.json",
            "copy/commercial_units.json",
            "review/review.json",
            "release/human_release.json",
        }
        self.assertEqual(set(producer_registry.VNEXT_SHADOW_ARTIFACTS) & frozen, set())


class ShadowDocumentationTests(unittest.TestCase):
    def test_the_contract_document_states_the_shadow_boundary(self) -> None:
        contract = (
            Path(__file__).parents[1]
            / "docs"
            / "contracts"
            / "candidate-extraction-and-analysis-v1.md"
        )
        text = contract.read_text(encoding="utf-8")
        self.assertIn("`candidate_window_proposal.v1`", text)
        self.assertIn("`candidate_analysis_response.v1`", text)
        self.assertIn("src/ai_autocut/candidate_extraction.py", text)
        self.assertIn("src/ai_autocut/candidate_analysis.py", text)
        self.assertIn("VNEXT_SHADOW", text)
        self.assertIn("this stage ends here", text)
        self.assertIn("Not wired into production", text)
        for rule in (
            "SINGLE_SEGMENT",
            "ADJACENT_MERGE",
            "ACTION_SAFE_WINDOW",
            "SHORTER_ACTION_WINDOW",
        ):
            self.assertIn(rule, text)

    def test_the_phase_2_fixtures_exist_and_are_named_unambiguously(self) -> None:
        fixtures = Path(__file__).parent / "fixtures"
        expected = {
            "phase2_identity_catalog_v1.json",
            "phase2_candidate_measurements_v1.json",
            "phase2_candidate_segmentations_v1.json",
            "phase2_candidate_window_proposal_v1.json",
            "phase2_claim_envelope_v1.json",
            "phase2_candidate_analysis_response_v1.json",
        }
        for name in expected:
            with self.subTest(name=name):
                self.assertTrue((fixtures / name).is_file())


if __name__ == "__main__":
    unittest.main()
