"""Machine-independent path configuration and path-hygiene rules.

This module is the only sanctioned place where AI-AutoCut code learns about
machine-specific locations. Every location is a *logical* role that resolves
from an environment variable, so no canonical source file, test, fixture, or
committed configuration carries a personal absolute path.

Two rules are enforced here rather than documented and hoped for:

1. Runtime locations arrive through environment variables or an explicit
   argument. They are never defaulted to a developer's home directory.
2. DaVinci Resolve Free 21.0.0 was observed to fail silently on non-ASCII I/O
   paths, so Resolve-bound staging is required to be ASCII-safe.

The module performs no filesystem writes and does not create any directory.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence


# Environment variable names that form the public configuration contract.
ENV_WORKSPACE = "AUTOCUT_WORKSPACE"
ENV_MEDIA_ROOT = "AUTOCUT_MEDIA_ROOT"
ENV_LEGACY_WORKSPACE = "AUTOCUT_LEGACY_WORKSPACE"
ENV_ASCII_STAGING = "AUTOCUT_ASCII_STAGING"
ENV_PRODUCTION_ROOT = "AUTOCUT_PRODUCTION_ROOT"
ENV_DAVINCI_PATH = "DAVINCI_PATH"
ENV_JIANYING_PATH = "JIANYING_PATH"

# Logical role names accepted by PathConfiguration.require().
ROLE_WORKSPACE = "workspace"
ROLE_MEDIA_ROOT = "media_root"
ROLE_LEGACY_WORKSPACE = "legacy_workspace"
ROLE_ASCII_STAGING = "ascii_staging"
ROLE_PRODUCTION_ROOT = "production_root"
ROLE_DAVINCI_PATH = "davinci_path"
ROLE_JIANYING_PATH = "jianying_path"

_ROLE_ENVIRONMENT = {
    ROLE_WORKSPACE: ENV_WORKSPACE,
    ROLE_MEDIA_ROOT: ENV_MEDIA_ROOT,
    ROLE_LEGACY_WORKSPACE: ENV_LEGACY_WORKSPACE,
    ROLE_ASCII_STAGING: ENV_ASCII_STAGING,
    ROLE_PRODUCTION_ROOT: ENV_PRODUCTION_ROOT,
    ROLE_DAVINCI_PATH: ENV_DAVINCI_PATH,
    ROLE_JIANYING_PATH: ENV_JIANYING_PATH,
}

# Prefixes that make a value a machine-bound path. Used to refuse path-shaped
# identifiers in contract values.
#
# These are assembled from fragments rather than written literally: the hygiene
# test scans every text file in the repository, including this one, and would
# otherwise flag its own definition as a violation.
_BACKSLASH = chr(92)
MACHINE_PATH_PREFIXES = (
    "/" + "Users" + "/",
    "/" + "home" + "/",
    "/" + "Volumes" + "/",
    "C:" + _BACKSLASH,
    _BACKSLASH + _BACKSLASH,
)

# Patterns identifying a *complete* personal path: a user-profile or volume root
# followed by a real name.
#
# Scanning is stricter than prefix matching on purpose. A bare `"/Users/"` is a
# privacy assertion in a test — it claims that no user path reached the output —
# and a Windows drive letter is generic platform syntax used in path-rejection
# probes. Neither embeds anybody's machine, so neither is reported. What is
# reported is a root with an actual name attached.
#
# Every pattern is assembled from fragments so that no pattern's own source text
# matches any pattern in this tuple. The repository hygiene test scans this file
# too, and a self-matching scanner is a scanner nobody can keep green.
_BACKSLASH_ESCAPED = chr(92) * 2  # a regex escape for one literal backslash
MACHINE_PATH_PATTERNS = (
    re.compile(r"/(?:Users|home)/[^/\s\"'`),;]+"),
    re.compile("/" + "Volumes" + "/" + r"[^/\s\"'`),;]+"),
    # Matches a Windows profile component in either escaped or raw form, which
    # also covers a drive-letter path that names a profile directory.
    re.compile(_BACKSLASH_ESCAPED + "Users" + _BACKSLASH_ESCAPED),
)

_HYGIENE_TEXT_SUFFIXES = (
    ".md",
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".ini",
    ".txt",
    ".sh",
)

_HYGIENE_SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)


class PathConfigurationError(ValueError):
    """Raised when a required logical location is unset or unusable."""


def _clean(environ: Mapping[str, str], name: str) -> Path | None:
    raw = environ.get(name)
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    return Path(stripped).expanduser()


def is_ascii_safe(value: object) -> bool:
    """Return whether a path can be handed to a Resolve-bound operation."""

    if not isinstance(value, (str, Path)):
        return False
    text = str(value)
    if not text:
        return False
    try:
        text.encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def assert_ascii_safe(path: object, *, role: str = "path") -> Path:
    """Fail closed when a Resolve-bound path is not ASCII-safe."""

    if not isinstance(path, (str, Path)):
        raise PathConfigurationError(f"{role} must be a path")
    if not is_ascii_safe(path):
        raise PathConfigurationError(
            f"{role} must be an ASCII-safe path: DaVinci Resolve Free 21.0.0 "
            "was observed to fail silently on non-ASCII I/O paths; stage the "
            "media through an ASCII-safe directory first"
        )
    return Path(path)


def looks_like_machine_path(value: object) -> bool:
    """Return whether a string is shaped like a machine-bound absolute path."""

    if not isinstance(value, str) or not value:
        return False
    if value.startswith(("~", "file://")):
        return True
    return value.startswith(MACHINE_PATH_PREFIXES)


@dataclass(frozen=True)
class PathConfiguration:
    """Resolved logical locations. Every field is optional by design."""

    workspace: Path | None = None
    media_root: Path | None = None
    legacy_workspace: Path | None = None
    ascii_staging: Path | None = None
    production_root: Path | None = None
    davinci_path: Path | None = None
    jianying_path: Path | None = None

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "PathConfiguration":
        source: Mapping[str, str] = os.environ if environ is None else environ
        if not isinstance(source, Mapping):
            raise PathConfigurationError("environ must be a mapping")
        return cls(
            workspace=_clean(source, ENV_WORKSPACE),
            media_root=_clean(source, ENV_MEDIA_ROOT),
            legacy_workspace=_clean(source, ENV_LEGACY_WORKSPACE),
            ascii_staging=_clean(source, ENV_ASCII_STAGING),
            production_root=_clean(source, ENV_PRODUCTION_ROOT),
            davinci_path=_clean(source, ENV_DAVINCI_PATH),
            jianying_path=_clean(source, ENV_JIANYING_PATH),
        )

    def get(self, role: str) -> Path | None:
        if role not in _ROLE_ENVIRONMENT:
            raise PathConfigurationError(f"unknown path role: {role!r}")
        return getattr(self, role)

    def require(self, role: str) -> Path:
        """Return one configured location or fail with the variable to set."""

        if role not in _ROLE_ENVIRONMENT:
            raise PathConfigurationError(f"unknown path role: {role!r}")
        value = getattr(self, role)
        if value is None:
            raise PathConfigurationError(
                f"logical location {role!r} is not configured; "
                f"set {_ROLE_ENVIRONMENT[role]}"
            )
        return value

    def require_ascii_safe(self, role: str) -> Path:
        """Return one configured location, refusing a non-ASCII-safe value."""

        return assert_ascii_safe(self.require(role), role=role)

    def describe(self) -> dict[str, str | None]:
        """Return a report-safe mapping. Unset roles stay ``None``."""

        return {
            role: (None if self.get(role) is None else str(self.get(role)))
            for role in sorted(_ROLE_ENVIRONMENT)
        }


def iter_repository_text_files(root: object) -> Iterable[Path]:
    """Yield committed-text-like files under ``root``, skipping caches."""

    if not isinstance(root, (str, Path)):
        raise PathConfigurationError("root must be a path")
    base = Path(root)
    if not base.is_dir():
        raise PathConfigurationError("root must be an existing directory")
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _HYGIENE_SKIP_DIRECTORIES for part in path.parts):
            continue
        if path.suffix.lower() in _HYGIENE_TEXT_SUFFIXES:
            yield path


def find_machine_paths(
    root: object, *, patterns: Sequence[re.Pattern[str]] = MACHINE_PATH_PATTERNS
) -> tuple[tuple[str, int, str], ...]:
    """Return ``(relative_path, line_number, evidence)`` for personal paths.

    The scan is deliberately textual and conservative: it reports where a
    complete personal path occurs so a reviewer can judge the context, and it
    never rewrites files.
    """

    if isinstance(patterns, (str, bytes)) or not isinstance(patterns, Sequence):
        raise PathConfigurationError("patterns must be a sequence of patterns")
    base = Path(root)
    findings: list[tuple[str, int, str]] = []
    for path in iter_repository_text_files(base):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for pattern in patterns:
                match = pattern.search(line)
                if match is not None:
                    findings.append(
                        (str(path.relative_to(base)), number, match.group(0))
                    )
                    break
    return tuple(findings)
