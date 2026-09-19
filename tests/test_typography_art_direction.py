"""Typography Art Direction A v1 — the locked baseline, as enforceable behaviour.

The Third SKU's typography was designed by hand three times before a human Producer locked
the accepted "Premium Minimal A" treatment as the project baseline. These tests are what
stop that decision from evaporating into a screenshot: they pin the rules, the closed zone
set, the refusal behaviour, and the fact that the Third SKU's own approved configuration is
still expressible.

What is deliberately NOT tested is any pixel size, font name or coordinate. Those are the
Third SKU's parameters, not the rules, and a test that froze them would turn one SKU's art
direction into every future SKU's default — the exact failure this consolidation exists to
avoid.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.ai_autocut import typography_art_direction as tad
from src.ai_autocut.typography_art_direction import (
    DEFAULT_PLATFORM_SAFE_ZONE,
    DEFAULT_ZONE_FOR_ROLE,
    NARRATIVE_ROLES,
    REVIEWER_CHECKS,
    ZONE_NAMES,
    ArtDirectionProfile,
    EvidenceRegion,
    Rect,
    TypographyArtDirectionError,
    TypographyEvent,
    body_anchor_zones,
    plan_layout,
    profile_from_document,
    review_typography,
    select_zone,
    summarise,
    zone_conflicts,
)

REPO = Path(__file__).resolve().parent.parent
PROFILE_PATH = REPO / "examples" / "typography" / "art-direction-a-v1.profile.json"

#: The Third SKU's accepted A layout, transcribed from typography_a.ass. Line breaks match
#: A, which re-broke the approved lines — that is layout, and it is allowed.
THIRD_SKU_A = (
    ("U01", "HOOK", ("KOTORAN KULIT", "TERANGKAT"), 0.00, 2.50, "UPPER_LEFT"),
    ("U02", "BODY_SELLING_POINT", ("BENTUK BULAT,", "MUDAH DIGENGGAM"), 7.03, 9.53, "UPPER_LEFT"),
    ("U03", "BODY_SELLING_POINT", ("TINGGAL PASANG", "DI JARI"), 10.70, 13.20, "UPPER_LEFT"),
    ("U04", "BODY_SELLING_POINT", ("BUSA MELIMPAH",), 15.10, 16.93, "UPPER_LEFT"),
    ("U05", "BODY_SELLING_POINT", ("BISA UNTUK", "BAGIAN TUBUH LAIN"), 16.93, 19.43, "UPPER_LEFT"),
    ("U06", "BODY_SELLING_POINT", ("SETELAH DIBILAS",), 20.63, 22.33, "UPPER_LEFT"),
    ("U07", "BODY_SELLING_POINT", ("MUDAH DIBERSIHKAN",), 22.33, 24.83, "UPPER_LEFT"),
    ("U08", "CTA", ("PAKAI LAGI SAAT MANDI", "KLIK LINK DI BAWAH"), 24.90, 30.20, "UPPER_CENTER"),
)

#: The approved wording as it was locked, before A re-broke the lines.
LOCKED_LINES = {
    "U01": ["KOTORAN KULIT TERANGKAT"],
    "U02": ["BENTUK BULAT, MUDAH DIGENGGAM"],
    "U03": ["TINGGAL PASANG DI JARI"],
    "U04": ["BUSA MELIMPAH"],
    "U05": ["BISA UNTUK BAGIAN TUBUH LAIN"],
    "U06": ["SETELAH DIBILAS"],
    "U07": ["MUDAH DIBERSIHKAN"],
    "U08": ["PAKAI LAGI SAAT MANDI", "KLIK LINK DI BAWAH"],
}


def third_sku_events() -> tuple[TypographyEvent, ...]:
    return tuple(
        TypographyEvent(event_id=eid, narrative_role=role, text_lines=lines,
                        start_seconds=start, end_seconds=end, zone_name=zone,
                        background_plate="ACCENT_RULE",
                        motion="FADE_AND_SETTLE")
        for eid, role, lines, start, end, zone in THIRD_SKU_A
    )


def third_sku_profile() -> ArtDirectionProfile:
    return profile_from_document(json.loads(PROFILE_PATH.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ 1. body anchor


class BodyAnchorTests(unittest.TestCase):
    """BODY must hold one visual anchor. This is the rule with the most obligation."""

    def test_body_events_share_one_zone_on_a_clean_piece(self) -> None:
        events = [e for e in third_sku_events() if e.narrative_role == "BODY_SELLING_POINT"]
        resolved = plan_layout(events).events
        self.assertEqual(body_anchor_zones(resolved), ("UPPER_LEFT",))

    def test_every_body_event_keeps_the_anchor_when_nothing_conflicts(self) -> None:
        """The default zone is safe, so no body event may drift to another zone."""

        events = third_sku_events()
        plan = plan_layout(events)
        body = [e for e in plan.events if e.narrative_role == "BODY_SELLING_POINT"]
        self.assertEqual({e.zone_name for e in body}, {"UPPER_LEFT"})
        for decision in plan.decisions:
            if decision.narrative_role == "BODY_SELLING_POINT":
                self.assertTrue(decision.is_default, decision.zone_name)

    def test_the_third_sku_layout_already_uses_the_default_body_zone(self) -> None:
        for event in third_sku_events():
            if event.narrative_role == "BODY_SELLING_POINT":
                with self.subTest(event=event.event_id):
                    self.assertEqual(event.zone_name,
                                     DEFAULT_ZONE_FOR_ROLE["BODY_SELLING_POINT"])


# ------------------------------------------------------- 2. no random repositioning


class DeterminismTests(unittest.TestCase):
    """The default zone is used whenever it is safe, with no searching and no randomness."""

    def test_select_zone_is_pure(self) -> None:
        first = select_zone("BODY_SELLING_POINT")
        for _ in range(20):
            self.assertEqual(select_zone("BODY_SELLING_POINT").zone_name, first.zone_name)

    def test_default_zone_wins_whenever_it_is_free(self) -> None:
        for role in NARRATIVE_ROLES:
            with self.subTest(role=role):
                decision = select_zone(role)
                self.assertEqual(decision.zone_name, DEFAULT_ZONE_FOR_ROLE[role])
                self.assertTrue(decision.is_default)
                self.assertEqual(decision.fallback_index, 0)

    def test_free_positioning_is_not_representable(self) -> None:
        """A layout must name a zone from the closed set; coordinates are not an option."""

        with self.assertRaises(TypographyArtDirectionError):
            TypographyEvent(event_id="X", narrative_role="BODY_SELLING_POINT",
                            text_lines=("A",), start_seconds=0.0, end_seconds=1.0,
                            zone_name="AT_X_86_Y_206")
        self.assertNotIn("AT_X_86_Y_206", ZONE_NAMES)

    def test_a_preferred_zone_is_honoured_only_when_it_is_safe(self) -> None:
        safe = select_zone("BODY_SELLING_POINT", preferred_zone="MID_LEFT")
        self.assertEqual(safe.zone_name, "MID_LEFT")
        band = [EvidenceRegion("product", Rect(0.0, 0.30, 1.0, 0.12))]
        conflicted = select_zone("BODY_SELLING_POINT", preferred_zone="MID_LEFT",
                                 evidence=band)
        self.assertNotEqual(conflicted.zone_name, "MID_LEFT")


# --------------------------------------------------------- 3. limited fallback


class FallbackTests(unittest.TestCase):
    """A real conflict buys a fallback — one step at a time, never a free choice."""

    def test_product_in_the_default_zone_takes_fallback_one(self) -> None:
        upper = [EvidenceRegion("product", Rect(0.0, 0.08, 1.0, 0.12))]
        chain = tad.FALLBACK_CHAIN_FOR_ROLE["BODY_SELLING_POINT"]
        decision = select_zone("BODY_SELLING_POINT", evidence=upper)
        self.assertEqual(decision.zone_name, chain[0])
        self.assertNotEqual(decision.zone_name, DEFAULT_ZONE_FOR_ROLE["BODY_SELLING_POINT"])
        self.assertFalse(decision.is_default)
        self.assertEqual(decision.fallback_index, 1)
        self.assertIn("covers product", decision.conflicts)

    def test_fallback_follows_the_declared_chain_in_order(self) -> None:
        chain = tad.FALLBACK_CHAIN_FOR_ROLE["BODY_SELLING_POINT"]
        # block the default and everything up to the nth fallback, then check which is used
        blocks = [EvidenceRegion("product", Rect(0.0, 0.0, 1.0, 0.20))]      # kills UPPER_*
        decision = select_zone("BODY_SELLING_POINT", evidence=blocks)
        self.assertEqual(decision.zone_name, chain[0])

    def test_a_conflict_driven_body_deviation_is_a_warning_not_a_failure(self) -> None:
        """The brief allows a limited fallback on a real conflict, so it must not FAIL.

        U04 sits on the lather shot where the product crosses the upper band; every other
        body shot is clear. Evidence is therefore per-event, which is what makes a single
        deviating event expressible at all.
        """

        band = [EvidenceRegion("product", Rect(0.0, 0.08, 1.0, 0.12))]
        plan = plan_layout(third_sku_events(), evidence_by_event={"U04": band})
        anchors = body_anchor_zones(plan.events)
        self.assertEqual(anchors[0], "UPPER_LEFT")
        self.assertEqual(len(anchors), 2)

        deviation = plan.decision_for("U04")
        self.assertIsNotNone(deviation)
        self.assertNotEqual(deviation.zone_name, "UPPER_LEFT")
        self.assertTrue(deviation.conflicts)

        findings = review_typography(plan.events, profile=third_sku_profile(),
                                     decisions=plan.decisions)
        by_check = {f.check: f for f in findings}
        self.assertEqual(by_check["body_position_consistency"].severity, "WARNING")

    def test_body_drift_without_a_conflict_is_a_failure(self) -> None:
        """Moving a body event for no reason is the per-shot drift the baseline forbids."""

        events = list(third_sku_events())
        events[5] = TypographyEvent(          # U06 dragged to a third zone, no evidence
            event_id="U06", narrative_role="BODY_SELLING_POINT",
            text_lines=events[5].text_lines, start_seconds=20.63, end_seconds=22.33,
            zone_name="LOWER_LEFT")
        # reviewed as an existing layout: plan_layout would recompute the zone and hide it
        findings = review_typography(tuple(events), profile=third_sku_profile(),
                                     locked_lines=LOCKED_LINES)
        by_check = {f.check: f for f in findings}
        self.assertEqual(by_check["body_position_consistency"].severity, "FAIL")
        self.assertIn("U06", by_check["body_position_consistency"].evidence["unjustified"])

    def test_refuses_rather_than_placing_text_anywhere(self) -> None:
        """When no zone is free the layout is refused. There is no fifth option."""

        everywhere = [EvidenceRegion("product", Rect(0.0, 0.0, 1.0, 1.0))]
        with self.assertRaises(TypographyArtDirectionError) as caught:
            select_zone("BODY_SELLING_POINT", evidence=everywhere)
        self.assertIn("no zone is free of conflicts", str(caught.exception))

    def test_the_lower_zone_sits_above_the_platform_caption_bar(self) -> None:
        """LOWER_LEFT is a *designed* fallback: far enough down to clear a busy upper
        band, far enough up to stay out of TikTok's caption and progress chrome."""

        self.assertEqual(zone_conflicts("LOWER_LEFT", platform=DEFAULT_PLATFORM_SAFE_ZONE), ())
        rect = tad.ZONES["LOWER_LEFT"].rect
        self.assertLess(rect.y1, 1.0 - DEFAULT_PLATFORM_SAFE_ZONE.bottom)

    def test_a_zone_reaching_into_the_platform_chrome_is_refused(self) -> None:
        """TikTok's own UI is a conflict source, not something to design around later."""

        deep = tad.PlatformSafeZone(bottom=0.45)
        reasons = zone_conflicts("LOWER_LEFT", platform=deep)
        self.assertTrue(any("platform keep-out" in r for r in reasons))


