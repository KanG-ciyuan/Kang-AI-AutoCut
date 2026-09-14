from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from src.ai_autocut.gold_manifest import (
    ASSET_STATUSES,
    GOLD_STATUSES,
    GoldAssetReference,
    GoldManifestContractError,
    assert_not_promoted,
    parse_gold_manifest,
    render_gold_manifest,
    sha256_of_file,
    verify_asset_reference,
)


REPO_ROOT = Path(__file__).parents[1]
GOLD_RECORD = REPO_ROOT / "schemas" / "gold_manifest" / "filter-gold-v1.json"
GOLD_SCHEMA = REPO_ROOT / "schemas" / "gold_manifest" / "gold_manifest.v1.schema.json"


def load_record() -> dict:
    return json.loads(GOLD_RECORD.read_text(encoding="utf-8"))


class GoldRecordTestCase(unittest.TestCase):
    """The committed Gold record is the artifact, so it is what gets tested."""

    def setUp(self) -> None:
        self.manifest = parse_gold_manifest(load_record())

    def test_committed_record_parses(self) -> None:
        self.assertEqual(self.manifest.gold_id, "filter-gold-v1")

    def test_gold_id_is_confirmed(self) -> None:
        # Codex upper review accepted filter-gold-v1 as the canonical Gold ID.
        self.assertEqual(self.manifest.gold_id_status, "CONFIRMED")

    def test_an_unconfirmed_id_status_is_still_representable(self) -> None:
        # The schema keeps the provisional state for future Gold records; this
        # record is simply no longer in it.
        document = load_record()
        document["gold_id_status"] = "PROVISIONAL_INTERNAL"
        self.assertEqual(
            parse_gold_manifest(document).gold_id_status, "PROVISIONAL_INTERNAL"
        )

    def test_status_is_reconciliation_required(self) -> None:
        self.assertEqual(self.manifest.status, "PASS_WITH_RECONCILIATION_REQUIRED")

    def test_automation_may_not_declare_a_freeze(self) -> None:
        # A FROZEN Gold is an upper-review decision.
        assert_not_promoted(self.manifest)

    def test_timeline_matches_the_validated_gold(self) -> None:
        self.assertEqual(self.manifest.frames, 518)
        self.assertEqual(self.manifest.fps, 30.0)
        self.assertAlmostEqual(
            float(self.manifest.timeline["duration_seconds"]), 17.266667, places=6
        )
        self.assertEqual(self.manifest.timeline["width"], 1080)
        self.assertEqual(self.manifest.timeline["height"], 1920)

    def test_visual_authority_is_the_frozen_visual_source(self) -> None:
        visual = self.manifest.visual_authority
        self.assertEqual(visual.role, "FINAL_FROZEN_VISUAL_SOURCE")
        self.assertEqual(visual.filename, "TYPO-P3-B.mp4")
        # The frozen picture carries no audio; the master carries both.
        self.assertFalse(visual.has_audio)

    def test_superseded_visuals_are_not_recorded_as_authority(self) -> None:
        for rejected in ("TYPO-P3-A.mp4", "CONSERVATIVE-2-COMBO.mp4"):
            with self.subTest(rejected=rejected):
                self.assertNotEqual(self.manifest.visual_authority.filename, rejected)

    def test_master_is_master_a_and_selected(self) -> None:
        self.assertEqual(self.manifest.master.master_id, "MASTER-A")
        self.assertEqual(self.manifest.master.filename, "FILTER-V4-FINAL-MASTER-A.mp4")
        self.assertTrue(self.manifest.master.selected)

    def test_master_b_is_retained_as_ab_reference(self) -> None:
        roles = {asset.logical_role for asset in self.manifest.external_assets}
        self.assertIn("ab_reference_master", roles)

    def test_voice_over_is_the_three_line_final_authority(self) -> None:
        lines = self.manifest.voice_over.lines
        self.assertEqual(len(lines), 3)
        self.assertEqual(
            self.manifest.voice_over.strategy,
            "CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS",
        )
        self.assertEqual(
            lines[0].text, "Bikin aktivitas di wastafel jadi lebih praktis."
        )

    def test_editorial_text_carries_hook_feature_and_cta(self) -> None:
        roles = [event.role for event in self.manifest.editorial_text]
        self.assertEqual(roles, ["hook", "feature", "cta"])

    def test_measured_loudness_is_recorded_beside_the_reference(self) -> None:
        self.assertEqual(self.manifest.loudness["reference"]["integrated_lufs"], -16.0)
        self.assertEqual(self.manifest.loudness["measured"]["integrated_lufs"], -16.1)
        self.assertEqual(self.manifest.loudness["measured"]["true_peak_dbtp"], -1.4)

    def test_every_external_asset_is_verified(self) -> None:
        self.assertTrue(self.manifest.external_assets)
        for asset in self.manifest.external_assets:
            with self.subTest(asset=asset.filename):
                self.assertEqual(asset.asset_status, "EXTERNAL_ASSET_VERIFIED")

    def test_render_is_deterministic(self) -> None:
        again = render_gold_manifest(parse_gold_manifest(json.loads(render_gold_manifest(self.manifest))))
        self.assertEqual(again, render_gold_manifest(self.manifest))


