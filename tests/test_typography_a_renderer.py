"""Typography Art Direction A v1 renderer.

Before this existed, the production executor could set one colour and one size for a whole
event, place it at a fixed position, and nothing else. Against the locked A v1 design that is
a downgrade: no warm-gold emphasis, no stroke, no shadow, no accent rule, no motion, no
placement adaptation. The policy recorded it honestly as Renderer = NOT_IMPLEMENTED.

These tests pin each of those seven behaviours, and pin the two things that would quietly
undo them: that the renderer reads its look from the job's profile rather than from constants
of its own, and that a job without an art direction keeps exactly the behaviour it had.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from src.ai_autocut import (execution_adapters, media_probe, typography_art_direction as art,
                            typography_renderer as tr)

REPO = Path(__file__).resolve().parents[1]
PROFILE = REPO / "examples" / "typography" / "art-direction-a-v1.profile.json"


def profile() -> tr.RenderProfile:
    return tr.RenderProfile.load(PROFILE)


def example_profile_font_available() -> bool:
    """Whether the shipped A v1 profile's own font can be resolved on this host.

    The profile is one job's locked parameters and it names a macOS font
    (``/System/Library/Fonts/Avenir Next Condensed.ttc``). Rendering with it needs that
    exact file: the renderer refuses to substitute a font rather than silently changing
    the approved look, so on a host without it these classes report the environment gap
    instead of failing as though the renderer were broken. The design already expects each
    job to state its own font, so a non-macOS job is not blocked by this - only these
    macOS-profile fixtures are.
    """

    try:
        return os.path.isfile(profile().font_path)
    except Exception:
        return False


FONT_REQUIREMENT = (
    "the shipped A v1 profile names a macOS font that is not resolvable on this host"
)


def event(event_id="E01", role="HOOK", lines=("KOTORAN KULIT", "TERANGKAT"),
          emphasis=("TERANGKAT",), zone=None) -> art.TypographyEvent:
    return art.TypographyEvent(
        event_id=event_id, narrative_role=role, text_lines=tuple(lines),
        start_seconds=0.0, end_seconds=2.0,
        zone_name=zone or art.DEFAULT_ZONE_FOR_ROLE[role],
        emphasis_terms=tuple(emphasis))


# ------------------------------------------------------------------ profile


class ProfileTests(unittest.TestCase):
    def test_the_profile_loads_and_states_every_renderable_value(self) -> None:
        p = profile()
        self.assertEqual(p.profile_id, "third-sku-typography-a-v1")
        self.assertTrue(p.font_path)
        self.assertEqual(len(p.warm_white), 4)
        self.assertGreater(p.stroke_width, 0)
        self.assertGreater(p.shadow_blur, 0)
        self.assertGreater(p.accent_rule_height, 0)
        self.assertTrue(p.role_base_sizes)

    def test_a_profile_missing_art_direction_is_refused_not_defaulted(self) -> None:
        """A default font or colour here would be one SKU's art direction on another."""

        for document in ({}, {"profile_id": "x"}, {"font": {}}, {"canvas": {}}):
            with self.subTest(document=document):
                with self.assertRaises(tr.TypographyRenderError):
                    tr.RenderProfile.from_document(document)

    def test_an_unknown_role_has_no_base_size(self) -> None:
        with self.assertRaises(tr.TypographyRenderError):
            profile().base_size("TITLE")

    def test_the_renderer_carries_no_sku_specific_visual_constant(self) -> None:
        source = Path(tr.__file__).read_text(encoding="utf-8")
        for forbidden in ("KOTORAN", "TERANGKAT", "KLIK LINK", "Avenir", "247, 243, 234",
                          "216, 183, 122"):
            self.assertNotIn(forbidden, source)


# ------------------------------------------------------------------ runs


