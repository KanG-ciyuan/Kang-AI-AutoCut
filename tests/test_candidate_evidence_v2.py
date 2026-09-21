"""Candidate Evidence v2: structured observations and the machine-truth boundary.

The gap these tests close came from the Phase 2.5 live run: an analyzer could only
say "no action" or "the surface is visibly soiled" in prose, and Phase 3 would have
had to parse that prose to plan. v2 gives those statements a finite, validated home,
and this file holds the line that a structured observation is never a commercial
claim.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from src.ai_autocut.candidate_analysis import (
    ANALYZER_PROMPT_CONTRACT_VERSION,
    CandidateAnalysisError,
    PROMPT_CONTRACT_VERSION,
    STRUCTURED_PROMPT_CONTRACT_VERSION,
    CandidateAnalysisRequest,
    ClaimEnvelope,
    build_candidate_evidence,
    evidence_contract_for,
    parse_analysis_response,
    prompt_contract,
    prompt_for,
    render_analysis_request,
    run_candidate_evidence_stage,
    targets_from_extraction,
)
from src.ai_autocut.candidate_evidence import (
    SCHEMA_VERSION as V1_SCHEMA_VERSION,
    CandidateEvidenceContractError,
    ClaimSupport,
    EvidenceStatus,
    parse_candidate_evidence,
)
from src.ai_autocut.candidate_evidence_v2 import (
    AUTHORITATIVE_FIELDS,
    FORBIDDEN_IN_OBSERVATION_VOCABULARY,
    NON_AUTHORITATIVE_FIELDS,
    OBSERVABLE_STATE_MEANINGS,
    RATIONALE_STATUS,
    SCHEMA_VERSION,
    ActionPresence,
    CandidateEvidenceEntryV2,
    CandidateEvidenceV2,
    MachineSupport,
    ObservableState,
    ObservationsV2,
    authoritative_evidence_view,
    check_machine_support,
    migrate_v1_document_to_v2,
    parse_candidate_evidence_v2,
    read_candidate_evidence,
    render_candidate_evidence_v2,
    validate_candidate_evidence_v2,
)
from src.ai_autocut.candidate_extraction import (
    extract_candidates,
    parse_window_proposals,
)
from src.ai_autocut.candidate_pool import CandidatePool
from src.ai_autocut.identity import parse_identity_catalog
from src.ai_autocut.candidate_evidence_v2 import CandidateEvidenceV2Error


FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = FIXTURES / "phase2_identity_catalog_v1.json"
MEASUREMENTS = FIXTURES / "phase2_candidate_measurements_v1.json"
SEGMENTATIONS = FIXTURES / "phase2_candidate_segmentations_v1.json"
PROPOSALS = FIXTURES / "phase2_candidate_window_proposal_v1.json"
ENVELOPE = FIXTURES / "phase2_claim_envelope_v1.json"
V1_RESPONSE = FIXTURES / "phase2_candidate_analysis_response_v1.json"

#: One structured observation per window in the Phase 2 fixture chain, so the v2
#: path is exercised on the same Candidates the reviewed fixtures describe.
OBSERVATION_UPDATES = {
    # window [0,30): the scrubbing window, with a visible action and a result
    "0": {
        "action_presence": "ACTION_PRESENT",
        "observable_states": [
            "BEFORE_AFTER_RELATION_VISIBLE",
            "CLEAN_STATE_VISIBLE",
            "CONTACT_VISIBLE",
            "PROBLEM_STATE_VISIBLE",
            "STATE_CHANGE_VISIBLE",
        ],
    },
    # window [30,75): the leg window, an action whose result is only partly readable
    "30": {
        "action_presence": "ACTION_PRESENT",
        "observable_states": ["CONTACT_VISIBLE", "STATE_CHANGE_VISIBLE"],
    },
    # window [75,120): the rinse window, an action with flow
    "75": {
        "action_presence": "ACTION_PRESENT",
        "observable_states": ["FLOW_VISIBLE", "STATE_CHANGE_VISIBLE"],
    },
    # window [10,50) on the second material: the beauty plate, no action at all
    "10": {
        "action_presence": "NO_ACTION",
        "observable_states": [
            "PRODUCT_BEAUTY_STATE_VISIBLE",
            "PRODUCT_IDENTITY_VISIBLE",
        ],
    },
    # window [88,118): the tighter rinse window, an action with flow
    "88": {
        "action_presence": "ACTION_PRESENT",
        "observable_states": ["FLOW_VISIBLE"],
    },
}


class V2TestCase(unittest.TestCase):
    """The Phase 2 fixture chain, answered under the v3 prompt contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = parse_identity_catalog(json.loads(CATALOG.read_text()))
        from src.ai_autocut.candidate_analysis import (
            parse_claim_envelope,
            parse_measurements,
            parse_segmentations,
        )

        cls.measurements = parse_measurements(json.loads(MEASUREMENTS.read_text()))
        cls.segmentations = parse_segmentations(json.loads(SEGMENTATIONS.read_text()))
        cls.proposals = parse_window_proposals(json.loads(PROPOSALS.read_text()))
        cls.envelope = parse_claim_envelope(json.loads(ENVELOPE.read_text()))
        cls.extraction = extract_candidates(
            catalog=cls.catalog,
            measurements=cls.measurements,
            segmentations=cls.segmentations,
            proposals=cls.proposals,
        )
        cls.v1_response = json.loads(V1_RESPONSE.read_text())

    def request(self, *, prompt_version: str = STRUCTURED_PROMPT_CONTRACT_VERSION):
        return CandidateAnalysisRequest(
            run_id=self.v1_response["run_id"],
            candidate_pool_id=self.extraction.pool.pool_id,
            claim_envelope=self.envelope,
            targets=targets_from_extraction(self.extraction),
            prompt_contract_version=prompt_version,
            question=prompt_for(prompt_version),
        )

    def v2_response(self, request=None) -> dict:
        """Take the Phase 2 answer and add the two structured observation fields."""

        request = request if request is not None else self.request()
        document = copy.deepcopy(self.v1_response)
        document["run_id"] = request.run_id
        document["candidate_pool_id"] = request.candidate_pool_id
        document["prompt_contract_version"] = request.prompt_contract_version
        document["request"] = {
            "ref": "analysis/candidate_analysis_request.json",
            "sha256": hashlib.sha256(
                render_analysis_request(request).encode("utf-8")
            ).hexdigest(),
        }
        for entry in document["entries"]:
            if entry["observations"] is None:
                continue
            start = str(
                next(
                    candidate.start_frame
                    for candidate in self.extraction.candidates
                    if candidate.candidate_id == entry["candidate_id"]
                )
            )
            entry["observations"].update(OBSERVATION_UPDATES[start])
        return document

    def v1_document(self) -> dict:
        """The same answer under the v1 contract, for migration and read tests."""

        request = self.request(prompt_version=PROMPT_CONTRACT_VERSION)
        response = parse_analysis_response(
            {
                **copy.deepcopy(self.v1_response),
                "request": {
                    "ref": "analysis/candidate_analysis_request.json",
                    "sha256": hashlib.sha256(
                        render_analysis_request(request).encode("utf-8")
                    ).hexdigest(),
                },
            },
            request=request,
            request_text=render_analysis_request(request),
        )
        evidence = build_candidate_evidence(
            request=request, response=response, extraction=self.extraction
        )
        from src.ai_autocut.candidate_evidence import render_candidate_evidence

        return json.loads(render_candidate_evidence(evidence))

    def build(self, document, request=None):
        request = request if request is not None else self.request()
        response = parse_analysis_response(
            document,
            request=request,
            request_text=render_analysis_request(request),
            evidence_contract_version=SCHEMA_VERSION,
        )
        evidence = build_candidate_evidence(
            request=request,
            response=response,
            extraction=self.extraction,
            evidence_contract_version=SCHEMA_VERSION,
        )
        return response, evidence


