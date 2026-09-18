"""C-02 regression — commercial narration coverage.

The ten frozen cases from the Gate F.3 specification. Each one pins a behaviour that the
Cushion Puff blind run proved was wrong or that the correction must not break.

The fixtures here are **test evidence**. No Cushion Puff or Filter value reaches the production
module; the anti-overfit scan checks that separately.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.ai_autocut.audio_plan import VoEvent, parse_audio_plan, BGM_STRUCTURE
from src.ai_autocut.narration_coverage import (
    CARRYING_ROLES,
    JUSTIFIED_SILENCE_REASONS,
    REJECTED_RULE,
    REVIEW_DIMENSION,
    VO_ROLES,
    WEAK_SILENCE_REASONS,
    CommercialUnit,
    CoverageReport,
    NarrationCoverageError,
    assess_narration_coverage,
    summary,
)
from src.ai_autocut.review import REVIEWER_DIMENSIONS
from src.ai_autocut.spoken_duration import (
    RateObservation,
    check_window,
    resolve_rate,
)

MODULE = Path(__file__).resolve().parents[1] / "src" / "ai_autocut" / "narration_coverage.py"


def executable_source() -> str:
    """Docstrings, comments AND string literals removed before any scan.

    String literals have to go too: the module contains a note saying there is no VO
    percentage, and a scan that flags its own denial is measuring nothing.
    """

    text = MODULE.read_text(encoding="utf-8")
    text = re.sub(r'""".*?"""', "", text, flags=re.S)
    text = re.sub(r'"[^"\n]*"', '""', text)
    text = re.sub(r"'[^'\n]*'", "''", text)
    return "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("#"))


def spoken(unit_id: str, role: str, *, start=0.0, end=2.0, title=False, adds=True):
    return CommercialUnit(
        unit_id=unit_id, start_seconds=start, end_seconds=end,
        visual_self_explanatory=True, carries_new_commercial_information=True,
        has_title=title,
        vo=VoEvent(vo_id=f"VO_{unit_id}", purpose=role, semantic_unit=unit_id),
        vo_adds_function_beyond_title=adds,
    )


def silent(unit_id: str, reason: str | None, *, start=0.0, end=2.0, title=False,
           self_explanatory=True, new_info=True, explanation_supported=True):
    return CommercialUnit(
        unit_id=unit_id, start_seconds=start, end_seconds=end,
        visual_self_explanatory=self_explanatory,
        carries_new_commercial_information=new_info, has_title=title,
        vo=VoEvent(vo_id=f"S_{unit_id}", purpose="silent slot", semantic_unit=unit_id,
                   required=False, silence_reason=reason),
        explanation_supported=explanation_supported,
    )


def healthy_plan() -> list[CommercialUnit]:
    """A piece where every channel is doing its own job."""

    return [
        spoken("U1", "HOOK", start=0.0, end=2.0),
        spoken("U2", "DEMONSTRATION_EXPLANATION", start=2.0, end=4.0),
        spoken("U3", "SELLING_POINT_EXPANSION", start=4.0, end=6.0, title=True),
        silent("U4", "HERO_VISUAL_CARRIES_MESSAGE", start=6.0, end=8.0,
               self_explanatory=False, new_info=False),
        spoken("U5", "CTA", start=8.0, end=10.0),
    ]


class C2R1TitleDoesNotSuppressVo(unittest.TestCase):
    """C2-R1 — a Title does not automatically suppress VO."""

    def test_silence_justified_only_by_a_title_fails(self) -> None:
        units = healthy_plan()
        units[3] = silent("U4", "TITLE_ALREADY_EXISTS", start=6.0, end=8.0, title=True)
        report = assess_narration_coverage(units)
        self.assertEqual(report.verdict, "FAIL")
        self.assertTrue(any(WEAK_SILENCE_REASONS[0] in f.detail or
                            "Title existing" in f.detail for f in report.findings))

    def test_a_title_produces_a_finding_not_a_crash(self) -> None:
        report = assess_narration_coverage([
            spoken("U1", "HOOK"), silent("U2", "TITLE_ALREADY_EXISTS", start=2.0, end=4.0,
                                         title=True), spoken("U3", "CTA", start=4.0, end=6.0)])
        self.assertIsInstance(report, CoverageReport)

    def test_the_weak_reason_is_declared_and_is_not_a_justified_one(self) -> None:
        self.assertIn("TITLE_ALREADY_EXISTS", WEAK_SILENCE_REASONS)
        self.assertNotIn("TITLE_ALREADY_EXISTS", JUSTIFIED_SILENCE_REASONS)

    def test_the_module_has_no_rule_suppressing_vo_when_a_title_exists(self) -> None:
        code = executable_source()
        for forbidden in ("if unit.has_title:\n            return None",
                          "suppress", "TITLE_SUPPRESSES"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)


class C2R2ChannelsCoexist(unittest.TestCase):
    """C2-R2 — Visual + Title + VO may coexist when their functions differ."""

    def test_visual_title_and_voice_together_pass(self) -> None:
        report = assess_narration_coverage(healthy_plan())
        self.assertNotEqual(report.verdict, "FAIL")

    def test_a_unit_may_carry_a_title_and_a_voice_that_adds_function(self) -> None:
        report = assess_narration_coverage([
            spoken("U1", "SELLING_POINT_EXPANSION", title=True, adds=True),
            spoken("U2", "CTA", start=2.0, end=4.0)])
        self.assertNotEqual(report.verdict, "FAIL")

    def test_the_unit_model_exposes_all_channels_independently(self) -> None:
        unit = spoken("U1", "HOOK", title=True)
        self.assertTrue(unit.has_title)
        self.assertTrue(unit.has_vo)
        self.assertTrue(unit.visual_self_explanatory)


class C2R3RedundantVoiceRejected(unittest.TestCase):
    """C2-R3 — VO that merely repeats a Title with no added function is rejected."""

    def test_a_voice_that_restates_its_title_fails(self) -> None:
        report = assess_narration_coverage([
            spoken("U1", "HOOK"),
            spoken("U2", "SELLING_POINT_EXPANSION", start=2.0, end=4.0, title=True,
                   adds=False),
            spoken("U3", "CTA", start=4.0, end=6.0)])
        self.assertEqual(report.verdict, "FAIL")
        self.assertTrue(any("duplicates the Title" in f.detail for f in report.findings))

    def test_the_check_only_applies_when_a_title_is_present(self) -> None:
        report = assess_narration_coverage([
            spoken("U1", "HOOK", adds=False),
            spoken("U2", "CTA", start=2.0, end=4.0)])
        self.assertFalse(any("duplicates the Title" in f.detail for f in report.findings))

    def test_a_voice_with_no_role_fails(self) -> None:
        report = assess_narration_coverage([
            spoken("U1", "MAKE_IT_SOUND_NICE"),
            spoken("U2", "CTA", start=2.0, end=4.0)])
        self.assertEqual(report.verdict, "FAIL")


class C2R4HeroSilencePasses(unittest.TestCase):
    """C2-R4 — a Hero silence passes when explicitly justified."""

    def test_every_justified_reason_is_accepted(self) -> None:
        for reason in JUSTIFIED_SILENCE_REASONS:
            with self.subTest(reason=reason):
                report = assess_narration_coverage([
                    spoken("U1", "HOOK"),
                    silent("U2", reason, start=2.0, end=4.0,
                           self_explanatory=False, new_info=False),
                    spoken("U3", "CTA", start=4.0, end=6.0)])
                self.assertNotEqual(report.verdict, "FAIL", reason)

    def test_a_hero_silence_is_reported_as_justified(self) -> None:
        report = assess_narration_coverage(healthy_plan())
        payload = summary(report)
        self.assertIn("U4", payload["justified_silence"])

    def test_silence_is_a_first_class_decision_not_an_absence(self) -> None:
        self.assertEqual(silent("U1", "HERO_VISUAL_CARRIES_MESSAGE").is_silent, True)
        self.assertEqual(silent("U1", "HERO_VISUAL_CARRIES_MESSAGE").silence_reason,
                         "HERO_VISUAL_CARRIES_MESSAGE")

    def test_silence_with_no_reason_at_all_fails(self) -> None:
        report = assess_narration_coverage([
            spoken("U1", "HOOK"),
            CommercialUnit("U2", 2.0, 4.0, True, True, False),
            spoken("U3", "CTA", start=4.0, end=6.0)])
        self.assertEqual(report.verdict, "FAIL")


class C2R5DeadZoneDetection(unittest.TestCase):
    """C2-R5 — an unjustified commercial narrative dead zone is warned."""

    def test_a_dead_zone_fails(self) -> None:
        report = assess_narration_coverage([
            spoken("U1", "HOOK"),
            silent("U2", "SOMETHING_VAGUE", start=2.0, end=4.0,
                   self_explanatory=False, new_info=False),
            silent("U3", "ALSO_VAGUE", start=4.0, end=6.0,
                   self_explanatory=False, new_info=False),
            spoken("U4", "CTA", start=6.0, end=8.0)])
        self.assertEqual(report.verdict, "FAIL")
        self.assertTrue(any("dead zone" in f.detail for f in report.findings))

    def test_all_four_conditions_are_required(self) -> None:
        """A silent stretch that is justified is not a dead zone."""

        report = assess_narration_coverage([
            spoken("U1", "HOOK"),
            silent("U2", "BGM_TRANSITION", start=2.0, end=4.0,
                   self_explanatory=False, new_info=False),
            spoken("U3", "CTA", start=4.0, end=6.0)])
        self.assertFalse(any("dead zone" in f.detail for f in report.findings))

    def test_a_self_explanatory_silent_stretch_is_not_a_dead_zone(self) -> None:
        report = assess_narration_coverage([
            spoken("U1", "HOOK"),
            silent("U2", "NOT_IN_VOCABULARY", start=2.0, end=4.0,
                   self_explanatory=True, new_info=True),
            spoken("U3", "CTA", start=4.0, end=6.0)])
        self.assertFalse(any("dead zone" in f.detail for f in report.findings))

    def test_no_seconds_threshold_exists_anywhere_in_the_module(self) -> None:
        code = executable_source()
        for forbidden in ("MAX_SILENCE", "MIN_SILENCE", "DEAD_ZONE_SECONDS",
                          "silence_threshold", "dead_zone_seconds"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)


class C2R6EvidenceSafety(unittest.TestCase):
    """C2-R6 — more narration cannot introduce unsupported claims."""

    def test_an_unsupported_explanation_gap_is_reported_not_filled(self) -> None:
        report = assess_narration_coverage([
            spoken("U1", "HOOK"),
            silent("U2", "NOT_JUSTIFIED", start=2.0, end=4.0, explanation_supported=False),
            spoken("U3", "CTA", start=4.0, end=6.0)])
        self.assertTrue(any("do not support" in f.detail for f in report.findings))

    def test_the_module_never_emits_copy(self) -> None:
        """It can say a unit needs an explanation. It can never supply one."""

        report = assess_narration_coverage(healthy_plan())
        for finding in report.findings:
            with self.subTest(detail=finding.detail[:40]):
                self.assertIsInstance(finding.detail, str)
        for unit in report.units:
            self.assertFalse(hasattr(unit, "text"))
            self.assertFalse(hasattr(unit, "copy"))
            self.assertFalse(hasattr(unit, "line"))

    def test_the_module_contains_no_claim_language(self) -> None:
        code = executable_source()
        for claim in ("absorbs", "flawless", "antibacterial", "hypoallergenic",
                      "waterproof", "reusable", "saves", "better than"):
            with self.subTest(claim=claim):
                self.assertNotIn(claim, code.lower())

    def test_the_output_contains_no_verdict_beyond_the_review_severities(self) -> None:
        payload = summary(assess_narration_coverage(healthy_plan()))
        self.assertIn(payload["verdict"], ("PASS", "WARNING", "FAIL"))
        for severity in payload["findings_by_severity"]:
            self.assertIn(severity, ("PASS", "WEAK", "FAIL", "CRITICAL"))


class C2R7SpokenDurationPreserved(unittest.TestCase):
    """C2-R7 — spoken duration validation still runs before paid VO."""

    def test_the_validator_still_flags_an_overflow(self) -> None:
        rate = resolve_rate("id", observations=[
            RateObservation(language="id", words_per_second=2.76, samples=1,
                            evidence="test fixture")])
        check = check_window(
            [("VO1", "This is a deliberately long line that cannot possibly fit the window")],
            available_window=1.0, rate=rate)
        self.assertEqual(check.risk, "OVERFLOW")

    def test_a_voice_plan_still_round_trips_through_the_audio_contract(self) -> None:
        document = {
            "schema_version": "audio_plan.v0",
            "vo_strategy": "CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS",
            "water_events": [{"shot_id": "S1", "has_water_evidence": False,
                              "event_state": "OFF", "mix_role": "BED"}],
            "bgm_structure": list(BGM_STRUCTURE),
            "sound_bridges": [],
            "vo_events": [{"vo_id": "VO1", "purpose": "HOOK", "semantic_unit": "U1",
                           "required": True, "silence_reason": None,
                           "window_seconds": [0.0, 2.0]},
                          {"vo_id": "S2", "purpose": "hero slot", "semantic_unit": "U2",
                           "required": False,
                           "silence_reason": "HERO_VISUAL_CARRIES_MESSAGE",
                           "window_seconds": None}],
        }
        plan = parse_audio_plan(document)
        self.assertEqual(len(plan.required_vo), 1)
        self.assertEqual(len(plan.silent_slots), 1)

    def test_the_audio_contract_still_requires_a_silence_reason(self) -> None:
        """The field that would have caught the Cushion Puff defect already existed."""

        with self.assertRaises(Exception):
            VoEvent(vo_id="S1", purpose="silent", semantic_unit="U1", required=False)


class C2R8ProgressionNotCaptions(unittest.TestCase):
    """C2-R8 — narration forms a coherent progression, not isolated captions."""

    def test_a_piece_whose_only_voice_is_a_cta_fails(self) -> None:
        report = assess_narration_coverage([
            spoken("U1", "CTA"),
            spoken("U2", "CTA", start=2.0, end=4.0)])
        self.assertEqual(report.verdict, "FAIL")
        self.assertTrue(any("does not carry the selling narrative" in f.detail
                            for f in report.findings))

    def test_a_progression_with_carrying_roles_passes_the_coverage_check(self) -> None:
        report = assess_narration_coverage(healthy_plan())
        self.assertFalse(any("does not carry the selling narrative" in f.detail
                             for f in report.findings))

    def test_a_missing_cta_is_flagged(self) -> None:
        report = assess_narration_coverage([spoken("U1", "HOOK")])
        self.assertTrue(any("call to action" in f.detail for f in report.findings))

    def test_the_carrying_roles_are_a_strict_subset_of_the_vocabulary(self) -> None:
        self.assertTrue(set(CARRYING_ROLES) < set(VO_ROLES))
        self.assertNotIn("CTA", CARRYING_ROLES)

    def test_the_role_vocabulary_is_small(self) -> None:
        self.assertEqual(len(VO_ROLES), 7)


class C2R9NoFixedPercentage(unittest.TestCase):
    """C2-R9 — no fixed VO percentage is required."""

    def test_the_module_declares_no_percentage_or_ratio(self) -> None:
        code = executable_source()
        for forbidden in ("PERCENT", "percentage", "VO_RATIO", "COVERAGE_TARGET",
                          "MIN_VO", "TARGET_DENSITY"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)

    def test_a_mostly_silent_piece_can_pass(self) -> None:
        report = assess_narration_coverage([
            spoken("U1", "HOOK", start=0.0, end=2.0),
            silent("U2", "HERO_VISUAL_CARRIES_MESSAGE", start=2.0, end=4.0,
                   self_explanatory=False, new_info=False),
            silent("U3", "BGM_TRANSITION", start=4.0, end=6.0,
                   self_explanatory=False, new_info=False),
            silent("U4", "DELIBERATE_PRE_CTA_CONTRAST", start=6.0, end=8.0,
                   self_explanatory=False, new_info=False),
            spoken("U5", "CTA", start=8.0, end=10.0)])
        self.assertNotEqual(report.verdict, "FAIL")
        payload = summary(report)
        self.assertEqual(payload["silent"], 3)
        self.assertEqual(payload["spoken"], 2)

    def test_a_majority_silent_piece_is_not_penalised_for_being_silent(self) -> None:
        report = assess_narration_coverage([
            silent("U1", "HERO_VISUAL_CARRIES_MESSAGE", start=0.0, end=6.0,
                   self_explanatory=False, new_info=False),
            spoken("U2", "HOOK", start=6.0, end=8.0),
            spoken("U3", "CTA", start=8.0, end=10.0)])
        self.assertNotEqual(report.verdict, "FAIL")

    def test_the_summary_reports_counts_not_a_score(self) -> None:
        payload = summary(assess_narration_coverage(healthy_plan()))
        self.assertIn("spoken", payload)
        self.assertIn("silent", payload)
        for forbidden in ("score", "percentage", "ratio", "coverage_percent"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, payload)


class C2R10OneChannelRuleRejected(unittest.TestCase):
    """C2-R10 — no "one channel per unit" rule remains."""

    def test_the_rejected_rule_is_named_as_rejected(self) -> None:
        self.assertEqual(REJECTED_RULE, "ONE_INFORMATION_CHANNEL_PER_UNIT")

    def test_the_module_does_not_enforce_it(self) -> None:
        """The constant exists to NAME the rejected rule. It must never appear in a branch."""

        code = executable_source()
        uses = [line.strip() for line in code.splitlines()
                if REJECTED_RULE in line and not line.strip().startswith("REJECTED_RULE =")]
        self.assertEqual(uses, [], "the rejected rule is referenced in logic: %s" % uses)

    def test_the_rejected_rule_is_named_exactly_once_as_a_constant(self) -> None:
        """Counted in the raw source: executable_source() strips string literals, and the
        constant's value IS a string literal."""

        raw = MODULE.read_text(encoding="utf-8")
        self.assertEqual(raw.count(REJECTED_RULE), 1)

    def test_a_unit_with_every_channel_present_is_acceptable(self) -> None:
        report = assess_narration_coverage([
            spoken("U1", "HOOK", title=True, adds=True),
            spoken("U2", "CTA", start=2.0, end=4.0, title=True, adds=True)])
        self.assertNotEqual(report.verdict, "FAIL")

    def test_no_new_review_dimension_was_added(self) -> None:
        self.assertIn(REVIEW_DIMENSION, REVIEWER_DIMENSIONS)
        self.assertEqual(len(REVIEWER_DIMENSIONS), 13)

    def test_findings_use_the_existing_review_dimension(self) -> None:
        report = assess_narration_coverage([
            silent("U1", "TITLE_ALREADY_EXISTS"),
            spoken("U2", "CTA", start=2.0, end=4.0)])
        for finding in report.findings:
            with self.subTest(severity=finding.severity):
                self.assertEqual(finding.dimension, REVIEW_DIMENSION)


