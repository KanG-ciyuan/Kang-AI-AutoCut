from __future__ import annotations

import json
from pathlib import Path
import unittest

from src.ai_autocut.candidate_pool import (
    SCHEMA_VERSION,
    CandidatePool,
    CandidatePoolContractError,
    canonical_pool_identity_json,
    parse_candidate_pool,
    pool_id_for,
    render_candidate_pool,
    validate_candidate_membership,
    validate_candidate_pool,
)
from src.ai_autocut.identity import (
    CandidateIdentity,
    bind_boundary_preflight,
    identify_material,
    parse_identity_catalog,
)
from src.ai_autocut.preflight import SCHEMA_VERSION as PREFLIGHT_SCHEMA_VERSION
from src.ai_autocut.preflight import parse_preflight_document


REPO_ROOT = Path(__file__).parents[1]
POOL_FIXTURE = Path(__file__).parent / "fixtures" / "candidate_pool_v1_valid.json"
IDENTITY_FIXTURE = (
    Path(__file__).parent / "fixtures" / "material_candidate_identity_v1_valid.json"
)
CONTRACT = REPO_ROOT / "docs" / "contracts" / "candidate-pool-v1.md"


class CandidatePoolTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = parse_identity_catalog(json.loads(IDENTITY_FIXTURE.read_text()))
        self.candidate = self.catalog.candidates[0]
        self.pool = CandidatePool.create((self.candidate.candidate_id,))

    def other_candidate(self) -> CandidateIdentity:
        material = identify_material(POOL_FIXTURE)
        return CandidateIdentity.create(material.material_id, 0, 1, 2)


class PoolIdentityTests(CandidatePoolTestCase):
    def test_empty_entries_are_valid(self) -> None:
        empty = CandidatePool.create(())
        self.assertEqual(empty.entries, ())
        self.assertEqual(parse_candidate_pool(empty.as_dict()), empty)

    def test_identity_is_order_independent_and_member_sensitive(self) -> None:
        other = self.other_candidate()
        first = CandidatePool.create((self.candidate.candidate_id, other.candidate_id))
        second = CandidatePool.create((other.candidate_id, self.candidate.candidate_id))
        self.assertEqual(first.pool_id, second.pool_id)
        self.assertEqual(first.entries, second.entries)
        self.assertNotEqual(first.pool_id, self.pool.pool_id)
        self.assertNotEqual(CandidatePool.create((other.candidate_id,)).pool_id, self.pool.pool_id)

    def test_canonical_member_payload_and_pool_id_are_fixed(self) -> None:
        self.assertEqual(
            canonical_pool_identity_json((self.candidate.candidate_id,)),
            '["candv1_f337412aa64f3bb35393191555ae9f8f6dc2bc42732b62f4192e1412eb7e6e3c"]',
        )
        self.assertEqual(
            pool_id_for((self.candidate.candidate_id,)),
            "poolv1_0b4db20356f946e35c542dde2d6977961b6a66455641b7587e569f43076eb8fd",
        )

    def test_pool_id_must_match_its_member_set(self) -> None:
        payload = self.pool.as_dict()
        payload["pool_id"] = "poolv1_" + "0" * 64
        with self.assertRaisesRegex(CandidatePoolContractError, "does not match"):
            parse_candidate_pool(payload)


