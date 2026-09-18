"""The typography execution boundary.

The audit found there is no production-capable typography executor in the repository:
``typography.py`` validates policy and deliberately refuses to place text, and the two
real rendering jobs are mutually incompatible one-off scripts. The risk in "fixing" that
is picking one SKU's layout numbers as the generic default, which would silently convert
one product's art direction into every product's art direction.

These tests hold the boundary: the generic layer owns the *contract*, a job supplies its
own geometry, and the Cushion Puff values never appear here as defaults.
"""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

from src.ai_autocut.typography import (
    DEFAULT_VISUAL_DIRECTION,
    MINIMUM_CONSIDERATIONS,
    TextEvent,
    TypographyPlan,
)
from src.ai_autocut.typography_adapter import (
    MissingTypographyExecutor,
    TypographyAdapterError,
    TypographyExecutor,
    TypographyRequest,
    TypographyResult,
    execute_typography,
)

MODULE_PATH = Path("src/ai_autocut/typography_adapter.py")

#: Art-direction values that belong to the Cushion Puff job and must never become
#: generic defaults.
CUSHION_PUFF_VALUES = (
    "Y_CENTER",
    "LEFT_MARGIN",
    "SIZE_L1",
    "SIZE_L2",
    "SHADOW_OFFSET",
    "SHADOW_BLUR",
    "SHADOW_ALPHA",
    "Avenir",
    "1620",
)


def plan(*, verified: bool = True) -> TypographyPlan:
    event = TextEvent(
        event_id="E1",
        role="hook",
        lines=("HELLO",),
        motion="fade",
        considered_zones=MINIMUM_CONSIDERATIONS,
        emphasis_terms=(),
        safe_area_verified=verified,
    )
    return TypographyPlan(visual_direction=DEFAULT_VISUAL_DIRECTION, events=(event,))


def request(**overrides: object) -> TypographyRequest:
    fields: dict[str, object] = {
        "job_id": "job-1",
        "master_path": "master.mp4",
        "out_path": "out.mp4",
        "plan": plan(),
        "frame_count": 120,
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "layout": {"lower_third_center": 1000},
        "font_stack": ("Some Job Font",),
    }
    fields.update(overrides)
    return TypographyRequest(**fields)  # type: ignore[arg-type]


class FakeExecutor:
    executor_id = "fake-job-executor"

    def __init__(self, **result_overrides: object) -> None:
        self.calls: list[TypographyRequest] = []
        self._overrides = result_overrides

    def render(self, req: TypographyRequest) -> TypographyResult:
        self.calls.append(req)
        fields: dict[str, object] = {
            "out_path": req.out_path,
            "executor_id": self.executor_id,
            "frame_count": req.frame_count,
            "width": req.width,
            "height": req.height,
            "layout_digest": "digest-1",
        }
        fields.update(self._overrides)
        return TypographyResult(**fields)  # type: ignore[arg-type]


class NoGenericArtDirectionTests(unittest.TestCase):
    """These inspect the module's *code*, not its prose.

    The module's docstring deliberately names the Cushion Puff values in order to say
    they are excluded, so a text scan would flag the explanation. Parsing the AST and
    dropping docstrings tests what the code actually declares.
    """

    @staticmethod
    def _code_surface() -> tuple[set[str], set[float], set[str]]:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        # Drop docstrings so prose cannot satisfy or trip the check.
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                body = getattr(node, "body", [])
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    body.pop(0)
        names: set[str] = set()
        numbers: set[float] = set()
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
            elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if not isinstance(node.value, bool):
                    numbers.add(float(node.value))
            elif isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split(".")[0])
        return names, numbers, imported

    def test_the_module_declares_no_cushion_puff_identifier(self) -> None:
        names, _, _ = self._code_surface()
        for value in CUSHION_PUFF_VALUES:
            with self.subTest(value=value):
                self.assertNotIn(
                    value,
                    names,
                    f"{value!r} is Cushion Puff art direction and must not appear as an "
                    "identifier in the generic typography boundary",
                )

    def test_the_module_declares_no_cushion_puff_geometry(self) -> None:
        _, numbers, _ = self._code_surface()
        for value in (1620.0, 96.0, 72.0, 130.0):
            with self.subTest(value=value):
                self.assertNotIn(
                    value,
                    numbers,
                    f"{value} is a Cushion Puff layout number and must not be a "
                    "constant in the generic typography boundary",
                )

    def test_the_module_imports_no_renderer(self) -> None:
        _, _, imported = self._code_surface()
        for forbidden in ("PIL", "Pillow", "subprocess", "numpy", "cv2"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, imported)

    def test_layout_has_no_default(self) -> None:
        with self.assertRaises(TypeError):
            TypographyRequest(  # type: ignore[call-arg]
                job_id="j", master_path="m", out_path="o", plan=plan(),
                frame_count=1, fps=30, width=1, height=1, font_stack=("F",),
            )

    def test_an_empty_layout_is_refused(self) -> None:
        with self.assertRaises(TypographyAdapterError) as caught:
            request(layout={})
        self.assertIn("no default layout", str(caught.exception))

    def test_font_stack_has_no_default(self) -> None:
        with self.assertRaises(TypeError):
            TypographyRequest(  # type: ignore[call-arg]
                job_id="j", master_path="m", out_path="o", plan=plan(),
                frame_count=1, fps=30, width=1, height=1, layout={"a": 1},
            )

    def test_an_empty_font_stack_is_refused(self) -> None:
        with self.assertRaises(TypographyAdapterError) as caught:
            request(font_stack=())
        self.assertIn("no default font", str(caught.exception))

    def test_a_non_tuple_font_stack_is_refused(self) -> None:
        with self.assertRaises(TypographyAdapterError):
            request(font_stack=["A Font"])


