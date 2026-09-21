"""Hook / Narrative Decision: one creative call, provenance, and a veto that cannot rank.

Three claims are held here. The model owns generation and ordering, so the gate must
never invent a reason to reject a viable angle - when several hypotheses are eligible the
decision is *pending*, never "weaker". Provenance is the supplied evidence bytes in the
supplied version, while eligibility is answered from the migrated authoritative view, so
a v1 artifact keeps meaning what it always meant. And the stage reads Phase 2's result
exactly once: no frame, no prose field, no second model call.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from src.ai_autocut import authoring, producer_registry
from src.ai_autocut.candidate_analysis import (
    PROMPT_CONTRACT_VERSION as ANALYSIS_PROMPT_V1,
    STRUCTURED_PROMPT_CONTRACT_VERSION,
    CandidateAnalysisRequest,
    build_candidate_evidence,
    parse_analysis_response,
    parse_claim_envelope,
    parse_measurements,
    parse_segmentations,
    prompt_for,
    render_analysis_request,
    targets_from_extraction,
)
from src.ai_autocut.candidate_evidence import (
    SCHEMA_VERSION as EVIDENCE_V1,
    ClaimSupport,
    ProductFacts,
    parse_candidate_evidence,
    render_candidate_evidence,
)
from src.ai_autocut.candidate_evidence_v2 import (
    SCHEMA_VERSION as EVIDENCE_V2,
    ActionPresence,
    ObservableState,
    read_candidate_evidence,
    render_candidate_evidence_v2,
    supplied_evidence_text,
)
from src.ai_autocut.candidate_pool import parse_candidate_pool
from src.ai_autocut.candidate_extraction import (
    extract_candidates,
    parse_window_proposals,
)
from src.ai_autocut.creative_intent import (
    DecisionOwner,
    EvidenceCoverage,
    EvidenceRequirement,
    FactSafety,
    HookType,
    RejectionCode,
    VisualSupport,
    parse_hook_decision,
    render_hook_decision,
    structured_support_satisfied,
    validate_hook_decision,
    validate_hook_decision_against_evidence,
)
from src.ai_autocut.editing_intelligence import CoverageToken
from src.ai_autocut.hook_planning import (
    BRIEF_FIELDS,
    HOOK_PLANNING_QUESTION,
    OUTCOME_INSUFFICIENT,
    OUTCOME_PENDING,
    OUTCOME_SELECTED,
    PROMPT_CONTRACT_VERSION,
    HookPlanningError,
    ProposedHypothesis,
    assess_hypothesis,
    build_brief_context,
    build_planning_request,
    evidence_gap,
    parse_planning_response,
    planning_context,
    planning_request_reference,
    render_planning_request,
    run_hook_planning_stage,
    validate_brief_binding,
    validate_declared_support,
)
from src.ai_autocut.identity import parse_identity_catalog


FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = FIXTURES / "phase2_identity_catalog_v1.json"
MEASUREMENTS = FIXTURES / "phase2_candidate_measurements_v1.json"
SEGMENTATIONS = FIXTURES / "phase2_candidate_segmentations_v1.json"
PROPOSALS = FIXTURES / "phase2_candidate_window_proposal_v1.json"
ENVELOPE = FIXTURES / "phase2_claim_envelope_v1.json"
ANSWER_FIXTURE = FIXTURES / "phase2_candidate_analysis_response_v1.json"
FROZEN_EVIDENCE = FIXTURES / "candidate_evidence_v1_valid.json"
FROZEN_DECISION = FIXTURES / "hook_decision_v1_valid.json"
FROZEN_POOL = FIXTURES / "vnext_candidate_pool_v1_valid.json"

RUN_ID = "hookrunv1_phase3"

#: Prose, coordinates and provenance must never appear in the model's context.
PROSE_MARKERS = (
    "rationale",
    "visible_action",
    "visible_result",
    "a forearm works a cloth",
    "the surface is left clear",
    "provenance",
    "start_frame",
    "confidence",
    "risk_notes",
    "analysis_run",
)

#: Nothing downstream of a hook decision may appear in it.
DOWNSTREAM_TERMS = (
    "timeline",
    "trim",
    "sequence",
    "subtitle",
    "voice_over",
    "voiceover",
    "narration",
    "typography",
    "render",
    "audio",
    "score",
    "predicted",
    "conversion",
    "ab_test",
)

_DECISION_KEYS = (
    "brief",
    "candidate_evidence",
    "decision_owner",
    "hypotheses",
    "schema_version",
    "selected_hook_id",
    "selection_reason_codes",
)
_HYPOTHESIS_KEYS = (
    "assessment",
    "available_visual_support",
    "commercial_premise",
    "copy_direction",
    "expected_opening_structure",
    "hook_id",
    "hook_type",
    "required_evidence",
)

#: The frames the fixture windows start at, named for what they show.
SCRUB, PLATE, LEG, RINSE, TIGHT = 0, 10, 30, 75, 88

#: The scripted analyzer's structured answer, per window. Chosen for what Phase 3 must
#: decide: the scrub window carries a problem, a change and a person handling the
#: subject; the plate holds the product with no action; the leg window shows the product
#: not at all; the rinse window shows flow but no result state.
STRUCTURED_ANSWER = {
    SCRUB: (
        "ACTION_PRESENT",
        (
            "BEFORE_AFTER_RELATION_VISIBLE",
            "CLEAN_STATE_VISIBLE",
            "CONTACT_VISIBLE",
            "HUMAN_USE_VISIBLE",
            "PROBLEM_STATE_VISIBLE",
            "STATE_CHANGE_VISIBLE",
        ),
    ),
    PLATE: ("NO_ACTION", ("PRODUCT_BEAUTY_STATE_VISIBLE", "PRODUCT_IDENTITY_VISIBLE")),
    LEG: ("ACTION_PRESENT", ("CONTACT_VISIBLE", "STATE_CHANGE_VISIBLE")),
    RINSE: ("ACTION_PRESENT", ("FLOW_VISIBLE",)),
    TIGHT: ("ACTION_PRESENT", ("FLOW_VISIBLE",)),
}

MANIFEST = {
    "schema_version": "job_manifest.v2",
    "job_id": "fixture-job",
    "created_at": "2026-09-21T00:00:00Z",
    "product": {
        "name": "Fixture Filter",
        "name_localized": "滤芯",
        "market": "ID",
        "platform": "TikTok",
        "language": "Indonesian",
        "cta": "Check the faucet size before buying",
        "target_duration_seconds": {"minimum": 15, "maximum": 20},
        "notes": "user-centric commercial copy",
    },
    "source": {"inventory": "source_inventory.json", "count": 4},
    "runtime": {
        "external_workspace": "/tmp/job",
        "media_root": "/tmp/media",
        "davinci_application": "/Applications/DaVinci.app",
    },
}
BRIEF_TEXT = json.dumps(MANIFEST, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def hypothesis(
    hook_type: HookType,
    premise: str,
    *,
    candidate: str,
    token: CoverageToken,
    facts: tuple[str, ...] = (),
    support: ClaimSupport = ClaimSupport.CONTEXTUAL,
) -> ProposedHypothesis:
    """One hypothesis, shaped the way a creative answer would state it."""

    return ProposedHypothesis(
        hook_type=hook_type,
        commercial_premise=premise,
        copy_direction="open on the visible state, then bring the product in",
        expected_opening_structure="state first, product inside two seconds",
        required_evidence=(EvidenceRequirement(token, f"{token.value} is required"),),
        available_visual_support=(VisualSupport(candidate, token, support),),
        product_fact_refs=facts,
    )


#: Every frozen Hook type, one premise a window can carry, and one it cannot. CURIOSITY is
#: answered from structured observations in v2 and from nothing at all in v1, which is why
#: its negative case uses the other evidence version.
HOOK_CASES = (
    (
        HookType.PAIN,
        "the surface is still soiled before anything is done",
        CoverageToken.USAGE_CONTEXT,
        SCRUB,
        RINSE,
        EVIDENCE_V2,
    ),
    (
        HookType.OLD_WAY,
        "people still scrub this by hand",
        CoverageToken.ACTION_ONSET,
        SCRUB,
        RINSE,
        EVIDENCE_V2,
    ),
    (
        HookType.RESULT,
        "the surface ends clear of what it started with",
        CoverageToken.OBSERVABLE_RESULT,
        SCRUB,
        RINSE,
        EVIDENCE_V2,
    ),
    (
        HookType.CURIOSITY,
        "what does the stream carry away from the surface",
        CoverageToken.USAGE_CONTEXT,
        RINSE,
        PLATE,
        EVIDENCE_V1,
    ),
    (
        HookType.PRODUCT_DIRECT,
        "here is the filter itself, turned to the light",
        CoverageToken.IDENTITY_SHOT,
        PLATE,
        LEG,
        EVIDENCE_V2,
    ),
)


class P3TestCase(unittest.TestCase):
    """The Phase 2 fixture chain supplies the Candidates, the Pool and the evidence."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = parse_identity_catalog(json.loads(CATALOG.read_text()))
        cls.envelope = parse_claim_envelope(json.loads(ENVELOPE.read_text()))
        cls.facts = cls.envelope.product_facts()
        cls.extraction = extract_candidates(
            catalog=cls.catalog,
            measurements=parse_measurements(json.loads(MEASUREMENTS.read_text())),
            segmentations=parse_segmentations(json.loads(SEGMENTATIONS.read_text())),
            proposals=parse_window_proposals(json.loads(PROPOSALS.read_text())),
        )
        cls.answer_fixture = json.loads(ANSWER_FIXTURE.read_text())
        cls.starts = {
            candidate.candidate_id: candidate.start_frame
            for candidate in cls.extraction.candidates
        }
        cls.frozen_evidence_text = FROZEN_EVIDENCE.read_text(encoding="utf-8")
        cls.frozen_evidence = parse_candidate_evidence(
            json.loads(cls.frozen_evidence_text)
        )
        cls.frozen_decision = json.loads(FROZEN_DECISION.read_text())
        cls.frozen_pool = parse_candidate_pool(json.loads(FROZEN_POOL.read_text()))

    def setUp(self) -> None:
        self.job = Path(tempfile.mkdtemp(prefix="p3-"))
        self.addCleanup(shutil.rmtree, self.job, ignore_errors=True)
        self.brief = build_brief_context(
            json.loads(BRIEF_TEXT), ref="brief/job_manifest.json", text=BRIEF_TEXT
        )
        self.evidence = self.evidence_v2()

    # ---- the Phase 2 documents --------------------------------------------

    def analysis_request(self, prompt_version: str) -> CandidateAnalysisRequest:
        return CandidateAnalysisRequest(
            run_id=self.answer_fixture["run_id"],
            candidate_pool_id=self.extraction.pool.pool_id,
            claim_envelope=self.envelope,
            targets=targets_from_extraction(self.extraction),
            prompt_contract_version=prompt_version,
            question=prompt_for(prompt_version),
        )

    def answer_document(self, structured: bool) -> tuple[CandidateAnalysisRequest, dict]:
        """The Phase 2 answer, with or without the structured observation fields."""

        request = self.analysis_request(
            STRUCTURED_PROMPT_CONTRACT_VERSION if structured else ANALYSIS_PROMPT_V1
        )
        document = copy.deepcopy(self.answer_fixture)
        document["run_id"] = request.run_id
        document["candidate_pool_id"] = request.candidate_pool_id
        document["prompt_contract_version"] = request.prompt_contract_version
        document["request"] = {
            "ref": "analysis/candidate_analysis_request.json",
            "sha256": hashlib.sha256(
                render_analysis_request(request).encode("utf-8")
            ).hexdigest(),
        }
        if structured:
            for entry in document["entries"]:
                if entry["observations"] is None:
                    continue
                presence, states = STRUCTURED_ANSWER[self.starts[entry["candidate_id"]]]
                entry["observations"]["action_presence"] = presence
                entry["observations"]["observable_states"] = list(states)
        return request, document

    def evidence_v2(self):
        """Candidate Evidence v2, produced by the real Phase 2 stage."""

        request, document = self.answer_document(structured=True)
        response = parse_analysis_response(
            document,
            request=request,
            request_text=render_analysis_request(request),
            evidence_contract_version=EVIDENCE_V2,
        )
        return build_candidate_evidence(
            request=request,
            response=response,
            extraction=self.extraction,
            evidence_contract_version=EVIDENCE_V2,
        )

    def evidence_v1(self) -> dict:
        """Candidate Evidence v1: no structured observation was ever recorded."""

        request, document = self.answer_document(structured=False)
        response = parse_analysis_response(
            document,
            request=request,
            request_text=render_analysis_request(request),
            evidence_contract_version=EVIDENCE_V1,
        )
        return json.loads(
            render_candidate_evidence(
                build_candidate_evidence(
                    request=request,
                    response=response,
                    extraction=self.extraction,
                    evidence_contract_version=EVIDENCE_V1,
                )
            )
        )

    def id_at(self, start: int) -> str:
        for candidate_id, frame in self.starts.items():
            if frame == start:
                return candidate_id
        raise AssertionError(f"no Candidate starts at frame {start}")

    # ---- P3 helpers --------------------------------------------------------

    def context(self, evidence=None, **overrides):
        arguments = {
            "run_id": RUN_ID,
            "evidence": self.evidence if evidence is None else evidence,
            "brief": self.brief,
            "product_facts": self.facts,
        }
        arguments.update(overrides)
        return planning_context(**arguments)

    def assess(self, proposal: ProposedHypothesis, evidence=None, **overrides):
        return assess_hypothesis(
            proposal,
            pool=self.extraction.pool,
            context=self.context(evidence, **overrides),
        )

    def proposal_payload(self, item: ProposedHypothesis) -> dict:
        """What a model writes: the response shape, from the parser's own inverse."""

        return item.as_dict()

    def answer(self, hypotheses, *, context=None, **overrides) -> dict:
        request = build_planning_request(
            self.context() if context is None else context
        )
        document = {
            "schema_version": "hook_planning_response.v1",
            "run_id": request.run_id,
            "candidate_pool_id": self.extraction.pool.pool_id,
            "provider": "fixture_provider",
            "model": "fixture_model",
            "prompt_contract_version": request.prompt_contract_version,
            "request": planning_request_reference(request).as_dict(),
            "hypotheses": [self.proposal_payload(item) for item in hypotheses],
        }
        document.update(overrides)
        return document

    def run_stage(self, hypotheses, evidence=None, *, agent=None, document=None):
        supplied = self.evidence if evidence is None else evidence
        return run_hook_planning_stage(
            job_root=self.job,
            evidence=supplied,
            brief=self.brief,
            product_facts=self.facts,
            pool=self.extraction.pool,
            catalog=self.extraction.catalog,
            run_id=RUN_ID,
            agent=agent,
            response_document=(
                document
                if document is not None
                else (
                    None
                    if agent
                    else self.answer(hypotheses, context=self.context(supplied))
                )
            ),
        )

    def pain(self, start: int = SCRUB, **kwargs) -> ProposedHypothesis:
        return hypothesis(
            HookType.PAIN,
            "the surface is still soiled before anything is done",
            candidate=self.id_at(start),
            token=CoverageToken.USAGE_CONTEXT,
            **kwargs,
        )

    def result(self, start: int = SCRUB, **kwargs) -> ProposedHypothesis:
        return hypothesis(
            HookType.RESULT,
            "the surface ends clear of what it started with",
            candidate=self.id_at(start),
            token=CoverageToken.OBSERVABLE_RESULT,
            **kwargs,
        )

    def direct_plate(self) -> ProposedHypothesis:
        return hypothesis(
            HookType.PRODUCT_DIRECT,
            "here is the filter itself, turned to the light",
            candidate=self.id_at(PLATE),
            token=CoverageToken.IDENTITY_SHOT,
            support=ClaimSupport.DIRECT,
        )


