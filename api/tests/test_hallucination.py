import numpy as np

from app.live.hallucination import EnergyTrack, looks_like_prompt, rms
from app.live.openai_rt import EXPECTED_TERMS, TRANSCRIPTION_PROMPT

# Verbatim from a live session: nobody said this, the transcriber wove it from the prompt.
LIVE_HALLUCINATION = (
    "我們討論了幾個重要的議題，包括Prototype A和Prototype B的進度，以及方案A和方案B的可行性。"
    "我們也檢視了API的整合問題，並討論了Redis和cache layer的優化。針對目前的issue，我們決定優先處理BOM問題，"
    "以控制成本上限。在使用者滿意度方面，我們計畫進行一系列的測試計畫，以確保握感和矽膠包覆符合需求。"
)


def test_expected_terms_listed() -> None:
    assert "Prototype A" in EXPECTED_TERMS and "握感" in EXPECTED_TERMS


def test_prompt_regurgitation_is_rejected_but_real_sentences_pass() -> None:
    assert looks_like_prompt(LIVE_HALLUCINATION, EXPECTED_TERMS)
    for text in (
        "這個貓咪杯子是我們之後要出的新產品。",
        "Prototype C 的握感問題還沒解，供應商說兩週內可以交樣品。",
        # 4 vocabulary words in one real sentence (rejected once in D2 - must pass)
        "Prototype C的滿意度中等,握感的問題還沒解,供應商說兩週內可以交樣品。",
        "但是 B 的成本是一千零二十，超過我們八百五的上限。",
    ):
        assert not looks_like_prompt(text, EXPECTED_TERMS, TRANSCRIPTION_PROMPT), text


# Live 2026-09-05: the transcriber returned the prompt's own example sentence five times
# while the host said something else. The prompt may not contain example speech, and
# anything that is verbatim prompt text must be rejected even if it does.
def test_transcription_prompt_has_no_example_sentence() -> None:
    assert "「" not in TRANSCRIPTION_PROMPT and "例如" not in TRANSCRIPTION_PROMPT
    assert "輸出" not in TRANSCRIPTION_PROMPT and "請以" not in TRANSCRIPTION_PROMPT


def test_verbatim_prompt_text_is_rejected() -> None:
    prompt = TRANSCRIPTION_PROMPT + "例如「我們這場會議先討論進度與問題，請確認時間。」"
    assert looks_like_prompt("我們這場會議先討論進度與問題，請確認時間。", EXPECTED_TERMS, prompt)
    # a short real sentence that happens to share a term is fine
    assert not looks_like_prompt("樣品什麼時候到？", EXPECTED_TERMS, TRANSCRIPTION_PROMPT)


def _tone(level: int, seconds: float = 0.1) -> bytes:
    t = np.arange(int(16_000 * seconds))
    return (np.sin(t / 8) * level).astype("<i2").tobytes()


def test_energy_gate_needs_speech_level_audio() -> None:
    track = EnergyTrack()
    for i in range(30):  # 3 s of room tone
        track.add(i / 10, rms(_tone(80)))
    assert not track.had_speech(0.5, 2.5)
    for i in range(30, 45):  # then 1.5 s of speech
        track.add(i / 10, rms(_tone(2000)))
    assert track.had_speech(3.0, 4.5)
    assert track.had_speech(0.5, 2.5) is False  # earlier window still silent
