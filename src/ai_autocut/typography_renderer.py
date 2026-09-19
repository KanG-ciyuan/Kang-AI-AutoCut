"""The Typography Art Direction A v1 renderer.

The production executor could set one colour and one size for a whole event, place it at a
fixed position, and nothing else. Against the locked A v1 design that is a downgrade, not a
rendering: no warm-gold emphasis, no stroke, no shadow, no accent rule, no motion, and no
placement adaptation at all. Recorded honestly in the policy as
``Renderer = NOT_IMPLEMENTED``.

This module renders A v1, and it does so from the job's art-direction profile and the
project's existing zone rules. It contains no Variant 01 coordinates, no Variant 01 sizes and
no Variant 01 copy: every visual value comes from the profile, and every position comes from
``typography_art_direction``. A second SKU with different words, a different role mix and a
different profile renders correctly through the same code.

The design rules it implements
------------------------------
  * a warm-white body with a low-saturation warm-gold emphasis
  * hierarchy from size, weight and that one accent colour — never a second colour
  * readability from a light stroke and a soft shadow, never a dark plate
  * one short gold accent rule above the block: left-aligned with left text, centred with
    centred text
  * a short fade with a small upward settle, serving reading only
  * text placed inside a named zone from the closed zone set, never at free coordinates

What it deliberately does NOT do
--------------------------------
It does not decide placement from the picture. Zones are chosen by
``typography_art_direction`` from whatever occlusion evidence the job supplies; with no
evidence the role's default zone is used. The module renders; it never looks at a frame to
decide where text should go.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import typography_art_direction as art

DEFAULT_PROFILE = Path("examples/typography/art-direction-a-v1.profile.json")


class TypographyRenderError(ValueError):
    """Raised when an event cannot be rendered inside the locked art direction."""


# --------------------------------------------------------------------------- profile


@dataclass(frozen=True)
class RenderProfile:
    """The renderable subset of an art-direction profile.

    Read from the job's profile file, never defaulted in code: a default font or colour here
    would be one SKU's art direction silently applied to another.
    """

    profile_id: str
    font_path: str
    font_index: int | None
    warm_white: tuple[int, int, int, int]
    accent: tuple[int, int, int, int]
    stroke: tuple[int, int, int, int]
    shadow: tuple[int, int, int, int]
    stroke_width: int
    shadow_offset: tuple[int, int]
    shadow_blur: float
    accent_rule_height: int
    accent_rule_radius: int
    accent_rule_width_left: int
    accent_rule_width_center: int
    role_base_sizes: Mapping[str, int]
    emphasis_scale_max: float
    line_gap: int
    letter_spacing: Mapping[str, float]
    fade_in_ms: Mapping[str, int]
    fade_out_ms: Mapping[str, int]
    settle_px: int
    settle_ms: Mapping[str, int]
    canvas_width: int
    canvas_height: int
    fps: int
    raw: Mapping[str, Any]

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "RenderProfile":
        try:
            font = document["font"]
            colours = document["colours"]
            devices = document["readability_devices"]
            motion = document["motion"]
            scale = document["type_scale"]
            canvas = document["canvas"]
            rule = devices["accent_rule"]
        except KeyError as exc:
            raise TypographyRenderError(
                f"the art-direction profile does not state {exc}; a renderer must not "
                "invent a font, a colour or a motion") from exc

        stack = font.get("font_stack") or []
        if not stack:
            raise TypographyRenderError("the profile states no font_stack")

        def colour(key: str, source: Mapping[str, Any]) -> tuple[int, int, int, int]:
            value = source.get(key)
            if not isinstance(value, (list, tuple)) or len(value) not in (3, 4):
                raise TypographyRenderError(f"profile colour {key!r} is malformed")
            parts = [int(c) for c in value]
            return tuple(parts + ([255] if len(parts) == 3 else []))  # type: ignore[return-value]

        return cls(
            profile_id=str(document.get("profile_id", "")),
            font_path=str(stack[0]),
            font_index=(None if font.get("font_index") is None else int(font["font_index"])),
            warm_white=colour("warm_white", colours),
            accent=colour("accent", colours),
            stroke=colour("stroke", colours),
            shadow=colour("shadow", colours),
            stroke_width=int(devices.get("stroke_width_px", 0)),
            shadow_offset=tuple(int(v) for v in devices.get("shadow_offset_px", (0, 0))),  # type: ignore[arg-type]
            shadow_blur=float(devices.get("shadow_blur_px", 0.0)),
            accent_rule_height=int(rule.get("height_px", 5)),
            accent_rule_radius=int(rule.get("radius_px", 2)),
            accent_rule_width_left=int(rule.get("width_px_left", 74)),
            accent_rule_width_center=int(rule.get("width_px_center", 160)),
            role_base_sizes={str(k): int(v)
                             for k, v in (scale.get("role_base_sizes_px") or {}).items()},
            emphasis_scale_max=float((scale.get("emphasis_scale") or {}).get("max", 1.0)),
            line_gap=int(scale.get("line_gap_px", 5)),
            letter_spacing={str(k): float(v)
                            for k, v in (scale.get("letter_spacing_em") or {}).items()},
            fade_in_ms={str(k): int(v)
                        for k, v in (motion.get("fade_in_ms") or {}).items()},
            fade_out_ms={str(k): int(v)
                         for k, v in (motion.get("fade_out_ms") or {}).items()},
            settle_px=int(motion.get("settle_px", 0)),
            settle_ms={str(k): int(v) for k, v in (motion.get("settle_ms") or {}).items()},
            canvas_width=int(canvas["width"]),
            canvas_height=int(canvas["height"]),
            fps=int(canvas.get("fps", 30)),
            raw=dict(document),
        )

    @classmethod
    def load(cls, path: Path | str) -> "RenderProfile":
        target = Path(path)
        if not target.is_file():
            raise TypographyRenderError(f"art-direction profile does not exist: {target}")
        try:
            return cls.from_document(json.loads(target.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            raise TypographyRenderError(f"cannot read profile {target}: {exc}") from exc

    def base_size(self, role: str) -> int:
        if role not in self.role_base_sizes:
            raise TypographyRenderError(
                f"the profile does not state a base size for role {role!r}; a renderer must "
                "not guess one")
        return int(self.role_base_sizes[role])


# --------------------------------------------------------------------------- runs


@dataclass(frozen=True)
class Run:
    """A stretch of one line sharing one colour."""

    text: str
    emphasised: bool


def split_runs(text: str, emphasis_terms: Sequence[str]) -> tuple[Run, ...]:
    """Split a line into alternating plain and emphasised runs.

    Emphasis is carried by the event, not decided here. The split is by whole-word match so
    a term never lands mid-word, and it is case-insensitive because the design renders upper
    case while the approved copy is mixed case.
    """

    terms = [t.strip().lower() for t in emphasis_terms if t and t.strip()]
    if not terms:
        return (Run(text, False),)

    words = text.split(" ")
    lowered = [w.lower().strip(",.") for w in words]
    flags: list[bool] = [False] * len(words)
    for term in terms:
        term_words = term.split()
        span = len(term_words)
        for start in range(len(words) - span + 1):
            if lowered[start:start + span] == term_words:
                for offset in range(span):
                    flags[start + offset] = True

    runs: list[Run] = []
    for word, emphasised in zip(words, flags):
        if runs and runs[-1].emphasised == emphasised:
            runs[-1] = Run(f"{runs[-1].text} {word}", emphasised)
        else:
            runs.append(Run(word, emphasised))
    return tuple(runs)


def line_text(line: Sequence[Run]) -> str:
    """The line exactly as it is drawn: runs separated by single spaces."""

    return " ".join(run.text for run in line)


def measured_width(draw, line: Sequence[Run], face, stroke_width: int) -> int:
    """Width of a drawn line, measured the way it is drawn.

    Measuring ``"".join(...)`` would drop the spaces BETWEEN runs and under-report the width,
    which lets a line the fit check believes is fine overflow the zone it was fitted to.
    """

    box = draw.textbbox((0, 0), line_text(line), font=face, stroke_width=stroke_width)
    return box[2] - box[0]


def line_is_wholly_emphasised(runs: Sequence[Run]) -> bool:
    """True when every word in the line is emphasised.

    The design gives such a line a larger size; a partly-emphasised line keeps the body size
    and carries the emphasis in colour alone. That is the reference's own behaviour and it
    generalises without knowing any particular line.
    """

    return bool(runs) and all(run.emphasised for run in runs)


# --------------------------------------------------------------------------- motion


@dataclass(frozen=True)
class MotionSpec:
    fade_in_seconds: float
    fade_out_seconds: float
    settle_pixels: int
    settle_seconds: float


def motion_for(role: str, profile: RenderProfile) -> MotionSpec:
    return MotionSpec(
        fade_in_seconds=float(profile.fade_in_ms.get(role, 0)) / 1000.0,
        fade_out_seconds=float(profile.fade_out_ms.get(role, 0)) / 1000.0,
        settle_pixels=int(profile.settle_px),
        settle_seconds=float(profile.settle_ms.get(role, 0)) / 1000.0,
    )


# --------------------------------------------------------------------------- render


@dataclass(frozen=True)
class RenderedOverlay:
    """One event's rendered block, and where it settles."""

    event_id: str
    image: Any                     # PIL.Image, RGBA
    left: int
    top: int
    zone: str
    lines: tuple[str, ...]
    emphasised: tuple[str, ...]
    motion: MotionSpec

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size


