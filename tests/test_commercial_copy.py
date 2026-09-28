"""Commercial Copy v1: two layers, three boundaries, and a derived status.

These tests hold the lines that make the copy layer trustworthy: a localised line may not
add a claim the semantic intent did not carry, a copy may not change the strategy it binds,
a forbidden or unresolved conditional claim can never enter a copy, designed silence is not
an empty track, a blocked attempt records what is missing instead of inventing it, and no
number exists here except a duration.

The artifact stays CONTRACT_ONLY / NOT_WIRED: no producer registered, no stage requires it,
no consumer reads it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
import re
import unittest

from src.ai_autocut import (
    commercial_copy,
    commercial_intelligence,
    commercial_strategy,
    fast_path,
    producer_registry,
)
from src.ai_autocut.commercial_copy import (
    AUTHORING_MODES,
    BACK_CHECK_FLAGS,
    BLOCK_REASON_CODES,
    DELIVERY,
    IMPLEMENTATION,
    RETURN_TARGETS,
    SKILL_NAME,
    VALIDATOR_NAME,
    WIRING_STATUS,
    CommercialCopyContractError,
    copy_structure,
    copy_structure_diff,
    parse_commercial_copy,
    render_commercial_copy,
    validate_commercial_copy,
)

REPO_ROOT = Path(__file__).parents[1]
MODULE_PATH = REPO_ROOT / "src" / "ai_autocut" / "commercial_copy.py"
SCHEMA_PATH = REPO_ROOT / "schemas" / "commercial_copy" / "commercial_copy.v1.schema.json"
CONTRACT_DOC = REPO_ROOT / "docs" / "contracts" / "commercial-copy-v1.md"
SKILL_DOC = REPO_ROOT / "docs" / "skills" / "commercial-copy-v1.md"
STRATEGY_PATH = REPO_ROOT / "examples" / "strategy" / "indonesia-faucet-filter-abc.json"
COPY_DIR = REPO_ROOT / "examples" / "strategy"

ARTIFACT = "strategy/commercial_copy.json"

FIXTURES = {
    "a": COPY_DIR / "indonesia-faucet-filter-copy-a.json",
    "b": COPY_DIR / "indonesia-faucet-filter-copy-b.json",
    "c": COPY_DIR / "indonesia-faucet-filter-copy-c.json",
    "blocked": COPY_DIR / "indonesia-faucet-filter-copy-result-first-blocked.json",
}

_STRATEGY_REF = "examples/strategy/indonesia-faucet-filter-abc.json"
_FACTS_REF = "brief/product_facts.json"
_EVIDENCE_REF = "evidence/visual-evidence-boundary.json"
_FACTS_SHA = "1" * 64
_EVIDENCE_SHA = "2" * 64
_LANGUAGE = "id-ID"

#: Assembled from fragments: the repository hygiene test scans every text file including
#: this one, and a literal personal path would trip its own scanner.
_ABSOLUTE_PROBE = "/" + "Users" + "/" + "someone" + "/copy.json"

#: Field names that would express a fabricated precision or a winner. None exists here.
_FORBIDDEN_FIELD_NAMES = (
    "score",
    "rank",
    "ranking",
    "confidence",
    "expected_performance",
    "winner",
    "best",
    "probability",
    "ctr",
    "cvr",
)


def _strategy_sha256() -> str:
    return hashlib.sha256(STRATEGY_PATH.read_bytes()).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _base_document() -> dict:
    """A minimal valid READY copy, deep-copied so a test can mutate it safely.

    It carries both layers and one designed-silence segment, so the two segment kinds are
    exercised by every mutation test that starts from here.
    """

    return json.loads(json.dumps({
        "schema_version": "commercial_copy.v1",
        "copy_id": "copy-under-test",
        "context": {
            "market": "INDONESIA",
            "language": _LANGUAGE,
            "platform": "TIKTOK",
            "platform_source": "DECLARED",
        },
        "strategy": {
            "ref": _STRATEGY_REF,
            "sha256": _strategy_sha256(),
            "variant_id": "A",
        },
        "boundaries": {
            "product_facts": {"ref": _FACTS_REF, "sha256": _FACTS_SHA},
            "visual_evidence_boundary": {
                "ref": _EVIDENCE_REF,
                "sha256": _EVIDENCE_SHA,
            },
        },
        "segments": [
            {
                "segment_id": "S01",
                "copy_job": "INSTALLATION",
                "delivery": "SPEECH",
                "semantic_intent": "say the filter is fitted by hand at the tap",
                "claim_refs": ["CLAIM-SIMPLE-TO-INSTALL"],
                "evidence_refs": ["EV-INSTALLATION"],
                "budget": {
                    "target_seconds": 2.4,
                    "acceptable_min_seconds": 2.0,
                    "acceptable_max_seconds": 2.8,
                },
                "localized": {
                    "language": _LANGUAGE,
                    "line": "Cukup dipasang dengan tangan ke keran.",
                },
                "designed_silence": None,
            },
            {
                "segment_id": "S02",
                "copy_job": "VISUAL_HOOK",
                "delivery": "DESIGNED_SILENCE",
                "semantic_intent": "let the fitting action carry the moment with no voice",
                "claim_refs": [],
                "evidence_refs": ["EV-INSTALLATION"],
                "budget": {
                    "target_seconds": 1.5,
                    "acceptable_min_seconds": 1.2,
                    "acceptable_max_seconds": 1.9,
                },
                "localized": None,
                "designed_silence": {
                    "reason": "the opening is carried by the visible action",
                    "bed_note": "the tap and kitchen sound in the footage continue; only the voice is absent",
                },
            },
        ],
        "semantic_back_check": {
            "findings": [
                {
                    "segment_id": "S01",
                    "adds_claim": False,
                    "expands_claim": False,
                    "drops_qualifier": False,
                    "possibility_as_certainty": False,
                    "unauthorised_product_fact": False,
                    "detail": None,
                    "verdict": "PASS",
                }
            ]
        },
        "blocking": [],
        "status": "READY",
        "provenance": {
            "authoring_mode": "AGENT_AUTHORED",
            "authored_by": {
                "actor": "CODEX_SUPERVISOR",
                "producer_id": "commercial-copy-author",
            },
            "skill": {"name": SKILL_NAME, "version": "1.0.0"},
            "validation": {"validator": VALIDATOR_NAME},
            "based_on": [
                {"ref": _STRATEGY_REF, "sha256": _strategy_sha256()},
                {"ref": _FACTS_REF, "sha256": _FACTS_SHA},
                {"ref": _EVIDENCE_REF, "sha256": _EVIDENCE_SHA},
            ],
        },
    }))


class _FixtureMixin:
    @classmethod
    def setUpClass(cls) -> None:
        cls.strategy = commercial_strategy.parse_commercial_strategy(_load(STRATEGY_PATH))
        cls.copies = {
            name: parse_commercial_copy(_load(path)) for name, path in FIXTURES.items()
        }


class ValidCopyTests(unittest.TestCase):
    def test_a_valid_copy_parses(self) -> None:
        copy = parse_commercial_copy(_base_document())
        self.assertEqual(copy.copy_id, "copy-under-test")
        self.assertEqual(copy.speech_segment_ids, ("S01",))
        self.assertEqual(copy.silence_segment_ids, ("S02",))
        self.assertEqual(copy.status, "READY")
        self.assertEqual(copy.derived_status, "READY")

    def test_the_contract_states_its_own_status(self) -> None:
        self.assertEqual(IMPLEMENTATION, "CONTRACT_ONLY")
        self.assertEqual(WIRING_STATUS, "NOT_WIRED")
        self.assertEqual(commercial_copy.CANONICAL_REF, ARTIFACT)
        self.assertEqual(commercial_copy.SCHEMA_VERSION, "commercial_copy.v1")
        self.assertEqual(SKILL_NAME, "commercial-copy")
        self.assertEqual(VALIDATOR_NAME, "commercial_copy.validate_commercial_copy")

    def test_both_layers_are_present_and_separate(self) -> None:
        copy = parse_commercial_copy(_base_document())
        segment = copy.segment("S01")
        self.assertTrue(segment.semantic_intent)
        self.assertIsNotNone(segment.localized)
        self.assertNotEqual(segment.semantic_intent, segment.localized.line)
        self.assertEqual(segment.localized.language, _LANGUAGE)

    def test_segments_render_ordered_by_id(self) -> None:
        document = _base_document()
        document["segments"] = list(reversed(document["segments"]))
        parsed = parse_commercial_copy(document)
        self.assertEqual(
            [item.segment_id for item in parsed.segments], ["S01", "S02"]
        )


class RequiredFieldTests(unittest.TestCase):
    def test_a_missing_document_field_fails(self) -> None:
        for key in (
            "schema_version", "copy_id", "context", "strategy", "boundaries",
            "segments", "semantic_back_check", "blocking", "status", "provenance",
        ):
            with self.subTest(key=key):
                document = _base_document()
                del document[key]
                with self.assertRaises(CommercialCopyContractError) as caught:
                    parse_commercial_copy(document)
                self.assertIn("missing required key", str(caught.exception))

    def test_a_missing_segment_field_fails(self) -> None:
        for key in (
            "segment_id", "copy_job", "delivery", "semantic_intent", "claim_refs",
            "evidence_refs", "budget", "localized", "designed_silence",
        ):
            with self.subTest(key=key):
                document = _base_document()
                del document["segments"][0][key]
                with self.assertRaises(CommercialCopyContractError) as caught:
                    parse_commercial_copy(document)
                self.assertIn("missing required key", str(caught.exception))

    def test_a_missing_budget_field_fails(self) -> None:
        for key in ("target_seconds", "acceptable_min_seconds", "acceptable_max_seconds"):
            with self.subTest(key=key):
                document = _base_document()
                del document["segments"][0]["budget"][key]
                with self.assertRaises(CommercialCopyContractError):
                    parse_commercial_copy(document)

    def test_an_unknown_key_fails(self) -> None:
        document = _base_document()
        document["segments"][0]["notes"] = "extra"
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("unsupported key", str(caught.exception))

    def test_a_wrong_schema_version_fails(self) -> None:
        document = _base_document()
        document["schema_version"] = "commercial_copy.v0"
        with self.assertRaises(CommercialCopyContractError):
            parse_commercial_copy(document)

    def test_a_multi_line_field_is_refused(self) -> None:
        for target in ("semantic_intent",):
            with self.subTest(target=target):
                document = _base_document()
                document["segments"][0][target] = "line one\nline two"
                with self.assertRaises(CommercialCopyContractError):
                    parse_commercial_copy(document)
        localized = _base_document()
        localized["segments"][0]["localized"]["line"] = "one\ntwo"
        with self.assertRaises(CommercialCopyContractError):
            parse_commercial_copy(localized)


class SegmentIdentityTests(unittest.TestCase):
    def test_a_duplicate_segment_id_fails(self) -> None:
        document = _base_document()
        document["segments"][1]["segment_id"] = "S01"
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("must not repeat", str(caught.exception))

    def test_a_malformed_segment_id_fails(self) -> None:
        for bad in ("", " S1", "S 1", "-S1", 7):
            with self.subTest(value=bad):
                document = _base_document()
                document["segments"][0]["segment_id"] = bad
                document["semantic_back_check"]["findings"][0]["segment_id"] = "S01"
                with self.assertRaises(CommercialCopyContractError):
                    parse_commercial_copy(document)

    def test_identity_is_not_an_array_position(self) -> None:
        """Reordering the document does not change any identity."""

        document = _base_document()
        document["segments"] = list(reversed(document["segments"]))
        parsed = parse_commercial_copy(document)
        self.assertEqual(parsed.segment("S01").copy_job, "INSTALLATION")
        self.assertEqual(parsed.segment("S02").copy_job, "VISUAL_HOOK")


class DeliveryTests(unittest.TestCase):
    def test_a_speech_segment_needs_a_localized_line(self) -> None:
        document = _base_document()
        document["segments"][0]["localized"] = None
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("must carry a localized line", str(caught.exception))

    def test_a_speech_segment_must_not_declare_designed_silence(self) -> None:
        document = _base_document()
        document["segments"][0]["designed_silence"] = {
            "reason": "x", "bed_note": "y"
        }
        with self.assertRaises(CommercialCopyContractError):
            parse_commercial_copy(document)

    def test_designed_silence_must_say_why_and_what_continues(self) -> None:
        for key in ("reason", "bed_note"):
            with self.subTest(key=key):
                document = _base_document()
                document["segments"][1]["designed_silence"] = {
                    "reason": "the visual carries it",
                    "bed_note": "the room sound continues",
                }
                del document["segments"][1]["designed_silence"][key]
                with self.assertRaises(CommercialCopyContractError):
                    parse_commercial_copy(document)

    def test_designed_silence_is_not_an_empty_track(self) -> None:
        """It must name what continues and must cite the evidence that carries it."""

        copy = parse_commercial_copy(_base_document())
        silence = copy.segment("S02")
        self.assertTrue(silence.is_designed_silence)
        self.assertIsNotNone(silence.designed_silence)
        self.assertTrue(silence.designed_silence.bed_note)
        self.assertTrue(silence.evidence_refs)

    def test_designed_silence_must_cite_evidence(self) -> None:
        document = _base_document()
        document["segments"][1]["evidence_refs"] = []
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("a visual carries it", str(caught.exception))

    def test_designed_silence_must_not_carry_a_localized_line(self) -> None:
        document = _base_document()
        document["segments"][1]["localized"] = {
            "language": _LANGUAGE, "line": "should not be here"
        }
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("not a missing line", str(caught.exception))

    def test_designed_silence_is_not_treated_as_missing_copy(self) -> None:
        """A silence segment parses, needs no finding, and does not fail anything."""

        copy = parse_commercial_copy(_base_document())
        self.assertEqual(copy.status, "READY")
        self.assertEqual(copy.failed_findings, ())
        self.assertNotIn("S02", [f.segment_id for f in copy.back_check])

    def test_an_unknown_delivery_fails(self) -> None:
        document = _base_document()
        document["segments"][0]["delivery"] = "WHISPER"
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("delivery must be one of", str(caught.exception))
        self.assertIn("SPEECH", DELIVERY)


class BudgetTests(unittest.TestCase):
    def test_a_target_outside_the_range_fails(self) -> None:
        document = _base_document()
        document["segments"][0]["budget"]["target_seconds"] = 4.0
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("inside the acceptable range", str(caught.exception))

    def test_an_inverted_range_fails(self) -> None:
        document = _base_document()
        document["segments"][0]["budget"] = {
            "target_seconds": 2.0,
            "acceptable_min_seconds": 3.0,
            "acceptable_max_seconds": 2.0,
        }
        with self.assertRaises(CommercialCopyContractError):
            parse_commercial_copy(document)

    def test_a_non_positive_duration_fails(self) -> None:
        document = _base_document()
        document["segments"][0]["budget"]["target_seconds"] = 0
        with self.assertRaises(CommercialCopyContractError):
            parse_commercial_copy(document)

    def test_the_budget_carries_no_frame_authority(self) -> None:
        """Timing belongs to the timeline; a frame count here is refused."""

        document = _base_document()
        document["segments"][0]["budget"]["frames"] = 72
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("only numbers this contract may carry are seconds", str(caught.exception))

    def test_a_number_that_is_not_a_duration_is_refused(self) -> None:
        document = _base_document()
        document["segments"][0]["confidence"] = 0.92
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("not a duration", str(caught.exception))

    def test_a_non_numeric_duration_fails(self) -> None:
        document = _base_document()
        document["segments"][0]["budget"]["target_seconds"] = "2.4"
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("must be a duration in seconds", str(caught.exception))


class BackCheckTests(unittest.TestCase):
    def test_a_missing_finding_fails(self) -> None:
        document = _base_document()
        document["semantic_back_check"]["findings"] = []
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("incomplete", str(caught.exception))

    def test_a_duplicate_finding_fails(self) -> None:
        document = _base_document()
        duplicate = dict(document["semantic_back_check"]["findings"][0])
        document["semantic_back_check"]["findings"].append(duplicate)
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("must not repeat", str(caught.exception))

    def test_a_finding_for_designed_silence_is_refused(self) -> None:
        document = _base_document()
        document["semantic_back_check"]["findings"].append({
            "segment_id": "S02",
            "adds_claim": False, "expands_claim": False, "drops_qualifier": False,
            "possibility_as_certainty": False, "unauthorised_product_fact": False,
            "detail": None, "verdict": "PASS",
        })
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("not speech", str(caught.exception))

    def test_a_verdict_that_contradicts_its_flags_is_refused(self) -> None:
        """The core anti-fabrication rule of the back-check."""

        document = _base_document()
        document["semantic_back_check"]["findings"][0]["expands_claim"] = True
        document["semantic_back_check"]["findings"][0]["verdict"] = "PASS"
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("derived from the findings", str(caught.exception))

    def test_any_true_flag_forces_fail(self) -> None:
        for flag in BACK_CHECK_FLAGS:
            with self.subTest(flag=flag):
                document = _base_document()
                finding = document["semantic_back_check"]["findings"][0]
                finding[flag] = True
                finding["verdict"] = "FAIL"
                finding["detail"] = "the wording exceeded the semantic intent"
                document["status"] = "BLOCKED"
                copy = parse_commercial_copy(document)
                self.assertEqual(copy.failed_findings[0].verdict, "FAIL")
                self.assertEqual(copy.status, "BLOCKED")

    def test_a_failed_finding_cannot_leave_the_copy_ready(self) -> None:
        """A finding that admits an exceedance forces BLOCKED, so READY is a contradiction."""

        document = _base_document()
        finding = document["semantic_back_check"]["findings"][0]
        finding["adds_claim"] = True
        finding["verdict"] = "FAIL"
        finding["detail"] = "the line added a claim the intent did not carry"
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("derives", str(caught.exception))

    def test_a_fail_must_state_what_exceeded_the_intent(self) -> None:
        document = _base_document()
        finding = document["semantic_back_check"]["findings"][0]
        finding["adds_claim"] = True
        finding["verdict"] = "FAIL"
        finding["detail"] = None
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("must state what exceeded", str(caught.exception))

    def test_the_indonesia_expansion_case_is_detected(self) -> None:
        """intent: attaches at the tap outlet -> line: suitable for every tap."""

        document = _base_document()
        document["segments"][0]["semantic_intent"] = (
            "say the filter attaches at the tap outlet"
        )
        document["segments"][0]["localized"]["line"] = (
            "Cocok untuk semua keran dan sangat mudah dipasang."
        )
        document["semantic_back_check"]["findings"][0]["expands_claim"] = True
        document["semantic_back_check"]["findings"][0]["adds_claim"] = True
        document["semantic_back_check"]["findings"][0]["verdict"] = "FAIL"
        document["semantic_back_check"]["findings"][0]["detail"] = (
            "the line widens the attachment to every tap and adds an ease-of-installation claim"
        )
        document["status"] = "BLOCKED"
        copy = parse_commercial_copy(document)
        self.assertEqual(copy.status, "BLOCKED")
        self.assertEqual(
            copy.failed_findings[0].segment_id, "S01"
        )

    def test_a_true_flag_without_a_verdict_contradiction_still_blocks(self) -> None:
        document = _base_document()
        finding = document["semantic_back_check"]["findings"][0]
        finding["drops_qualifier"] = True
        finding["verdict"] = "FAIL"
        finding["detail"] = "the qualifier was dropped"
        document["status"] = "BLOCKED"
        copy = parse_commercial_copy(document)
        self.assertEqual(copy.derived_status, "BLOCKED")

    def test_flags_must_be_booleans(self) -> None:
        document = _base_document()
        document["semantic_back_check"]["findings"][0]["adds_claim"] = "no"
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("must be a boolean", str(caught.exception))


class BlockingTests(unittest.TestCase):
    def test_ready_must_have_no_blocking_condition(self) -> None:
        document = _base_document()
        document["blocking"] = [{
            "segment_id": None,
            "reason_code": "REQUIRED_EVIDENCE_ABSENT",
            "reason": "the footage is missing",
            "claim_ref": None,
            "missing": ["footage"],
            "return_to": "VISUAL_EVIDENCE",
        }]
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("derives", str(caught.exception))

    def test_blocked_must_record_a_cause(self) -> None:
        document = _base_document()
        document["status"] = "BLOCKED"
        with self.assertRaises(CommercialCopyContractError):
            parse_commercial_copy(document)

    def test_every_blocking_field_is_required(self) -> None:
        for key in (
            "segment_id", "reason_code", "reason", "claim_ref", "missing", "return_to",
        ):
            with self.subTest(key=key):
                document = _load(FIXTURES["blocked"])
                del document["blocking"][0][key]
                with self.assertRaises(CommercialCopyContractError):
                    parse_commercial_copy(document)

    def test_a_blocking_condition_must_state_what_is_missing(self) -> None:
        document = _load(FIXTURES["blocked"])
        document["blocking"][0]["missing"] = []
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("must not be empty", str(caught.exception))

    def test_an_unknown_reason_code_or_return_target_fails(self) -> None:
        bad_code = _load(FIXTURES["blocked"])
        bad_code["blocking"][0]["reason_code"] = "SOMETHING_ELSE"
        with self.assertRaises(CommercialCopyContractError):
            parse_commercial_copy(bad_code)
        bad_target = _load(FIXTURES["blocked"])
        bad_target["blocking"][0]["return_to"] = "THIS_LAYER"
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(bad_target)
        self.assertIn("return_to must be one of", str(caught.exception))
        self.assertIn("COMMERCIAL_STRATEGY", RETURN_TARGETS)
        self.assertIn("CLAIM_FORBIDDEN_BY_BOUNDARY", BLOCK_REASON_CODES)

    def test_a_blockage_cannot_reference_an_undeclared_segment(self) -> None:
        document = _base_document()
        document["blocking"] = [{
            "segment_id": "S99",
            "reason_code": "REQUIRED_EVIDENCE_ABSENT",
            "reason": "missing footage for a segment that does not exist",
            "claim_ref": None,
            "missing": ["footage"],
            "return_to": "VISUAL_EVIDENCE",
        }]
        document["status"] = "BLOCKED"
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("does not declare", str(caught.exception))

    def test_a_blocked_copy_may_have_no_segments(self) -> None:
        copy = parse_commercial_copy(_load(FIXTURES["blocked"]))
        self.assertEqual(copy.segments, ())
        self.assertEqual(copy.status, "BLOCKED")
        self.assertEqual(len(copy.blocking), 3)

    def test_a_ready_copy_must_declare_a_segment(self) -> None:
        document = _base_document()
        document["segments"] = []
        document["semantic_back_check"]["findings"] = []
        with self.assertRaises(CommercialCopyContractError) as caught:
            parse_commercial_copy(document)
        self.assertIn("at least one segment", str(caught.exception))


class StrategyBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.strategy = commercial_strategy.parse_commercial_strategy(
            _load(STRATEGY_PATH)
        )

    def _copy(self, document: dict | None = None):
        return parse_commercial_copy(document or _base_document())

    def test_a_matching_copy_validates(self) -> None:
        validate_commercial_copy(self._copy(), self.strategy)

    def test_a_different_variant_fails(self) -> None:
        document = _base_document()
        document["strategy"]["variant_id"] = "Z"
        with self.assertRaises(CommercialCopyContractError) as caught:
            validate_commercial_copy(self._copy(document), self.strategy)
        self.assertIn("unknown variant_id", str(caught.exception))

    def test_a_different_market_fails(self) -> None:
        document = _base_document()
        document["context"]["market"] = "THAILAND"
        with self.assertRaises(CommercialCopyContractError) as caught:
            validate_commercial_copy(self._copy(document), self.strategy)
        self.assertIn("context.market", str(caught.exception))

    def test_a_different_boundary_revision_fails(self) -> None:
        document = _base_document()
        document["boundaries"]["visual_evidence_boundary"]["sha256"] = "3" * 64
        document["provenance"]["based_on"][2]["sha256"] = "3" * 64
        with self.assertRaises(CommercialCopyContractError) as caught:
            validate_commercial_copy(self._copy(document), self.strategy)
        self.assertIn("may not bind a different boundary revision", str(caught.exception))

    def test_a_claim_the_variant_did_not_select_fails(self) -> None:
        """A copy may not add a claim the chosen variant did not choose."""

        narrowed = dataclasses.replace(
            self.strategy.variant("A"), claims_used=("CLAIM-SIMPLE-TO-INSTALL",)
        )
        strategy = dataclasses.replace(
            self.strategy,
            variants=(narrowed,)
            + tuple(
                item
                for item in self.strategy.variants
                if item.variant_id != narrowed.variant_id
            ),
        )
        document = _base_document()
        document["segments"][0]["claim_refs"] = ["CLAIM-STRUCTURE-IS-VISIBLE"]
        document["segments"][0]["evidence_refs"] = ["EV-STRUCTURE-VISIBLE"]
        with self.assertRaises(CommercialCopyContractError) as caught:
            validate_commercial_copy(self._copy(document), strategy)
        self.assertIn("did not select", str(caught.exception))

    def test_a_forbidden_claim_fails(self) -> None:
        document = _base_document()
        document["segments"][0]["claim_refs"] = ["CLAIM-BEFORE-AFTER-FILTRATION-RESULT"]
        document["segments"][0]["evidence_refs"] = ["EV-INSTALLATION"]
        with self.assertRaises(CommercialCopyContractError) as caught:
            validate_commercial_copy(self._copy(document), self.strategy)
        self.assertIn("forbidden claim", str(caught.exception))

    def test_a_conditional_claim_fails(self) -> None:
        document = _base_document()
        document["segments"][0]["claim_refs"] = ["CLAIM-DIRECTION-ADJUSTABLE"]
        with self.assertRaises(CommercialCopyContractError) as caught:
            validate_commercial_copy(self._copy(document), self.strategy)
        self.assertIn("conditional claim", str(caught.exception))

    def test_an_undeclared_claim_fails(self) -> None:
        document = _base_document()
        document["segments"][0]["claim_refs"] = ["CLAIM-NEVER-DECLARED"]
        with self.assertRaises(CommercialCopyContractError) as caught:
            validate_commercial_copy(self._copy(document), self.strategy)
        self.assertIn("does not declare", str(caught.exception))

    def test_unknown_evidence_fails(self) -> None:
        document = _base_document()
        document["segments"][0]["evidence_refs"] = ["EV-INSTALLATION", "EV-INVENTED"]
        with self.assertRaises(CommercialCopyContractError) as caught:
            validate_commercial_copy(self._copy(document), self.strategy)
        self.assertIn("does not declare", str(caught.exception))

    def test_absent_evidence_fails(self) -> None:
        document = _base_document()
        document["segments"][0]["evidence_refs"] = [
            "EV-INSTALLATION", "EV-FILTRATION-RESULT"
        ]
        with self.assertRaises(CommercialCopyContractError) as caught:
            validate_commercial_copy(self._copy(document), self.strategy)
        self.assertIn("ABSENT", str(caught.exception))

    def test_a_claim_used_without_its_evidence_fails(self) -> None:
        document = _base_document()
        document["segments"][0]["evidence_refs"] = []
        with self.assertRaises(CommercialCopyContractError) as caught:
            validate_commercial_copy(self._copy(document), self.strategy)
        self.assertIn("does not cite evidence", str(caught.exception))

    def test_a_blockage_on_a_permitted_claim_fails(self) -> None:
        document = _base_document()
        document["blocking"] = [{
            "segment_id": None,
            "reason_code": "CLAIM_FORBIDDEN_BY_BOUNDARY",
            "reason": "blocked on a claim the boundary actually allows",
            "claim_ref": "CLAIM-SIMPLE-TO-INSTALL",
            "missing": ["nothing"],
            "return_to": "CLAIM_BOUNDARY",
        }]
        document["status"] = "BLOCKED"
        with self.assertRaises(CommercialCopyContractError) as caught:
            validate_commercial_copy(self._copy(document), self.strategy)
        self.assertIn("permit it", str(caught.exception))

    def test_a_blockage_must_declare_the_derived_missing_evidence(self) -> None:
        document = _base_document()
        document["blocking"] = [{
            "segment_id": None,
            "reason_code": "CONDITIONAL_CLAIM_UNSATISFIED",
            "reason": "the direction-change evidence is missing",
            "claim_ref": "CLAIM-DIRECTION-ADJUSTABLE",
            "missing": ["something vague"],
            "return_to": "VISUAL_EVIDENCE",
        }]
        document["status"] = "BLOCKED"
        with self.assertRaises(CommercialCopyContractError) as caught:
            validate_commercial_copy(self._copy(document), self.strategy)
        self.assertIn("EV-DIRECTION-CHANGE", str(caught.exception))

    def test_validation_refuses_the_wrong_type(self) -> None:
        with self.assertRaises(CommercialCopyContractError):
            validate_commercial_copy(self._copy(), object())


class StructureTests(_FixtureMixin, unittest.TestCase):
    """A/B/C differ in commercial structure, not in tone of voice."""

    def test_all_four_demonstrations_parse_and_bind(self) -> None:
        for name, copy in self.copies.items():
            with self.subTest(fixture=name):
                parse_commercial_copy(copy.as_dict())
                if name != "blocked":
                    validate_commercial_copy(copy, self.strategy)

    def test_a_b_c_are_structurally_distinct(self) -> None:
        for left, right in (("a", "b"), ("a", "c"), ("b", "c")):
            with self.subTest(left=left, right=right):
                diff = copy_structure_diff(self.copies[left], self.copies[right])
                self.assertFalse(diff["identical_structure"])
                self.assertTrue(diff["job_sequence_differs"])

    def test_b_is_not_a_rewritten_a(self) -> None:
        """B's structure is different, not A's sentences in a chattier voice."""

        a_structure = copy_structure(self.copies["a"])
        b_structure = copy_structure(self.copies["b"])
        self.assertNotEqual(
            [item["copy_job"] for item in a_structure],
            [item["copy_job"] for item in b_structure],
        )
        self.assertNotEqual(len(a_structure), len(b_structure))
        # B opens on context and asserts nothing about the product there.
        self.assertEqual(b_structure[0]["copy_job"], "DAILY_KITCHEN_CONTEXT")
        self.assertEqual(b_structure[0]["claim_refs"], [])
        # A opens on the product itself.
        self.assertEqual(a_structure[0]["copy_job"], "PRODUCT_IDENTITY")

    def test_c_opens_on_the_visual_with_designed_silence(self) -> None:
        structure = copy_structure(self.copies["c"])
        self.assertEqual(structure[0]["copy_job"], "VISUAL_ACTION_HOOK")
        self.assertEqual(structure[0]["delivery"], "DESIGNED_SILENCE")
        self.assertEqual(self.copies["c"].silence_segment_ids, ("C01",))

    def test_c_is_product_in_action_not_a_purification_result(self) -> None:
        copy = self.copies["c"]
        forbidden = set(self.strategy.claim_boundary.forbidden_ids)
        conditional = set(self.strategy.claim_boundary.conditional_ids)
        for segment in copy.segments:
            with self.subTest(segment=segment.segment_id):
                self.assertEqual(set(segment.claim_refs) & (forbidden | conditional), set())
        opening = copy.segment("C01")
        self.assertIn("product working in place", opening.semantic_intent)
        self.assertNotIn("FILTRATION", opening.copy_job)

    def test_a_and_c_share_boundaries_but_not_structure(self) -> None:
        diff = copy_structure_diff(self.copies["a"], self.copies["c"])
        self.assertFalse(diff["claims_differ"])
        self.assertFalse(diff["evidence_differ"])
        self.assertTrue(diff["delivery_sequence_differs"])
        self.assertTrue(diff["job_sequence_differs"])

    def test_structure_diff_refuses_the_wrong_type(self) -> None:
        with self.assertRaises(CommercialCopyContractError):
            copy_structure_diff(self.copies["a"], "not a copy")
        with self.assertRaises(CommercialCopyContractError):
            copy_structure("not a copy")

    def test_every_speech_segment_is_audited_and_silence_is_not(self) -> None:
        for name, copy in self.copies.items():
            with self.subTest(fixture=name):
                asked = [finding.segment_id for finding in copy.back_check]
                self.assertEqual(sorted(asked), sorted(copy.speech_segment_ids))


class SerializationTests(unittest.TestCase):
    def test_serialization_is_deterministic(self) -> None:
        first = render_commercial_copy(parse_commercial_copy(_base_document()))
        second = render_commercial_copy(parse_commercial_copy(_base_document()))
        self.assertEqual(first, second)
        self.assertTrue(first.endswith("}\n"))

    def test_key_order_does_not_change_the_rendering(self) -> None:
        shuffled = dict(reversed(list(_base_document().items())))
        self.assertEqual(
            render_commercial_copy(parse_commercial_copy(shuffled)),
            render_commercial_copy(parse_commercial_copy(_base_document())),
        )

    def test_a_render_round_trips(self) -> None:
        copy = parse_commercial_copy(_base_document())
        re_parsed = parse_commercial_copy(json.loads(render_commercial_copy(copy)))
        self.assertEqual(copy.as_dict(), re_parsed.as_dict())

    def test_status_travels_with_the_document(self) -> None:
        """A reader sees the derived status without re-deriving it, and cannot fake it."""

        copy = parse_commercial_copy(_load(FIXTURES["blocked"]))
        self.assertEqual(copy.as_dict()["status"], "BLOCKED")
        tampered = _load(FIXTURES["blocked"])
        tampered["status"] = "READY"
        with self.assertRaises(CommercialCopyContractError):
            parse_commercial_copy(tampered)


class NoFakeWinnerTests(unittest.TestCase):
    def test_a_numeric_score_or_winner_field_is_refused(self) -> None:
        """A fabricated number is refused twice over: unknown key, and not a duration."""

        for key in _FORBIDDEN_FIELD_NAMES:
            with self.subTest(key=key):
                document = _base_document()
                document["segments"][0][key] = 92
                with self.assertRaises(CommercialCopyContractError) as caught:
                    parse_commercial_copy(document)
                self.assertIn("not a duration", str(caught.exception))

    def test_a_non_numeric_score_or_winner_field_is_refused(self) -> None:
        for key in _FORBIDDEN_FIELD_NAMES:
            with self.subTest(key=key):
                document = _base_document()
                document["segments"][0][key] = "A"
                with self.assertRaises(CommercialCopyContractError) as caught:
                    parse_commercial_copy(document)
                self.assertIn("unsupported key", str(caught.exception))

    def test_a_document_level_winner_is_refused(self) -> None:
        for key in ("winner", "selected_variant", "recommended", "ranking"):
            with self.subTest(key=key):
                document = _base_document()
                document[key] = "A"
                with self.assertRaises(CommercialCopyContractError):
                    parse_commercial_copy(document)

    def test_no_number_in_a_fixture_is_anything_but_a_duration(self) -> None:
        for name, path in FIXTURES.items():
            with self.subTest(fixture=name):
                document = _load(path)

                def walk(value: object, path_label: str) -> None:
                    if isinstance(value, dict):
                        for key, item in value.items():
                            walk(item, f"{path_label}.{key}")
                    elif isinstance(value, list):
                        for index, item in enumerate(value):
                            walk(item, f"{path_label}[{index}]")
                    elif isinstance(value, bool) or value is None or isinstance(value, str):
                        return
                    else:
                        self.assertIsInstance(value, (int, float), path_label)
                        self.assertTrue(
                            path_label.split(".")[-1].endswith("_seconds"), path_label
                        )

                walk(document, name)


class SchemaFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_the_schema_is_closed(self) -> None:
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(
            self.schema["properties"]["schema_version"]["const"],
            commercial_copy.SCHEMA_VERSION,
        )
        self.assertFalse(
            self.schema["properties"]["segments"]["items"]["additionalProperties"]
        )

    def test_the_schema_lists_the_keys_the_parser_requires(self) -> None:
        self.assertEqual(
            set(self.schema["required"]),
            {
                "schema_version", "copy_id", "context", "strategy", "boundaries",
                "segments", "semantic_back_check", "blocking", "status", "provenance",
            },
        )
        self.assertEqual(
            set(self.schema["properties"]["segments"]["items"]["required"]),
            {
                "segment_id", "copy_job", "delivery", "semantic_intent", "claim_refs",
                "evidence_refs", "budget", "localized", "designed_silence",
            },
        )

    def test_the_schema_records_the_closed_vocabularies(self) -> None:
        segments = self.schema["properties"]["segments"]["items"]["properties"]
        self.assertEqual(tuple(segments["delivery"]["enum"]), DELIVERY)
        self.assertEqual(
            self.schema["properties"]["status"]["enum"], ["READY", "BLOCKED"]
        )
        self.assertEqual(
            tuple(
                self.schema["properties"]["blocking"]["items"]["properties"]
                ["return_to"]["enum"]
            ),
            RETURN_TARGETS,
        )
        self.assertEqual(
            tuple(
                self.schema["properties"]["provenance"]["properties"]
                ["authoring_mode"]["enum"]
            ),
            AUTHORING_MODES,
        )

    def test_the_schema_has_no_system_generated_mode(self) -> None:
        """The artifact may not claim a generation capability the repository lacks."""

        modes = (
            self.schema["properties"]["provenance"]["properties"]["authoring_mode"]
            ["enum"]
        )
        self.assertNotIn("SYSTEM_GENERATED", modes)
        self.assertEqual(tuple(modes), AUTHORING_MODES)

    def test_the_schema_offers_no_ranking_field(self) -> None:
        candidate_keys = set(self.schema["properties"])
        segment_keys = set(
            self.schema["properties"]["segments"]["items"]["properties"]
        )
        for name in _FORBIDDEN_FIELD_NAMES:
            with self.subTest(name=name):
                self.assertNotIn(name, candidate_keys)
                self.assertNotIn(name, segment_keys)

    def test_the_schema_status_matches_the_implementation(self) -> None:
        status = self.schema["x-status"]
        self.assertEqual(status["implementation"], IMPLEMENTATION)
        self.assertEqual(status["wiring_status"], WIRING_STATUS)
        self.assertIsNone(status["writer"])
        self.assertIsNone(status["reader"])
        self.assertFalse(status["producer_registered"])
        self.assertFalse(status["required_by_a_stage"])
        self.assertTrue(status["only_duration_numbers"])
        self.assertIn("commercial_strategy.v1", status["downstream_of"])


class SkillSpecificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SKILL_DOC.read_text(encoding="utf-8")

    def test_the_skill_specification_exists_and_is_named(self) -> None:
        self.assertIn("commercial-copy", self.text)
        self.assertIn("1.0.0", self.text)
        self.assertIn("commercial_copy.v1", self.text)

    def test_it_defines_the_role_and_the_boundary(self) -> None:
        for heading in (
            "## 1. Role",
            "## 2. Required inputs",
            "## 3. Allowed decisions",
            "## 4. Forbidden decisions",
            "## 5. STOP / BLOCK authority",
            "## 6. Back-check duty",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.text)

    def test_it_states_the_localization_principle(self) -> None:
        self.assertIn("how to say it", self.text.lower())
        self.assertIn("may not invent what may be said", self.text.lower())

    def test_it_grants_block_authority_and_no_evidence_authority(self) -> None:
        self.assertIn("never solved by inventing evidence", self.text)
        self.assertIn("MUST return `BLOCKED`", self.text)

    def test_it_is_a_specification_not_an_installed_skill(self) -> None:
        """AGENTS.md rule 9 keeps Agent skills outside this repository."""

        self.assertIn("specification", self.text.lower())
        self.assertIn("outside this repository", self.text)
        self.assertFalse((REPO_ROOT / "skills").exists())


class ContractOnlyTests(unittest.TestCase):
    """CONTRACT_ONLY / NOT_WIRED: nothing in production writes or reads this artifact."""

    def test_no_producer_is_registered(self) -> None:
        with self.assertRaises(producer_registry.ProducerRegistryError) as caught:
            producer_registry.producer_for(ARTIFACT)
        self.assertIn("NO PRODUCER", str(caught.exception))

    def test_no_mode_owns_the_artifact(self) -> None:
        self.assertIsNone(producer_registry.mode_of(ARTIFACT))

    def test_no_third_mode_scope_or_registry_was_added(self) -> None:
        for name in (
            "DECLARED_PRODUCERS",
            "DECLARED_ARTIFACTS",
            "DECLARED_PRODUCER_BY_ARTIFACT",
            "declared_producer_for",
            "declared_gate_for",
        ):
            with self.subTest(name=name):
                self.assertFalse(hasattr(producer_registry, name))
        self.assertEqual(producer_registry.MODES, ("LEGACY", "VNEXT_SHADOW"))

    def test_the_artifact_is_not_a_production_or_shadow_artifact(self) -> None:
        self.assertNotIn(ARTIFACT, producer_registry.REQUIRED_INPUT_ARTIFACTS)
        self.assertNotIn(ARTIFACT, producer_registry.AUTO_ARTIFACTS)
        self.assertNotIn(ARTIFACT, producer_registry.VNEXT_SHADOW_ARTIFACTS)

    def test_no_production_stage_declares_the_artifact(self) -> None:
        declared = {artifact for stage in fast_path.STAGES for artifact in stage.inputs}
        self.assertNotIn(ARTIFACT, declared)
        self.assertEqual(len(fast_path.SEMANTIC_STAGES), 8)

    def test_the_contract_does_not_register_itself(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("producer_registry", source)

    def test_the_contract_document_records_the_contract_only_status(self) -> None:
        text = CONTRACT_DOC.read_text(encoding="utf-8")
        self.assertIn("CONTRACT_ONLY", text)
        self.assertIn("NOT_WIRED", text)
        self.assertIn("No producer is registered", text)
        self.assertIn("hand-authored contract demonstrations", text)


class FamilyReuseTests(unittest.TestCase):
    """The copy layer reuses the family's vocabulary instead of inventing a fourth one."""

    def test_the_context_source_vocabulary_is_the_existing_one(self) -> None:
        self.assertEqual(
            commercial_copy.CONTEXT_SOURCES, commercial_intelligence.CONTEXT_SOURCES
        )
        self.assertEqual(
            commercial_copy.UNSPECIFIED_PLATFORM,
            commercial_intelligence.UNSPECIFIED_PLATFORM,
        )

    def test_the_claim_availability_derivation_is_the_existing_one(self) -> None:
        self.assertIs(
            commercial_copy.claim_availability,
            commercial_intelligence.claim_availability,
        )

    def test_the_author_type_is_the_existing_one(self) -> None:
        self.assertIs(
            commercial_copy.StrategyAuthor, commercial_strategy.StrategyAuthor
        )

    def test_the_copy_contract_does_not_redefine_the_boundary_parsers(self) -> None:
        """It binds the strategy and validates against it instead of re-parsing blocks."""

        for parser in (
            "parse_product_facts",
            "parse_evidence_boundary",
            "parse_claim_boundary",
        ):
            with self.subTest(parser=parser):
                self.assertIsNone(getattr(commercial_copy, parser, None))