class RunSplitTests(unittest.TestCase):
    def test_a_whole_line_term_emphasises_the_whole_line(self) -> None:
        runs = tr.split_runs("TERANGKAT", ["TERANGKAT"])
        self.assertTrue(all(r.emphasised for r in runs))
        self.assertTrue(tr.line_is_wholly_emphasised(runs))

    def test_a_word_within_a_line_emphasises_only_that_word(self) -> None:
        runs = tr.split_runs("BUSA MELIMPAH", ["MELIMPAH"])
        self.assertEqual([(r.text, r.emphasised) for r in runs],
                         [("BUSA", False), ("MELIMPAH", True)])
        self.assertFalse(tr.line_is_wholly_emphasised(runs))

    def test_a_multi_word_term_is_matched_as_a_phrase(self) -> None:
        runs = tr.split_runs("BAGIAN TUBUH LAIN", ["BAGIAN TUBUH LAIN"])
        self.assertTrue(tr.line_is_wholly_emphasised(runs))

    def test_matching_is_case_insensitive_because_the_design_renders_upper(self) -> None:
        runs = tr.split_runs("Busa Melimpah", ["MELIMPAH"])
        self.assertEqual([(r.text, r.emphasised) for r in runs],
                         [("Busa", False), ("Melimpah", True)])

    def test_no_terms_means_one_plain_run(self) -> None:
        runs = tr.split_runs("PLAIN LINE", [])
        self.assertEqual(len(runs), 1)
        self.assertFalse(runs[0].emphasised)

    def test_emphasis_never_lands_mid_word(self) -> None:
        runs = tr.split_runs("MELIMPAHKAN", ["MELIMPAH"])
        self.assertFalse(any(r.emphasised for r in runs),
                         "a partial word match must not be emphasised")


# ------------------------------------------------------------------ render


@unittest.skipUnless(example_profile_font_available(), FONT_REQUIREMENT)
class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.p = profile()

    def overlay(self, **kwargs) -> tr.RenderedOverlay:
        return tr.render_events([event(**kwargs)], profile=self.p)[0]

    def test_emphasis_is_warm_gold_and_the_body_is_warm_white(self) -> None:
        """The single most visible A v1 behaviour, checked on actual pixels."""

        o = self.overlay()
        px = np.asarray(o.image)
        accent = np.array(self.p.accent[:3])
        white = np.array(self.p.warm_white[:3])
        opaque = px[..., 3] > 200
        near_accent = (np.abs(px[..., :3].astype(int) - accent).sum(axis=2) < 40) & opaque
        near_white = (np.abs(px[..., :3].astype(int) - white).sum(axis=2) < 40) & opaque
        self.assertGreater(near_accent.sum(), 200, "no warm-gold emphasis pixels")
        self.assertGreater(near_white.sum(), 200, "no warm-white body pixels")

    def test_a_wholly_emphasised_line_is_set_larger(self) -> None:
        """The reference's own behaviour: line-level emphasis carries the size step."""

        two = self.overlay(lines=("KOTORAN KULIT", "TERANGKAT"), emphasis=("TERANGKAT",))
        one = self.overlay(lines=("TERANGKAT",), emphasis=("TERANGKAT",))
        self.assertGreater(two.image.size[1], one.image.size[1],
                           "the emphasised second line did not add height")

    def test_a_light_stroke_and_a_soft_shadow_are_drawn(self) -> None:
        """Readability must come from these, because the design forbids a dark plate."""

        o = self.overlay()
        px = np.asarray(o.image).astype(int)
        opaque = px[..., 3] > 200
        stroke = np.array(self.p.stroke[:3])
        near_stroke = (np.abs(px[..., :3] - stroke).sum(axis=2) < 90) & opaque
        self.assertGreater(near_stroke.sum(), 100, "no stroke pixels")
        # a blurred shadow means partial alpha around the block
        partial = ((px[..., 3] > 10) & (px[..., 3] < 200)).sum()
        self.assertGreater(partial, 200, "no soft shadow falloff")

    def test_the_accent_rule_sits_above_the_text_and_is_gold(self) -> None:
        o = self.overlay()
        px = np.asarray(o.image).astype(int)
        accent = np.array(self.p.accent[:3])
        gold = (np.abs(px[..., :3] - accent).sum(axis=2) < 40) & (px[..., 3] > 200)
        rows = np.nonzero(gold.any(axis=1))[0]
        self.assertTrue(len(rows), "no gold pixels at all")
        # the topmost gold run is the rule, and it is wider than it is tall
        rule_rows = rows[rows <= rows.min() + self.p.accent_rule_height]
        rule_cols = np.nonzero(gold[rule_rows].any(axis=0))[0]
        self.assertGreater(rule_cols.max() - rule_cols.min(), 20, "rule is not a bar")

    def test_the_rule_is_centred_for_a_centred_zone(self) -> None:
        left = self.overlay(role="BODY_SELLING_POINT", lines=("PLAIN",), emphasis=())
        centre = self.overlay(role="CTA", lines=("PLAIN",), emphasis=())
        self.assertLess(left.left, centre.left,
                        "the CTA zone is centred and must not sit at the left margin")

    def test_text_is_placed_by_zone_not_by_free_coordinates(self) -> None:
        o = self.overlay(role="HOOK")
        self.assertEqual(o.zone, art.DEFAULT_ZONE_FOR_ROLE["HOOK"])
        rect = art.ZONES[o.zone].rect
        self.assertGreaterEqual(o.left, int(rect.x * self.p.canvas_width) - 60)
        self.assertIn(o.zone, art.ZONE_NAMES)

    def test_a_long_line_shrinks_to_fit_its_zone_rather_than_overflowing(self) -> None:
        """Size adaptation to text length is a rule, not a table of sizes."""

        long_line = ("BISA DIGUNAKAN UNTUK MENGGOSOK AREA TUBUH SEPERTI KAKI DAN TUMIT",)
        o = tr.render_events([art.TypographyEvent(
            event_id="L", narrative_role="BODY_SELLING_POINT", text_lines=long_line,
            start_seconds=0.0, end_seconds=2.0, zone_name="UPPER_LEFT",
            emphasis_terms=("MENGGOSOK AREA TUBUH",))], profile=self.p)[0]
        usable = int(art.ZONES["UPPER_LEFT"].rect.width * self.p.canvas_width)
        self.assertLessEqual(o.size[0], usable + 80)

    def test_motion_comes_from_the_profile_and_the_role(self) -> None:
        hook = tr.motion_for("HOOK", self.p)
        cta = tr.motion_for("CTA", self.p)
        self.assertEqual(hook.fade_in_seconds, self.p.fade_in_ms["HOOK"] / 1000.0)
        self.assertEqual(hook.settle_pixels, self.p.settle_px)
        self.assertNotEqual(hook.fade_in_seconds, cta.fade_in_seconds)

    def test_an_unknown_role_cannot_be_rendered(self) -> None:
        with self.assertRaises(art.TypographyArtDirectionError):
            art.TypographyEvent(event_id="X", narrative_role="TITLE", text_lines=("A",),
                                start_seconds=0.0, end_seconds=1.0, zone_name="UPPER_LEFT")