class BriefTests(P3TestCase):
    def test_the_compact_brief_keeps_only_creative_fields(self) -> None:
        compact = self.brief.as_dict()
        self.assertEqual(tuple(compact), BRIEF_FIELDS)
        self.assertEqual(compact["market"], "ID")
        self.assertEqual(
            compact["target_duration_seconds"], {"minimum": 15, "maximum": 20}
        )

    def test_machine_locations_never_reach_the_model_context(self) -> None:
        rendered = render_planning_request(build_planning_request(self.context()))
        for marker in (
            "/tmp/",
            "/Applications/",
            "external_workspace",
            "media_root",
            "davinci",
            "source_inventory",
            "created_at",
            "job_id",
        ):
            self.assertNotIn(marker, rendered)

    def test_a_brief_without_a_product_name_is_refused(self) -> None:
        with self.assertRaises(HookPlanningError):
            build_brief_context(
                {"product": {"market": "ID"}}, ref="brief/x.json", text=BRIEF_TEXT
            )

    def test_the_brief_binds_its_exact_bytes(self) -> None:
        result = self.run_stage([self.result(), self.pain(RINSE)])
        validate_brief_binding(result.decision, BRIEF_TEXT)
        with self.assertRaises(HookPlanningError) as caught:
            validate_brief_binding(
                result.decision, BRIEF_TEXT.replace("Indonesian", "Malay")
            )
        self.assertIn("does not match", str(caught.exception))

    def test_facts_that_do_not_match_the_evidence_are_refused(self) -> None:
        widened = ProductFacts(
            self.facts.ref,
            self.facts.sha256,
            tuple(self.facts.allowed_fact_refs) + ("fact_kills_bacteria",),
        )
        with self.assertRaises(HookPlanningError) as caught:
            self.context(product_facts=widened)
        self.assertIn("Claim Envelope", str(caught.exception))


