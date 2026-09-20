from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
import unittest

from src.ai_autocut.candidate_pool import parse_candidate_pool
from src.ai_autocut.creative_intent import (
    parse_hook_decision,
    render_hook_decision,
)
from src.ai_autocut.editing_intelligence import (
    COVERAGE_ADD_REASON_CODES,
    COVERAGE_WITHHOLD_REASON_CODES,
    PLANNING_EVIDENCE_CANONICAL_REF,
    PLANNING_EVIDENCE_SCHEMA_VERSION,
    REINFORCEMENT_REASON_CODES,
    ActionEvidence,
    CoverageReasonCode,
    CoverageSummary,
    CoverageToken,
    EditingIntelligenceError,
    NarrativeRole,
    PlanDecision,
    PlannedCandidateDecision,
    PlanningEvidence,
    PlanningEvidenceContractError,
    parse_planning_evidence,
    render_planning_evidence,
    useful_action_range,
    validate_planning_evidence,
    validate_planning_evidence_binding,
    validate_planning_evidence_reference,
    validate_timeline_range,
)
from src.ai_autocut.editing_plan import EditingPlan, parse_editing_plan
from src.ai_autocut.identity import parse_identity_catalog


# Probe paths are assembled from fragments on purpose: this repository is scanned
# by the path-hygiene test, which would otherwise flag this module's own probe.
def absolute(*parts: str) -> str:
    """Build an absolute POSIX path without writing a literal prefix."""

    return "/" + "/".join(parts)


FIXTURES = Path(__file__).parent / "fixtures"
IDENTITY_FIXTURE = FIXTURES / "vnext_identity_catalog_v1_valid.json"
POOL_FIXTURE = FIXTURES / "vnext_candidate_pool_v1_valid.json"
PLAN_FIXTURE = FIXTURES / "vnext_editing_plan_v1_valid.json"
HOOK_FIXTURE = FIXTURES / "hook_decision_v1_valid.json"
PLANNING_FIXTURE = FIXTURES / "planning_evidence_v1_valid.json"
CONTRACT = (
    Path(__file__).parents[1] / "docs" / "contracts" / "planning-evidence-v1.md"
)


class PlanningEvidenceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = parse_identity_catalog(json.loads(IDENTITY_FIXTURE.read_text()))
        self.pool = parse_candidate_pool(json.loads(POOL_FIXTURE.read_text()))
        self.plan = parse_editing_plan(json.loads(PLAN_FIXTURE.read_text()))
        self.hook_raw = HOOK_FIXTURE.read_text(encoding="utf-8")
        self.hook = parse_hook_decision(json.loads(self.hook_raw))
        self.raw = json.loads(PLANNING_FIXTURE.read_text())
        self.evidence = parse_planning_evidence(self.raw)

    def payload(self) -> dict:
        return copy.deepcopy(self.raw)

    def candidate_id(self, start_frame: int) -> str:
        for item in self.catalog.candidates:
            if item.start_frame == start_frame:
                return item.candidate_id
        raise AssertionError("fixture candidate is missing")

    def decision(self, payload: dict, start_frame: int) -> dict:
        target = self.candidate_id(start_frame)
        for item in payload["decisions"]:
            if item["candidate_id"] == target:
                return item
        raise AssertionError("fixture decision is missing")

    def summary(self, payload: dict) -> dict:
        return payload["coverage_summary"]