class StructureTests(V2TestCase):
    def test_the_entry_key_set_is_identical_to_v1(self) -> None:
        _, evidence = self.build(self.v2_response())
        document = json.loads(render_candidate_evidence_v2(evidence))
        self.assertEqual(document["schema_version"], SCHEMA_VERSION)
        self.assertEqual(
            sorted(document), ["analysis_run", "candidate_pool_id", "entries", "product_facts", "schema_version"]
        )
        for entry in document["entries"]:
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

    def test_only_the_observations_object_grew(self) -> None:
        _, evidence = self.build(self.v2_response())
        document = json.loads(render_candidate_evidence_v2(evidence))
        analysed = [e for e in document["entries"] if e["observations"] is not None]
        self.assertTrue(analysed)
        for entry in analysed:
            self.assertEqual(
                sorted(entry["observations"]),
                [
                    "action_presence",
                    "body_area",
                    "claim_support_class",
                    "observable_states",
                    "product_visibility",
                    "usage_context",
                    "visible_action",
                    "visible_result",
                    "visual_usability",
                ],
            )

    def test_the_document_round_trips_and_validates(self) -> None:
        _, evidence = self.build(self.v2_response())
        raw = render_candidate_evidence_v2(evidence)
        parsed = parse_candidate_evidence_v2(json.loads(raw))
        self.assertEqual(render_candidate_evidence_v2(parsed), raw)
        resolved = validate_candidate_evidence_v2(
            parsed, self.extraction.pool, self.extraction.catalog
        )
        self.assertEqual(len(resolved), len(self.extraction.pool.entries))
        self.assertEqual(len(parsed.entries), len(self.extraction.pool.entries))

    def test_a_v1_document_is_refused_by_the_v2_parser_with_guidance(self) -> None:
        with self.assertRaisesRegex(CandidateEvidenceV2Error, "migrates it"):
            parse_candidate_evidence_v2(self.v1_document())

    def test_the_v2_vocabulary_is_finite_and_contains_no_efficacy_language(self) -> None:
        self.assertEqual(set(OBSERVABLE_STATE_MEANINGS), {s.value for s in ObservableState})
        for code, meaning in OBSERVABLE_STATE_MEANINGS.items():
            lowered = (code + " " + meaning).lower()
            for word in FORBIDDEN_IN_OBSERVATION_VOCABULARY:
                with self.subTest(code=code, word=word):
                    self.assertNotIn(word, lowered)

    def test_an_unknown_observation_code_is_refused(self) -> None:
        document = self.v2_response()
        entry = next(e for e in document["entries"] if e["observations"] is not None)
        entry["observations"]["observable_states"] = ["KILLS_BACTERIA"]
        response, _ = self.build(document)
        self.assertEqual(response.counts()["malformed_entries"], 1)
        self.assertIs(
            response.outcome_for(entry["candidate_id"]).entry.status,
            EvidenceStatus.ANALYSIS_FAILED,
        )


