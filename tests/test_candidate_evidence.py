from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from src.ai_autocut.candidate_evidence import (
    SCHEMA_VERSION,
    CandidateEvidenceContractError,
    EvidenceStatus,
    candidate_evidence_reference,
    parse_candidate_evidence,
    render_candidate_evidence,
    validate_candidate_evidence,
    validate_candidate_evidence_reference,
)
from src.ai_autocut.candidate_pool import CandidatePool, parse_candidate_pool
from src.ai_autocut.identity import CandidateIdentity, parse_identity_catalog


# Probe paths are assembled from fragments on purpose: this repository is scanned
# by the path-hygiene test, which would otherwise flag this module's own probe.
def absolute(*parts: str) -> str:
    """Build an absolute POSIX path without writing a literal prefix."""

    return "/" + "/".join(parts)


FIXTURES = Path(__file__).parent / "fixtures"
IDENTITY_FIXTURE = FIXTURES / "vnext_identity_catalog_v1_valid.json"
POOL_FIXTURE = FIXTURES / "vnext_candidate_pool_v1_valid.json"
EVIDENCE_FIXTURE = FIXTURES / "candidate_evidence_v1_valid.json"
CONTRACT = (
    Path(__file__).parents[1] / "docs" / "contracts" / "candidate-evidence-v1.md"
)

CANDIDATE_KEYS = (
    "candidate_id",
    "status",
    "observations",
    "action_evidence",
    "claims",
    "evidence_type",
    "confidence",
    "provenance",
    "role_affinities",
    "risks",
    "rationale",
)


class CandidateEvidenceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = parse_identity_catalog(json.loads(IDENTITY_FIXTURE.read_text()))
        self.pool = parse_candidate_pool(json.loads(POOL_FIXTURE.read_text()))
        self.raw = json.loads(EVIDENCE_FIXTURE.read_text())
        self.evidence = parse_candidate_evidence(self.raw)

    def payload(self) -> dict:
        return copy.deepcopy(self.raw)

    def candidate(self, start_frame: int) -> CandidateIdentity:
        for item in self.catalog.candidates:
            if item.start_frame == start_frame:
                return item
        raise AssertionError("fixture candidate is missing")

    def entry(self, payload: dict, start_frame: int) -> dict:
        target = self.candidate(start_frame).candidate_id
        for item in payload["entries"]:
            if item["candidate_id"] == target:
                return item
        raise AssertionError("fixture entry is missing")

    def analyzed_entry(self, payload: dict) -> dict:
        return self.entry(payload, 100)


class RoundTripTests(CandidateEvidenceTestCase):
    def test_canonical_fixture_parses_and_matches_renderer(self) -> None:
        raw_text = EVIDENCE_FIXTURE.read_text(encoding="utf-8")
        self.assertEqual(render_candidate_evidence(self.evidence), raw_text)
        self.assertEqual(parse_candidate_evidence(json.loads(raw_text)), self.evidence)

    def test_fixture_validates_against_pool_and_identity(self) -> None:
        resolved = validate_candidate_evidence(self.evidence, self.pool, self.catalog)
        self.assertEqual(len(resolved), len(self.pool.entries))
        self.assertEqual(
            [item.candidate_id for item in resolved],
            [entry.candidate_id for entry in self.pool.entries],
        )

    def test_serialization_is_stable_and_entry_order_independent(self) -> None:
        reversed_payload = self.payload()
        reversed_payload["entries"].reverse()
        shuffled = self.payload()
        shuffled["product_facts"]["allowed_fact_refs"].reverse()
        entry = self.analyzed_entry(shuffled)
        entry["provenance"].reverse()
        entry["role_affinities"].reverse()
        entry["claims"][0]["provenance"].reverse()
        first = render_candidate_evidence(self.evidence)
        for payload in (reversed_payload, shuffled):
            with self.subTest(payload=payload["entries"][0]["candidate_id"]):
                self.assertEqual(
                    render_candidate_evidence(parse_candidate_evidence(payload)), first
                )
        self.assertEqual(render_candidate_evidence(self.evidence), first)

    def test_reference_binds_exact_rendered_bytes(self) -> None:
        raw_text = EVIDENCE_FIXTURE.read_text(encoding="utf-8")
        reference = candidate_evidence_reference(self.evidence)
        self.assertEqual(reference.ref, "analysis/candidate_evidence.json")
        validate_candidate_evidence_reference(self.evidence, raw_text)
        with self.assertRaises(CandidateEvidenceContractError):
            validate_candidate_evidence_reference(
                self.evidence, raw_text.replace("0.72", "0.73")
            )

    def test_evidence_json_carries_no_candidate_pool_or_plan_fields(self) -> None:
        rendered = render_candidate_evidence(self.evidence)
        for marker in ("plan_id", "planv1_", "segments", "pool_entry", "trim_range"):
            self.assertNotIn(marker, rendered)
        document = json.loads(rendered)
        self.assertEqual(
            sorted(document),
            ["analysis_run", "candidate_pool_id", "entries", "product_facts", "schema_version"],
        )
        self.assertEqual(document["schema_version"], SCHEMA_VERSION)
        for entry in document["entries"]:
            self.assertEqual(tuple(sorted(entry)), tuple(sorted(CANDIDATE_KEYS)))


