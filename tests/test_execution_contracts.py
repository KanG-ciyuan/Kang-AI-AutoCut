"""Execution contracts and the global timebase invariant.

Two accepted inspection findings are held here.

**Execution contracts.** Picture execution, typography execution, audio rendering and
assembly have no in-repository executor. Rather than implying otherwise, each declares a
reproducible contract a job-specific adapter must satisfy, and the fast path consumes
that contract instead of trusting that someone remembered a command.

**The timebase invariant is global.** It is not one call inside one stage. It governs
every active production path that converts a source range into timeline frames —
including placement coordinates, which the earlier phase left unchecked — and the two
legacy paths that could bypass it are explicitly classified.
"""

from __future__ import annotations

import ast
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from src.ai_autocut import execution_contracts, fast_path, local_preview, media_probe
from src.ai_autocut.execution_contracts import (
    ASSEMBLY_REQUIRED_KEYS,
    CONTRACTS,
    CONTRACT_NAMES,
    ExecutionContractError,
    contracts_document,
    get_contract,
    verify_assembly_evidence,
)
from src.ai_autocut.local_preview import (
    THIRD_SKU_EXCLUSION_REASON,
    THIRD_SKU_PRODUCTION_SCOPE,
    LocalPreviewScopeError,
    assert_third_sku_production_allowed,
)
from src.ai_autocut.timebase_adapter import TimebaseAdapter, TimebaseAdapterError


def _has_ffmpeg() -> bool:
    return media_probe.have_tools()


class FakeTiming:
    """A variable frame rate source whose PTS table is deliberately non-uniform."""

    def __init__(self, timestamps: list[float], fps: int = 30) -> None:
        self.path = "vfr.mp4"
        self.fps = fps
        self.timestamps = timestamps
        self.deltas = {0.0333: 3, 0.1: 2}

    @property
    def frame_count(self) -> int:
        return len(self.timestamps)

    @property
    def span_seconds(self) -> float:
        return round(self.timestamps[-1] - self.timestamps[0], 4)

    @property
    def nominal(self) -> int:
        return int(round(self.span_seconds * self.fps))

    @property
    def is_variable_frame_rate(self) -> bool:
        return True

    def timestamp_of(self, index: int) -> float:
        if index < 0 or index >= len(self.timestamps):
            from src.ai_autocut.timebase import TimebaseError

            raise TimebaseError(f"frame {index} is outside the source")
        return self.timestamps[index]

    def timeline_index(self, timestamp: float) -> int:
        return int(round(timestamp * self.fps))

    def describe(self) -> dict:
        return {
            "frames": self.frame_count,
            "span_seconds": self.span_seconds,
            "nominal_frames_at_fps": self.nominal,
            "fps": self.fps,
            "variable_frame_rate": True,
            "dominant_deltas": {"0.0333": 3, "0.1": 2},
        }


