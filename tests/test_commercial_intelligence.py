"""Commercial Intelligence v1: strategy candidates, and their contract-only status.

Commercial Strategy v1 recorded the decision but nothing recorded the reasoning before it:
which consumer beliefs the candidates rest on, and which attractive ideas the material
cannot support. These tests hold the contract that closes that gap, and hold the lines that
make it trustworthy - an inference cannot present itself as verified market knowledge, a
forbidden claim cannot enter a viable candidate, a blocked idea cannot quietly become
usable, and there is no score or winner anywhere to be filled in.

The artifact stays CONTRACT_ONLY / NOT_WIRED: no producer registered, no stage requires it,
no consumer reads it.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

from src.ai_autocut import commercial_intelligence, fast_path, producer_registry
from src.ai_autocut.commercial_intelligence import (
    BLOCKING_CODES,
    DEFAULT_OBJECTIVE,
    HYPOTHESIS_SUPPORT,
    IMPLEMENTATION,
    UNSPECIFIED_PLATFORM,
    WIRING_STATUS,
    CommercialIntelligenceContractError,
    claim_availability,
    parse_commercial_intelligence,
    render_commercial_intelligence,
    resolve_context,
    unlock_requirements,
)

REPO_ROOT = Path(__file__).parents[1]
MODULE_PATH = REPO_ROOT / "src" / "ai_autocut" / "commercial_intelligence.py"
SCHEMA_PATH = (
    REPO_ROOT
    / "schemas"
    / "commercial_intelligence"
    / "commercial_intelligence.v1.schema.json"
)
EXAMPLE_PATH = (
    REPO_ROOT / "examples" / "strategy" / "indonesia-faucet-filter-candidates.json"
)
STRATEGY_EXAMPLE_PATH = (
    REPO_ROOT / "examples" / "strategy" / "indonesia-faucet-filter-abc.json"
)

ARTIFACT = "strategy/commercial_intelligence.json"
STRATEGY_ARTIFACT = "strategy/commercial_strategy.json"

_FACTS_REF = "brief/product_facts.json"
_EVIDENCE_REF = "evidence/visual-evidence-boundary.json"
_NOTE_REF = "evidence/market-note.json"
_FACTS_SHA = "a" * 64
_EVIDENCE_SHA = "b" * 64
_NOTE_SHA = "c" * 64

#: Assembled from fragments: the repository hygiene test scans every text file including
#: this one, and a literal personal path would trip its own scanner.
_ABSOLUTE_PROBE = "/" + "Users" + "/" + "someone" + "/evidence.json"
_VOLUME_ROOT = "/" + "Volumes" + "/"
_USER_ROOT = "/" + "Users" + "/"

#: Field names that would express a ranking or a fabricated precision. None of them exists.
_FORBIDDEN_FIELD_NAMES = (
    "score",
    "rank",
    "ranking",
    "confidence",
    "expected_performance",
    "winner",
    "best",
    "probability",
    "ctr",
    "cvr",
)


def _base_document() -> dict:
    """A minimal valid candidate set, deep-copied so a test can mutate it safely."""

    return json.loads(json.dumps({
        "schema_version": "commercial_intelligence.v1",
        "candidate_set_id": "candidate-set-under-test",
        "context": {
            "product": {"name": "Faucet Filter"},
            "market": "INDONESIA",
            "platform": "TIKTOK",
            "platform_source": "DECLARED",
            "objective": "DIRECT_CONVERSION",
            "objective_source": "DECLARED",
        },
        "product_facts": {
            "ref": _FACTS_REF,
            "sha256": _FACTS_SHA,
            "allowed_fact_refs": [
                "FACT-INSTALLATION",
                "FACT-DIRECTION-ADJUSTABLE",
                "FACT-TRANSPARENT-STRUCTURE",
            ],
        },
        "visual_evidence_boundary": {
            "ref": _EVIDENCE_REF,
            "sha256": _EVIDENCE_SHA,
            "items": [
                {"evidence_id": "EV-INSTALLATION",
                 "statement": "the filter is fitted to a tap by hand",
                 "presence": "PRESENT"},
                {"evidence_id": "EV-STRUCTURE-VISIBLE",
                 "statement": "the transparent housing is visible",
                 "presence": "PRESENT"},
                {"evidence_id": "EV-DIRECTION-CHANGE",
                 "statement": "no clip shows the water behaviour changing",
                 "presence": "ABSENT"},
            ],
        },
        "claim_boundary": {
            "allowed": [
                {"claim_id": "CLAIM-SIMPLE-TO-INSTALL",
                 "statement": "the filter fits to the tap by hand",
                 "product_fact_ref": "FACT-INSTALLATION",
                 "evidence_ref": "EV-INSTALLATION"},
                {"claim_id": "CLAIM-STRUCTURE-IS-VISIBLE",
                 "statement": "the transparent housing shows the filter body",
                 "product_fact_ref": "FACT-TRANSPARENT-STRUCTURE",
                 "evidence_ref": "EV-STRUCTURE-VISIBLE"},
            ],
            "conditional": [
                {"claim_id": "CLAIM-DIRECTION-ADJUSTABLE",
                 "statement": "the outlet can be turned",
                 "product_fact_ref": "FACT-DIRECTION-ADJUSTABLE",
                 "requires_evidence_ref": "EV-DIRECTION-CHANGE",
                 "condition": "may be described as adjustable, never as a demonstrated change"},
            ],
            "forbidden": [
                {"claim_id": "CLAIM-REMOVES-VISIBLE-DIRT",
                 "statement": "the filter removes visible dirt",
                 "reason": "no clip shows dirt or dirt being removed"},
            ],
        },
        "consumer_hypotheses": [
            {"hypothesis_id": "H1-INSTALLATION-FRICTION",
             "statement": "the buyer may assume a filter needs a plumber",
             "support": "INFERRED",
             "basis_ref": None},
            {"hypothesis_id": "H2-COMPREHENSION-COST",
             "statement": "the buyer may want to understand the product quickly",
             "support": "DIRECT",
             "basis_ref": {"ref": _NOTE_REF, "sha256": _NOTE_SHA}},
        ],
        "candidates": [
            {"candidate_id": "A", "persuasion_job": "REDUCE_COMPREHENSION_COST",
             "hypothesis_refs": ["H1-INSTALLATION-FRICTION"],
             "product_fact_refs": ["FACT-INSTALLATION"],
             "evidence_refs": ["EV-INSTALLATION"],
             "claims_used": ["CLAIM-SIMPLE-TO-INSTALL"],
             "hook_strategy": "open on the fitting action",
             "copy_direction": ["explain only what is visible"],
             "cta_direction": "go to the product page",
             "rationale": "the fitting is filmed and the claim rests on evidence marked PRESENT",
             "limitations": ["explains a product rather than a benefit"]},
            {"candidate_id": "B", "persuasion_job": "ESTABLISH_DAILY_RELEVANCE",
             "hypothesis_refs": ["H2-COMPREHENSION-COST"],
             "product_fact_refs": ["FACT-INSTALLATION"],
             "evidence_refs": ["EV-INSTALLATION"],
             "claims_used": ["CLAIM-SIMPLE-TO-INSTALL"],
             "hook_strategy": "open on the everyday kitchen",
             "copy_direction": ["lead with the daily situation"],
             "cta_direction": "check the product page",
             "rationale": "the daily context is filmed with the product fitted",
             "limitations": []},
            {"candidate_id": "C", "persuasion_job": "DEMONSTRATE_PRODUCT_IN_ACTION",
             "hypothesis_refs": ["H1-INSTALLATION-FRICTION"],
             "product_fact_refs": ["FACT-INSTALLATION"],
             "evidence_refs": ["EV-INSTALLATION"],
             "claims_used": ["CLAIM-SIMPLE-TO-INSTALL"],
             "hook_strategy": "open on the strongest visible action in the pool",
             "copy_direction": ["show the action before naming it"],
             "cta_direction": "see the product page",
             "rationale": "the demonstration leans on filmed action, not on a result the material lacks",
             "limitations": ["the adjustable outlet is visible but its effect on the water is not"]},
        ],
        "blocked_opportunities": [
            {"opportunity_id": "DIRECTION-CHANGE",
             "statement": "showing the water direction changing would give a visible payoff",
             "persuasion_job": "DEMONSTRATE_ADJUSTABILITY",
             "claim_ref": "CLAIM-DIRECTION-ADJUSTABLE",
             "blocked_by": "CONDITIONAL_EVIDENCE_ABSENT",
             "missing": ["EV-DIRECTION-CHANGE", "a clip of the water behaviour changing"],
             "next_action": "film the outlet being operated with the water visible"},
            {"opportunity_id": "RESULT-DEMONSTRATION",
             "statement": "showing a filtration result would carry the strongest argument",
             "persuasion_job": "DEMONSTRATE_RESULT",
             "claim_ref": "CLAIM-REMOVES-VISIBLE-DIRT",
             "blocked_by": "CLAIM_FORBIDDEN",
             "missing": ["a clip showing dirt being removed"],
             "next_action": "acquire and verify the evidence before reconsidering"},
        ],
        "provenance": {
            "authored_by": {"actor": "CODEX_SUPERVISOR",
                            "producer_id": "commercial-intelligence-author"},
            "based_on": [
                {"ref": _FACTS_REF, "sha256": _FACTS_SHA},
                {"ref": _EVIDENCE_REF, "sha256": _EVIDENCE_SHA},
                {"ref": _NOTE_REF, "sha256": _NOTE_SHA},
            ],
        },
    }))


class ValidCandidateSetTests(unittest.TestCase):
    def test_a_valid_candidate_set_parses(self) -> None:
        document = parse_commercial_intelligence(_base_document())
        self.assertEqual(document.candidate_set_id, "candidate-set-under-test")
        self.assertEqual(
            [item.candidate_id for item in document.candidates], ["A", "B", "C"]
        )
        self.assertEqual(len(document.blocked_opportunities), 2)
        self.assertEqual(len(document.consumer_hypotheses), 2)

    def test_the_contract_states_its_own_status(self) -> None:
        self.assertEqual(IMPLEMENTATION, "CONTRACT_ONLY")
        self.assertEqual(WIRING_STATUS, "NOT_WIRED")
        self.assertEqual(commercial_intelligence.CANONICAL_REF, ARTIFACT)
        self.assertEqual(
            commercial_intelligence.SCHEMA_VERSION, "commercial_intelligence.v1"
        )

    def test_lookups_resolve_declared_ids(self) -> None:
        document = parse_commercial_intelligence(_base_document())
        self.assertEqual(document.candidate("C").persuasion_job,
                         "DEMONSTRATE_PRODUCT_IN_ACTION")
        self.assertEqual(document.hypothesis("H2-COMPREHENSION-COST").support, "DIRECT")
        with self.assertRaises(CommercialIntelligenceContractError):
            document.candidate("Z")
        with self.assertRaises(CommercialIntelligenceContractError):
            document.hypothesis("H9")


class RequiredFieldTests(unittest.TestCase):
    def test_a_missing_required_field_fails(self) -> None:
        for key in (
            "schema_version", "candidate_set_id", "context", "product_facts",
            "visual_evidence_boundary", "claim_boundary", "consumer_hypotheses",
            "candidates", "blocked_opportunities", "provenance",
        ):
            with self.subTest(key=key):
                document = _base_document()
                del document[key]
                with self.assertRaises(CommercialIntelligenceContractError) as caught:
                    parse_commercial_intelligence(document)
                self.assertIn("missing required key", str(caught.exception))

    def test_a_missing_candidate_field_fails(self) -> None:
        for key in (
            "candidate_id", "persuasion_job", "hypothesis_refs", "product_fact_refs",
            "evidence_refs", "claims_used", "hook_strategy", "copy_direction",
            "cta_direction", "rationale", "limitations",
        ):
            with self.subTest(key=key):
                document = _base_document()
                del document["candidates"][0][key]
                with self.assertRaises(CommercialIntelligenceContractError) as caught:
                    parse_commercial_intelligence(document)
                self.assertIn("missing required key", str(caught.exception))

    def test_an_unknown_key_fails(self) -> None:
        document = _base_document()
        document["candidates"][0]["notes"] = "extra"
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("unsupported key", str(caught.exception))

    def test_a_wrong_schema_version_fails(self) -> None:
        document = _base_document()
        document["schema_version"] = "commercial_intelligence.v0"
        with self.assertRaises(CommercialIntelligenceContractError):
            parse_commercial_intelligence(document)

    def test_empty_hypothesis_or_candidate_lists_fail(self) -> None:
        for key in ("consumer_hypotheses", "candidates"):
            with self.subTest(key=key):
                document = _base_document()
                document[key] = []
                with self.assertRaises(CommercialIntelligenceContractError):
                    parse_commercial_intelligence(document)

    def test_an_empty_required_reference_list_fails(self) -> None:
        for key in ("hypothesis_refs", "product_fact_refs", "evidence_refs", "claims_used"):
            with self.subTest(key=key):
                document = _base_document()
                document["candidates"][0][key] = []
                with self.assertRaises(CommercialIntelligenceContractError):
                    parse_commercial_intelligence(document)

    def test_empty_limitations_are_allowed(self) -> None:
        document = parse_commercial_intelligence(_base_document())
        self.assertEqual(document.candidate("B").limitations, ())

    def test_the_contract_carries_no_final_copy(self) -> None:
        for key in ("final_copy", "vo_lines", "subtitles", "cta_text", "script"):
            with self.subTest(key=key):
                document = _base_document()
                document["candidates"][0][key] = "text"
                with self.assertRaises(CommercialIntelligenceContractError):
                    parse_commercial_intelligence(document)

    def test_a_multi_line_rationale_is_refused(self) -> None:
        """A decision basis is one line, not a deliberation transcript."""

        for key in ("rationale", "hook_strategy", "cta_direction"):
            with self.subTest(key=key):
                document = _base_document()
                document["candidates"][0][key] = "first line\nsecond line"
                with self.assertRaises(CommercialIntelligenceContractError) as caught:
                    parse_commercial_intelligence(document)
                self.assertIn("single line", str(caught.exception))

    def test_a_multi_line_statement_is_refused(self) -> None:
        document = _base_document()
        document["consumer_hypotheses"][0]["statement"] = "one\ntwo"
        with self.assertRaises(CommercialIntelligenceContractError):
            parse_commercial_intelligence(document)


class CandidateIdentityTests(unittest.TestCase):
    def test_a_duplicate_candidate_id_fails(self) -> None:
        document = _base_document()
        document["candidates"][1]["candidate_id"] = "A"
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("must not repeat", str(caught.exception))

    def test_a_malformed_candidate_id_fails(self) -> None:
        for bad in ("", " A", "A B", "-A", 7):
            with self.subTest(value=bad):
                document = _base_document()
                document["candidates"][0]["candidate_id"] = bad
                with self.assertRaises(CommercialIntelligenceContractError):
                    parse_commercial_intelligence(document)

    def test_a_duplicate_hypothesis_or_opportunity_id_fails(self) -> None:
        duplicate_hypothesis = _base_document()
        duplicate_hypothesis["consumer_hypotheses"][1]["hypothesis_id"] = (
            "H1-INSTALLATION-FRICTION"
        )
        with self.assertRaises(CommercialIntelligenceContractError):
            parse_commercial_intelligence(duplicate_hypothesis)
        duplicate_opportunity = _base_document()
        duplicate_opportunity["blocked_opportunities"][1]["opportunity_id"] = (
            "DIRECTION-CHANGE"
        )
        with self.assertRaises(CommercialIntelligenceContractError):
            parse_commercial_intelligence(duplicate_opportunity)

    def test_candidates_render_ordered_by_id(self) -> None:
        """Ordering by id is deterministic, and per hook_decision.json it is not a ranking."""

        document = _base_document()
        document["candidates"] = list(reversed(document["candidates"]))
        parsed = parse_commercial_intelligence(document)
        self.assertEqual([item.candidate_id for item in parsed.candidates], ["A", "B", "C"])

    def test_duplicate_references_within_a_candidate_fail(self) -> None:
        document = _base_document()
        document["candidates"][0]["evidence_refs"] = ["EV-INSTALLATION", "EV-INSTALLATION"]
        with self.assertRaises(CommercialIntelligenceContractError):
            parse_commercial_intelligence(document)


class HypothesisTests(unittest.TestCase):
    def test_support_is_required_and_closed(self) -> None:
        document = _base_document()
        del document["consumer_hypotheses"][0]["support"]
        with self.assertRaises(CommercialIntelligenceContractError):
            parse_commercial_intelligence(document)
        unknown = _base_document()
        unknown["consumer_hypotheses"][0]["support"] = "PROBABLY"
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(unknown)
        self.assertIn("support", str(caught.exception))

    def test_the_support_vocabulary_is_the_existing_one(self) -> None:
        """One vocabulary for how directly something is backed, not a second taxonomy."""

        from src.ai_autocut.candidate_evidence import ClaimSupport

        self.assertEqual(
            HYPOTHESIS_SUPPORT, tuple(member.value for member in ClaimSupport)
        )

    def test_a_hypothesis_cannot_masquerade_as_verified(self) -> None:
        """AI inference must not be presented as verified market knowledge."""

        # There is no VERIFIED level to claim: the strongest level is citable only.
        for label in ("VERIFIED", "PROVEN", "RESEARCHED", "SUPPORTED"):
            with self.subTest(label=label):
                document = _base_document()
                document["consumer_hypotheses"][0]["support"] = label
                with self.assertRaises(CommercialIntelligenceContractError):
                    parse_commercial_intelligence(document)

    def test_direct_support_requires_a_citation(self) -> None:
        document = _base_document()
        document["consumer_hypotheses"][1]["basis_ref"] = None
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("must cite the basis", str(caught.exception))

    def test_a_weaker_level_must_not_claim_a_citation(self) -> None:
        for support in ("CONTEXTUAL", "INFERRED"):
            with self.subTest(support=support):
                document = _base_document()
                document["consumer_hypotheses"][0]["support"] = support
                document["consumer_hypotheses"][0]["basis_ref"] = {
                    "ref": _NOTE_REF, "sha256": _NOTE_SHA
                }
                with self.assertRaises(CommercialIntelligenceContractError) as caught:
                    parse_commercial_intelligence(document)
                self.assertIn("must not name a basis reference", str(caught.exception))

    def test_is_verified_is_true_only_with_a_bound_citation(self) -> None:
        document = parse_commercial_intelligence(_base_document())
        self.assertTrue(document.hypothesis("H2-COMPREHENSION-COST").is_verified)
        self.assertFalse(document.hypothesis("H1-INSTALLATION-FRICTION").is_verified)

    def test_a_malformed_basis_reference_fails(self) -> None:
        for bad in ({"ref": _ABSOLUTE_PROBE, "sha256": _NOTE_SHA},
                    {"ref": _NOTE_REF, "sha256": "nope"},
                    {"ref": _NOTE_REF}):
            with self.subTest(value=bad):
                document = _base_document()
                document["consumer_hypotheses"][1]["basis_ref"] = bad
                with self.assertRaises(CommercialIntelligenceContractError):
                    parse_commercial_intelligence(document)

    def test_a_hypothesis_cannot_be_used_as_a_claim(self) -> None:
        """Insight and claim stay separate layers: the ids do not cross over."""

        document = _base_document()
        document["candidates"][0]["claims_used"] = ["H1-INSTALLATION-FRICTION"]
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("does not declare", str(caught.exception))


class FactAndEvidenceBindingTests(unittest.TestCase):
    def test_a_candidate_may_only_cite_known_product_facts(self) -> None:
        document = _base_document()
        document["candidates"][0]["product_fact_refs"] = ["FACT-INVENTED"]
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("does not permit", str(caught.exception))

    def test_a_candidate_may_only_cite_known_evidence(self) -> None:
        document = _base_document()
        document["candidates"][0]["evidence_refs"] = ["EV-INVENTED"]
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("does not declare", str(caught.exception))

    def test_a_candidate_may_not_lean_on_absent_evidence(self) -> None:
        """A product fact the footage does not show cannot become a viable candidate."""

        document = _base_document()
        document["candidates"][0]["evidence_refs"] = ["EV-DIRECTION-CHANGE"]
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("ABSENT", str(caught.exception))

    def test_a_candidate_must_cite_the_fact_its_claim_rests_on(self) -> None:
        document = _base_document()
        document["candidates"][0]["product_fact_refs"] = ["FACT-DIRECTION-ADJUSTABLE"]
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("that the claim rests on", str(caught.exception))

    def test_a_candidate_must_cite_the_evidence_its_claim_rests_on(self) -> None:
        document = _base_document()
        document["candidates"][0]["claims_used"] = [
            "CLAIM-SIMPLE-TO-INSTALL", "CLAIM-STRUCTURE-IS-VISIBLE"
        ]
        document["candidates"][0]["product_fact_refs"] = [
            "FACT-INSTALLATION", "FACT-TRANSPARENT-STRUCTURE"
        ]
        document["candidates"][0]["evidence_refs"] = ["EV-INSTALLATION"]
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("EV-STRUCTURE-VISIBLE", str(caught.exception))

    def test_an_allowed_claim_without_evidence_is_accepted(self) -> None:
        document = _base_document()
        document["claim_boundary"]["allowed"][0]["evidence_ref"] = None
        parsed = parse_commercial_intelligence(document)
        self.assertIsNone(parsed.claim_boundary.allowed[0].evidence_ref)

    def test_the_boundary_blocks_reuse_the_v1_parsers(self) -> None:
        """One implementation of facts/evidence/claims, imported rather than rewritten."""

        from src.ai_autocut import commercial_strategy

        document = _base_document()
        self.assertEqual(
            commercial_strategy.parse_product_facts(document["product_facts"]),
            parse_commercial_intelligence(document).product_facts,
        )
        self.assertEqual(
            commercial_strategy.parse_evidence_boundary(
                document["visual_evidence_boundary"]
            ),
            parse_commercial_intelligence(document).visual_evidence_boundary,
        )
        self.assertEqual(
            commercial_strategy.parse_claim_boundary(document["claim_boundary"]),
            parse_commercial_intelligence(document).claim_boundary,
        )

    def test_a_malformed_boundary_block_is_refused(self) -> None:
        for key in ("product_facts", "visual_evidence_boundary", "claim_boundary"):
            with self.subTest(key=key):
                document = _base_document()
                document[key]["extra"] = 1
                with self.assertRaises(CommercialIntelligenceContractError):
                    parse_commercial_intelligence(document)


class ClaimBoundaryTests(unittest.TestCase):
    def test_a_forbidden_claim_cannot_enter_a_viable_candidate(self) -> None:
        document = _base_document()
        document["candidates"][0]["claims_used"] = ["CLAIM-REMOVES-VISIBLE-DIRT"]
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("forbidden claim", str(caught.exception))

    def test_a_conditional_claim_cannot_be_treated_as_fully_evidenced(self) -> None:
        document = _base_document()
        document["candidates"][0]["claims_used"] = ["CLAIM-DIRECTION-ADJUSTABLE"]
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("as though its condition held", str(caught.exception))

    def test_an_undeclared_claim_cannot_be_used(self) -> None:
        document = _base_document()
        document["candidates"][0]["claims_used"] = ["CLAIM-NEVER-DECLARED"]
        with self.assertRaises(CommercialIntelligenceContractError):
            parse_commercial_intelligence(document)

    def test_a_conditional_claim_whose_evidence_exists_is_not_usable_by_default(self) -> None:
        """The module never promotes a claim on the boundary owner's behalf."""

        document = _base_document()
        for item in document["visual_evidence_boundary"]["items"]:
            if item["evidence_id"] == "EV-DIRECTION-CHANGE":
                item["presence"] = "PRESENT"
        document["candidates"][0]["claims_used"] = ["CLAIM-DIRECTION-ADJUSTABLE"]
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("has not promoted", str(caught.exception))

    def test_claim_availability_is_derived_from_the_boundaries(self) -> None:
        document = parse_commercial_intelligence(_base_document())
        allowed = claim_availability(
            "CLAIM-SIMPLE-TO-INSTALL",
            document.claim_boundary,
            document.visual_evidence_boundary,
        )
        self.assertTrue(allowed.available)
        self.assertIsNone(allowed.blocked_by)

        conditional = claim_availability(
            "CLAIM-DIRECTION-ADJUSTABLE",
            document.claim_boundary,
            document.visual_evidence_boundary,
        )
        self.assertFalse(conditional.available)
        self.assertEqual(conditional.blocked_by, "CONDITIONAL_EVIDENCE_ABSENT")
        self.assertEqual(conditional.missing, ("EV-DIRECTION-CHANGE",))

        forbidden = claim_availability(
            "CLAIM-REMOVES-VISIBLE-DIRT",
            document.claim_boundary,
            document.visual_evidence_boundary,
        )
        self.assertEqual(forbidden.blocked_by, "CLAIM_FORBIDDEN")

        undeclared = claim_availability(
            "CLAIM-NOWHERE", document.claim_boundary, document.visual_evidence_boundary
        )
        self.assertEqual(undeclared.state, None)
        self.assertEqual(undeclared.blocked_by, "CLAIM_NOT_DECLARED")

    def test_a_result_first_purification_candidate_is_rejected(self) -> None:
        """The Indonesia boundary case: result-first may not become a filtration claim."""

        document = _base_document()
        document["candidates"][0]["persuasion_job"] = "DEMONSTRATE_RESULT"
        document["candidates"][0]["claims_used"] = ["CLAIM-REMOVES-VISIBLE-DIRT"]
        document["candidates"][0]["evidence_refs"] = ["EV-INSTALLATION"]
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("never be used", str(caught.exception))