class StructuralTests(unittest.TestCase):
    def test_exactly_one_finding_for_a_healthy_plan(self) -> None:
        report = assess_narration_coverage(healthy_plan())
        self.assertEqual(report.verdict, "PASS")
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].severity, "PASS")

    def test_an_empty_plan_is_refused(self) -> None:
        with self.assertRaises(NarrationCoverageError):
            assess_narration_coverage([])

    def test_interval_geometry_is_validated(self) -> None:
        with self.assertRaises(NarrationCoverageError):
            CommercialUnit("U1", 2.0, 2.0, True, True, False)

    def test_a_unit_needs_an_id(self) -> None:
        with self.assertRaises(NarrationCoverageError):
            CommercialUnit("", 0.0, 1.0, True, True, False)

    def test_a_unit_must_carry_a_real_voice_event(self) -> None:
        with self.assertRaises(NarrationCoverageError):
            CommercialUnit("U1", 0.0, 1.0, True, True, False, vo="not an event")

    def test_the_report_serialises(self) -> None:
        payload = assess_narration_coverage(healthy_plan()).as_dict()
        self.assertEqual(payload["dimension"], REVIEW_DIMENSION)
        self.assertEqual(payload["verdict"], "PASS")

    def test_units_are_ordered_by_time(self) -> None:
        report = assess_narration_coverage([
            spoken("late", "CTA", start=4.0, end=6.0),
            spoken("early", "HOOK", start=0.0, end=2.0)])
        self.assertEqual([u.unit_id for u in report.units], ["early", "late"])

    def test_the_frozen_vocabularies_are_intact(self) -> None:
        self.assertEqual(len(VO_ROLES), 7)
        self.assertIn("HERO_VISUAL_CARRIES_MESSAGE", JUSTIFIED_SILENCE_REASONS)
        self.assertIn("PRODUCTION_SOUND_CARRIES_ACTION", JUSTIFIED_SILENCE_REASONS)
        self.assertIn("PRODUCTION_SOUND_IMPORTANT", JUSTIFIED_SILENCE_REASONS)


if __name__ == "__main__":
    unittest.main()
