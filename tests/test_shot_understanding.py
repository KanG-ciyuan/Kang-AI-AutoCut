"""Tests for the Shot Understanding Foundation (Batch 1: A1 / A2 / A3).

The synthetic cases pin the behaviour that the Filter First Job regression only
demonstrates statistically: a candidate window is not a shot, an action and its result
are one unit, and comprehension is a requirement rather than a duration threshold.
"""

from __future__ import annotations

import unittest

from src.ai_autocut.shot_understanding import (
    ACCIDENTAL_FRAGMENT_FRAMES,
    CFR_FPS,
    CONTEXT_CREDIT_SECONDS,
    DETECTION_THRESHOLD,
    MICRO_FRAGMENT_SECONDS,
    ROLE_BASE_SECONDS,
    ComprehensionFinding,
    Placement,
    PlacementAnalysis,
    ShotUnderstandingError,
    SemanticGroup,
    SegmentRef,
    VisualBoundary,
    VisualSegment,
    analyse_placements,
    assess_comprehension,
    build_segment_refs,
    detect_boundaries,
    group_segments,
    required_seconds,
    split_into_segments,
    summarise,
    truncation_of,
)


def _analysis(placement_id: str, role: str, in_frame: int, out_frame: int,
              cuts: tuple[int, ...] = (), timeline_start: int = 0) -> PlacementAnalysis:
    boundaries = tuple(VisualBoundary(c, 60.0) for c in cuts)
    segments, inside = split_into_segments(in_frame, out_frame, boundaries)
    return PlacementAnalysis(
        placement_id=placement_id, source_id="SRC", narrative_role=role,
        source_in=in_frame, source_out_exclusive=out_frame, timeline_start=timeline_start,
        segments=segments, internal_boundaries=inside,
    )


class VisualSegmentationTests(unittest.TestCase):
    """A1 — a candidate window is not a shot."""

    def test_internal_cut_splits_one_window_into_two(self) -> None:
        segments, boundaries = split_into_segments(0, 60, (VisualBoundary(20, 55.0),))
        self.assertEqual(len(segments), 2)
        self.assertEqual(len(boundaries), 1)
        self.assertEqual((segments[0].start_frame, segments[0].end_frame_exclusive), (0, 20))
        self.assertEqual((segments[1].start_frame, segments[1].end_frame_exclusive), (20, 60))

    def test_continuous_shot_stays_one_segment(self) -> None:
        segments, boundaries = split_into_segments(0, 60, ())
        self.assertEqual(len(segments), 1)
        self.assertEqual(boundaries, ())
        self.assertEqual(segments[0].duration_frames, 60)

    def test_boundaries_outside_the_window_are_ignored(self) -> None:
        """A candidate edge is not a visual boundary, and a neighbour's cut is not ours."""

        segments, boundaries = split_into_segments(
            100, 160, (VisualBoundary(100, 70.0), VisualBoundary(40, 70.0),
                       VisualBoundary(160, 70.0))
        )
        self.assertEqual(len(segments), 1)
        self.assertEqual(boundaries, ())

    def test_detection_is_deterministic(self) -> None:
        differences = [1.0, 2.0, 50.0, 1.5, 1.4, 44.0, 2.0]
        first = detect_boundaries(differences)
        second = detect_boundaries(differences)
        self.assertEqual(first, second)
        self.assertEqual([b.frame_index for b in first], [3, 6])

    def test_threshold_is_the_only_gate(self) -> None:
        self.assertEqual(detect_boundaries([DETECTION_THRESHOLD]), ())
        self.assertEqual(len(detect_boundaries([DETECTION_THRESHOLD + 0.01])), 1)

    def test_analysis_decodes_each_media_once(self) -> None:
        """Placements sharing a media file must not be decoded twice."""

        from src.ai_autocut import shot_understanding as module

        calls: list[str] = []
        original = module.decode_differences

        def counting(path: str, **_kwargs):
            calls.append(path)
            return 31, [1.0] * 30

        module.decode_differences = counting  # type: ignore[assignment]
        try:
            analyse_placements([
                Placement("a", "S", "same.mp4", 0, 30),
                Placement("b", "S", "same.mp4", 0, 30),
            ])
        finally:
            module.decode_differences = original  # type: ignore[assignment]
        self.assertEqual(calls, ["same.mp4"])

    def test_segment_rejects_empty_range(self) -> None:
        with self.assertRaises(ShotUnderstandingError):
            VisualSegment(10, 10)

    def test_boundary_rejects_frame_zero(self) -> None:
        with self.assertRaises(ShotUnderstandingError):
            VisualBoundary(0, 50.0)