# ------------------------------------------------------------------- 4/5. roles


class RoleTests(unittest.TestCase):
    def test_the_three_roles_are_recognised(self) -> None:
        self.assertEqual(NARRATIVE_ROLES, ("HOOK", "BODY_SELLING_POINT", "CTA"))
        for eid, role, lines, start, end, zone in THIRD_SKU_A:
            event = TypographyEvent(event_id=eid, narrative_role=role, text_lines=lines,
                                    start_seconds=start, end_seconds=end, zone_name=zone)
            self.assertEqual(event.narrative_role, role)

    def test_an_unknown_role_is_refused(self) -> None:
        for bad in ("body", "BODY", "SELLING_POINT", "TITLE", ""):
            with self.subTest(role=bad):
                with self.assertRaises(TypographyArtDirectionError):
                    TypographyEvent(event_id="X", narrative_role=bad, text_lines=("A",),
                                    start_seconds=0.0, end_seconds=1.0,
                                    zone_name="UPPER_LEFT")

    def test_the_cta_uses_the_cta_zone(self) -> None:
        cta = [e for e in third_sku_events() if e.narrative_role == "CTA"]
        self.assertEqual(len(cta), 1)
        self.assertEqual(cta[0].zone_name, DEFAULT_ZONE_FOR_ROLE["CTA"])
        self.assertEqual(tad.ZONES[cta[0].zone_name].alignment, "center")

    def test_hook_and_cta_may_differ_from_the_body_zone(self) -> None:
        """Roles may carry different weight, but only from the same zone vocabulary."""

        zones = {e.narrative_role: e.zone_name for e in third_sku_events()}
        self.assertNotEqual(zones["CTA"], zones["BODY_SELLING_POINT"])
        self.assertTrue(set(zones.values()) <= set(ZONE_NAMES))


