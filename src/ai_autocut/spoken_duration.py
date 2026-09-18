"""Spoken duration validation: does this copy fit this window?

This runs **before** copy lock and **before** any paid voice generation, which is the
entire point. The First Job locked its closing copy, generated the voice, and only then
discovered that three lines needed more time than the frozen window had. The mismatch was
arithmetic and was detectable earlier for free.

Three rules the module is built around:

* **Cheap validation before expensive generation.** No network call, no TTS, no provider.
* **The validator may warn; it may not rewrite copy.** Nothing here mutates a string.
* **A speaking rate is measured, never assumed.** A rate carries where it came from and
  how much to trust it, and a rate measured on one job is an observation, not a constant.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

#: Risk bands. Thresholds on a ratio, chosen for the first version and to be re-derived
#: from recorded outcomes. They are not universal constants.
SAFE_MAX_RATIO = 0.85
TIGHT_MAX_RATIO = 1.00

RISKS = ("SAFE", "TIGHT", "OVERFLOW")

#: Where a speaking rate came from, best evidence first.
RATE_SOURCES = (
    "MEASURED_SAME_VOICE",
    "MEASURED_SAME_LANGUAGE",
    "LANGUAGE_DEFAULT",
    "FALLBACK_ESTIMATE",
)

#: How much to trust the rate.
CONFIDENCES = ("LOW", "MEDIUM", "HIGH")

#: Conservative language-level placeholders, used only when nothing has been measured.
#:
#: These are deliberately BELOW typical measured conversational rates, so the estimator
#: errs toward reporting a window as tight rather than falsely safe. They are placeholders
#: with no claim to being the true rate of any language: the first job that measures its
#: own voice replaces them for that language and voice.
LANGUAGE_DEFAULT_WORDS_PER_SECOND = {
    "id": 2.40,
    "en": 2.50,
    "zh": 3.60,
}

#: Used when the language is not in the table at all. Deliberately low and flagged LOW
#: confidence, because a wrong rate in this direction produces a warning rather than a
#: silent overflow discovered after paying for a voice.
GLOBAL_FALLBACK_WORDS_PER_SECOND = 2.20

#: Residual uncertainty applied to estimates that are not backed by a same-voice
#: measurement, as a multiplier on the estimated duration.
UNCERTAINTY_MARGIN = {
    "MEASURED_SAME_VOICE": 1.00,
    "MEASURED_SAME_LANGUAGE": 1.05,
    "LANGUAGE_DEFAULT": 1.12,
    "FALLBACK_ESTIMATE": 1.20,
}

_TERMINAL = re.compile(r"[.!?。！？]+")
_CLAUSE = re.compile(r"[,;:，；：、—–]+")
_WORD = re.compile(r"[^\s]+")


class SpokenDurationError(ValueError):
    """Raised when a duration cannot be validated safely."""


@dataclass(frozen=True)
class PauseModel:
    """How long the voice rests at punctuation.

    Named and explicit so an estimate is auditable. The defaults come from an observation
    that generated speech pauses for far longer than the prompt requested, so a model that
    assumes instructed pauses underestimates.
    """

    name: str = "punctuation-conservative-v1"
    clause_seconds: float = 0.28
    sentence_seconds: float = 0.45
    between_lines_seconds: float = 0.12

    def __post_init__(self) -> None:
        for label, value in (
            ("clause_seconds", self.clause_seconds),
            ("sentence_seconds", self.sentence_seconds),
            ("between_lines_seconds", self.between_lines_seconds),
        ):
            if value < 0:
                raise SpokenDurationError(f"{label} cannot be negative")


DEFAULT_PAUSE_MODEL = PauseModel()


@dataclass(frozen=True)
class SpeakingRate:
    """A measured or assumed speaking rate, with its provenance."""

    words_per_second: float
    language: str
    rate_source: str
    confidence: str
    voice: str | None = None
    evidence: str = ""

    def __post_init__(self) -> None:
        if self.words_per_second <= 0:
            raise SpokenDurationError("words_per_second must be positive")
        if self.rate_source not in RATE_SOURCES:
            raise SpokenDurationError(
                f"rate_source must be one of: {', '.join(RATE_SOURCES)}"
            )
        if self.confidence not in CONFIDENCES:
            raise SpokenDurationError(
                f"confidence must be one of: {', '.join(CONFIDENCES)}"
            )


@dataclass(frozen=True)
class RateObservation:
    """A rate somebody actually measured, offered as evidence to the resolver.

    Nothing in this module carries a built-in observation. A job supplies its own, so a
    number measured on one production can never silently become a default for another.
    """

    language: str
    words_per_second: float
    voice: str | None = None
    samples: int = 1
    evidence: str = ""

    def __post_init__(self) -> None:
        if self.words_per_second <= 0:
            raise SpokenDurationError("an observation must have a positive rate")
        if self.samples < 1:
            raise SpokenDurationError("an observation must come from at least one sample")


def resolve_rate(
    language: str,
    *,
    voice: str | None = None,
    observations: Sequence[RateObservation] = (),
) -> SpeakingRate:
    """Pick the best available rate, in order of evidence strength.

    1. a measured rate for the same language **and** voice
    2. a measured rate for the same language, pooled
    3. a conservative language-level placeholder
    4. a global placeholder, flagged as an estimate
    """

    code = (language or "").strip().lower()
    if not code:
        raise SpokenDurationError("language is required to resolve a speaking rate")

    same_voice = [
        o for o in observations
        if o.language.strip().lower() == code and voice is not None and o.voice == voice
    ]
    if same_voice:
        samples = sum(o.samples for o in same_voice)
        rate = sum(o.words_per_second * o.samples for o in same_voice) / samples
        return SpeakingRate(
            words_per_second=round(rate, 4), language=code, voice=voice,
            rate_source="MEASURED_SAME_VOICE",
            confidence="HIGH" if samples >= 3 else "MEDIUM",
            evidence=("; ".join(o.evidence for o in same_voice if o.evidence)
                      or f"pooled from {samples} measured sample(s)"),
        )

    same_language = [o for o in observations if o.language.strip().lower() == code]
    if same_language:
        samples = sum(o.samples for o in same_language)
        rate = sum(o.words_per_second * o.samples for o in same_language) / samples
        return SpeakingRate(
            words_per_second=round(rate, 4), language=code,
            rate_source="MEASURED_SAME_LANGUAGE",
            confidence="MEDIUM" if samples >= 2 else "LOW",
            evidence=("; ".join(o.evidence for o in same_language if o.evidence)
                      or f"pooled from {samples} measured sample(s) in this language"),
        )

    if code in LANGUAGE_DEFAULT_WORDS_PER_SECOND:
        return SpeakingRate(
            words_per_second=LANGUAGE_DEFAULT_WORDS_PER_SECOND[code], language=code,
            rate_source="LANGUAGE_DEFAULT", confidence="LOW",
            evidence="conservative language-level placeholder; no measurement available",
        )

    return SpeakingRate(
        words_per_second=GLOBAL_FALLBACK_WORDS_PER_SECOND, language=code,
        rate_source="FALLBACK_ESTIMATE", confidence="LOW",
        evidence="no measurement and no language default; global placeholder",
    )


@dataclass(frozen=True)
class LineEstimate:
    """One copy line's estimated spoken duration."""

    line_id: str
    words: int
    speech_seconds: float
    pause_seconds: float
    estimated_seconds: float