class ExactKeyTests(CandidateEvidenceTestCase):
    def test_document_and_nested_keys_are_closed(self) -> None:
        unknown_top = self.payload()
        unknown_top["score"] = 1.0
        unknown_entry = self.payload()
        self.analyzed_entry(unknown_entry)["semantic_label"] = "hero"
        unknown_observation = self.payload()
        self.analyzed_entry(unknown_observation)["observations"]["analysis"] = "x"
        unknown_claim = self.payload()
        self.analyzed_entry(unknown_claim)["claims"][0]["approval"] = "ACCEPTED"
        missing_key = self.payload()
        del self.analyzed_entry(missing_key)["confidence"]
        unknown_run = self.payload()
        unknown_run["analysis_run"]["temperature"] = 0.2
        for payload in (
            unknown_top,
            unknown_entry,
            unknown_observation,
            unknown_claim,
            missing_key,
            unknown_run,
        ):
            with self.subTest(payload=sorted(payload["analysis_run"])):
                with self.assertRaises(CandidateEvidenceContractError):
                    parse_candidate_evidence(payload)

    def test_schema_version_is_enforced(self) -> None:
        payload = self.payload()
        payload["schema_version"] = "candidate_evidence.v2"
        with self.assertRaisesRegex(CandidateEvidenceContractError, "schema_version"):
            parse_candidate_evidence(payload)


class CardinalityTests(CandidateEvidenceTestCase):
    def test_missing_pool_member_fails_closed(self) -> None:
        payload = self.payload()
        payload["entries"] = [
            item
            for item in payload["entries"]
            if item["candidate_id"] != self.candidate(900).candidate_id
        ]
        with self.assertRaisesRegex(CandidateEvidenceContractError, "every Pool member"):
            validate_candidate_evidence(
                parse_candidate_evidence(payload), self.pool, self.catalog
            )

    def test_candidate_outside_the_pool_fails_closed(self) -> None:
        payload = self.payload()
        extra = copy.deepcopy(self.entry(payload, 900))
        extra["candidate_id"] = "candv1_" + "0" * 64
        payload["entries"].append(extra)
        with self.assertRaisesRegex(CandidateEvidenceContractError, "outside the Pool"):
            validate_candidate_evidence(
                parse_candidate_evidence(payload), self.pool, self.catalog
            )

    def test_unknown_pool_and_unknown_candidate_fail_closed(self) -> None:
        with self.assertRaisesRegex(CandidateEvidenceContractError, "pool_id"):
            validate_candidate_evidence(
                self.evidence, CandidatePool.create(()), self.catalog
            )
        orphan = "candv1_" + "1" * 64
        pool = CandidatePool.create(
            [entry.candidate_id for entry in self.pool.entries] + [orphan]
        )
        with self.assertRaises(CandidateEvidenceContractError):
            validate_candidate_evidence(self.evidence, pool, self.catalog)

    def test_duplicate_candidate_entry_fails_closed(self) -> None:
        payload = self.payload()
        duplicate = copy.deepcopy(self.analyzed_entry(payload))
        payload["entries"].append(duplicate)
        with self.assertRaisesRegex(CandidateEvidenceContractError, "duplicate"):
            parse_candidate_evidence(payload)

    def test_every_pool_member_needs_an_explicit_status(self) -> None:
        statuses = {
            item["candidate_id"]: item["status"] for item in self.raw["entries"]
        }
        self.assertEqual(len(statuses), len(self.pool.entries))
        self.assertIn(EvidenceStatus.UNKNOWN.value, set(statuses.values()))
        unknown = self.evidence.entry_for(self.candidate(900).candidate_id)
        self.assertIs(unknown.status, EvidenceStatus.UNKNOWN)
        self.assertIsNone(unknown.observations)
        self.assertTrue(unknown.rationale)

    def test_unanalysed_entry_must_not_carry_semantic_payload(self) -> None:
        payload = self.payload()
        entry = self.entry(payload, 900)
        entry["confidence"] = 0.5
        with self.assertRaisesRegex(CandidateEvidenceContractError, "not ANALYZED"):
            parse_candidate_evidence(payload)

    def test_analyzed_entry_missing_payload_fails_closed(self) -> None:
        payload = self.payload()
        self.analyzed_entry(payload)["confidence"] = None
        with self.assertRaisesRegex(CandidateEvidenceContractError, "missing required"):
            parse_candidate_evidence(payload)
        payload = self.payload()
        self.analyzed_entry(payload)["observations"] = None
        with self.assertRaises(CandidateEvidenceContractError):
            parse_candidate_evidence(payload)


