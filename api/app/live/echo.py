"""Cross-channel echo suppression.

With speakers instead of headphones, the remote participant's voice comes out of the
host's speakers and back into the host microphone, so the `me` channel transcribes the
remote person's words a second time. The tab audio never contains the host's voice, so
the check is one-directional: a `me` utterance that closely matches a `remote` utterance
starting around the same time is treated as echo and dropped before it reaches the
transcript or the reasoning model.
"""

import re
from collections import deque

from rapidfuzz import fuzz

HOLD_SECONDS = 1.5  # how long a `me` utterance waits for its remote twin before commit
MAX_HOLD_SECONDS = 8.0  # ...extended while the remote channel is still mid-sentence
WINDOW_SECONDS = 4.0  # max |speech-start difference| between the two channels
SIMILARITY = 80  # 0-100
MIN_CHARS = 3  # "好", "對" etc. legitimately overlap; never treat them as echo

_STRIP = re.compile(r"[\s,.!?;:，。！？；：、「」『』（）()\-—…]+")


def normalize(text: str) -> str:
    return _STRIP.sub("", text).lower()


def similar(me_text: str, remote_text: str) -> bool:
    me, remote = normalize(me_text), normalize(remote_text)
    if len(me) < MIN_CHARS or not remote:
        return False
    # The mic usually catches a fragment of the remote sentence, so allow containment.
    return fuzz.ratio(me, remote) >= SIMILARITY or (
        len(me) <= len(remote) and fuzz.partial_ratio(me, remote) >= SIMILARITY + 10
    )


class EchoFilter:
    def __init__(self, window_s: float = WINDOW_SECONDS, keep: int = 32) -> None:
        self.window_s = window_s
        self._remote: deque[tuple[float, str]] = deque(maxlen=keep)

    def note_remote(self, ts: float, text: str) -> None:
        self._remote.append((ts, text))

    def is_echo(self, ts: float, text: str) -> bool:
        return any(
            abs(ts - remote_ts) <= self.window_s and similar(text, remote_text)
            for remote_ts, remote_text in self._remote
        )