@dataclass(frozen=True)
class WindowCheck:
    """The verdict for one window."""

    available_window: float
    estimated_spoken_duration: float
    ratio: float
    risk: str
    recommended_action: str
    rate_source: str
    pause_model: str
    confidence: str
    uncertainty_margin: float
    lines: tuple[LineEstimate, ...]
    note: str = ""

    def __post_init__(self) -> None:
        if self.risk not in RISKS:
            raise SpokenDurationError(f"risk must be one of: {', '.join(RISKS)}")


def count_words(text: str) -> int:
    return len(_WORD.findall(text.strip()))


def estimate_line(
    text: str, *, line_id: str, rate: SpeakingRate,
    pause_model: PauseModel = DEFAULT_PAUSE_MODEL,
) -> LineEstimate:
    """Estimate one line. The text is read, never modified."""

    if not isinstance(text, str) or not text.strip():
        raise SpokenDurationError("a copy line must be non-empty text")
    words = count_words(text)
    speech = words / rate.words_per_second
    sentences = max(1, len([s for s in _TERMINAL.split(text) if s.strip()]))
    clauses = len(_CLAUSE.findall(text))
    pauses = clauses * pause_model.clause_seconds
    pauses += max(0, sentences - 1) * pause_model.sentence_seconds
    return LineEstimate(
        line_id=line_id, words=words,
        speech_seconds=round(speech, 4), pause_seconds=round(pauses, 4),
        estimated_seconds=round(speech + pauses, 4),
    )


