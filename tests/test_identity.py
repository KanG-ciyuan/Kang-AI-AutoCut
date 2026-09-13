from __future__ import annotations

import json
from pathlib import Path
import tempfile
import traceback
import unittest
from unittest.mock import patch

from src.ai_autocut.identity import (
    CATALOG_SCHEMA_VERSION,
    LOCATIONS_SCHEMA_VERSION,
    CandidateIdentity,
    IdentityCatalog,
    IdentityContractError,
    LocatorResolutionError,
    MaterialLocation,
    MaterialLocations,
    bind_boundary_preflight,
    candidate_id_for,
    canonical_candidate_identity_json,
    hash_file_sha256,
    identify_material,
    parse_identity_catalog,
    parse_material_locations,
    render_identity_catalog,
    render_material_locations,
    resolve_material_path,
)
from src.ai_autocut.frame_boundary import FrameBoundaryError
from src.ai_autocut.preflight import SCHEMA_VERSION as PREFLIGHT_SCHEMA_VERSION
from src.ai_autocut.preflight import parse_preflight_document


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "material_candidate_identity_v1_valid.json"
)
CONTRACT = (
    Path(__file__).parents[1]
    / "docs"
    / "contracts"
    / "material-candidate-identity-v1.md"
)
CONTENT = b"AI-AutoCut identity fixture v1\n"