class FixtureIntegrityTests(_FixtureMixin, unittest.TestCase):
    def test_the_fixtures_bind_a_strategy_revision_that_exists(self) -> None:
        """The strategy binding is verifiable, not decorative."""

        for name, copy in self.copies.items():
            with self.subTest(fixture=name):
                self.assertEqual(copy.strategy.ref, _STRATEGY_REF)
                self.assertEqual(copy.strategy.sha256, _strategy_sha256())

    def test_the_fixtures_bind_the_strategy_boundary_revisions(self) -> None:
        for name, copy in self.copies.items():
            with self.subTest(fixture=name):
                self.assertEqual(
                    copy.boundaries.product_facts.as_dict(),
                    self.strategy.product_facts.reference.as_dict(),
                )
                self.assertEqual(
                    copy.boundaries.visual_evidence_boundary.as_dict(),
                    self.strategy.visual_evidence_boundary.reference.as_dict(),
                )

    def test_the_fixtures_name_a_declared_variant(self) -> None:
        for name, copy in self.copies.items():
            with self.subTest(fixture=name):
                self.assertIn(
                    copy.strategy.variant_id,
                    [variant.variant_id for variant in self.strategy.variants],
                )

    def test_the_blocked_demonstration_returns_to_upstream_areas(self) -> None:
        copy = self.copies["blocked"]
        targets = {condition.return_to for condition in copy.blocking}
        self.assertEqual(
            targets, {"COMMERCIAL_STRATEGY", "CLAIM_BOUNDARY", "VISUAL_EVIDENCE"}
        )
        self.assertTrue(all(condition.missing for condition in copy.blocking))

    def test_the_fixtures_are_honestly_labelled_as_demonstrations(self) -> None:
        for name, path in FIXTURES.items():
            with self.subTest(fixture=name):
                document = _load(path)
                self.assertEqual(
                    document["provenance"]["authoring_mode"], "AGENT_AUTHORED"
                )
                self.assertEqual(document["provenance"]["skill"]["name"], SKILL_NAME)

    def test_the_fixtures_carry_no_media_and_no_machine_path(self) -> None:
        user_root = "/" + "Users" + "/"
        for name, path in FIXTURES.items():
            with self.subTest(fixture=name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn(user_root, text)
                self.assertIsNone(re.search(r"\.(mp4|mov|wav|mp3)\b", text))

    def test_a_malformed_reference_in_a_fixture_is_refused(self) -> None:
        document = _load(FIXTURES["a"])
        document["strategy"]["ref"] = _ABSOLUTE_PROBE
        with self.assertRaises(CommercialCopyContractError):
            parse_commercial_copy(document)


class NoProviderDependencyTests(unittest.TestCase):
    def test_the_module_makes_no_network_provider_or_tts_call(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "socket", "ssl", "http.client", "urllib", "requests", "httpx", "openai",
            "anthropic", "api_key", "subprocess", "ffmpeg", "doubao", "minimax", "tts",
        ):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_module_has_no_generation_entry_point(self) -> None:
        for name in commercial_copy.__all__:
            lowered = name.lower()
            for fragment in ("generate", "write_copy", "propose", "invent", "best",
                             "rank", "score", "winner"):
                with self.subTest(name=name, fragment=fragment):
                    self.assertNotIn(fragment, lowered.lower())

    def test_validation_is_pure(self) -> None:
        copy = parse_commercial_copy(_base_document())
        self.assertFalse(hasattr(copy, "job_root"))
        self.assertFalse(hasattr(copy, "path"))


if __name__ == "__main__":
    unittest.main()
