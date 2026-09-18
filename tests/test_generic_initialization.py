"""Fresh commercial SKU initialization, and the real VFR mapping it must not disturb.

The defect this closes
----------------------
The registered producer procedure for ``source_inventory.json`` routed every fresh job
through ``initialize_filter_job``, which hardcodes **exactly sixteen MP4 files** and a
**Faucet Filter** product identity. That is a Filter-first-job contract, not a
Third-SKU one: a freshly initialized non-Filter SKU could not exist at all.

``job_foundation.initialize_job`` is the generic producer contract. It requires only what
a fresh commercial SKU has — an id, a product identity, and a directory of source media —
and it discovers whatever supported media is there. ``initialize_filter_job`` is kept
unchanged for historical compatibility.

This file proves the generic path on a job that is deliberately not Filter, not Faucet,
not Cushion Puff, and whose source count is deliberately not sixteen.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from src.ai_autocut import job_foundation, media_probe, producer_registry
from src.ai_autocut.fast_path import FastPath
from src.ai_autocut.job_foundation import (
    JobFoundationError,
    SUPPORTED_SOURCE_SUFFIXES,
    build_generic_source_inventory,
    discover_sources,
    initialize_filter_job,
    initialize_job,
)

#: Deliberately none of: Filter, Faucet Filter, Cushion Puff.
PRODUCT_NAME = "Bamboo Cutting Board"
#: Deliberately not sixteen.
SOURCE_COUNT = 3

FORBIDDEN_TOKENS = (
    "Faucet",
    "Filter",
    "水龙头",
    "Cushion",
    "气垫粉扑",
    "FILTER-",
    "exactly 16",
)


def make_source(path: Path, colour: str = "green") -> Path:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={colour}:size=64x64:rate=30:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise unittest.SkipTest(f"ffmpeg unavailable: {result.stderr[-200:]}")
    return path


@unittest.skipUnless(media_probe.have_tools(), "ffmpeg and ffprobe are required")
class GenericInitializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.sources = self.tmp / "sources"
        self.sources.mkdir()
        # Mixed extensions on purpose: discovery is by supported media, not by .mp4 count.
        make_source(self.sources / "board-01.mp4", "green")
        make_source(self.sources / "board-02.mov", "yellow")
        make_source(self.sources / "board-03.mkv", "purple")
        self.workspace = self.tmp / "job"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def initialize(self):
        return initialize_job(
            job_id="fresh-sku-proof",
            product={"name": PRODUCT_NAME},
            source_root=self.sources,
            workspace=self.workspace,
        )

    def read(self, relative: str) -> dict:
        return json.loads((self.workspace / relative).read_text(encoding="utf-8"))

    # ---- discovery ------------------------------------------------------------

    def test_discovery_finds_every_supported_source(self) -> None:
        found = discover_sources(self.sources)
        self.assertEqual(len(found), SOURCE_COUNT)
        self.assertEqual(
            [path.name for path in found],
            ["board-01.mp4", "board-02.mov", "board-03.mkv"],
        )

    def test_discovery_ignores_unsupported_files(self) -> None:
        (self.sources / "notes.txt").write_text("not media", encoding="utf-8")
        (self.sources / "cover.jpg").write_bytes(b"\xff\xd8\xff")
        self.assertEqual(len(discover_sources(self.sources)), SOURCE_COUNT)

    def test_the_supported_set_is_not_tied_to_one_sku(self) -> None:
        self.assertIn(".mp4", SUPPORTED_SOURCE_SUFFIXES)
        self.assertIn(".mov", SUPPORTED_SOURCE_SUFFIXES)
        self.assertIn(".mkv", SUPPORTED_SOURCE_SUFFIXES)

    def test_no_supported_media_is_a_controlled_error(self) -> None:
        empty = self.tmp / "empty"
        empty.mkdir()
        with self.assertRaises(JobFoundationError) as caught:
            build_generic_source_inventory(empty)
        self.assertIn("no supported source media", str(caught.exception))

    def test_a_missing_source_root_is_a_controlled_error(self) -> None:
        with self.assertRaises(JobFoundationError):
            discover_sources(self.tmp / "nope")

    # ---- the generic initializer ---------------------------------------------

    def test_initialization_succeeds_for_a_non_filter_sku(self) -> None:
        job = self.initialize()
        self.assertTrue(job.source_inventory_path.is_file())
        self.assertTrue(job.manifest_path.is_file())
        self.assertTrue(job.state_path.is_file())
        self.assertEqual(job.resume_stage(), "ANALYZE")

    def test_the_product_identity_is_what_the_job_stated(self) -> None:
        self.initialize()
        manifest = self.read("job_manifest.json")
        self.assertEqual(manifest["product"], {"name": PRODUCT_NAME})
        self.assertEqual(manifest["job_id"], "fresh-sku-proof")

    def test_the_discovered_count_is_what_was_found(self) -> None:
        self.initialize()
        inventory = self.read("source_inventory.json")
        manifest = self.read("job_manifest.json")
        self.assertEqual(len(inventory["files"]), SOURCE_COUNT)
        self.assertEqual(manifest["source"]["count"], SOURCE_COUNT)
        self.assertNotEqual(manifest["source"]["count"], 16)

    def test_the_inventory_records_every_discovered_file_with_a_digest(self) -> None:
        self.initialize()
        for entry in self.read("source_inventory.json")["files"]:
            with self.subTest(entry=entry["filename"]):
                self.assertEqual(len(entry["sha256"]), 64)
                self.assertTrue(Path(entry["path"]).is_file())
                self.assertGreater(entry["size_bytes"], 0)

    def test_no_filter_specific_value_leaks_into_the_job(self) -> None:
        self.initialize()
        blob = json.dumps(self.read("job_manifest.json")) + json.dumps(
            self.read("source_inventory.json")
        )
        for token in FORBIDDEN_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(token, blob)

    def test_a_single_source_job_initializes(self) -> None:
        one = self.tmp / "one"
        one.mkdir()
        make_source(one / "only.mp4", "red")
        job = initialize_job(
            job_id="single-source-sku",
            product={"name": PRODUCT_NAME},
            source_root=one,
            workspace=self.tmp / "job-single",
        )
        inventory = json.loads(job.source_inventory_path.read_text(encoding="utf-8"))
        self.assertEqual(len(inventory["files"]), 1)

    def test_a_product_identity_is_required(self) -> None:
        with self.assertRaises(JobFoundationError) as caught:
            initialize_job(
                job_id="no-product", product={}, source_root=self.sources,
                workspace=self.tmp / "job-noproduct",
            )
        self.assertIn("product identity", str(caught.exception))

    def test_an_existing_workspace_is_refused(self) -> None:
        self.workspace.mkdir()
        with self.assertRaises(JobFoundationError) as caught:
            self.initialize()
        self.assertIn("refusing to overwrite evidence", str(caught.exception))

    # ---- the wildcard media types are genuinely discovered --------------------

    def test_only_supported_media_enters_the_inventory(self) -> None:
        (self.sources / "readme.md").write_text("x", encoding="utf-8")
        self.initialize()
        names = [e["filename"] for e in self.read("source_inventory.json")["files"]]
        self.assertNotIn("readme.md", names)
        self.assertEqual(len(names), SOURCE_COUNT)


@unittest.skipUnless(media_probe.have_tools(), "ffmpeg and ffprobe are required")
class FreshSkuThroughTheFastPathTests(GenericInitializationTests):
    """The initialized job is one the production path can actually begin from."""

    def test_the_fast_path_begins_from_a_freshly_initialized_job(self) -> None:
        self.initialize()
        result = FastPath(self.workspace, job_id="fresh-sku-proof").run_stage("PREPARE")
        self.assertEqual(result.outcome, "PASS", result.reason)
        self.assertEqual(result.evidence["sources"], SOURCE_COUNT)

    def test_the_fast_path_then_gates_on_the_next_producer(self) -> None:
        self.initialize()
        report = FastPath(self.workspace, job_id="fresh-sku-proof").run()
        self.assertEqual(report.stopped_at, "UNDERSTAND SHOTS")
        gate = report.results[-1].gate
        self.assertEqual(gate["missing_artifact"], "shots/placements.json")
        self.assertEqual(gate["producer_type"], "CODEX")

    def test_the_initialized_prepare_state_is_recorded(self) -> None:
        self.initialize()
        pipeline = self.read("pipeline_state.json")
        self.assertEqual(pipeline["stages"]["PREPARE"]["state"], "PASS")


class RegisteredProcedureTests(unittest.TestCase):
    """A fresh agent must be able to initialize a job from the registry alone."""

    def test_the_registry_points_at_the_generic_initializer(self) -> None:
        producer = producer_registry.producer_for("source_inventory.json")
        self.assertEqual(producer.producer_id, "job_foundation.initialize_job")
        self.assertNotIn("filter", producer.producer_id.lower())

    def test_the_registered_procedure_is_the_generic_cli(self) -> None:
        producer = producer_registry.producer_for("source_inventory.json")
        self.assertIn("--product-name", producer.procedure)
        self.assertIn("--source-root", producer.procedure)
        self.assertIn("GENERIC", producer.procedure.upper())

    def test_the_procedure_states_that_no_file_count_is_assumed(self) -> None:
        producer = producer_registry.producer_for("source_inventory.json")
        self.assertIn("no file count", producer.procedure.lower())

    def test_the_historical_filter_initializer_is_preserved(self) -> None:
        """Compatibility: the old contract still exists and still demands 16 files."""

        import inspect

        from src.ai_autocut.job_foundation import build_source_inventory

        self.assertTrue(callable(initialize_filter_job))
        self.assertIn(
            "Filter first job requires exactly 16 MP4 files",
            inspect.getsource(build_source_inventory),
        )
        self.assertIn(
            "Faucet Filter", inspect.getsource(initialize_filter_job)
        )


@unittest.skipUnless(media_probe.have_tools(), "ffmpeg and ffprobe are required")
class RegisteredProcedureRunsTests(unittest.TestCase):
    """Run the registered command exactly as written, with no other context."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.sources = self.tmp / "sources"
        self.sources.mkdir()
        make_source(self.sources / "item-01.mp4", "teal")
        make_source(self.sources / "item-02.mp4", "orange")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_registered_cli_initializes_a_fresh_sku(self) -> None:
        workspace = self.tmp / "job"
        result = subprocess.run(
            [
                "python3", "-m", "src.ai_autocut.job_foundation",
                "--job-id", "cli-fresh-sku",
                "--product-name", PRODUCT_NAME,
                "--source-root", str(self.sources),
                "--workspace", str(workspace),
            ],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(Path(payload["job_manifest"]).is_file())
        manifest = json.loads(Path(payload["job_manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["product"]["name"], PRODUCT_NAME)
        self.assertEqual(manifest["source"]["count"], 2)

    def test_the_registered_cli_refuses_zero_media(self) -> None:
        empty = self.tmp / "empty"
        empty.mkdir()
        result = subprocess.run(
            [
                "python3", "-m", "src.ai_autocut.job_foundation",
                "--job-id", "cli-empty",
                "--product-name", PRODUCT_NAME,
                "--source-root", str(empty),
                "--workspace", str(self.tmp / "job-empty"),
            ],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no supported source media", result.stderr)

    def test_the_registered_cli_requires_a_product_identity(self) -> None:
        result = subprocess.run(
            [
                "python3", "-m", "src.ai_autocut.job_foundation",
                "--job-id", "cli-noproduct",
                "--source-root", str(self.sources),
                "--workspace", str(self.tmp / "job-noproduct"),
            ],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--product-name is required", result.stderr)

    def test_the_filter_cli_remains_available_and_still_demands_16(self) -> None:
        """The historical path is preserved, not silently changed."""

        result = subprocess.run(
            [
                "python3", "-m", "src.ai_autocut.job_foundation",
                "--job-id", "cli-filter", "--filter",
                "--source-root", str(self.sources),
                "--workspace", str(self.tmp / "job-filter"),
                "--media-root", str(self.tmp),
                "--staging-root", str(self.tmp / "staging"),
                "--davinci-path", str(self.tmp),
            ],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly 16", result.stderr)


if __name__ == "__main__":
    unittest.main()