def _font(profile: RenderProfile, size: int):
    from PIL import ImageFont

    try:
        return (ImageFont.truetype(profile.font_path, size=size, index=profile.font_index)
                if profile.font_index is not None
                else ImageFont.truetype(profile.font_path, size=size))
    except OSError as exc:
        raise TypographyRenderError(
            f"cannot load the profile's font {profile.font_path!r}: {exc}") from exc


def _fit_size(profile: RenderProfile, lines: Sequence[Sequence[Run]], target: int,
              usable_width: int, draw) -> int:
    """Largest size at or below the target whose longest line fits the zone.

    Size adaptation to text length is what the design does — the reference's longer lines are
    set smaller than its shorter ones — so it is a rule here rather than a table of sizes.
    """

    size = int(target)
    while size > 8:
        face = _font(profile, size)
        widest = max((measured_width(draw, line, face, profile.stroke_width)
                      for line in lines), default=0)
        if widest <= usable_width:
            return size
        size -= 1
    raise TypographyRenderError(
        f"no size at or below {target}px fits {usable_width}px; the text is too long for "
        "its zone and the art direction does not permit overflowing it")


def render_event(
    *,
    event: art.TypographyEvent,
    profile: RenderProfile,
    zone: art.Zone,
    text_top: int | None = None,
) -> RenderedOverlay:
    """Render one A v1 event into a cropped RGBA overlay plus its settle position.

    ``text_top`` overrides where the text block's top lands; the default is the zone's own
    top plus the accent rule and its breathing space.
    """

    from PIL import Image, ImageDraw, ImageFilter

    if not event.text_lines:
        raise TypographyRenderError(f"{event.event_id} has no lines to render")

    canvas_w = profile.canvas_width
    rect = zone.rect
    left = int(round(rect.x * canvas_w))
    usable_width = int(round(rect.width * canvas_w))

    runs_per_line = [split_runs(line, event.emphasis_terms) for line in event.text_lines]
    base = profile.base_size(event.narrative_role)
    emphasised_size = int(round(base * profile.emphasis_scale_max))

    # Work out each line's size first, then measure, so the block's height is known before
    # anything is drawn into it.
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    sizes: list[int] = []
    for line in runs_per_line:
        target = emphasised_size if line_is_wholly_emphasised(line) else base
        sizes.append(_fit_size(profile, [line], target, usable_width, probe))

    faces = [_font(profile, size) for size in sizes]
    sw = profile.stroke_width
    line_boxes = [
        probe.textbbox((0, 0), line_text(line), font=face, stroke_width=sw)
        for line, face in zip(runs_per_line, faces)
    ]
    line_heights = [box[3] - box[1] for box in line_boxes]
    gap = profile.line_gap
    block_height = sum(line_heights) + gap * (len(line_heights) - 1)

    rule_h = profile.accent_rule_height
    rule_pad = max(6, gap + 2)
    rule_w = (profile.accent_rule_width_center if zone.alignment == "center"
              else profile.accent_rule_width_left)

    pad = (profile.shadow_blur * 2 + abs(profile.shadow_offset[0]) + sw + 8)
    pad = int(pad) + 4
    image_w = min(usable_width + pad * 2 + rule_w, canvas_w)
    top = (text_top if text_top is not None
           else int(round(rect.y * profile.canvas_height)) + rule_h + rule_pad)
    offset_x = pad
    offset_y = pad

    content_h = rule_h + rule_pad + block_height
    image_h = content_h + pad * 2

    shadow = Image.new("RGBA", (image_w, image_h), (0, 0, 0, 0))
    body = Image.new("RGBA", (image_w, image_h), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    draw = ImageDraw.Draw(body)

    # The one accent rule. It sits above the block, aligned with the text: left with left
    # text, centred with centred text.
    rule_x = offset_x if zone.alignment == "left" else (
        offset_x + max(0, (usable_width - rule_w) // 2))
    draw.rounded_rectangle((rule_x, offset_y, rule_x + rule_w, offset_y + rule_h),
                           radius=profile.accent_rule_radius, fill=profile.accent)

    y = offset_y + rule_h + rule_pad
    for line, face, height, line_box in zip(runs_per_line, faces, line_heights, line_boxes):
        line_width = line_box[2] - line_box[0]
        x = offset_x if zone.alignment == "left" else (
            offset_x + max(0, (usable_width - line_width) // 2))

        # Shadow first, offset and blurred, so it never sits over the glyphs.
        sx = x + profile.shadow_offset[0]
        sy = y + (line_box[1] - line_box[1]) + profile.shadow_offset[1]
        cursor = sx
        for index, run in enumerate(line):
            shadow_draw.text((cursor, sy), run.text, font=face,
                             fill=profile.shadow, stroke_width=sw,
                             stroke_fill=profile.shadow)
            if index + 1 < len(line):
                cursor += draw.textlength(run.text + " ", font=face)

        cursor = x
        for index, run in enumerate(line):
            draw.text((cursor, y), run.text, font=face,
                      fill=(profile.accent if run.emphasised else profile.warm_white),
                      stroke_width=sw, stroke_fill=profile.stroke)
            if index + 1 < len(line):
                cursor += draw.textlength(run.text + " ", font=face)

        y += height + gap

    if profile.shadow_blur > 0:
        shadow = shadow.filter(ImageFilter.GaussianBlur(profile.shadow_blur))
    composed = Image.alpha_composite(shadow, body)

    box = composed.getbbox()
    if box is None:
        raise TypographyRenderError(f"{event.event_id} rendered nothing")
    crop_left = max(0, box[0] - 2)
    crop_top = max(0, box[1] - 2)
    crop_right = min(image_w, box[2] + 3)
    crop_bottom = min(image_h, box[3] + 3)
    cropped = composed.crop((crop_left, crop_top, crop_right, crop_bottom))

    return RenderedOverlay(
        event_id=event.event_id, image=cropped,
        left=left + crop_left - offset_x,
        top=top + crop_top - offset_y,
        zone=event.zone_name,
        lines=tuple(event.text_lines),
        emphasised=tuple(event.emphasis_terms),
        motion=motion_for(event.narrative_role, profile),
    )


def render_events(
    events: Sequence[art.TypographyEvent],
    *,
    profile: RenderProfile,
    evidence: Sequence[art.EvidenceRegion] = (),
    platform: art.PlatformSafeZone | None = None,
) -> tuple[RenderedOverlay, ...]:
    """Plan the zones and render every event.

    Placement comes from ``typography_art_direction``: the role's default zone, a fallback
    only on a real conflict, and a refusal when no zone is free. This function never looks at
    a frame.
    """

    layout = art.plan_layout(events, evidence=evidence,
                             platform=platform or art.DEFAULT_PLATFORM_SAFE_ZONE)
    zones = art.ZONES
    return tuple(
        render_event(event=event, profile=profile, zone=zones[event.zone_name])
        for event in layout.events
    )


def ffmpeg_composite_chain(overlays: Sequence[RenderedOverlay], *, base: str = "0:v",
                           start_frame: Sequence[int] | None = None,
                           end_frame: Sequence[int] | None = None,
                           fps: int = 30) -> tuple[str, str]:
    """Build the ffmpeg filter chain that fades, settles and composites the overlays.

    Motion is expressed with ffmpeg's own ``fade`` (alpha) and an overlay ``y`` expression,
    so the picture is still encoded exactly once and no per-frame PNG set is produced.

    ``end_frame`` is exclusive, matching the ASS convention the rest of the project uses.
    """

    if start_frame is None or end_frame is None:
        raise TypographyRenderError("start_frame and end_frame are required")

    parts: list[str] = []
    current = base
    for index, (overlay, start, end) in enumerate(zip(overlays, start_frame, end_frame)):
        if end <= start:
            raise TypographyRenderError(f"{overlay.event_id} has an empty frame window")
        s = start / fps
        e = end / fps
        fin = max(0.0, overlay.motion.fade_in_seconds)
        fout = max(0.0, overlay.motion.fade_out_seconds)
        settle_s = max(0.0, overlay.motion.settle_seconds)
        settle_px = overlay.motion.settle_pixels

        chain = f"[{index + 1}:v]format=rgba"
        if fin > 0:
            chain += f",fade=t=in:st={s:.6f}:d={fin:.6f}:alpha=1"
        if fout > 0:
            chain += f",fade=t=out:st={max(s, e - fout):.6f}:d={fout:.6f}:alpha=1"
        chain += f"[o{index}]"

        if settle_px > 0 and settle_s > 0:
            y_expr = (f"{overlay.top}+{settle_px}*"
                      f"(1-min(1\\,max(0\\,(t-{s:.6f})/{settle_s:.6f})))")
        else:
            y_expr = str(overlay.top)

        label = f"v{index}"
        parts.append(chain)
        parts.append(
            f"[{current}][o{index}]overlay=x={overlay.left}:y='{y_expr}':"
            f"enable='between(n,{start},{end - 1})'[{label}]"
        )
        current = label
    return ";".join(parts), current


__all__ = [
    "DEFAULT_PROFILE",
    "MotionSpec",
    "RenderProfile",
    "RenderedOverlay",
    "Run",
    "TypographyRenderError",
    "ffmpeg_composite_chain",
    "line_is_wholly_emphasised",
    "motion_for",
    "render_event",
    "render_events",
    "split_runs",
]
