"""Tests for the additive ``audio_plan.v0`` extension: voice events and BGM intent.

Kept in a separate file so that ``tests/test_audio_plan.py`` remains evidence that the
extension did not change any existing behaviour: it still passes unmodified.
"""

from __future__ import annotations

import json
import unittest

from src.ai_autocut.audio_plan import (
    BGM_INTENTS,
    BGM_STRUCTURE,
    BGM_TRANSITIONS,
    DEFAULT_BGM_TRANSITION,
    AudioPlan,
    AudioPlanPolicyError,
    BgmSection,
    VoEvent,
    ducking_target,
    mix_rank,
    parse_audio_plan,
)


def water_event(shot_id: str, *, has_water: bool, state: str, role: str) -> dict:
    return {"shot_id": shot_id, "has_water_evidence": has_water,
            "event_state": state, "mix_role": role}


def base_document(**extra) -> dict:
    document = {
        "schema_version": "audio_plan.v0",
        "vo_strategy": "CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS",
        "water_events": [
            water_event("SHOT_A", has_water=True, state="FLOW", role="EVIDENCE"),
            water_event("SHOT_B", has_water=False, state="OFF", role="BED"),
        ],
        "bgm_structure": list(BGM_STRUCTURE),
        "sound_bridges": [],
    }
    document.update(extra)
    return document


