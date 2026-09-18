"""KN-01 — ``AudioPlan`` round-trip maintenance.

The defect: ``AudioPlan.as_dict()`` emitted an ``implementation`` field that
``parse_audio_plan()`` — correctly following ``audio_plan.v0.schema.json`` — refused. A plan
therefore could not survive its own serialisation, which breaks the
Write -> Read-back -> Validate discipline.

The fix was in the serializer, not the parser: the schema declares
``additionalProperties: false`` and does not list ``implementation`` as a property, keeping
module status in its description and ``x-policy`` instead.
"""

from __future__ import annotations

import json
import unittest

from src.ai_autocut.audio_plan import (
    BGM_INTENTS,
    BGM_STRUCTURE,
    BGM_TRANSITIONS,
    IMPLEMENTATION,
    MIX_PRIORITY,
    MIX_ROLES,
    SCHEMA_VERSION,
    VO_STRATEGIES,
    AudioPlan,
    AudioPlanPolicyError,
    BgmSection,
    SoundBridge,
    VoEvent,
    WaterEvent,
    parse_audio_plan,
)


def minimal_plan() -> AudioPlan:
    return AudioPlan(
        vo_strategy="CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS",
        water_events=(
            WaterEvent(shot_id="SHOT_A", has_water_evidence=True, event_state="FLOW",
                       mix_role="EVIDENCE"),
            WaterEvent(shot_id="SHOT_B", has_water_evidence=True, event_state="IMPACT",
                       mix_role="HERO"),
            WaterEvent(shot_id="SHOT_C", has_water_evidence=False, event_state="OFF",
                       mix_role="BED"),
        ),
        bgm_structure=BGM_STRUCTURE,
        sound_bridges=(SoundBridge(from_shot_id="SHOT_A", to_shot_id="SHOT_B",
                                   continuity_reason="the water never stops"),),
    )


def extended_plan() -> AudioPlan:
    """Everything Batch 2 added, on top of everything that already existed."""

    return AudioPlan(
        vo_strategy="CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS",
        water_events=(
            WaterEvent(shot_id="SHOT_A", has_water_evidence=True, event_state="ONSET",
                       mix_role="EVIDENCE"),
            WaterEvent(shot_id="SHOT_B", has_water_evidence=True, event_state="FLOW",
                       mix_role="HERO"),
            WaterEvent(shot_id="SHOT_C", has_water_evidence=True, event_state="DECAY",
                       mix_role="BED"),
            WaterEvent(shot_id="SHOT_D", has_water_evidence=False, event_state="OFF",
                       mix_role="BED"),
        ),
        bgm_structure=BGM_STRUCTURE,
        sound_bridges=(SoundBridge(from_shot_id="SHOT_B", to_shot_id="SHOT_C",
                                   continuity_reason="the flow decays rather than stops"),),
        vo_events=(
            VoEvent(vo_id="VO1", purpose="open the idea", semantic_unit="UNIT_OPEN",
                    window_seconds=(0.15, 4.5)),
            VoEvent(vo_id="VO2", purpose="name the benefit", semantic_unit="UNIT_USE",
                    window_seconds=(12.2, 17.03)),
            VoEvent(vo_id="VO3", purpose="leave the hero to the water",
                    semantic_unit="UNIT_HERO", required=False,
                    silence_reason="the product moment is the message"),
        ),
        bgm_sections=(
            BgmSection(section="HOOK_INTRO", intent="HOLD", transition="RAMP",
                       transition_seconds=0.6),
            BgmSection(section="PRODUCT_BUILD", intent="YIELD", transition="RAMP",
                       transition_seconds=0.8),
            BgmSection(section="USAGE_LIFT", intent="RETURN", transition="RAMP",
                       transition_seconds=0.9),
            BgmSection(section="CTA_RESOLVE", intent="RETURN", transition="STEP",
                       step_reason="the final cut lands on the beat"),
        ),
    )


def cycle(plan: AudioPlan) -> dict:
    """AudioPlan -> JSON text -> dict -> AudioPlan -> dict."""

    text = json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True)
    return parse_audio_plan(json.loads(text)).as_dict()


class Test1BasicRoundTrip(unittest.TestCase):
    """Test 1 — a plain plan survives serialisation."""

    def test_a_minimal_plan_round_trips(self) -> None:
        plan = minimal_plan()
        self.assertEqual(cycle(plan), plan.as_dict())

    def test_the_serialised_document_is_json_serialisable(self) -> None:
        json.dumps(minimal_plan().as_dict())

    def test_serialisation_is_stable_across_two_cycles(self) -> None:
        once = cycle(minimal_plan())
        twice = parse_audio_plan(once).as_dict()
        self.assertEqual(once, twice)

    def test_an_empty_plan_with_no_water_events_round_trips(self) -> None:
        """The parser refuses a plan with no water events; a valid one still round-trips."""

        with self.assertRaises(AudioPlanPolicyError):
            AudioPlan(vo_strategy="CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS",
                      water_events=(), bgm_structure=BGM_STRUCTURE)