# ------------------------------------------------------------------ placement


@unittest.skipUnless(example_profile_font_available(), FONT_REQUIREMENT)
class PlacementTests(unittest.TestCase):
    """Placement stays 'stable zone plus controlled adaptation', never free positioning."""

    def test_the_default_zone_is_used_when_nothing_conflicts(self) -> None:
        for role in art.NARRATIVE_ROLES:
            with self.subTest(role=role):
                o = tr.render_events([event(role=role)], profile=profile())[0]
                self.assertEqual(o.zone, art.DEFAULT_ZONE_FOR_ROLE[role])

    def test_a_real_conflict_takes_one_fallback(self) -> None:
        band = [art.EvidenceRegion("product", art.Rect(0.0, 0.08, 1.0, 0.12))]
        o = tr.render_events([event(role="BODY_SELLING_POINT")], profile=profile(),
                             evidence=band)[0]
        self.assertNotEqual(o.zone, art.DEFAULT_ZONE_FOR_ROLE["BODY_SELLING_POINT"])
        self.assertIn(o.zone, art.FALLBACK_CHAIN_FOR_ROLE["BODY_SELLING_POINT"])

    def test_the_body_keeps_one_anchor_across_events(self) -> None:
        events = [event("E1", "BODY_SELLING_POINT", ("ONE",), ()),
                  event("E2", "BODY_SELLING_POINT", ("TWO",), ()),
                  event("E3", "BODY_SELLING_POINT", ("THREE",), ())]
        self.assertEqual(len({o.zone for o in tr.render_events(events, profile=profile())}), 1)

    def test_a_fully_occluded_canvas_is_refused(self) -> None:
        everything = [art.EvidenceRegion("product", art.Rect(0.0, 0.0, 1.0, 1.0))]
        with self.assertRaises(art.TypographyArtDirectionError):
            tr.render_events([event()], profile=profile(), evidence=everything)