class RoundTripTests(PlanningEvidenceTestCase):
    def test_canonical_fixture_round_trips_and_validates(self) -> None:
        raw_text = PLANNING_FIXTURE.read_text(encoding="utf-8")
        self.assertEqual(render_planning_evidence(self.evidence), raw_text)
        self.assertEqual(
            parse_planning_evidence(json.loads(raw_text)), self.evidence
        )
        validate_planning_evidence(self.evidence)
        resolved = validate_planning_evidence_binding(
            self.evidence, self.plan, self.pool, self.catalog
        )
        self.assertEqual(
            [item.candidate_id for item in resolved],
            [segment.candidate_id for segment in self.plan.segments],
        )

    def test_decision_types_are_all_represented(self) -> None:
        kinds = {item.decision.value for item in self.evidence.decisions}
        self.assertEqual(kinds, {"KEEP", "TRIM", "REJECT"})
        self.assertEqual(
            self.evidence.coverage_summary.keep_count,
            sum(1 for item in self.evidence.decisions if item.decision is PlanDecision.KEEP),
        )

    def test_serialization_is_stable_and_order_independent(self) -> None:
        first = render_planning_evidence(self.evidence)
        payload = self.payload()
        payload["decisions"].reverse()
        payload["requirements"].reverse()
        item = self.decision(payload, 100)
        item["adds_coverage"].reverse()
        item["reason_codes"].reverse()
        self.summary(payload)["covered_tokens"].reverse()
        self.assertEqual(render_planning_evidence(parse_planning_evidence(payload)), first)
        self.assertEqual(render_planning_evidence(self.evidence), first)

    def test_reference_binding_detects_a_stale_hook_decision(self) -> None:
        validate_planning_evidence_reference(self.evidence, self.hook_raw)
        with self.assertRaisesRegex(PlanningEvidenceContractError, "does not match"):
            validate_planning_evidence_reference(self.evidence, self.hook_raw + "\n")
        self.assertEqual(
            render_hook_decision(self.hook),
            self.hook_raw,
        )
        self.assertEqual(
            self.evidence.hook_decision.ref, "planning/hook_decision.json"
        )
        self.assertEqual(PLANNING_EVIDENCE_CANONICAL_REF, "planning/planning_evidence.json")

    def test_plan_binding_maps_positions_to_plan_segments(self) -> None:
        positions = {
            item.sequence_position: item.candidate_id
            for item in self.evidence.decisions
            if item.is_selected
        }
        for position, segment in enumerate(self.plan.segments, start=1):
            self.assertEqual(positions[position], segment.candidate_id)

    def test_why_is_prose_and_never_machine_truth(self) -> None:
        payload = self.payload()
        self.decision(payload, 100)["why"] = "a completely different sentence"
        parsed = parse_planning_evidence(payload)
        validate_planning_evidence_binding(parsed, self.plan, self.pool, self.catalog)
        original = self.evidence.decision_for(self.candidate_id(100))
        changed = parsed.decision_for(self.candidate_id(100))
        self.assertEqual(original.decision, changed.decision)
        self.assertEqual(original.reason_codes, changed.reason_codes)
        self.assertEqual(original.adds_coverage, changed.adds_coverage)
        self.assertEqual(original.duration_cost_frames, changed.duration_cost_frames)
        self.assertNotEqual(original.why, changed.why)


