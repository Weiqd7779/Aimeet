from app.live.echo import EchoFilter, similar


def test_exact_and_punctuation_variants_are_echo() -> None:
    assert similar("供應商說兩週內可以交樣品。", "供應商說，兩週內可以交樣品")


def test_simplified_vs_traditional_output_is_still_echo() -> None:
    assert similar(
        "這張圖表顯示，Prototype B的滿意度最高，測試者都給正面回饋。",
        "这张图表显示,Prototype B的满意度最高,测试者都给正面反馈。",
    )


def test_mic_fragment_of_remote_sentence_is_echo() -> None:
    assert similar("兩週內可以交樣品", "供應商說兩週內可以交樣品，成本大概每台八百五十塊。")


def test_short_backchannel_is_never_echo() -> None:
    assert not similar("好", "好，那就這樣定。")
    assert not similar("對對", "對，B 的成本超過上限。")


def test_different_sentences_overlapping_in_time_are_kept() -> None:
    echo = EchoFilter()
    echo.note_remote(10.0, "Prototype B 的滿意度最高，測試者都給正面回饋。")
    assert not echo.is_echo(10.2, "但是 B 的成本是一千零二十，超過我們八百五的上限。")


def test_same_sentence_outside_window_is_kept() -> None:
    echo = EchoFilter(window_s=3.0)
    echo.note_remote(10.0, "供應商說兩週內可以交樣品。")
    assert echo.is_echo(11.5, "供應商說兩週內可以交樣品")
    assert not echo.is_echo(20.0, "供應商說兩週內可以交樣品")  # host repeating it later