# ------------------------------------------------------------------ ffmpeg chain


@unittest.skipUnless(example_profile_font_available(), FONT_REQUIREMENT)
class CompositeChainTests(unittest.TestCase):
    def test_the_chain_fades_settles_and_uses_integer_frame_windows(self) -> None:
        overlays = tr.render_events([event()], profile=profile())
        chain, last = tr.ffmpeg_composite_chain(overlays, start_frame=[0], end_frame=[45])
        self.assertIn("fade=t=in", chain)
        self.assertIn("fade=t=out", chain)
        self.assertIn("between(n,0,44)", chain, "the window must be integer frame indices")
        self.assertIn("t-", chain, "the settle must be driven by time")
        self.assertEqual(last, "v0")

    def test_an_empty_window_is_refused(self) -> None:
        overlays = tr.render_events([event()], profile=profile())
        with self.assertRaises(tr.TypographyRenderError):
            tr.ffmpeg_composite_chain(overlays, start_frame=[10], end_frame=[10])

    def test_missing_windows_are_refused(self) -> None:
        overlays = tr.render_events([event()], profile=profile())
        with self.assertRaises(tr.TypographyRenderError):
            tr.ffmpeg_composite_chain(overlays)


# ------------------------------------------------------------------ executor


@unittest.skipUnless(media_probe.have_tools(), "ffmpeg and ffprobe are required")
@unittest.skipUnless(example_profile_font_available(), FONT_REQUIREMENT)
class ExecutorIntegrationTests(unittest.TestCase):
    """The production boundary must actually call the renderer."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = Path(tempfile.mkdtemp(prefix="av1-executor-"))
        cls.job = cls._tmp / "job"
        (cls.job / "picture").mkdir(parents=True)
        (cls.job / "typography").mkdir(parents=True)
        (cls.job / "examples" / "typography").mkdir(parents=True)
        shutil.copy2(PROFILE, cls.job / "examples" / "typography" / PROFILE.name)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", "color=c=0x6E7276:size=1080x1920:rate=30:duration=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
             str(cls.job / "picture" / "picture_master.mp4")], check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def request(self, **overrides) -> dict:
        payload = {
            "schema_version": "typography_request.v1", "job_id": "av1-executor",
            "master": "picture/picture_master.mp4", "out": "typography/typography_master.mp4",
            "width": 1080, "height": 1920, "fps": 30, "frame_count": 90,
            "font_stack": ["/System/Library/Fonts/Avenir Next Condensed.ttc"],
            "art_direction": {"profile": "examples/typography/art-direction-a-v1.profile.json"},
            "events": [{"event_id": "E01", "narrative_role": "HOOK",
                        "lines": ["KOTORAN KULIT", "TERANGKAT"],
                        "emphasis_terms": ["TERANGKAT"],
                        "start_frame": 0, "end_frame_exclusive": 90}],
        }
        payload.update(overrides)
        return payload

    def write(self, payload: dict) -> Path:
        target = self.job / "typography" / "typography_request.json"
        target.write_text(json.dumps(payload), encoding="utf-8")
        return target

    def frame(self, path: Path, index: int) -> np.ndarray:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{index})",
             "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
            capture_output=True).stdout
        return np.frombuffer(raw[:1080 * 1920 * 3], dtype=np.uint8).reshape(
            1920, 1080, 3).astype(int)

    def test_the_executor_renders_a_v1_and_says_so(self) -> None:
        out = self.job / "typography" / "typography_master.mp4"
        out.unlink(missing_ok=True)
        self.write(self.request())
        result = execution_adapters.execute_typography(self.job)

        self.assertEqual(result["art_direction"], profile().profile_id)
        self.assertEqual(result["art_direction_rules"], "LOCKED")
        self.assertEqual(result["reference_pixel_reproduction"], "UNRESOLVED")
        self.assertEqual(result["events_rendered"], 1)
        self.assertTrue(result["measured"])

    def test_the_rendered_frames_really_carry_the_design(self) -> None:
        """Not just 'it returned success' — the pixels must show emphasis and the rule."""

        out = self.job / "typography" / "typography_master.mp4"
        out.unlink(missing_ok=True)
        self.write(self.request())
        execution_adapters.execute_typography(self.job)

        p = profile()
        settled = self.frame(out, 30)
        master = self.frame(self.job / "picture" / "picture_master.mp4", 30)
        changed = np.abs(settled - master).sum(axis=2) > 40
        self.assertGreater(changed.sum(), 500, "the executor composited no typography")

        accent = np.array(p.accent[:3])
        self.assertTrue(((np.abs(settled - accent).sum(axis=2) < 40) & changed).sum() > 100,
                        "no warm-gold emphasis reached the encoded frames")

    def test_the_settle_is_visible_between_the_first_and_settled_frame(self) -> None:
        """The settle, isolated from the fade.

        In the locked profile the fade (160 ms) and the settle (220 ms) overlap almost
        entirely, so an early frame is BOTH dimmer and lower and a bounding-box comparison
        cannot tell which effect it is measuring. The fixture therefore zeroes the fade so
        the block is fully opaque immediately, leaving the settle as the only variable.
        """

        fixture = json.loads(PROFILE.read_text(encoding="utf-8"))
        for role in fixture["motion"]["fade_in_ms"]:
            fixture["motion"]["fade_in_ms"][role] = 0
        (self.job / "examples" / "typography" / "fixture.json").write_text(
            json.dumps(fixture), encoding="utf-8")

        out = self.job / "typography" / "typography_master.mp4"
        out.unlink(missing_ok=True)
        self.write(self.request(art_direction={
            "profile": "examples/typography/fixture.json"}))
        execution_adapters.execute_typography(self.job)

        def top_of_text(index: int) -> int:
            frame = self.frame(out, index)
            master = self.frame(self.job / "picture" / "picture_master.mp4", index)
            rows = np.nonzero((np.abs(frame - master).sum(axis=2) > 60).any(axis=1))[0]
            return int(rows.min()) if len(rows) else -1

        first, settled = top_of_text(1), top_of_text(30)
        self.assertGreater(first, 0, "the block was not visible at all on the first frame")
        self.assertGreater(settled, 0, "the block was not visible when settled")
        self.assertGreater(first, settled, "the block did not settle upward")

    def test_a_request_without_art_direction_keeps_the_original_behaviour(self) -> None:
        """Additive change: an existing job must render exactly as it did before."""

        out = self.job / "typography" / "typography_master.mp4"
        out.unlink(missing_ok=True)
        self.write({
            "schema_version": "typography_request.v1", "job_id": "legacy",
            "master": "picture/picture_master.mp4", "out": "typography/typography_master.mp4",
            "width": 1080, "height": 1920, "fps": 30, "frame_count": 90,
            "font_stack": ["/System/Library/Fonts/Avenir Next Condensed.ttc"],
            "layout": {"baseline_y": 300, "left_margin": 60, "size_l1": 62, "size_l2": 72,
                       "fill": [255, 255, 255, 255]},
            "events": [{"lines": ["LEGACY TITLE"], "start_frame": 0,
                        "end_frame_exclusive": 90}],
        })
        result = execution_adapters.execute_typography(self.job)
        self.assertNotIn("art_direction", result)
        self.assertEqual(result["events_rendered"], 1)

    def test_a_profile_at_the_wrong_canvas_size_is_refused(self) -> None:
        self.write(self.request(width=540, height=960))
        with self.assertRaises(execution_adapters.ExecutionAdapterError):
            execution_adapters.execute_typography(self.job)

    def test_an_event_without_a_role_is_refused_with_a_reason(self) -> None:
        self.write(self.request(events=[{"event_id": "E", "lines": ["A"],
                                         "start_frame": 0, "end_frame_exclusive": 45}]))
        with self.assertRaises(execution_adapters.ExecutionAdapterError) as caught:
            execution_adapters.execute_typography(self.job)
        self.assertIn("narrative_role", str(caught.exception))

    def test_a_missing_profile_is_refused(self) -> None:
        self.write(self.request(art_direction={"profile": "nope/missing.json"}))
        with self.assertRaises(tr.TypographyRenderError):
            execution_adapters.execute_typography(self.job)


if __name__ == "__main__":
    unittest.main()