class FragmentDiagnosticsTests(unittest.TestCase):
    """Micro-fragments are a metric, accidental fragments are an anomaly."""

    def test_micro_fragment_is_a_metric_not_a_defect(self) -> None:
        short = VisualSegment(0, int(MICRO_FRAGMENT_SECONDS * CFR_FPS) - 1)
        self.assertTrue(short.is_micro_fragment)
        # It is only a metric: nothing in the module rejects it.
        self.assertFalse(short.is_accidental_fragment)

    def test_borderline_length_is_not_accidental(self) -> None:
        one_frame_under = VisualSegment(0, int(MICRO_FRAGMENT_SECONDS * CFR_FPS) - 1)
        self.assertFalse(one_frame_under.is_accidental_fragment)

    def test_one_and_two_frame_segments_are_accidental(self) -> None:
        for frames in (1, 2, ACCIDENTAL_FRAGMENT_FRAMES):
            self.assertTrue(VisualSegment(0, frames).is_accidental_fragment)
        self.assertFalse(VisualSegment(0, 3).is_accidental_fragment)


class SemanticGroupingTests(unittest.TestCase):
    """A2 — Visual Change != Semantic Change."""

    def test_action_then_result_becomes_one_unit(self) -> None:
        placements = [
            Placement("install", "S", "m.mp4", 0, 60, timeline_start=0,
                      narrative_role="action"),
            Placement("flow", "S", "m.mp4", 60, 120, timeline_start=60,
                      narrative_role="identity"),
        ]
        analyses = [_analysis("install", "action", 0, 60),
                    _analysis("flow", "identity", 60, 120)]
        groups = group_segments(placements, analyses)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].shape, "ACTION_RESULT")
        self.assertEqual(groups[0].roles, ("action", "identity"))
        self.assertAlmostEqual(groups[0].duration_seconds, 4.0, places=3)

    def test_unrelated_adjacent_segments_are_not_grouped(self) -> None:
        """Two identity beats next to each other are two units, not one."""

        placements = [
            Placement("a", "S", "m.mp4", 0, 60, timeline_start=0, narrative_role="identity"),
            Placement("b", "S", "m.mp4", 60, 120, timeline_start=60, narrative_role="identity"),
        ]
        analyses = [_analysis("a", "identity", 0, 60), _analysis("b", "identity", 60, 120)]
        groups = group_segments(placements, analyses)
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(g.shape == "SINGLE" for g in groups))

    def test_result_without_a_preceding_action_is_not_grouped(self) -> None:
        placements = [
            Placement("proof", "S", "m.mp4", 0, 60, timeline_start=0, narrative_role="proof"),
            Placement("identity", "S", "m.mp4", 60, 120, timeline_start=60,
                      narrative_role="identity"),
        ]
        analyses = [_analysis("proof", "proof", 0, 60),
                    _analysis("identity", "identity", 60, 120)]
        groups = group_segments(placements, analyses)
        self.assertEqual(len(groups), 2)

    def test_hero_keeps_all_of_its_segments_in_one_unit(self) -> None:
        placements = [Placement("hero", "S", "m.mp4", 0, 90, timeline_start=0,
                                narrative_role="hero")]
        analyses = [_analysis("hero", "hero", 0, 90, cuts=(30, 60))]
        groups = group_segments(placements, analyses)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].shape, "HERO_UNIT")
        self.assertEqual(groups[0].segment_count, 3)

    def test_truncated_placement_marks_its_group(self) -> None:
        placements = [
            Placement("a", "S", "m.mp4", 0, 60, timeline_start=0, narrative_role="action",
                      candidate_in=0, candidate_out_exclusive=120),
        ]
        analyses = [_analysis("a", "action", 0, 60)]
        self.assertTrue(truncation_of(placements[0]))
        groups = group_segments(placements, analyses, truncated_ids={"a"})
        self.assertTrue(groups[0].truncated)

    def test_full_range_placement_is_not_truncated(self) -> None:
        placement = Placement("a", "S", "m.mp4", 0, 120, narrative_role="action",
                              candidate_in=0, candidate_out_exclusive=120)
        self.assertFalse(truncation_of(placement))

    def test_segment_refs_are_timeline_ordered(self) -> None:
        placements = [
            Placement("first", "S", "m.mp4", 0, 60, timeline_start=0,
                      narrative_role="identity"),
            Placement("second", "S", "m.mp4", 60, 120, timeline_start=60,
                      narrative_role="action"),
        ]
        analyses = [_analysis("first", "identity", 0, 60, cuts=(30,)),
                    _analysis("second", "action", 60, 120)]
        refs = build_segment_refs(placements, analyses)
        self.assertEqual([r.timeline_start for r in refs], sorted(r.timeline_start for r in refs))
        self.assertEqual(len(refs), 3)


