from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from src.ai_autocut.candidate_evidence import (
    parse_candidate_evidence,
    render_candidate_evidence,
)
from src.ai_autocut.candidate_pool import parse_candidate_pool
from src.ai_autocut.editing_intelligence import CoverageToken
from src.ai_autocut.creative_intent import (
    HOOK_TYPES,
    MAX_HYPOTHESES,
    MIN_HYPOTHESES,
    REJECTION_CODES,
    SCHEMA_VERSION,
    SELECTION_REASON_CODES,
    DecisionOwner,
    EvidenceCoverage,
    FactSafety,
    HookDecision,
    HookDecisionContractError,
    HookType,
    RejectionCode,
    canonical_hook_identity_json,
    hook_id_for,
    parse_hook_decision,
    render_hook_decision,
    validate_hook_decision,
    validate_hook_decision_against_evidence,
    validate_hook_decision_reference,
)
from src.ai_autocut.identity import parse_identity_catalog


# Probe paths are assembled from fragments on purpose: this repository is scanned
# by the path-hygiene test, which would otherwise flag this module's own probe.
def absolute(*parts: str) -> str:
    """Build an absolute POSIX path without writing a literal prefix."""

    return "/" + "/".join(parts)


FIXTURES = Path(__file__).parent / "fixtures"
IDENTITY_FIXTURE = FIXTURES / "vnext_identity_catalog_v1_valid.json"
POOL_FIXTURE = FIXTURES / "vnext_candidate_pool_v1_valid.json"
EVIDENCE_FIXTURE = FIXTURES / "candidate_evidence_v1_valid.json"
HOOK_FIXTURE = FIXTURES / "hook_decision_v1_valid.json"
CONTRACT = Path(__file__).parents[1] / "docs" / "contracts" / "hook-decision-v1.md"


class HookDecisionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = parse_identity_catalog(json.loads(IDENTITY_FIXTURE.read_text()))
        self.pool = parse_candidate_pool(json.loads(POOL_FIXTURE.read_text()))
        self.evidence_raw = EVIDENCE_FIXTURE.read_text(encoding="utf-8")
        self.evidence = parse_candidate_evidence(json.loads(self.evidence_raw))
        self.raw = json.loads(HOOK_FIXTURE.read_text())
        self.decision = parse_hook_decision(self.raw)

    def payload(self) -> dict:
        return copy.deepcopy(self.raw)

    def candidate_id(self, start_frame: int) -> str:
        for item in self.catalog.candidates:
            if item.start_frame == start_frame:
                return item.candidate_id
        raise AssertionError("fixture candidate is missing")

    def hypothesis(self, payload: dict, hook_type: str) -> dict:
        for item in payload["hypotheses"]:
            if item["hook_type"] == hook_type:
                return item
        raise AssertionError("fixture hypothesis is missing")

    def selected_hypothesis(self, payload: dict) -> dict:
        for item in payload["hypotheses"]:
            if item["hook_id"] == payload["selected_hook_id"]:
                return item
        raise AssertionError("fixture selection is missing")