class CrossRuleTests(V2TestCase):
    def test_no_action_is_structurally_representable(self) -> None:
        _, evidence = self.build(self.v2_response())
        for entry in evidence.entries:
            if entry.status is not EvidenceStatus.ANALYZED:
                continue
            if not entry.action_evidence:
                self.assertIs(entry.action_presence, ActionPresence.NO_ACTION)
                self.assertEqual(entry.action_evidence, ())

    def test_action_presence_must_match_the_recorded_action(self) -> None:
        document = self.v2_response()
        entry = next(e for e in document["entries"] if e["action_evidence"] == [])
        entry["observations"]["action_presence"] = "ACTION_PRESENT"
        response, _ = self.build(document)
        self.assertIs(
            response.outcome_for(entry["candidate_id"]).entry.status,
            EvidenceStatus.ANALYSIS_FAILED,
        )

    def test_no_action_may_not_contradict_recorded_action_evidence(self) -> None:
        document = self.v2_response()
        entry = next(e for e in document["entries"] if e["action_evidence"])
        entry["observations"]["action_presence"] = "NO_ACTION"
        response, _ = self.build(document)
        self.assertIs(
            response.outcome_for(entry["candidate_id"]).entry.status,
            EvidenceStatus.ANALYSIS_FAILED,
        )

    def test_an_event_observation_requires_an_action(self) -> None:
        document = self.v2_response()
        entry = next(e for e in document["entries"] if e["action_evidence"] == [])
        entry["observations"]["observable_states"] = ["FLOW_VISIBLE"]
        response, _ = self.build(document)
        outcome = response.outcome_for(entry["candidate_id"])
        self.assertIs(outcome.entry.status, EvidenceStatus.ANALYSIS_FAILED)
        self.assertIn("ACTION_PRESENT", outcome.failure or "")

    def test_product_states_require_the_product_to_be_visible(self) -> None:
        document = self.v2_response()
        entry = next(
            e for e in document["entries"] if e["observations"] is not None
        )
        entry["observations"]["product_visibility"] = "NOT_VISIBLE"
        entry["observations"]["observable_states"] = ["PRODUCT_BEAUTY_STATE_VISIBLE"]
        response, _ = self.build(document)
        self.assertIs(
            response.outcome_for(entry["candidate_id"]).entry.status,
            EvidenceStatus.ANALYSIS_FAILED,
        )

    def test_states_are_unique_and_canonically_ordered(self) -> None:
        document = self.v2_response()
        entry = next(e for e in document["entries"] if e["observations"] is not None)
        entry["observations"]["observable_states"] = [
            "STATE_CHANGE_VISIBLE",
            "CONTACT_VISIBLE",
            "STATE_CHANGE_VISIBLE",
        ]
        response, _ = self.build(document)
        self.assertIs(
            response.outcome_for(entry["candidate_id"]).entry.status,
            EvidenceStatus.ANALYSIS_FAILED,
        )

    def test_observations_are_absent_when_a_candidate_is_not_analysed(self) -> None:
        document = self.v2_response()
        entry = next(e for e in document["entries"] if e["status"] == "UNKNOWN")
        self.assertIsNone(entry["observations"])
        _, evidence = self.build(document)
        unknown = evidence.entry_for(entry["candidate_id"])
        self.assertIs(unknown.status, EvidenceStatus.UNKNOWN)
        self.assertIsNone(unknown.observations)
        self.assertEqual(unknown.observable_states, ())
        self.assertIs(unknown.action_presence, ActionPresence.NOT_RECORDED)