class DecisionTests(PlanningEvidenceTestCase):
    def test_keep_can_be_built_and_validated(self) -> None:
        keep = PlannedCandidateDecision(
            candidate_id=self.candidate_id(100),
            decision=PlanDecision.KEEP,
            sequence_position=1,
            adds_coverage=(CoverageToken.PRODUCT_VISIBLE,),
            duration_cost_frames=30,
            reason_codes=(CoverageReasonCode.FIRST_DIRECT_PROOF,),
            why="first direct proof of the product",
        )
        self.assertTrue(keep.is_selected)
        self.assertEqual(
            keep.as_dict()["adds_coverage"], ["PRODUCT_VISIBLE"]
        )

    def test_trim_is_representable_and_spends_less_than_the_candidate(self) -> None:
        payload = self.payload()
        trim = self.decision(payload, 600)
        self.assertEqual(trim["decision"], "TRIM")
        self.assertEqual(trim["duration_cost_frames"], 60)
        parsed = parse_planning_evidence(payload)
        validate_planning_evidence_binding(parsed, self.plan, self.pool, self.catalog)
        candidate = next(
            item
            for item in self.catalog.candidates
            if item.candidate_id == self.candidate_id(600)
        )
        self.assertLess(
            trim["duration_cost_frames"],
            candidate.end_frame_exclusive - candidate.start_frame,
        )
        self.assertIn(
            candidate.candidate_id,
            [segment.candidate_id for segment in self.plan.segments],
        )

    def test_trim_must_spend_less_than_the_identified_duration(self) -> None:
        payload = self.payload()
        self.decision(payload, 600)["duration_cost_frames"] = 90
        payload["total_duration_frames"] = 213
        with self.assertRaisesRegex(PlanningEvidenceContractError, "TRIM"):
            validate_planning_evidence_binding(
                parse_planning_evidence(payload), self.plan, self.pool, self.catalog
            )

    def test_reject_is_representable(self) -> None:
        payload = self.payload()
        reject = self.decision(payload, 900)
        self.assertEqual(reject["decision"], "REJECT")
        self.assertIsNone(reject["sequence_position"])
        self.assertEqual(reject["duration_cost_frames"], 0)
        self.assertEqual(reject["adds_coverage"], [])
        parsed = parse_planning_evidence(payload)
        self.assertFalse(parsed.decision_for(self.candidate_id(900)).is_selected)

    def test_reject_cannot_claim_position_duration_or_coverage(self) -> None:
        for field, value in (
            ("sequence_position", 5),
            ("duration_cost_frames", 12),
            ("adds_coverage", ["PRODUCT_VISIBLE"]),
        ):
            payload = self.payload()
            self.decision(payload, 900)[field] = value
            with self.subTest(field=field):
                with self.assertRaises(PlanningEvidenceContractError):
                    parse_planning_evidence(payload)

    def test_keep_must_spend_the_identified_duration(self) -> None:
        payload = self.payload()
        self.decision(payload, 100)["duration_cost_frames"] = 29
        payload["total_duration_frames"] = 182
        with self.assertRaisesRegex(PlanningEvidenceContractError, "KEEP"):
            validate_planning_evidence_binding(
                parse_planning_evidence(payload), self.plan, self.pool, self.catalog
            )

    def test_a_rejected_candidate_must_not_be_in_the_plan(self) -> None:
        plan = EditingPlan.create(
            self.pool.pool_id,
            [segment.candidate_id for segment in self.plan.segments]
            + [self.candidate_id(900)],
        )
        evidence = dataclasses.replace(self.evidence, plan_id=plan.plan_id)
        with self.assertRaisesRegex(PlanningEvidenceContractError, "REJECT"):
            validate_planning_evidence_binding(
                evidence, plan, self.pool, self.catalog
            )

    def test_decision_requires_a_reason_code(self) -> None:
        payload = self.payload()
        self.decision(payload, 900)["reason_codes"] = []
        with self.assertRaisesRegex(PlanningEvidenceContractError, "reason code"):
            parse_planning_evidence(payload)

    def test_unknown_reason_code_and_wrong_code_class_fail_closed(self) -> None:
        payload = self.payload()
        self.decision(payload, 100)["reason_codes"] = ["LOOKS_GOOD"]
        with self.assertRaises(PlanningEvidenceContractError):
            parse_planning_evidence(payload)
        payload = self.payload()
        self.decision(payload, 100)["reason_codes"] = ["SEMANTIC_SATURATION"]
        with self.assertRaisesRegex(PlanningEvidenceContractError, "coverage"):
            parse_planning_evidence(payload)
        payload = self.payload()
        self.decision(payload, 900)["reason_codes"] = ["FIRST_DIRECT_PROOF"]
        with self.assertRaisesRegex(PlanningEvidenceContractError, "withholding"):
            parse_planning_evidence(payload)
        payload = self.payload()
        item = self.decision(payload, 500)
        item["reason_codes"] = ["SEMANTIC_SATURATION"]
        with self.assertRaisesRegex(PlanningEvidenceContractError, "reinforcement"):
            parse_planning_evidence(payload)

    def test_reinforcement_vocabulary_is_complete(self) -> None:
        self.assertEqual(
            {code.value for code in REINFORCEMENT_REASON_CODES},
            {
                "MULTI_AREA_REQUIREMENT",
                "ACTION_TO_RESULT_RELATION",
                "CONTRAST_OR_OLD_WAY",
                "HOOK_CALLBACK",
                "RHYTHM_BRIDGE_WITH_NO_SEMANTIC_ALTERNATIVE",
                "PRODUCER_EXPLICIT_REINFORCEMENT",
            },
        )
        self.assertEqual(
            {code.value for code in COVERAGE_ADD_REASON_CODES},
            {"FIRST_DIRECT_PROOF"},
        )
        self.assertEqual(
            {code.value for code in COVERAGE_WITHHOLD_REASON_CODES},
            {
                "SEMANTIC_SATURATION",
                "NO_NEW_EVIDENCE_DIMENSION",
                "ANALYSIS_UNAVAILABLE",
            },
        )

    def test_redundant_keep_must_not_claim_new_coverage(self) -> None:
        payload = self.payload()
        item = self.decision(payload, 500)
        item["adds_coverage"] = ["PRODUCT_VISIBLE"]
        with self.assertRaisesRegex(PlanningEvidenceContractError, "redundant"):
            parse_planning_evidence(payload)

    def test_non_redundant_selected_decision_must_claim_coverage(self) -> None:
        payload = self.payload()
        self.decision(payload, 100)["adds_coverage"] = []
        with self.assertRaisesRegex(PlanningEvidenceContractError, "coverage"):
            parse_planning_evidence(payload)

    def test_invalid_redundant_with_fails_closed(self) -> None:
        payload = self.payload()
        item = self.decision(payload, 300)
        item["redundant_with"] = [self.candidate_id(500)]
        item["adds_coverage"] = []
        item["reason_codes"] = ["HOOK_CALLBACK"]
        with self.assertRaisesRegex(PlanningEvidenceContractError, "earlier"):
            parse_planning_evidence(payload)
        payload = self.payload()
        self.decision(payload, 500)["redundant_with"] = [self.candidate_id(500)]
        with self.assertRaisesRegex(PlanningEvidenceContractError, "itself"):
            parse_planning_evidence(payload)
        payload = self.payload()
        self.decision(payload, 500)["redundant_with"] = ["candv1_" + "0" * 64]
        with self.assertRaisesRegex(PlanningEvidenceContractError, "selected Candidate"):
            parse_planning_evidence(payload)
        payload = self.payload()
        self.decision(payload, 900)["redundant_with"] = [self.candidate_id(100)]
        with self.assertRaisesRegex(PlanningEvidenceContractError, "REJECT"):
            parse_planning_evidence(payload)

    def test_duplicate_candidate_decision_fails_closed(self) -> None:
        payload = self.payload()
        payload["decisions"].append(copy.deepcopy(self.decision(payload, 100)))
        with self.assertRaisesRegex(PlanningEvidenceContractError, "duplicate"):
            parse_planning_evidence(payload)

    def test_candidate_outside_the_pool_fails_closed(self) -> None:
        payload = self.payload()
        payload["decisions"].append(
            {
                "candidate_id": "candv1_" + "0" * 64,
                "decision": "REJECT",
                "sequence_position": None,
                "adds_coverage": [],
                "redundant_with": [],
                "duration_cost_frames": 0,
                "reason_codes": ["ANALYSIS_UNAVAILABLE"],
                "why": "fabricated candidate",
            }
        )
        payload["coverage_summary"]["decision_counts"]["REJECT"] = 3
        parsed = parse_planning_evidence(payload)
        with self.assertRaises(PlanningEvidenceContractError):
            validate_planning_evidence_binding(
                parsed, self.plan, self.pool, self.catalog
            )

    def test_malformed_candidate_id_fails_closed(self) -> None:
        payload = self.payload()
        self.decision(payload, 100)["candidate_id"] = "C01"
        with self.assertRaises(PlanningEvidenceContractError):
            parse_planning_evidence(payload)


