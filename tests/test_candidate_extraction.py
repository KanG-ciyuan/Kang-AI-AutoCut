from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from src.ai_autocut import media_probe, shot_understanding, timebase_adapter
from src.ai_autocut.candidate_extraction import (
    MAX_MERGE_SEGMENTS,
    SCHEMA_VERSION,
    CandidateExtractionError,
    ProposalDecision,
    RejectionCode,
    SegmentSpan,
    SourceMeasurement,
    SourceSegmentation,
    WindowProposal,
    WindowRule,
    extract_candidates,
    parse_window_proposals,
    proposals_from_segmentation,
    render_extraction,
    render_window_proposals,
)
from src.ai_autocut.editing_intelligence import ActionEvidence
from src.ai_autocut.identity import (
    IdentityCatalog,
    MaterialIdentity,
    candidate_id_for,
    material_id_from_sha256,
    parse_identity_catalog,
)
from src.ai_autocut.timebase_adapter import TimebaseAdapter


FIXTURES = Path(__file__).parent / "fixtures"
CATALOG_FIXTURE = FIXTURES / "phase2_identity_catalog_v1.json"
MEASUREMENTS_FIXTURE = FIXTURES / "phase2_candidate_measurements_v1.json"
SEGMENTATIONS_FIXTURE = FIXTURES / "phase2_candidate_segmentations_v1.json"
PROPOSALS_FIXTURE = FIXTURES / "phase2_candidate_window_proposal_v1.json"

SHA = hashlib.sha256(b"candidate-extraction-tests").hexdigest()
MATERIAL = material_id_from_sha256(SHA)


def cfr_measurement(frames: int = 120, *, material_id: str = MATERIAL) -> SourceMeasurement:
    return SourceMeasurement(
        material_id=material_id,
        stream_index=0,
        source="sources/test.mp4",
        timestamps=tuple(round(index / 30, 6) for index in range(frames)),
    )


def simple_segmentation(
    spans: tuple[tuple[int, int], ...], *, material_id: str = MATERIAL
) -> SourceSegmentation:
    return SourceSegmentation(
        material_id=material_id,
        stream_index=0,
        segments=tuple(
            SegmentSpan(index, start, end) for index, (start, end) in enumerate(spans)
        ),
    )


class ExtractionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.material = MATERIAL
        self.sha = SHA
        self.catalog = IdentityCatalog(
            materials=(MaterialIdentity(self.material, self.sha, 4096),), candidates=()
        )
        self.measurement = cfr_measurement()
        self.segmentation = simple_segmentation(((0, 30), (30, 45), (45, 75), (75, 120)))

    def extract(self, proposals, *, catalog=None, measurements=None, segmentations=None):
        return extract_candidates(
            catalog=catalog if catalog is not None else self.catalog,
            measurements=measurements if measurements is not None else (self.measurement,),
            segmentations=(
                segmentations if segmentations is not None else (self.segmentation,)
            ),
            proposals=tuple(proposals),
        )

    def outcome(self, result, proposal_id: str):
        for item in result.outcomes:
            if item.proposal.proposal_id == proposal_id:
                return item
        raise AssertionError("proposal outcome is missing")


class MeasurementTests(ExtractionTestCase):
    def test_measured_timestamps_must_be_strictly_increasing(self) -> None:
        for timestamps in ((0.0, 0.0), (0.1, 0.05), (0.0, float("nan")), (-0.1, 0.0), ()):
            with self.subTest(timestamps=timestamps):
                with self.assertRaises(CandidateExtractionError):
                    SourceMeasurement(MATERIAL, 0, "sources/x.mp4", timestamps)

    def test_pts_lookup_never_divides_by_fps(self) -> None:
        measurement = SourceMeasurement(
            MATERIAL, 0, "sources/vfr.mp4", (0.0, 0.1, 0.133333, 0.166667, 0.25)
        )
        self.assertTrue(measurement.is_variable_frame_rate)
        self.assertEqual(measurement.pts_at(2), 0.133333)
        self.assertNotEqual(measurement.pts_at(2), round(2 / 30, 6))
        with self.assertRaises(CandidateExtractionError):
            measurement.pts_at(5)

    def test_measured_duration_comes_from_the_table(self) -> None:
        measurement = SourceMeasurement(
            MATERIAL, 0, "sources/vfr.mp4", (0.0, 0.1, 0.2, 0.5)
        )
        self.assertEqual(measurement.measured_duration_frames(0, 3), 0.5)
        self.assertNotEqual(measurement.measured_duration_frames(0, 3), round(3 / 30, 6))

    def test_a_measured_source_requires_a_registered_material_id(self) -> None:
        with self.assertRaises(CandidateExtractionError):
            SourceMeasurement("not-a-material", 0, "sources/x.mp4", (0.0, 0.1))