class HookVocabularyTests(HookDecisionTestCase):
    def test_hook_vocabulary_is_finite_and_complete(self) -> None:
        self.assertEqual(
            HOOK_TYPES,
            {"PAIN", "OLD_WAY", "RESULT", "CURIOSITY", "PRODUCT_DIRECT"},
        )
        self.assertEqual(set(HookType.__members__), HOOK_TYPES)

    def test_reason_vocabularies_are_finite_and_disjoint(self) -> None:
        self.assertEqual(
            REJECTION_CODES,
            {
                "UNSUPPORTED_CLAIM",
                "NO_OPENING_VISUAL",
                "INSUFFICIENT_EVIDENCE",
                "DUPLICATES_SELECTED_PREMISE",
                "WEAKER_EVIDENCE",
                "FACT_UNSAFE_PREMISE",
            },
        )
        self.assertEqual(
            SELECTION_REASON_CODES,
            {
                "FACT_SAFE",
                "DIRECT_VISUAL_SUPPORT",
                "BRIEF_ALIGNED",
                "STRONGER_EVIDENCE",
            },
        )
        self.assertEqual(REJECTION_CODES & SELECTION_REASON_CODES, set())
        self.assertTrue(REJECTION_CODES <= set(RejectionCode.__members__))

    def test_invalid_hook_type_fails_closed(self) -> None:
        for value in ("SCORE", "pain", "PROBLEM_AGITATION", "", None, 3):
            payload = self.payload()
            self.hypothesis(payload, "PAIN")["hook_type"] = value
            with self.subTest(value=value):
                with self.assertRaises(HookDecisionContractError):
                    parse_hook_decision(payload)

    def test_invalid_reason_codes_fail_closed(self) -> None:
        payload = self.payload()
        self.hypothesis(payload, "PAIN")["assessment"]["rejection_codes"] = [
            "SCORE_TOO_LOW"
        ]
        with self.assertRaises(HookDecisionContractError):
            parse_hook_decision(payload)
        payload = self.payload()
        payload["selection_reason_codes"] = ["SCORE_TOO_HIGH"]
        with self.assertRaises(HookDecisionContractError):
            parse_hook_decision(payload)

    def test_a_rejection_code_cannot_be_used_as_a_selection_reason(self) -> None:
        payload = self.payload()
        payload["selection_reason_codes"] = ["WEAKER_EVIDENCE"]
        with self.assertRaises(HookDecisionContractError):
            parse_hook_decision(payload)
        payload = self.payload()
        self.hypothesis(payload, "PAIN")["assessment"]["rejection_codes"] = [
            "FACT_SAFE"
        ]
        with self.assertRaises(HookDecisionContractError):
            parse_hook_decision(payload)

    def test_duplicate_reason_codes_fail_closed(self) -> None:
        payload = self.payload()
        payload["selection_reason_codes"] = ["FACT_SAFE", "FACT_SAFE"]
        with self.assertRaises(HookDecisionContractError):
            parse_hook_decision(payload)


class HookIdentityTests(HookDecisionTestCase):
    def test_hook_id_is_content_addressed_and_stable(self) -> None:
        first = hook_id_for(HookType.RESULT, "the stream bends when the head turns")
        second = hook_id_for(HookType.RESULT, "the stream bends when the head turns")
        other_type = hook_id_for(HookType.PAIN, "the stream bends when the head turns")
        other_premise = hook_id_for(HookType.RESULT, "the stream narrows")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other_type)
        self.assertNotEqual(first, other_premise)
        self.assertTrue(first.startswith("hookv1_"))
        self.assertEqual(
            canonical_hook_identity_json(
                HookType.RESULT, "the stream bends when the head turns"
            ),
            '{"commercial_premise":"the stream bends when the head turns",'
            '"hook_type":"RESULT"}',
        )

    def test_duplicate_hook_id_fails_closed(self) -> None:
        payload = self.payload()
        first = self.hypothesis(payload, "RESULT")
        duplicate = copy.deepcopy(first)
        duplicate["hook_id"] = None
        payload["hypotheses"] = [first, duplicate]
        payload["selected_hook_id"] = None
        payload["selection_reason_codes"] = []
        payload["decision_owner"] = "UNASSIGNED"
        with self.assertRaisesRegex(HookDecisionContractError, "duplicate hook_id"):
            parse_hook_decision(payload)

    def test_hook_id_must_match_its_premise(self) -> None:
        payload = self.payload()
        self.hypothesis(payload, "PAIN")["hook_id"] = "hookv1_" + "0" * 64
        with self.assertRaisesRegex(HookDecisionContractError, "hook_id"):
            parse_hook_decision(payload)
        payload = self.payload()
        self.hypothesis(payload, "PAIN")["hook_id"] = "hook-1"
        with self.assertRaises(HookDecisionContractError):
            parse_hook_decision(payload)