class ComprehensionTests(unittest.TestCase):
    """A3 — Comprehension Requirement > Fixed Duration Threshold."""

    def _case(self, duration_seconds: float, count: int = 1, role: str = "identity",
              truncated: bool = False, spans: bool = True):
        """Build a group and the analysis it came from.

        ``spans=True`` means the group covers its whole window, which is what makes it a
        deliberate insert rather than a fragment left over from an internal cut.
        """

        frames = int(round(duration_seconds * CFR_FPS))
        per = max(1, frames // count)
        cuts = tuple(per * (i + 1) for i in range(count - 1))
        analysis = _analysis("p", role, 0, frames, cuts=cuts)
        members = tuple(
            SegmentRef("p", i, role, seg.start_frame, seg.end_frame_exclusive,
                       seg.start_frame)
            for i, seg in enumerate(analysis.segments)
        )
        group = SemanticGroup("g", "SINGLE", members, (role,),
                              round(sum(m.duration_seconds for m in members), 4),
                              truncated=truncated)
        if not spans:
            # a fragment: the window is longer and a real cut carves this piece out of it
            window = _analysis("p", role, 0, frames + 60, cuts=(frames,))
            analysis = window
            first = window.segments[0]
            members = (SegmentRef("p", 0, role, first.start_frame,
                                  first.end_frame_exclusive, first.start_frame),)
            group = SemanticGroup("g", "SINGLE", members, (role,),
                                  members[0].duration_seconds,
                                  truncated=truncated)
        return group, [analysis]

    def _assess(self, duration_seconds: float, *, established: int = 0, **kwargs):
        group, analyses = self._case(duration_seconds, **kwargs)
        return assess_comprehension(
            [group], analyses, establishing_roles_seen_before=established
        )[0]

    def test_short_but_valid_insert_produces_no_warning(self) -> None:
        """0.5-0.7s is legitimate for a deliberate insert in established context."""

        for length in (0.5, 0.6, 0.7):
            with self.subTest(length=length):
                self.assertFalse(self._assess(length, established=1).warning)
        finding = self._assess(0.7, established=1)
        self.assertFalse(finding.warning)
        self.assertIsNone(finding.factor)
        self.assertTrue(finding.spans_window)

    def test_long_but_incomplete_action_warns_on_completion(self) -> None:
        """A group can be long and still fail, because the action never lands."""

        finding = self._assess(1.2, role="action", truncated=True)
        self.assertTrue(finding.warning)
        self.assertEqual(finding.factor, "action_completion")

    def test_complete_short_unit_produces_no_warning(self) -> None:
        """The purchase-check detail the accepted edit kept at 0.77s."""

        finding = self._assess(0.77, role="proof", established=1)
        self.assertFalse(finding.warning)

    def test_warning_names_the_factor_rather_than_a_number(self) -> None:
        finding = self._assess(0.2, role="hero")
        self.assertTrue(finding.warning)
        self.assertIsNotNone(finding.factor)
        self.assertIn(finding.factor, {
            "visual_complexity", "product_recognition", "information_density",
            "action_completion", "accidental_fragment", "context", "rhythm",
        })
        self.assertTrue(finding.detail)

    def test_there_is_no_universal_duration_threshold(self) -> None:
        """The same length passes or warns depending on the requirement, not the length."""

        lenient = self._assess(0.7, role="identity", established=1)
        demanding = self._assess(0.7, role="hero")
        self.assertAlmostEqual(lenient.actual_seconds, demanding.actual_seconds, places=4)
        self.assertFalse(lenient.warning)
        self.assertTrue(demanding.warning)

    def test_fragment_of_a_window_is_flagged_on_context(self) -> None:
        finding = self._assess(0.4, role="identity", established=1, spans=False)
        self.assertTrue(finding.warning)
        self.assertEqual(finding.factor, "context")

    def test_one_and_two_frame_segments_are_an_accidental_fragment(self) -> None:
        group, analyses = self._case(0.03)
        group = SemanticGroup(
            "g", "SINGLE", (SegmentRef("p", 0, "identity", 0, 1, 0),), ("identity",),
            1 / CFR_FPS,
        )
        finding = assess_comprehension([group], analyses)[0]
        self.assertEqual(finding.factor, "accidental_fragment")
        self.assertEqual(finding.accidental_fragments, 1)

    def test_extra_segments_raise_the_requirement(self) -> None:
        one_group, one_analyses = self._case(1.0, count=1, role="identity")
        three_group, three_analyses = self._case(1.0, count=3, role="identity")
        one, _ = required_seconds(one_group, product_established=False)
        three, factor = required_seconds(three_group, product_established=False)
        self.assertGreater(three, one)
        self.assertEqual(factor, "visual_complexity")

    def test_established_context_lowers_the_requirement(self) -> None:
        group, _ = self._case(1.0)
        fresh, _ = required_seconds(group, product_established=False)
        settled, _ = required_seconds(group, product_established=True)
        self.assertLess(settled, fresh)

    def test_product_recognition_raises_the_requirement(self) -> None:
        identity_group, _ = self._case(1.0, role="identity")
        proof_group, _ = self._case(1.0, role="proof")
        identity, _ = required_seconds(identity_group, product_established=False)
        proof, factor = required_seconds(proof_group, product_established=False)
        self.assertGreater(proof, identity)
        self.assertEqual(factor, "product_recognition")

    def test_warning_is_not_an_exception(self) -> None:
        findings = assess_comprehension(
            [self._case(0.05, role="hero")[0]], self._case(0.05, role="hero")[1]
        )
        self.assertIsInstance(findings[0], ComprehensionFinding)

    def test_shortfall_is_reported(self) -> None:
        finding = self._assess(0.2, role="hero")
        self.assertGreater(finding.shortfall_seconds, 0)

    def test_action_role_is_never_treated_as_a_simple_insert(self) -> None:
        group, _ = self._case(0.7, role="action")
        requirement, _ = required_seconds(
            group, product_established=True, spans_window=True
        )
        self.assertGreaterEqual(requirement, ROLE_BASE_SECONDS["action"] - CONTEXT_CREDIT_SECONDS)


class SummaryTests(unittest.TestCase):
    """The summary is the artifact the regression is scored against."""

    def test_summary_counts_segments_groups_and_warnings(self) -> None:
        placements = [
            Placement("a", "S", "m.mp4", 0, 60, timeline_start=0, narrative_role="action"),
            Placement("b", "S", "m.mp4", 60, 120, timeline_start=60,
                      narrative_role="identity"),
        ]
        analyses = [_analysis("a", "action", 0, 60, cuts=(30,)),
                    _analysis("b", "identity", 60, 120)]
        groups = group_segments(placements, analyses)
        findings = assess_comprehension(groups, analyses)
        summary = summarise(analyses, groups, findings)
        self.assertEqual(summary["placements_analysed"], 2)
        self.assertEqual(summary["visual_segments"], 3)
        self.assertEqual(summary["placements_containing_internal_cuts"], ["a"])
        self.assertEqual(summary["semantic_groups"], 1)
        self.assertEqual(summary["group_shapes"], {"ACTION_RESULT": 1})
        self.assertIn("comprehension_warnings", summary)


if __name__ == "__main__":
    unittest.main()