class SingleSegmentTests(ExtractionTestCase):
    def test_a_complete_visual_segment_is_a_candidate(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_seg_a", WindowRule.SINGLE_SEGMENT, self.material, 0, 45, 75,
                    "one complete segment", (2,),
                )
            ]
        )
        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual((candidate.start_frame, candidate.end_frame_exclusive), (45, 75))
        self.assertEqual(candidate.candidate_id, candidate_id_for(self.material, 0, 45, 75))
        self.assertEqual(result.pool.entries[0].candidate_id, candidate.candidate_id)

    def test_a_window_that_is_not_a_segment_is_rejected(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_partial", WindowRule.SINGLE_SEGMENT, self.material, 0, 45, 70,
                    "part of a segment", (2,),
                )
            ]
        )
        outcome = self.outcome(result, "wpropv1_partial")
        self.assertIs(outcome.rejection, RejectionCode.WINDOW_NOT_A_SEGMENT)
        self.assertEqual(result.candidates, ())

    def test_segment_indices_must_exist(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_ghost", WindowRule.SINGLE_SEGMENT, self.material, 0, 45, 75,
                    "a window that names a segment the segmentation does not have", (9,),
                )
            ]
        )
        self.assertIs(
            self.outcome(result, "wpropv1_ghost").rejection,
            RejectionCode.UNKNOWN_SEGMENT,
        )

    def test_rule_a_needs_no_action_evidence(self) -> None:
        auto, skipped = proposals_from_segmentation(
            self.segmentation, measurement=self.measurement
        )
        self.assertEqual(len(auto), 4)
        self.assertEqual(skipped, ())
        result = self.extract(auto)
        self.assertEqual(len(result.candidates), 4)
        self.assertTrue(all(item.accepted for item in result.outcomes))


class AdjacentMergeTests(ExtractionTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.action = ActionEvidence(
            preparation_start=34, action_onset=40, action_completion=58, result_end_exclusive=70
        )

    def test_one_action_spanning_the_join_may_merge(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_merge", WindowRule.ADJACENT_MERGE, self.material, 0, 30, 75,
                    "one action continues across the cut", (1, 2), (), self.action,
                )
            ]
        )
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(
            (result.candidates[0].start_frame, result.candidates[0].end_frame_exclusive),
            (30, 75),
        )

    def test_a_merge_without_a_crossing_action_is_rejected(self) -> None:
        standalone = ActionEvidence(2, 6, 20, 28)
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_wide", WindowRule.ADJACENT_MERGE, self.material, 0, 0, 75,
                    "a wide window that just looks useful", (0, 1, 2), (), standalone,
                )
            ]
        )
        self.assertIs(
            self.outcome(result, "wpropv1_wide").rejection,
            RejectionCode.ACTION_NOT_CROSSING_BOUNDARY,
        )

    def test_non_adjacent_segments_cannot_be_merged(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_gap", WindowRule.ADJACENT_MERGE, self.material, 0, 0, 75,
                    "segments with a gap between them", (0, 2), (), self.action,
                )
            ]
        )
        self.assertIs(
            self.outcome(result, "wpropv1_gap").rejection,
            RejectionCode.SEGMENT_NOT_ADJACENT,
        )

    def test_a_merge_may_not_grow_without_bound(self) -> None:
        spans = tuple((index * 10, index * 10 + 10) for index in range(8))
        segmentation = simple_segmentation(spans)
        measurement = cfr_measurement(80)
        indices = tuple(range(MAX_MERGE_SEGMENTS + 1))
        action = ActionEvidence(2, 4, 30, 40)
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_huge", WindowRule.ADJACENT_MERGE, self.material, 0, 0,
                    spans[len(indices) - 1][1], "an ever-widening window", indices, (), action,
                )
            ],
            measurements=(measurement,),
            segmentations=(segmentation,),
        )
        self.assertIs(
            self.outcome(result, "wpropv1_huge").rejection, RejectionCode.MERGE_TOO_WIDE
        )

    def test_a_merge_must_cover_exactly_its_segments(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_short_merge", WindowRule.ADJACENT_MERGE, self.material, 0, 30, 70,
                    "a merge that does not reach its last segment's end", (1, 2), (), self.action,
                )
            ]
        )
        self.assertIs(
            self.outcome(result, "wpropv1_short_merge").rejection,
            RejectionCode.WINDOW_NOT_THE_MERGE,
        )