class ProvenanceTests(CandidateEvidenceTestCase):
    def test_out_of_range_provenance_fails_closed(self) -> None:
        payload = self.payload()
        self.analyzed_entry(payload)["provenance"] = [
            {"start_frame": 99, "end_frame_exclusive": 130}
        ]
        with self.assertRaisesRegex(CandidateEvidenceContractError, "exact Candidate"):
            validate_candidate_evidence(
                parse_candidate_evidence(payload), self.pool, self.catalog
            )

    def test_out_of_range_action_evidence_fails_closed(self) -> None:
        payload = self.payload()
        entry = self.analyzed_entry(payload)
        entry["provenance"] = [{"start_frame": 100, "end_frame_exclusive": 140}]
        entry["action_evidence"] = [
            {
                "preparation_start": 100,
                "action_onset": 108,
                "action_completion": 124,
                "result_end_exclusive": 140,
            }
        ]
        with self.assertRaisesRegex(CandidateEvidenceContractError, "action_evidence"):
            validate_candidate_evidence(
                parse_candidate_evidence(payload), self.pool, self.catalog
            )

    def test_out_of_range_direct_claim_provenance_fails_closed(self) -> None:
        payload = self.payload()
        self.analyzed_entry(payload)["claims"][0]["provenance"] = [
            {"start_frame": 100, "end_frame_exclusive": 131}
        ]
        with self.assertRaisesRegex(CandidateEvidenceContractError, "exact Candidate"):
            validate_candidate_evidence(
                parse_candidate_evidence(payload), self.pool, self.catalog
            )

    def test_analyzed_entry_requires_cited_frames(self) -> None:
        payload = self.payload()
        self.analyzed_entry(payload)["provenance"] = []
        with self.assertRaisesRegex(CandidateEvidenceContractError, "provenance"):
            parse_candidate_evidence(payload)

    def test_missing_direct_provenance_fails_closed(self) -> None:
        payload = self.payload()
        self.analyzed_entry(payload)["claims"][0]["provenance"] = []
        with self.assertRaisesRegex(CandidateEvidenceContractError, "DIRECT claim"):
            parse_candidate_evidence(payload)

    def test_illegal_action_chronology_fails_closed(self) -> None:
        payload = self.payload()
        self.analyzed_entry(payload)["action_evidence"] = [
            {
                "preparation_start": 100,
                "action_onset": 124,
                "action_completion": 108,
                "result_end_exclusive": 130,
            }
        ]
        with self.assertRaisesRegex(CandidateEvidenceContractError, "chronology"):
            parse_candidate_evidence(payload)

    def test_overlapping_actions_fail_closed(self) -> None:
        payload = self.payload()
        self.analyzed_entry(payload)["action_evidence"] = [
            {
                "preparation_start": 100,
                "action_onset": 104,
                "action_completion": 118,
                "result_end_exclusive": 124,
            },
            {
                "preparation_start": 120,
                "action_onset": 124,
                "action_completion": 127,
                "result_end_exclusive": 130,
            },
        ]
        with self.assertRaisesRegex(CandidateEvidenceContractError, "overlap"):
            parse_candidate_evidence(payload)

    def test_action_evidence_must_lie_inside_cited_frames(self) -> None:
        payload = self.payload()
        entry = self.analyzed_entry(payload)
        entry["provenance"] = [{"start_frame": 110, "end_frame_exclusive": 130}]
        entry["claims"][0]["provenance"] = [{"start_frame": 110, "end_frame_exclusive": 130}]
        with self.assertRaisesRegex(CandidateEvidenceContractError, "cited provenance"):
            parse_candidate_evidence(payload)

    def test_direct_claim_may_cite_fewer_frames_than_the_entry(self) -> None:
        payload = self.payload()
        entry = self.analyzed_entry(payload)
        entry["claims"][0]["provenance"] = [
            {"start_frame": 104, "end_frame_exclusive": 120}
        ]
        evidence = parse_candidate_evidence(payload)
        validate_candidate_evidence(evidence, self.pool, self.catalog)
        claim = evidence.entry_for(self.candidate(100).candidate_id).claims[0]
        self.assertEqual(claim.provenance[0].start_frame, 104)

    def test_gapped_provenance_cannot_carry_an_action(self) -> None:
        payload = self.payload()
        entry = self.analyzed_entry(payload)
        entry["provenance"] = [
            {"start_frame": 100, "end_frame_exclusive": 112},
            {"start_frame": 118, "end_frame_exclusive": 130},
        ]
        entry["claims"][0]["provenance"] = [
            {"start_frame": 100, "end_frame_exclusive": 112}
        ]
        with self.assertRaisesRegex(CandidateEvidenceContractError, "cited provenance"):
            parse_candidate_evidence(payload)


