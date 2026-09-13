from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.ai_autocut.frame_boundary import FrameBoundaryError
from src.ai_autocut.preflight import (
    EXIT_BOUNDARY_ISSUES,
    EXIT_CONTRACT_ERROR,
    EXIT_OK,
    SCHEMA_VERSION,
    PreflightContractError,
    main,
    parse_preflight_document,
    preflight_document,
    render_report,
)

REPO_ROOT = Path(__file__).parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "s06_boundary_regression.json"
CLI = (sys.executable, "-m", "src.ai_autocut.preflight")


def segment_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "segment_id": "S01",
        "candidate_id": "C01",
        "source_id": "SRC-A",
        "source_range": {"start_frame": 10, "end_frame_exclusive": 20},
    }
    payload.update(overrides)
    return payload


def document(*segments: dict[str, object]) -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "segments": list(segments)}


class PreflightCliTestCase(unittest.TestCase):
    """Shared harness: every CLI case runs in a temp dir outside the repo."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def run_cli(self, payload: object) -> subprocess.CompletedProcess[str]:
        path = self.tmp / "input.json"
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload),
            encoding="utf-8",
        )
        return subprocess.run(
            [*CLI, str(path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )


class S06FixtureTests(PreflightCliTestCase):
    """Consume Agent A's sanitized regression fixture through the JSON entry."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(FIXTURE.read_text(encoding="utf-8"))[
            "canonical_frame_evidence"
        ]

    def s06(self, end_frame_exclusive: int) -> dict[str, object]:
        return segment_payload(
            segment_id="S06",
            candidate_id="C16",
            source_id="SRC-B",
            source_range={
                "start_frame": self.evidence["source_in_frame"],
                "end_frame_exclusive": end_frame_exclusive,
            },
            verified_safe_end_frame_exclusive=self.evidence[
                "verified_safe_end_frame_exclusive"
            ],
        )

    def test_safe_input_exits_zero_and_reports_passed(self) -> None:
        result = self.run_cli(document(self.s06(self.evidence["repaired_end_frame_exclusive"])))
        self.assertEqual(result.returncode, EXIT_OK)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["segments_checked"], 1)
        self.assertEqual(report["total_frames"], 605 - self.evidence["source_in_frame"])
        self.assertEqual(report["placements"][0]["source_out_frame_exclusive"], 605)

    def test_s06_unsafe_input_exits_two_and_reports_two_excess_frames(self) -> None:
        unsafe = self.evidence["unsafe_legacy_rounded_end_frame_exclusive"]
        result = self.run_cli(document(self.s06(unsafe)))
        self.assertEqual(result.returncode, EXIT_BOUNDARY_ISSUES)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertEqual(len(report["issues"]), 1)
        issue = report["issues"][0]
        self.assertEqual(issue["code"], "SOURCE_OUT_EXCEEDS_VERIFIED_BOUNDARY")
        self.assertEqual(issue["frame"], self.evidence["verified_safe_end_frame_exclusive"])
        self.assertIn("by 2 frame(s)", issue["reason"])
        self.assertNotEqual(EXIT_BOUNDARY_ISSUES, EXIT_CONTRACT_ERROR)


class MalformedInputTests(PreflightCliTestCase):
    def assert_contract_failure(self, payload: object) -> str:
        result = self.run_cli(payload)
        self.assertEqual(result.returncode, EXIT_CONTRACT_ERROR)
        self.assertEqual(result.stdout, "")
        self.assertIn("preflight contract error", result.stderr)
        return result.stderr

    def test_missing_required_segment_key(self) -> None:
        stderr = self.assert_contract_failure(
            document({"segment_id": "S01", "source_id": "SRC-A"})
        )
        self.assertIn("segments[0] is missing required key(s)", stderr)
        self.assertIn("candidate_id", stderr)

    def test_wrong_schema_version(self) -> None:
        stderr = self.assert_contract_failure(
            {"schema_version": "boundary_preflight.v2", "segments": [segment_payload()]}
        )
        self.assertIn("schema_version must be", stderr)

    def test_unsupported_key_is_named(self) -> None:
        stderr = self.assert_contract_failure(
            document(segment_payload(reviewer_note="looks fine"))
        )
        self.assertIn("unsupported key(s): reviewer_note", stderr)

    def test_empty_segments_and_non_array_segments(self) -> None:
        self.assert_contract_failure({"schema_version": SCHEMA_VERSION, "segments": []})
        self.assert_contract_failure(
            {"schema_version": SCHEMA_VERSION, "segments": "S01"}
        )

    def test_inverted_source_range_is_reported_as_contract_error(self) -> None:
        stderr = self.assert_contract_failure(
            document(
                segment_payload(source_range={"start_frame": 20, "end_frame_exclusive": 20})
            )
        )
        self.assertIn("positive duration", stderr)

    def test_duplicate_segment_id_is_a_contract_error_not_a_guard_issue(self) -> None:
        stderr = self.assert_contract_failure(
            document(segment_payload(), segment_payload(candidate_id="C02"))
        )
        self.assertIn("duplicate segment_id", stderr)

    def test_ambiguous_second_fields_are_rejected_by_name(self) -> None:
        stderr = self.assert_contract_failure(
            document(segment_payload(source_in_seconds="17.67"))
        )
        self.assertIn("source_in_seconds", stderr)
        self.assertIn("canonical integer frames", stderr)

    def test_binary_float_frames_are_rejected(self) -> None:
        stderr = self.assert_contract_failure(
            document(
                segment_payload(
                    source_range={"start_frame": 10.0, "end_frame_exclusive": 20}
                )
            )
        )
        self.assertIn("integer frame number", stderr)

    def test_invalid_json_text(self) -> None:
        result = self.run_cli("{ not json")
        self.assertEqual(result.returncode, EXIT_CONTRACT_ERROR)
        self.assertIn("not valid JSON", result.stderr)

    def test_missing_input_file(self) -> None:
        result = subprocess.run(
            [*CLI, str(self.tmp / "absent.json")],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, EXIT_CONTRACT_ERROR)
        self.assertIn("cannot read input", result.stderr)

    def test_missing_argument_returns_contract_error(self) -> None:
        sink = io.StringIO()
        with contextlib.redirect_stderr(sink):
            self.assertEqual(main([]), EXIT_CONTRACT_ERROR)
        self.assertIn("usage:", sink.getvalue())