class ActionWindowTests(ExtractionTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.action = ActionEvidence(
            preparation_start=80, action_onset=88, action_completion=108, result_end_exclusive=118
        )

    def test_the_action_safe_window_is_the_shortest_complete_one(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_safe", WindowRule.ACTION_SAFE_WINDOW, self.material, 0, 88, 118,
                    "shortest window that still keeps the result", (), (), self.action,
                )
            ]
        )
        measured = result.measured_for(result.candidates[0].candidate_id)
        self.assertEqual(measured.t_in_seconds, round(88 / 30, 6))
        self.assertEqual(measured.frame_count, 30)
        self.assertAlmostEqual(measured.duration_seconds, 1.0, places=6)

    def test_a_window_that_is_not_the_action_span_is_rejected(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_notsafe", WindowRule.ACTION_SAFE_WINDOW, self.material, 0, 80, 118,
                    "a window that includes the preparation", (), (), self.action,
                )
            ]
        )
        self.assertIs(
            self.outcome(result, "wpropv1_notsafe").rejection,
            RejectionCode.WINDOW_NOT_ACTION_SAFE,
        )

    def test_a_window_that_drops_the_result_is_rejected(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_trunc", WindowRule.SHORTER_ACTION_WINDOW, self.material, 0, 75, 110,
                    "a shorter window that ends before the action's result", (), (3,),
                    self.action,
                )
            ]
        )
        self.assertIs(
            self.outcome(result, "wpropv1_trunc").rejection,
            RejectionCode.RESULT_TRUNCATED,
        )

    def test_a_window_that_enters_after_the_onset_is_rejected(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_late", WindowRule.SHORTER_ACTION_WINDOW, self.material, 0, 95, 120,
                    "a shorter window that skips the onset", (), (3,), self.action,
                )
            ]
        )
        self.assertIs(
            self.outcome(result, "wpropv1_late").rejection,
            RejectionCode.ACTION_ONSET_EXCLUDED,
        )

    def test_illegal_action_chronology_is_refused_at_construction(self) -> None:
        from src.ai_autocut.editing_intelligence import EditingIntelligenceError

        with self.assertRaises(EditingIntelligenceError):
            ActionEvidence(80, 108, 95, 118)


class ShorterWindowTests(ExtractionTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.action = ActionEvidence(
            preparation_start=80, action_onset=88, action_completion=108, result_end_exclusive=118
        )

    def test_a_shorter_window_gets_a_new_identity(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_full", WindowRule.SINGLE_SEGMENT, self.material, 0, 75, 120,
                    "the complete segment", (3,),
                ),
                WindowProposal(
                    "wpropv1_shorter", WindowRule.SHORTER_ACTION_WINDOW, self.material, 0, 86, 120,
                    "the same action, read completely from a later in-point", (), (3,), self.action,
                ),
            ]
        )
        self.assertEqual(len(result.candidates), 2)
        full = self.outcome(result, "wpropv1_full").candidate
        shorter = self.outcome(result, "wpropv1_shorter").candidate
        self.assertNotEqual(full.candidate_id, shorter.candidate_id)
        self.assertEqual((shorter.start_frame, shorter.end_frame_exclusive), (86, 120))
        # The complete Candidate is still in the Pool; nothing was trimmed in place.
        self.assertIn(full.candidate_id, [entry.candidate_id for entry in result.pool.entries])

    def test_a_shorter_window_must_be_shorter_and_inside_its_parent(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_not_shorter", WindowRule.SHORTER_ACTION_WINDOW, self.material, 0,
                    75, 120, "the same window as the parent", (), (3,), self.action,
                )
            ]
        )
        self.assertIs(
            self.outcome(result, "wpropv1_not_shorter").rejection,
            RejectionCode.NOT_SHORTER_THAN_PARENT,
        )
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_outside_parent", WindowRule.SHORTER_ACTION_WINDOW, self.material, 0,
                    70, 110, "a window that leaves its parent", (), (3,), self.action,
                )
            ]
        )
        self.assertIs(
            self.outcome(result, "wpropv1_outside_parent").rejection,
            RejectionCode.PARENT_SEGMENT_REQUIRED,
        )

    def test_a_shorter_window_needs_a_parent(self) -> None:
        with self.assertRaises(CandidateExtractionError):
            WindowProposal(
                "wpropv1_orphan", WindowRule.SHORTER_ACTION_WINDOW, self.material, 0, 86, 120,
                "a shorter window with nothing to be shorter than", (), (), self.action,
            )