class ObservationIsNotClaimTests(V2TestCase):
    def test_a_structured_observation_never_creates_a_claim(self) -> None:
        document = self.v2_response()
        entry = next(
            e
            for e in document["entries"]
            if e["observations"] is not None and e["claims"]
        )
        entry["observations"]["observable_states"] = [
            "PROBLEM_STATE_VISIBLE",
            "CLEAN_STATE_VISIBLE",
            "STATE_CHANGE_VISIBLE",
        ]
        entry["claims"] = []
        entry["observations"]["claim_support_class"] = "NONE"
        _, evidence = self.build(document)
        built = evidence.entry_for(entry["candidate_id"])
        self.assertEqual(built.claims, ())
        self.assertEqual(
            [state.value for state in built.observable_states],
            ["CLEAN_STATE_VISIBLE", "PROBLEM_STATE_VISIBLE", "STATE_CHANGE_VISIBLE"],
        )
        view = next(
            item
            for item in authoritative_evidence_view(evidence)
            if item.candidate_id == entry["candidate_id"]
        )
        self.assertEqual(view.claims, ())
        self.assertTrue(view.observable_states)

    def test_an_unsupported_product_fact_is_still_refused_with_states_present(self) -> None:
        document = self.v2_response()
        entry = next(e for e in document["entries"] if e["claims"])
        entry["claims"].append(
            {
                "product_fact_ref": "fact_kills_bacteria",
                "support": "DIRECT",
                "provenance": entry["claims"][0]["provenance"],
                "note": "never permitted by the envelope",
            }
        )
        entry["observations"]["observable_states"] = ["STATE_CHANGE_VISIBLE"]
        response, _ = self.build(document)
        self.assertEqual(response.counts()["unsupported_claim_rejections"], 1)
        self.assertIs(
            response.outcome_for(entry["candidate_id"]).entry.status,
            EvidenceStatus.ANALYSIS_FAILED,
        )

    def test_a_beauty_state_cannot_become_efficacy_truth(self) -> None:
        document = self.v2_response()
        beauty = None
        for entry in document["entries"]:
            if entry["observations"] is None:
                continue
            entry["observations"]["product_visibility"] = "HERO"
            entry["observations"]["observable_states"] = [
                "PRODUCT_BEAUTY_STATE_VISIBLE",
                "PRODUCT_IDENTITY_VISIBLE",
            ]
            entry["observations"]["usage_context"] = "PACKAGING"
            entry["observations"]["claim_support_class"] = "CONTEXTUAL_ONLY"
            entry["action_evidence"] = []
            entry["observations"]["action_presence"] = "NO_ACTION"
            entry["claims"] = [
                {
                    "product_fact_ref": "fact_product_identity_visible",
                    "support": "CONTEXTUAL",
                    "provenance": [],
                    "note": "the product is identifiable",
                }
            ]
            beauty = entry
            break
        _, evidence = self.build(document)
        view = next(
            item
            for item in authoritative_evidence_view(evidence)
            if item.candidate_id == beauty["candidate_id"]
        )
        self.assertIs(view.action_presence, ActionPresence.NO_ACTION)
        self.assertTrue(view.has_state(ObservableState.PRODUCT_BEAUTY_STATE_VISIBLE))
        # The efficacy premise is refused from structured truth, although the fact
        # itself is permitted by the envelope.
        check = check_machine_support(
            view,
            observable_states=(ObservableState.STATE_CHANGE_VISIBLE,),
            product_fact_refs=("fact_surface_state_change_visible",),
        )
        self.assertIs(check.support, MachineSupport.NOT_MACHINE_SUPPORTED)
        self.assertEqual(
            check.missing,
            ("observation:STATE_CHANGE_VISIBLE", "claim:fact_surface_state_change_visible"),
        )