# ------------------------------------------------------------------ 6. locked text


class LockedTextTests(unittest.TestCase):
    def test_the_third_sku_a_layout_preserves_the_locked_wording(self) -> None:
        """A re-broke the approved lines; that is layout, and the words must be identical."""

        findings = review_typography(third_sku_events(), profile=third_sku_profile(),
                                     locked_lines=LOCKED_LINES)
        by_check = {f.check: f for f in findings}
        self.assertEqual(by_check["text_preserved"].severity, "PASS")

    def test_reworded_text_is_caught(self) -> None:
        events = list(third_sku_events())
        events[0] = TypographyEvent(
            event_id="U01", narrative_role="HOOK",
            text_lines=("KOTORAN KULIT", "TERANGKAT!"),   # punctuation added
            start_seconds=0.0, end_seconds=2.5, zone_name="UPPER_LEFT")
        findings = review_typography(tuple(events), profile=third_sku_profile(),
                                     locked_lines=LOCKED_LINES)
        by_check = {f.check: f for f in findings}
        self.assertEqual(by_check["text_preserved"].severity, "FAIL")
        self.assertIn("U01", by_check["text_preserved"].evidence["drifted"])

    def test_a_dropped_word_is_caught(self) -> None:
        events = list(third_sku_events())
        events[6] = TypographyEvent(
            event_id="U07", narrative_role="BODY_SELLING_POINT",
            text_lines=("DIBERSIHKAN",),   # "MUDAH" dropped
            start_seconds=22.33, end_seconds=24.83, zone_name="UPPER_LEFT")
        findings = review_typography(tuple(events), profile=third_sku_profile(),
                                     locked_lines=LOCKED_LINES)
        by_check = {f.check: f for f in findings}
        self.assertEqual(by_check["text_preserved"].severity, "FAIL")