class BoundaryFailureTests(ExtractionTestCase):
    def test_an_unregistered_material_is_rejected(self) -> None:
        ghost = material_id_from_sha256(hashlib.sha256(b"ghost").hexdigest())
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_ghost_material", WindowRule.SINGLE_SEGMENT, ghost, 0, 0, 30,
                    "a material nobody registered", (0,),
                )
            ]
        )
        self.assertIs(
            self.outcome(result, "wpropv1_ghost_material").rejection,
            RejectionCode.UNREGISTERED_MATERIAL,
        )

    def test_an_unmeasured_stream_is_rejected(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_unmeasured", WindowRule.SINGLE_SEGMENT, self.material, 3, 0, 30,
                    "a stream with no measured timebase", (0,),
                )
            ],
            segmentations=(simple_segmentation(((0, 30),)),),
        )
        self.assertIs(
            self.outcome(result, "wpropv1_unmeasured").rejection,
            RejectionCode.MEASURED_TIMEBASE_UNAVAILABLE,
        )

    def test_an_empty_window_is_rejected(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_empty", WindowRule.SINGLE_SEGMENT, self.material, 0, 30, 30,
                    "an empty window", (0,),
                )
            ]
        )
        self.assertIs(
            self.outcome(result, "wpropv1_empty").rejection, RejectionCode.EMPTY_RANGE
        )

    def test_a_window_past_the_measured_end_is_rejected(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_bounds", WindowRule.SINGLE_SEGMENT, self.material, 0, 0, 130,
                    "a window past the measured end", (0,),
                )
            ]
        )
        self.assertIs(
            self.outcome(result, "wpropv1_bounds").rejection,
            RejectionCode.OUT_OF_MATERIAL_BOUNDS,
        )

    def test_a_duplicate_identity_is_rejected(self) -> None:
        first = WindowProposal(
            "wpropv1_first", WindowRule.SINGLE_SEGMENT, self.material, 0, 0, 30,
            "the same window twice", (0,),
        )
        second = WindowProposal(
            "wpropv1_second", WindowRule.SINGLE_SEGMENT, self.material, 0, 0, 30,
            "the same window twice", (0,),
        )
        result = self.extract([first, second])
        self.assertEqual(len(result.candidates), 1)
        self.assertIs(
            self.outcome(result, "wpropv1_second").rejection,
            RejectionCode.DUPLICATE_IDENTITY,
        )

    def test_rejections_are_counted_and_never_silently_dropped(self) -> None:
        result = self.extract(
            [
                WindowProposal(
                    "wpropv1_ok", WindowRule.SINGLE_SEGMENT, self.material, 0, 0, 30,
                    "a valid window", (0,),
                ),
                WindowProposal(
                    "wpropv1_bad", WindowRule.SINGLE_SEGMENT, self.material, 0, 0, 130,
                    "an invalid window", (0,),
                ),
            ]
        )
        self.assertEqual(len(result.outcomes), 2)
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(len(result.rejected), 1)
        self.assertEqual(result.rejection_counts(), {"OUT_OF_MATERIAL_BOUNDS": 1})
        document = json.loads(render_extraction(result))
        self.assertEqual(
            [item["decision"] for item in document["proposals"]],
            ["ACCEPTED", "REJECTED"],
        )
        self.assertEqual(document["counts"]["rejected_proposals"], 1)


