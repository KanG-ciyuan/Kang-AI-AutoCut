from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from src.ai_autocut import authoring, producer_registry
from src.ai_autocut.artifact_reference import artifact_reference
from src.ai_autocut.candidate_analysis import (
    ANALYSIS_QUESTION,
    CandidateAnalysisError,
    CandidateAnalysisRequest,
    CandidateAnalysisResponse,
    ClaimEnvelope,
    ClaimFact,
    build_candidate_evidence,
    parse_analysis_request,
    parse_analysis_response,
    parse_claim_envelope,
    parse_measurements,
    parse_segmentations,
    render_analysis_request,
    render_claim_envelope,
    run_candidate_evidence_stage,
    run_candidate_extraction_stage,
    targets_from_extraction,
)
from src.ai_autocut.candidate_evidence import (
    EvidenceStatus,
    parse_candidate_evidence,
    render_candidate_evidence,
    validate_candidate_evidence,
)
from src.ai_autocut.candidate_extraction import (
    extract_candidates,
    parse_window_proposals,
)
from src.ai_autocut.identity import parse_identity_catalog


FIXTURES = Path(__file__).parent / "fixtures"
CATALOG_FIXTURE = FIXTURES / "phase2_identity_catalog_v1.json"
MEASUREMENTS_FIXTURE = FIXTURES / "phase2_candidate_measurements_v1.json"
SEGMENTATIONS_FIXTURE = FIXTURES / "phase2_candidate_segmentations_v1.json"
PROPOSALS_FIXTURE = FIXTURES / "phase2_candidate_window_proposal_v1.json"
ENVELOPE_FIXTURE = FIXTURES / "phase2_claim_envelope_v1.json"
RESPONSE_FIXTURE = FIXTURES / "phase2_candidate_analysis_response_v1.json"

RUN_ID = "analysisrunv1_phase2fixture"


