import unittest

from src.ai_autocut.editing_intelligence import (
    ActionEvidence,
    EditingIntelligenceError,
    NarrativeRole,
    useful_action_range,
    validate_timeline_range,
)


class EditingIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.evidence = ActionEvidence(100, 112, 140, 165)

    def test_action_range_starts_on_action_and_keeps_result(self):
        self.assertEqual(useful_action_range(self.evidence), (112, 165))

    def test_action_requires_result(self):
        with self.assertRaisesRegex(EditingIntelligenceError, "result"):
            validate_timeline_range(
                role=NarrativeRole.HERO,
                start_frame=112,
                end_frame_exclusive=150,
                evidence=self.evidence,
            )

    def test_action_must_not_enter_late(self):
        with self.assertRaisesRegex(EditingIntelligenceError, "onset"):
            validate_timeline_range(
                role=NarrativeRole.ACTION,
                start_frame=120,
                end_frame_exclusive=165,
                evidence=self.evidence,
            )

    def test_non_action_range_needs_no_action_evidence(self):
        validate_timeline_range(
            role=NarrativeRole.HOOK, start_frame=0, end_frame_exclusive=30
        )