class DeterministicProposalTests(ExtractionTestCase):
    """The deterministic helper must not lose a segment quietly."""

    def test_an_out_of_range_segment_is_proposed_and_then_rejected(self) -> None:
        segmentation = simple_segmentation(((0, 30), (30, 90)))  # 90 is past the 120? no: 120 frames
        measurement = cfr_measurement(60)  # the measured source holds only 60 frames
        proposals, skipped = proposals_from_segmentation(
            segmentation, measurement=measurement
        )
        self.assertEqual(len(proposals), 2)
        self.assertEqual(skipped, ())
        result = self.extract(
            proposals,
            measurements=(measurement,),
            segmentations=(segmentation,),
        )
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.rejection_counts(), {"OUT_OF_MATERIAL_BOUNDS": 1})
        rejected = result.rejected[0]
        self.assertIs(rejected.rejection, RejectionCode.OUT_OF_MATERIAL_BOUNDS)
        self.assertEqual(rejected.proposal.frame_range, (30, 90))
        # The rejection is visible in the rendered extraction document too.
        document = json.loads(render_extraction(result))
        self.assertEqual(document["counts"]["candidate_proposals"], 2)
        self.assertEqual(document["rejection_counts"], {"OUT_OF_MATERIAL_BOUNDS": 1})

    def test_an_accidental_fragment_is_counted_as_a_policy_skip(self) -> None:
        segmentation = simple_segmentation(((0, 2), (2, 30)))
        measurement = cfr_measurement(60)
        proposals, skipped = proposals_from_segmentation(
            segmentation, measurement=measurement
        )
        self.assertEqual([p.frame_range for p in proposals], [(2, 30)])
        self.assertEqual(skipped, ((segmentation.material_id, 0, 2),))
        result = self.extract(
            proposals,
            measurements=(measurement,),
            segmentations=(segmentation,),
        )
        self.assertEqual(result.counts()["skipped_fragments"], 0)
        self.assertEqual(result.counts()["accepted_candidates"], 1)


class PoolTests(ExtractionTestCase):
    def test_every_accepted_candidate_becomes_a_member(self) -> None:
        auto, _ = proposals_from_segmentation(
            self.segmentation, measurement=self.measurement
        )
        result = self.extract(auto)
        self.assertEqual(
            {entry.candidate_id for entry in result.pool.entries},
            {candidate.candidate_id for candidate in result.candidates},
        )
        self.assertEqual(len(result.pool.entries), 4)

    def test_the_pool_schema_is_unchanged_and_semantic_free(self) -> None:
        auto, _ = proposals_from_segmentation(
            self.segmentation, measurement=self.measurement
        )
        result = self.extract(auto)
        document = json.loads(render_extraction(result))
        self.assertEqual(document["pool_id"], result.pool.pool_id)
        from src.ai_autocut.candidate_pool import parse_candidate_pool, render_candidate_pool

        rendered = render_candidate_pool(result.pool)
        pool_document = json.loads(rendered)
        self.assertEqual(
            sorted(pool_document), ["entries", "pool_id", "schema_version"]
        )
        self.assertEqual(pool_document["schema_version"], "candidate_pool.v1")
        for entry in pool_document["entries"]:
            self.assertEqual(sorted(entry), ["candidate_id"])
        for marker in ("score", "label", "confidence", "claim", "WHY_KEEP", "approval"):
            self.assertNotIn(marker, rendered)
        self.assertEqual(parse_candidate_pool(pool_document), result.pool)

    def test_pool_identity_is_order_independent(self) -> None:
        first = WindowProposal(
            "wpropv1_first", WindowRule.SINGLE_SEGMENT, self.material, 0, 0, 30, "a", (0,)
        )
        second = WindowProposal(
            "wpropv1_second", WindowRule.SINGLE_SEGMENT, self.material, 0, 45, 75, "b", (2,)
        )
        forward = self.extract([first, second])
        backward = self.extract([second, first])
        self.assertEqual(forward.pool.pool_id, backward.pool.pool_id)
        self.assertEqual(
            render_extraction(forward),
            render_extraction(
                self.extract([first, second])
            ),
        )

    def test_the_extended_catalog_resolves_the_new_candidates(self) -> None:
        auto, _ = proposals_from_segmentation(
            self.segmentation, measurement=self.measurement
        )
        result = self.extract(auto)
        for candidate in result.candidates:
            self.assertEqual(
                result.catalog.candidate(candidate.candidate_id).candidate_id,
                candidate.candidate_id,
            )
        self.assertEqual(len(result.catalog.candidates), len(result.candidates))

    def test_extraction_is_deterministic(self) -> None:
        auto, _ = proposals_from_segmentation(
            self.segmentation, measurement=self.measurement
        )
        first = render_extraction(self.extract(auto))
        second = render_extraction(self.extract(auto))
        self.assertEqual(first, second)
        self.assertEqual(
            hashlib.sha256(first.encode()).hexdigest(),
            hashlib.sha256(second.encode()).hexdigest(),
        )


