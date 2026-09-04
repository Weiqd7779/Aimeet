from app.live.reasoner import Reasoner, _pointed_object


def _reasoner_with_frames(times: list[float]) -> Reasoner:
    reasoner = Reasoner(client=None, model="x")  # type: ignore[arg-type]
    for t in times:
        reasoner.set_frame(t, b"\xff\xd8", f"f{t:g}")
    return reasoner


def test_frames_between_covers_the_speech_span_with_at_most_three() -> None:
    reasoner = _reasoner_with_frames([0, 2, 4, 6, 8, 10, 12, 14])
    picked = reasoner.frames_between(3.0, 11.0)
    assert [f.frame_id for f in picked] == ["f4", "f8", "f10"]  # first, middle, last
    assert reasoner.frames_between(20.0, 25.0) == []  # nothing captured then


def test_pointed_object_takes_the_noun_after_the_pointer() -> None:
    assert _pointed_object("右邊這塊圖表顯示 Prototype B 的滿意度最高") == "圖表"
    assert _pointed_object("這個指甲剪有非常棒的功能") == "指甲剪"
    assert _pointed_object("這個是貓咪杯子") == "貓咪杯子"
    assert _pointed_object("你看這裡") == "說話者指的東西"  # no noun at all -> generic
