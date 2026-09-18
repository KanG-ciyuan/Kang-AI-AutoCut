"""Typography execution boundary.

This module owns **the contract, not the renderer**.

Why the boundary exists
-----------------------
``typography.py`` validates policy and deliberately refuses to place text:
``PLACEMENT_IMPLEMENTATION`` is ``"NOT_IMPLEMENTED"`` and
``assert_placement_implemented()`` raises. That refusal is correct and is kept. What
was missing was a *named shape* for the thing that does execute, so that the
production fast path can require an executor without the policy module pretending to
be one.

The temptation this design removes
----------------------------------
Both SKUs rasterised text with Pillow and composited with FFmpeg, using different
fonts, different safe bands and different composition techniques. It is tempting to
"unify" them by picking one set of numbers as the default. That would silently
convert one product's art direction into every product's art direction.

So the request carries **no layout defaults at all**. ``layout`` and ``font_stack``
are required fields with no fallback: a job that does not state its own typography
geometry cannot be rendered, and cannot accidentally inherit another job's.

Deliberately absent from this module
------------------------------------
``Y_CENTER = 1620``, ``LEFT_MARGIN = 96``, ``SIZE_L1 = 96``, ``SIZE_L2 = 72``, the
Avenir Next font stack, shadow offset/blur/alpha, and the Cushion Puff ``UNITS`` list.
Those are job-scoped art direction. They belong to a job's executor, never here.

A Pillow + FFmpeg implementation may later be attached as a *job-specific* executor
implementing :class:`TypographyExecutor`. Nothing in this module imports Pillow,
FFmpeg, or any renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, runtime_checkable

from .typography import TypographyPlan, TypographyPolicyError


class TypographyAdapterError(ValueError):
    """Raised when a typography request cannot be executed safely."""


def _non_empty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypographyAdapterError(f"{label} must be a non-empty string")
    return value


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise TypographyAdapterError(f"{label} must be a positive integer")
    return value


@dataclass(frozen=True)
class TypographyRequest:
    """One typography execution request.

    Every geometry-bearing field is supplied by the caller for this job. There are no
    defaults, because a default here would be one product's art direction imposed on
    another product.
    """

    job_id: str
    master_path: str
    out_path: str
    plan: TypographyPlan
    frame_count: int
    fps: int
    width: int
    height: int
    layout: Mapping[str, object]
    font_stack: tuple[str, ...]

    def __post_init__(self) -> None:
        _non_empty(self.job_id, "job_id")
        _non_empty(self.master_path, "master_path")
        _non_empty(self.out_path, "out_path")
        if not isinstance(self.plan, TypographyPlan):
            raise TypographyAdapterError("plan must be a TypographyPlan")
        _positive_int(self.frame_count, "frame_count")
        _positive_int(self.fps, "fps")
        _positive_int(self.width, "width")
        _positive_int(self.height, "height")

        # Art direction is required, never defaulted. An empty mapping is refused so a
        # caller cannot pass `{}` and quietly get whatever the executor happens to do.
        if not isinstance(self.layout, Mapping) or not self.layout:
            raise TypographyAdapterError(
                "layout is required and must state this job's typography geometry; "
                "there is no default layout, because a default would be one job's art "
                "direction applied to another"
            )
        if not isinstance(self.font_stack, tuple) or not self.font_stack:
            raise TypographyAdapterError(
                "font_stack is required as a non-empty tuple of this job's fonts; "
                "there is no default font"
            )
        for index, font in enumerate(self.font_stack):
            _non_empty(font, f"font_stack[{index}]")

        # A plan whose safe area was never verified must not reach a renderer. This is
        # the policy module's own refusal condition, enforced at the boundary.
        unreleasable = self.plan.unreleasable_events()
        if unreleasable:
            raise TypographyAdapterError(
                "typography plan has events with an unverified safe area: "
                + ", ".join(unreleasable)
            )


@dataclass(frozen=True)
class TypographyResult:
    """What an executor reports back. Measurements, not claims."""

    out_path: str
    executor_id: str
    frame_count: int
    width: int
    height: int
    layout_digest: str

    def __post_init__(self) -> None:
        _non_empty(self.out_path, "out_path")
        _non_empty(self.executor_id, "executor_id")
        _non_empty(self.layout_digest, "layout_digest")
        _positive_int(self.frame_count, "frame_count")
        _positive_int(self.width, "width")
        _positive_int(self.height, "height")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "typography_result.v1",
            "out_path": self.out_path,
            "executor_id": self.executor_id,
            "frame_count": self.frame_count,
            "width": self.width,
            "height": self.height,
            "layout_digest": self.layout_digest,
        }


@runtime_checkable
class TypographyExecutor(Protocol):
    """The narrow interface a job-specific typography renderer implements.

    A Pillow + FFmpeg implementation satisfies this by exposing ``executor_id`` and a
    ``render`` method. The protocol is structural, so no inheritance is required and no
    renderer is imported here.
    """

    executor_id: str

    def render(self, request: TypographyRequest) -> TypographyResult:  # pragma: no cover
        ...


class MissingTypographyExecutor:
    """The executor used when a job has not supplied one.

    It fails loudly rather than returning something that looks rendered. The fast path
    uses it so ``PLAN THE WORDS`` cannot silently report success without an executor.
    """

    executor_id = "MISSING_TYPOGRAPHY_EXECUTOR"

    def render(self, request: TypographyRequest) -> TypographyResult:
        raise TypographyAdapterError(
            "no typography executor is configured for this job; typography execution "
            "is an adapter boundary and a job must supply its own executor. The "
            "generic layer owns the contract only — it deliberately does not ship a "
            "renderer or any default layout"
        )


def execute_typography(
    request: TypographyRequest, executor: TypographyExecutor
) -> TypographyResult:
    """Run one typography request through an executor, checking the result shape."""

    if not isinstance(request, TypographyRequest):
        raise TypographyAdapterError("request must be a TypographyRequest")
    if not isinstance(executor, TypographyExecutor):
        raise TypographyAdapterError(
            "executor must satisfy TypographyExecutor (executor_id + render)"
        )
    result = executor.render(request)
    if not isinstance(result, TypographyResult):
        raise TypographyAdapterError("an executor must return a TypographyResult")
    if result.frame_count != request.frame_count:
        raise TypographyAdapterError(
            f"executor produced {result.frame_count} frames where "
            f"{request.frame_count} were requested"
        )
    if (result.width, result.height) != (request.width, request.height):
        raise TypographyAdapterError(
            "executor output geometry does not match the request"
        )
    return result


__all__ = [
    "MissingTypographyExecutor",
    "TypographyAdapterError",
    "TypographyExecutor",
    "TypographyRequest",
    "TypographyResult",
    "execute_typography",
]