class ProposalDocumentTests(ExtractionTestCase):
    def test_the_canonical_fixture_parses_and_round_trips(self) -> None:
        raw = PROPOSALS_FIXTURE.read_text(encoding="utf-8")
        proposals = parse_window_proposals(json.loads(raw))
        self.assertEqual(render_window_proposals(proposals), raw)
        rules = {proposal.rule for proposal in proposals}
        self.assertEqual(
            rules,
            {
                WindowRule.SINGLE_SEGMENT,
                WindowRule.ADJACENT_MERGE,
                WindowRule.ACTION_SAFE_WINDOW,
                WindowRule.SHORTER_ACTION_WINDOW,
            },
        )

    def test_the_proposal_document_is_exact_key(self) -> None:
        payload = json.loads(PROPOSALS_FIXTURE.read_text(encoding="utf-8"))
        payload["proposals"][0]["confidence"] = 0.9
        with self.assertRaises(CandidateExtractionError):
            parse_window_proposals(payload)
        payload = json.loads(PROPOSALS_FIXTURE.read_text(encoding="utf-8"))
        del payload["proposals"][0]["segment_indices"]
        with self.assertRaises(CandidateExtractionError):
            parse_window_proposals(payload)
        payload = json.loads(PROPOSALS_FIXTURE.read_text(encoding="utf-8"))
        payload["proposals"][0]["rule"] = "WHATEVER_LOOKS_GOOD"
        with self.assertRaises(CandidateExtractionError):
            parse_window_proposals(payload)

    def test_bad_action_chronology_in_a_proposal_is_refused(self) -> None:
        payload = json.loads(PROPOSALS_FIXTURE.read_text(encoding="utf-8"))
        for item in payload["proposals"]:
            if item["rule"] == "ACTION_SAFE_WINDOW":
                item["action_evidence"] = {
                    "preparation_start": 88,
                    "action_onset": 108,
                    "action_completion": 95,
                    "result_end_exclusive": 118,
                }
                break
        with self.assertRaises(CandidateExtractionError):
            parse_window_proposals(payload)


class CanonicalChainTests(ExtractionTestCase):
    """The whole extraction stage over the canonical fixture chain."""

    def setUp(self) -> None:
        super().setUp()
        from src.ai_autocut.candidate_analysis import (
            parse_measurements,
            parse_segmentations,
        )

        self.catalog_fixture = parse_identity_catalog(
            json.loads(CATALOG_FIXTURE.read_text(encoding="utf-8"))
        )
        self.measurements = parse_measurements(
            json.loads(MEASUREMENTS_FIXTURE.read_text(encoding="utf-8"))
        )
        self.segmentations = parse_segmentations(
            json.loads(SEGMENTATIONS_FIXTURE.read_text(encoding="utf-8"))
        )
        self.proposals = parse_window_proposals(
            json.loads(PROPOSALS_FIXTURE.read_text(encoding="utf-8"))
        )
        self.result = extract_candidates(
            catalog=self.catalog_fixture,
            measurements=self.measurements,
            segmentations=self.segmentations,
            proposals=self.proposals,
        )

    def test_the_chain_extracts_the_expected_candidates(self) -> None:
        self.assertEqual(len(self.measurements), 2)
        self.assertEqual(len(self.segmentations), 2)
        self.assertEqual(len(self.proposals), 11)
        counts = self.result.counts()
        self.assertEqual(counts["materials"], 2)
        self.assertEqual(counts["visual_segments"], 7)
        self.assertEqual(counts["candidate_proposals"], 11)
        self.assertEqual(counts["accepted_candidates"], 6)
        self.assertEqual(counts["rejected_proposals"], 5)
        self.assertEqual(counts["candidate_pool_size"], 6)

    def test_every_rejection_named_a_reason(self) -> None:
        self.assertEqual(
            self.result.rejection_counts(),
            {
                "ACTION_NOT_CROSSING_BOUNDARY": 1,
                "DUPLICATE_IDENTITY": 1,
                "OUT_OF_MATERIAL_BOUNDS": 1,
                "UNREGISTERED_MATERIAL": 1,
                "WINDOW_NOT_ACTION_SAFE": 1,
            },
        )
        for outcome in self.result.rejected:
            self.assertIs(outcome.decision, ProposalDecision.REJECTED)
            self.assertIsNotNone(outcome.rejection)
            self.assertIsNone(outcome.candidate)

    def test_the_variable_frame_rate_material_is_measured_not_assumed(self) -> None:
        beauty = next(
            outcome
            for outcome in self.result.outcomes
            if outcome.proposal.proposal_id == "wpropv1_beauty"
        )
        measured = beauty.measured
        self.assertIsNotNone(measured)
        assert measured is not None
        self.assertTrue(measured.variable_frame_rate)
        self.assertEqual(measured.frame_count, 40)
        # 40 frames is not 40/30 seconds on a variable frame rate source.
        self.assertNotAlmostEqual(
            measured.duration_seconds, round(40 / 30, 6), places=5
        )

    def test_the_extraction_document_uses_the_registry_schema(self) -> None:
        document = json.loads(render_extraction(self.result))
        self.assertEqual(document["schema_version"], SCHEMA_VERSION)
        self.assertEqual(document["counts"]["accepted_candidates"], 6)
        self.assertEqual(len(document["accepted_candidates"]), 6)
        for entry in document["accepted_candidates"]:
            self.assertIn("candidate_id", entry)
            self.assertIn("material_id", entry)
            self.assertIn("measured", entry)
            self.assertIn(entry["rule"], {rule.value for rule in WindowRule})


