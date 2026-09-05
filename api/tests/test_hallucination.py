import numpy as np

from app.live.hallucination import EnergyTrack, looks_like_prompt, rms
from app.live.openai_rt import TRANSCRIPTION_PROMPT

# Both leaked verbatim in live sessions once they were part of the prompt.
LEAKED_EXAMPLE = "我們這場會議先討論進度與問題，請確認時間。"
LEAKED_TERMS = "那個Prototype A跟Prototype B的握感怎麼樣？有沒有滿意度調查的結果？還有Prototype C的矽膠包覆樣品進度如何？"


def test_prompt_is_only_a_scene_description() -> None:
    """Per OpenAI docs the prompt describes the recording. Anything else has leaked."""
    for banned in ("例如", "「", "輸出", "請以", "詞彙：", "Prototype", "握感"):
        assert banned not in TRANSCRIPTION_PROMPT, banned
    assert len(TRANSCRIPTION_PROMPT) < 40


def test_only_verbatim_prompt_text_is_refused() -> None:
    assert looks_like_prompt(TRANSCRIPTION_PROMPT, TRANSCRIPTION_PROMPT)
    assert looks_like_prompt("台灣繁體中文的產品會議對話", TRANSCRIPTION_PROMPT)
    # Real speech - including a sentence stuffed with product terms - always passes now.
    for text in (
        LEAKED_EXAMPLE,
        LEAKED_TERMS,
        "還沒喔",
        "好的好的。",
        "Prototype C的滿意度中等,握感的問題還沒解,供應商說兩週內可以交樣品。",
    ):
        assert not looks_like_prompt(text, TRANSCRIPTION_PROMPT), text


def _tone(level: int, seconds: float = 0.1) -> bytes:
    t = np.arange(int(16_000 * seconds))
    return (np.sin(t / 8) * level).astype("<i2").tobytes()


def test_energy_track_reports_peak_and_distinguishes_no_data() -> None:
    track = EnergyTrack()
    for i in range(30):  # 3 s of room tone
        track.add(i / 10, rms(_tone(80)))
    for i in range(30, 45):  # 1.5 s of speech
        track.add(i / 10, rms(_tone(2000)))
    assert (track.peak(0.5, 2.5) or 0) < 100
    assert (track.peak(3.0, 4.5) or 0) > 1000
    assert track.peak(20.0, 21.0) is None  # no samples there: unknown, not silent