class ClaimAndVocabularyTests(CandidateEvidenceTestCase):
    def test_unsupported_product_fact_reference_fails_closed(self) -> None:
        payload = self.payload()
        self.analyzed_entry(payload)["claims"][0]["product_fact_ref"] = (
            "fact_direct_drinking"
        )
        with self.assertRaisesRegex(CandidateEvidenceContractError, "not permitted"):
            validate_candidate_evidence(
                parse_candidate_evidence(payload), self.pool, self.catalog
            )

    def test_malformed_claim_reference_fails_closed(self) -> None:
        for value in (absolute("Users", "someone", "fact.json"), "fact with space", "", 12):
            payload = self.payload()
            self.analyzed_entry(payload)["claims"][0]["product_fact_ref"] = value
            with self.subTest(value=value):
                with self.assertRaises(CandidateEvidenceContractError):
                    parse_candidate_evidence(payload)

    def test_unknown_support_and_evidence_type_fail_closed(self) -> None:
        for field, value in (
            ("support", "PROVEN"),
            ("support", "direct"),
            ("support", "WHY_KEEP"),
        ):
            payload = self.payload()
            self.analyzed_entry(payload)["claims"][0][field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(CandidateEvidenceContractError):
                    parse_candidate_evidence(payload)
        payload = self.payload()
        self.analyzed_entry(payload)["evidence_type"] = "SCORE"
        with self.assertRaises(CandidateEvidenceContractError):
            parse_candidate_evidence(payload)

    def test_confidence_bounds_and_type_are_enforced(self) -> None:
        for value in (-0.01, 1.01, "0.5", None, True, float("nan"), float("inf")):
            payload = self.payload()
            self.analyzed_entry(payload)["confidence"] = value
            with self.subTest(value=value):
                with self.assertRaises(CandidateEvidenceContractError):
                    parse_candidate_evidence(payload)
        for value in (0.0, 0.5, 1, 1.0):
            payload = self.payload()
            self.analyzed_entry(payload)["confidence"] = value
            with self.subTest(value=value):
                parse_candidate_evidence(payload)

    def test_unusable_frames_cannot_carry_direct_evidence(self) -> None:
        payload = self.payload()
        entry = self.analyzed_entry(payload)
        entry["observations"]["visual_usability"] = "UNUSABLE"
        with self.assertRaisesRegex(CandidateEvidenceContractError, "UNUSABLE"):
            parse_candidate_evidence(payload)

    def test_evidence_type_none_forbids_direct_support(self) -> None:
        payload = self.payload()
        entry = self.analyzed_entry(payload)
        entry["evidence_type"] = "NONE"
        with self.assertRaisesRegex(CandidateEvidenceContractError, "DIRECT claim"):
            parse_candidate_evidence(payload)

    def test_direct_demonstration_class_requires_a_direct_claim(self) -> None:
        payload = self.payload()
        self.entry(payload, 500)["observations"]["claim_support_class"] = (
            "DIRECT_DEMONSTRATION"
        )
        with self.assertRaisesRegex(CandidateEvidenceContractError, "DIRECT claim"):
            parse_candidate_evidence(payload)

    def test_action_evidence_requires_an_observable_result(self) -> None:
        payload = self.payload()
        self.analyzed_entry(payload)["observations"]["visible_result"] = None
        with self.assertRaisesRegex(CandidateEvidenceContractError, "visible_result"):
            parse_candidate_evidence(payload)

    def test_risk_vocabulary_is_finite(self) -> None:
        payload = self.payload()
        self.entry(payload, 800)["risks"][0]["code"] = "LOOKS_BAD"
        with self.assertRaises(CandidateEvidenceContractError):
            parse_candidate_evidence(payload)
        payload = self.payload()
        self.entry(payload, 800)["risks"][0]["severity"] = "CATASTROPHIC"
        with self.assertRaises(CandidateEvidenceContractError):
            parse_candidate_evidence(payload)

    def test_role_affinity_vocabulary_is_finite_and_unique(self) -> None:
        payload = self.payload()
        self.analyzed_entry(payload)["role_affinities"] = ["ACTION", "ACTION"]
        with self.assertRaises(CandidateEvidenceContractError):
            parse_candidate_evidence(payload)
        payload = self.payload()
        self.analyzed_entry(payload)["role_affinities"] = ["SCORE"]
        with self.assertRaises(CandidateEvidenceContractError):
            parse_candidate_evidence(payload)

    def test_run_metadata_shape_is_enforced(self) -> None:
        for field, value in (
            ("run_id", absolute("Users", "someone", "run")),
            ("run_id", ""),
            ("provider", "local provider"),
            ("model", None),
            ("prompt_contract_version", "candidate_evidence_prompt"),
            ("prompt_contract_version", "CandidateEvidencePrompt.v1"),
        ):
            payload = self.payload()
            payload["analysis_run"][field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(CandidateEvidenceContractError):
                    parse_candidate_evidence(payload)

    def test_product_fact_allow_list_must_be_well_formed(self) -> None:
        payload = self.payload()
        payload["product_facts"]["allowed_fact_refs"] = []
        with self.assertRaises(CandidateEvidenceContractError):
            parse_candidate_evidence(payload)
        payload = self.payload()
        payload["product_facts"]["allowed_fact_refs"] = ["fact_a", "fact_a"]
        with self.assertRaises(CandidateEvidenceContractError):
            parse_candidate_evidence(payload)
        payload = self.payload()
        payload["product_facts"]["sha256"] = "0" * 63
        with self.assertRaises(CandidateEvidenceContractError):
            parse_candidate_evidence(payload)
        payload = self.payload()
        payload["product_facts"]["ref"] = absolute("Users", "someone", "facts.json")
        with self.assertRaises(CandidateEvidenceContractError):
            parse_candidate_evidence(payload)


class PathLeakageTests(CandidateEvidenceTestCase):
    def test_machine_paths_never_enter_the_document(self) -> None:
        rendered = render_candidate_evidence(self.evidence)
        for marker in ("/Users/", "file://", "\\\\", "/tmp/"):
            self.assertNotIn(marker, rendered)

    def test_path_like_candidate_is_not_echoed_in_error(self) -> None:
        payload = self.payload()
        private = "/private/candidate.mov"
        self.analyzed_entry(payload)["candidate_id"] = private
        with self.assertRaises(CandidateEvidenceContractError) as caught:
            parse_candidate_evidence(payload)
        self.assertNotIn(private, str(caught.exception))


class ContractDocumentTests(CandidateEvidenceTestCase):
    def test_contract_document_states_contract_only_status(self) -> None:
        text = CONTRACT.read_text(encoding="utf-8")
        self.assertIn("`candidate_evidence.v1`", text)
        self.assertIn("src/ai_autocut/candidate_evidence.py", text)
        self.assertIn("tests/fixtures/candidate_evidence_v1_valid.json", text)
        self.assertIn("CONTRACT EXISTS", text)
        self.assertIn("does not yet exist", text)
        self.assertIn("DIRECT", text)
        self.assertIn("Product Fact", text)


if __name__ == "__main__":
    unittest.main()
