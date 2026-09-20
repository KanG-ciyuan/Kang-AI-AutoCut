"""The FFmpeg version floor is stated, checked, and reported by name.

Why this exists
---------------
``-fps_mode`` is what builds the variable-frame-rate fixture, and it was measured absent
from FFmpeg 4.4.2 **and** 5.0.1 and present from 5.1.2 onwards. No single spelling spans
that range, so the repository declares a minimum instead of carrying a version-adaptive
option table, and it must fail fast and *by version* rather than failing later inside a
filtergraph with ``Unrecognized option 'fps_mode'``.

These tests inject a fake toolchain, so they assert the gate itself and do not depend on
which FFmpeg happens to be installed.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import unittest

from src.ai_autocut import media_probe


class ToolVersionParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="tool-version-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def fake_tool(self, name: str, first_line: str) -> str:
        """A stand-in binary that answers ``-version`` with ``first_line``."""

        path = self.root / name
        path.write_text(f'#!/bin/sh\necho "{first_line}"\n', encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return str(path)

    def test_the_two_floors_are_the_two_measured_boundaries(self) -> None:
        # Production floor: 4.4.2 is the oldest build the execution path was exercised on.
        # Fixture floor: -fps_mode is absent from 4.4.2 and 5.0.1, present from 5.1.2.
        self.assertEqual(media_probe.MINIMUM_FFMPEG_VERSION, (4, 4))
        self.assertEqual(media_probe.VFR_FIXTURE_MINIMUM_VERSION, (5, 1))
        self.assertLess(media_probe.MINIMUM_FFMPEG_VERSION,
                        media_probe.VFR_FIXTURE_MINIMUM_VERSION)

    def test_a_supported_version_is_read_and_accepted(self) -> None:
        tool = self.fake_tool("ffprobe-new",
                              "ffprobe version 9.0.1 Copyright (c) 2007-2026 the FFmpeg developers")
        self.assertEqual(media_probe.tool_version(tool), (9, 0))
        self.assertIsNone(media_probe.version_problem(tool))

    def test_the_exact_minimum_is_accepted(self) -> None:
        tool = self.fake_tool("ffprobe-min",
                              "ffprobe version 5.1.2 Copyright (c) 2007-2022 the FFmpeg developers")
        self.assertIsNone(media_probe.version_problem(tool))

    def test_the_two_measured_older_generations_are_refused_by_name_and_version(self) -> None:
        """4.4.2 and 5.0.1 cannot run the VFR fixture, and the message says so by name."""

        for reported in ("4.4.2", "5.0.1"):
            with self.subTest(reported=reported):
                tool = self.fake_tool(f"ffprobe-{reported.replace('.', '')}",
                                      f"ffprobe version {reported} Copyright (c) 2007-2021")
                problem = media_probe.version_problem(
                    tool, media_probe.VFR_FIXTURE_MINIMUM_VERSION)
                self.assertIsNotNone(problem)
                self.assertIn(reported, problem or "")
                self.assertIn("5.1 or later", problem or "")

    def test_the_fixture_floor_is_not_applied_to_the_production_path(self) -> None:
        """A toolchain that runs the product must not be refused by the suite's floor."""

        for reported in ("4.4.2", "5.0.1", "5.1.2", "9.0.1"):
            with self.subTest(reported=reported):
                tool = self.fake_tool(f"ffprobe-prod-{reported.replace('.', '')}",
                                      f"ffprobe version {reported} Copyright (c) 2007-2021")
                self.assertIsNone(media_probe.version_problem(tool))

    def test_a_toolchain_older_than_the_production_floor_is_refused(self) -> None:
        tool = self.fake_tool("ffprobe-old",
                              "ffprobe version 3.4.13 Copyright (c) 2007-2020")
        problem = media_probe.version_problem(tool)
        self.assertIsNotNone(problem)
        self.assertIn("3.4.13", problem or "")
        self.assertIn("4.4 or later", problem or "")

    def test_an_unreadable_version_is_refused_rather_than_assumed(self) -> None:
        tool = self.fake_tool("ffprobe-garbage", "not an ffmpeg at all")
        problem = media_probe.version_problem(tool)
        self.assertIsNotNone(problem)
        self.assertIn("could not read the version", problem or "")

    def test_a_missing_tool_is_named_in_the_failure(self) -> None:
        with self.assertRaises(media_probe.MediaProbeError) as caught:
            media_probe.require_supported_tools("ffmpeg-does-not-exist",
                                                "ffprobe-does-not-exist")
        self.assertIn("required", str(caught.exception))

    def test_an_absent_binary_reports_instead_of_raising(self) -> None:
        """Every reader must honour its own docstring: absent means unreadable, not fatal.

        A helper whose whole job is to explain why a toolchain is unusable must not raise
        FileNotFoundError out of the explanation.
        """

        absent = str(self.root / "no-such-binary")
        self.assertIsNone(media_probe.tool_version(absent))
        self.assertIsNone(media_probe.tool_version_text(absent))
        problem = media_probe.version_problem(absent)
        self.assertIsNotNone(problem)
        self.assertIn("could not read the version", problem or "")
        self.assertIn("4.4 or later", problem or "")

    def test_the_real_local_toolchain_still_passes_the_gate(self) -> None:
        if not media_probe.have_tools():
            self.skipTest("ffmpeg and ffprobe are not installed here")
        media_probe.require_supported_tools()
        for binary in ("ffprobe", "ffmpeg"):
            self.assertIsNone(media_probe.version_problem(binary), binary)


class ProductionGuardTests(unittest.TestCase):
    """The production boundary must refuse an unsupported toolchain before it runs."""

    def test_the_execution_adapter_gate_reports_the_version_problem(self) -> None:
        from src.ai_autocut import execution_adapters

        original = media_probe.version_problem
        media_probe.version_problem = lambda binary="ffprobe": (  # type: ignore[assignment]
            "ffprobe 4.4.2 is not supported; FFmpeg 5.1 or later is required")
        try:
            with self.assertRaises(execution_adapters.ExecutionAdapterError) as caught:
                execution_adapters._require_tools()
        finally:
            media_probe.version_problem = original  # type: ignore[assignment]
        self.assertIn("5.1 or later", str(caught.exception))

    def test_a_supported_toolchain_passes_the_execution_adapter_gate(self) -> None:
        if not media_probe.have_tools():
            self.skipTest("ffmpeg and ffprobe are not installed here")
        from src.ai_autocut import execution_adapters

        execution_adapters._require_tools()


class EnvironmentNoteTests(unittest.TestCase):
    def test_the_repository_reports_which_ffmpeg_it_was_verified_on(self) -> None:
        """A readable, non-fatal fact for anyone diagnosing a cross-platform failure."""

        if not media_probe.have_tools():
            self.skipTest("ffmpeg and ffprobe are not installed here")
        version = media_probe.tool_version("ffprobe")
        self.assertIsNotNone(version)
        self.assertGreaterEqual(version or (0, 0), media_probe.MINIMUM_FFMPEG_VERSION,
                                os.environ.get("PATH", ""))


if __name__ == "__main__":
    unittest.main()