class SequencePositionTests(PlanningEvidenceTestCase):
    def test_sequence_positions_must_be_contiguous(self) -> None:
        for value in (0, 5, 99):
            payload = self.payload()
            self.decision(payload, 500)["sequence_position"] = value
            with self.subTest(value=value):
                with self.assertRaises(PlanningEvidenceContractError):
                    parse_planning_evidence(payload)

    def test_duplicate_sequence_position_fails_closed(self) -> None:
        payload = self.payload()
        self.decision(payload, 500)["sequence_position"] = 1
        with self.assertRaisesRegex(PlanningEvidenceContractError, "1..N"):
            validate_planning_evidence(parse_planning_evidence(payload))

    def test_selected_decision_requires_a_position(self) -> None:
        payload = self.payload()
        self.decision(payload, 500)["sequence_position"] = None
        with self.assertRaisesRegex(PlanningEvidenceContractError, "sequence position"):
            parse_planning_evidence(payload)

    def test_positions_must_match_the_editing_plan(self) -> None:
        payload = self.payload()
        first = self.decision(payload, 100)
        second = self.decision(payload, 300)
        first["candidate_id"], second["candidate_id"] = (
            second["candidate_id"],
            first["candidate_id"],
        )
        first["duration_cost_frames"], second["duration_cost_frames"] = 45, 30
        parsed = parse_planning_evidence(payload)
        with self.assertRaisesRegex(PlanningEvidenceContractError, "sequence position"):
            validate_planning_evidence_binding(
                parsed, self.plan, self.pool, self.catalog
            )

    def test_plan_id_mismatch_fails_closed(self) -> None:
        other = EditingPlan.create(
            self.pool.pool_id, [self.candidate_id(100)]
        )
        with self.assertRaisesRegex(PlanningEvidenceContractError, "plan_id"):
            validate_planning_evidence_binding(
                self.evidence, other, self.pool, self.catalog
            )

    def test_selected_decisions_must_account_for_every_plan_segment(self) -> None:
        payload = self.payload()
        target = self.candidate_id(500)
        payload["decisions"] = [
            item for item in payload["decisions"] if item["candidate_id"] != target
        ]
        payload["coverage_summary"]["redundant_keeps"] = 0
        payload["coverage_summary"]["decision_counts"] = {
            "KEEP": 2,
            "TRIM": 1,
            "REJECT": 2,
        }
        payload["total_duration_frames"] = 30 + 45 + 60
        parsed = parse_planning_evidence(payload)
        with self.assertRaisesRegex(PlanningEvidenceContractError, "every Editing Plan"):
            validate_planning_evidence_binding(
                parsed, self.plan, self.pool, self.catalog
            )


