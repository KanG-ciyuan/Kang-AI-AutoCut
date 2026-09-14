from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from src.ai_autocut.typography import (
    ALLOWED_MOTION,
    DEFAULT_VISUAL_DIRECTION,
    FORBIDDEN_MOTION,
    MAX_EMPHASIS_TERMS,
    MINIMUM_CONSIDERATIONS,
    PLACEMENT_CONSIDERATIONS,
    POLICY_STATUS,
    PLACEMENT_IMPLEMENTATION,
    TEXT_PRIORITY,
    TEXT_ROLES,
    TextEvent,
    TypographyPlan,
    TypographyPolicyError,
    assert_placement_implemented,
    parse_typography_plan,
    priority_rank,
    resolve_conflict,
)


REPO_ROOT = Path(__file__).parents[1]
SCHEMA = REPO_ROOT / "schemas" / "typography" / "typography_policy.v0.schema.json"

FULL_ZONES = list(PLACEMENT_CONSIDERATIONS)


def document() -> dict:
    return {
        "schema_version": "typography_policy.v0",
        "visual_direction": DEFAULT_VISUAL_DIRECTION,
        "events": [
            {
                "event_id": "TEXT-01",
                "role": "hook",
                "lines": ["FILTER KERAN"],
                "motion": "fade",
                "considered_zones": FULL_ZONES,
                "emphasis_terms": ["KERAN"],
                "safe_area_verified": True,
            },
            {
                "event_id": "TEXT-02",
                "role": "feature",
                "lines": ["ARAH AIR", "BISA DIATUR"],
                "motion": "micro_motion",
                "considered_zones": FULL_ZONES,
                "emphasis_terms": [],
                "safe_area_verified": True,
            },
        ],
    }


class TypographyPolicyTestCase(unittest.TestCase):
    def test_priority_puts_product_first_and_decoration_last(self) -> None:
        self.assertEqual(TEXT_PRIORITY[0], "product")
        self.assertEqual(TEXT_PRIORITY[-1], "decoration")

    def test_priority_is_a_total_order(self) -> None:
        self.assertEqual(
            [priority_rank(need) for need in TEXT_PRIORITY], [0, 1, 2, 3]
        )

    def test_text_never_displaces_product_or_action(self) -> None:
        self.assertEqual(resolve_conflict("product", "text"), "product")
        self.assertEqual(resolve_conflict("action", "text"), "action")

    def test_decoration_never_displaces_text(self) -> None:
        self.assertEqual(resolve_conflict("decoration", "text"), "text")

    def test_unknown_need_is_rejected(self) -> None:
        with self.assertRaises(TypographyPolicyError):
            priority_rank("vibes")

    def test_allowed_and_forbidden_motion_do_not_overlap(self) -> None:
        self.assertEqual(set(ALLOWED_MOTION) & set(FORBIDDEN_MOTION), set())

    def test_default_direction_forbids_directional_graphics(self) -> None:
        for motion in ("arrows", "trajectory_lines", "particles", "glow", "bounce", "rotation", "stickers"):
            with self.subTest(motion=motion):
                self.assertIn(motion, FORBIDDEN_MOTION)

    def test_voice_over_subtitles_are_not_a_text_role(self) -> None:
        self.assertEqual(tuple(TEXT_ROLES), ("hook", "feature", "cta"))
        self.assertNotIn("subtitle", TEXT_ROLES)

    def test_minimum_considerations_are_part_of_the_full_list(self) -> None:
        for zone in MINIMUM_CONSIDERATIONS:
            with self.subTest(zone=zone):
                self.assertIn(zone, PLACEMENT_CONSIDERATIONS)

    def test_policy_status_separates_policy_from_implementation(self) -> None:
        self.assertEqual(POLICY_STATUS, "POLICY_VALIDATED_IMPLEMENTATION_PENDING")
        self.assertEqual(PLACEMENT_IMPLEMENTATION, "NOT_IMPLEMENTED")

    def test_automatic_placement_refuses_rather_than_faking_positions(self) -> None:
        with self.assertRaises(NotImplementedError):
            assert_placement_implemented()