class BackwardCompatibilityTests(unittest.TestCase):
    """A plan written before the extension must still parse and behave."""

    def test_a_plan_without_the_new_keys_still_parses(self) -> None:
        plan = parse_audio_plan(base_document())
        self.assertEqual(plan.vo_events, ())
        self.assertEqual(plan.bgm_sections, ())

    def test_the_new_fields_default_to_empty(self) -> None:
        from src.ai_autocut.audio_plan import WaterEvent

        plan = AudioPlan(
            vo_strategy="CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS",
            water_events=(WaterEvent(shot_id="SHOT_A", has_water_evidence=True,
                                     event_state="FLOW", mix_role="EVIDENCE"),),
            bgm_structure=BGM_STRUCTURE,
        )
        self.assertEqual(plan.vo_events, ())
        self.assertEqual(plan.bgm_sections, ())

    def test_the_dry_shot_law_is_unchanged(self) -> None:
        plan = parse_audio_plan(base_document())
        self.assertEqual(plan.dry_shots, ("SHOT_B",))

    def test_structural_bgm_is_still_enforced(self) -> None:
        document = base_document(bgm_structure=["HOOK_INTRO"])
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(document)

    def test_an_unknown_key_is_still_refused(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(base_document(gain=0.5))


class VoEventBindingTests(unittest.TestCase):
    """Semantic binding, not stale absolute timestamps."""

    def test_a_voice_event_binds_to_a_semantic_unit(self) -> None:
        event = VoEvent(vo_id="VO1", purpose="open the idea",
                        semantic_unit="UNIT_INSTALL")
        self.assertEqual(event.semantic_unit, "UNIT_INSTALL")
        self.assertIsNone(event.window_seconds)

    def test_a_voice_event_does_not_require_a_timestamp(self) -> None:
        parsed = parse_audio_plan(base_document(vo_events=[
            {"vo_id": "VO1", "purpose": "open", "semantic_unit": "UNIT_A",
             "required": True, "silence_reason": None, "window_seconds": None},
        ]))
        self.assertIsNone(parsed.vo_events[0].window_seconds)
        self.assertIsNone(parsed.vo_events[0].window_duration)

    def test_a_declared_window_is_optional_and_validated(self) -> None:
        event = VoEvent(vo_id="VO1", purpose="open", semantic_unit="UNIT_A",
                        window_seconds=(1.0, 4.5))
        self.assertAlmostEqual(event.window_duration, 3.5, places=4)
        with self.assertRaises(AudioPlanPolicyError):
            VoEvent(vo_id="VO1", purpose="open", semantic_unit="UNIT_A",
                    window_seconds=(4.5, 1.0))
        with self.assertRaises(AudioPlanPolicyError):
            VoEvent(vo_id="VO1", purpose="open", semantic_unit="UNIT_A",
                    window_seconds=(-1.0, 4.5))

    def test_an_empty_semantic_unit_is_refused(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            VoEvent(vo_id="VO1", purpose="open", semantic_unit="")

    def test_a_purpose_is_required(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            VoEvent(vo_id="VO1", purpose="  ", semantic_unit="UNIT_A")

    def test_duplicate_voice_ids_are_refused(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(base_document(vo_events=[
                {"vo_id": "VO1", "purpose": "a", "semantic_unit": "U1",
                 "required": True, "silence_reason": None, "window_seconds": None},
                {"vo_id": "VO1", "purpose": "b", "semantic_unit": "U2",
                 "required": True, "silence_reason": None, "window_seconds": None},
            ]))

    def test_required_and_silent_slots_are_separable(self) -> None:
        plan = parse_audio_plan(base_document(vo_events=[
            {"vo_id": "VO1", "purpose": "open", "semantic_unit": "U1",
             "required": True, "silence_reason": None, "window_seconds": None},
            {"vo_id": "VO2", "purpose": "let the water speak",
             "semantic_unit": "U2", "required": False,
             "silence_reason": "the product moment is the message",
             "window_seconds": None},
        ]))
        self.assertEqual([e.vo_id for e in plan.required_vo], ["VO1"])
        self.assertEqual([e.vo_id for e in plan.silent_slots], ["VO2"])


class SilenceMustBeJustifiedTests(unittest.TestCase):
    """A hero may be silent, but not by accident."""

    def test_a_silent_slot_must_state_its_reason(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            VoEvent(vo_id="VO1", purpose="hero", semantic_unit="U1", required=False)

    def test_a_blank_silence_reason_is_refused(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            VoEvent(vo_id="VO1", purpose="hero", semantic_unit="U1", required=False,
                    silence_reason="   ")

    def test_a_silent_slot_with_a_reason_is_accepted(self) -> None:
        event = VoEvent(vo_id="VO1", purpose="hero", semantic_unit="U1", required=False,
                        silence_reason="water carries this moment")
        self.assertFalse(event.required)

    def test_a_required_slot_cannot_also_declare_silence(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            VoEvent(vo_id="VO1", purpose="open", semantic_unit="U1", required=True,
                    silence_reason="but also silent")

    def test_hero_is_not_hardcoded_to_silence(self) -> None:
        """HERO may carry voice. Only the budget decides."""

        speaking_hero = VoEvent(vo_id="VO1", purpose="hero with voice",
                                semantic_unit="U1", required=True)
        silent_hero = VoEvent(vo_id="VO2", purpose="hero without voice",
                              semantic_unit="U2", required=False,
                              silence_reason="water leads")
        self.assertTrue(speaking_hero.required)
        self.assertFalse(silent_hero.required)


class BgmIntentTests(unittest.TestCase):
    """The contract carries intent, never a level."""

    def test_intents_are_declared(self) -> None:
        for intent in ("HOLD", "YIELD", "RETURN", "RAMP"):
            with self.subTest(intent=intent):
                self.assertIn(intent, BGM_INTENTS)

    def test_transitions_are_declared(self) -> None:
        self.assertEqual(set(BGM_TRANSITIONS), {"RAMP", "STEP"})

    def test_the_default_transition_is_a_ramp(self) -> None:
        self.assertEqual(DEFAULT_BGM_TRANSITION, "RAMP")

    def test_a_section_carries_no_gain_field(self) -> None:
        section = BgmSection(section="HOOK_INTRO", intent="HOLD", transition="RAMP",
                             transition_seconds=0.8)
        payload = section.as_dict()
        self.assertNotIn("gain", payload)
        self.assertNotIn("level", payload)
        self.assertNotIn("db", payload)
        self.assertEqual(set(payload),
                         {"section", "intent", "transition", "transition_seconds",
                          "step_reason"})

    def test_a_ramp_must_state_its_duration(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            BgmSection(section="HOOK_INTRO", intent="RAMP", transition="RAMP",
                       transition_seconds=0.0)

    def test_a_ramped_section_is_accepted(self) -> None:
        section = BgmSection(section="USAGE_LIFT", intent="YIELD", transition="RAMP",
                             transition_seconds=0.9)
        self.assertEqual(section.transition, "RAMP")
        self.assertAlmostEqual(section.transition_seconds, 0.9, places=3)

    def test_a_step_must_state_why(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            BgmSection(section="CTA_RESOLVE", intent="RETURN", transition="STEP")
        with self.assertRaises(AudioPlanPolicyError):
            BgmSection(section="CTA_RESOLVE", intent="RETURN", transition="STEP",
                       step_reason="   ")

    def test_an_justified_step_is_accepted(self) -> None:
        section = BgmSection(section="CTA_RESOLVE", intent="RETURN", transition="STEP",
                             step_reason="the cut lands on the beat and a ramp would smear it")
        self.assertEqual(section.transition, "STEP")
        self.assertTrue(section.step_reason)

    def test_a_ramp_does_not_carry_a_step_reason(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            BgmSection(section="HOOK_INTRO", intent="HOLD", transition="RAMP",
                       transition_seconds=0.5, step_reason="not applicable")

    def test_the_section_must_be_a_real_structure_value(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            BgmSection(section="SOMEWHERE_ELSE", intent="HOLD", transition="RAMP",
                       transition_seconds=0.5)

    def test_the_intent_must_be_declared(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            BgmSection(section="HOOK_INTRO", intent="LOUDER", transition="RAMP",
                       transition_seconds=0.5)

    def test_a_negative_transition_is_refused(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            BgmSection(section="HOOK_INTRO", intent="HOLD", transition="STEP",
                       transition_seconds=-1.0, step_reason="x")

    def test_a_section_described_twice_is_refused(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(base_document(bgm_sections=[
                {"section": "HOOK_INTRO", "intent": "HOLD", "transition": "RAMP",
                 "transition_seconds": 0.5, "step_reason": None},
                {"section": "HOOK_INTRO", "intent": "YIELD", "transition": "RAMP",
                 "transition_seconds": 0.5, "step_reason": None},
            ]))

    def test_sections_round_trip(self) -> None:
        plan = parse_audio_plan(base_document(bgm_sections=[
            {"section": "HOOK_INTRO", "intent": "HOLD", "transition": "RAMP",
             "transition_seconds": 0.6, "step_reason": None},
            {"section": "USAGE_LIFT", "intent": "YIELD", "transition": "RAMP",
             "transition_seconds": 0.9, "step_reason": None},
        ]))
        self.assertEqual([s.section for s in plan.bgm_sections],
                         ["HOOK_INTRO", "USAGE_LIFT"])
        self.assertEqual([s.intent for s in plan.bgm_sections], ["HOLD", "YIELD"])


class RoundTripTests(unittest.TestCase):
    def test_a_full_plan_round_trips_through_json(self) -> None:
        document = base_document(
            vo_events=[
                {"vo_id": "VO1", "purpose": "open", "semantic_unit": "U1",
                 "required": True, "silence_reason": None, "window_seconds": [0.1, 3.2]},
                {"vo_id": "VO2", "purpose": "hero", "semantic_unit": "U2",
                 "required": False, "silence_reason": "water leads",
                 "window_seconds": None},
            ],
            bgm_sections=[
                {"section": "HOOK_INTRO", "intent": "HOLD", "transition": "RAMP",
                 "transition_seconds": 0.6, "step_reason": None},
            ],
        )
        plan = parse_audio_plan(json.loads(json.dumps(document)))
        rendered = plan.as_dict()
        again = parse_audio_plan(json.loads(json.dumps(rendered)))
        self.assertEqual([e.vo_id for e in again.vo_events], ["VO1", "VO2"])
        self.assertEqual([s.section for s in again.bgm_sections], ["HOOK_INTRO"])

    def test_as_dict_includes_the_new_groups(self) -> None:
        plan = parse_audio_plan(base_document())
        payload = plan.as_dict()
        self.assertIn("vo_events", payload)
        self.assertIn("bgm_sections", payload)

    def test_round_trip_never_emits_a_field_the_parser_rejects(self) -> None:
        """KN-01, closed.

        This test previously asserted the opposite — that a plan could NOT be fed back
        through its own parser — which froze a known defect in place. It now fails if the
        asymmetry ever returns.
        """

        plan = parse_audio_plan(base_document())
        rendered = plan.as_dict()
        self.assertNotIn("implementation", rendered)
        self.assertEqual(parse_audio_plan(rendered).as_dict(), rendered)

    def test_an_unsupported_voice_key_is_refused(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(base_document(vo_events=[
                {"vo_id": "VO1", "purpose": "a", "semantic_unit": "U1",
                 "gain": 0.4},
            ]))


class MixLawUnchangedTests(unittest.TestCase):
    """The existing mix law is untouched by the extension."""

    def test_voice_still_has_the_highest_priority(self) -> None:
        self.assertEqual(mix_rank("VO"), 0)
        self.assertLess(mix_rank("VO"), mix_rank("EVIDENCE"))
        self.assertLess(mix_rank("EVIDENCE"), mix_rank("BGM"))

    def test_every_role_still_ducks_under_voice(self) -> None:
        for role in ("VO", "EVIDENCE", "BGM"):
            with self.subTest(role=role):
                self.assertEqual(ducking_target(role), "VO")

    def test_hero_remains_a_first_class_mix_role(self) -> None:
        event = parse_audio_plan(base_document(water_events=[
            water_event("SHOT_A", has_water=True, state="FLOW", role="HERO"),
            water_event("SHOT_B", has_water=False, state="OFF", role="BED"),
        ]))
        self.assertEqual(event.water_events[0].mix_role, "HERO")

    def test_a_dry_shot_cannot_take_a_hero_role(self) -> None:
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(base_document(water_events=[
                water_event("SHOT_A", has_water=False, state="OFF", role="HERO"),
            ]))


if __name__ == "__main__":
    unittest.main()