class GoldManifestSchemaTestCase(unittest.TestCase):
    def test_schema_declares_the_same_statuses_as_the_validator(self) -> None:
        schema = json.loads(GOLD_SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(
            tuple(schema["properties"]["status"]["enum"]), tuple(GOLD_STATUSES)
        )
        asset_statuses = schema["properties"]["external_assets"]["items"]["properties"][
            "asset_status"
        ]["enum"]
        self.assertEqual(tuple(asset_statuses), tuple(ASSET_STATUSES))

    def test_schema_requires_every_top_level_key_the_validator_requires(self) -> None:
        schema = json.loads(GOLD_SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(
            tuple(schema["required"]),
            (
                "schema_version",
                "gold_id",
                "gold_id_status",
                "status",
                "timeline",
                "editorial_text",
                "voice_over",
                "visual_authority",
                "color_strategy",
                "typography_strategy",
                "audio_strategy",
                "master",
                "loudness",
                "external_assets",
                "reconciliation",
            ),
        )


class GoldManifestContractTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.record = load_record()

    def reject(self, mutate) -> None:
        document = copy.deepcopy(self.record)
        mutate(document)
        with self.assertRaises(GoldManifestContractError):
            parse_gold_manifest(document)

    def test_unknown_key_is_rejected(self) -> None:
        self.reject(lambda d: d.__setitem__("extra", 1))

    def test_missing_key_is_rejected(self) -> None:
        self.reject(lambda d: d.pop("master"))

    def test_duration_must_match_frames_and_fps(self) -> None:
        self.reject(lambda d: d["timeline"].__setitem__("duration_seconds", 18.0))

    def test_master_frames_must_match_the_timeline(self) -> None:
        self.reject(lambda d: d["master"].__setitem__("frames", 540))

    def test_master_duration_must_match_the_timeline(self) -> None:
        self.reject(lambda d: d["master"].__setitem__("duration_seconds", 18.0))

    def test_asset_filename_must_be_bare(self) -> None:
        self.reject(
            lambda d: d["external_assets"][0].__setitem__(
                "filename", "renders/TYPO-P3-B.mp4"
            )
        )

    def test_machine_path_is_rejected_anywhere_in_the_document(self) -> None:
        # Assembled from fragments: this file is scanned by the repository
        # hygiene test, so a literal personal path here would fail that test.
        probe = "/" + "Users" + "/" + "someone" + "/renders"
        self.reject(lambda d: d["reconciliation"].__setitem__("canonical_status", probe))

    def test_home_relative_path_is_rejected(self) -> None:
        self.reject(lambda d: d["voice_over"]["lines"][0].__setitem__("text", "~/notes"))

    def test_malformed_hash_is_rejected(self) -> None:
        self.reject(lambda d: d["master"].__setitem__("sha256", "not-a-hash"))

    def test_uppercase_hash_is_rejected(self) -> None:
        self.reject(
            lambda d: d["master"].__setitem__("sha256", "A" * 64)
        )

    def test_unknown_status_is_rejected(self) -> None:
        self.reject(lambda d: d.__setitem__("status", "PRODUCTION_READY"))

    def test_unknown_asset_status_is_rejected(self) -> None:
        self.reject(
            lambda d: d["external_assets"][0].__setitem__("asset_status", "MAYBE")
        )

    def test_unknown_storage_class_is_rejected(self) -> None:
        self.reject(
            lambda d: d["external_assets"][0].__setitem__("storage_class", "CLOUD")
        )

    def test_duplicate_editorial_roles_are_rejected(self) -> None:
        def mutate(document: dict) -> None:
            document["editorial_text"][2]["role"] = "hook"

        self.reject(mutate)

    def test_positive_integrated_loudness_is_rejected(self) -> None:
        self.reject(
            lambda d: d["loudness"]["measured"].__setitem__("integrated_lufs", 1.0)
        )

    def test_positive_true_peak_is_rejected(self) -> None:
        self.reject(lambda d: d["loudness"]["measured"].__setitem__("true_peak_dbtp", 0.5))

    def test_empty_voice_over_is_rejected(self) -> None:
        self.reject(lambda d: d["voice_over"].__setitem__("lines", []))

    def test_frozen_status_is_refused_by_the_promotion_guard(self) -> None:
        document = copy.deepcopy(self.record)
        document["status"] = "FROZEN"
        manifest = parse_gold_manifest(document)
        with self.assertRaises(GoldManifestContractError):
            assert_not_promoted(manifest)


class AssetVerificationTestCase(unittest.TestCase):
    def test_verify_asset_reference_accepts_matching_bytes(self) -> None:
        asset = parse_gold_manifest(load_record()).external_assets[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / asset.filename
            path.write_bytes(b"ai-autocut")
            rebuilt = GoldAssetReference(
                logical_role=asset.logical_role,
                filename=asset.filename,
                sha256=sha256_of_file(path),
                storage_class=asset.storage_class,
                asset_status=asset.asset_status,
            )
            verify_asset_reference(rebuilt, path)

    def test_verify_asset_reference_rejects_mismatched_bytes(self) -> None:
        manifest = parse_gold_manifest(load_record())
        asset = manifest.external_assets[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / asset.filename
            path.write_bytes(b"different bytes")
            with self.assertRaises(GoldManifestContractError):
                verify_asset_reference(asset, path)

    def test_missing_file_is_reported_as_a_contract_error(self) -> None:
        manifest = parse_gold_manifest(load_record())
        with self.assertRaises(GoldManifestContractError):
            verify_asset_reference(
                manifest.external_assets[0], Path("/nonexistent/asset.mp4")
            )


if __name__ == "__main__":
    unittest.main()