class CoverageTests(PlanningEvidenceTestCase):
    def test_coverage_token_vocabulary_is_minimal_and_finite(self) -> None:
        self.assertEqual(
            {token.value for token in CoverageToken},
            {
                "PRODUCT_VISIBLE",
                "ACTION_ONSET",
                "OBSERVABLE_RESULT",
                "BEFORE_STATE",
                "AFTER_STATE",
                "USAGE_CONTEXT",
                "CLAIM_SUPPORT_DIRECT",
                "IDENTITY_SHOT",
                "BODY_AREA",
            },
        )

    def test_unknown_coverage_token_fails_closed(self) -> None:
        payload = self.payload()
        self.decision(payload, 100)["adds_coverage"] = ["BEAUTY"]
        with self.assertRaises(PlanningEvidenceContractError):
            parse_planning_evidence(payload)
        payload = self.payload()
        payload["requirements"] = ["BEAUTY"]
        with self.assertRaises(PlanningEvidenceContractError):
            parse_planning_evidence(payload)

    def test_a_token_may_be_claimed_once(self) -> None:
        payload = self.payload()
        self.decision(payload, 300)["adds_coverage"] = [
            "PRODUCT_VISIBLE",
            "ACTION_ONSET",
            "OBSERVABLE_RESULT",
        ]
        with self.assertRaisesRegex(PlanningEvidenceContractError, "only one"):
            validate_planning_evidence(parse_planning_evidence(payload))

    def test_coverage_outside_the_requirements_fails_closed(self) -> None:
        payload = self.payload()
        self.decision(payload, 100)["adds_coverage"] = [
            "PRODUCT_VISIBLE",
            "CLAIM_SUPPORT_DIRECT",
            "USAGE_CONTEXT",
        ]
        self.summary(payload)["covered_tokens"].append("USAGE_CONTEXT")
        with self.assertRaisesRegex(PlanningEvidenceContractError, "do not ask for"):
            validate_planning_evidence(parse_planning_evidence(payload))

    def test_invalid_coverage_summary_fails_closed(self) -> None:
        mutations = (
            ("covered_tokens", ["PRODUCT_VISIBLE"]),
            ("missing_tokens", ["PRODUCT_VISIBLE"]),
            ("redundant_keeps", 0),
        )
        for field, value in mutations:
            payload = self.payload()
            self.summary(payload)[field] = value
            with self.subTest(field=field):
                with self.assertRaises(PlanningEvidenceContractError):
                    validate_planning_evidence(parse_planning_evidence(payload))

    def test_decision_counts_must_match_the_decisions(self) -> None:
        for field, value in (("KEEP", 2), ("TRIM", 2), ("REJECT", 1)):
            payload = self.payload()
            self.summary(payload)["decision_counts"][field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    PlanningEvidenceContractError, "decision_counts"
                ):
                    validate_planning_evidence(parse_planning_evidence(payload))

    def test_missing_tokens_are_reported_honestly(self) -> None:
        payload = self.payload()
        item = self.decision(payload, 600)
        item["adds_coverage"] = []
        item["redundant_with"] = [self.candidate_id(300)]
        item["reason_codes"] = ["MULTI_AREA_REQUIREMENT"]
        self.summary(payload)["covered_tokens"].remove("BODY_AREA")
        self.summary(payload)["missing_tokens"] = ["BODY_AREA"]
        parsed = parse_planning_evidence(payload)
        validate_planning_evidence(parsed)
        self.assertEqual(
            [token.value for token in parsed.coverage_summary.missing_tokens],
            ["BODY_AREA"],
        )
        self.summary(payload)["missing_tokens"] = []
        with self.assertRaises(PlanningEvidenceContractError):
            validate_planning_evidence(parse_planning_evidence(payload))

    def test_requirements_must_not_be_empty(self) -> None:
        payload = self.payload()
        payload["requirements"] = []
        with self.assertRaisesRegex(PlanningEvidenceContractError, "requirements"):
            parse_planning_evidence(payload)

    def test_duplicate_requirement_fails_closed(self) -> None:
        payload = self.payload()
        payload["requirements"].append("PRODUCT_VISIBLE")
        with self.assertRaises(PlanningEvidenceContractError):
            parse_planning_evidence(payload)