class Test2ExtendedRoundTrip(unittest.TestCase):
    """Test 2 — a plan carrying everything Batch 2 added still rounds-trips."""

    def test_an_extended_plan_round_trips(self) -> None:
        plan = extended_plan()
        self.assertEqual(cycle(plan), plan.as_dict())

    def test_voice_events_survive(self) -> None:
        rendered = cycle(extended_plan())
        self.assertEqual([e["vo_id"] for e in rendered["vo_events"]],
                         ["VO1", "VO2", "VO3"])

    def test_bgm_sections_survive(self) -> None:
        rendered = cycle(extended_plan())
        self.assertEqual([s["section"] for s in rendered["bgm_sections"]],
                         list(BGM_STRUCTURE))

    def test_semantic_audio_state_survives(self) -> None:
        rendered = cycle(extended_plan())
        self.assertEqual([e["event_state"] for e in rendered["water_events"]],
                         ["ONSET", "FLOW", "DECAY", "OFF"])

    def test_mix_role_survives(self) -> None:
        rendered = cycle(extended_plan())
        self.assertEqual([e["mix_role"] for e in rendered["water_events"]],
                         ["EVIDENCE", "HERO", "BED", "BED"])

    def test_continuous_vo_strategy_survives(self) -> None:
        rendered = cycle(extended_plan())
        self.assertEqual(rendered["vo_strategy"],
                         "CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS")

    def test_sound_bridges_survive(self) -> None:
        rendered = cycle(extended_plan())
        self.assertEqual(len(rendered["sound_bridges"]), 1)
        self.assertIn("continuity_reason", rendered["sound_bridges"][0])

    def test_a_differs_only_plan_round_trips(self) -> None:
        plan = AudioPlan(
            vo_strategy="INDEPENDENT_PER_SENTENCE",
            water_events=(WaterEvent("A", True, "FLOW", "EVIDENCE"),),
            bgm_structure=BGM_STRUCTURE,
        )
        self.assertEqual(cycle(plan)["vo_strategy"], "INDEPENDENT_PER_SENTENCE")


class Test3SemanticEquivalence(unittest.TestCase):
    """Test 3 — the round-tripped plan means the same thing, not merely parses."""

    def test_every_water_event_field_is_preserved_in_order(self) -> None:
        plan = extended_plan()
        again = parse_audio_plan(cycle(plan))
        self.assertEqual(
            [(e.shot_id, e.has_water_evidence, e.event_state, e.mix_role)
             for e in again.water_events],
            [(e.shot_id, e.has_water_evidence, e.event_state, e.mix_role)
             for e in plan.water_events],
        )

    def test_every_voice_event_field_is_preserved(self) -> None:
        plan = extended_plan()
        again = parse_audio_plan(cycle(plan))
        self.assertEqual(
            [(e.vo_id, e.purpose, e.semantic_unit, e.required, e.silence_reason,
              e.window_seconds) for e in again.vo_events],
            [(e.vo_id, e.purpose, e.semantic_unit, e.required, e.silence_reason,
              e.window_seconds) for e in plan.vo_events],
        )

    def test_every_bgm_section_field_is_preserved(self) -> None:
        plan = extended_plan()
        again = parse_audio_plan(cycle(plan))
        self.assertEqual(
            [(s.section, s.intent, s.transition, s.transition_seconds, s.step_reason)
             for s in again.bgm_sections],
            [(s.section, s.intent, s.transition, s.transition_seconds, s.step_reason)
             for s in plan.bgm_sections],
        )

    def test_derived_properties_agree_after_round_trip(self) -> None:
        plan = extended_plan()
        again = parse_audio_plan(cycle(plan))
        self.assertEqual(again.dry_shots, plan.dry_shots)
        self.assertEqual([e.vo_id for e in again.required_vo],
                         [e.vo_id for e in plan.required_vo])
        self.assertEqual([e.vo_id for e in again.silent_slots],
                         [e.vo_id for e in plan.silent_slots])

    def test_the_dry_shot_invariant_still_holds_after_round_trip(self) -> None:
        again = parse_audio_plan(cycle(extended_plan()))
        self.assertEqual(again.dry_shots, ("SHOT_D",))
        dry = [e for e in again.water_events if e.shot_id == "SHOT_D"][0]
        self.assertEqual(dry.event_state, "OFF")

    def test_the_dry_shot_invariant_is_still_enforced_after_round_trip(self) -> None:
        """A plan that violates it cannot be smuggled in through a serialised document."""

        document = extended_plan().as_dict()
        document["water_events"][3]["mix_role"] = "HERO"
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(document)

    def test_all_four_bgm_sections_are_still_required(self) -> None:
        document = extended_plan().as_dict()
        document["bgm_structure"] = ["HOOK_INTRO"]
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(document)

    def test_the_voice_window_duration_survives(self) -> None:
        again = parse_audio_plan(cycle(extended_plan()))
        first = again.vo_events[0]
        self.assertAlmostEqual(first.window_duration, 4.35, places=4)

    def test_the_silence_reason_survives(self) -> None:
        again = parse_audio_plan(cycle(extended_plan()))
        silent = again.silent_slots[0]
        self.assertEqual(silent.vo_id, "VO3")
        self.assertTrue(silent.silence_reason)