class RequestValidationTests(unittest.TestCase):
    def test_a_valid_request_is_accepted(self) -> None:
        self.assertEqual(request().job_id, "job-1")

    def test_an_unverified_safe_area_is_refused(self) -> None:
        with self.assertRaises(TypographyAdapterError) as caught:
            request(plan=plan(verified=False))
        self.assertIn("E1", str(caught.exception))

    def test_a_missing_job_id_is_refused(self) -> None:
        with self.assertRaises(TypographyAdapterError):
            request(job_id="")

    def test_a_non_positive_frame_count_is_refused(self) -> None:
        with self.assertRaises(TypographyAdapterError):
            request(frame_count=0)

    def test_a_non_positive_dimension_is_refused(self) -> None:
        with self.assertRaises(TypographyAdapterError):
            request(width=0)


class ExecutorBoundaryTests(unittest.TestCase):
    def test_a_job_executor_is_invoked(self) -> None:
        executor = FakeExecutor()
        result = execute_typography(request(), executor)
        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(result.executor_id, "fake-job-executor")

    def test_the_executor_satisfies_the_protocol_structurally(self) -> None:
        self.assertIsInstance(FakeExecutor(), TypographyExecutor)

    def test_the_missing_executor_fails_loudly(self) -> None:
        with self.assertRaises(TypographyAdapterError) as caught:
            execute_typography(request(), MissingTypographyExecutor())
        self.assertIn("adapter boundary", str(caught.exception))

    def test_the_missing_executor_satisfies_the_protocol(self) -> None:
        self.assertIsInstance(MissingTypographyExecutor(), TypographyExecutor)

    def test_a_frame_count_mismatch_is_refused(self) -> None:
        with self.assertRaises(TypographyAdapterError) as caught:
            execute_typography(request(), FakeExecutor(frame_count=119))
        self.assertIn("119", str(caught.exception))

    def test_a_geometry_mismatch_is_refused(self) -> None:
        with self.assertRaises(TypographyAdapterError):
            execute_typography(request(), FakeExecutor(width=1920))

    def test_a_non_result_is_refused(self) -> None:
        class Bad:
            executor_id = "bad"

            def render(self, req: TypographyRequest) -> object:
                return {"out_path": "nope"}

        with self.assertRaises(TypographyAdapterError):
            execute_typography(request(), Bad())  # type: ignore[arg-type]

    def test_an_object_without_render_is_refused(self) -> None:
        class NotAnExecutor:
            executor_id = "nope"

        with self.assertRaises(TypographyAdapterError):
            execute_typography(request(), NotAnExecutor())  # type: ignore[arg-type]


class ResultTests(unittest.TestCase):
    def test_a_result_serialises_its_measurements(self) -> None:
        document = FakeExecutor().render(request()).as_dict()
        self.assertEqual(document["schema_version"], "typography_result.v1")
        self.assertEqual(document["frame_count"], 120)

    def test_a_result_without_an_executor_id_is_refused(self) -> None:
        with self.assertRaises(TypographyAdapterError):
            TypographyResult(
                out_path="o", executor_id="", frame_count=1,
                width=1, height=1, layout_digest="d",
            )


if __name__ == "__main__":
    unittest.main()