# --------------------------------------------------------------- 7/8. geometry


class GeometryReviewTests(unittest.TestCase):
    def _profile_with_zone(self, name: str, rect: Rect) -> ArtDirectionProfile:
        base = third_sku_profile()
        return ArtDirectionProfile(
            profile_id=base.profile_id, baseline=base.baseline, status=base.status,
            canvas_width=base.canvas_width, canvas_height=base.canvas_height, fps=base.fps,
            font_stack=base.font_stack, font_index=base.font_index,
            zone_overrides={name: rect})

    def test_a_zone_outside_the_safe_area_is_detected(self) -> None:
        profile = self._profile_with_zone("UPPER_LEFT", Rect(0.0, 0.0, 1.0, 0.02))
        findings = review_typography(third_sku_events(), profile=profile)
        by_check = {f.check: f for f in findings}
        self.assertEqual(by_check["clipping"].severity, "FAIL")
        self.assertEqual(by_check["platform_safe_zone"].severity, "FAIL")

    def test_the_shipped_zones_pass_the_geometry_checks(self) -> None:
        findings = review_typography(third_sku_events(), profile=third_sku_profile())
        by_check = {f.check: f for f in findings}
        for check in ("safe_margin", "platform_safe_zone", "clipping"):
            with self.subTest(check=check):
                self.assertEqual(by_check[check].severity, "PASS")

    def test_typography_covering_known_evidence_is_detected(self) -> None:
        """A product region the job reports must not be covered by any text zone."""

        product = [EvidenceRegion("product", Rect(0.0, 0.08, 1.0, 0.12))]
        findings = review_typography(third_sku_events(), profile=third_sku_profile(),
                                     evidence=product)
        by_check = {f.check: f for f in findings}
        self.assertEqual(by_check["product_overlap"].severity, "FAIL")
        self.assertTrue(by_check["product_overlap"].evidence["events"])

    def test_hand_action_and_result_regions_are_reported_separately(self) -> None:
        """Each evidence class is judged on its own. A hand crossing the text band must not
        drag the result check down with it."""

        evidence = [
            EvidenceRegion("hand", Rect(0.0, 0.09, 1.0, 0.10)),      # crosses the upper band
            EvidenceRegion("result", Rect(0.0, 0.56, 1.0, 0.12)),    # nothing sits there
        ]
        findings = review_typography(third_sku_events(), profile=third_sku_profile(),
                                     evidence=evidence)
        by_check = {f.check: f for f in findings}
        self.assertEqual(by_check["action_overlap"].severity, "FAIL")
        self.assertEqual(by_check["evidence_overlap"].severity, "PASS")
        self.assertEqual(by_check["product_overlap"].severity, "PASS")

    def test_a_result_region_under_a_placed_zone_is_detected(self) -> None:
        """When the layout does reach the result band, the result check fires."""

        event = TypographyEvent(event_id="T", narrative_role="BODY_SELLING_POINT",
                                text_lines=("A",), start_seconds=0.0, end_seconds=1.0,
                                zone_name="LOWER_LEFT")
        findings = review_typography((event,), profile=third_sku_profile(),
                                     evidence=[EvidenceRegion("result", Rect(0.0, 0.56, 1.0, 0.12))])
        by_check = {f.check: f for f in findings}
        self.assertEqual(by_check["evidence_overlap"].severity, "FAIL")

    def test_a_clean_piece_reports_no_overlap(self) -> None:
        findings = review_typography(third_sku_events(), profile=third_sku_profile(),
                                     evidence=[EvidenceRegion("product", Rect(0.2, 0.42, 0.5, 0.2))])
        by_check = {f.check: f for f in findings}
        for check in ("product_overlap", "action_overlap", "evidence_overlap"):
            self.assertEqual(by_check[check].severity, "PASS")


