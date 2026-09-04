import asyncio

from app.knowledge.store import KnowledgeStore
from app.live.deictic import DEICTIC
from app.live.session import (
    COMMIT,
    UNDECIDED,
    LiveSessionManager,
    _extend_unique,
    _is_fragment,
    _same_meaning,
)
from app.models import Alert, Decision, MeetingSession


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