def vfr_adapter() -> TimebaseAdapter:
    adapter = TimebaseAdapter(fps=30)
    adapter._timing_cache["vfr.mp4"] = FakeTiming(  # type: ignore[assignment]
        [0.0, 0.0333, 0.0667, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    )
    return adapter


class ExecutionContractTests(unittest.TestCase):
    def test_the_four_boundaries_are_declared(self) -> None:
        self.assertEqual(
            {c.name for c in CONTRACTS}, {"picture", "typography", "audio", "assemble_master"}
        )

    def test_every_contract_states_its_full_shape(self) -> None:
        for contract in CONTRACTS:
            with self.subTest(contract=contract.name):
                for field_name in (
                    "producer_type", "required_input", "expected_output", "procedure",
                    "validation", "output_evidence", "resume_condition",
                    "ledger_obligation",
                ):
                    self.assertTrue(
                        getattr(contract, field_name, None) is not None,
                        f"{contract.name} is missing {field_name}",
                    )

    def test_every_contract_names_a_real_stage(self) -> None:
        for contract in CONTRACTS:
            with self.subTest(contract=contract.name):
                self.assertIn(contract.stage, fast_path.SEMANTIC_STAGES)

    def test_every_contract_declares_a_producer_type(self) -> None:
        from src.ai_autocut.producer_registry import PRODUCER_TYPES

        for contract in CONTRACTS:
            with self.subTest(contract=contract.name):
                self.assertIn(contract.producer_type, PRODUCER_TYPES)

    def test_every_contract_declares_a_ledger_obligation(self) -> None:
        for contract in CONTRACTS:
            with self.subTest(contract=contract.name):
                self.assertGreater(len(contract.ledger_obligation.strip()), 20)

    def test_no_universal_executor_ships_here(self) -> None:
        """Each contract is a boundary, not a renderer."""

        for contract in CONTRACTS:
            with self.subTest(contract=contract.name):
                self.assertTrue(contract.adapter_required)

    def test_the_document_is_serialisable(self) -> None:
        document = contracts_document()
        self.assertEqual(document["schema_version"], "execution_contracts.v1")
        self.assertEqual(len(document["contracts"]), len(CONTRACTS))

    def test_an_unknown_contract_is_refused(self) -> None:
        with self.assertRaises(ExecutionContractError):
            get_contract("nope")

    def test_an_empty_procedure_is_refused(self) -> None:
        from src.ai_autocut.execution_contracts import ExecutionContract

        with self.assertRaises(ExecutionContractError):
            ExecutionContract(
                name="picture", stage="FINISH THE PICTURE", producer_type="ADAPTER",
                producer_id="x", required_input=("x",), expected_output="x",
                output_evidence=("x",), procedure="  ", validation="x",
                resume_condition="x", ledger_obligation="x",
                intervention_kind="SUPERVISOR_DECISIONS", adapter_required=True,
            )


@unittest.skipUnless(_has_ffmpeg(), "real media is required")
class AssemblyEvidenceTests(unittest.TestCase):
    """Assembly is verified against the real file, never against a claim.

    The Phase 5 inspection found this accepted a JSON document without opening
    anything: a nonexistent path, a fabricated SHA256 and a fabricated frame count all
    passed. Every case below is therefore built from a real master on disk.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.master = self.tmp / "master.mp4"
        self._render(self.master, black=False)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _render(self, path: Path, *, black: bool, seconds: float = 1.0) -> None:
        source = "color=c=black:size=64x64:rate=30" if black else "testsrc2=size=64x64:rate=30"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"{source}:duration={seconds}",
                "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                "-c:a", "aac", "-b:a", "128k", "-shortest", str(path),
            ],
            check=True,
            capture_output=True,
        )

    def evidence(self, **overrides: object) -> dict:
        measured = media_probe.probe_streams(self.master)
        loudness = media_probe.measure_loudness(self.master)
        document = {
            "master_path": str(self.master),
            "master_sha256": media_probe.sha256_of_file(self.master),
            "frame_count": int(measured["frame_count"] or 0),
            "method": "REMUX",
            "black_frames": 0,
            "audio": {"integrated_lufs": loudness["integrated_lufs"]},
        }
        document.update(overrides)
        return document

    def test_a_real_master_verifies_and_is_measured(self) -> None:
        verified = verify_assembly_evidence(self.evidence(), job_root=self.tmp)
        self.assertTrue(verified["measured"])
        self.assertEqual(verified["master_sha256"], media_probe.sha256_of_file(self.master))
        self.assertGreater(verified["frame_count"], 0)
        self.assertEqual(verified["video_codec"], "h264")
        self.assertEqual(verified["audio_codec"], "aac")
        self.assertEqual(verified["black_frames"], 0)

    def test_a_nonexistent_master_is_refused(self) -> None:
        with self.assertRaises(ExecutionContractError) as caught:
            verify_assembly_evidence(
                self.evidence(master_path=str(self.tmp / "absent.mp4")), job_root=self.tmp
            )
        self.assertIn("does not exist", str(caught.exception))

    def test_a_fabricated_sha256_is_refused(self) -> None:
        with self.assertRaises(ExecutionContractError) as caught:
            verify_assembly_evidence(self.evidence(master_sha256="a" * 64), job_root=self.tmp)
        self.assertIn("does not match the file on disk", str(caught.exception))

    def test_a_fabricated_frame_count_is_refused(self) -> None:
        with self.assertRaises(ExecutionContractError) as caught:
            verify_assembly_evidence(self.evidence(frame_count=9999), job_root=self.tmp)
        self.assertIn("does not match the decoded count", str(caught.exception))

    def test_a_frame_count_that_disagrees_with_upstream_is_refused(self) -> None:
        with self.assertRaises(ExecutionContractError) as caught:
            verify_assembly_evidence(
                self.evidence(), job_root=self.tmp, expected_frame_count=9999
            )
        self.assertIn("upstream evidence", str(caught.exception))

    def test_fabricated_audio_measurements_are_refused(self) -> None:
        with self.assertRaises(ExecutionContractError) as caught:
            verify_assembly_evidence(
                self.evidence(audio={"integrated_lufs": -3.0}), job_root=self.tmp
            )
        self.assertIn("does not match the measured", str(caught.exception))

    def test_a_black_master_is_refused(self) -> None:
        black = self.tmp / "black.mp4"
        self._render(black, black=True, seconds=2.0)
        with self.assertRaises(ExecutionContractError) as caught:
            verify_assembly_evidence(
                self.evidence(
                    master_path=str(black),
                    master_sha256=media_probe.sha256_of_file(black),
                    frame_count=int(media_probe.probe_streams(black)["frame_count"] or 0),
                ),
                job_root=self.tmp,
            )
        self.assertIn("black frame", str(caught.exception))

    def test_an_unknown_method_is_refused(self) -> None:
        with self.assertRaises(ExecutionContractError):
            verify_assembly_evidence(self.evidence(method="MAGIC"), job_root=self.tmp)

    def test_a_master_without_audio_is_refused(self) -> None:
        silent = self.tmp / "silent.mp4"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30:duration=1",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(silent),
            ],
            check=True, capture_output=True,
        )
        with self.assertRaises(ExecutionContractError) as caught:
            verify_assembly_evidence(
                self.evidence(
                    master_path=str(silent),
                    master_sha256=media_probe.sha256_of_file(silent),
                    frame_count=int(media_probe.probe_streams(silent)["frame_count"] or 0),
                ),
                job_root=self.tmp,
            )
        self.assertIn("no audio stream", str(caught.exception))

    def test_a_missing_evidence_field_is_refused(self) -> None:
        document = self.evidence()
        del document["frame_count"]
        with self.assertRaises(ExecutionContractError) as caught:
            verify_assembly_evidence(document, job_root=self.tmp)
        self.assertIn("missing required evidence", str(caught.exception))

    def test_an_evidence_path_outside_the_job_root_is_refused(self) -> None:
        with self.assertRaises(ExecutionContractError) as caught:
            verify_assembly_evidence(self.evidence(), job_root=self.tmp / "elsewhere")
        self.assertIn("outside the job root", str(caught.exception))

    def test_a_non_object_is_refused(self) -> None:
        with self.assertRaises(ExecutionContractError):
            verify_assembly_evidence([])


class PlacementCoordinateTests(unittest.TestCase):
    """The invariant now covers placement coordinates, not only extraction."""

    def test_a_measured_timestamp_is_accepted(self) -> None:
        adapter = vfr_adapter()
        record = adapter.assert_placement_timing(
            placement_id="P01", source="vfr.mp4", source_in=5,
            source_out_exclusive=9, t_in_seconds=0.3,
        )
        self.assertEqual(record["measured_t_in_seconds"], 0.3)
        self.assertEqual(record["coordinate_system"], "SOURCE_PTS_SECONDS -> CFR_TIMELINE_FRAMES")

    def test_an_assumed_frame_rate_coordinate_is_refused(self) -> None:
        """5/30 = 0.1667s, but frame 5 really starts at 0.3s."""

        adapter = vfr_adapter()
        with self.assertRaises(TimebaseAdapterError) as caught:
            adapter.assert_placement_timing(
                placement_id="P01", source="vfr.mp4", source_in=5,
                source_out_exclusive=9, t_in_seconds=5 / 30,
            )
        self.assertIn("assumed constant frame rate", str(caught.exception))

    def test_a_missing_timestamp_is_refused(self) -> None:
        adapter = vfr_adapter()
        with self.assertRaises(TimebaseAdapterError) as caught:
            adapter.assert_placement_timing(
                placement_id="P01", source="vfr.mp4", source_in=0,
                source_out_exclusive=9, t_in_seconds=None,
            )
        self.assertIn("t_in_seconds", str(caught.exception))

    def test_the_measured_duration_is_not_frames_over_fps(self) -> None:
        """Frames 0..4 span 0.2s, not 4/30 = 0.1333s."""

        adapter = vfr_adapter()
        measured = adapter.measured_duration_seconds(
            source="vfr.mp4", source_in=0, source_out_exclusive=4
        )
        self.assertAlmostEqual(measured, 0.2, places=4)
        self.assertNotAlmostEqual(measured, 4 / 30, places=3)

    def test_duration_delta_is_reported(self) -> None:
        adapter = vfr_adapter()
        record = adapter.assert_placement_timing(
            placement_id="P01", source="vfr.mp4", source_in=0,
            source_out_exclusive=4, t_in_seconds=0.0,
        )
        self.assertNotEqual(record["duration_delta_seconds"], 0.0)
        self.assertEqual(record["duration_coordinate"], "MEASURED_PTS")

    def test_a_range_outside_the_source_is_refused(self) -> None:
        adapter = vfr_adapter()
        with self.assertRaises(TimebaseAdapterError):
            adapter.assert_placement_timing(
                placement_id="P01", source="vfr.mp4", source_in=0,
                source_out_exclusive=999, t_in_seconds=0.0,
            )

    def test_an_empty_range_is_refused(self) -> None:
        adapter = vfr_adapter()
        with self.assertRaises(TimebaseAdapterError):
            adapter.assert_placement_timing(
                placement_id="P01", source="vfr.mp4", source_in=4,
                source_out_exclusive=4, t_in_seconds=0.2,
            )


class ShotUnderstandingBypassTests(unittest.TestCase):
    """``shot_understanding`` must not be reachable with assumed-frame-rate coordinates."""

    def test_the_fast_path_verifies_placements_before_segmenting(self) -> None:
        stage = next(s for s in fast_path.STAGES if s.name == "UNDERSTAND SHOTS")
        self.assertIn(
            "timebase_adapter.TimebaseAdapter.assert_placement_timing", stage.invariants
        )

    def test_shot_understanding_itself_still_uses_frame_indices_for_decoding(self) -> None:
        """Recorded honestly: the engine works in decoded frame indices.

        That is legitimate for segmentation — it walks the decoder's own output. What
        must not happen is treating those indices as *time*, which is why the fast path
        verifies a measured timestamp for every placement before calling it.
        """

        source = Path("src/ai_autocut/shot_understanding.py").read_text(encoding="utf-8")
        self.assertIn("source_in: int", source)
        self.assertIn("CFR_FPS", source)

    def test_the_engine_module_is_not_claimed_as_a_production_coordinate_source(self) -> None:
        from src.ai_autocut.producer_registry import REQUIRED_INPUT_ARTIFACTS

        self.assertIn("shots/placements.json", REQUIRED_INPUT_ARTIFACTS)


class LocalPreviewScopeTests(unittest.TestCase):
    """The legacy frame-index trim path is classified, not silently reusable."""

    def test_local_preview_is_excluded_from_third_sku_production(self) -> None:
        self.assertEqual(THIRD_SKU_PRODUCTION_SCOPE, "EXCLUDED")

    def test_third_sku_production_use_is_refused(self) -> None:
        with self.assertRaises(LocalPreviewScopeError) as caught:
            assert_third_sku_production_allowed("THIRD_SKU_PRODUCTION")
        self.assertIn("trim=start_frame", str(caught.exception))

    def test_local_preview_use_is_allowed(self) -> None:
        assert_third_sku_production_allowed("LOCAL_PREVIEW")
        assert_third_sku_production_allowed("LOCAL_INSPECTION")

    def test_an_unknown_scope_is_refused(self) -> None:
        with self.assertRaises(LocalPreviewScopeError):
            assert_third_sku_production_allowed("WHATEVER")

    def test_the_exclusion_reason_names_the_defect(self) -> None:
        self.assertIn("variable frame rate", THIRD_SKU_EXCLUSION_REASON)

    def test_local_preview_really_does_trim_by_frame_index(self) -> None:
        """The reason for the exclusion, asserted rather than asserted-about."""

        source = Path("src/ai_autocut/local_preview.py").read_text(encoding="utf-8")
        self.assertIn("trim=start_frame=", source)

    def test_the_fast_path_does_not_import_local_preview(self) -> None:
        tree = ast.parse(Path("src/ai_autocut/fast_path.py").read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.update(alias.name for alias in node.names)
        self.assertNotIn("local_preview", imported)


if __name__ == "__main__":
    unittest.main()
