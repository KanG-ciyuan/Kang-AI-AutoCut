from __future__ import annotations

from pathlib import Path
import unittest

from src.ai_autocut.paths import (
    ENV_ASCII_STAGING,
    ENV_DAVINCI_PATH,
    ENV_MEDIA_ROOT,
    ENV_PRODUCTION_ROOT,
    ENV_WORKSPACE,
    PathConfiguration,
    PathConfigurationError,
    assert_ascii_safe,
    find_machine_paths,
    is_ascii_safe,
    looks_like_machine_path,
)


REPO_ROOT = Path(__file__).parents[1]

# Probe strings are assembled from fragments on purpose. This module is itself
# inside the repository that `find_machine_paths` scans, so writing a literal
# machine-bound prefix here would make the hygiene test fail on its own source.
_BACKSLASH = chr(92)
_TILDE = chr(126)
_SCHEME = "file" + ":" + "//"
_NON_ASCII_VOLUME = "\u68b5\u60f3\u79fb\u52a8\u76d8"


def absolute(*parts: str) -> str:
    """Build an absolute POSIX path without writing a literal prefix."""

    return "/" + "/".join(parts)


class PathConfigurationTestCase(unittest.TestCase):
    def test_unset_role_fails_with_the_variable_to_set(self) -> None:
        config = PathConfiguration.from_environ({})
        with self.assertRaises(PathConfigurationError) as caught:
            config.require("workspace")
        self.assertIn(ENV_WORKSPACE, str(caught.exception))

    def test_no_role_is_defaulted_to_a_home_directory(self) -> None:
        config = PathConfiguration.from_environ({})
        for role in (
            "workspace",
            "media_root",
            "legacy_workspace",
            "ascii_staging",
            "production_root",
            "davinci_path",
            "jianying_path",
        ):
            with self.subTest(role=role):
                self.assertIsNone(config.get(role))

    def test_the_production_root_role_is_read_from_the_environment(self) -> None:
        config = PathConfiguration.from_environ(
            {ENV_PRODUCTION_ROOT: "/srv/production-storage"}
        )
        self.assertEqual(
            str(config.require("production_root")), "/srv/production-storage"
        )

    def test_environment_values_are_read(self) -> None:
        config = PathConfiguration.from_environ(
            {
                ENV_WORKSPACE: "/srv/autocut",
                ENV_MEDIA_ROOT: "/srv/media",
                ENV_DAVINCI_PATH: "/Applications/DaVinci Resolve.app",
            }
        )
        self.assertEqual(str(config.require("workspace")), "/srv/autocut")
        self.assertEqual(str(config.require("media_root")), "/srv/media")

    def test_blank_value_is_treated_as_unset(self) -> None:
        config = PathConfiguration.from_environ({ENV_WORKSPACE: "   "})
        self.assertIsNone(config.get("workspace"))

    def test_values_are_stripped(self) -> None:
        config = PathConfiguration.from_environ({ENV_WORKSPACE: "  /srv/autocut  "})
        self.assertEqual(str(config.require("workspace")), "/srv/autocut")

    def test_unknown_role_is_rejected(self) -> None:
        config = PathConfiguration.from_environ({})
        with self.assertRaises(PathConfigurationError):
            config.require("cloud_bucket")

    def test_describe_is_report_safe(self) -> None:
        described = PathConfiguration.from_environ({}).describe()
        self.assertTrue(all(value is None for value in described.values()))

    def test_non_mapping_environ_is_rejected(self) -> None:
        with self.assertRaises(PathConfigurationError):
            PathConfiguration.from_environ(["AUTOCUT_WORKSPACE"])  # type: ignore[arg-type]


