from __future__ import annotations

import json
from pathlib import Path
import unittest

from src.ai_autocut.candidate_pool import CandidatePool, parse_candidate_pool
from src.ai_autocut.editing_plan import (
    SCHEMA_VERSION,
    EditingPlan,
    EditingPlanContractError,
    EditingPlanSegment,
    bind_plan_boundary_preflight,
    canonical_plan_identity_json,
    parse_editing_plan,
    plan_id_for,
    render_editing_plan,
    segment_id_for_position,
    validate_editing_plan,
)
from src.ai_autocut.identity import parse_identity_catalog
from src.ai_autocut.preflight import SCHEMA_VERSION as PREFLIGHT_SCHEMA_VERSION
from src.ai_autocut.preflight import parse_preflight_document


REPO_ROOT = Path(__file__).parents[1]
IDENTITY_FIXTURE = (
    Path(__file__).parent / "fixtures" / "material_candidate_identity_v1_valid.json"
)
POOL_FIXTURE = Path(__file__).parent / "fixtures" / "candidate_pool_v1_valid.json"
PLAN_FIXTURE = Path(__file__).parent / "fixtures" / "editing_plan_v1_valid.json"
CONTRACT = REPO_ROOT / "docs" / "contracts" / "editing-plan-v1.md"


class EditingPlanTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = parse_identity_catalog(json.loads(IDENTITY_FIXTURE.read_text()))
        self.pool = parse_candidate_pool(json.loads(POOL_FIXTURE.read_text()))
        self.candidate = self.catalog.candidates[0]
        self.plan = EditingPlan.create(self.pool.pool_id, (self.candidate.candidate_id,))


class PlanIdentityTests(EditingPlanTestCase):
    def test_canonical_payload_and_plan_id_are_fixed(self) -> None:
        self.assertEqual(
            canonical_plan_identity_json(
                self.pool.pool_id, (self.candidate.candidate_id,)
            ),
            '{"candidate_pool_id":"'
            + self.pool.pool_id
            + '","segments":[{"candidate_id":"'
            + self.candidate.candidate_id
            + '"}]}',
        )
        self.assertEqual(
            plan_id_for(self.pool.pool_id, (self.candidate.candidate_id,)),
            "planv1_fb241f72e275a248ecb53e8cd6ce0a0ccf15f499b7f5fda7fa90616d5c4a70fe",
        )

    def test_order_replacement_addition_deletion_and_pool_change_change_identity(self) -> None:
        other = "candv1_" + "f" * 64
        baseline = self.plan.plan_id
        variants = (
            plan_id_for(self.pool.pool_id, (other,)),
            plan_id_for(self.pool.pool_id, (self.candidate.candidate_id, other)),
            plan_id_for(self.pool.pool_id, (other, self.candidate.candidate_id)),
            plan_id_for("poolv1_" + "f" * 64, (self.candidate.candidate_id,)),
        )
        self.assertEqual(len(set(variants)), len(variants))
        self.assertNotIn(baseline, variants)

    def test_plan_id_excludes_external_explanation_and_score(self) -> None:
        evidence = {"reason": "opening", "score": 0.1, "confidence": 0.2}
        before = plan_id_for(self.pool.pool_id, (self.candidate.candidate_id,))
        evidence.update(reason="revised", score=0.9, confidence=0.8, model="x")
        after = plan_id_for(self.pool.pool_id, (self.candidate.candidate_id,))
        self.assertEqual(before, after)

    def test_tampered_plan_id_and_empty_plan_are_rejected(self) -> None:
        payload = self.plan.as_dict()
        payload["plan_id"] = "planv1_" + "0" * 64
        with self.assertRaisesRegex(EditingPlanContractError, "does not match"):
            parse_editing_plan(payload)
        with self.assertRaisesRegex(EditingPlanContractError, "must not be empty"):
            EditingPlan.create(self.pool.pool_id, ())