class DurationTests(PlanningEvidenceTestCase):
    def test_total_duration_must_match_the_selected_costs(self) -> None:
        payload = self.payload()
        payload["total_duration_frames"] = 999
        with self.assertRaisesRegex(PlanningEvidenceContractError, "total_duration"):
            validate_planning_evidence(parse_planning_evidence(payload))

    def test_negative_and_non_integer_durations_fail_closed(self) -> None:
        for value in (-1, 1.5, "30", None, True):
            payload = self.payload()
            self.decision(payload, 100)["duration_cost_frames"] = value
            with self.subTest(value=value):
                with self.assertRaises(PlanningEvidenceContractError):
                    parse_planning_evidence(payload)

    def test_selected_duration_must_be_positive(self) -> None:
        payload = self.payload()
        self.decision(payload, 100)["duration_cost_frames"] = 0
        with self.assertRaisesRegex(PlanningEvidenceContractError, "positive"):
            parse_planning_evidence(payload)

    def test_trim_shorter_than_one_frame_is_not_representable(self) -> None:
        payload = self.payload()
        self.decision(payload, 600)["duration_cost_frames"] = 0
        payload["total_duration_frames"] = 123
        with self.assertRaises(PlanningEvidenceContractError):
            parse_planning_evidence(payload)


class ExactKeyAndLeakageTests(PlanningEvidenceTestCase):
    def test_document_keys_are_closed(self) -> None:
        payload = self.payload()
        payload["score"] = 0.9
        with self.assertRaises(PlanningEvidenceContractError):
            parse_planning_evidence(payload)
        payload = self.payload()
        self.decision(payload, 100)["confidence"] = 0.9
        with self.assertRaises(PlanningEvidenceContractError):
            parse_planning_evidence(payload)
        payload = self.payload()
        self.summary(payload)["approval"] = "ACCEPTED"
        with self.assertRaises(PlanningEvidenceContractError):
            parse_planning_evidence(payload)
        payload = self.payload()
        payload["coverage_summary"]["decision_counts"]["HOLD"] = 0
        with self.assertRaises(PlanningEvidenceContractError):
            parse_planning_evidence(payload)
        payload = self.payload()
        payload["coverage_summary"]["decision_counts"] = {"KEEP": 3}
        with self.assertRaises(PlanningEvidenceContractError):
            parse_planning_evidence(payload)

    def test_schema_version_is_enforced(self) -> None:
        payload = self.payload()
        payload["schema_version"] = "planning_evidence.v2"
        with self.assertRaisesRegex(PlanningEvidenceContractError, "schema_version"):
            parse_planning_evidence(payload)

    def test_document_does_not_mutate_the_editing_plan_contract(self) -> None:
        rendered = render_planning_evidence(self.evidence)
        document = json.loads(rendered)
        self.assertEqual(document["schema_version"], PLANNING_EVIDENCE_SCHEMA_VERSION)
        for marker in ("trim_range", "start_frame", "end_frame_exclusive"):
            self.assertNotIn(marker, rendered)
        self.assertEqual(
            sorted(document),
            [
                "coverage_summary",
                "decisions",
                "hook_decision",
                "plan_id",
                "planner_run_id",
                "requirements",
                "schema_version",
                "total_duration_frames",
            ],
        )

    def test_planner_run_id_shape_is_enforced(self) -> None:
        for value in (absolute("Users", "someone", "run"), "", "run one", None, 7):
            payload = self.payload()
            payload["planner_run_id"] = value
            with self.subTest(value=value):
                with self.assertRaises(PlanningEvidenceContractError):
                    parse_planning_evidence(payload)

    def test_path_like_values_are_not_echoed_in_error(self) -> None:
        private = absolute("Users", "someone", "plan.json")
        payload = self.payload()
        payload["planner_run_id"] = private
        with self.assertRaises(PlanningEvidenceContractError) as caught:
            parse_planning_evidence(payload)
        self.assertNotIn(private, str(caught.exception))

    def test_evidence_type_is_enforced(self) -> None:
        for value in ("planning_evidence.json", {}, None):
            with self.subTest(value=value):
                with self.assertRaises(PlanningEvidenceContractError):
                    render_planning_evidence(value)  # type: ignore[arg-type]
                with self.assertRaises(PlanningEvidenceContractError):
                    validate_planning_evidence(value)  # type: ignore[arg-type]
        self.assertIsInstance(self.evidence, PlanningEvidence)

    def test_blocked_binding_inputs_fail_closed(self) -> None:
        with self.assertRaises(PlanningEvidenceContractError):
            validate_planning_evidence_binding(
                self.evidence, self.plan, self.pool, object()  # type: ignore[arg-type]
            )
        with self.assertRaises(PlanningEvidenceContractError):
            validate_planning_evidence_reference(self.evidence, 42)