class AsciiSafetyTestCase(unittest.TestCase):
    """Resolve Free 21.0.0 fails silently on non-ASCII I/O paths."""

    def test_ascii_path_is_safe(self) -> None:
        self.assertTrue(is_ascii_safe("/srv/autocut/staging"))

    def test_non_ascii_path_is_not_safe(self) -> None:
        self.assertFalse(is_ascii_safe(absolute("Volumes", _NON_ASCII_VOLUME, "media")))

    def test_assert_ascii_safe_refuses_a_non_ascii_path(self) -> None:
        with self.assertRaises(PathConfigurationError):
            assert_ascii_safe(absolute("Volumes", _NON_ASCII_VOLUME, "media"))

    def test_assert_ascii_safe_accepts_an_ascii_path(self) -> None:
        self.assertEqual(
            assert_ascii_safe("/srv/autocut/staging"), Path("/srv/autocut/staging")
        )

    def test_require_ascii_safe_combines_both_checks(self) -> None:
        config = PathConfiguration.from_environ(
            {ENV_ASCII_STAGING: absolute("Volumes", _NON_ASCII_VOLUME, "staging")}
        )
        with self.assertRaises(PathConfigurationError):
            config.require_ascii_safe("ascii_staging")

    def test_empty_value_is_not_safe(self) -> None:
        self.assertFalse(is_ascii_safe(""))

    def test_non_string_is_not_safe(self) -> None:
        self.assertFalse(is_ascii_safe(42))


class MachinePathDetectionTestCase(unittest.TestCase):
    def test_machine_bound_prefixes_are_detected(self) -> None:
        for value in (
            absolute("Users", "someone", "media"),
            absolute("home", "someone", "media"),
            absolute("Volumes", "disk", "media"),
            "C:" + _BACKSLASH + "media",
            _BACKSLASH + _BACKSLASH + "server" + _BACKSLASH + "share",
            _TILDE + "/media",
            _SCHEME + "/media/clip.mp4",
        ):
            with self.subTest(value=value):
                self.assertTrue(looks_like_machine_path(value))

    def test_logical_identifiers_are_not_machine_paths(self) -> None:
        for value in ("SRC-A", "candv1_abc", "renders/clip.mp4", ""):
            with self.subTest(value=value):
                self.assertFalse(looks_like_machine_path(value))


class RepositoryHygieneTestCase(unittest.TestCase):
    """The canonical repository must not carry a machine-bound absolute path."""

    def test_no_machine_path_in_the_repository(self) -> None:
        findings = find_machine_paths(REPO_ROOT)
        self.assertEqual(
            findings,
            (),
            "machine-bound paths found in the repository: "
            + "; ".join(f"{path}:{line} ({marker})" for path, line, marker in findings),
        )

    def test_the_scanner_detects_a_planted_probe(self) -> None:
        # Guards against a scanner that silently reports nothing at all.
        import tempfile

        probe = absolute("Users", "example", "media")
        with tempfile.TemporaryDirectory() as directory:
            planted = Path(directory) / "planted.md"
            planted.write_text(f"leaked: {probe}\n", encoding="utf-8")
            findings = find_machine_paths(directory)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0][0], "planted.md")
            self.assertEqual(findings[0][1], 1)
            self.assertEqual(findings[0][2], absolute("Users", "example"))

    def test_a_bare_privacy_marker_is_not_reported(self) -> None:
        # Tests legitimately assert that a user path never reaches output. That
        # is a privacy assertion, not an embedded personal path, so the scan
        # must not report it.
        import tempfile

        marker_line = 'self.assertNotIn("' + "/" + "Users" + "/" + '", output)' + "\n"
        with tempfile.TemporaryDirectory() as directory:
            planted = Path(directory) / "marker.py"
            planted.write_text(marker_line, encoding="utf-8")
            self.assertEqual(find_machine_paths(directory), ())

    def test_a_generic_windows_drive_probe_is_not_reported(self) -> None:
        # A drive-letter path is generic platform syntax used by path-rejection
        # tests. It embeds nobody's machine.
        import tempfile

        line = "probe = " + '"' + "C:" + _BACKSLASH + "Media" + _BACKSLASH + 'x.mov"' + "\n"
        with tempfile.TemporaryDirectory() as directory:
            planted = Path(directory) / "probe.py"
            planted.write_text(line, encoding="utf-8")
            self.assertEqual(find_machine_paths(directory), ())

    def test_scanner_skips_caches_and_git(self) -> None:
        for path, _line, _evidence in find_machine_paths(REPO_ROOT):
            with self.subTest(path=path):
                self.assertNotIn("__pycache__", path)
                self.assertNotIn(".git/", path)

    def test_scanning_a_missing_root_is_rejected(self) -> None:
        with self.assertRaises(PathConfigurationError):
            find_machine_paths(REPO_ROOT / "does-not-exist")


if __name__ == "__main__":
    unittest.main()