class TextEventTestCase(unittest.TestCase):
    def make(self, **overrides) -> TextEvent:
        values = {
            "event_id": "TEXT-01",
            "role": "hook",
            "lines": ("FILTER KERAN",),
            "motion": "fade",
            "considered_zones": FULL_ZONES,
            "emphasis_terms": (),
            "safe_area_verified": True,
        }
        values.update(overrides)
        return TextEvent(**values)  # type: ignore[arg-type]

    def test_valid_event_is_accepted(self) -> None:
        self.assertEqual(self.make().role, "hook")

    def test_forbidden_motion_is_refused(self) -> None:
        for motion in FORBIDDEN_MOTION:
            with self.subTest(motion=motion):
                with self.assertRaises(TypographyPolicyError):
                    self.make(motion=motion)

    def test_unknown_motion_is_refused(self) -> None:
        with self.assertRaises(TypographyPolicyError):
            self.make(motion="explode")

    def test_unknown_role_is_refused(self) -> None:
        with self.assertRaises(TypographyPolicyError):
            self.make(role="subtitle")

    def test_emphasis_is_limited_to_one_term(self) -> None:
        with self.assertRaises(TypographyPolicyError):
            self.make(emphasis_terms=("FILTER", "KERAN"))
        self.assertEqual(MAX_EMPHASIS_TERMS, 1)

    def test_missing_minimum_consideration_is_refused(self) -> None:
        with self.assertRaises(TypographyPolicyError):
            self.make(considered_zones=["product", "face"])

    def test_unknown_zone_is_refused(self) -> None:
        with self.assertRaises(TypographyPolicyError):
            self.make(considered_zones=FULL_ZONES + ["vibes"])

    def test_empty_lines_are_refused(self) -> None:
        with self.assertRaises(TypographyPolicyError):
            self.make(lines=())


class TypographyPlanTestCase(unittest.TestCase):
    def test_document_parses(self) -> None:
        plan = parse_typography_plan(document())
        self.assertEqual(len(plan.events), 2)
        self.assertEqual(plan.visual_direction, DEFAULT_VISUAL_DIRECTION)

    def test_plan_status_is_reported(self) -> None:
        self.assertEqual(parse_typography_plan(document()).status, POLICY_STATUS)

    def test_unverified_safe_area_is_listed(self) -> None:
        payload = document()
        payload["events"][0]["safe_area_verified"] = False
        plan = parse_typography_plan(payload)
        self.assertEqual(plan.unreleasable_events(), ("TEXT-01",))

    def test_duplicate_role_is_refused(self) -> None:
        payload = copy.deepcopy(document())
        payload["events"][1]["role"] = "hook"
        with self.assertRaises(TypographyPolicyError):
            parse_typography_plan(payload)

    def test_duplicate_event_id_is_refused(self) -> None:
        payload = copy.deepcopy(document())
        payload["events"][1]["event_id"] = "TEXT-01"
        with self.assertRaises(TypographyPolicyError):
            parse_typography_plan(payload)

    def test_other_visual_direction_is_refused(self) -> None:
        payload = copy.deepcopy(document())
        payload["visual_direction"] = "CINEMATIC_TEAL_ORANGE"
        with self.assertRaises(TypographyPolicyError):
            parse_typography_plan(payload)

    def test_empty_events_are_refused(self) -> None:
        payload = copy.deepcopy(document())
        payload["events"] = []
        with self.assertRaises(TypographyPolicyError):
            parse_typography_plan(payload)

    def test_unknown_key_is_refused(self) -> None:
        payload = copy.deepcopy(document())
        payload["font"] = "DIN Condensed"
        with self.assertRaises(TypographyPolicyError):
            parse_typography_plan(payload)

    def test_missing_key_is_refused(self) -> None:
        payload = copy.deepcopy(document())
        payload.pop("visual_direction")
        with self.assertRaises(TypographyPolicyError):
            parse_typography_plan(payload)

    def test_plan_requires_tuple_events(self) -> None:
        with self.assertRaises(TypographyPolicyError):
            TypographyPlan(DEFAULT_VISUAL_DIRECTION, [])  # type: ignore[arg-type]

    def test_schema_records_the_same_status(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["x-policy"]["status"], POLICY_STATUS)
        self.assertEqual(
            schema["x-policy"]["placement_implementation"], PLACEMENT_IMPLEMENTATION
        )
        self.assertEqual(tuple(schema["x-policy"]["forbidden_motion"]), FORBIDDEN_MOTION)


if __name__ == "__main__":
    unittest.main()
