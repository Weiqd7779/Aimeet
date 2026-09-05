import asyncio

from app.knowledge.store import KnowledgeStore
from app.live.deictic import DEICTIC
from app.live.events import ToolCall
from app.live.session import (
    COMMIT,
    UNDECIDED,
    LiveSessionManager,
    _extend_unique,
    _is_fragment,
    _same_meaning,
)
from app.models import Alert, Decision, Frame, GroundedEvent, MeetingSession, TranscriptEntry


def test_deictic_matches_pointing_and_screen_words_only() -> None:
    for text in (
        "你看右邊這張表",
        "螢幕上的表格顯示 B 最高",
        "這頁的 KPI 太低",
        "look at this chart",
        "the number on the screen is wrong",
    ):
        assert DEICTIC.search(text), text
    for text in (
        "Prototype C 八百三十",
        "this is fine",
        "that was quick",
        "B 的成本超過上限",
    ):
        assert not DEICTIC.search(text), text


def test_fragment_gate_waits_for_the_object_to_be_named() -> None:
    for text in ("以及這個是", "以及這個是...", "然後這個", "這個就是，"):
        assert _is_fragment(text), text
    for text in ("這個貓咪杯子是我們之後要出的新產品。", "這個指甲剪非常好用", "你看右邊這張表"):
        assert not _is_fragment(text), text


def test_commit_words_separate_decisions_from_evaluation() -> None:
    for text in (
        "那我們決定 Q4 先採用 Prototype C",
        "那就這樣定",
        "改用矽膠包覆",
        "let's go with C",
    ):
        assert COMMIT.search(text), text
    for text in ("今天要看成本和滿意度", "B 的滿意度最高", "成本可以壓到九百二十"):
        assert not COMMIT.search(text), text
    assert UNDECIDED.search("尚未拍板") and not UNDECIDED.search("Q4 採用 Prototype C")
    assert not UNDECIDED.search("Q4 採用 Prototype C，Prototype B 留做下一季候選")


def test_same_meaning_merges_rewordings_but_never_different_facts() -> None:
    assert _same_meaning(
        "Prototype C 成本 NT$830，未超過 BOM 成本上限 NT$850",
        "Prototype C 成本 NT$830，符合 BOM 成本上限 NT$850",
    )
    assert not _same_meaning("Prototype A 成本 NT$780", "Prototype B 成本 NT$1,020")
    assert not _same_meaning("兩週內交樣品", "三週內交樣品")
    reasons: list[str] = []
    _extend_unique(
        reasons,
        [
            "主持人已明確拍板採用 Prototype C",
            "主持人已明確拍板表示採用 Prototype C",
            "Prototype C 握感問題待解決",
        ],
    )
    assert len(reasons) == 2


class _Socket:
    async def send_json(self, _: dict) -> None:
        return None


def _manager() -> LiveSessionManager:
    return LiveSessionManager(_Socket(), MeetingSession(), KnowledgeStore())  # type: ignore[arg-type]


def test_restating_a_decision_does_not_recheck_or_stack_alerts() -> None:
    async def scenario() -> None:
        manager = _manager()
        first, changed = manager._merge_decision(
            Decision(ts=1, topic="Q4 主打方案", chosen="採用 Prototype C", reasons_for=["成本 830"])
        )
        assert changed
        again, changed = manager._merge_decision(
            Decision(
                ts=2, topic="Q4 主打方案", chosen="Q4 採用 Prototype C", reasons_for=["成本830"]
            )
        )
        assert again is first and not changed
        assert first.reasons_for == ["成本 830"]
        switched, changed = manager._merge_decision(
            Decision(ts=3, topic="Q4 主打方案", chosen="改採 Prototype B")
        )
        assert switched is first and changed

        alert = Alert(
            ts=3, kind="conflict", title="t", detail="v1", source="PRD v3", decision_id=first.id
        )
        manager._merge_alerts(first, [alert])
        manager._merge_alerts(
            first,
            [
                Alert(
                    ts=4,
                    kind="conflict",
                    title="t",
                    detail="v2",
                    source="PRD v3",
                    decision_id=first.id,
                )
            ],
        )
        assert len(manager.session.alerts) == 1 and manager.session.alerts[0].detail == "v2"
        assert first.conflicts == [alert.id]

    asyncio.run(scenario())