def _has_real_tools() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _run(command: list[str], label: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"{label} failed: {result.stderr[-300:]}")


def build_cfr_scene_clip(path: Path) -> Path:
    """A real 30 fps file with two hard visual cuts at 1.0 s and 2.0 s."""

    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=red:size=64x64:rate=30:duration=1",
            "-f", "lavfi", "-i", "color=c=blue:size=64x64:rate=30:duration=1",
            "-f", "lavfi", "-i", "color=c=green:size=64x64:rate=30:duration=1",
            "-filter_complex",
            "[0:v][1:v][2:v]concat=n=3:v=1[v]",
            "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
            str(path),
        ],
        "building the CFR scene clip",
    )
    return path


def build_vfr_clip(path: Path) -> Path:
    """A real variable-frame-rate file: 10 fps for one second, then 30 fps."""

    base = path.with_name("vfr-base.mp4")
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=red:size=64x64:rate=30:duration=1",
            "-f", "lavfi", "-i", "color=c=blue:size=64x64:rate=30:duration=1",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(base),
        ],
        "building the VFR base",
    )
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(base),
            "-vf", "select='if(lt(t,1),not(mod(n,3)),1)'", "-fps_mode", "vfr",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        "building the VFR clip",
    )
    return path


@unittest.skipUnless(_has_real_tools(), "ffmpeg and ffprobe are required")
class RealMediaBoundaryTests(unittest.TestCase):
    """Extraction against real decoded media with real measured timestamps.

    This is boundary and measurement validation. It is not semantic validation:
    no multimodal provider is called here.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp())
        cls.cfr = build_cfr_scene_clip(cls.tmp / "scenes.mp4")
        cls.vfr = build_vfr_clip(cls.tmp / "vfr.mp4")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_measured_duration_matches_the_timebase_adapter_exactly(self) -> None:
        adapter = TimebaseAdapter(fps=30)
        measurement = SourceMeasurement.from_source(
            material_id=MATERIAL, stream_index=0, source=str(self.cfr), adapter=adapter
        )
        self.assertEqual(measurement.timestamps, tuple(adapter.timing(str(self.cfr)).timestamps))
        self.assertFalse(measurement.is_variable_frame_rate)
        for start, end in ((0, 30), (5, 47), (0, measurement.frame_count)):
            self.assertAlmostEqual(
                measurement.measured_duration_frames(start, end),
                adapter.measured_duration_seconds(
                    source=str(self.cfr), source_in=start, source_out_exclusive=end
                ),
                places=6,
            )

    def test_real_vfr_source_keeps_its_own_cadence(self) -> None:
        adapter = TimebaseAdapter(fps=30)
        measurement = SourceMeasurement.from_source(
            material_id=MATERIAL, stream_index=0, source=str(self.vfr), adapter=adapter
        )
        self.assertTrue(measurement.is_variable_frame_rate)
        real = measurement.measured_duration_frames(0, measurement.frame_count)
        assumed = round(measurement.frame_count / 30, 6)
        self.assertGreater(abs(real - assumed), 0.1)
        self.assertAlmostEqual(
            real,
            adapter.measured_duration_seconds(
                source=str(self.vfr), source_in=0, source_out_exclusive=measurement.frame_count
            ),
            places=6,
        )

    def test_real_segmentation_becomes_real_candidates(self) -> None:
        adapter = TimebaseAdapter(fps=shot_understanding.CFR_FPS)
        measurement = SourceMeasurement.from_source(
            material_id=MATERIAL, stream_index=0, source=str(self.cfr), adapter=adapter
        )
        frame_count, differences = shot_understanding.decode_differences(str(self.cfr))
        # The analysis frame space is the source frame space only when the source is
        # CFR at the analysis rate and no frame was dropped. Assert it, do not assume it.
        self.assertFalse(measurement.is_variable_frame_rate)
        self.assertEqual(frame_count, measurement.frame_count)
        boundaries = shot_understanding.detect_boundaries(differences)
        self.assertEqual([boundary.frame_index for boundary in boundaries], [30, 60])
        segments, _ = shot_understanding.split_into_segments(
            0, frame_count, boundaries
        )
        segmentation = SourceSegmentation(
            material_id=MATERIAL,
            stream_index=0,
            segments=tuple(
                SegmentSpan(
                    segment_index=index,
                    start_frame=segment.start_frame,
                    end_frame_exclusive=segment.end_frame_exclusive,
                )
                for index, segment in enumerate(segments)
            ),
        )
        catalog = IdentityCatalog(
            materials=(MaterialIdentity(MATERIAL, SHA, 4096),), candidates=()
        )
        proposals, skipped = proposals_from_segmentation(
            segmentation, measurement=measurement
        )
        self.assertEqual(len(proposals), 3)
        self.assertEqual(skipped, ())
        result = extract_candidates(
            catalog=catalog,
            measurements=(measurement,),
            segmentations=(segmentation,),
            proposals=proposals,
        )
        self.assertEqual(len(result.candidates), 3)
        self.assertEqual(
            sorted(
                (item.start_frame, item.end_frame_exclusive)
                for item in result.candidates
            ),
            [(0, 30), (30, 60), (60, 90)],
        )

    def test_a_real_cross_segment_action_may_merge_two_segments(self) -> None:
        adapter = TimebaseAdapter(fps=shot_understanding.CFR_FPS)
        measurement = SourceMeasurement.from_source(
            material_id=MATERIAL, stream_index=0, source=str(self.cfr), adapter=adapter
        )
        segmentation = simple_segmentation(((0, 30), (30, 60), (60, 90)))
        action = ActionEvidence(10, 20, 40, 50)
        catalog = IdentityCatalog(
            materials=(MaterialIdentity(MATERIAL, SHA, 4096),), candidates=()
        )
        result = extract_candidates(
            catalog=catalog,
            measurements=(measurement,),
            segmentations=(segmentation,),
            proposals=(
                WindowProposal(
                    "wpropv1_real_merge", WindowRule.ADJACENT_MERGE, MATERIAL, 0, 0, 60,
                    "one action continues across the real cut at frame 30", (0, 1), (), action,
                ),
                WindowProposal(
                    "wpropv1_real_bounds", WindowRule.SINGLE_SEGMENT, MATERIAL, 0, 0, 120,
                    "a window past the real measured end", (0,),
                ),
            ),
        )
        merge = next(
            outcome
            for outcome in result.outcomes
            if outcome.proposal.proposal_id == "wpropv1_real_merge"
        )
        self.assertTrue(merge.accepted)
        assert merge.measured is not None
        self.assertEqual(merge.measured.frame_count, 60)
        self.assertAlmostEqual(merge.measured.duration_seconds, 2.0, places=3)
        bounds = next(
            outcome
            for outcome in result.outcomes
            if outcome.proposal.proposal_id == "wpropv1_real_bounds"
        )
        self.assertIs(bounds.rejection, RejectionCode.OUT_OF_MATERIAL_BOUNDS)


if __name__ == "__main__":
    unittest.main()
