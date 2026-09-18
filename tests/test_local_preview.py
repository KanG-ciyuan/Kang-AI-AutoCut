from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from src.ai_autocut.candidate_pool import CandidatePool, render_candidate_pool
from src.ai_autocut.editing_plan import EditingPlan, bind_plan_boundary_preflight, render_editing_plan
from src.ai_autocut.identity import (
    CandidateIdentity,
    IdentityCatalog,
    MaterialIdentity,
    MaterialLocation,
    MaterialLocations,
    identify_material,
    render_identity_catalog,
    render_material_locations,
)
from src.ai_autocut.local_preview import (
    LocalPreviewError,
    build_filter_graph,
    execute_local_preview,
)
from src.ai_autocut.preflight import build_report, parse_preflight_document, run_preflight


FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


@unittest.skipUnless(FFMPEG and FFPROBE, "local preview tests require ffmpeg and ffprobe")
class LocalPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.source = cls.root / "source.mp4"
        subprocess.run(
            [
                FFMPEG,
                "-hide_banner",
                "-nostdin",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=64x48:rate=10:duration=4",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(cls.source),
            ],
            capture_output=True,
            check=True,
            text=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def setUp(self) -> None:
        self.case = Path(tempfile.mkdtemp(dir=self.root))
        self.runtime = self.case / "runtime"
        self.runtime.mkdir()
        self.preview = self.case / "previews" / "preview.mp4"

    def write_runtime(
        self,
        ranges: tuple[tuple[int, int], ...] = ((0, 10), (20, 30)),
        *,
        stream_index: int = 0,
        material_size_delta: int = 0,
        pool_ids: tuple[str, ...] | None = None,
        plan_pool: CandidatePool | None = None,
        plan_ids: tuple[str, ...] | None = None,
    ) -> tuple[IdentityCatalog, CandidatePool, EditingPlan]:
        actual_material = identify_material(self.source)
        material = MaterialIdentity(
            actual_material.material_id,
            actual_material.content_sha256,
            actual_material.byte_size + material_size_delta,
        )
        candidates = tuple(
            CandidateIdentity.create(material.material_id, stream_index, start, end)
            for start, end in ranges
        )
        catalog = IdentityCatalog((material,), candidates)
        locations = MaterialLocations((MaterialLocation(material.material_id, (str(self.source),)),))
        pool = CandidatePool.create(
            pool_ids if pool_ids is not None else tuple(item.candidate_id for item in candidates)
        )
        plan = EditingPlan.create(
            (plan_pool or pool).pool_id,
            plan_ids if plan_ids is not None else tuple(item.candidate_id for item in candidates),
        )
        all_ids = tuple(item.candidate_id for item in candidates)
        prepared_pool = (
            pool if set(all_ids) == {entry.candidate_id for entry in pool.entries}
            else CandidatePool.create(all_ids)
        )
        prepared_plan = EditingPlan.create(prepared_pool.pool_id, all_ids)
        bound = bind_plan_boundary_preflight(prepared_plan, prepared_pool, catalog)
        report = build_report(run_preflight(parse_preflight_document(bound)))
        (self.runtime / "identity_catalog.json").write_text(render_identity_catalog(catalog))
        (self.runtime / "material_locations.json").write_text(render_material_locations(locations))
        (self.runtime / "candidate_pool.json").write_text(render_candidate_pool(pool))
        (self.runtime / "editing_plan.json").write_text(render_editing_plan(plan))
        (self.runtime / "boundary_preflight_input.json").write_text(
            json.dumps(bound, sort_keys=True, indent=2) + "\n"
        )
        (self.runtime / "boundary_preflight_report.json").write_text(
            json.dumps(report, sort_keys=True, indent=2) + "\n"
        )
        return catalog, pool, plan

    def execute(self) -> object:
        return execute_local_preview(
            self.runtime,
            self.preview,
            production_scope="LOCAL_PREVIEW",
            ffmpeg_binary=FFMPEG,
            ffprobe_binary=FFPROBE,
        )

    def test_filter_graph_and_derived_preflight_are_deterministic(self) -> None:
        catalog, _pool, plan = self.write_runtime()
        candidates = tuple(catalog.candidate(segment.candidate_id) for segment in plan.segments)
        self.assertEqual(
            build_filter_graph(candidates),
            "[0:v:0]trim=start_frame=0:end_frame=10,setpts=PTS-STARTPTS[v0];"
            "[0:v:0]trim=start_frame=20:end_frame=30,setpts=PTS-STARTPTS[v1];"
            "[v0][v1]concat=n=2:v=1:a=0[vout]",
        )
        bound = json.loads((self.runtime / "boundary_preflight_input.json").read_text())
        self.assertEqual(
            [item["segment_id"] for item in bound["segments"]],
            ["segv1_000001", "segv1_000002"],
        )
        self.assertEqual(
            [item["planned_record_frame_relative"] for item in bound["segments"]],
            [0, 10],
        )

    def test_malformed_runtime_document_fails_before_output(self) -> None:
        self.write_runtime()
        (self.runtime / "identity_catalog.json").write_text("[]\n")
        with self.assertRaises(LocalPreviewError):
            self.execute()
        self.assertFalse(self.preview.exists())

    def test_hash_mismatch_fails_before_output(self) -> None:
        self.write_runtime()
        locations = json.loads((self.runtime / "material_locations.json").read_text())
        locations["locations"][0]["paths"] = [str(self.case / "missing.mp4")]
        (self.runtime / "material_locations.json").write_text(json.dumps(locations))
        with self.assertRaisesRegex(LocalPreviewError, "locator"):
            self.execute()
        self.assertFalse(self.preview.exists())

    def test_byte_size_mismatch_fails_before_output(self) -> None:
        self.write_runtime(material_size_delta=1)
        with self.assertRaisesRegex(LocalPreviewError, "locator"):
            self.execute()
        self.assertFalse(self.preview.exists())

    def test_unsupported_stream_fails_before_output(self) -> None:
        self.write_runtime(stream_index=1)
        with self.assertRaisesRegex(LocalPreviewError, "stream 0"):
            self.execute()
        self.assertFalse(self.preview.exists())

    def test_candidate_out_of_range_fails_before_output(self) -> None:
        self.write_runtime(ranges=((0, 10), (40, 50)))
        with self.assertRaisesRegex(LocalPreviewError, "exceeds"):
            self.execute()
        self.assertFalse(self.preview.exists())

    def test_pool_mismatch_fails_before_output(self) -> None:
        self.write_runtime(plan_pool=CandidatePool.create(()))
        with self.assertRaisesRegex(LocalPreviewError, "contract validation"):
            self.execute()
        self.assertFalse(self.preview.exists())

    def test_pool_external_candidate_fails_before_output(self) -> None:
        catalog, _pool, _plan = self.write_runtime()
        self.write_runtime(
            pool_ids=(catalog.candidates[0].candidate_id,),
            plan_ids=tuple(candidate.candidate_id for candidate in catalog.candidates),
        )
        with self.assertRaisesRegex(LocalPreviewError, "contract validation"):
            self.execute()
        self.assertFalse(self.preview.exists())

    def test_preflight_report_mismatch_fails_before_output(self) -> None:
        self.write_runtime()
        report = json.loads((self.runtime / "boundary_preflight_report.json").read_text())
        report["passed"] = False
        (self.runtime / "boundary_preflight_report.json").write_text(json.dumps(report))
        with self.assertRaisesRegex(LocalPreviewError, "Preflight report"):
            self.execute()
        self.assertFalse(self.preview.exists())

    def test_tiny_video_is_executed_and_verified(self) -> None:
        self.write_runtime()
        result = self.execute()
        self.assertTrue(result.preview_path.is_file())
        self.assertEqual(result.expected_frame_count, 20)
        self.assertEqual(result.output.decoded_frame_count, 20)
        self.assertEqual((result.output.width, result.output.height), (64, 48))
        self.assertEqual(result.output.codec_name, "h264")
        self.assertAlmostEqual(result.expected_duration_seconds, 2.0)
        self.assertIn("concat=n=2:v=1:a=0", result.ffmpeg_command[7])


if __name__ == "__main__":
    unittest.main()