class PathLeakTests(PreflightCliTestCase):
    def test_machine_local_path_identifier_is_rejected(self) -> None:
        leaked = "$AUTOCUT_WORKSPACE/raw/SRC-B.mov"
        result = self.run_cli(document(segment_payload(source_id=leaked)))
        self.assertEqual(result.returncode, EXIT_CONTRACT_ERROR)
        self.assertIn("logical identifier", result.stderr)
        # The offending value is a local path, so it must not be echoed anywhere.
        self.assertNotIn(leaked, result.stdout)
        self.assertNotIn(leaked, result.stderr)

    def test_rejected_path_never_reaches_a_report(self) -> None:
        for leaked in (
            "/Users/example/Movies/SRC-B.mov",
            "~/Movies/SRC-B.mov",
            "C:\\Media\\SRC-B.mov",
        ):
            with self.subTest(leaked=leaked):
                result = self.run_cli(document(segment_payload(source_id=leaked)))
                self.assertEqual(result.returncode, EXIT_CONTRACT_ERROR)
                self.assertNotIn("SRC-B.mov", result.stdout)

    def test_valid_report_contains_no_machine_local_media_path(self) -> None:
        for payload in (
            document(segment_payload()),
            document(segment_payload(source_range={"start_frame": 10, "end_frame_exclusive": 25},
                                     verified_safe_end_frame_exclusive=20)),
        ):
            with self.subTest(payload=payload):
                result = self.run_cli(payload)
                for marker in ("/Users/", str(self.tmp), "file://", "\\"):
                    self.assertNotIn(marker, result.stdout)


class DeterminismTests(PreflightCliTestCase):
    MULTI_ISSUE = (
        segment_payload(
            segment_id="S01",
            candidate_id="C01",
            source_id="SRC-A",
            source_range={"start_frame": 10, "end_frame_exclusive": 22},
            continuation_group="A1",
            verified_safe_end_frame_exclusive=20,
        ),
        segment_payload(
            segment_id="S02",
            candidate_id="C02",
            source_id="SRC-A",
            source_range={"start_frame": 22, "end_frame_exclusive": 30},
            continuation_group="A1",
            planned_record_frame_relative=99,
        ),
    )

    def test_repeated_runs_produce_identical_output(self) -> None:
        payload = document(*self.MULTI_ISSUE)
        first = self.run_cli(payload)
        second = self.run_cli(payload)
        self.assertEqual(first.returncode, EXIT_BOUNDARY_ISSUES)
        self.assertEqual(first.stdout, second.stdout)

    def test_issue_order_follows_timeline_order(self) -> None:
        result = self.run_cli(document(*self.MULTI_ISSUE))
        report = json.loads(result.stdout)
        self.assertEqual(
            [issue["code"] for issue in report["issues"]],
            [
                "SOURCE_OUT_EXCEEDS_VERIFIED_BOUNDARY",
                "CANDIDATE_BOUNDARY_SPLITS_CONTINUOUS_SOURCE",
                "TIMELINE_RELATIVE_PLACEMENT_MISMATCH",
            ],
        )
        self.assertEqual(result.stdout, render_report(report))

    def test_top_level_keys_are_emitted_in_sorted_order(self) -> None:
        result = self.run_cli(document(segment_payload()))
        keys = [
            line.split('"')[1]
            for line in result.stdout.splitlines()
            if line.startswith('  "')
        ]
        self.assertEqual(keys, sorted(keys))


class ContractParsingTests(unittest.TestCase):
    def test_parse_maps_canonical_frames_onto_guard_segments(self) -> None:
        segments = parse_preflight_document(
            document(
                segment_payload(
                    continuation_group="A1",
                    verified_safe_end_frame_exclusive=20,
                    planned_record_frame_relative=0,
                )
            )
        )
        self.assertEqual(len(segments), 1)
        segment = segments[0]
        self.assertEqual(segment.segment_id, "S01")
        self.assertEqual(segment.source_range.start_frame, 10)
        self.assertEqual(segment.source_range.end_frame_exclusive, 20)
        self.assertEqual(segment.continuation_group, "A1")
        self.assertEqual(segment.verified_safe_end_frame_exclusive, 20)
        self.assertEqual(segment.planned_record_frame_relative, 0)

    def test_optional_fields_default_to_none(self) -> None:
        segment = parse_preflight_document(document(segment_payload()))[0]
        self.assertIsNone(segment.continuation_group)
        self.assertIsNone(segment.verified_safe_end_frame_exclusive)
        self.assertIsNone(segment.planned_record_frame_relative)

    def test_preflight_document_returns_a_delegated_report(self) -> None:
        report = preflight_document(document(segment_payload()))
        self.assertTrue(report["passed"])
        self.assertEqual(report["schema_version"], SCHEMA_VERSION)
        self.assertEqual(report["total_frames"], 10)

    def test_contract_errors_share_the_frame_boundary_base(self) -> None:
        with self.assertRaises(FrameBoundaryError):
            parse_preflight_document({"segments": []})
        with self.assertRaises(PreflightContractError):
            parse_preflight_document({"segments": []})


if __name__ == "__main__":
    unittest.main(verbosity=2)