class PlanParsingTests(EditingPlanTestCase):
    def test_canonical_fixture_parses_and_matches_renderer(self) -> None:
        raw = PLAN_FIXTURE.read_text(encoding="utf-8")
        plan = parse_editing_plan(json.loads(raw))
        self.assertEqual(plan, self.plan)
        self.assertEqual(render_editing_plan(plan), raw)

    def test_renderer_is_deterministic_and_preserves_segment_order(self) -> None:
        repeated = EditingPlan.create(
            self.pool.pool_id,
            (self.candidate.candidate_id, self.candidate.candidate_id),
        )
        rendered = render_editing_plan(repeated)
        self.assertEqual(rendered, render_editing_plan(repeated))
        self.assertEqual(
            [item["candidate_id"] for item in json.loads(rendered)["segments"]],
            [self.candidate.candidate_id, self.candidate.candidate_id],
        )

    def test_strict_schema_and_single_field_segment(self) -> None:
        for payload in (
            {"schema_version": SCHEMA_VERSION, "plan_id": self.plan.plan_id},
            {**self.plan.as_dict(), "reason": "not allowed"},
            {
                **self.plan.as_dict(),
                "segments": [{"candidate_id": self.candidate.candidate_id, "score": 1}],
            },
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(EditingPlanContractError):
                    parse_editing_plan(payload)

    def test_malformed_path_like_and_noncanonical_identifiers_fail_closed(self) -> None:
        for candidate_id in ("/private/candidate.mov", "candv1_" + "0" * 63):
            with self.subTest(candidate_id=candidate_id):
                with self.assertRaises(EditingPlanContractError) as caught:
                    EditingPlan.create(self.pool.pool_id, (candidate_id,))
                self.assertNotIn(candidate_id, str(caught.exception))
        with self.assertRaises(EditingPlanContractError):
            EditingPlan.create("/private/pool", (self.candidate.candidate_id,))


class PlanValidationAndBindingTests(EditingPlanTestCase):
    def test_duplicate_candidate_usage_and_derived_segment_ids_are_deterministic(self) -> None:
        plan = EditingPlan.create(
            self.pool.pool_id,
            (self.candidate.candidate_id, self.candidate.candidate_id),
        )
        resolved = validate_editing_plan(plan, self.pool, self.catalog)
        self.assertEqual(resolved, (self.candidate, self.candidate))
        self.assertEqual(segment_id_for_position(1), "segv1_000001")
        self.assertEqual(segment_id_for_position(2), "segv1_000002")
        with self.assertRaises(EditingPlanContractError):
            segment_id_for_position(0)

    def test_pool_mismatch_pool_external_and_unknown_candidates_fail_closed(self) -> None:
        other_pool = CandidatePool.create(())
        with self.assertRaisesRegex(EditingPlanContractError, "does not match"):
            validate_editing_plan(self.plan, other_pool, self.catalog)

        external = EditingPlan.create(self.pool.pool_id, ("candv1_" + "f" * 64,))
        with self.assertRaisesRegex(EditingPlanContractError, "valid Candidate Pool"):
            validate_editing_plan(external, self.pool, self.catalog)

        unknown_id = "candv1_" + "0" * 64
        unknown_pool = CandidatePool.create((unknown_id,))
        unknown_plan = EditingPlan.create(unknown_pool.pool_id, (unknown_id,))
        with self.assertRaisesRegex(EditingPlanContractError, "valid Candidate Pool"):
            validate_editing_plan(unknown_plan, unknown_pool, self.catalog)

    def test_plan_pool_identity_preflight_chain_is_unchanged_and_contiguous(self) -> None:
        plan = EditingPlan.create(
            self.pool.pool_id,
            (self.candidate.candidate_id, self.candidate.candidate_id),
        )
        document = bind_plan_boundary_preflight(plan, self.pool, self.catalog)
        self.assertEqual(document["schema_version"], PREFLIGHT_SCHEMA_VERSION)
        segments = document["segments"]
        self.assertEqual(
            [segment["segment_id"] for segment in segments],
            ["segv1_000001", "segv1_000002"],
        )
        duration = self.candidate.end_frame_exclusive - self.candidate.start_frame
        self.assertEqual(
            [segment["planned_record_frame_relative"] for segment in segments],
            [0, duration],
        )
        self.assertNotIn("candidate_pool_id", segments[0])
        self.assertNotIn("plan_id", segments[0])
        self.assertEqual(len(parse_preflight_document(document)), 2)


class ContractAndLeakageTests(EditingPlanTestCase):
    def test_contract_and_rendered_plan_exclude_source_metadata_and_paths(self) -> None:
        text = CONTRACT.read_text(encoding="utf-8")
        self.assertIn("`editing_plan.v1`", text)
        self.assertIn("Status:** frozen", text)
        rendered = render_editing_plan(self.plan)
        for marker in (
            "material_id",
            "stream_index",
            "source_range",
            "trim",
            "/Users/",
            "file://",
            "reason",
            "score",
            "confidence",
            "explanation",
        ):
            self.assertNotIn(marker, rendered)


if __name__ == "__main__":
    unittest.main()