class EvidenceBindingTests(P3TestCase):
    """Provenance binds the supplied bytes; reasoning uses the migrated view."""

    def test_each_version_binds_its_own_canonical_bytes(self) -> None:
        v1_document = self.evidence_v1()
        v1_object = parse_candidate_evidence(v1_document)
        v2_document = json.loads(render_candidate_evidence_v2(self.evidence))
        cases = {
            "v1 dict": (v1_document, render_candidate_evidence(v1_object)),
            "v1 object": (v1_object, render_candidate_evidence(v1_object)),
            "v2 dict": (v2_document, render_candidate_evidence_v2(self.evidence)),
            "v2 object": (self.evidence, render_candidate_evidence_v2(self.evidence)),
        }
        shas = {}
        for label, (supplied, expected_text) in cases.items():
            with self.subTest(supplied=label):
                context = self.context(supplied)
                self.assertEqual(supplied_evidence_text(supplied), expected_text)
                self.assertEqual(
                    context.evidence.sha256,
                    hashlib.sha256(expected_text.encode("utf-8")).hexdigest(),
                )
                self.assertEqual(
                    context.evidence.ref,
                    producer_registry.CANDIDATE_EVIDENCE_ARTIFACT,
                )
                shas[label] = context.evidence.sha256
        # A v1 artifact must never be bound to the v2 rendering migration produces.
        self.assertNotEqual(shas["v1 dict"], shas["v2 object"])
        self.assertEqual(shas["v1 dict"], shas["v1 object"])
        self.assertEqual(shas["v2 dict"], shas["v2 object"])

    def test_a_v1_artifact_run_end_to_end_binds_v1_bytes(self) -> None:
        evidence = self.evidence_v1()
        result = self.run_stage([self.pain(SCRUB), self.direct_plate()], evidence=evidence)
        self.assertEqual(result.outcome, OUTCOME_SELECTED)
        written = json.loads(
            (self.job / producer_registry.HOOK_DECISION_ARTIFACT).read_text(
                encoding="utf-8"
            )
        )
        expected = hashlib.sha256(
            render_candidate_evidence(parse_candidate_evidence(evidence)).encode("utf-8")
        ).hexdigest()
        self.assertEqual(written["candidate_evidence"]["sha256"], expected)
        self.assertNotEqual(
            written["candidate_evidence"]["sha256"],
            hashlib.sha256(
                render_candidate_evidence_v2(self.evidence).encode("utf-8")
            ).hexdigest(),
        )
        # And the frozen validator accepts it against the artifact as supplied.
        validate_hook_decision_against_evidence(
            parse_hook_decision(written),
            evidence,
            self.extraction.pool,
            self.extraction.catalog,
        )

    def test_the_request_reference_is_content_addressed(self) -> None:
        request = build_planning_request(self.context())
        self.assertEqual(
            planning_request_reference(request).sha256,
            hashlib.sha256(render_planning_request(request).encode("utf-8")).hexdigest(),
        )

    def test_a_v1_document_is_read_honestly_not_guessed(self) -> None:
        document = self.evidence_v1()
        context = self.context(document)
        recorded = {
            entry.candidate_id: bool(entry.action_evidence)
            for entry in parse_candidate_evidence(document).entries
        }
        for candidate in context.compact:
            # v1 recorded no structured observation, so nothing is claimed as one.
            self.assertEqual(candidate.observable_states, ())
            self.assertEqual(
                candidate.action_presence,
                (
                    ActionPresence.ACTION_PRESENT.value
                    if recorded[candidate.candidate_id]
                    else ActionPresence.NOT_RECORDED.value
                ),
            )