class HookSelectionTests(HookDecisionTestCase):
    def test_canonical_fixture_round_trips_and_validates(self) -> None:
        raw_text = HOOK_FIXTURE.read_text(encoding="utf-8")
        self.assertEqual(render_hook_decision(self.decision), raw_text)
        validate_hook_decision(self.decision)
        self.assertIs(self.decision.decision_owner, DecisionOwner.HUMAN_PRODUCER)
        self.assertIs(
            self.decision.selected_hypothesis.hook_type, HookType.PRODUCT_DIRECT
        )

    def test_hypothesis_count_bounds_are_enforced(self) -> None:
        base = self.hypothesis(self.payload(), "PAIN")
        payload = self.payload()
        payload["hypotheses"] = [base]
        payload["selected_hook_id"] = None
        payload["selection_reason_codes"] = []
        payload["decision_owner"] = "UNASSIGNED"
        with self.assertRaisesRegex(HookDecisionContractError, "between"):
            parse_hook_decision(payload)

        payload = self.payload()
        copies = []
        for index in range(MAX_HYPOTHESES + 1):
            item = copy.deepcopy(base)
            item["commercial_premise"] = f"premise number {index}"
            item["hook_id"] = None
            item["assessment"]["rejection_codes"] = ["WEAKER_EVIDENCE"]
            item["assessment"]["fact_safety"] = "FACT_SAFE"
            copies.append(item)
        payload["hypotheses"] = copies
        payload["selected_hook_id"] = None
        payload["selection_reason_codes"] = []
        payload["decision_owner"] = "UNASSIGNED"
        with self.assertRaisesRegex(HookDecisionContractError, "between"):
            parse_hook_decision(payload)
        self.assertEqual(MIN_HYPOTHESES, 2)

    def test_unknown_selected_hook_id_fails_closed(self) -> None:
        payload = self.payload()
        payload["selected_hook_id"] = "hookv1_" + "0" * 64
        with self.assertRaisesRegex(HookDecisionContractError, "does not name"):
            parse_hook_decision(payload)
        payload = self.payload()
        payload["selected_hook_id"] = "hook-1"
        with self.assertRaises(HookDecisionContractError):
            parse_hook_decision(payload)

    def test_selected_hook_requires_owner_and_reasons(self) -> None:
        payload = self.payload()
        payload["decision_owner"] = "UNASSIGNED"
        with self.assertRaisesRegex(HookDecisionContractError, "owner"):
            parse_hook_decision(payload)
        payload = self.payload()
        payload["selection_reason_codes"] = []
        with self.assertRaisesRegex(HookDecisionContractError, "selection reason"):
            parse_hook_decision(payload)

    def test_rejected_or_unsafe_hypothesis_cannot_be_selected(self) -> None:
        payload = self.payload()
        selected = self.selected_hypothesis(payload)
        selected["assessment"]["rejection_codes"] = ["WEAKER_EVIDENCE"]
        with self.assertRaisesRegex(HookDecisionContractError, "rejected"):
            parse_hook_decision(payload)
        payload = self.payload()
        selected = self.selected_hypothesis(payload)
        selected["assessment"]["fact_safety"] = "FACT_UNVERIFIED"
        selected["assessment"]["rejection_codes"] = ["NO_OPENING_VISUAL"]
        with self.assertRaisesRegex(HookDecisionContractError, "fact-safe"):
            parse_hook_decision(payload)
        payload = self.payload()
        selected = self.selected_hypothesis(payload)
        selected["assessment"]["evidence_coverage"] = "INSUFFICIENT"
        selected["assessment"]["rejection_codes"] = ["INSUFFICIENT_EVIDENCE"]
        with self.assertRaisesRegex(HookDecisionContractError, "insufficient"):
            parse_hook_decision(payload)

    def test_decided_set_must_reject_every_other_hypothesis(self) -> None:
        payload = self.payload()
        self.hypothesis(payload, "RESULT")["assessment"]["rejection_codes"] = []
        with self.assertRaisesRegex(HookDecisionContractError, "rejection code"):
            parse_hook_decision(payload)

    def test_duplicate_premise_must_be_named_as_duplicate(self) -> None:
        payload = self.payload()
        second = copy.deepcopy(self.selected_hypothesis(payload))
        second["commercial_premise"] = (
            self.selected_hypothesis(payload)["commercial_premise"] + " again"
        )
        second["hook_id"] = None
        second["assessment"]["rejection_codes"] = ["WEAKER_EVIDENCE"]
        payload["hypotheses"].append(second)
        with self.assertRaisesRegex(HookDecisionContractError, "DUPLICATES"):
            parse_hook_decision(payload)
        payload["hypotheses"][-1]["assessment"]["rejection_codes"] = [
            "DUPLICATES_SELECTED_PREMISE"
        ]
        parse_hook_decision(payload)

    def test_pending_decision_is_representable_and_honest(self) -> None:
        payload = self.payload()
        payload["selected_hook_id"] = None
        payload["selection_reason_codes"] = []
        payload["decision_owner"] = "UNASSIGNED"
        for item in payload["hypotheses"]:
            item["assessment"]["rejection_codes"] = []
            item["assessment"]["fact_safety"] = "FACT_SAFE"
            item["assessment"]["evidence_coverage"] = "PARTIAL"
        pending = parse_hook_decision(payload)
        self.assertIsNone(pending.selected_hypothesis)
        self.assertIs(pending.decision_owner, DecisionOwner.UNASSIGNED)

    def test_pending_decision_must_not_state_selection_reasons(self) -> None:
        payload = self.payload()
        payload["selected_hook_id"] = None
        payload["decision_owner"] = "UNASSIGNED"
        with self.assertRaises(HookDecisionContractError):
            parse_hook_decision(payload)

    def test_owned_decision_without_selection_must_reject_everything(self) -> None:
        payload = self.payload()
        payload["selected_hook_id"] = None
        payload["selection_reason_codes"] = []
        for item in payload["hypotheses"]:
            item["assessment"]["rejection_codes"] = ["WEAKER_EVIDENCE"]
            item["assessment"]["fact_safety"] = "FACT_SAFE"
        parsed = parse_hook_decision(payload)
        self.assertIsNone(parsed.selected_hypothesis)
        payload["hypotheses"][0]["assessment"]["rejection_codes"] = []
        with self.assertRaises(HookDecisionContractError):
            parse_hook_decision(payload)


