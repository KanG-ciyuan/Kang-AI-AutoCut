"""Small, deterministic spoken-caption layer; alignment is a producer input.

No ASR, copy generation, semantic model, provider call or title planning lives here.
Times are seconds on the FINAL VO timeline, including any leading offset.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Callable, Mapping, Sequence

from PIL import Image, ImageDraw


class CaptionError(ValueError):
    pass


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Phrase:
    words: tuple[Word, ...]
    lines: tuple[tuple[int, ...], ...]

    def active_word(self, seconds: float) -> int | None:
        return next((i for i, w in enumerate(self.words)
                     if w.start <= seconds < w.end), None)


@dataclass(frozen=True)
class CaptionPlan:
    phrases: tuple[Phrase, ...]
    width: int
    height: int
    size: int
    stroke: int
    shadow: int
    rect: tuple[int, int, int, int]  # left, top, right, bottom
    line_height: int


def _normal(text: str) -> str:
    # ASR punctuation/case may differ; display ALWAYS uses approved tokens.
    return ''.join(c for c in text.casefold() if c.isalnum())


def compile_captions(copy: str, timings: Sequence[Mapping], *, duration: float,
                     width: int, height: int, font_loader: Callable,
                     phrase_ends: Sequence[int] = (),
                     safe_area: Sequence[float] = (.08, .08, .16, .16),
                     reserved: Sequence[Sequence[float]] = ()) -> CaptionPlan:
    """Compile actual word timings into short phrases.

    phrase_ends: optional complete semantic grouping, exclusive word indices;
    when supplied it wins over pause/word-count heuristics (up to 8 words if fit).
    safe_area: fractional left/top/right/bottom margins.
    reserved: pixel rectangles (left, top, right, bottom) for titles/evidence.
    Conservative collision checks apply for the whole timeline.
    """
    if not copy.strip() or any(ord(c) < 32 and c not in '\n\t\r' for c in copy):
        raise CaptionError('approved copy is empty or contains control characters')
    tokens = copy.split()
    if len(tokens) != len(timings):
        raise CaptionError('one measured timing per approved word is required')
    if not math.isfinite(duration) or duration <= 0 or min(width, height) < 64:
        raise CaptionError('invalid duration or canvas')
    words = []
    previous = 0.0
    for token, entry in zip(tokens, timings):
        start, end = float(entry['start']), float(entry['end'])
        if not _normal(token) or _normal(token) != _normal(str(entry['text'])):
            raise CaptionError('timing text does not match approved copy')
        if not (math.isfinite(start) and math.isfinite(end) and
                previous <= start < end <= duration):
            raise CaptionError('word timings must be finite, ordered, non-overlapping and in range')
        words.append(Word(token, start, end))
        previous = end
    if len(safe_area) != 4 or any(not math.isfinite(v) or not 0 <= v < 1 for v in safe_area):
        raise CaptionError('invalid safe area')
    left, top, right, bottom = safe_area
    size = max(8, round(min(width * .075, height * .045)))
    stroke, shadow = max(1, round(size * .07)), max(1, round(size * .025))
    font = font_loader(size)
    if not any(k in font.getname()[1].lower() for k in ('bold', 'heavy', 'black', 'demi')):
        raise CaptionError('spoken captions require a bold font in font_stack')
    draw = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    ascent, descent = font.getmetrics()
    line_height = ascent + descent + stroke * 2 + shadow
    x1, x2 = math.ceil(width * left), math.floor(width * (1 - right))
    y2 = math.floor(height * min(.84, 1 - bottom))
    y1 = y2 - line_height * 2
    if x2 <= x1 or y1 < max(height * top, height * .50):
        raise CaptionError('caption block cannot fit safe lower half')
    rect = (x1, y1, x2, y2)
    for region in reserved:
        if len(region) != 4 or not all(math.isfinite(v) for v in region):
            raise CaptionError('invalid reserved rectangle')
        a, b, c, d = region
        if a < x2 and c > x1 and b < y2 and d > y1:
            raise CaptionError('spoken caption overlaps a title/evidence region')

    def line_width(part):
        box = draw.textbbox((0, 0), ' '.join(w.text for w in part), font=font,
                            stroke_width=stroke)
        return max(box[2] - box[0], draw.textlength(' '.join(w.text for w in part), font=font)) + shadow + 2 * stroke

    def wrap(part):
        if line_width(part) <= x2 - x1:
            return (tuple(range(len(part))),)
        choices = [(max(line_width(part[:i]), line_width(part[i:])), i)
                   for i in range(1, len(part))]
        if not choices or min(choices)[0] > x2 - x1:
            return None
        _, split = min(choices)
        return (tuple(range(split)), tuple(range(split, len(part))))

    groups = []
    if phrase_ends:
        ends = list(phrase_ends)
        if any(type(i) is not int for i in ends) or ends != sorted(set(ends)) or ends[-1] != len(words) or ends[0] <= 0:
            raise CaptionError('phrase_ends must be increasing and cover every word')
        begin = 0
        for end in ends:
            part = words[begin:end]
            lines = wrap(part)
            if len(part) > 8 or lines is None:
                raise CaptionError('semantic phrase is too long; producer must regroup it')
            groups.append(Phrase(tuple(part), lines))
            begin = end
    else:
        # Punctuation and real pauses define runs first. Within a run, balanced
        # short units avoid a fixed five-word chop and a one-word trailing unit.
        ends = [i + 1 for i, w in enumerate(words)
                if i == len(words) - 1 or re.search(r'[.!?;,:…]$', w.text)
                or words[i + 1].start - w.end >= .28]
        begin = 0
        for end in ends:
            while begin < end:
                remaining = end - begin
                count = min(5, remaining)
                if remaining == 6:
                    count = 3
                elif remaining == 7:
                    count = 4
                while count and wrap(words[begin:begin + count]) is None:
                    count -= 1
                if not count:
                    raise CaptionError('word cannot fit mobile caption area')
                part = words[begin:begin + count]
                groups.append(Phrase(tuple(part), wrap(part)))
                begin += count
    return CaptionPlan(tuple(groups), width, height, size, stroke, shadow, rect, line_height)


def render_states(plan: CaptionPlan, font_loader: Callable):
    """Yield (RGBA, start, end, active-index) with exclusive ends.

    Every state contains the same complete phrase at the same coordinates. Gaps
    within a phrase show base text only; silence between phrases shows no text.
    """
    font = font_loader(plan.size)
    for phrase in plan.phrases:
        boundaries = sorted({t for w in phrase.words for t in (w.start, w.end)})
        for start, end in zip(boundaries, boundaries[1:]):
            active = phrase.active_word((start + end) / 2)
            image = Image.new('RGBA', (plan.width, plan.height))
            draw = ImageDraw.Draw(image)
            x1, y1, x2, y2 = plan.rect
            y = y2 - len(phrase.lines) * plan.line_height + plan.stroke
            for indices in phrase.lines:
                text = ' '.join(phrase.words[i].text for i in indices)
                x = (x1 + x2 - draw.textlength(text, font=font)) / 2
                draw.text((x + plan.shadow, y + plan.shadow), text, font=font,
                          fill=(0, 0, 0, 150), stroke_width=plan.stroke,
                          stroke_fill=(0, 0, 0, 150), anchor='la')
                draw.text((x, y), text, font=font, fill='#FFFFFF',
                          stroke_width=plan.stroke, stroke_fill='#151515', anchor='la')
                if active in indices:
                    prefix = ' '.join(phrase.words[i].text for i in indices if i < active)
                    offset = draw.textlength(prefix + ' ', font=font) if prefix else 0
                    draw.text((x + offset, y), phrase.words[active].text, font=font,
                              fill='#FFD966', anchor='la')
                y += plan.line_height
            yield image, start, end, active