class Test4StrictParsingPreserved(unittest.TestCase):
    """Test 4 — unknown fields must still fail closed."""

    def test_an_unknown_top_level_key_is_refused(self) -> None:
        for key in ("implementation", "output_implementation", "notes", "gain"):
            with self.subTest(key=key):
                document = minimal_plan().as_dict()
                document[key] = "x"
                with self.assertRaises(AudioPlanPolicyError) as caught:
                    parse_audio_plan(document)
                self.assertIn(key, str(caught.exception))

    def test_an_unknown_water_event_key_is_refused(self) -> None:
        document = minimal_plan().as_dict()
        document["water_events"][0]["level"] = 0.5
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(document)

    def test_an_unknown_voice_event_key_is_refused(self) -> None:
        document = extended_plan().as_dict()
        document["vo_events"][0]["gain"] = 0.9
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(document)

    def test_an_unknown_bgm_section_key_is_refused(self) -> None:
        document = extended_plan().as_dict()
        document["bgm_sections"][0]["gain"] = 0.8
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(document)

    def test_a_missing_required_key_is_refused(self) -> None:
        for key in ("schema_version", "vo_strategy", "water_events", "bgm_structure",
                    "sound_bridges"):
            with self.subTest(key=key):
                document = minimal_plan().as_dict()
                del document[key]
                with self.assertRaises(AudioPlanPolicyError):
                    parse_audio_plan(document)

    def test_a_wrong_schema_version_is_refused(self) -> None:
        document = minimal_plan().as_dict()
        document["schema_version"] = "audio_plan.v1"
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(document)

    def test_an_invalid_enum_value_is_refused(self) -> None:
        document = extended_plan().as_dict()
        document["water_events"][0]["event_state"] = "FLOWING"
        with self.assertRaises(AudioPlanPolicyError):
            parse_audio_plan(document)


class SerialisedDocumentShapeTests(unittest.TestCase):
    """The document carries exactly the schema's fields, and nothing else."""

    def test_as_dict_matches_the_schema_property_set(self) -> None:
        import json as _json
        from pathlib import Path

        schema = _json.loads(
            (Path(__file__).resolve().parents[1] / "schemas" / "audio_plan"
             / "audio_plan.v0.schema.json").read_text(encoding="utf-8")
        )
        allowed = set(schema["properties"])
        self.assertEqual(set(extended_plan().as_dict()), allowed)

    def test_implementation_is_not_an_instance_field(self) -> None:
        self.assertNotIn("implementation", extended_plan().as_dict())
        self.assertNotIn("implementation", minimal_plan().as_dict())

    def test_module_status_is_still_available(self) -> None:
        """Removing it from the document must not remove the information."""

        self.assertEqual(IMPLEMENTATION, "NOT_IMPLEMENTED")

    def test_schema_version_is_unchanged(self) -> None:
        self.assertEqual(SCHEMA_VERSION, "audio_plan.v0")
        self.assertEqual(minimal_plan().as_dict()["schema_version"], "audio_plan.v0")


class UnrelatedConstantsUnchangedTests(unittest.TestCase):
    """No compatibility regression: nothing else about the contract moved."""

    def test_mix_roles_unchanged(self) -> None:
        self.assertEqual(MIX_ROLES, ("BED", "EVIDENCE", "HERO"))

    def test_mix_priority_unchanged(self) -> None:
        self.assertEqual(MIX_PRIORITY, ("VO", "EVIDENCE", "BGM"))

    def test_bgm_structure_unchanged(self) -> None:
        self.assertEqual(BGM_STRUCTURE,
                         ("HOOK_INTRO", "PRODUCT_BUILD", "USAGE_LIFT", "CTA_RESOLVE"))

    def test_vo_strategies_unchanged(self) -> None:
        self.assertEqual(set(VO_STRATEGIES),
                         {"CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS",
                          "INDEPENDENT_PER_SENTENCE"})

    def test_batch_2_intent_and_transition_vocabularies_unchanged(self) -> None:
        self.assertEqual(set(BGM_INTENTS), {"HOLD", "YIELD", "RETURN", "RAMP"})
        self.assertEqual(set(BGM_TRANSITIONS), {"RAMP", "STEP"})


if __name__ == "__main__":
    unittest.main()