class RationaleBoundaryTests(V2TestCase):
    def test_rationale_is_declared_non_authoritative(self) -> None:
        self.assertEqual(RATIONALE_STATUS, "NON_AUTHORITATIVE_EXPLANATORY_TEXT")

    def test_a_claim_like_rationale_changes_no_machine_truth(self) -> None:
        first_response, first = self.build(self.v2_response())
        document = self.v2_response()
        for entry in document["entries"]:
            if entry["observations"] is None:
                continue
            entry["rationale"] = (
                "the surface is now sterile and the product kills 99.9 percent of "
                "bacteria on contact"
            )
            for claim in entry["claims"] or []:
                claim["note"] = "the product guarantees cleaning performance"
        second_response, second = self.build(document)
        first_view = authoritative_evidence_view(first)
        second_view = authoritative_evidence_view(second)
        self.assertEqual(
            [item.as_dict() for item in first_view],
            [item.as_dict() for item in second_view],
        )
        self.assertEqual(
            first_response.counts()["unsupported_claim_rejections"],
            second_response.counts()["unsupported_claim_rejections"],
        )

    def test_the_authoritative_view_contains_no_prose_field(self) -> None:
        _, evidence = self.build(self.v2_response())
        for view in authoritative_evidence_view(evidence):
            document = view.as_dict()
            self.assertEqual(sorted(document), sorted(AUTHORITATIVE_FIELDS))
            for prose in NON_AUTHORITATIVE_FIELDS:
                self.assertNotIn(prose.split(".")[-1], document)
            rendered = json.dumps(document)
            self.assertNotIn("rationale", rendered)
            self.assertNotIn("visible_action", rendered)

    def test_a_premise_named_only_in_prose_is_not_machine_supported(self) -> None:
        document = self.v2_response()
        entry = next(
            e for e in document["entries"] if e["observations"] is not None and e["action_evidence"]
        )
        entry["rationale"] = (
            "the surface is visibly in its problem state and the product is clearly "
            "the hero of the shot"
        )
        entry["observations"]["observable_states"] = []
        _, evidence = self.build(document)
        view = next(
            item
            for item in authoritative_evidence_view(evidence)
            if item.candidate_id == entry["candidate_id"]
        )
        check = check_machine_support(
            view, observable_states=(ObservableState.PROBLEM_STATE_VISIBLE,)
        )
        self.assertIs(check.support, MachineSupport.NOT_MACHINE_SUPPORTED)
        self.assertIn("prose cannot supply it", check.detail)


