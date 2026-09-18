"""Review contract round-trip.

The defect: ``Review.as_dict()`` emitted a derived ``verdict`` field that
``parse_review()`` — correctly following ``review.v0.schema.json``, which declares
``additionalProperties: false`` — refused. A review document therefore could not survive
its own serialisation, which breaks the Write -> Read-back -> Validate discipline the
project requires of every backend write.

The fix follows the proven KN-01 ``audio_plan`` pattern: the serializer emits exactly the
fields the schema declares. ``verdict`` is a *derived property*, not an instance field, so
it is recomputed from the recorded findings after parsing. That is also the stronger
position — the reviewer policy says a verdict cannot be improved by rewriting a summary,
and a stored verdict that nothing verifies is exactly such a summary.
"""

from __future__ import annotations

import json
import unittest

from src.ai_autocut.review import (
    RELEASE_VERDICTS,
    REVIEWER_DIMENSIONS,
    SCHEMA_VERSION,
    Finding,
    Review,
    ReviewContractError,
    build_targeted_repair,
    layers_for_repair,
    parse_review,
)

SCHEMA = "schemas/review/review.v0.schema.json"


def load_schema() -> dict:
    with open(SCHEMA, encoding="utf-8") as handle:
        return json.load(handle)


def review_with(severities: dict[str, str], *, accepted: tuple[str, ...] = ()) -> Review:
    findings = tuple(
        Finding(
            dimension=dimension,
            severity=severities.get(dimension, "PASS"),
            detail=f"{dimension} measured",
            accepted=dimension in accepted,
        )
        for dimension in REVIEWER_DIMENSIONS
    )
    return Review(reviewer_id="reviewer-1", executor_id="executor-1", findings=findings)


class ReviewRoundTripTests(unittest.TestCase):
    def test_a_review_survives_its_own_serialisation(self) -> None:
        original = review_with({})
        document = original.as_dict()
        restored = parse_review(json.loads(json.dumps(document)))
        self.assertEqual(restored.reviewer_id, original.reviewer_id)
        self.assertEqual(restored.executor_id, original.executor_id)
        self.assertEqual(restored.findings, original.findings)

    def test_verdict_is_recomputed_and_still_correct(self) -> None:
        for severities, expected in (
            ({}, "PRODUCTION_READY"),
            ({"rhythm": "WEAK"}, "NEEDS_REPAIR"),
            ({"rhythm": "FAIL"}, "NEEDS_REPAIR"),
            ({"shot_selection": "CRITICAL"}, "REJECT"),
        ):
            with self.subTest(expected=expected):
                original = review_with(severities)
                restored = parse_review(original.as_dict())
                self.assertEqual(original.verdict, expected)
                self.assertEqual(restored.verdict, expected)

    def test_the_document_carries_exactly_the_schema_fields(self) -> None:
        schema = load_schema()
        document = review_with({}).as_dict()
        self.assertEqual(set(document), set(schema["properties"]))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(document["schema_version"], SCHEMA_VERSION)

    def test_verdict_is_not_serialised(self) -> None:
        self.assertNotIn("verdict", review_with({}).as_dict())

    def test_a_serialised_verdict_cannot_be_smuggled_back_in(self) -> None:
        """A stored verdict is refused rather than trusted.

        Reconstruction is the only way to obtain a verdict, so a document cannot
        assert one that its own findings do not support.
        """

        document = review_with({})
        tampered = dict(document.as_dict())
        tampered["verdict"] = "PRODUCTION_READY"
        with self.assertRaises(ReviewContractError):
            parse_review(tampered)

    def test_an_incomplete_review_is_refused_after_round_trip(self) -> None:
        document = review_with({}).as_dict()
        document["findings"] = document["findings"][:-1]
        with self.assertRaises(ReviewContractError):
            parse_review(document)

    def test_accepted_weak_findings_survive(self) -> None:
        original = review_with({"rhythm": "WEAK"}, accepted=("rhythm",))
        restored = parse_review(original.as_dict())
        self.assertEqual(restored.verdict, "PRODUCTION_READY")
        self.assertTrue(
            next(f for f in restored.findings if f.dimension == "rhythm").accepted
        )

    def test_repair_plan_derives_from_a_restored_review(self) -> None:
        restored = parse_review(review_with({"rhythm": "FAIL"}).as_dict())
        plan = build_targeted_repair(restored, ["U01"])
        self.assertEqual(plan.affected_dimensions, ("rhythm",))
        self.assertFalse(plan.regenerate_entire_video)
        self.assertEqual(layers_for_repair(plan), ("editing",))

    def test_every_release_verdict_is_reachable(self) -> None:
        produced = {
            parse_review(review_with(severities).as_dict()).verdict
            for severities in ({}, {"rhythm": "WEAK"}, {"rhythm": "CRITICAL"})
        }
        self.assertEqual(produced, set(RELEASE_VERDICTS))


if __name__ == "__main__":
    unittest.main()