def strings(node: object) -> list[str]:
    found: list[str] = []
    if isinstance(node, str):
        found.append(node)
    elif isinstance(node, dict):
        for value in node.values():
            found.extend(strings(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(strings(value))
    return found


class IdentityTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.first_path = self.tmp / "first-name.mov"
        self.first_path.write_bytes(CONTENT)
        self.material = identify_material(self.first_path)
        self.candidate = CandidateIdentity.create(
            self.material.material_id, 0, 100, 130
        )
        self.catalog = IdentityCatalog((self.material,), (self.candidate,))


class MaterialIdentityTests(IdentityTestCase):
    def assert_sanitized_error_chain(
        self, error: BaseException, leaked_path: Path
    ) -> None:
        self.assertIsInstance(error, IdentityContractError)
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        rendered = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        self.assertNotIn(str(leaked_path), rendered)
        self.assertNotIn("PermissionError", rendered)
        self.assertNotIn("OSError", rendered)

    def test_material_id_is_full_file_sha256_with_v1_prefix(self) -> None:
        self.assertEqual(
            self.material.material_id,
            "matv1_3e29b288505586976ba3121e262eb1faa35dcf92571e09d000c0ddfcf41a52c6",
        )
        self.assertEqual(self.material.byte_size, len(CONTENT))

    def test_same_bytes_at_different_path_have_same_identity(self) -> None:
        moved_name = self.tmp / "renamed-copy.mp4"
        moved_name.write_bytes(CONTENT)
        self.assertEqual(
            identify_material(moved_name).material_id, self.material.material_id
        )

    def test_path_filename_and_mtime_do_not_enter_identity(self) -> None:
        second = self.tmp / "completely-different-name.mkv"
        second.write_bytes(CONTENT)
        second.touch()
        self.assertEqual(identify_material(second), self.material)

    def test_one_byte_change_creates_new_material_id(self) -> None:
        self.first_path.write_bytes(CONTENT + b"x")
        self.assertNotEqual(
            identify_material(self.first_path).material_id, self.material.material_id
        )

    def test_missing_material_file_fails_closed_without_echoing_path(self) -> None:
        missing = self.tmp / "private-name.mov"
        with self.assertRaises(LocatorResolutionError) as caught:
            identify_material(missing)
        self.assertNotIn(str(missing), str(caught.exception))

    def test_read_os_errors_are_removed_from_cause_and_traceback(self) -> None:
        leaked = self.tmp / "private-read-path.mov"
        for error_type in (OSError, PermissionError):
            with self.subTest(error_type=error_type.__name__):
                underlying = error_type(13, "denied", str(leaked))
                with patch.object(Path, "open", side_effect=underlying):
                    with self.assertRaises(IdentityContractError) as caught:
                        hash_file_sha256(self.first_path)
                self.assert_sanitized_error_chain(caught.exception, leaked)

    def test_stat_permission_error_is_removed_from_cause_and_traceback(self) -> None:
        leaked = self.tmp / "private-stat-path.mov"
        underlying = PermissionError(13, "denied", str(leaked))
        with patch(
            "src.ai_autocut.identity.hash_file_sha256",
            return_value=self.material.content_sha256,
        ), patch.object(Path, "stat", side_effect=underlying):
            with self.assertRaises(IdentityContractError) as caught:
                identify_material(self.first_path)
        self.assert_sanitized_error_chain(caught.exception, leaked)


class CandidateIdentityTests(IdentityTestCase):
    def test_canonical_json_and_candidate_id_are_fixed(self) -> None:
        canonical = canonical_candidate_identity_json(
            self.material.material_id, 0, 100, 130
        )
        self.assertEqual(
            canonical,
            '{"end_frame_exclusive":130,"material_id":"'
            + self.material.material_id
            + '","start_frame":100,"stream_index":0}',
        )
        self.assertEqual(
            self.candidate.candidate_id,
            "candv1_f337412aa64f3bb35393191555ae9f8f6dc2bc42732b62f4192e1412eb7e6e3c",
        )

    def test_same_identity_fields_always_produce_same_id(self) -> None:
        self.assertEqual(
            candidate_id_for(self.material.material_id, 0, 100, 130),
            candidate_id_for(self.material.material_id, 0, 100, 130),
        )

    def test_each_identity_field_changes_candidate_id(self) -> None:
        other_path = self.tmp / "other.mov"
        other_path.write_bytes(b"different")
        other_material = identify_material(other_path)
        baseline = self.candidate.candidate_id
        variants = (
            candidate_id_for(other_material.material_id, 0, 100, 130),
            candidate_id_for(self.material.material_id, 1, 100, 130),
            candidate_id_for(self.material.material_id, 0, 101, 130),
            candidate_id_for(self.material.material_id, 0, 100, 131),
        )
        self.assertEqual(len(set(variants)), 4)
        self.assertNotIn(baseline, variants)

    def test_non_identity_analysis_fields_cannot_enter_candidate_record(self) -> None:
        payload = self.catalog.as_dict()
        payload["candidates"][0]["score"] = 0.99  # type: ignore[index]
        with self.assertRaises(IdentityContractError):
            parse_identity_catalog(payload)

    def test_external_analysis_metadata_does_not_change_candidate_id(self) -> None:
        analysis = {
            "score": 0.2,
            "label": "wide shot",
            "description": "first analysis",
            "approval": "unreviewed",
        }
        before = candidate_id_for(self.material.material_id, 0, 100, 130)
        analysis.update(
            score=0.95,
            label="close-up",
            description="revised analysis",
            approval="approved",
        )
        after = candidate_id_for(self.material.material_id, 0, 100, 130)
        self.assertEqual(before, after)
        self.assertNotIn(analysis["label"], canonical_candidate_identity_json(
            self.material.material_id, 0, 100, 130
        ))

    def test_invalid_frame_ranges_and_types_are_rejected(self) -> None:
        for start, end in ((-1, 10), (10, 10), (11, 10), (True, 10), (1.5, 10)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(IdentityContractError):
                    candidate_id_for(  # type: ignore[arg-type]
                        self.material.material_id, 0, start, end
                    )

    def test_forged_candidate_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(IdentityContractError, "does not match"):
            CandidateIdentity(
                "candv1_" + "0" * 64,
                self.material.material_id,
                0,
                100,
                130,
            )


class CatalogTests(IdentityTestCase):
    def test_canonical_fixture_parses_and_renders_deterministically(self) -> None:
        raw = FIXTURE.read_text(encoding="utf-8")
        parsed = parse_identity_catalog(json.loads(raw))
        self.assertEqual(parsed, self.catalog)
        self.assertEqual(render_identity_catalog(parsed), render_identity_catalog(parsed))
        self.assertEqual(raw, render_identity_catalog(parsed))

    def test_render_order_is_independent_of_input_order(self) -> None:
        other_path = self.tmp / "other.mov"
        other_path.write_bytes(b"different")
        other = identify_material(other_path)
        other_candidate = CandidateIdentity.create(other.material_id, 0, 1, 2)
        first = IdentityCatalog(
            (self.material, other), (self.candidate, other_candidate)
        )
        second = IdentityCatalog(
            (other, self.material), (other_candidate, self.candidate)
        )
        self.assertEqual(render_identity_catalog(first), render_identity_catalog(second))

    def test_duplicate_material_and_candidate_ids_are_rejected(self) -> None:
        with self.assertRaisesRegex(IdentityContractError, "duplicate material_id"):
            IdentityCatalog((self.material, self.material), (self.candidate,))
        with self.assertRaisesRegex(IdentityContractError, "duplicate candidate_id"):
            IdentityCatalog((self.material,), (self.candidate, self.candidate))

    def test_unknown_material_reference_is_rejected(self) -> None:
        empty = IdentityCatalog((), ())
        with self.assertRaises(IdentityContractError):
            IdentityCatalog(empty.materials, (self.candidate,))

    def test_forged_material_id_is_rejected(self) -> None:
        payload = self.catalog.as_dict()
        payload["materials"][0]["material_id"] = "matv1_" + "0" * 64  # type: ignore[index]
        with self.assertRaisesRegex(IdentityContractError, "does not match"):
            parse_identity_catalog(payload)

    def test_catalog_is_path_free_and_rejects_extra_path_field(self) -> None:
        rendered = render_identity_catalog(self.catalog)
        for marker in (str(self.tmp), "/Users/", "file://", "\\"):
            self.assertNotIn(marker, rendered)
        payload = self.catalog.as_dict()
        payload["materials"][0]["path"] = str(self.first_path)  # type: ignore[index]
        with self.assertRaises(IdentityContractError):
            parse_identity_catalog(payload)


class LocatorTests(IdentityTestCase):
    def locations(self, *paths: Path) -> MaterialLocations:
        return MaterialLocations(
            (MaterialLocation(self.material.material_id, tuple(map(str, paths))),)
        )

    def test_locator_schema_is_separate_and_contains_paths(self) -> None:
        rendered = render_material_locations(self.locations(self.first_path))
        document = json.loads(rendered)
        self.assertEqual(document["schema_version"], LOCATIONS_SCHEMA_VERSION)
        self.assertNotEqual(document["schema_version"], CATALOG_SCHEMA_VERSION)
        self.assertIn(str(self.first_path), strings(document))
        self.assertEqual(parse_material_locations(document), self.locations(self.first_path))

    def test_nested_path_value_raises_identity_error_not_native_type_error(self) -> None:
        document = {
            "schema_version": LOCATIONS_SCHEMA_VERSION,
            "locations": [
                {
                    "material_id": self.material.material_id,
                    "paths": [["/x"]],
                }
            ],
        }
        with self.assertRaises(IdentityContractError) as caught:
            parse_material_locations(document)
        self.assertNotIsInstance(caught.exception, TypeError)
        self.assertIn("locator paths[0]", str(caught.exception))

    def test_resolver_rehashes_and_returns_verified_path(self) -> None:
        self.assertEqual(
            resolve_material_path(
                self.material.material_id,
                self.catalog,
                self.locations(self.first_path),
            ),
            self.first_path,
        )

    def test_missing_locations_fail_closed_without_path_leak(self) -> None:
        missing = self.tmp / "secret-missing.mov"
        with self.assertRaises(LocatorResolutionError) as caught:
            resolve_material_path(
                self.material.material_id, self.catalog, self.locations(missing)
            )
        self.assertNotIn(str(missing), str(caught.exception))

    def test_hash_mismatch_fails_closed_without_path_leak(self) -> None:
        changed = self.tmp / "secret-changed.mov"
        changed.write_bytes(b"tampered")
        with self.assertRaisesRegex(LocatorResolutionError, "does not match") as caught:
            resolve_material_path(
                self.material.material_id, self.catalog, self.locations(changed)
            )
        self.assertNotIn(str(changed), str(caught.exception))

    def test_duplicate_content_paths_do_not_create_new_material(self) -> None:
        copy = self.tmp / "copy.mov"
        copy.write_bytes(CONTENT)
        resolved = resolve_material_path(
            self.material.material_id,
            self.catalog,
            self.locations(self.first_path, copy),
        )
        self.assertEqual(resolved, self.first_path)
        self.assertEqual(identify_material(copy).material_id, self.material.material_id)


class BoundaryBindingTests(IdentityTestCase):
    def segment(self, **overrides: object) -> dict[str, object]:
        value: dict[str, object] = {
            "segment_id": "SEG-01",
            "material_id": self.material.material_id,
            "candidate_id": self.candidate.candidate_id,
            "source_range": {"start_frame": 100, "end_frame_exclusive": 130},
        }
        value.update(overrides)
        return value

    def test_binding_emits_unchanged_boundary_preflight_v1_shape(self) -> None:
        document = bind_boundary_preflight(self.catalog, (self.segment(),))
        self.assertEqual(document["schema_version"], PREFLIGHT_SCHEMA_VERSION)
        segment = document["segments"][0]  # type: ignore[index]
        self.assertEqual(segment["source_id"], self.material.material_id)  # type: ignore[index]
        self.assertEqual(  # type: ignore[index]
            segment["candidate_id"], self.candidate.candidate_id
        )
        self.assertNotIn("material_id", segment)
        self.assertEqual(len(parse_preflight_document(document)), 1)

    def test_optional_preflight_fields_are_preserved(self) -> None:
        document = bind_boundary_preflight(
            self.catalog,
            (
                self.segment(
                    continuation_group="TAKE-A",
                    verified_safe_end_frame_exclusive=130,
                    planned_record_frame_relative=0,
                ),
            ),
        )
        segment = document["segments"][0]  # type: ignore[index]
        self.assertEqual(segment["continuation_group"], "TAKE-A")  # type: ignore[index]

    def test_material_candidate_mismatch_is_rejected(self) -> None:
        other_path = self.tmp / "other.mov"
        other_path.write_bytes(b"different")
        other = identify_material(other_path)
        catalog = IdentityCatalog((self.material, other), (self.candidate,))
        with self.assertRaisesRegex(IdentityContractError, "does not belong"):
            bind_boundary_preflight(
                catalog, (self.segment(material_id=other.material_id),)
            )

    def test_source_range_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(IdentityContractError, "does not match"):
            bind_boundary_preflight(
                self.catalog,
                (self.segment(source_range={"start_frame": 100, "end_frame_exclusive": 129}),),
            )

    def test_unknown_candidate_is_rejected(self) -> None:
        with self.assertRaisesRegex(IdentityContractError, "unknown candidate_id"):
            bind_boundary_preflight(
                self.catalog,
                (self.segment(candidate_id="candv1_" + "0" * 64),),
            )

    def test_path_like_segment_identifier_is_rejected_by_existing_preflight(self) -> None:
        with self.assertRaises(FrameBoundaryError):
            bind_boundary_preflight(
                self.catalog, (self.segment(segment_id="/private/segment"),)
            )


class ContractTests(IdentityTestCase):
    def test_contract_exists_and_declares_frozen_schema(self) -> None:
        text = CONTRACT.read_text(encoding="utf-8")
        self.assertIn(f"`{CATALOG_SCHEMA_VERSION}`", text)
        self.assertIn("Status: frozen", text)

    def test_contract_names_identity_exclusions_and_frame_semantics(self) -> None:
        text = CONTRACT.read_text(encoding="utf-8")
        for term in ("path", "score", "label", "description", "approval"):
            self.assertIn(term, text)
        self.assertIn("[start_frame, end_frame_exclusive)", text)

    def test_fixture_contains_no_local_path_or_identity(self) -> None:
        raw = FIXTURE.read_text(encoding="utf-8")
        document = json.loads(raw)
        parse_identity_catalog(document)
        for marker in ("/Users/", "file://", "\\", "kang", "desktop", "movies"):
            self.assertNotIn(marker, raw.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