class PoolParsingTests(CandidatePoolTestCase):
    def test_canonical_fixture_parses_and_matches_renderer(self) -> None:
        raw = POOL_FIXTURE.read_text(encoding="utf-8")
        pool = parse_candidate_pool(json.loads(raw))
        self.assertEqual(pool, self.pool)
        self.assertEqual(render_candidate_pool(pool), raw)

    def test_renderer_is_deterministic_and_sorts_entries(self) -> None:
        other = self.other_candidate()
        pool = CandidatePool.create((other.candidate_id, self.candidate.candidate_id))
        rendered = render_candidate_pool(pool)
        self.assertEqual(rendered, render_candidate_pool(pool))
        document = json.loads(rendered)
        self.assertEqual(
            [entry["candidate_id"] for entry in document["entries"]],
            sorted((self.candidate.candidate_id, other.candidate_id)),
        )

    def test_strict_allowlist_and_entry_shape(self) -> None:
        for payload in (
            {"schema_version": SCHEMA_VERSION, "pool_id": self.pool.pool_id},
            {**self.pool.as_dict(), "metadata": {}},
            {
                **self.pool.as_dict(),
                "entries": [{"candidate_id": self.candidate.candidate_id, "score": 1}],
            },
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(CandidatePoolContractError):
                    parse_candidate_pool(payload)

    def test_malformed_forged_and_duplicate_candidates_fail_closed(self) -> None:
        malformed = self.pool.as_dict()
        malformed["entries"] = [{"candidate_id": "/private/candidate"}]
        forged = self.pool.as_dict()
        forged["entries"] = [{"candidate_id": "candv1_" + "0" * 64}]
        duplicate = self.pool.as_dict()
        duplicate["entries"] = [
            {"candidate_id": self.candidate.candidate_id},
            {"candidate_id": self.candidate.candidate_id},
        ]
        for payload in (malformed, forged, duplicate):
            with self.subTest(payload=payload):
                with self.assertRaises(CandidatePoolContractError):
                    parse_candidate_pool(payload)


class PoolMembershipTests(CandidatePoolTestCase):
    def test_every_member_must_exist_in_the_identity_catalog(self) -> None:
        unknown = CandidatePool.create(("candv1_" + "0" * 64,))
        with self.assertRaisesRegex(CandidatePoolContractError, "unknown"):
            validate_candidate_pool(unknown, self.catalog)

    def test_membership_returns_existing_candidate_identity(self) -> None:
        resolved = validate_candidate_membership(
            self.pool.pool_id, self.candidate.candidate_id, self.pool, self.catalog
        )
        self.assertEqual(resolved, self.candidate)

    def test_pool_id_mismatch_and_outside_candidate_fail_closed(self) -> None:
        outside = "candv1_" + "0" * 64
        with self.assertRaisesRegex(CandidatePoolContractError, "pool_id"):
            validate_candidate_membership(
                "poolv1_" + "0" * 64,
                self.candidate.candidate_id,
                self.pool,
                self.catalog,
            )
        with self.assertRaisesRegex(CandidatePoolContractError, "not a member"):
            validate_candidate_membership(
                self.pool.pool_id, outside, self.pool, self.catalog
            )

    def test_pool_identity_chain_preserves_existing_preflight_schema(self) -> None:
        candidate = validate_candidate_membership(
            self.pool.pool_id, self.candidate.candidate_id, self.pool, self.catalog
        )
        document = bind_boundary_preflight(
            self.catalog,
            (
                {
                    "segment_id": "SEG-POOL-01",
                    "material_id": candidate.material_id,
                    "candidate_id": candidate.candidate_id,
                    "source_range": {
                        "start_frame": candidate.start_frame,
                        "end_frame_exclusive": candidate.end_frame_exclusive,
                    },
                },
            ),
        )
        self.assertEqual(document["schema_version"], PREFLIGHT_SCHEMA_VERSION)
        self.assertEqual(len(parse_preflight_document(document)), 1)
        self.assertNotIn("candidate_pool_id", document["segments"][0])


class ContractAndLeakageTests(CandidatePoolTestCase):
    def test_contract_fixture_and_rendered_pool_have_no_path_or_analysis_fields(self) -> None:
        text = CONTRACT.read_text(encoding="utf-8")
        self.assertIn("`candidate_pool.v1`", text)
        self.assertIn("Status:** frozen", text)
        rendered = render_candidate_pool(self.pool)
        for marker in ("/Users/", "file://", "\\\\", "score", "label", "description"):
            self.assertNotIn(marker, rendered)

    def test_path_like_candidate_is_not_echoed_in_error(self) -> None:
        private_path = "/private/candidate.mov"
        with self.assertRaises(CandidatePoolContractError) as caught:
            CandidatePool.create((private_path,))
        self.assertNotIn(private_path, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