class LegacyVocabularyTests(PlanningEvidenceTestCase):
    def test_existing_editing_intelligence_behaviour_is_unchanged(self) -> None:
        evidence = ActionEvidence(100, 112, 140, 165)
        self.assertEqual(useful_action_range(evidence), (112, 165))
        with self.assertRaisesRegex(EditingIntelligenceError, "result"):
            validate_timeline_range(
                role=NarrativeRole.HERO,
                start_frame=112,
                end_frame_exclusive=150,
                evidence=evidence,
            )
        validate_timeline_range(
            role=NarrativeRole.HOOK, start_frame=0, end_frame_exclusive=30
        )
        self.assertEqual(NarrativeRole.PROOF.value, "proof")
        self.assertEqual(CoverageSummary(
            covered_tokens=(CoverageToken.PRODUCT_VISIBLE,),
            missing_tokens=(),
            redundant_keeps=0,
            keep_count=1,
            trim_count=0,
            reject_count=0,
        ).as_dict()["decision_counts"], {"KEEP": 1, "TRIM": 0, "REJECT": 0})


class ContractDocumentTests(PlanningEvidenceTestCase):
    def test_contract_document_states_contract_only_status(self) -> None:
        text = CONTRACT.read_text(encoding="utf-8")
        self.assertIn("`planning_evidence.v1`", text)
        self.assertIn("src/ai_autocut/editing_intelligence.py", text)
        self.assertIn("tests/fixtures/planning_evidence_v1_valid.json", text)
        self.assertIn("CONTRACT EXISTS", text)
        self.assertIn("does not yet exist", text)
        for code in (
            "MULTI_AREA_REQUIREMENT",
            "ACTION_TO_RESULT_RELATION",
            "CONTRAST_OR_OLD_WAY",
            "HOOK_CALLBACK",
            "RHYTHM_BRIDGE_WITH_NO_SEMANTIC_ALTERNATIVE",
            "PRODUCER_EXPLICIT_REINFORCEMENT",
            "FIRST_DIRECT_PROOF",
            "SEMANTIC_SATURATION",
            "NO_NEW_EVIDENCE_DIMENSION",
        ):
            self.assertIn(code, text)


if __name__ == "__main__":
    unittest.main()
