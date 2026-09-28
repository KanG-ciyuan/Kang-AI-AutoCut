"""Commercial Strategy v1 contract, validation and its contract-only status.

The chain Market -> Consumer Insight -> Commercial Strategy -> Commercial Copy had a
producer for its last link only, so a strategy could be decided without anything recording
it. These tests hold the fix: the strategy is a validated artifact, a claim may not be
promoted past the evidence the material actually has, and a forbidden claim cannot be
re-introduced as an allowed one. The artifact stays CONTRACT_ONLY / NOT_WIRED - no
producer registered, no stage requires it, no consumer reads it - and these tests hold
that too, so a validated contract is never mistaken for a shipped capability.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

from src.ai_autocut import commercial_strategy, fast_path, producer_registry
from src.ai_autocut.commercial_strategy import (
    CLAIM_STATES,
    EVIDENCE_PRESENCE,
    IMPLEMENTATION,
    WIRING_STATUS,
    CommercialStrategyContractError,
    parse_commercial_strategy,
    render_commercial_strategy,
    strategy_differences,
    validate_against_product_facts,
)

REPO_ROOT = Path(__file__).parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "commercial_strategy" / "commercial_strategy.v1.schema.json"
EXAMPLE_PATH = REPO_ROOT / "examples" / "strategy" / "indonesia-faucet-filter-abc.json"
MODULE_PATH = REPO_ROOT / "src" / "ai_autocut" / "commercial_strategy.py"

ARTIFACT = "strategy/commercial_strategy.json"

_FACTS_REF = "brief/product_facts.json"
_EVIDENCE_REF = "evidence/visual-evidence-boundary.json"
_FACTS_SHA = "a" * 64
_EVIDENCE_SHA = "b" * 64

#: An absolute-path probe, assembled from fragments for the same reason
#: ``paths.MACHINE_PATH_PATTERNS`` is: the repository hygiene test scans every text
#: file including this one, and a literal personal path would trip its own scanner.
_ABSOLUTE_PROBE = "/" + "Users" + "/" + "someone" + "/evidence.json"
_VOLUME_ROOT = "/" + "Volumes" + "/"
_USER_ROOT = "/" + "Users" + "/"


def _base_document() -> dict:
    """A minimal valid document, deep-copied so a test can mutate it safely."""

    return json.loads(json.dumps({
        "schema_version": "commercial_strategy.v1",
        "strategy_id": "strategy-under-test",
        "market": "INDONESIA",
        "platform": "TIKTOK",
        "objective": "DIRECT_CONVERSION",
        "product": {"name": "Faucet Filter"},
        "target_consumer": "a buyer in a small rented kitchen",
        "consumer_insight": [
            {"insight_id": "INSIGHT-FITTING-LOOKS-HARD",
             "statement": "the buyer assumes a filter needs a plumber"},
        ],
        "product_facts": {
            "ref": _FACTS_REF,
            "sha256": _FACTS_SHA,
            "allowed_fact_refs": ["FACT-INSTALLATION", "FACT-DIRECTION-ADJUSTABLE"],
        },
        "visual_evidence_boundary": {
            "ref": _EVIDENCE_REF,
            "sha256": _EVIDENCE_SHA,
            "items": [
                {"evidence_id": "EV-INSTALLATION",
                 "statement": "the filter is fitted to a tap by hand",
                 "presence": "PRESENT"},
                {"evidence_id": "EV-DIRECTION-CHANGE",
                 "statement": "no clip shows the water behaviour changing",
                 "presence": "ABSENT"},
            ],
        },
        "claim_boundary": {
            "allowed": [
                {"claim_id": "CLAIM-SIMPLE-TO-INSTALL",
                 "statement": "the filter fits to the tap by hand",
                 "product_fact_ref": "FACT-INSTALLATION",
                 "evidence_ref": "EV-INSTALLATION"},
            ],
            "conditional": [
                {"claim_id": "CLAIM-DIRECTION-ADJUSTABLE",
                 "statement": "the outlet can be turned",
                 "product_fact_ref": "FACT-DIRECTION-ADJUSTABLE",
                 "requires_evidence_ref": "EV-DIRECTION-CHANGE",
                 "condition": "may be described as adjustable, never as a demonstrated change"},
            ],
            "forbidden": [
                {"claim_id": "CLAIM-REMOVES-VISIBLE-DIRT",
                 "statement": "the filter removes visible dirt",
                 "reason": "no clip shows dirt or dirt being removed"},
            ],
        },
        "variants": [
            {"variant_id": "A", "persuasion_job": "EXPLAIN",
             "hook_strategy": "open on the fitting action",
             "copy_direction": ["explain only what is visible"],
             "cta_direction": "go to the product page",
             "claims_used": ["CLAIM-SIMPLE-TO-INSTALL"]},
            {"variant_id": "B", "persuasion_job": "RELATE",
             "hook_strategy": "open on the everyday kitchen",
             "copy_direction": ["speak in the first person"],
             "cta_direction": "check the product page",
             "claims_used": ["CLAIM-SIMPLE-TO-INSTALL"]},
            {"variant_id": "C", "persuasion_job": "DEMONSTRATE",
             "hook_strategy": "open on the strongest visible action",
             "copy_direction": ["show the action before naming it"],
             "cta_direction": "see the product page",
             "claims_used": ["CLAIM-SIMPLE-TO-INSTALL"]},
        ],
        "provenance": {
            "authored_by": {"actor": "CODEX_SUPERVISOR",
                            "producer_id": "commercial-strategy-author"},
            "based_on": [
                {"ref": _FACTS_REF, "sha256": _FACTS_SHA},
                {"ref": _EVIDENCE_REF, "sha256": _EVIDENCE_SHA},
            ],
        },
    }))


class ValidStrategyTests(unittest.TestCase):
    def test_a_valid_strategy_parses(self) -> None:
        strategy = parse_commercial_strategy(_base_document())
        self.assertEqual(strategy.market, "INDONESIA")
        self.assertEqual(strategy.strategy_id, "strategy-under-test")
        self.assertEqual(len(strategy.variants), 3)
        self.assertIn("FACT-INSTALLATION", strategy.product_facts.allowed_fact_refs)

    def test_the_contract_states_its_own_implementation_status(self) -> None:
        self.assertEqual(IMPLEMENTATION, "CONTRACT_ONLY")
        self.assertEqual(WIRING_STATUS, "NOT_WIRED")
        self.assertEqual(CLAIM_STATES, ("ALLOWED", "CONDITIONAL", "FORBIDDEN"))
        self.assertEqual(EVIDENCE_PRESENCE, ("PRESENT", "ABSENT"))

    def test_the_canonical_reference_is_the_contract_path(self) -> None:
        self.assertEqual(commercial_strategy.CANONICAL_REF, ARTIFACT)
        self.assertEqual(commercial_strategy.SCHEMA_VERSION, "commercial_strategy.v1")


class RequiredFieldTests(unittest.TestCase):
    def test_a_missing_required_field_fails(self) -> None:
        for key in (
            "schema_version", "strategy_id", "market", "platform", "objective", "product",
            "target_consumer", "consumer_insight", "product_facts",
            "visual_evidence_boundary", "claim_boundary", "variants", "provenance",
        ):
            with self.subTest(key=key):
                document = _base_document()
                del document[key]
                with self.assertRaises(CommercialStrategyContractError) as caught:
                    parse_commercial_strategy(document)
                self.assertIn("missing required key", str(caught.exception))

    def test_an_unknown_key_fails(self) -> None:
        document = _base_document()
        document["final_copy"] = ["Beli sekarang!"]
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("unsupported key", str(caught.exception))

    def test_the_contract_cannot_carry_final_copy(self) -> None:
        """The four layers stay separate: there is nowhere to write the words."""

        for key in ("final_copy", "vo_lines", "subtitles", "cta_text"):
            with self.subTest(key=key):
                document = _base_document()
                document[key] = "text"
                with self.assertRaises(CommercialStrategyContractError):
                    parse_commercial_strategy(document)
        variant = _base_document()
        variant["variants"][0]["vo_line"] = "text"
        with self.assertRaises(CommercialStrategyContractError):
            parse_commercial_strategy(variant)

    def test_a_wrong_schema_version_fails(self) -> None:
        document = _base_document()
        document["schema_version"] = "commercial_strategy.v0"
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("schema_version", str(caught.exception))

    def test_empty_identity_fields_fail(self) -> None:
        for key in ("strategy_id", "market", "platform", "objective", "target_consumer"):
            with self.subTest(key=key):
                document = _base_document()
                document[key] = "   "
                with self.assertRaises(CommercialStrategyContractError):
                    parse_commercial_strategy(document)
        blank_product = _base_document()
        blank_product["product"]["name"] = ""
        with self.assertRaises(CommercialStrategyContractError):
            parse_commercial_strategy(blank_product)

    def test_an_empty_insight_or_variant_list_fails(self) -> None:
        no_insight = _base_document()
        no_insight["consumer_insight"] = []
        with self.assertRaises(CommercialStrategyContractError):
            parse_commercial_strategy(no_insight)
        no_variants = _base_document()
        no_variants["variants"] = []
        with self.assertRaises(CommercialStrategyContractError):
            parse_commercial_strategy(no_variants)


class VariantIdentityTests(unittest.TestCase):
    def test_a_duplicate_variant_id_fails(self) -> None:
        document = _base_document()
        document["variants"][2]["variant_id"] = "A"
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("variant_id", str(caught.exception))

    def test_a_malformed_variant_id_fails(self) -> None:
        for bad in ("", " A", "A B", "-A", 7):
            with self.subTest(value=bad):
                document = _base_document()
                document["variants"][0]["variant_id"] = bad
                with self.assertRaises(CommercialStrategyContractError):
                    parse_commercial_strategy(document)

    def test_three_variants_may_share_a_boundary_and_still_differ(self) -> None:
        strategy = parse_commercial_strategy(_base_document())
        differences = strategy_differences(strategy)
        self.assertEqual(
            differences["differing_fields"],
            ["copy_direction", "cta_direction", "hook_strategy", "persuasion_job"],
        )
        self.assertEqual(differences["identical_fields"], ["claims_used"])
        shared = differences["shared"]
        self.assertEqual(shared["market"], "INDONESIA")
        self.assertEqual(
            shared["visual_evidence_boundary"], {"ref": _EVIDENCE_REF, "sha256": _EVIDENCE_SHA}
        )
        self.assertEqual(sorted(shared["allowed_claim_ids"]), ["CLAIM-SIMPLE-TO-INSTALL"])
        self.assertEqual(
            sorted(differences["variants"]), ["A", "B", "C"]
        )

    def test_the_document_level_boundary_cannot_drift_per_variant(self) -> None:
        """There is no per-variant evidence or claim boundary field to drift into."""

        for key in (
            "product_facts", "visual_evidence_boundary", "claim_boundary", "market",
            "platform", "objective", "target_consumer",
        ):
            with self.subTest(key=key):
                document = _base_document()
                document["variants"][0][key] = {}
                with self.assertRaises(CommercialStrategyContractError) as caught:
                    parse_commercial_strategy(document)
                self.assertIn("unsupported key", str(caught.exception))


class ClaimBoundaryTests(unittest.TestCase):
    def test_a_duplicate_claim_id_fails(self) -> None:
        document = _base_document()
        document["claim_boundary"]["conditional"].append(
            dict(document["claim_boundary"]["conditional"][0])
        )
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("must not repeat", str(caught.exception))

    def test_a_forbidden_claim_cannot_be_represented_as_allowed(self) -> None:
        """The contradiction rule is what closes this door."""

        document = _base_document()
        forbidden = dict(document["claim_boundary"]["forbidden"][0])
        document["claim_boundary"]["allowed"].append(
            {"claim_id": forbidden["claim_id"],
             "statement": forbidden["statement"],
             "product_fact_ref": "FACT-INSTALLATION",
             "evidence_ref": "EV-INSTALLATION"}
        )
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("must not repeat", str(caught.exception))

    def test_a_forbidden_claim_cannot_be_used_by_a_variant(self) -> None:
        document = _base_document()
        document["variants"][0]["claims_used"] = ["CLAIM-REMOVES-VISIBLE-DIRT"]
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("forbidden claim", str(caught.exception))

    def test_a_conditional_claim_cannot_be_used_as_though_its_condition_held(self) -> None:
        document = _base_document()
        document["variants"][0]["claims_used"] = ["CLAIM-DIRECTION-ADJUSTABLE"]
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("conditional claim", str(caught.exception))

    def test_a_variant_cannot_use_an_undeclared_claim(self) -> None:
        document = _base_document()
        document["variants"][0]["claims_used"] = ["CLAIM-NEVER-DECLARED"]
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("does not declare", str(caught.exception))

    def test_an_allowed_claim_naming_an_unpermitted_fact_fails(self) -> None:
        document = _base_document()
        document["claim_boundary"]["allowed"][0]["product_fact_ref"] = "FACT-INVENTED"
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("does not permit", str(caught.exception))

    def test_an_allowed_claim_resting_on_absent_evidence_fails(self) -> None:
        """This is what keeps a permitted product fact at CONDITIONAL."""

        document = _base_document()
        document["claim_boundary"]["allowed"][0]["evidence_ref"] = "EV-DIRECTION-CHANGE"
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("ABSENT", str(caught.exception))

    def test_an_allowed_claim_without_evidence_is_permitted(self) -> None:
        document = _base_document()
        document["claim_boundary"]["allowed"][0]["evidence_ref"] = None
        strategy = parse_commercial_strategy(document)
        self.assertIsNone(strategy.claim_boundary.allowed[0].evidence_ref)

    def test_a_conditional_claim_may_require_absent_evidence(self) -> None:
        strategy = parse_commercial_strategy(_base_document())
        conditional = strategy.claim_boundary.conditional[0]
        self.assertEqual(conditional.requires_evidence_ref, "EV-DIRECTION-CHANGE")
        self.assertEqual(
            strategy.visual_evidence_boundary.presence_of("EV-DIRECTION-CHANGE"), "ABSENT"
        )
        self.assertEqual(
            strategy.claim_boundary.state_of("CLAIM-DIRECTION-ADJUSTABLE"), "CONDITIONAL"
        )

    def test_a_missing_claim_condition_fails(self) -> None:
        document = _base_document()
        document["claim_boundary"]["conditional"][0]["condition"] = "  "
        with self.assertRaises(CommercialStrategyContractError):
            parse_commercial_strategy(document)

    def test_a_forbidden_claim_must_state_its_reason(self) -> None:
        document = _base_document()
        document["claim_boundary"]["forbidden"][0]["reason"] = " "
        with self.assertRaises(CommercialStrategyContractError):
            parse_commercial_strategy(document)

    def test_an_empty_claim_boundary_fails(self) -> None:
        document = _base_document()
        document["claim_boundary"] = {"allowed": [], "conditional": [], "forbidden": []}
        with self.assertRaises(CommercialStrategyContractError):
            parse_commercial_strategy(document)


class EvidenceReferenceTests(unittest.TestCase):
    def test_an_allowed_claim_naming_undeclared_evidence_fails(self) -> None:
        document = _base_document()
        document["claim_boundary"]["allowed"][0]["evidence_ref"] = "EV-INVENTED"
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("does not declare", str(caught.exception))

    def test_a_conditional_claim_naming_undeclared_evidence_fails(self) -> None:
        document = _base_document()
        document["claim_boundary"]["conditional"][0]["requires_evidence_ref"] = "EV-INVENTED"
        with self.assertRaises(CommercialStrategyContractError):
            parse_commercial_strategy(document)

    def test_a_duplicate_evidence_id_fails(self) -> None:
        document = _base_document()
        items = document["visual_evidence_boundary"]["items"]
        items.append(dict(items[0]))
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("must not repeat", str(caught.exception))

    def test_an_unknown_evidence_presence_fails(self) -> None:
        document = _base_document()
        document["visual_evidence_boundary"]["items"][0]["presence"] = "MAYBE"
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("presence", str(caught.exception))

    def test_a_malformed_evidence_reference_fails(self) -> None:
        for bad in (_ABSOLUTE_PROBE, "../evidence.json", "evidence.json ",
                    "evidence/visual.txt", ""):
            with self.subTest(value=bad):
                document = _base_document()
                document["visual_evidence_boundary"]["ref"] = bad
                with self.assertRaises(CommercialStrategyContractError):
                    parse_commercial_strategy(document)

    def test_a_malformed_sha256_fails(self) -> None:
        for bad in ("ABC", "z" * 64, "a" * 63, 7):
            with self.subTest(value=bad):
                document = _base_document()
                document["product_facts"]["sha256"] = bad
                with self.assertRaises(CommercialStrategyContractError):
                    parse_commercial_strategy(document)


class ProvenanceTests(unittest.TestCase):
    def test_provenance_is_required(self) -> None:
        document = _base_document()
        del document["provenance"]
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("provenance", str(caught.exception))

    def test_provenance_must_name_something_it_was_authored_against(self) -> None:
        document = _base_document()
        document["provenance"]["based_on"] = []
        with self.assertRaises(CommercialStrategyContractError):
            parse_commercial_strategy(document)

    def test_provenance_must_bind_both_declared_artifacts(self) -> None:
        for dropped in (_FACTS_REF, _EVIDENCE_REF):
            with self.subTest(dropped=dropped):
                document = _base_document()
                document["provenance"]["based_on"] = [
                    entry for entry in document["provenance"]["based_on"]
                    if entry["ref"] != dropped
                ]
                with self.assertRaises(CommercialStrategyContractError) as caught:
                    parse_commercial_strategy(document)
                self.assertIn("does not name", str(caught.exception))

    def test_provenance_sha256_must_agree_with_the_bound_artifact(self) -> None:
        document = _base_document()
        document["provenance"]["based_on"][0]["sha256"] = "c" * 64
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("disagrees", str(caught.exception))

    def test_an_unknown_author_actor_fails(self) -> None:
        document = _base_document()
        document["provenance"]["authored_by"]["actor"] = "DEEPSEEK"
        with self.assertRaises(CommercialStrategyContractError) as caught:
            parse_commercial_strategy(document)
        self.assertIn("actor", str(caught.exception))

    def test_the_document_carries_no_timestamp_or_reasoning(self) -> None:
        """Only auditable external provenance: no clock, no prompt, no rationale."""

        for key in ("authored_at", "timestamp", "prompt", "rationale", "reasoning",
                    "chain_of_thought"):
            with self.subTest(key=key):
                document = _base_document()
                document["provenance"][key] = "x"
                with self.assertRaises(CommercialStrategyContractError):
                    parse_commercial_strategy(document)
        strategy = parse_commercial_strategy(_base_document())
        self.assertEqual(
            set(strategy.provenance.as_dict()), {"authored_by", "based_on"}
        )


class ProductFactsIntegrityTests(unittest.TestCase):
    def test_the_binding_uses_the_existing_product_fact_key_vocabulary(self) -> None:
        """One fact vocabulary, not two: the shape matches ProductFacts exactly."""

        from src.ai_autocut.candidate_evidence import ProductFacts

        existing = ProductFacts(_FACTS_REF, _FACTS_SHA, ("FACT-B", "FACT-A"))
        strategy = parse_commercial_strategy(_base_document())
        binding = strategy.product_facts
        self.assertEqual(set(binding.as_dict()), set(existing.as_dict()))
        # Both contracts sort their fact lists, so the same input renders the same order.
        self.assertEqual(
            list(binding.allowed_fact_refs), sorted(binding.allowed_fact_refs)
        )
        self.assertEqual(
            existing.as_dict()["allowed_fact_refs"],
            sorted(existing.as_dict()["allowed_fact_refs"]),
        )

    def test_validation_rebinds_the_document_to_the_authority(self) -> None:
        strategy = parse_commercial_strategy(_base_document())
        validate_against_product_facts(
            strategy, ["FACT-INSTALLATION", "FACT-DIRECTION-ADJUSTABLE", "FACT-EXTRA"]
        )

    def test_a_drifted_snapshot_is_refused(self) -> None:
        strategy = parse_commercial_strategy(_base_document())
        with self.assertRaises(CommercialStrategyContractError) as caught:
            validate_against_product_facts(strategy, ["FACT-INSTALLATION"])
        self.assertIn("does not permit", str(caught.exception))

    def test_an_empty_authority_is_refused(self) -> None:
        strategy = parse_commercial_strategy(_base_document())
        with self.assertRaises(CommercialStrategyContractError):
            validate_against_product_facts(strategy, [])

    def test_an_empty_permitted_fact_list_fails(self) -> None:
        document = _base_document()
        document["product_facts"]["allowed_fact_refs"] = []
        with self.assertRaises(CommercialStrategyContractError):
            parse_commercial_strategy(document)


class SerializationTests(unittest.TestCase):
    def test_serialization_is_deterministic(self) -> None:
        first = render_commercial_strategy(parse_commercial_strategy(_base_document()))
        second = render_commercial_strategy(parse_commercial_strategy(_base_document()))
        self.assertEqual(first, second)
        self.assertTrue(first.endswith("}\n"))

    def test_key_order_does_not_change_the_rendering(self) -> None:
        shuffled = dict(reversed(list(_base_document().items())))
        self.assertEqual(
            render_commercial_strategy(parse_commercial_strategy(shuffled)),
            render_commercial_strategy(parse_commercial_strategy(_base_document())),
        )

    def test_a_render_round_trips(self) -> None:
        strategy = parse_commercial_strategy(_base_document())
        self.assertEqual(
            strategy.as_dict(),
            parse_commercial_strategy(json.loads(render_commercial_strategy(strategy))).as_dict(),
        )

    def test_the_permitted_fact_list_is_normalised(self) -> None:
        document = _base_document()
        document["product_facts"]["allowed_fact_refs"] = [
            "FACT-DIRECTION-ADJUSTABLE", "FACT-INSTALLATION"
        ]
        strategy = parse_commercial_strategy(document)
        self.assertEqual(
            list(strategy.product_facts.allowed_fact_refs),
            ["FACT-DIRECTION-ADJUSTABLE", "FACT-INSTALLATION"],
        )


class SchemaFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_the_schema_is_closed(self) -> None:
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(
            self.schema["properties"]["schema_version"]["const"],
            commercial_strategy.SCHEMA_VERSION,
        )

    def test_the_schema_lists_every_required_key_the_parser_requires(self) -> None:
        self.assertEqual(
            set(self.schema["required"]),
            {
                "schema_version", "strategy_id", "market", "platform", "objective",
                "product", "target_consumer", "consumer_insight", "product_facts",
                "visual_evidence_boundary", "claim_boundary", "variants", "provenance",
            },
        )

    def test_the_schema_records_the_claim_states_and_presence_values(self) -> None:
        boundary = self.schema["properties"]["claim_boundary"]["properties"]
        self.assertEqual(set(boundary), {state.lower() for state in CLAIM_STATES})
        presence = (
            self.schema["properties"]["visual_evidence_boundary"]["properties"]["items"]
            ["items"]["properties"]["presence"]["enum"]
        )
        self.assertEqual(tuple(presence), EVIDENCE_PRESENCE)

    def test_the_schema_does_not_offer_a_field_for_final_copy(self) -> None:
        document_keys = set(self.schema["properties"])
        variant_keys = set(
            self.schema["properties"]["variants"]["items"]["properties"]
        )
        for key in ("final_copy", "vo_lines", "subtitles", "cta_text"):
            with self.subTest(key=key):
                self.assertNotIn(key, document_keys)
                self.assertNotIn(key, variant_keys)

    def test_the_schema_status_matches_the_implementation(self) -> None:
        status = self.schema["x-status"]
        self.assertEqual(status["implementation"], IMPLEMENTATION)
        self.assertEqual(status["wiring_status"], WIRING_STATUS)
        self.assertIsNone(status["writer"])
        self.assertIsNone(status["reader"])
        self.assertFalse(status["producer_registered"])
        self.assertFalse(status["required_by_a_stage"])
        self.assertTrue(status["production_chain_untouched"])
        self.assertIn("planning_evidence.v1", status["precedent"])
        self.assertIn("final copy", status["not_in_this_contract"])


class ContractOnlyTests(unittest.TestCase):
    """CONTRACT_ONLY / NOT_WIRED: nothing in production writes or reads this artifact."""

    def test_no_producer_is_registered(self) -> None:
        with self.assertRaises(producer_registry.ProducerRegistryError) as caught:
            producer_registry.producer_for(ARTIFACT)
        self.assertIn("NO PRODUCER", str(caught.exception))

    def test_no_mode_owns_the_artifact(self) -> None:
        self.assertIsNone(producer_registry.mode_of(ARTIFACT))

    def test_no_third_mode_scope_or_registry_was_added(self) -> None:
        """A declared scope was considered and rejected; the registry must be unchanged."""

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
        """It is unreachable from the control path, so it cannot be a wired capability."""

        declared = {
            artifact for stage in fast_path.STAGES for artifact in stage.inputs
        }
        self.assertNotIn(ARTIFACT, declared)
        self.assertEqual(len(fast_path.SEMANTIC_STAGES), 8)

    def test_the_contract_document_records_the_contract_only_status(self) -> None:
        text = (
            REPO_ROOT / "docs" / "contracts" / "commercial-strategy-v1.md"
        ).read_text(encoding="utf-8")
        self.assertIn("CONTRACT_ONLY", text)
        self.assertIn("NOT_WIRED", text)
        self.assertIn("planning_evidence.v1", text)
        self.assertIn("No producer is registered", text)


class ExampleFixtureTests(unittest.TestCase):
    """The Indonesia demonstration must stay a contract demonstration."""

    def setUp(self) -> None:
        self.document = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        self.strategy = parse_commercial_strategy(self.document)

    def test_the_example_parses(self) -> None:
        self.assertEqual(self.strategy.market, "INDONESIA")
        self.assertEqual(self.strategy.platform, "TIKTOK")
        self.assertEqual(self.strategy.objective, "DIRECT_CONVERSION")
        self.assertEqual(
            [variant.variant_id for variant in self.strategy.variants], ["A", "B", "C"]
        )

    def test_the_three_variants_do_three_different_jobs(self) -> None:
        self.assertEqual(
            [variant.persuasion_job for variant in self.strategy.variants],
            ["EXPLAIN", "RELATE", "DEMONSTRATE"],
        )
        differences = strategy_differences(self.strategy)
        self.assertIn("persuasion_job", differences["differing_fields"])
        self.assertIn("hook_strategy", differences["differing_fields"])

    def test_the_unproven_facts_are_forbidden_and_the_permitted_one_is_conditional(self) -> None:
        forbidden = set(self.strategy.claim_boundary.forbidden_ids)
        expected = {
            "CLAIM-REMOVES-VISIBLE-DIRT",
            "CLAIM-REMOVES-SEDIMENT",
            "CLAIM-BEFORE-AFTER-FILTRATION-RESULT",
            "CLAIM-TURBID-TO-CLEAR-WATER",
            "CLAIM-REMOVES-BACTERIA",
            "CLAIM-REMOVES-CHLORINE",
            "CLAIM-REMOVES-HEAVY-METALS",
            "CLAIM-FILTRATION-EFFICIENCY",
            "CLAIM-PURIFICATION-RATE",
            "CLAIM-DRINKING-WATER-SAFE",
            "CLAIM-HEALTH-IMPROVEMENT",
            "CLAIM-UNSUPPORTED-FILTER-MATERIAL",
        }
        self.assertEqual(forbidden, expected)
        self.assertEqual(
            self.strategy.claim_boundary.state_of("CLAIM-DIRECTION-ADJUSTABLE"),
            "CONDITIONAL",
        )

    def test_no_variant_uses_a_claim_the_material_cannot_support(self) -> None:
        unsupported = set(
            self.strategy.claim_boundary.forbidden_ids
        ) | set(self.strategy.claim_boundary.conditional_ids)
        for variant in self.strategy.variants:
            with self.subTest(variant=variant.variant_id):
                self.assertEqual(set(variant.claims_used) & unsupported, set())
                self.assertTrue(
                    set(variant.claims_used) <= set(self.strategy.claim_boundary.allowed_ids)
                )

    def test_the_result_first_variant_does_not_open_on_an_unprovable_result(self) -> None:
        variant_c = self.strategy.variant("C")
        self.assertEqual(variant_c.persuasion_job, "DEMONSTRATE")
        self.assertIn("does not open on a filtration result", variant_c.hook_strategy)
        self.assertEqual(
            self.strategy.visual_evidence_boundary.presence_of("EV-FILTRATION-RESULT"),
            "ABSENT",
        )

    def test_the_example_uses_illustrative_hashes(self) -> None:
        """It is a demonstration, not a record of any file in this repository."""

        self.assertEqual(self.strategy.product_facts.sha256, "1" * 64)
        self.assertEqual(self.strategy.visual_evidence_boundary.sha256, "2" * 64)

    def test_the_example_carries_no_media_and_no_machine_path(self) -> None:
        text = EXAMPLE_PATH.read_text(encoding="utf-8")
        self.assertNotIn(_USER_ROOT, text)
        self.assertNotIn(_VOLUME_ROOT, text)
        self.assertIsNone(re.search(r"\.(mp4|mov|wav|mp3)\b", text))


class NoProviderDependencyTests(unittest.TestCase):
    def test_the_module_makes_no_network_or_provider_call(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "socket", "ssl", "http.client", "urllib", "requests", "httpx", "openai",
            "anthropic", "api_key", "subprocess",
        ):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_contract_does_not_register_itself(self) -> None:
        """CONTRACT_ONLY: the module must not reach into the producer registry."""

        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("producer_registry", source)

    def test_the_module_does_not_depend_on_a_shadow_mode_contract(self) -> None:
        """A contract-only artifact must not import the Editing Intelligence vNext stack."""

        source = MODULE_PATH.read_text(encoding="utf-8")
        for shadow in (
            "candidate_evidence", "candidate_analysis", "candidate_pool",
            "candidate_extraction", "editing_intelligence", "hook_planning",
            "creative_intent",
        ):
            with self.subTest(module=shadow):
                self.assertNotIn(f"from .{shadow}", source)

    def test_validation_is_pure(self) -> None:
        """A parse must not touch the filesystem: the example is read by the test, not by it."""

        strategy = parse_commercial_strategy(_base_document())
        self.assertFalse(hasattr(strategy, "job_root"))
        self.assertFalse(hasattr(strategy, "path"))


if __name__ == "__main__":
    unittest.main()