class HistoricalSemanticsTests(P3TestCase):
    """The frozen v1 result rule is restored, and P3 stays strict. Both, separately."""

    def frozen_result_candidate(self) -> str:
        for item in self.frozen_decision["hypotheses"]:
            if item["hook_type"] == "RESULT":
                return item["available_visual_support"][-1]["candidate_id"]
        raise AssertionError("the frozen fixture has no RESULT hypothesis")

    def test_the_same_artifact_does_not_satisfy_p3_result_eligibility(self) -> None:
        """The contract-level half of this pair lives in tests/test_creative_intent.py."""


        proposal = hypothesis(
            HookType.RESULT,
            "the surface ends clear of what it started with",
            candidate=self.frozen_result_candidate(),
            token=CoverageToken.OBSERVABLE_RESULT,
        )
        verdict = assess_hypothesis(
            proposal,
            pool=self.frozen_pool,
            context=planning_context(
                run_id=RUN_ID,
                evidence=json.loads(self.frozen_evidence_text),
                brief=self.brief,
                product_facts=self.frozen_evidence.product_facts,
            ),
        )
        self.assertFalse(verdict.eligible)
        self.assertIs(verdict.rejection, RejectionCode.INSUFFICIENT_EVIDENCE)
        self.assertIn("records none of", verdict.detail)

    def test_p3_result_eligibility_is_structured_only(self) -> None:
        self.assertTrue(self.assess(self.result()).eligible)
        verdict = self.assess(self.result(), self.evidence_v1())
        self.assertFalse(verdict.eligible)
        self.assertIn("records none of", verdict.detail)
        self.assertIn("CLEAN_STATE_VISIBLE", verdict.detail)