class BlockedOpportunityTests(unittest.TestCase):
    def test_a_blocked_opportunity_must_match_the_derived_reason(self) -> None:
        document = _base_document()
        document["blocked_opportunities"][0]["blocked_by"] = "CLAIM_FORBIDDEN"
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("the boundaries give", str(caught.exception))

    def test_an_allowed_claim_cannot_be_presented_as_blocked(self) -> None:
        document = _base_document()
        document["blocked_opportunities"][0]["claim_ref"] = "CLAIM-SIMPLE-TO-INSTALL"
        document["blocked_opportunities"][0]["blocked_by"] = "CLAIM_FORBIDDEN"
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("ALLOWED", str(caught.exception))

    def test_the_derived_missing_item_must_be_declared(self) -> None:
        document = _base_document()
        document["blocked_opportunities"][0]["missing"] = ["something else entirely"]
        with self.assertRaises(CommercialIntelligenceContractError) as caught:
            parse_commercial_intelligence(document)
        self.assertIn("EV-DIRECTION-CHANGE", str(caught.exception))

    def test_a_blocked_opportunity_must_state_what_is_missing(self) -> None:
        document = _base_document()
        document["blocked_opportunities"][0]["missing"] = []
        with self.assertRaises(CommercialIntelligenceContractError):
            parse_commercial_intelligence(document)

    def test_an_unknown_blocking_code_fails(self) -> None:
        document = _base_document()
        document["blocked_opportunities"][0]["blocked_by"] = "NOT_SURE"
        with self.assertRaises(CommercialIntelligenceContractError):
            parse_commercial_intelligence(document)
        self.assertIn("CONDITIONAL_EVIDENCE_ABSENT", BLOCKING_CODES)

    def test_a_blocked_opportunity_never_appears_as_a_viable_candidate(self) -> None:
        """The two rules compose: candidate claims are ALLOWED, blocked claims are not."""

        document = parse_commercial_intelligence(_base_document())
        used = {claim for item in document.candidates for claim in item.claims_used}
        blocked = {item.claim_ref for item in document.blocked_opportunities}
        self.assertEqual(used & blocked, set())

    def test_a_blocked_opportunity_grants_nothing(self) -> None:
        document = parse_commercial_intelligence(_base_document())
        requirements = unlock_requirements(document)
        self.assertEqual(len(requirements), 2)
        for entry in requirements:
            with self.subTest(opportunity=entry["opportunity_id"]):
                self.assertFalse(entry["grants_claim_use"])
                self.assertIsNotNone(entry["blocked_by"])
                self.assertTrue(entry["next_action"])

    def test_unlock_requirements_report_the_derived_missing_evidence(self) -> None:
        document = parse_commercial_intelligence(_base_document())
        entry = next(
            item
            for item in unlock_requirements(document)
            if item["opportunity_id"] == "DIRECTION-CHANGE"
        )
        self.assertEqual(entry["derived_missing"], ["EV-DIRECTION-CHANGE"])
        self.assertEqual(entry["claim_state"], "CONDITIONAL")