def test_anchor_merge_is_a_safety_net_for_same_looking_objects() -> None:
    async def scenario() -> None:
        manager = _manager()
        first = manager._merge_anchor(
            GroundedEvent(
                ts=15.5,
                speaker="我",
                utterance="這個是個手把。",
                target="手把——右手拿著的黑色遊戲控制器",
                observation="一個黑色遊戲控制器，兩個類比搖桿與按鍵，右手握著",
                frame_id="f1",
                confidence=0.98,
                said=[],
                mention_ids=["u1"],
            )
        )
        # model said "new thing" but vision saw the very same controller 6 s later
        merged = manager._merge_anchor(
            GroundedEvent(
                ts=21.8,
                speaker="我",
                utterance="我會在9月29號的時候推出這個東西。",
                target="東西——左手拿著的黑色遊戲手把",
                observation="一個黑色遊戲控制器，左右握把與搖桿，被手握著",
                frame_id="f4",
                confidence=0.93,
                said=["9月29號推出"],
                mention_ids=["u4"],
            )
        )
        assert merged is first and len(manager.session.grounded_events) == 1
        assert first.said == ["9月29號推出"] and first.mention_ids == ["u1", "u4"]
        assert first.frame_id == "f1"  # keep the higher-confidence look
        # a genuinely different object is not merged
        cup = manager._merge_anchor(
            GroundedEvent(
                ts=30.0,
                speaker="我",
                utterance="這個是貓咪杯子",
                target="貓咪杯子——舉起的白色馬克杯",
                observation="白色直筒杯，杯身有戴眼鏡的卡通貓圖案",
                frame_id="f9",
                confidence=0.97,
            )
        )
        assert cup is not first and len(manager.session.grounded_events) == 2

    asyncio.run(scenario())


def test_confident_look_overrides_text_gates_but_weak_look_does_not() -> None:
    """Session f9d3f01a: STT split 「就是這個，最新的智慧眼鏡…」 into a fragment and a sentence
    with no pointing word; vision saw the glasses at 0.92 / 0.84 both times and both were
    dropped. A confident look must anchor; an uncertain one still needs the wording."""

    async def anchor(text: str, confidence: float) -> int:
        manager = _manager()
        manager.engine = object()  # not the mock engine: gates apply
        manager.session.frames.append(Frame(ts=30.0, jpeg_b64="", reason="periodic"))
        entry = TranscriptEntry(ts=35.5, speaker="我", text=text)
        manager.session.transcript.append(entry)
        manager.recorder.add_utterance(id=entry.id, ts=entry.ts, speaker="我", text=text)
        await manager._handle_tool_call(
            ToolCall(
                name="create_anchor",
                args={
                    "target": "智慧眼鏡——雙手舉著的黑色裝置",
                    "observation": "黑色圓形裝置",
                    "confidence": confidence,
                    "frame_id": manager.session.frames[0].id,
                },
                ts=35.5,
                utterance_id=entry.id,
            )
        )
        return len(manager.session.grounded_events)

    async def scenario() -> None:
        assert await anchor("啊,就是這個。", 0.92) == 1  # fragment, but vision is sure
        assert await anchor("最新的智慧眼鏡由我們公司發布的", 0.84) == 1  # no pointer, sure
        assert await anchor("啊,就是這個。", 0.7) == 0  # fragment + only fairly sure
        assert await anchor("最新的智慧眼鏡由我們公司發布的", 0.7) == 0  # no pointer + fairly sure
        assert await anchor("你看這個智慧眼鏡", 0.7) == 1  # proper pointing sentence is enough
        assert await anchor("你看這個智慧眼鏡", 0.5) == 0  # vision not sure: never

    asyncio.run(scenario())
