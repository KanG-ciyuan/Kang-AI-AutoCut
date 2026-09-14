from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from src.ai_autocut.audio_plan import (
    BGM_STRUCTURE,
    EVENT_STATES,
    GOLD_REFERENCE_IS_UNIVERSAL,
    GOLD_REFERENCE_LOUDNESS,
    IMPLEMENTATION,
    MIX_PRIORITY,
    MIX_ROLES,
    VO_STRATEGIES,
    AudioPlan,
    AudioPlanPolicyError,
    SoundBridge,
    WaterEvent,
    assert_creative_pass_before_mastering,
    assert_targeted_repair,
    ducking_target,
    mix_rank,
    parse_audio_plan,
)


REPO_ROOT = Path(__file__).parents[1]
SCHEMA = REPO_ROOT / "schemas" / "audio_plan" / "audio_plan.v0.schema.json"


def document() -> dict:
    return {
        "schema_version": "audio_plan.v0",
        "vo_strategy": "CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS",
        "water_events": [
            {
                "shot_id": "S01",
                "has_water_evidence": True,
                "event_state": "FLOW",
                "mix_role": "EVIDENCE",
            },
            {
                "shot_id": "S02",
                "has_water_evidence": False,
                "event_state": "OFF",
                "mix_role": "BED",
            },
            {
                "shot_id": "S03",
                "has_water_evidence": True,
                "event_state": "IMPACT",
                "mix_role": "HERO",
            },
        ],
        "bgm_structure": list(BGM_STRUCTURE),
        "sound_bridges": [],
    }


class AudioPlanTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = parse_audio_plan(document())

    def test_event_state_and_mix_role_are_separate_dimensions(self) -> None:
        self.assertEqual(set(EVENT_STATES) & set(MIX_ROLES), set())

    def test_default_voice_strategy_is_one_continuous_performance(self) -> None:
        self.assertEqual(
            self.plan.vo_strategy, "CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS"
        )
        self.assertEqual(
            VO_STRATEGIES[0], "CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS"
        )

    def test_mix_priority_puts_voice_first_and_bgm_last(self) -> None:
        self.assertEqual(MIX_PRIORITY, ("VO", "EVIDENCE", "BGM"))
        self.assertLess(mix_rank("VO"), mix_rank("BGM"))

    def test_voice_wins_a_mix_conflict(self) -> None:
        self.assertEqual(ducking_target("VO"), "VO")
        self.assertEqual(ducking_target("BGM"), "VO")

    def test_dry_shots_are_recorded(self) -> None:
        self.assertEqual(self.plan.dry_shots, ("S02",))

    def test_bgm_must_be_structurally_edited(self) -> None:
        self.assertEqual(
            self.plan.bgm_structure,
            ("HOOK_INTRO", "PRODUCT_BUILD", "USAGE_LIFT", "CTA_RESOLVE"),
        )

    def test_gold_loudness_is_a_reference_not_a_law(self) -> None:
        self.assertEqual(GOLD_REFERENCE_LOUDNESS["integrated_lufs"], -16.0)
        self.assertEqual(GOLD_REFERENCE_LOUDNESS["true_peak_dbtp"], -1.4)
        self.assertFalse(GOLD_REFERENCE_IS_UNIVERSAL)

    def test_implementation_status_is_declared(self) -> None:
        self.assertEqual(IMPLEMENTATION, "NOT_IMPLEMENTED")

    def test_schema_records_the_same_policy(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(tuple(schema["x-policy"]["mix_priority"]), MIX_PRIORITY)
        self.assertFalse(schema["x-policy"]["gold_reference_is_universal"])
        self.assertTrue(schema["x-policy"]["event_state_is_not_mix_role"])


class DryShotRuleTestCase(unittest.TestCase):
    """A dry visual shot never carries water sound."""

    def test_non_off_state_without_water_evidence_is_refused(self) -> None:
        for state in ("ONSET", "FLOW", "IMPACT", "DECAY"):
            with self.subTest(state=state):
                with self.assertRaises(AudioPlanPolicyError):
                    WaterEvent("S02", False, state, "BED")

    def test_off_state_is_required_for_a_dry_shot(self) -> None:
        self.assertEqual(WaterEvent("S02", False, "OFF", "BED").event_state, "OFF")

    def test_water_evidence_may_carry_any_state(self) -> None:
        for state in EVENT_STATES:
            with self.subTest(state=state):
                self.assertEqual(WaterEvent("S01", True, state, "BED").event_state, state)

    def test_inactive_event_cannot_lead_the_mix(self) -> None:
        # Nothing is happening, so nothing may lead the mix.
        with self.assertRaises(AudioPlanPolicyError):
            WaterEvent("S01", True, "OFF", "HERO")
        with self.assertRaises(AudioPlanPolicyError):
            WaterEvent("S01", True, "OFF", "EVIDENCE")

    def test_a_decaying_event_is_still_active(self) -> None:
        # DECAY is not silence: the sound is still present while it fades.
        self.assertEqual(
            WaterEvent("S01", True, "DECAY", "EVIDENCE").mix_role, "EVIDENCE"
        )

    def test_unknown_state_or_role_is_refused(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            WaterEvent("S01", True, "SPLASH", "BED")
        with self.assertRaises(AudioPlanPolicyError):
            WaterEvent("S01", True, "FLOW", "LOUD")


class SoundBridgeTestCase(unittest.TestCase):
    def test_bridge_requires_a_continuity_reason(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            SoundBridge("S01", "S02", "   ")

    def test_bridge_with_a_reason_is_accepted(self) -> None:
        bridge = SoundBridge("S01", "S02", "the same water stream continues across the cut")
        self.assertEqual(bridge.from_shot_id, "S01")

    def test_bridge_must_join_two_different_shots(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            SoundBridge("S01", "S01", "same shot")

    def test_bridge_must_reference_declared_shots(self) -> None:
        payload = document()
        payload["sound_bridges"] = [
            {
                "from_shot_id": "S01",
                "to_shot_id": "S99",
                "continuity_reason": "not declared",
            }
        ]
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(payload)


class StageOrderTestCase(unittest.TestCase):
    def test_mastering_requires_a_creative_pass(self) -> None:
        assert_creative_pass_before_mastering(True)

    def test_mastering_before_a_creative_pass_is_refused(self) -> None:
        for value in (False, None, "yes", 1):
            with self.subTest(value=value):
                with self.assertRaises(AudioPlanPolicyError):
                    assert_creative_pass_before_mastering(value)


class TargetedRepairTestCase(unittest.TestCase):
    def test_scoped_repair_is_accepted(self) -> None:
        self.assertEqual(
            assert_targeted_repair(scope_shots=["S02"]), ("S02",)
        )

    def test_unscoped_repair_is_refused(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            assert_targeted_repair(scope_shots=[])

    def test_regeneration_is_refused(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            assert_targeted_repair(scope_shots=["S02"], regenerate=True)


class AudioPlanParsingTestCase(unittest.TestCase):
    def reject(self, mutate) -> None:
        payload = copy.deepcopy(document())
        mutate(payload)
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(payload)

    def test_bgm_single_track_is_refused(self) -> None:
        self.reject(lambda d: d.__setitem__("bgm_structure", ["BGM"]))

    def test_bgm_out_of_order_is_refused(self) -> None:
        self.reject(
            lambda d: d.__setitem__(
                "bgm_structure",
                ["PRODUCT_BUILD", "HOOK_INTRO", "USAGE_LIFT", "CTA_RESOLVE"],
            )
        )

    def test_unknown_key_is_refused(self) -> None:
        self.reject(lambda d: d.__setitem__("sfx_provider", "x"))

    def test_missing_key_is_refused(self) -> None:
        self.reject(lambda d: d.pop("sound_bridges"))

    def test_duplicate_shot_is_refused(self) -> None:
        self.reject(lambda d: d["water_events"].append(copy.deepcopy(d["water_events"][0])))

    def test_empty_water_events_are_refused(self) -> None:
        self.reject(lambda d: d.__setitem__("water_events", []))

    def test_per_sentence_voice_strategy_is_representable_but_not_default(self) -> None:
        payload = document()
        payload["vo_strategy"] = "INDEPENDENT_PER_SENTENCE"
        plan = parse_audio_plan(payload)
        self.assertNotEqual(plan.vo_strategy, VO_STRATEGIES[0])

    def test_plan_requires_tuple_events(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            AudioPlan(
                VO_STRATEGIES[0],
                [WaterEvent("S01", True, "FLOW", "BED")],  # type: ignore[arg-type]
                BGM_STRUCTURE,
            )


if __name__ == "__main__":
    unittest.main()