class NoFakeWinnerTests(unittest.TestCase):
    def test_a_score_or_winner_field_is_refused(self) -> None:
        for key in _FORBIDDEN_FIELD_NAMES:
            with self.subTest(key=key):
                document = _base_document()
                document["candidates"][0][key] = 92
                with self.assertRaises(CommercialIntelligenceContractError) as caught:
                    parse_commercial_intelligence(document)
                self.assertIn("unsupported key", str(caught.exception))

    def test_a_document_level_ranking_is_refused(self) -> None:
        for key in ("ranking", "winner", "selected_candidate_id", "recommended"):
            with self.subTest(key=key):
                document = _base_document()
                document[key] = "A"
                with self.assertRaises(CommercialIntelligenceContractError):
                    parse_commercial_intelligence(document)

    def test_no_parsed_value_is_numeric(self) -> None:
        """There is no field a fabricated precision could be written into."""

        document = parse_commercial_intelligence(_base_document())

        def walk(value: object, path: str) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    walk(item, f"{path}.{key}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, f"{path}[{index}]")
            else:
                self.assertNotIsInstance(
                    value, (int, float), f"{path} is numeric; this contract has no scores"
                )

        walk(document.as_dict(), "document")

    def test_no_field_name_suggests_a_ranking(self) -> None:
        document = parse_commercial_intelligence(_base_document())

        def walk(value: object) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertNotIn(key, _FORBIDDEN_FIELD_NAMES, key)
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(document.as_dict())

    def test_the_module_has_no_generation_or_ranking_entry_point(self) -> None:
        """Python here validates and derives; it does not invent candidates or a winner."""

        for name in commercial_intelligence.__all__:
            lowered = name.lower()
            for fragment in ("best", "rank", "score", "winner", "generate", "propose",
                             "invent", "plan_candidates"):
                with self.subTest(name=name, fragment=fragment):
                    self.assertNotIn(fragment, lowered)


class ContextDefaultTests(unittest.TestCase):
    def test_objective_defaults_and_records_that_it_did(self) -> None:
        context = resolve_context("Faucet Filter", "INDONESIA")
        self.assertEqual(context.objective, DEFAULT_OBJECTIVE)
        self.assertEqual(context.objective_source, "DEFAULTED")

    def test_platform_is_not_invented(self) -> None:
        context = resolve_context("Faucet Filter", "INDONESIA")
        self.assertEqual(context.platform, UNSPECIFIED_PLATFORM)
        self.assertEqual(context.platform_source, "UNSPECIFIED")

    def test_both_values_may_be_declared(self) -> None:
        context = resolve_context(
            "Faucet Filter", "INDONESIA", platform="TIKTOK", objective="AWARENESS"
        )
        self.assertEqual(context.platform_source, "DECLARED")
        self.assertEqual(context.objective, "AWARENESS")
        self.assertEqual(context.objective_source, "DECLARED")

    def test_only_the_product_and_market_are_required(self) -> None:
        with self.assertRaises(CommercialIntelligenceContractError):
            resolve_context("", "INDONESIA")
        with self.assertRaises(CommercialIntelligenceContractError):
            resolve_context("Faucet Filter", "")

    def test_a_defaulted_objective_may_not_be_something_else(self) -> None:
        document = _base_document()
        document["context"]["objective"] = "AWARENESS"
        document["context"]["objective_source"] = "DEFAULTED"
        with self.assertRaises(CommercialIntelligenceContractError):
            parse_commercial_intelligence(document)

    def test_an_unspecified_platform_must_say_so(self) -> None:
        document = _base_document()
        document["context"]["platform"] = UNSPECIFIED_PLATFORM
        document["context"]["platform_source"] = "DECLARED"
        with self.assertRaises(CommercialIntelligenceContractError):
            parse_commercial_intelligence(document)

    def test_an_unknown_context_source_fails(self) -> None:
        document = _base_document()
        document["context"]["platform_source"] = "GUESSED"
        with self.assertRaises(CommercialIntelligenceContractError):
            parse_commercial_intelligence(document)


class SerializationTests(unittest.TestCase):
    def test_serialization_is_deterministic(self) -> None:
        first = render_commercial_intelligence(
            parse_commercial_intelligence(_base_document())
        )
        second = render_commercial_intelligence(
            parse_commercial_intelligence(_base_document())
        )
        self.assertEqual(first, second)
        self.assertTrue(first.endswith("}\n"))

    def test_key_order_does_not_change_the_rendering(self) -> None:
        shuffled = dict(reversed(list(_base_document().items())))
        self.assertEqual(
            render_commercial_intelligence(parse_commercial_intelligence(shuffled)),
            render_commercial_intelligence(
                parse_commercial_intelligence(_base_document())
            ),
        )

    def test_a_render_round_trips(self) -> None:
        document = parse_commercial_intelligence(_base_document())
        re_parsed = parse_commercial_intelligence(
            json.loads(render_commercial_intelligence(document))
        )
        self.assertEqual(document.as_dict(), re_parsed.as_dict())


class SchemaFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_the_schema_is_closed(self) -> None:
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(
            self.schema["properties"]["schema_version"]["const"],
            commercial_intelligence.SCHEMA_VERSION,
        )
        self.assertFalse(
            self.schema["properties"]["candidates"]["items"]["additionalProperties"]
        )

    def test_the_schema_lists_the_keys_the_parser_requires(self) -> None:
        self.assertEqual(
            set(self.schema["required"]),
            {
                "schema_version", "candidate_set_id", "context", "product_facts",
                "visual_evidence_boundary", "claim_boundary", "consumer_hypotheses",
                "candidates", "blocked_opportunities", "provenance",
            },
        )
        self.assertEqual(
            set(self.schema["properties"]["candidates"]["items"]["required"]),
            {
                "candidate_id", "persuasion_job", "hypothesis_refs", "product_fact_refs",
                "evidence_refs", "claims_used", "hook_strategy", "copy_direction",
                "cta_direction", "rationale", "limitations",
            },
        )

    def test_the_schema_records_the_support_and_blocking_vocabularies(self) -> None:
        support = (
            self.schema["properties"]["consumer_hypotheses"]["items"]["properties"]
            ["support"]["enum"]
        )
        self.assertEqual(tuple(support), HYPOTHESIS_SUPPORT)
        blocked = (
            self.schema["properties"]["blocked_opportunities"]["items"]["properties"]
            ["blocked_by"]["enum"]
        )
        self.assertEqual(tuple(blocked), BLOCKING_CODES)

    def test_the_schema_offers_no_ranking_field(self) -> None:
        candidate_keys = set(
            self.schema["properties"]["candidates"]["items"]["properties"]
        )
        document_keys = set(self.schema["properties"])
        for name in _FORBIDDEN_FIELD_NAMES:
            with self.subTest(name=name):
                self.assertNotIn(name, candidate_keys)
                self.assertNotIn(name, document_keys)

    def test_the_schema_status_matches_the_implementation(self) -> None:
        status = self.schema["x-status"]
        self.assertEqual(status["implementation"], IMPLEMENTATION)
        self.assertEqual(status["wiring_status"], WIRING_STATUS)
        self.assertIsNone(status["writer"])
        self.assertIsNone(status["reader"])
        self.assertFalse(status["producer_registered"])
        self.assertFalse(status["required_by_a_stage"])
        self.assertTrue(status["no_numeric_fields"])
        self.assertIn("commercial_strategy.v1", status["upstream_of"])
        boundary = status["boundary"]
        self.assertIn("shape and enum validation", boundary["system_contract_and_validation"])
        self.assertIn("the rationale", boundary["agent_intelligence_and_authoring"])


class ContractOnlyTests(unittest.TestCase):
    """CONTRACT_ONLY / NOT_WIRED: nothing in production writes or reads this artifact."""

    def test_no_producer_is_registered(self) -> None:
        with self.assertRaises(producer_registry.ProducerRegistryError) as caught:
            producer_registry.producer_for(ARTIFACT)
        self.assertIn("NO PRODUCER", str(caught.exception))

    def test_no_mode_owns_the_artifact(self) -> None:
        self.assertIsNone(producer_registry.mode_of(ARTIFACT))

    def test_no_third_mode_scope_or_registry_was_added(self) -> None:
        for name in (
            "DECLARED_PRODUCERS",
            "DECLARED_ARTIFACTS",
            "DECLARED_PRODUCER_BY_ARTIFACT",
            "declared_producer_for",
            "declared_gate_for",
        ):
            with self.subTest(name=name):
                self.assertFalse(hasattr(producer_registry, name))
        self.assertEqual(producer_registry.MODES, ("LEGACY", "VNEXT_SHADOW"))

    def test_the_artifact_is_not_a_production_or_shadow_artifact(self) -> None:
        self.assertNotIn(ARTIFACT, producer_registry.REQUIRED_INPUT_ARTIFACTS)
        self.assertNotIn(ARTIFACT, producer_registry.AUTO_ARTIFACTS)
        self.assertNotIn(ARTIFACT, producer_registry.VNEXT_SHADOW_ARTIFACTS)

    def test_no_production_stage_declares_the_artifact(self) -> None:
        declared = {artifact for stage in fast_path.STAGES for artifact in stage.inputs}
        self.assertNotIn(ARTIFACT, declared)
        self.assertEqual(len(fast_path.SEMANTIC_STAGES), 8)

    def test_the_contract_does_not_register_itself(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("producer_registry", source)

    def test_the_contract_document_records_the_contract_only_status(self) -> None:
        text = (
            REPO_ROOT / "docs" / "contracts" / "commercial-intelligence-v1.md"
        ).read_text(encoding="utf-8")
        self.assertIn("CONTRACT_ONLY", text)
        self.assertIn("NOT_WIRED", text)
        self.assertIn("No producer is registered", text)
        self.assertIn("hand-authored", text)


class ReuseTests(unittest.TestCase):
    """The demonstration shares one boundary with Commercial Strategy v1, not a copy."""

    def setUp(self) -> None:
        from src.ai_autocut import commercial_strategy

        self.intelligence = parse_commercial_intelligence(
            json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        )
        self.strategy = commercial_strategy.parse_commercial_strategy(
            json.loads(STRATEGY_EXAMPLE_PATH.read_text(encoding="utf-8"))
        )

    def test_both_documents_bind_the_same_authorities(self) -> None:
        self.assertEqual(
            self.intelligence.product_facts.reference.as_dict(),
            self.strategy.product_facts.reference.as_dict(),
        )
        self.assertEqual(
            self.intelligence.visual_evidence_boundary.reference.as_dict(),
            self.strategy.visual_evidence_boundary.reference.as_dict(),
        )

    def test_both_documents_declare_the_same_claim_ids(self) -> None:
        self.assertEqual(
            sorted(self.intelligence.claim_boundary.allowed_ids),
            sorted(self.strategy.claim_boundary.allowed_ids),
        )
        self.assertEqual(
            sorted(self.intelligence.claim_boundary.conditional_ids),
            sorted(self.strategy.claim_boundary.conditional_ids),
        )
        self.assertEqual(
            sorted(self.intelligence.claim_boundary.forbidden_ids),
            sorted(self.strategy.claim_boundary.forbidden_ids),
        )

    def test_the_candidates_correspond_to_the_strategy_variants(self) -> None:
        self.assertEqual(
            [item.candidate_id for item in self.intelligence.candidates],
            [item.variant_id for item in self.strategy.variants],
        )

    def test_the_candidates_and_the_variants_share_the_same_context(self) -> None:
        self.assertEqual(self.intelligence.context.market, self.strategy.market)
        self.assertEqual(self.intelligence.context.objective, self.strategy.objective)


class ExampleFixtureTests(unittest.TestCase):
    """The Indonesia demonstration must stay a contract demonstration."""

    def setUp(self) -> None:
        self.document = parse_commercial_intelligence(
            json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        )

    def test_the_example_parses(self) -> None:
        self.assertEqual(self.document.context.market, "INDONESIA")
        self.assertEqual(
            [item.persuasion_job for item in self.document.candidates],
            [
                "REDUCE_COMPREHENSION_COST",
                "ESTABLISH_DAILY_RELEVANCE",
                "DEMONSTRATE_PRODUCT_IN_ACTION",
            ],
        )

    def test_every_hypothesis_is_honestly_labelled(self) -> None:
        for hypothesis in self.document.consumer_hypotheses:
            with self.subTest(hypothesis=hypothesis.hypothesis_id):
                self.assertIn(hypothesis.support, ("CONTEXTUAL", "INFERRED"))
                self.assertFalse(hypothesis.is_verified)
                self.assertIsNone(hypothesis.basis_ref)

    def test_no_candidate_leans_on_the_unprovable_result(self) -> None:
        unsupported = set(
            self.document.claim_boundary.forbidden_ids
        ) | set(self.document.claim_boundary.conditional_ids)
        for candidate in self.document.candidates:
            with self.subTest(candidate=candidate.candidate_id):
                self.assertEqual(set(candidate.claims_used) & unsupported, set())

    def test_the_result_first_candidate_is_product_in_action_not_a_result(self) -> None:
        candidate = self.document.candidate("C")
        self.assertEqual(candidate.persuasion_job, "DEMONSTRATE_PRODUCT_IN_ACTION")
        self.assertIn("product-in-action demonstration", candidate.hook_strategy)
        self.assertEqual(
            self.document.visual_evidence_boundary.presence_of("EV-FILTRATION-RESULT"),
            "ABSENT",
        )

    def test_the_blocked_opportunities_cover_both_blocking_kinds(self) -> None:
        blocked = {
            item.opportunity_id: item.blocked_by
            for item in self.document.blocked_opportunities
        }
        self.assertEqual(blocked["RESULT-DEMONSTRATION"], "CLAIM_FORBIDDEN")
        self.assertEqual(blocked["DIRECTION-CHANGE"], "CONDITIONAL_EVIDENCE_ABSENT")

    def test_the_example_answers_what_would_unlock_a_stronger_strategy(self) -> None:
        requirements = {
            item["opportunity_id"]: item for item in unlock_requirements(self.document)
        }
        self.assertEqual(
            requirements["DIRECTION-CHANGE"]["derived_missing"], ["EV-DIRECTION-CHANGE"]
        )
        self.assertFalse(requirements["RESULT-DEMONSTRATION"]["grants_claim_use"])

    def test_the_example_uses_illustrative_hashes(self) -> None:
        self.assertEqual(self.document.product_facts.sha256, "1" * 64)
        self.assertEqual(self.document.visual_evidence_boundary.sha256, "2" * 64)

    def test_the_example_carries_no_media_and_no_machine_path(self) -> None:
        text = EXAMPLE_PATH.read_text(encoding="utf-8")
        self.assertNotIn(_USER_ROOT, text)
        self.assertNotIn(_VOLUME_ROOT, text)
        self.assertIsNone(re.search(r"\.(mp4|mov|wav|mp3)\b", text))


class NoProviderDependencyTests(unittest.TestCase):
    def test_the_module_makes_no_network_or_provider_call(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "socket", "ssl", "http.client", "urllib", "requests", "httpx", "openai",
            "anthropic", "api_key", "subprocess",
        ):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, source)

    def test_validation_is_pure(self) -> None:
        document = parse_commercial_intelligence(_base_document())
        self.assertFalse(hasattr(document, "job_root"))
        self.assertFalse(hasattr(document, "path"))


if __name__ == "__main__":
    unittest.main()