class MigrationTests(V2TestCase):
    def test_a_v1_document_migrates_losslessly_and_honestly(self) -> None:
        v1 = self.v1_document()
        migrated = migrate_v1_document_to_v2(v1)
        self.assertEqual(migrated["schema_version"], SCHEMA_VERSION)
        self.assertEqual(migrated["candidate_pool_id"], v1["candidate_pool_id"])
        self.assertEqual(migrated["product_facts"], v1["product_facts"])
        self.assertEqual(migrated["analysis_run"], v1["analysis_run"])
        self.assertEqual(len(migrated["entries"]), len(v1["entries"]))
        for before, after in zip(v1["entries"], migrated["entries"]):
            self.assertEqual(before["candidate_id"], after["candidate_id"])
            self.assertEqual(before["claims"], after["claims"])
            self.assertEqual(before["provenance"], after["provenance"])
            self.assertEqual(before["rationale"], after["rationale"])
            if before["observations"] is None:
                self.assertIsNone(after["observations"])
                continue
            self.assertEqual(after["observations"]["observable_states"], [])
            expected = "ACTION_PRESENT" if before["action_evidence"] else "NOT_RECORDED"
            self.assertEqual(after["observations"]["action_presence"], expected)

    def test_migration_never_upgrades_prose_to_a_structured_assertion(self) -> None:
        v1 = self.v1_document()
        no_action_entry = next(
            entry
            for entry in v1["entries"]
            if entry["observations"] is not None and not entry["action_evidence"]
        )
        # v1 could only say this in prose, which is exactly the gap v2 closes.
        no_action_entry["observations"]["visible_action"] = (
            "no action: the surface is static across every sampled frame"
        )
        migrated = migrate_v1_document_to_v2(v1)
        after = next(
            e
            for e in migrated["entries"]
            if e["candidate_id"] == no_action_entry["candidate_id"]
        )
        self.assertEqual(after["observations"]["action_presence"], "NOT_RECORDED")
        self.assertEqual(after["observations"]["observable_states"], [])

    def test_migration_is_deterministic_and_readable_as_v2(self) -> None:
        v1 = self.v1_document()
        first = migrate_v1_document_to_v2(v1)
        second = migrate_v1_document_to_v2(copy.deepcopy(v1))
        self.assertEqual(
            json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True)
        )
        evidence = parse_candidate_evidence_v2(first)
        self.assertEqual(len(evidence.entries), len(v1["entries"]))

    def test_the_read_path_accepts_both_versions(self) -> None:
        v1 = self.v1_document()
        _, evidence_v2 = self.build(self.v2_response())
        from_v1 = read_candidate_evidence(v1)
        from_v2 = read_candidate_evidence(
            json.loads(render_candidate_evidence_v2(evidence_v2))
        )
        self.assertIsInstance(from_v1, CandidateEvidenceV2)
        self.assertIsInstance(read_candidate_evidence(evidence_v2), CandidateEvidenceV2)
        self.assertIsInstance(from_v2, CandidateEvidenceV2)
        self.assertEqual(
            [e.candidate_id for e in from_v1.entries],
            [e.candidate_id for e in from_v2.entries],
        )
        # v1 carries no structured observation: migration records none, and derives
        # presence only from action evidence that v1 actually recorded.
        self.assertTrue(all(not e.observable_states for e in from_v1.entries))
        for entry in from_v1.entries:
            expected = (
                ActionPresence.ACTION_PRESENT
                if entry.action_evidence
                else ActionPresence.NOT_RECORDED
            )
            self.assertIs(entry.action_presence, expected, entry.candidate_id)
        # v2 states presence for analysed Candidates; a non-analysed one stays silent.
        self.assertTrue(
            any(e.action_presence is not ActionPresence.NOT_RECORDED for e in from_v2.entries)
        )

    def test_an_analyzed_v1_object_is_read_and_migrated_honestly(self) -> None:
        """The advertised object input must behave exactly like the JSON input.

        It previously raised: the object path wrapped every v1 entry with no
        observations, and a v2 invariant requires an analyzed entry to have them.
        """

        request = self.request(prompt_version=PROMPT_CONTRACT_VERSION)
        response = parse_analysis_response(
            {
                **copy.deepcopy(self.v1_response),
                "request": {
                    "ref": "analysis/candidate_analysis_request.json",
                    "sha256": hashlib.sha256(
                        render_analysis_request(request).encode("utf-8")
                    ).hexdigest(),
                },
            },
            request=request,
            request_text=render_analysis_request(request),
        )
        v1_object = build_candidate_evidence(
            request=request, response=response, extraction=self.extraction
        )
        analyzed = [
            entry for entry in v1_object.entries
            if entry.status is EvidenceStatus.ANALYZED
        ]
        self.assertTrue(analyzed, "the fixture chain has analyzed entries")
        migrated = read_candidate_evidence(v1_object)
        analyzed_migrated = [
            entry for entry in migrated.entries
            if entry.status is EvidenceStatus.ANALYZED
        ]
        self.assertEqual(len(migrated.entries), len(v1_object.entries))
        for entry in analyzed_migrated:
            self.assertIsNotNone(entry.observations)
            self.assertEqual(entry.observable_states, ())
            self.assertIn(
                entry.action_presence,
                (ActionPresence.ACTION_PRESENT, ActionPresence.NOT_RECORDED),
            )
            expected = (
                ActionPresence.ACTION_PRESENT
                if entry.action_evidence
                else ActionPresence.NOT_RECORDED
            )
            self.assertIs(entry.action_presence, expected)
        # And the object path agrees with the JSON path, entry for entry.
        from_json = read_candidate_evidence(self.v1_document())
        self.assertEqual(
            [e.as_dict() for e in migrated.entries],
            [e.as_dict() for e in from_json.entries],
        )

    def test_a_non_analyzed_v1_object_carries_no_observations(self) -> None:
        from src.ai_autocut.candidate_evidence import (
            AnalysisRun,
            CandidateEvidence,
            CandidateEvidenceEntry,
            ProductFacts,
        )

        entry = CandidateEvidenceEntry(
            candidate_id="candv1_" + "a" * 64,
            status=EvidenceStatus.UNKNOWN,
            rationale="the analyzer did not read this window",
        )
        v1_object = CandidateEvidence(
            candidate_pool_id="poolv1_" + "b" * 64,
            product_facts=ProductFacts("brief/product_facts.json", "c" * 64, ("fact_x",)),
            analysis_run=AnalysisRun("run", "p", "m", "prompt.v1"),
            entries=(entry,),
        )
        migrated = read_candidate_evidence(v1_object)
        self.assertIs(migrated.entries[0].status, EvidenceStatus.UNKNOWN)
        self.assertIsNone(migrated.entries[0].observations)
        self.assertIs(
            migrated.entries[0].action_presence, ActionPresence.NOT_RECORDED
        )

    def test_an_unknown_version_is_refused(self) -> None:
        with self.assertRaises(CandidateEvidenceV2Error):
            read_candidate_evidence({"schema_version": "candidate_evidence.v3"})

    def test_the_v1_parser_still_reads_v1_unchanged(self) -> None:
        v1 = self.v1_document()
        self.assertEqual(v1["schema_version"], V1_SCHEMA_VERSION)
        parsed = parse_candidate_evidence(v1)
        self.assertEqual(len(parsed.entries), len(v1["entries"]))