# ------------------------------------------------------------------- reviewer


class ReviewerTests(unittest.TestCase):
    def test_every_named_check_is_reported(self) -> None:
        findings = review_typography(third_sku_events(), profile=third_sku_profile())
        self.assertEqual(tuple(f.check for f in findings), REVIEWER_CHECKS)

    def test_there_is_no_numeric_score(self) -> None:
        """'Premium' is not compressed into a number; the summary counts named checks."""

        summary = summarise(review_typography(third_sku_events(),
                                              profile=third_sku_profile()))
        self.assertEqual(set(summary), {"checks", "pass", "warning", "fail", "blocking",
                                        "note"})
        self.assertNotIn("score", summary)

    def test_the_third_sku_a_layout_is_clean_apart_from_the_cta_check(self) -> None:
        findings = review_typography(third_sku_events(), profile=third_sku_profile(),
                                     locked_lines=LOCKED_LINES)
        failing = [f.check for f in findings if f.severity == "FAIL"]
        self.assertEqual(failing, [])

    def test_height_passed_in_is_what_judges_mobile_readability(self) -> None:
        """The module does not guess a font size; the caller measures and supplies it."""

        tiny = {eid: 20.0 for eid, *_ in THIRD_SKU_A}
        findings = review_typography(third_sku_events(), profile=third_sku_profile(),
                                     measured_line_heights=tiny)
        by_check = {f.check: f for f in findings}
        self.assertEqual(by_check["mobile_readability"].severity, "WARNING")
        self.assertTrue(by_check["mobile_readability"].evidence["measured"])

    def test_a_heavy_dark_plate_is_reported(self) -> None:
        events = list(third_sku_events())
        events[0] = TypographyEvent(
            event_id="U01", narrative_role="HOOK", text_lines=events[0].text_lines,
            start_seconds=0.0, end_seconds=2.5, zone_name="UPPER_LEFT",
            background_plate="HEAVY_PLATE")
        findings = review_typography(tuple(events), profile=third_sku_profile())
        by_check = {f.check: f for f in findings}
        self.assertEqual(by_check["background_plate"].severity, "WARNING")


# ------------------------------------------------- 9. the Third SKU still expresses