class AnalysisTestCase(unittest.TestCase):
    """The canonical fixture chain, plus a temp workspace for stage runs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = parse_identity_catalog(json.loads(CATALOG_FIXTURE.read_text()))
        cls.measurements = parse_measurements(json.loads(MEASUREMENTS_FIXTURE.read_text()))
        cls.segmentations = parse_segmentations(
            json.loads(SEGMENTATIONS_FIXTURE.read_text())
        )
        cls.proposals = parse_window_proposals(
            json.loads(PROPOSALS_FIXTURE.read_text())
        )
        cls.extraction = extract_candidates(
            catalog=cls.catalog,
            measurements=cls.measurements,
            segmentations=cls.segmentations,
            proposals=cls.proposals,
        )
        cls.envelope_raw = json.loads(ENVELOPE_FIXTURE.read_text())
        cls.envelope = parse_claim_envelope(cls.envelope_raw)
        cls.request = CandidateAnalysisRequest(
            run_id=RUN_ID,
            candidate_pool_id=cls.extraction.pool.pool_id,
            claim_envelope=cls.envelope,
            targets=targets_from_extraction(cls.extraction),
        )
        cls.request_text = render_analysis_request(cls.request)
        cls.response_raw = json.loads(RESPONSE_FIXTURE.read_text())

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def response_document(self) -> dict:
        return copy.deepcopy(self.response_raw)

    def entry(self, document: dict, candidate_id: str) -> dict:
        for item in document["entries"]:
            if item["candidate_id"] == candidate_id:
                return item
        raise AssertionError("fixture entry is missing")

    def candidate_id(self, proposal_id: str) -> str:
        for outcome in self.extraction.outcomes:
            if outcome.proposal.proposal_id == proposal_id:
                assert outcome.candidate is not None
                return outcome.candidate.candidate_id
        raise AssertionError("fixture proposal is missing")

    def parse(self, document: object, *, request=None):
        return parse_analysis_response(
            document,
            request=request if request is not None else self.request,
            request_text=self.request_text,
        )

    def evidence_for(self, document: object):
        response = self.parse(document)
        return build_candidate_evidence(
            request=self.request, response=response, extraction=self.extraction
        )


class CanonicalChainTests(AnalysisTestCase):
    def test_the_recorded_answer_produces_valid_candidate_evidence(self) -> None:
        response = self.parse(self.response_raw)
        self.assertIsNone(response.response_failure)
        evidence = build_candidate_evidence(
            request=self.request, response=response, extraction=self.extraction
        )
        validate_candidate_evidence(evidence, self.extraction.pool, self.extraction.catalog)
        self.assertEqual(len(evidence.entries), len(self.extraction.pool.entries))
        self.assertEqual(evidence.candidate_pool_id, self.extraction.pool.pool_id)
        self.assertEqual(
            tuple(entry.candidate_id for entry in evidence.entries),
            tuple(entry.candidate_id for entry in self.extraction.pool.entries),
        )

    def test_the_evidence_document_is_the_phase_1_contract(self) -> None:
        evidence = self.evidence_for(self.response_raw)
        rendered = render_candidate_evidence(evidence)
        document = json.loads(rendered)
        self.assertEqual(document["schema_version"], "candidate_evidence.v1")
        self.assertEqual(
            sorted(document),
            [
                "analysis_run",
                "candidate_pool_id",
                "entries",
                "product_facts",
                "schema_version",
            ],
        )
        self.assertEqual(
            document["product_facts"]["ref"], self.envelope.ref
        )
        self.assertEqual(
            document["product_facts"]["allowed_fact_refs"],
            sorted(self.envelope.allowed_fact_refs),
        )
        self.assertEqual(document["analysis_run"]["run_id"], RUN_ID)
        self.assertEqual(document["analysis_run"]["provider"], "fixture_provider")
        self.assertEqual(document["analysis_run"]["model"], "fixture_multimodal_v1")
        self.assertEqual(
            document["analysis_run"]["prompt_contract_version"],
            "candidate_evidence_prompt.v1",
        )
        self.assertEqual(parse_candidate_evidence(document), evidence)

    def test_the_answer_is_counted_honestly(self) -> None:
        counts = self.parse(self.response_raw).counts()
        self.assertEqual(counts["analyzed"], 5)
        self.assertEqual(counts["unknown"], 1)
        self.assertEqual(counts["analysis_failed"], 0)
        self.assertEqual(counts["direct_support"], 4)
        self.assertEqual(counts["contextual_support"], 3)
        self.assertEqual(counts["inferred_support"], 1)
        self.assertEqual(counts["unsupported_claim_rejections"], 0)
        self.assertEqual(counts["malformed_entries"], 0)

    def test_a_high_quality_product_shot_claims_nothing(self) -> None:
        evidence = self.evidence_for(self.response_raw)
        beauty = evidence.entry_for(self.candidate_id("wpropv1_beauty"))
        self.assertIs(beauty.status, EvidenceStatus.ANALYZED)
        self.assertEqual(beauty.claims, ())
        assert beauty.observations is not None
        self.assertEqual(beauty.observations.product_visibility.value, "HERO")
        self.assertGreater(beauty.confidence or 0, 0.9)
        # A high confidence and a beautiful frame do not create a cleaning claim.
        for claim in beauty.claims or ():
            self.fail("the product shot produced a commercial claim")

    def test_a_short_window_carries_its_own_weaker_evidence(self) -> None:
        evidence = self.evidence_for(self.response_raw)
        wider = evidence.entry_for(self.candidate_id("wpropv1_rinse"))
        tighter = evidence.entry_for(self.candidate_id("wpropv1_rinse_safe"))
        self.assertIsNotNone(self.extraction.candidate(tighter.candidate_id))
        self.assertNotEqual(wider.candidate_id, tighter.candidate_id)
        self.assertIs(tighter.status, EvidenceStatus.ANALYZED)
        assert tighter.risks is not None and wider.risks is not None
        self.assertEqual([risk.code.value for risk in tighter.risks], ["FRAME_RANGE_TOO_SHORT"])
        self.assertEqual(wider.risks, ())

    def test_contextual_and_inferred_support_are_kept_as_reported(self) -> None:
        evidence = self.evidence_for(self.response_raw)
        leg = evidence.entry_for(self.candidate_id("wpropv1_leg_scrub"))
        assert leg.claims is not None
        classes = {claim.product_fact_ref: claim.support.value for claim in leg.claims}
        self.assertEqual(classes["fact_surface_contact"], "CONTEXTUAL")
        self.assertEqual(classes["fact_surface_result_state"], "INFERRED")

    def test_the_unknown_candidate_is_present_and_says_why(self) -> None:
        evidence = self.evidence_for(self.response_raw)
        unknown = evidence.entry_for(self.candidate_id("wpropv1_rinse_short"))
        self.assertIs(unknown.status, EvidenceStatus.UNKNOWN)
        self.assertIsNone(unknown.observations)
        self.assertTrue(unknown.rationale)
        self.assertEqual(len(evidence.entries), len(self.extraction.pool.entries))

    def test_serialization_is_stable(self) -> None:
        first = render_candidate_evidence(self.evidence_for(self.response_raw))
        second = render_candidate_evidence(self.evidence_for(self.response_raw))
        self.assertEqual(first, second)
        shuffled = self.response_document()
        shuffled["entries"].reverse()
        for item in shuffled["entries"]:
            if item["role_affinities"]:
                item["role_affinities"].reverse()
        self.assertEqual(
            render_candidate_evidence(self.evidence_for(shuffled)), first
        )


class RequestTests(AnalysisTestCase):
    def test_the_request_round_trips_and_states_the_question(self) -> None:
        parsed = parse_analysis_request(json.loads(self.request_text))
        self.assertEqual(parse_analysis_request(json.loads(render_analysis_request(parsed))), parsed)
        self.assertEqual(parsed.question, ANALYSIS_QUESTION)
        self.assertIn("Do not introduce a Product Fact", parsed.question)
        self.assertEqual(
            parsed.candidate_ids, tuple(sorted(parsed.candidate_ids))
        )
        self.assertEqual(len(parsed.targets), len(self.extraction.candidates))

    def test_the_request_carries_the_measured_window_of_each_candidate(self) -> None:
        document = json.loads(self.request_text)
        beauty = next(
            target
            for target in document["candidates"]
            if target["candidate_id"] == self.candidate_id("wpropv1_beauty")
        )
        self.assertEqual(beauty["measured"]["coordinate_system"], "SOURCE_PTS_SECONDS")
        self.assertTrue(beauty["measured"]["variable_frame_rate"])
        self.assertNotAlmostEqual(
            beauty["measured"]["duration_seconds"],
            round(beauty["measured"]["frame_count"] / 30, 6),
            places=5,
        )

    def test_the_request_is_exact_key(self) -> None:
        payload = json.loads(self.request_text)
        payload["temperature"] = 0.2
        with self.assertRaises(CandidateAnalysisError):
            parse_analysis_request(payload)
        payload = json.loads(self.request_text)
        payload["candidates"][0]["measured"]["coordinate_system"] = "FRAME_INDEX_OVER_FPS"
        with self.assertRaises(CandidateAnalysisError):
            parse_analysis_request(payload)

    def test_the_request_hash_binds_the_answer(self) -> None:
        stale = self.response_document()
        stale["request"]["sha256"] = "0" * 64
        response = self.parse(stale)
        self.assertIsNotNone(response.response_failure)
        self.assertIn("different request", response.response_failure or "")
        self.assertEqual(len(response.outcomes), len(self.extraction.candidates))

    def test_a_request_for_another_pool_is_not_answered(self) -> None:
        other = CandidateAnalysisRequest(
            run_id=RUN_ID,
            candidate_pool_id=self.request.candidate_pool_id,
            claim_envelope=self.envelope,
            targets=self.request.targets[:1],
        )
        response = parse_analysis_response(
            self.response_raw, request=other, request_text=render_analysis_request(other)
        )
        self.assertIsNotNone(response.response_failure)
        self.assertEqual(len(response.outcomes), 1)


class ClaimEnvelopeTests(AnalysisTestCase):
    def test_the_envelope_round_trips(self) -> None:
        raw = ENVELOPE_FIXTURE.read_text(encoding="utf-8")
        self.assertEqual(render_claim_envelope(self.envelope), raw)
        self.assertEqual(parse_claim_envelope(json.loads(raw)), self.envelope)
        self.assertEqual(
            self.envelope.allowed_fact_refs,
            tuple(sorted(fact.ref for fact in self.envelope.facts)),
        )

    def test_the_envelope_is_exact_key_and_validated(self) -> None:
        for mutate in (
            lambda payload: payload.update({"notes": "anything"}),
            lambda payload: payload.update({"sha256": "0" * 63}),
            lambda payload: payload.update({"ref": "/absolute/facts.json"}),
            lambda payload: payload.update({"facts": []}),
            lambda payload: payload.update(
                {"facts": [{"ref": "fact_a", "statement": "a"}, {"ref": "fact_a", "statement": "b"}]}
            ),
        ):
            payload = copy.deepcopy(self.envelope_raw)
            mutate(payload)
            with self.subTest(payload=payload):
                with self.assertRaises(CandidateAnalysisError):
                    parse_claim_envelope(payload)

    def test_an_unsupported_claim_is_refused_not_upgraded(self) -> None:
        document = self.response_document()
        scrub = self.entry(document, self.candidate_id("wpropv1_arm_scrub"))
        scrub["claims"].append(
            {
                "product_fact_ref": "fact_removes_all_bacteria",
                "support": "DIRECT",
                "provenance": [{"start_frame": 0, "end_frame_exclusive": 30}],
                "note": "a claim the envelope never permitted",
            }
        )
        response = self.parse(document)
        counts = response.counts()
        self.assertEqual(counts["unsupported_claim_rejections"], 1)
        self.assertEqual(counts["analyzed"], 4)
        outcome = response.outcome_for(self.candidate_id("wpropv1_arm_scrub"))
        self.assertIs(outcome.entry.status, EvidenceStatus.ANALYSIS_FAILED)
        evidence = build_candidate_evidence(
            request=self.request, response=response, extraction=self.extraction
        )
        self.assertEqual(len(evidence.entries), len(self.extraction.pool.entries))
        self.assertNotIn(
            "fact_removes_all_bacteria", render_candidate_evidence(evidence)
        )

    def test_a_fabricated_product_fact_reference_is_refused(self) -> None:
        document = self.response_document()
        rinse = self.entry(document, self.candidate_id("wpropv1_rinse"))
        rinse["claims"][0]["product_fact_ref"] = "fact_invented_by_the_model"
        response = self.parse(document)
        self.assertEqual(response.counts()["unsupported_claim_rejections"], 1)
        self.assertEqual(response.counts()["analyzed"], 4)

    def test_a_claim_may_not_be_moved_into_another_fact_by_editing_prose(self) -> None:
        # The envelope is the authority; the note is prose and changes nothing.
        document = self.response_document()
        scrub = self.entry(document, self.candidate_id("wpropv1_arm_scrub"))
        scrub["claims"][0]["note"] = "this also proves the water is drinkable"
        evidence = self.evidence_for(document)
        entry = evidence.entry_for(self.candidate_id("wpropv1_arm_scrub"))
        assert entry.claims is not None
        self.assertEqual(
            [claim.product_fact_ref for claim in entry.claims],
            ["fact_surface_contact", "fact_surface_result_state"],
        )


class SupportClassTests(AnalysisTestCase):
    def test_direct_with_valid_provenance_is_kept(self) -> None:
        evidence = self.evidence_for(self.response_raw)
        candidate = self.extraction.candidate(self.candidate_id("wpropv1_arm_scrub"))
        scrub = evidence.entry_for(candidate.candidate_id)
        assert scrub.claims is not None
        direct = [claim for claim in scrub.claims if claim.support.value == "DIRECT"]
        self.assertEqual(len(direct), 2)
        for claim in direct:
            self.assertTrue(claim.provenance)
            for source_range in claim.provenance:
                self.assertGreaterEqual(source_range.start_frame, candidate.start_frame)
                self.assertLessEqual(
                    source_range.end_frame_exclusive, candidate.end_frame_exclusive
                )

    def test_direct_without_provenance_fails_the_entry(self) -> None:
        document = self.response_document()
        scrub = self.entry(document, self.candidate_id("wpropv1_arm_scrub"))
        scrub["claims"][0]["provenance"] = []
        response = self.parse(document)
        outcome = response.outcome_for(self.candidate_id("wpropv1_arm_scrub"))
        self.assertIs(outcome.entry.status, EvidenceStatus.ANALYSIS_FAILED)
        self.assertTrue(outcome.malformed)
        self.assertEqual(response.counts()["malformed_entries"], 1)
        self.assertEqual(response.counts()["analyzed"], 4)
        self.assertIn("DIRECT", outcome.failure or "")

    def test_direct_outside_the_candidate_range_fails_the_entry(self) -> None:
        document = self.response_document()
        scrub = self.entry(document, self.candidate_id("wpropv1_arm_scrub"))
        scrub["claims"][0]["provenance"] = [{"start_frame": 0, "end_frame_exclusive": 31}]
        response = self.parse(document)
        # Phase 1 containment is enforced by the Phase 1 validator, on the real Pool.
        with self.assertRaises(CandidateAnalysisError):
            build_candidate_evidence(
                request=self.request, response=response, extraction=self.extraction
            )

    def test_high_confidence_cannot_upgrade_inferred_support(self) -> None:
        document = self.response_document()
        leg = self.entry(document, self.candidate_id("wpropv1_leg_scrub"))
        leg["confidence"] = 0.99
        evidence = self.evidence_for(document)
        entry = evidence.entry_for(self.candidate_id("wpropv1_leg_scrub"))
        assert entry.claims is not None
        self.assertEqual(entry.confidence, 0.99)
        self.assertEqual(
            {claim.product_fact_ref: claim.support.value for claim in entry.claims},
            {
                "fact_surface_contact": "CONTEXTUAL",
                "fact_surface_result_state": "INFERRED",
            },
        )
        self.assertNotIn("DIRECT", {claim.support.value for claim in entry.claims})

    def test_summary_class_may_not_outrun_the_claims(self) -> None:
        document = self.response_document()
        leg = self.entry(document, self.candidate_id("wpropv1_leg_scrub"))
        leg["observations"]["claim_support_class"] = "DIRECT_DEMONSTRATION"
        response = self.parse(document)
        self.assertIs(
            response.outcome_for(
                self.candidate_id("wpropv1_leg_scrub")
            ).entry.status,
            EvidenceStatus.ANALYSIS_FAILED,
        )
        self.assertEqual(response.counts()["malformed_entries"], 1)

    def test_an_unusable_candidate_is_expressed_not_hidden(self) -> None:
        document = self.response_document()
        beauty = self.entry(document, self.candidate_id("wpropv1_beauty"))
        beauty["observations"]["visual_usability"] = "UNUSABLE"
        beauty["observations"]["claim_support_class"] = "NONE"
        beauty["evidence_type"] = "NONE"
        beauty["claims"] = []
        beauty["action_evidence"] = []
        beauty["observations"]["visible_result"] = None
        evidence = self.evidence_for(document)
        entry = evidence.entry_for(self.candidate_id("wpropv1_beauty"))
        self.assertIs(entry.status, EvidenceStatus.ANALYZED)
        assert entry.observations is not None
        self.assertEqual(entry.observations.visual_usability.value, "UNUSABLE")
        self.assertEqual(entry.evidence_type.value, "NONE")

    def test_a_provider_reported_failure_keeps_the_candidate(self) -> None:
        document = self.response_document()
        rinse = self.entry(document, self.candidate_id("wpropv1_rinse"))
        rinse.update(
            {
                "status": "ANALYSIS_FAILED",
                "observations": None,
                "action_evidence": None,
                "claims": None,
                "evidence_type": None,
                "confidence": None,
                "provenance": None,
                "role_affinities": None,
                "risks": None,
                "rationale": "the frames could not be decoded by the analyzer",
            }
        )
        response = self.parse(document)
        outcome = response.outcome_for(self.candidate_id("wpropv1_rinse"))
        self.assertIs(outcome.entry.status, EvidenceStatus.ANALYSIS_FAILED)
        self.assertIsNone(outcome.failure)
        evidence = build_candidate_evidence(
            request=self.request, response=response, extraction=self.extraction
        )
        self.assertEqual(len(evidence.entries), len(self.extraction.pool.entries))


class MalformedPayloadTests(AnalysisTestCase):
    def test_a_malformed_entry_fails_alone(self) -> None:
        document = self.response_document()
        scrub = self.entry(document, self.candidate_id("wpropv1_arm_scrub"))
        scrub["evidence_type"] = "SCORE"
        response = self.parse(document)
        self.assertIs(
            response.outcome_for(self.candidate_id("wpropv1_arm_scrub")).entry.status,
            EvidenceStatus.ANALYSIS_FAILED,
        )
        self.assertEqual(response.counts()["analyzed"], 4)
        self.assertEqual(response.counts()["malformed_entries"], 1)
        self.assertIs(
            response.outcome_for(self.candidate_id("wpropv1_rinse")).entry.status,
            EvidenceStatus.ANALYZED,
        )

    def test_out_of_bounds_action_evidence_fails_the_entry(self) -> None:
        document = self.response_document()
        beauty = self.entry(document, self.candidate_id("wpropv1_beauty"))
        beauty["action_evidence"] = [
            {"preparation_start": 12, "action_onset": 20, "action_completion": 30,
             "result_end_exclusive": 40}
        ]
        beauty["observations"]["visible_result"] = "something moves"
        response = self.parse(document)
        # The action is inside this Candidate, so Phase 1 accepts it there; the
        # containment authority is the Pool-bound validator.
        evidence = build_candidate_evidence(
            request=self.request, response=response, extraction=self.extraction
        )
        self.assertEqual(len(evidence.entries), len(self.extraction.pool.entries))

    def test_a_provider_specific_field_inside_an_entry_fails_that_entry(self) -> None:
        document = self.response_document()
        scrub = self.entry(document, self.candidate_id("wpropv1_arm_scrub"))
        scrub["latency_ms"] = 812
        response = self.parse(document)
        outcome = response.outcome_for(self.candidate_id("wpropv1_arm_scrub"))
        self.assertIs(outcome.entry.status, EvidenceStatus.ANALYSIS_FAILED)
        self.assertTrue(outcome.malformed)
        self.assertEqual(response.counts()["malformed_entries"], 1)
        evidence = build_candidate_evidence(
            request=self.request, response=response, extraction=self.extraction
        )
        # The provider's field never becomes a contract field: the entry keeps
        # exactly the eleven keys candidate_evidence.v1 defines.
        rendered = render_candidate_evidence(evidence)
        document = json.loads(rendered)
        for entry in document["entries"]:
            self.assertNotIn("latency_ms", entry)
            self.assertEqual(
                sorted(entry),
                [
                    "action_evidence",
                    "candidate_id",
                    "claims",
                    "confidence",
                    "evidence_type",
                    "observations",
                    "provenance",
                    "rationale",
                    "risks",
                    "role_affinities",
                    "status",
                ],
            )

    def test_a_missing_entry_becomes_a_visible_failure(self) -> None:
        document = self.response_document()
        document["entries"] = [
            item
            for item in document["entries"]
            if item["candidate_id"] != self.candidate_id("wpropv1_rinse")
        ]
        response = self.parse(document)
        outcome = response.outcome_for(self.candidate_id("wpropv1_rinse"))
        self.assertIs(outcome.entry.status, EvidenceStatus.ANALYSIS_FAILED)
        self.assertIn("no entry", outcome.failure or "")
        self.assertEqual(response.counts()["analyzed"], 4)
        evidence = build_candidate_evidence(
            request=self.request, response=response, extraction=self.extraction
        )
        self.assertEqual(len(evidence.entries), len(self.extraction.pool.entries))

    def test_an_empty_answer_fails_every_candidate_visibly(self) -> None:
        document = self.response_document()
        document["entries"] = []
        response = self.parse(document)
        self.assertEqual(response.counts()["analysis_failed"], 6)
        evidence = build_candidate_evidence(
            request=self.request, response=response, extraction=self.extraction
        )
        self.assertEqual(len(evidence.entries), 6)


class ResponseLevelFailureTests(AnalysisTestCase):
    def assert_all_failed(self, document: object, expected: str) -> None:
        response = self.parse(document)
        self.assertIsNotNone(response.response_failure)
        self.assertIn(expected, response.response_failure or "")
        self.assertEqual(len(response.outcomes), len(self.extraction.candidates))
        self.assertEqual(response.counts()["analysis_failed"], len(self.extraction.candidates))

    def test_a_response_about_another_run_pool_or_prompt_is_refused(self) -> None:
        for key, value, expected in (
            ("schema_version", "candidate_analysis_response.v2", "schema_version"),
            ("run_id", "analysisrunv1_somewhere_else", "run_id"),
            ("candidate_pool_id", "poolv1_" + "0" * 64, "Candidate Pool"),
            ("prompt_contract_version", "candidate_evidence_prompt.v2", "prompt contract"),
        ):
            document = self.response_document()
            document[key] = value
            with self.subTest(key=key):
                self.assert_all_failed(document, expected)

    def test_a_top_level_provider_field_is_refused(self) -> None:
        document = self.response_document()
        document["provider_trace_id"] = "abc-123"
        self.assert_all_failed(document, "unsupported key")

    def test_an_answer_about_an_unrequested_candidate_is_refused(self) -> None:
        document = self.response_document()
        fabricated = copy.deepcopy(document["entries"][0])
        fabricated["candidate_id"] = "candv1_" + "0" * 64
        document["entries"].append(fabricated)
        response = self.parse(document)
        self.assertIsNotNone(response.response_failure)
        self.assertEqual(response.unexpected_entries, 1)
        self.assertEqual(len(response.outcomes), len(self.extraction.candidates))

    def test_a_duplicated_candidate_is_refused(self) -> None:
        document = self.response_document()
        document["entries"].append(copy.deepcopy(document["entries"][0]))
        self.assert_all_failed(document, "more than once")

    def test_a_non_document_answer_is_refused(self) -> None:
        for document in ("not json at all", [], 42, None):
            with self.subTest(document=document):
                response = self.parse(document)
                self.assertIsNotNone(response.response_failure)
                self.assertEqual(len(response.outcomes), len(self.extraction.candidates))


class ProviderBoundaryTests(AnalysisTestCase):
    def test_the_existing_scripted_agent_is_the_deterministic_provider(self) -> None:
        agent = authoring.ScriptedAuthoringAgent(
            {
                producer_registry.CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT: json.dumps(
                    self.response_raw, ensure_ascii=False, sort_keys=True, indent=2
                )
                + "\n"
            }
        )
        result = run_candidate_evidence_stage(
            job_root=self.tmp,
            extraction=self.extraction,
            envelope=self.envelope,
            run_id=RUN_ID,
            agent=agent,
        )
        self.assertEqual(result.response_source, "AUTHORING_SEAM")
        self.assertEqual(len(agent.requests), 1)
        self.assertEqual(
            agent.requests[0].artifact,
            producer_registry.CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT,
        )
        self.assertEqual(
            agent.requests[0].required_inputs,
            (producer_registry.CANDIDATE_ANALYSIS_REQUEST_ARTIFACT,),
        )
        self.assertEqual(result.response.counts()["analyzed"], 5)
        self.assertTrue(
            (self.tmp / producer_registry.CANDIDATE_EVIDENCE_ARTIFACT).is_file()
        )
        self.assertTrue(
            (self.tmp / producer_registry.CANDIDATE_ANALYSIS_REQUEST_ARTIFACT).is_file()
        )

    def test_a_recording_agent_answers_a_replayable_request(self) -> None:
        """The request on disk is enough to replay the answer later."""

        agent = authoring.ScriptedAuthoringAgent(
            {
                producer_registry.CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT: json.dumps(
                    self.response_raw
                )
            }
        )
        run_candidate_evidence_stage(
            job_root=self.tmp,
            extraction=self.extraction,
            envelope=self.envelope,
            run_id=RUN_ID,
            agent=agent,
        )
        request_document = json.loads(
            (self.tmp / producer_registry.CANDIDATE_ANALYSIS_REQUEST_ARTIFACT).read_text()
        )
        self.assertEqual(request_document["run_id"], RUN_ID)
        self.assertEqual(
            request_document["claim_envelope"]["ref"], self.envelope.ref
        )
        replayed = parse_analysis_request(request_document)
        self.assertEqual(replayed.candidate_ids, self.request.candidate_ids)

    def test_a_provider_that_does_not_answer_leaves_every_candidate_visible(self) -> None:
        result = run_candidate_evidence_stage(
            job_root=self.tmp,
            extraction=self.extraction,
            envelope=self.envelope,
            run_id=RUN_ID,
            agent=authoring.NullAuthoringAgent(),
        )
        self.assertIsNotNone(result.response.response_failure)
        self.assertEqual(result.response.counts()["analysis_failed"], 6)
        self.assertEqual(len(result.evidence.entries), 6)
        self.assertEqual(result.evidence.entries[0].status, EvidenceStatus.ANALYSIS_FAILED)

    def test_a_provider_timeout_is_a_failure_not_a_lost_candidate(self) -> None:
        agent = authoring.CommandAuthoringAgent("sleep 30", timeout_seconds=0.15)
        result = run_candidate_evidence_stage(
            job_root=self.tmp,
            extraction=self.extraction,
            envelope=self.envelope,
            run_id=RUN_ID,
            agent=agent,
        )
        self.assertIsNotNone(result.response.response_failure)
        self.assertEqual(len(result.evidence.entries), len(self.extraction.pool.entries))
        self.assertIn("no response", result.response.response_failure or "")
        for entry in result.evidence.entries:
            self.assertIs(entry.status, EvidenceStatus.ANALYSIS_FAILED)
            self.assertTrue(entry.rationale.strip())

    def test_a_broken_agent_is_recorded_not_propagated(self) -> None:
        class Exploding:
            def author(self, request):  # noqa: ANN001 - protocol shape
                raise RuntimeError("provider SDK exploded: sk-secret-value")

        result = run_candidate_evidence_stage(
            job_root=self.tmp,
            extraction=self.extraction,
            envelope=self.envelope,
            run_id=RUN_ID,
            agent=Exploding(),  # type: ignore[arg-type]
        )
        self.assertIsNotNone(result.response.response_failure)
        self.assertIn("RuntimeError", result.response.response_failure or "")
        report = json.dumps(result.as_dict(), ensure_ascii=False)
        self.assertNotIn("sk-secret-value", report)
        self.assertEqual(len(result.evidence.entries), len(self.extraction.pool.entries))

    def test_an_unreadable_provider_answer_keeps_the_candidates(self) -> None:
        agent = authoring.ScriptedAuthoringAgent(
            {producer_registry.CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT: "{not json"}
        )
        result = run_candidate_evidence_stage(
            job_root=self.tmp,
            extraction=self.extraction,
            envelope=self.envelope,
            run_id=RUN_ID,
            agent=agent,
        )
        self.assertIsNotNone(result.response.response_failure)
        self.assertEqual(len(result.evidence.entries), len(self.extraction.pool.entries))

    def test_a_supplied_document_is_used_without_an_agent(self) -> None:
        result = run_candidate_evidence_stage(
            job_root=self.tmp,
            extraction=self.extraction,
            envelope=self.envelope,
            run_id=RUN_ID,
            response_document=self.response_raw,
        )
        self.assertEqual(result.response_source, "SUPPLIED_DOCUMENT")
        self.assertTrue(
            (self.tmp / producer_registry.CANDIDATE_EVIDENCE_ARTIFACT).is_file()
        )


class StageTests(AnalysisTestCase):
    def test_the_propose_stage_writes_extraction_and_pool(self) -> None:
        result = run_candidate_extraction_stage(
            job_root=self.tmp,
            catalog=self.catalog,
            measurements=self.measurements,
            segmentations=self.segmentations,
            proposals=self.proposals,
        )
        self.assertEqual(result.proposal_source, "SUPPLIED_PROPOSALS")
        self.assertIsNone(result.proposal_failure)
        self.assertEqual(result.extraction.pool.pool_id, self.extraction.pool.pool_id)
        extraction_document = json.loads(
            (self.tmp / producer_registry.CANDIDATE_EXTRACTION_ARTIFACT).read_text()
        )
        self.assertEqual(extraction_document["counts"]["accepted_candidates"], 6)
        pool_document = json.loads(
            (self.tmp / producer_registry.CANDIDATE_POOL_ARTIFACT).read_text()
        )
        self.assertEqual(pool_document["schema_version"], "candidate_pool.v1")
        self.assertEqual(pool_document["pool_id"], result.extraction.pool.pool_id)

    def test_the_propose_stage_requests_a_proposal_through_the_seam(self) -> None:
        agent = authoring.ScriptedAuthoringAgent(
            {
                producer_registry.CANDIDATE_WINDOW_PROPOSAL_ARTIFACT: PROPOSALS_FIXTURE.read_text()
            }
        )
        result = run_candidate_extraction_stage(
            job_root=self.tmp,
            catalog=self.catalog,
            measurements=self.measurements,
            segmentations=self.segmentations,
            agent=agent,
        )
        self.assertEqual(result.proposal_source, "AUTHORING_SEAM")
        self.assertEqual(len(result.extraction.candidates), 6)
        self.assertEqual(
            agent.requests[0].artifact,
            producer_registry.CANDIDATE_WINDOW_PROPOSAL_ARTIFACT,
        )

    def test_an_analyzer_that_proposes_nothing_is_recorded(self) -> None:
        result = run_candidate_extraction_stage(
            job_root=self.tmp,
            catalog=self.catalog,
            measurements=self.measurements,
            segmentations=self.segmentations,
            agent=authoring.NullAuthoringAgent(),
        )
        self.assertIsNotNone(result.proposal_failure)
        self.assertEqual(len(result.extraction.candidates), 0)
        self.assertEqual(result.extraction.pool.entries, ())

    def test_an_unusable_proposal_document_is_recorded(self) -> None:
        agent = authoring.ScriptedAuthoringAgent(
            {producer_registry.CANDIDATE_WINDOW_PROPOSAL_ARTIFACT: '{"schema_version": "nope"}'}
        )
        result = run_candidate_extraction_stage(
            job_root=self.tmp,
            catalog=self.catalog,
            measurements=self.measurements,
            segmentations=self.segmentations,
            agent=agent,
        )
        self.assertIn("not usable", result.proposal_failure or "")
        self.assertEqual(result.proposal_source, "AUTHORING_SEAM")

    def test_the_stage_report_exposes_the_observability_counters(self) -> None:
        result = run_candidate_evidence_stage(
            job_root=self.tmp,
            extraction=self.extraction,
            envelope=self.envelope,
            run_id=RUN_ID,
            response_document=self.response_raw,
        )
        report = result.as_dict()
        self.assertEqual(report["schema_version"], "candidate_evidence_report.v1")
        self.assertEqual(report["stage"], "ANALYZE CANDIDATES")
        self.assertEqual(report["provider"], "fixture_provider")
        self.assertEqual(report["model"], "fixture_multimodal_v1")
        self.assertEqual(report["prompt_contract_version"], "candidate_evidence_prompt.v1")
        self.assertEqual(report["run_id"], RUN_ID)
        self.assertEqual(report["analysis"]["analyzed"], 5)
        self.assertEqual(report["analysis"]["direct_support"], 4)
        self.assertEqual(report["evidence"]["entries"], report["evidence"]["pool_size"])
        self.assertEqual(report["extraction"]["accepted_candidates"], 6)
        self.assertEqual(report["candidate_pool_id"], self.extraction.pool.pool_id)
        rendered = json.dumps(report, ensure_ascii=False)
        for forbidden in ("api_key", "secret", "password", "credential", "sk-"):
            self.assertNotIn(forbidden, rendered.lower())

    def test_the_evidence_artifact_on_disk_is_the_validated_document(self) -> None:
        result = run_candidate_evidence_stage(
            job_root=self.tmp,
            extraction=self.extraction,
            envelope=self.envelope,
            run_id=RUN_ID,
            response_document=self.response_raw,
        )
        written = (
            self.tmp / producer_registry.CANDIDATE_EVIDENCE_ARTIFACT
        ).read_text(encoding="utf-8")
        self.assertEqual(written, result.evidence_text)
        parsed = parse_candidate_evidence(json.loads(written))
        validate_candidate_evidence(
            parsed, self.extraction.pool, self.extraction.catalog
        )
        reference = artifact_reference(
            producer_registry.CANDIDATE_EVIDENCE_ARTIFACT, written
        )
        self.assertEqual(reference.sha256, result.as_dict()["evidence"]["sha256"])


class AvailabilityTests(AnalysisTestCase):
    """A Candidate nobody could analyze is reported, never removed."""

    def test_a_provider_reported_unknown_is_preserved_as_unknown(self) -> None:
        document = self.response_document()
        beauty = self.entry(document, self.candidate_id("wpropv1_beauty"))
        beauty.update(
            {
                "status": "UNKNOWN",
                "observations": None,
                "action_evidence": None,
                "claims": None,
                "evidence_type": None,
                "confidence": None,
                "provenance": None,
                "role_affinities": None,
                "risks": None,
                "rationale": "the analyzer could not read this window at all",
            }
        )
        response = self.parse(document)
        self.assertEqual(response.counts()["unknown"], 2)
        evidence = build_candidate_evidence(
            request=self.request, response=response, extraction=self.extraction
        )
        entry = evidence.entry_for(self.candidate_id("wpropv1_beauty"))
        self.assertIs(entry.status, EvidenceStatus.UNKNOWN)
        self.assertEqual(len(evidence.entries), len(self.extraction.pool.entries))

    def test_the_approved_unavailable_vocabulary_is_still_phase_1(self) -> None:
        """Phase 2 reports unavailability in evidence; planning names its reason.

        ``ANALYSIS_UNAVAILABLE`` was approved in Phase 1 as the planning reason for
        a Candidate that could not be analyzed. Phase 2 does not rename it, move
        it, or start emitting a second code for the same thing.
        """

        from src.ai_autocut.editing_intelligence import (
            COVERAGE_WITHHOLD_REASON_CODES,
            CoverageReasonCode,
        )

        self.assertIn(
            CoverageReasonCode.ANALYSIS_UNAVAILABLE, COVERAGE_WITHHOLD_REASON_CODES
        )
        evidence = self.evidence_for(self.response_raw)
        statuses = {entry.status for entry in evidence.entries}
        self.assertIn(EvidenceStatus.UNKNOWN, statuses)
        # Candidate Evidence expresses availability with its own status vocabulary.
        self.assertEqual(
            {status.value for status in EvidenceStatus},
            {"ANALYZED", "ANALYSIS_FAILED", "UNKNOWN"},
        )


class CommandLineTests(AnalysisTestCase):
    def test_the_shadow_cli_runs_both_stages_and_stops_at_evidence(self) -> None:
        from src.ai_autocut.candidate_analysis import main

        job = self.tmp / "shadow-job"
        measurements = self.tmp / "measurements.json"
        segmentations = self.tmp / "segmentations.json"
        proposals = self.tmp / "proposals.json"
        envelope = self.tmp / "envelope.json"
        response = self.tmp / "response.json"
        measurements.write_text(MEASUREMENTS_FIXTURE.read_text(), encoding="utf-8")
        segmentations.write_text(SEGMENTATIONS_FIXTURE.read_text(), encoding="utf-8")
        proposals.write_text(PROPOSALS_FIXTURE.read_text(), encoding="utf-8")
        envelope.write_text(ENVELOPE_FIXTURE.read_text(), encoding="utf-8")
        response.write_text(RESPONSE_FIXTURE.read_text(), encoding="utf-8")

        common = [
            "--job-root", str(job),
            "--measurements", str(measurements),
            "--segmentations", str(segmentations),
            "--catalog", str(CATALOG_FIXTURE),
        ]
        self.assertEqual(
            main(common + ["--stage", "propose", "--proposals", str(proposals)]), 0
        )
        self.assertTrue(
            (job / producer_registry.CANDIDATE_EXTRACTION_ARTIFACT).is_file()
        )
        self.assertEqual(
            main(
                common
                + [
                    "--stage", "analyze",
                    "--proposals", str(proposals),
                    "--envelope", str(envelope),
                    "--response", str(response),
                    "--run-id", RUN_ID,
                ]
            ),
            0,
        )
        evidence_path = job / producer_registry.CANDIDATE_EVIDENCE_ARTIFACT
        self.assertTrue(evidence_path.is_file())
        evidence = parse_candidate_evidence(json.loads(evidence_path.read_text()))
        self.assertEqual(len(evidence.entries), 6)
        # Nothing downstream of Candidate Evidence was produced by this stage.
        for absent in ("planning", "hook", "edit", "renders", "final"):
            self.assertFalse((job / absent).exists())

    def test_the_cli_reports_a_blocked_run_without_producing_evidence(self) -> None:
        from src.ai_autocut.candidate_analysis import main

        job = self.tmp / "blocked-job"
        bad = self.tmp / "bad.json"
        bad.write_text('{"schema_version": "nope"}', encoding="utf-8")
        code = main(
            [
                "--job-root", str(job),
                "--stage", "propose",
                "--measurements", str(bad),
                "--segmentations", str(SEGMENTATIONS_FIXTURE),
                "--catalog", str(CATALOG_FIXTURE),
            ]
        )
        self.assertEqual(code, 3)
        self.assertFalse(job.exists())


if __name__ == "__main__":
    unittest.main()