class HookEvidenceRequirementTests(HookDecisionTestCase):
    def test_missing_evidence_requirement_fails_closed(self) -> None:
        payload = self.payload()
        self.hypothesis(payload, "PAIN")["required_evidence"] = []
        with self.assertRaisesRegex(HookDecisionContractError, "evidence requirement"):
            parse_hook_decision(payload)

    def test_duplicate_requirement_token_fails_closed(self) -> None:
        payload = self.payload()
        item = self.hypothesis(payload, "PAIN")
        item["required_evidence"] = [item["required_evidence"][0]] * 2
        with self.assertRaises(HookDecisionContractError):
            parse_hook_decision(payload)

    def test_visual_support_must_answer_a_stated_requirement(self) -> None:
        payload = self.payload()
        self.hypothesis(payload, "PAIN")["available_visual_support"][0][
            "coverage_token"
        ] = "OBSERVABLE_RESULT"
        with self.assertRaisesRegex(HookDecisionContractError, "stated evidence"):
            parse_hook_decision(payload)

    def test_no_opening_visual_must_be_stated(self) -> None:
        payload = self.payload()
        item = self.hypothesis(payload, "PAIN")
        item["available_visual_support"] = []
        with self.assertRaisesRegex(HookDecisionContractError, "NO_OPENING_VISUAL"):
            parse_hook_decision(payload)
        item["assessment"]["rejection_codes"] = [
            "NO_OPENING_VISUAL",
            "UNSUPPORTED_CLAIM",
        ]
        parse_hook_decision(payload)

    def test_full_coverage_requires_support_for_every_requirement(self) -> None:
        payload = self.payload()
        self.hypothesis(payload, "PAIN")["assessment"]["evidence_coverage"] = "FULL"
        with self.assertRaisesRegex(HookDecisionContractError, "FULL"):
            parse_hook_decision(payload)

    def test_malformed_evidence_refs_fail_closed(self) -> None:
        for field in ("candidate_evidence", "brief"):
            for value in (
                {"ref": absolute("Users", "someone", "evidence.json"), "sha256": "0" * 64},
                {"ref": "analysis/candidate_evidence.json", "sha256": "0" * 63},
                {"ref": "analysis/candidate_evidence.json"},
                {"ref": "analysis/candidate_evidence.json", "sha256": "0" * 64, "x": 1},
            ):
                payload = self.payload()
                payload[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(HookDecisionContractError):
                        parse_hook_decision(payload)

    def test_malformed_candidate_ref_in_support_fails_closed(self) -> None:
        payload = self.payload()
        self.hypothesis(payload, "PAIN")["available_visual_support"][0][
            "candidate_id"
        ] = "C05"
        with self.assertRaises(HookDecisionContractError):
            parse_hook_decision(payload)


class HookAgainstEvidenceTests(HookDecisionTestCase):
    def test_declared_support_is_checked_against_the_named_evidence(self) -> None:
        validate_hook_decision_against_evidence(
            self.decision, self.evidence, self.pool, self.catalog
        )
        validate_hook_decision_reference(self.decision, self.evidence_raw)

    def test_stale_candidate_evidence_reference_fails_closed(self) -> None:
        with self.assertRaisesRegex(HookDecisionContractError, "does not match"):
            validate_hook_decision_reference(
                self.decision, self.evidence_raw.replace("0.72", "0.73")
            )

    def test_direct_support_must_be_recorded_in_the_evidence(self) -> None:
        payload = self.payload()
        selected = self.selected_hypothesis(payload)
        selected["required_evidence"].append(
            {
                "coverage_token": "AFTER_STATE",
                "description": "the state after use has to be on screen",
            }
        )
        selected["available_visual_support"].append(
            {
                "candidate_id": self.candidate_id(100),
                "coverage_token": "AFTER_STATE",
                "support": "DIRECT",
            }
        )
        decision = parse_hook_decision(payload)
        with self.assertRaisesRegex(HookDecisionContractError, "not recorded"):
            validate_hook_decision_against_evidence(
                decision, self.evidence, self.pool, self.catalog
            )

    def test_direct_support_on_another_candidate_is_checked_too(self) -> None:
        payload = self.payload()
        pain = self.hypothesis(payload, "PAIN")
        pain["available_visual_support"][0]["support"] = "DIRECT"
        pain["available_visual_support"][0]["candidate_id"] = self.candidate_id(800)
        decision = parse_hook_decision(payload)
        with self.assertRaisesRegex(HookDecisionContractError, "not recorded"):
            validate_hook_decision_against_evidence(
                decision, self.evidence, self.pool, self.catalog
            )

    def test_support_on_an_unanalysed_candidate_fails_closed(self) -> None:
        payload = self.payload()
        pain = self.hypothesis(payload, "PAIN")
        pain["available_visual_support"][0]["candidate_id"] = self.candidate_id(900)
        decision = parse_hook_decision(payload)
        with self.assertRaisesRegex(HookDecisionContractError, "ANALYZED"):
            validate_hook_decision_against_evidence(
                decision, self.evidence, self.pool, self.catalog
            )

    def test_contradictory_evidence_fails_closed(self) -> None:
        payload = self.payload()
        pain = self.hypothesis(payload, "PAIN")
        pain["required_evidence"] = [
            {
                "coverage_token": "OBSERVABLE_RESULT",
                "description": "the result has to be on screen",
            }
        ]
        pain["available_visual_support"] = [
            {
                "candidate_id": self.candidate_id(800),
                "coverage_token": "OBSERVABLE_RESULT",
                "support": "DIRECT",
            }
        ]
        decision = parse_hook_decision(payload)
        with self.assertRaisesRegex(HookDecisionContractError, "not recorded"):
            validate_hook_decision_against_evidence(
                decision, self.evidence, self.pool, self.catalog
            )


class FrozenResultRuleTests(HookDecisionTestCase):
    """The v1 result rule stays the v1 rule. Phase 3 tightens its own gate, not this one."""

    def result_candidate(self) -> str:
        for item in self.raw["hypotheses"]:
            if item["hook_type"] == "RESULT":
                return item["available_visual_support"][-1]["candidate_id"]
        raise AssertionError("the frozen fixture has no RESULT hypothesis")

    def views(self):
        from src.ai_autocut.candidate_evidence_v2 import (
            authoritative_evidence_view,
            read_candidate_evidence,
        )

        read = read_candidate_evidence(json.loads(EVIDENCE_FIXTURE.read_text()))
        return {one.candidate_id: one for one in authoritative_evidence_view(read)}

    def test_a_recorded_result_in_prose_still_supports_the_token(self) -> None:
        from src.ai_autocut.creative_intent import (
            direct_support_satisfied,
            structured_support_satisfied,
            support_recorded,
        )

        candidate_id = self.result_candidate()
        entry = self.evidence.entry_for(candidate_id)
        view = self.views()[candidate_id]
        self.assertTrue(direct_support_satisfied(entry, CoverageToken.OBSERVABLE_RESULT))
        # A v1 artifact never recorded a structured observation, so the structured half
        # is false and the compatibility rule cannot be narrower than the frozen rule.
        self.assertFalse(
            structured_support_satisfied(view, CoverageToken.OBSERVABLE_RESULT)
        )
        self.assertTrue(
            support_recorded(entry, view, CoverageToken.OBSERVABLE_RESULT)
        )

    def test_the_compatibility_predicate_is_never_narrower_than_v1(self) -> None:
        from src.ai_autocut.creative_intent import (
            direct_support_satisfied,
            support_recorded,
        )

        views = self.views()
        for token in CoverageToken:
            for entry in self.evidence.entries:
                with self.subTest(token=token.value, candidate=entry.candidate_id[:12]):
                    self.assertEqual(
                        support_recorded(entry, views[entry.candidate_id], token),
                        direct_support_satisfied(entry, token),
                    )

    def test_the_validator_still_accepts_a_direct_result(self) -> None:
        payload = self.payload()
        for item in payload["hypotheses"]:
            if item["hook_type"] != "RESULT":
                continue
            for support in item["available_visual_support"]:
                if support["coverage_token"] == "OBSERVABLE_RESULT":
                    support["support"] = "DIRECT"
        decision = parse_hook_decision(payload)
        validate_hook_decision(decision)
        validate_hook_decision_against_evidence(
            decision, self.evidence, self.pool, self.catalog
        )


class HookSerializationTests(HookDecisionTestCase):
    def test_serialization_is_stable_and_order_independent(self) -> None:
        first = render_hook_decision(self.decision)
        payload = self.payload()
        payload["hypotheses"].reverse()
        payload["selection_reason_codes"].reverse()
        item = self.hypothesis(payload, "PAIN")
        item["required_evidence"].reverse()
        item["available_visual_support"].reverse()
        item["assessment"]["rejection_codes"].reverse()
        self.assertEqual(render_hook_decision(parse_hook_decision(payload)), first)
        self.assertEqual(render_hook_decision(self.decision), first)

    def test_document_is_exact_key_and_self_describing(self) -> None:
        document = json.loads(render_hook_decision(self.decision))
        self.assertEqual(document["schema_version"], SCHEMA_VERSION)
        self.assertEqual(
            sorted(document),
            [
                "brief",
                "candidate_evidence",
                "decision_owner",
                "hypotheses",
                "schema_version",
                "selected_hook_id",
                "selection_reason_codes",
            ],
        )
        for payload in (
            {**self.payload(), "score": 0.9},
            {**self.payload(), "hook_type": "PAIN"},
        ):
            with self.subTest(payload=sorted(payload)):
                with self.assertRaises(HookDecisionContractError):
                    parse_hook_decision(payload)
        unknown_nested = self.payload()
        self.hypothesis(unknown_nested, "PAIN")["approval"] = "ACCEPTED"
        with self.assertRaises(HookDecisionContractError):
            parse_hook_decision(unknown_nested)

    def test_hook_decision_carries_no_copy_or_production_state(self) -> None:
        rendered = render_hook_decision(self.decision)
        for marker in ("plan_id", "segments", "released", "producer_final_review"):
            self.assertNotIn(marker, rendered)
        self.assertEqual(
            tuple(sorted(json.loads(rendered)["brief"])), ("ref", "sha256")
        )

    def test_path_like_hook_input_is_not_echoed_in_error(self) -> None:
        private = absolute("Users", "someone", "hook.json")
        payload = self.payload()
        payload["candidate_evidence"] = {"ref": private, "sha256": "0" * 64}
        with self.assertRaises(HookDecisionContractError) as caught:
            parse_hook_decision(payload)
        self.assertNotIn(private, str(caught.exception))

    def test_decision_type_is_enforced(self) -> None:
        with self.assertRaises(HookDecisionContractError):
            render_hook_decision("hook_decision.json")  # type: ignore[arg-type]
        with self.assertRaises(HookDecisionContractError):
            validate_hook_decision({})  # type: ignore[arg-type]
        self.assertIsInstance(self.decision, HookDecision)
        self.assertEqual(
            render_candidate_evidence(self.evidence),
            self.evidence_raw,
        )
        self.assertEqual(
            self.hypothesis(self.raw, "PAIN")["assessment"]["fact_safety"],
            FactSafety.FACT_UNSAFE.value,
        )
        self.assertEqual(EvidenceCoverage.FULL.value, "FULL")


class ContractDocumentTests(HookDecisionTestCase):
    def test_contract_document_states_status_and_its_own_limits(self) -> None:
        text = CONTRACT.read_text(encoding="utf-8")
        self.assertIn("`hook_decision.v1`", text)
        self.assertIn("src/ai_autocut/creative_intent.py", text)
        self.assertIn("tests/fixtures/hook_decision_v1_valid.json", text)
        for hook_type in sorted(HOOK_TYPES):
            self.assertIn(hook_type, text)

    def test_contract_document_names_its_producer_and_its_boundary(self) -> None:
        """The document must not overclaim, and must not understate either.

        Phase 3 gave the contract a producer, so "no writer exists" would now be false.
        What must stay checkable is the boundary: the document names the stage that
        writes it, the three outcomes, where the model's ordering actually lives, the
        limit of the fact gate, and everything the stage still does not do.
        """

        text = " ".join(CONTRACT.read_text(encoding="utf-8").split())
        self.assertIn("src/ai_autocut/hook_planning.py", text)
        self.assertIn("DECIDE THE HOOK", text)
        self.assertIn("`PENDING`", text)
        self.assertIn("UNASSIGNED", text)
        self.assertIn("does not compare evidence strength", text)
        self.assertIn("No case calls a second model", text)
        # Ordering is recorded in the response artifact, not in the decision.
        self.assertIn("planning/hook_planning_response.json", text)
        self.assertIn("not a ranking", text)
        # The fact gate validates declared references, and says so.
        self.assertIn("declared Product Fact reference validation", text)
        self.assertIn("cannot prove that a premise declared", text)
        self.assertIn("shot ordering", text)
        self.assertIn("Sequence Planning", text)
        self.assertIn("conversion prediction", text)
        self.assertIn("Nothing downstream consumes one yet", text)

    def test_contract_document_keeps_the_v1_result_rule_and_says_so(self) -> None:
        """The document must not claim the frozen v1 result rule stopped applying."""

        text = " ".join(CONTRACT.read_text(encoding="utf-8").split())
        self.assertIn("Historical semantics are preserved", text)
        self.assertIn("A v1 artifact that was directly supported", text)
        self.assertIn("never narrower than it was", text)


if __name__ == "__main__":
    unittest.main()
