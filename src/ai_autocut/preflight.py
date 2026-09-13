"""Offline JSON entry point for the committed multi-segment boundary guard.

This module is a thin adapter. It reads a ``boundary_preflight.v1`` JSON
document, validates the minimal contract, converts each entry into a
:class:`~src.ai_autocut.boundary_guard.GuardSegment`, delegates to the
already-committed guard, and renders a deterministic, auditable JSON report.

It deliberately does not reimplement any boundary logic: the guard owns the
business rules, this module owns parsing, exit-code semantics, and stable
output. It performs no network, media, editor, or process I/O beyond reading
the single JSON file named on the command line.

Contract rules enforced here:

* Canonical integer frames only. Ambiguous decimal-second fields are rejected
  by name rather than silently ignored, so a caller cannot smuggle a rounded
  timestamp into the boundary decision.
* Identifiers are logical IDs, not filesystem paths. A path-like identifier is
  refused so machine-local absolute paths never reach the audit report.

Exit codes:

* ``0`` — input valid, boundary preflight passed
* ``1`` — input format, schema, contract, or runtime error
* ``2`` — input valid, but the guard found boundary business issues
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

from .boundary_guard import (
    BoundaryGuardContractError,
    GuardReport,
    GuardSegment,
    run_boundary_guard,
)
from .frame_boundary import FrameBoundaryError, SourceRange

SCHEMA_VERSION = "boundary_preflight.v1"

EXIT_OK = 0
EXIT_CONTRACT_ERROR = 1
EXIT_BOUNDARY_ISSUES = 2

_TOP_LEVEL_KEYS = ("schema_version", "segments")
_SEGMENT_KEYS = (
    "segment_id",
    "candidate_id",
    "source_id",
    "source_range",
    "continuation_group",
    "verified_safe_end_frame_exclusive",
    "planned_record_frame_relative",
)
_SOURCE_RANGE_KEYS = ("start_frame", "end_frame_exclusive")
_REQUIRED_SEGMENT_KEYS = ("segment_id", "candidate_id", "source_id", "source_range")

_USAGE = "usage: python3 -m src.ai_autocut.preflight INPUT.json"


class PreflightContractError(FrameBoundaryError):
    """Raised when the JSON preflight document violates its contract."""


def _as_object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise PreflightContractError(f"{label} must be a JSON object")
    return value


def _reject_seconds_fields(mapping: Mapping[str, object], label: str) -> None:
    """Refuse second-based keys by name before generic unknown-key handling.

    The versioned contract accepts canonical integer frames only. A public
    ``*_seconds`` field would invite a rounded decimal into the boundary
    decision, which is exactly the failure the frame kernel exists to prevent.
    """

    offending = sorted(
        key
        for key in mapping
        if key in {"seconds", "source_in_seconds", "source_out_seconds"}
        or key.endswith(("_seconds", "_sec", "_secs"))
    )
    if offending:
        raise PreflightContractError(
            f"{label} uses second-based field(s): {', '.join(offending)}; "
            f"{SCHEMA_VERSION} accepts canonical integer frames only — convert "
            "seconds to exact frame numbers before calling preflight"
        )


def _reject_unknown_keys(
    mapping: Mapping[str, object], allowed: Sequence[str], label: str
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise PreflightContractError(
            f"{label} has unsupported key(s): {', '.join(unknown)}; "
            f"allowed keys are: {', '.join(allowed)}"
        )


def _looks_like_local_path(value: str) -> bool:
    if value.startswith(("/", "~", "\\")):
        return True
    if len(value) >= 3 and value[1] == ":" and value[2] in "/\\":
        return True
    return "\\" in value


def _logical_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PreflightContractError(f"{label} must be a non-empty string")
    if _looks_like_local_path(value):
        # The offending value is intentionally not echoed: it is a local path.
        raise PreflightContractError(
            f"{label} must be a logical identifier, not a local filesystem path; "
            "refusing to record a machine-local path in the preflight report"
        )
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _logical_identifier(value, label)


def _optional_frame(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PreflightContractError(
            f"{label} must be a non-negative integer frame or null"
        )
    if value < 0:
        raise PreflightContractError(
            f"{label} must be a non-negative integer frame or null"
        )
    return value


def _parse_source_range(value: object, label: str) -> SourceRange:
    mapping = _as_object(value, label)
    _reject_seconds_fields(mapping, label)
    _reject_unknown_keys(mapping, _SOURCE_RANGE_KEYS, label)
    missing = [key for key in _SOURCE_RANGE_KEYS if key not in mapping]
    if missing:
        raise PreflightContractError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )
    try:
        return SourceRange(
            start_frame=mapping["start_frame"],  # type: ignore[arg-type]
            end_frame_exclusive=mapping["end_frame_exclusive"],  # type: ignore[arg-type]
        )
    except FrameBoundaryError as exc:
        raise PreflightContractError(f"{label} is invalid: {exc}") from exc


def _parse_segment(value: object, index: int) -> GuardSegment:
    label = f"segments[{index}]"
    mapping = _as_object(value, label)
    _reject_seconds_fields(mapping, label)
    _reject_unknown_keys(mapping, _SEGMENT_KEYS, label)
    missing = [key for key in _REQUIRED_SEGMENT_KEYS if key not in mapping]
    if missing:
        raise PreflightContractError(
            f"{label} is missing required key(s): {', '.join(missing)}"
        )
    try:
        return GuardSegment(
            segment_id=_logical_identifier(mapping["segment_id"], f"{label}.segment_id"),
            candidate_id=_logical_identifier(
                mapping["candidate_id"], f"{label}.candidate_id"
            ),
            source_id=_logical_identifier(mapping["source_id"], f"{label}.source_id"),
            source_range=_parse_source_range(
                mapping["source_range"], f"{label}.source_range"
            ),
            continuation_group=_optional_text(
                mapping.get("continuation_group"), f"{label}.continuation_group"
            ),
            verified_safe_end_frame_exclusive=_optional_frame(
                mapping.get("verified_safe_end_frame_exclusive"),
                f"{label}.verified_safe_end_frame_exclusive",
            ),
            planned_record_frame_relative=_optional_frame(
                mapping.get("planned_record_frame_relative"),
                f"{label}.planned_record_frame_relative",
            ),
        )
    except BoundaryGuardContractError as exc:
        raise PreflightContractError(f"{label} is invalid: {exc}") from exc


def parse_preflight_document(document: object) -> tuple[GuardSegment, ...]:
    """Validate a decoded ``boundary_preflight.v1`` document into guard input."""

    mapping = _as_object(document, "preflight document")
    _reject_seconds_fields(mapping, "preflight document")
    _reject_unknown_keys(mapping, _TOP_LEVEL_KEYS, "preflight document")

    version = mapping.get("schema_version")
    if version != SCHEMA_VERSION:
        raise PreflightContractError(
            f"schema_version must be {SCHEMA_VERSION!r}, got {version!r}"
        )

    if "segments" not in mapping:
        raise PreflightContractError(
            "preflight document is missing required key: segments"
        )
    raw_segments = mapping["segments"]
    if not isinstance(raw_segments, list):
        raise PreflightContractError("segments must be a JSON array")
    if not raw_segments:
        raise PreflightContractError("segments must not be empty")

    return tuple(
        _parse_segment(item, index) for index, item in enumerate(raw_segments)
    )


def run_preflight(segments: Sequence[GuardSegment]) -> GuardReport:
    """Delegate the boundary decision to the committed guard engine."""

    return run_boundary_guard(segments)


def build_report(report: GuardReport) -> dict[str, object]:
    """Wrap a guard report in a versioned, audit-stable envelope."""

    payload = report.as_dict()
    return {
        "schema_version": SCHEMA_VERSION,
        "passed": payload["passed"],
        "segments_checked": len(report.placements),
        "total_frames": payload["total_frames"],
        "issues": payload["issues"],
        "placements": payload["placements"],
    }


def render_report(report: Mapping[str, object]) -> str:
    """Render a report as deterministically ordered JSON text."""

    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def preflight_document(document: object) -> dict[str, object]:
    """Parse, guard, and build the report for a decoded JSON document."""

    return build_report(run_preflight(parse_preflight_document(document)))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the offline preflight CLI and return its documented exit code."""

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(_USAGE, file=sys.stderr)
        return EXIT_CONTRACT_ERROR

    try:
        text = Path(args[0]).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"preflight error: cannot read input: {exc}", file=sys.stderr)
        return EXIT_CONTRACT_ERROR
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        print(
            f"preflight error: input is not valid JSON: "
            f"line {exc.lineno} column {exc.colno}: {exc.msg}",
            file=sys.stderr,
        )
        return EXIT_CONTRACT_ERROR

    try:
        report = preflight_document(document)
    except FrameBoundaryError as exc:
        print(f"preflight contract error: {exc}", file=sys.stderr)
        return EXIT_CONTRACT_ERROR
    except Exception as exc:  # runtime failure must not masquerade as a guard result
        print(
            f"preflight runtime error: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return EXIT_CONTRACT_ERROR

    sys.stdout.write(render_report(report))
    return EXIT_OK if report["passed"] else EXIT_BOUNDARY_ISSUES


if __name__ == "__main__":
    raise SystemExit(main())