class PromptContractTests(V2TestCase):
    def test_prompt_contracts_declare_the_evidence_version_they_produce(self) -> None:
        self.assertEqual(
            evidence_contract_for(PROMPT_CONTRACT_VERSION), V1_SCHEMA_VERSION
        )
        self.assertEqual(
            evidence_contract_for(ANALYZER_PROMPT_CONTRACT_VERSION), V1_SCHEMA_VERSION
        )
        self.assertEqual(
            evidence_contract_for(STRUCTURED_PROMPT_CONTRACT_VERSION), SCHEMA_VERSION
        )
        with self.assertRaises(CandidateAnalysisError):
            evidence_contract_for("candidate_evidence_prompt.v99")

    def test_the_v3_prompt_states_the_ladder_the_vocabulary_and_the_rules(self) -> None:
        contract = prompt_contract(STRUCTURED_PROMPT_CONTRACT_VERSION)
        text = " ".join(contract.question.split())
        for register in ("OBSERVATION", "DIRECT", "CONTEXTUAL", "INFERRED", "UNSUPPORTED"):
            self.assertIn(register, text)
        for code in OBSERVABLE_STATE_MEANINGS:
            self.assertIn(code, text)
        self.assertIn("never claims", text)
        self.assertIn("never derive a claim from an observation", text.lower())
        self.assertIn("ACTION_PRESENT", text)
        self.assertIn("NO_ACTION", text)
        self.assertIn("NOT_RECORDED", text)

    def test_the_stage_produces_v2_when_the_contract_says_so(self) -> None:
        import tempfile
        import shutil as _shutil

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, tmp, ignore_errors=True)
        result = run_candidate_evidence_stage(
            job_root=tmp,
            extraction=self.extraction,
            envelope=self.envelope,
            run_id="analysisrunv1_v2stage",
            prompt_contract_version=STRUCTURED_PROMPT_CONTRACT_VERSION,
            response_document=self.v2_response(
                CandidateAnalysisRequest(
                    run_id="analysisrunv1_v2stage",
                    candidate_pool_id=self.extraction.pool.pool_id,
                    claim_envelope=self.envelope,
                    targets=targets_from_extraction(self.extraction),
                    prompt_contract_version=STRUCTURED_PROMPT_CONTRACT_VERSION,
                    question=prompt_for(STRUCTURED_PROMPT_CONTRACT_VERSION),
                )
            ),
        )
        written = json.loads(
            (tmp / "analysis/candidate_evidence.json").read_text(encoding="utf-8")
        )
        self.assertEqual(written["schema_version"], SCHEMA_VERSION)
        self.assertIsInstance(result.evidence, CandidateEvidenceV2)
        self.assertEqual(result.response.counts()["analyzed"], 5)
        request = json.loads(
            (tmp / "analysis/candidate_analysis_request.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            request["prompt_contract_version"], STRUCTURED_PROMPT_CONTRACT_VERSION
        )

    def test_a_v1_answer_cannot_satisfy_a_v3_request(self) -> None:
        import tempfile
        import shutil as _shutil

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, tmp, ignore_errors=True)
        result = run_candidate_evidence_stage(
            job_root=tmp,
            extraction=self.extraction,
            envelope=self.envelope,
            run_id=self.v1_response["run_id"],
            prompt_contract_version=STRUCTURED_PROMPT_CONTRACT_VERSION,
            response_document=self.v1_response,
        )
        self.assertIsNotNone(result.response.response_failure)
        self.assertIn("prompt contract", result.response.response_failure or "")
        # Every Candidate is still present, and the document is still v2-shaped.
        self.assertEqual(len(result.evidence.entries), len(self.extraction.pool.entries))
        self.assertIsInstance(result.evidence, CandidateEvidenceV2)


