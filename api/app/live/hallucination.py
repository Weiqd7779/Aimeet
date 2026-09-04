"""Reject transcripts the STT model made up.

Whisper-family transcribers, given a vocabulary prompt and audio with no clear speech
(room noise, keyboard, someone far away), sometimes emit a fluent paragraph stitched from
the prompt words. Seen live: 234 characters of "我們討論了 Prototype A ... Redis cache layer
... BOM 成本上限 ... 握感 矽膠包覆 ... Q4" while nobody said any of it. Two independent
checks catch this:

1. Energy: the audio window of the utterance never reached speech level.
2. Vocabulary: the text is mostly the prompt's own terms (several distinct ones at once).
"""

import re
from collections import deque

import numpy as np

SPEECH_RMS = 300  # int16 RMS; quiet speech through AGC is > 800, room tone < 150
# A real sentence about the product legitimately uses 3-4 vocabulary words
# ("Prototype C 的滿意度中等，握感還沒解，兩週交樣品"); the fabricated paragraph used 8 in
# 234 characters. Only paragraph-length + term-dense text is treated as regurgitation.
MAX_PROMPT_TERMS = 6
LONG_UTTERANCE_CHARS = 100  # one VAD turn of real speech is far shorter than this
LONG_UTTERANCE_TERMS = 3
HISTORY_SECONDS = 120.0


def rms(pcm16: bytes) -> float:
    samples = np.frombuffer(pcm16, dtype="<i2")
    return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) if len(samples) else 0.0


class EnergyTrack:
    """Per-source RMS timeline so a finished utterance can be checked against its audio."""

    def __init__(self) -> None:
        self._points: deque[tuple[float, float]] = deque()

    def add(self, elapsed: float, level: float) -> None:
        self._points.append((elapsed, level))
        while self._points and elapsed - self._points[0][0] > HISTORY_SECONDS:
            self._points.popleft()

    def peak(self, start: float, end: float) -> float:
        window = [level for t, level in self._points if start - 0.3 <= t <= end + 0.3]
        return max(window, default=0.0)

    def had_speech(self, start: float, end: float) -> bool:
        return not self._points or self.peak(start, end) >= SPEECH_RMS


def prompt_terms(prompt: str) -> list[str]:
    """Vocabulary items listed in the transcription prompt after 「詞彙：」."""
    _, _, listing = prompt.partition("詞彙：")
    return [t.strip("。 ") for t in re.split(r"[、,]", listing) if len(t.strip("。 ")) >= 2]


def looks_like_prompt(text: str, terms: list[str]) -> bool:
    hits = {term for term in terms if term.lower() in text.lower()}
    return len(hits) >= MAX_PROMPT_TERMS or (
        len(text) > LONG_UTTERANCE_CHARS and len(hits) >= LONG_UTTERANCE_TERMS
    )
