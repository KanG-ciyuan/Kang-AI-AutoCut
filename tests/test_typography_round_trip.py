"""Typography policy round-trip.

The defect: ``TypographyPlan.as_dict()`` emitted ``policy_status`` and
``placement_implementation``, which ``parse_typography_plan()`` — correctly following
``typography_policy.v0.schema.json`` — refused. A typography plan could not survive its
own serialisation.

The fix follows the KN-01 ``audio_plan`` pattern: the serializer emits exactly the fields
the schema declares, and module status stays reachable through
``POLICY_STATUS`` / ``PLACEMENT_IMPLEMENTATION`` and ``TypographyPlan.status``.

Note on scope: this fixes the *serializer*. It deliberately does not make the validator
accept the historical SKU#1 ``editorial_text_plan.json``, which carries nine unrelated
extra keys and a richer motion vocabulary. That incompatibility is recorded as a known
limitation and is out of scope.
"""

from __future__ import annotations

import json
import unittest

from src.ai_autocut.typography import (
    DEFAULT_VISUAL_DIRECTION,
    MINIMUM_CONSIDERATIONS,
    PLACEMENT_IMPLEMENTATION,
    POLICY_STATUS,
    SCHEMA_VERSION,
    TextEvent,
    TypographyPlan,
    TypographyPolicyError,
    parse_typography_plan,
)

SCHEMA = "schemas/typography/typography_policy.v0.schema.json"


def load_schema() -> dict:
    with open(SCHEMA, encoding="utf-8") as handle:
        return json.load(handle)


def event(**overrides: object) -> TextEvent:
    fields: dict[str, object] = {
        "event_id": "E1",
        "role": "hook",
        "lines": ("HELLO",),
        "motion": "fade",
        "considered_zones": MINIMUM_CONSIDERATIONS,
        "emphasis_terms": (),
        "safe_area_verified": True,
    }
    fields.update(overrides)
    return TextEvent(**fields)  # type: ignore[arg-type]


def plan(*events: TextEvent) -> TypographyPlan:
    return TypographyPlan(
        visual_direction=DEFAULT_VISUAL_DIRECTION,
        events=events or (event(),),
    )


class TypographyRoundTripTests(unittest.TestCase):
    def test_a_plan_survives_its_own_serialisation(self) -> None:
        original = plan(event(event_id="E1", role="hook"), event(event_id="E2", role="cta"))
        restored = parse_typography_plan(json.loads(json.dumps(original.as_dict())))
        self.assertEqual(restored.visual_direction, original.visual_direction)
        self.assertEqual(restored.events, original.events)

    def test_the_document_carries_exactly_the_schema_fields(self) -> None:
        schema = load_schema()
        document = plan().as_dict()
        self.assertEqual(set(document), set(schema["properties"]))
        self.assertEqual(document["schema_version"], SCHEMA_VERSION)

    def test_module_status_is_not_an_instance_field(self) -> None:
        document = plan().as_dict()
        self.assertNotIn("policy_status", document)
        self.assertNotIn("placement_implementation", document)

    def test_module_status_remains_reported(self) -> None:
        """Removing it from the document must not remove it from the system."""

        self.assertEqual(plan().status, POLICY_STATUS)
        self.assertEqual(POLICY_STATUS, "POLICY_VALIDATED_IMPLEMENTATION_PENDING")
        self.assertEqual(PLACEMENT_IMPLEMENTATION, "NOT_IMPLEMENTED")

    def test_the_schema_still_records_the_status(self) -> None:
        schema = load_schema()
        self.assertEqual(schema["x-policy"]["status"], POLICY_STATUS)
        self.assertEqual(
            schema["x-policy"]["placement_implementation"], PLACEMENT_IMPLEMENTATION
        )

    def test_a_smuggled_status_field_is_refused(self) -> None:
        document = plan().as_dict()
        document["placement_implementation"] = "IMPLEMENTED"
        with self.assertRaises(TypographyPolicyError):
            parse_typography_plan(document)

    def test_unreleasable_events_are_still_reported_after_round_trip(self) -> None:
        original = plan(event(safe_area_verified=False))
        restored = parse_typography_plan(original.as_dict())
        self.assertEqual(restored.unreleasable_events(), ("E1",))

    def test_the_historical_sku1_plan_is_still_out_of_scope(self) -> None:
        """Recorded, not repaired. This asserts the limitation stays visible.

        The documented production plan used a richer shape than the frozen policy
        vocabulary. Making the validator accept it would silently widen a frozen
        contract, so the incompatibility is kept and reported instead.
        """

        historical = {
            "schema_version": "typography_policy.v0",
            "visual_direction": DEFAULT_VISUAL_DIRECTION,
            "canonical_policy": {},
            "claim_validation": {},
            "editorial_rule": {},
            "event_count": 5,
            "gate": "D.1",
            "job_id": "filter-first-job-v1",
            "safe_area": {},
            "type_scale": {},
            "variant": "A",
            "events": [],
        }
        with self.assertRaises(TypographyPolicyError) as caught:
            parse_typography_plan(historical)
        self.assertIn("unsupported key", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