class OwnershipTests(P3TestCase):
    """The model ranks; the code vetoes. It never chooses between viable options."""

    def test_exactly_one_eligible_hypothesis_is_selected(self) -> None:
        result = self.run_stage([self.pain(RINSE), self.result()])
        self.assertEqual(result.outcome, OUTCOME_SELECTED)
        self.assertEqual(result.selected_hook_id, self.result().hook_id)
        self.assertIs(result.decision.decision_owner, DecisionOwner.SUPERVISOR_AGENT)
        rejected = [
            item for item in result.decision.hypotheses if item.assessment.rejection_codes
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(
            [code.value for code in rejected[0].assessment.rejection_codes],
            ["INSUFFICIENT_EVIDENCE"],
        )

    def test_several_eligible_hypotheses_leave_a_pending_decision(self) -> None:
        answer = [self.pain(), self.result(), self.direct_plate()]
        result = self.run_stage(answer)
        self.assertTrue(all(verdict.eligible for verdict in result.verdicts))
        self.assertEqual(result.outcome, OUTCOME_PENDING)
        self.assertIsNone(result.selected_hook_id)
        self.assertIs(result.decision.decision_owner, DecisionOwner.UNASSIGNED)
        self.assertEqual(result.decision.selection_reason_codes, ())
        # Nothing was fabricated to make a choice look decided.
        for item in result.decision.hypotheses:
            self.assertEqual(item.assessment.rejection_codes, ())
        validate_hook_decision(result.decision)
        validate_hook_decision_against_evidence(
            result.decision,
            self.evidence,
            self.extraction.pool,
            self.extraction.catalog,
        )

    def test_no_hypothesis_ever_receives_a_fabricated_weaker_code(self) -> None:
        result = self.run_stage([self.pain(), self.result()])
        for item in result.decision.hypotheses:
            self.assertNotIn(
                RejectionCode.WEAKER_EVIDENCE, item.assessment.rejection_codes
            )
        for verdict in result.verdicts:
            self.assertNotIn(RejectionCode.WEAKER_EVIDENCE, verdict.rejection_codes)
        self.assertNotIn(
            RejectionCode.WEAKER_EVIDENCE.value,
            (self.job / producer_registry.HOOK_DECISION_ARTIFACT).read_text(
                encoding="utf-8"
            ),
        )

    def test_an_invalid_first_choice_yields_to_the_next_eligible_one(self) -> None:
        result = self.run_stage([self.pain(RINSE), self.result()])
        self.assertFalse(result.verdicts[0].eligible)
        self.assertEqual(result.selected_hook_id, self.result().hook_id)

    def test_the_answer_order_is_preserved_and_never_re_ranked(self) -> None:
        answer = [self.result(), self.pain(RINSE)]
        agent = authoring.ScriptedAuthoringAgent(
            {
                producer_registry.HOOK_PLANNING_RESPONSE_ARTIFACT: self.answer(
                    answer
                )
            }
        )
        result = self.run_stage(None, agent=agent)
        self.assertEqual(
            [verdict.proposal.commercial_premise for verdict in result.verdicts],
            [item.commercial_premise for item in answer],
        )
        # The model's own order is what the response artifact holds; the decision
        # document is sorted by hook_id by contract and never claims to be a ranking.
        written = json.loads(
            (self.job / producer_registry.HOOK_PLANNING_RESPONSE_ARTIFACT).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            [item["commercial_premise"] for item in written["hypotheses"]],
            [item.commercial_premise for item in answer],
        )

    def test_a_hypothesis_sharing_the_selected_type_is_named_a_duplicate(self) -> None:
        selected = self.result(SCRUB)
        same_type = hypothesis(
            HookType.RESULT,
            "the surface is left clean at the end of the scrub",
            candidate=self.id_at(RINSE),  # a viable premise the footage cannot carry
            token=CoverageToken.OBSERVABLE_RESULT,
        )
        result = self.run_stage([selected, same_type, self.pain(RINSE)])
        self.assertEqual(result.selected_hook_id, selected.hook_id)
        other = next(
            item
            for item in result.decision.hypotheses
            if item.hook_id == same_type.hook_id
        )
        self.assertEqual(
            [code.value for code in other.assessment.rejection_codes],
            ["DUPLICATES_SELECTED_PREMISE", "INSUFFICIENT_EVIDENCE"],
        )

    def test_exactly_one_model_call_and_no_retry(self) -> None:
        agent = authoring.ScriptedAuthoringAgent(
            {
                producer_registry.HOOK_PLANNING_RESPONSE_ARTIFACT: self.answer(
                    [self.result(), self.pain(RINSE)]
                )
            }
        )
        result = self.run_stage(None, agent=agent)
        self.assertEqual(len(agent.requests), 1)
        self.assertEqual(agent.requests[0].stage, "DECIDE THE HOOK")
        self.assertEqual(result.model_call_count, 1)
        self.assertEqual(result.response_source, "AUTHORING_SEAM")

    def test_a_declined_answer_fails_closed_without_a_second_call(self) -> None:
        with self.assertRaises(HookPlanningError) as caught:
            self.run_stage(None, agent=authoring.NullAuthoringAgent())
        self.assertIn("no second call", str(caught.exception))
        self.assertFalse((self.job / producer_registry.HOOK_DECISION_ARTIFACT).exists())

    def test_no_eligible_hypothesis_is_recorded_as_insufficient(self) -> None:
        result = self.run_stage([self.pain(RINSE), self.result(RINSE)])
        self.assertEqual(result.outcome, OUTCOME_INSUFFICIENT)
        self.assertIsNone(result.selected_hook_id)
        self.assertIs(result.decision.decision_owner, DecisionOwner.SUPERVISOR_AGENT)
        for item in result.decision.hypotheses:
            self.assertTrue(item.assessment.rejection_codes)
        for verdict in result.verdicts:
            self.assertIs(verdict.coverage, EvidenceCoverage.INSUFFICIENT)


class DirectSupportReasonTests(P3TestCase):
    """``DIRECT_VISUAL_SUPPORT`` requires the premise to name the fact it rests on."""

    def recorded_fact(self) -> str:
        for view in self.context().views.values():
            for fact, kind, _ in view.claims:
                if kind is ClaimSupport.DIRECT and fact in self.facts.allowed_fact_refs:
                    return fact
        raise AssertionError("the fixture records no direct permitted claim")

    def claim_premise(self, facts: tuple[str, ...]) -> ProposedHypothesis:
        return hypothesis(
            HookType.RESULT,
            "the surface ends clear of what it started with",
            candidate=self.id_at(SCRUB),
            token=CoverageToken.CLAIM_SUPPORT_DIRECT,
            facts=facts,
            support=ClaimSupport.DIRECT,
        )

    def test_the_reason_requires_a_named_and_recorded_fact(self) -> None:
        cases = {
            "named and recorded": (self.recorded_fact(),),
            "recorded but not named": (),
        }
        expected = {
            "named and recorded": ["DIRECT_VISUAL_SUPPORT", "FACT_SAFE"],
            "recorded but not named": ["FACT_SAFE"],
        }
        for label, facts in cases.items():
            with self.subTest(case=label):
                result = self.run_stage([self.claim_premise(facts), self.pain(RINSE)])
                self.assertEqual(result.outcome, OUTCOME_SELECTED)
                self.assertEqual(
                    [code.value for code in result.decision.selection_reason_codes],
                    expected[label],
                )

    def test_a_named_fact_without_recorded_direct_support_is_not_a_reason(self) -> None:
        verdict = self.assess(
            hypothesis(
                HookType.PRODUCT_DIRECT,
                "here is the filter itself, turned to the light",
                candidate=self.id_at(PLATE),
                token=CoverageToken.IDENTITY_SHOT,
                facts=("fact_product_identity_visible",),
                support=ClaimSupport.DIRECT,
            )
        )
        # The plate records no claim at all, so no direct-support reason may be claimed.
        self.assertTrue(verdict.eligible)
        self.assertFalse(verdict.direct_claim_backed)


class VetoTests(P3TestCase):
    def test_a_declared_fact_outside_the_envelope_is_vetoed(self) -> None:
        verdict = self.assess(
            hypothesis(
                HookType.RESULT,
                "the surface is hygienically clean afterwards",
                candidate=self.id_at(SCRUB),
                token=CoverageToken.OBSERVABLE_RESULT,
                facts=("fact_kills_bacteria",),
            )
        )
        self.assertFalse(verdict.eligible)
        self.assertIs(verdict.rejection, RejectionCode.UNSUPPORTED_CLAIM)
        self.assertIs(verdict.fact_safety, FactSafety.FACT_UNSAFE)
        self.assertIn("fact_kills_bacteria", verdict.detail)
        self.assertEqual(
            [code.value for code in verdict.rejection_codes],
            ["INSUFFICIENT_EVIDENCE", "UNSUPPORTED_CLAIM"],
        )

    def test_a_permitted_declared_fact_is_allowed(self) -> None:
        verdict = self.assess(
            hypothesis(
                HookType.RESULT,
                "the surface ends clear of what it started with",
                candidate=self.id_at(SCRUB),
                token=CoverageToken.OBSERVABLE_RESULT,
                facts=("fact_surface_result_state",),
            )
        )
        self.assertTrue(verdict.eligible, verdict.detail)
        self.assertIs(verdict.fact_safety, FactSafety.FACT_SAFE)

    def test_a_candidate_outside_the_pool_is_vetoed(self) -> None:
        verdict = self.assess(
            hypothesis(
                HookType.RESULT,
                "the surface ends clear of what it started with",
                candidate="candv1_" + "0" * 64,
                token=CoverageToken.OBSERVABLE_RESULT,
            )
        )
        self.assertFalse(verdict.eligible)
        self.assertIn("outside the Pool", verdict.detail)
        self.assertEqual(verdict.kept_support, ())
        self.assertIn(RejectionCode.NO_OPENING_VISUAL, verdict.rejection_codes)

    def test_declared_direct_support_must_really_be_recorded(self) -> None:
        verdict = self.assess(
            hypothesis(
                HookType.PRODUCT_DIRECT,
                "here is the filter itself",
                candidate=self.id_at(PLATE),
                token=CoverageToken.CLAIM_SUPPORT_DIRECT,
                support=ClaimSupport.DIRECT,
            )
        )
        self.assertFalse(verdict.eligible)
        self.assertIn("DIRECT visual support is not recorded", verdict.detail)

    def test_contextual_support_is_allowed_where_direct_is_not(self) -> None:
        kept, rejection, detail = validate_declared_support(
            hypothesis(
                HookType.CURIOSITY,
                "what does the stream carry away from the surface",
                candidate=self.id_at(RINSE),
                token=CoverageToken.USAGE_CONTEXT,
                support=ClaimSupport.DIRECT,
            ),
            pool=self.extraction.pool,
            views=self.context().views,
        )
        self.assertIsNone(rejection, detail)
        self.assertEqual(len(kept), 1)

    def test_no_action_and_not_recorded_are_different_facts(self) -> None:
        plate = self.context().views[self.id_at(PLATE)]
        self.assertIs(plate.action_presence, ActionPresence.NO_ACTION)
        self.assertFalse(structured_support_satisfied(plate, CoverageToken.ACTION_ONSET))
        recorded = self.context(self.evidence_v1()).views[self.id_at(PLATE)]
        self.assertIs(recorded.action_presence, ActionPresence.NOT_RECORDED)
        self.assertIsNot(recorded.action_presence, plate.action_presence)
        self.assertFalse(
            structured_support_satisfied(recorded, CoverageToken.ACTION_ONSET)
        )
        scrub = self.context().views[self.id_at(SCRUB)]
        self.assertIs(scrub.action_presence, ActionPresence.ACTION_PRESENT)
        self.assertTrue(structured_support_satisfied(scrub, CoverageToken.ACTION_ONSET))


class HookTypeTests(P3TestCase):
    """All five frozen Hook types, each carried by one window and refused by another."""

    def test_the_table_covers_the_frozen_vocabulary(self) -> None:
        self.assertEqual({case[0] for case in HOOK_CASES}, set(HookType))

    def test_every_hook_type_is_eligible_when_its_evidence_is_there(self) -> None:
        for hook_type, premise, token, ok_start, _, _ in HOOK_CASES:
            with self.subTest(hook_type=hook_type.value):
                verdict = self.assess(
                    hypothesis(
                        hook_type, premise, candidate=self.id_at(ok_start), token=token
                    )
                )
                self.assertTrue(verdict.eligible, verdict.detail)
                self.assertIs(verdict.fact_safety, FactSafety.FACT_SAFE)
                self.assertIs(verdict.rejection, None)

    def test_every_hook_type_is_vetoed_when_its_evidence_is_missing(self) -> None:
        for hook_type, premise, token, _, bad_start, version in HOOK_CASES:
            with self.subTest(hook_type=hook_type.value):
                evidence = (
                    self.evidence if version == EVIDENCE_V2 else self.evidence_v1()
                )
                verdict = self.assess(
                    hypothesis(
                        hook_type, premise, candidate=self.id_at(bad_start), token=token
                    ),
                    evidence,
                )
                self.assertFalse(verdict.eligible, verdict.detail)
                self.assertIs(verdict.rejection, RejectionCode.INSUFFICIENT_EVIDENCE)
                self.assertIn(hook_type.value, verdict.detail)

    def test_the_result_policy_reads_structured_result_states(self) -> None:
        states = self.context().views[self.id_at(SCRUB)].observable_states
        for state in (
            ObservableState.CLEAN_STATE_VISIBLE,
            ObservableState.STATE_CHANGE_VISIBLE,
            ObservableState.BEFORE_AFTER_RELATION_VISIBLE,
        ):
            with self.subTest(state=state.value):
                self.assertIn(state, states)

    def test_the_gap_function_answers_each_rule_kind(self) -> None:
        pain = ObservableState.PROBLEM_STATE_VISIBLE
        healthy = {
            "has_action": True,
            "product_on_screen": True,
            "answerable": True,
        }
        cases = (
            (HookType.PAIN, [pain], {}, None),
            (HookType.PAIN, [], {}, "PROBLEM_STATE_VISIBLE"),
            (HookType.RESULT, [], {}, "none of"),
            (HookType.OLD_WAY, [pain], {"has_action": False}, "action"),
            (
                HookType.PRODUCT_DIRECT,
                [],
                {"product_on_screen": False},
                "product",
            ),
            (HookType.CURIOSITY, [], {"answerable": False}, "answer the question"),
        )
        for hook_type, states, overrides, expected in cases:
            with self.subTest(hook_type=hook_type.value, expected=expected):
                gap = evidence_gap(
                    hook_type, frozenset(states), **{**healthy, **overrides}
                )
                if expected is None:
                    self.assertIsNone(gap)
                else:
                    self.assertIn(expected, gap)


class ModelContextTests(P3TestCase):
    def test_the_request_carries_structured_truth_and_no_prose(self) -> None:
        rendered = render_planning_request(build_planning_request(self.context()))
        document = json.loads(rendered)
        self.assertEqual(
            document["candidate_evidence"]["ref"],
            producer_registry.CANDIDATE_EVIDENCE_ARTIFACT,
        )
        self.assertEqual(document["prompt_contract_version"], PROMPT_CONTRACT_VERSION)
        self.assertEqual(document["question"], HOOK_PLANNING_QUESTION)
        self.assertEqual(len(document["candidates"]), len(self.extraction.candidates))
        for forbidden in PROSE_MARKERS:
            self.assertNotIn(forbidden, rendered)

    def test_the_compact_candidate_exposes_no_prose_key(self) -> None:
        context = self.context()
        self.assertEqual(
            sorted(context.compact[0].as_dict()),
            [
                "action_presence",
                "candidate_id",
                "claims",
                "observable_states",
                "product_visibility",
                "risk_codes",
                "status",
                "usage_context",
            ],
        )
        plate = next(
            one for one in context.compact if one.candidate_id == self.id_at(PLATE)
        )
        self.assertEqual(plate.action_presence, ActionPresence.NO_ACTION.value)
        self.assertEqual(plate.product_visibility, "HERO")

    def test_mutating_every_prose_field_changes_nothing_the_model_sees(self) -> None:
        before = json.loads(
            render_planning_request(build_planning_request(self.context()))
        )
        payload = json.loads(render_candidate_evidence_v2(self.evidence))
        for entry in payload["entries"]:
            entry["rationale"] = "this product kills bacteria and guarantees hygiene"
            if entry["observations"] is not None:
                entry["observations"]["visible_action"] = "a completely different story"
                entry["observations"]["visible_result"] = "a result nobody filmed"
            for claim in entry.get("claims") or []:
                claim["note"] = "a claim-like note"
            for risk in entry.get("risks") or []:
                risk["note"] = "a risk-like note"
        mutated = read_candidate_evidence(payload)
        after = json.loads(
            render_planning_request(build_planning_request(self.context(mutated)))
        )
        # The prose really did change the document, so its bytes moved.
        self.assertNotEqual(
            before["candidate_evidence"]["sha256"],
            after["candidate_evidence"]["sha256"],
        )
        for key in before:
            if key != "candidate_evidence":
                self.assertEqual(before[key], after[key], key)
        self.assertEqual(
            self.assess(self.result(), mutated).eligible,
            self.assess(self.result()).eligible,
        )


class FailClosedTests(P3TestCase):
    def malformed(self) -> dict[str, dict]:
        good = self.answer([self.result(), self.pain(RINSE)])
        cases: dict[str, dict] = {}
        cases["one hypothesis"] = {**good, "hypotheses": good["hypotheses"][:1]}
        cases["six hypotheses"] = {**good, "hypotheses": good["hypotheses"] * 3}
        unknown = copy.deepcopy(good)
        unknown["hypotheses"][0]["hook_type"] = "VIRAL"
        cases["unknown hook type"] = unknown
        confident = copy.deepcopy(good)
        confident["hypotheses"][0]["confidence"] = 0.93
        cases["a provider field in a hypothesis"] = confident
        duplicate = copy.deepcopy(good)
        duplicate["hypotheses"][1] = copy.deepcopy(duplicate["hypotheses"][0])
        cases["duplicate premise"] = duplicate
        path_fact = copy.deepcopy(good)
        path_fact["hypotheses"][0]["product_fact_refs"] = ["/etc/passwd"]
        cases["a path as a fact reference"] = path_fact
        no_requirements = copy.deepcopy(good)
        no_requirements["hypotheses"][0]["required_evidence"] = []
        cases["no stated requirement"] = no_requirements
        orphan_support = copy.deepcopy(good)
        orphan_support["hypotheses"][0]["available_visual_support"] = [
            {
                "candidate_id": self.id_at(SCRUB),
                "coverage_token": "BODY_AREA",
                "support": "CONTEXTUAL",
            }
        ]
        cases["support answering no requirement"] = orphan_support
        unknown_support = copy.deepcopy(good)
        unknown_support["hypotheses"][1]["available_visual_support"][0][
            "support"
        ] = "CERTAIN"
        cases["unknown support class"] = unknown_support
        cases["no model identity"] = {
            key: value for key, value in good.items() if key != "model"
        }
        return cases

    def test_malformed_answers_fail_closed_at_the_parser(self) -> None:
        request = build_planning_request(self.context())
        request_text = render_planning_request(request)
        for label, document in self.malformed().items():
            with self.subTest(case=label):
                with self.assertRaises(HookPlanningError):
                    parse_planning_response(
                        document, request=request, request_text=request_text
                    )

    def test_a_malformed_answer_fails_closed_end_to_end(self) -> None:
        with self.assertRaises(HookPlanningError):
            self.run_stage(None, document=self.malformed()["duplicate premise"])
        self.assertFalse((self.job / producer_registry.HOOK_DECISION_ARTIFACT).exists())

    def test_an_answer_to_another_request_is_refused(self) -> None:
        good = self.answer([self.result(), self.pain(RINSE)])
        for label, mutated in (
            (
                "another request hash",
                {**good, "request": {**good["request"], "sha256": "0" * 64}},
            ),
            ("another run", {**good, "run_id": "someone-elses-run"}),
            (
                "another prompt contract",
                {**good, "prompt_contract_version": "hook_decision_prompt.v2"},
            ),
        ):
            with self.subTest(case=label):
                with self.assertRaises(HookPlanningError):
                    self.run_stage(None, document=mutated)

    def test_the_question_narrows_the_stage(self) -> None:
        question = " ".join(HOOK_PLANNING_QUESTION.split())
        for hook_type in ("PAIN", "OLD_WAY", "RESULT", "CURIOSITY", "PRODUCT_DIRECT"):
            self.assertIn(hook_type, question)
        self.assertIn("You own that ranking", question)
        self.assertIn("never the finished line", question)
        self.assertIn("NO_ACTION", question)
        self.assertIn("NOT_RECORDED", question)
        self.assertIn("no voice-over, no subtitles, no final call to action", question)
        for out_of_scope in ("shot order", "timeline", "sequence"):
            self.assertNotIn(out_of_scope, question.lower())


class ArtifactTests(P3TestCase):
    def test_the_stage_writes_the_request_and_the_decision_only(self) -> None:
        self.run_stage([self.result(), self.pain(RINSE)])
        written = sorted(
            str(path.relative_to(self.job))
            for path in self.job.rglob("*")
            if path.is_file()
        )
        self.assertEqual(
            written,
            [
                producer_registry.HOOK_DECISION_ARTIFACT,
                producer_registry.HOOK_PLANNING_REQUEST_ARTIFACT,
            ],
        )

    def test_the_written_decision_is_a_valid_hook_decision_v1(self) -> None:
        result = self.run_stage([self.result(), self.pain(RINSE)])
        written = json.loads(
            (self.job / producer_registry.HOOK_DECISION_ARTIFACT).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(written["schema_version"], "hook_decision.v1")
        self.assertEqual(sorted(written), sorted(_DECISION_KEYS))
        self.assertEqual(sorted(written["hypotheses"][0]), sorted(_HYPOTHESIS_KEYS))
        self.assertEqual(written["decision_owner"], "SUPERVISOR_AGENT")
        self.assertEqual(written["brief"]["sha256"], self.brief.sha256)
        self.assertEqual(
            render_hook_decision(parse_hook_decision(written)), result.decision_text
        )
        validate_hook_decision_against_evidence(
            parse_hook_decision(written),
            self.evidence,
            self.extraction.pool,
            self.extraction.catalog,
        )

    def test_the_request_artifact_is_the_exact_bound_context(self) -> None:
        self.run_stage([self.result(), self.pain(RINSE)])
        request_text = (
            self.job / producer_registry.HOOK_PLANNING_REQUEST_ARTIFACT
        ).read_text(encoding="utf-8")
        request = build_planning_request(self.context())
        self.assertEqual(request_text, render_planning_request(request))
        self.assertEqual(
            hashlib.sha256(request_text.encode("utf-8")).hexdigest(),
            planning_request_reference(request).sha256,
        )

    def test_the_decision_carries_no_downstream_production_state(self) -> None:
        result = self.run_stage([self.result(), self.pain(RINSE)])
        rendered = (
            self.job / producer_registry.HOOK_DECISION_ARTIFACT
        ).read_text(encoding="utf-8")
        for forbidden in DOWNSTREAM_TERMS:
            self.assertNotIn(forbidden, rendered.lower())
        self.assertEqual(len(result.verdicts), 2)


if __name__ == "__main__":
    unittest.main()