def recommended_action_for(risk: str) -> str:
    """The action to recommend, in the order the specification sets out."""

    if risk == "SAFE":
        return "no timing action needed; proceed toward copy lock"
    if risk == "TIGHT":
        return ("consider a light pacing adjustment or a small window change before "
                "lock; the copy may fit as written")
    return ("adjust the copy before lock if it is not yet locked; if it is locked, "
            "revisit the available window where that is commercially valid, otherwise "
            "make a deliberate recorded pacing decision")


def check_window(
    lines: Sequence[tuple[str, str]],
    *,
    available_window: float,
    rate: SpeakingRate,
    pause_model: PauseModel = DEFAULT_PAUSE_MODEL,
    required: bool = True,
) -> WindowCheck:
    """Compare the copy against the window it must fit.

    ``lines`` is a sequence of ``(line_id, text)``. The texts are never altered.
    """

    if available_window <= 0:
        raise SpokenDurationError("available_window must be positive")

    estimates = tuple(
        estimate_line(text, line_id=line_id, rate=rate, pause_model=pause_model)
        for line_id, text in lines
    )

    if not estimates:
        if required:
            raise SpokenDurationError(
                "a required window must carry at least one copy line"
            )
        return WindowCheck(
            available_window=round(available_window, 4),
            estimated_spoken_duration=0.0, ratio=0.0, risk="SAFE",
            recommended_action="no copy is required in this window; leave it empty",
            rate_source=rate.rate_source, pause_model=pause_model.name,
            confidence=rate.confidence,
            uncertainty_margin=UNCERTAINTY_MARGIN[rate.rate_source],
            lines=(), note="window deliberately carries no line",
        )

    speech_and_pauses = sum(e.estimated_seconds for e in estimates)
    gaps = max(0, len(estimates) - 1) * pause_model.between_lines_seconds
    raw = speech_and_pauses + gaps
    margin = UNCERTAINTY_MARGIN[rate.rate_source]
    estimated = raw * margin
    ratio = estimated / available_window

    if ratio <= SAFE_MAX_RATIO:
        risk = "SAFE"
    elif ratio <= TIGHT_MAX_RATIO:
        risk = "TIGHT"
    else:
        risk = "OVERFLOW"

    note = ""
    if margin > 1.0:
        note = (f"estimate widened by {margin:.2f}x because the rate is "
                f"{rate.rate_source} ({rate.confidence} confidence)")

    return WindowCheck(
        available_window=round(available_window, 4),
        estimated_spoken_duration=round(estimated, 4),
        ratio=round(ratio, 4), risk=risk,
        recommended_action=recommended_action_for(risk),
        rate_source=rate.rate_source, pause_model=pause_model.name,
        confidence=rate.confidence, uncertainty_margin=margin,
        lines=estimates, note=note,
    )


def fits(check: WindowCheck) -> bool:
    """Convenience predicate. ``TIGHT`` still fits; only ``OVERFLOW`` does not."""

    return check.risk != "OVERFLOW"