class ThirdSkuExpressibilityTests(unittest.TestCase):
    """The approved A configuration must remain expressible. If it stops being, the
    consolidation broke the very thing it was meant to preserve."""

    def test_the_profile_loads(self) -> None:
        profile = third_sku_profile()
        self.assertEqual(profile.profile_id, "third-sku-typography-a-v1")
        self.assertEqual(profile.status, "LOCKED")
        self.assertEqual((profile.canvas_width, profile.canvas_height), (1080, 1920))
        self.assertEqual(profile.font_stack, ("/System/Library/Fonts/Avenir Next Condensed.ttc",))
        self.assertIsNotNone(profile.font_index, "the Heavy face index must be stated, not assumed")

    def test_the_profile_needs_no_zone_overrides(self) -> None:
        """The shipped zone set already contains A's layout — the strongest form of
        'still expressible'."""

        profile = third_sku_profile()
        self.assertEqual(dict(profile.zone_overrides), {})

    def test_ays_actual_text_band_sits_inside_the_default_zone(self) -> None:
        """A occupies roughly y 0.096-0.185 at x 0.080 of the canvas."""

        zone = tad.ZONES["UPPER_LEFT"].rect
        self.assertLessEqual(zone.y, 0.096)
        self.assertGreaterEqual(zone.y1, 0.186)
        self.assertLessEqual(zone.x, 0.080)

    def test_every_third_sku_event_plans_into_a_zone(self) -> None:
        plan = plan_layout(third_sku_events())
        self.assertEqual(len(plan.events), 8)
        self.assertEqual(len(plan.decisions), 8)
        for event in plan.events:
            self.assertIn(event.zone_name, ZONE_NAMES)

    def test_the_planning_matches_the_locked_a_layout(self) -> None:
        """Planning the third SKU reproduces A's own zones, so the baseline is intact."""

        plan = plan_layout(third_sku_events())
        for original, planned in zip(third_sku_events(), plan.events):
            with self.subTest(event=original.event_id):
                self.assertEqual(planned.zone_name, original.zone_name)

    def test_the_profile_is_job_scoped_not_a_module_constant(self) -> None:
        """A parameter must not exist as a module default. Font and colour are the test."""

        for name in dir(tad):
            value = getattr(tad, name)
            if isinstance(value, str):
                self.assertNotIn("Avenir", value,
                                 f"{name} carries a font name out of one job's profile")
        self.assertFalse(hasattr(tad, "DEFAULT_FONT_STACK"))
        self.assertFalse(hasattr(tad, "DEFAULT_ACCENT"))

    def test_a_profile_without_art_direction_is_refused(self) -> None:
        for document in ({}, {"profile_id": "x"}, {"profile_id": "x", "canvas": {}}):
            with self.subTest(document=document):
                with self.assertRaises(TypographyArtDirectionError):
                    profile_from_document(document)


# ------------------------------------------------- status semantics (not one claim)


class StatusSemanticsTests(unittest.TestCase):
    """The baseline makes two claims and only one of them is settled.

    The rules generalise and are locked. Reproducing the approved A *pixels* exactly is not
    claimed: A's ASS spec and its overlay renderer disagree about their own sizes by about
    1.12x, and which one produced the accepted frames is unknown. Collapsing the two into a
    single "LOCKED" is how a future job would end up asserting a match it cannot prove.
    """

    def test_the_two_statuses_are_separate_and_explicit(self) -> None:
        self.assertEqual(tad.ART_DIRECTION_RULES, "LOCKED")
        self.assertEqual(tad.REFERENCE_PIXEL_REPRODUCTION, "UNRESOLVED")
        self.assertNotEqual(tad.ART_DIRECTION_RULES, tad.REFERENCE_PIXEL_REPRODUCTION)

    def test_the_profile_declares_both_semantics(self) -> None:
        document = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        semantics = document.get("status_semantics")
        self.assertIsInstance(semantics, dict)
        self.assertEqual(semantics["art_direction_rules"], "LOCKED")
        self.assertEqual(semantics["reference_pixel_reproduction"], "UNRESOLVED")

    def test_the_profile_does_not_claim_pixel_exact_reproduction(self) -> None:
        """A bare top-level LOCKED would read as 'this file is the approved A'. It is not."""

        document = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        semantics = document["status_semantics"]
        self.assertIn("what_is_not_claimed", semantics)
        self.assertIn("pixel-for-pixel", semantics["what_is_not_claimed"])
        self.assertIn("known_discrepancy", document)
        self.assertNotEqual(document["known_discrepancy"]["status"].split(" -")[0],
                            "RESOLVED")

    def test_the_sizes_carry_their_provenance_and_uncertainty(self) -> None:
        document = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        provenance = document["type_scale"].get("sizes_provenance", "")
        self.assertIn("UNRESOLVED", provenance)
        self.assertIn("1.12x", provenance)

    def test_no_module_string_claims_a_pixel_exact_match(self) -> None:
        """The module must not promise what the artifacts cannot support."""

        source = Path(tad.__file__).read_text(encoding="utf-8")
        for phrase in ("pixel-exact", "pixel exact", "exactly reproduces",
                       "byte-identical to A"):
            self.assertNotIn(phrase, source)


if __name__ == "__main__":
    unittest.main()