class SupportGateTests(V2TestCase):
    def test_a_required_premise_is_answered_from_structure_only(self) -> None:
        _, evidence = self.build(self.v2_response())
        views = {v.candidate_id: v for v in authoritative_evidence_view(evidence)}
        structured = next(
            v for v in views.values() if v.has_state(ObservableState.PROBLEM_STATE_VISIBLE)
        )
        check = check_machine_support(
            structured, observable_states=(ObservableState.PROBLEM_STATE_VISIBLE,)
        )
        self.assertIs(check.support, MachineSupport.SUPPORTED)
        self.assertEqual(check.satisfied_by, ("observation:PROBLEM_STATE_VISIBLE",))

    def test_the_required_support_class_is_respected(self) -> None:
        _, evidence = self.build(self.v2_response())
        candidates = [
            v
            for v in authoritative_evidence_view(evidence)
            if "fact_surface_state_change_visible"
            in v.claims_with(ClaimSupport.CONTEXTUAL)
        ]
        if not candidates:
            # None of these windows carries a CONTEXTUAL state-change claim, so give
            # one a CONTEXTUAL claim and re-read: the gate is what is under test.
            document = self.v2_response()
            entry = next(e for e in document["entries"] if e["claims"])
            fact = self.envelope.allowed_fact_refs[0]
            entry["claims"] = [
                {
                    "product_fact_ref": fact,
                    "support": "CONTEXTUAL",
                    "provenance": [],
                    "note": "supported by context, not by direct proof",
                }
            ]
            entry["observations"]["claim_support_class"] = "CONTEXTUAL_ONLY"
            _, evidence = self.build(document)
            candidates = [
                v
                for v in authoritative_evidence_view(evidence)
                if fact in v.claims_with(ClaimSupport.CONTEXTUAL)
            ]
        contextual_only = candidates[0]
        fact = contextual_only.claims_with(ClaimSupport.CONTEXTUAL)[0]
        weak = check_machine_support(contextual_only, product_fact_refs=(fact,))
        self.assertIs(weak.support, MachineSupport.NOT_MACHINE_SUPPORTED)
        satisfied = check_machine_support(
            contextual_only,
            product_fact_refs=(fact,),
            required_support=ClaimSupport.CONTEXTUAL,
        )
        self.assertIs(satisfied.support, MachineSupport.SUPPORTED)

    def test_a_check_without_a_premise_is_refused(self) -> None:
        _, evidence = self.build(self.v2_response())
        view = authoritative_evidence_view(evidence)[0]
        with self.assertRaises(CandidateEvidenceV2Error):
            check_machine_support(view)


if __name__ == "__main__":
    unittest.main()
