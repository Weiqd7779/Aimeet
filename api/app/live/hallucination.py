"""What the STT model made up, and what we do about it.

History, because every rule here was added after a live failure and most were later wrong:

- 2026-09-04: with a vocabulary list *inside* the transcription prompt, gpt-4o-mini-transcribe
  emitted a 234-character paragraph stitched from those terms while nobody spoke. We added
  an energy gate and a term-density gate.
- 2026-09-05: the prompt gained an example sentence; the model transcribed that sentence
  verbatim five times. Then, with the example removed but the term list still there, it
  emitted the term list as a question. Meanwhile the energy gate rejected real short
  sentences (「還沒喔」「好的好的」) because of a clock-window bug.

The fix was never a better filter: it was following the API docs. `prompt` describes the
recording setting and nothing else; no example speech, no instructions, no vocabulary.
With nothing in the prompt to regurgitate, the gates only hurt, so they are gone.

What remains:
- `looks_like_prompt`: refuse an utterance that *is* the prompt sentence. Zero false
  positives (nobody says the prompt out loud), keeps the one known leak shape impossible.
- `EnergyTrack`: mic level per utterance, stored as `peak_rms` on the record for diagnosis.
  It never decides anything.
"""

import re
from collections import deque

import numpy as np

HISTORY_SECONDS = 120.0


def rms(pcm16: bytes) -> float:
    samples = np.frombuffer(pcm16, dtype="<i2")
    return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) if len(samples) else 0.0


class EnergyTrack:
    """Per-source RMS timeline so an utterance can be annotated with how loud the mic was."""

    def __init__(self) -> None:
        self._points: deque[tuple[float, float]] = deque()

    def add(self, elapsed: float, level: float) -> None:
        self._points.append((elapsed, level))
        while self._points and elapsed - self._points[0][0] > HISTORY_SECONDS:
            self._points.popleft()

    def peak(self, start: float, end: float) -> float | None:
        """Loudest level in [start, end] (±0.3 s); None when the window holds no samples,
        which means our clock and the transcriber's disagree - not that it was silent."""
        window = [level for t, level in self._points if start - 0.3 <= t <= end + 0.3]
        return max(window) if window else None


MIN_VERBATIM_CHARS = 6
_PUNCT = re.compile(r"[\s，。、,.!?！？:：「」()（）]")


def _bare(text: str) -> str:
    return _PUNCT.sub("", text).lower()


def looks_like_prompt(text: str, prompt: str) -> bool:
    """True when the utterance is a verbatim fragment of the context prompt."""
    bare = _bare(text)
    return len(bare) >= MIN_VERBATIM_CHARS and bare in _bare(prompt)
