"""Consistency agent: time / assignee contradictions become spoken silent reminders."""

import asyncio
import base64
from types import SimpleNamespace

from app import tts
from app.config import settings
from app.consistency import (
    CommitmentUpdate,
    ConsistencyAgent,
    ConsistencyVerdict,
    Inconsistency,
    has_cue,
)
from app.knowledge.store import KnowledgeStore
from app.live.events import ToolCall, Transcript
from app.live.session import LiveSessionManager
from app.models import MeetingSession, TranscriptEntry

DATE = "2026-09-05（Sat）"


def _say(text: str, ts: float, speaker: str = "我") -> TranscriptEntry:
    return TranscriptEntry(ts=ts, speaker=speaker, text=text)


def test_cue_gate_skips_sentences_without_time_or_owner() -> None:
    for text in ("API 串接由小王負責", "下星期三要交", "報告 9 月 12 號給我", "assign it to Amy"):
        assert has_cue(text), text
    for text in ("B 的滿意度最高", "我們先看成本", "這個握感不錯"):
        assert not has_cue(text), text


def test_mock_agent_catches_time_and_assignee_conflicts() -> None:
    agent = ConsistencyAgent(mock=True)

    async def run() -> list[list[Inconsistency]]:
        return [
            await agent.observe(_say("API 串接由小王負責，下星期三交。", 5), DATE),
            await agent.observe(_say("所以是下週三對吧？", 9, "與會者"), DATE),
            await agent.observe(_say("API 串接這星期五要交。", 14, "與會者"), DATE),
            await agent.observe(_say("API 串接交給小李處理。", 20), DATE),
        ]

    first, restated, time_conflict, owner_conflict = asyncio.run(run())
    assert first == [] and restated == []  # 週三 == 星期三: same deadline, no conflict
    assert [f.kind for f in time_conflict] == ["time"]
    assert time_conflict[0].previous == "下星期三" and time_conflict[0].current == "這星期五"
    assert time_conflict[0].detail.startswith("事：API 串接｜人：小王｜時間：下星期三 → 這星期五")
    assert "下星期三" in time_conflict[0].speech and "這星期五" in time_conflict[0].speech
    assert [f.kind for f in owner_conflict] == ["assignee"]
    assert (owner_conflict[0].previous, owner_conflict[0].current) == ("小王", "小李")
    assert len(agent.ledger) == 1 and agent.ledger[0].owner == "小李"


def test_explicit_correction_updates_without_conflict() -> None:
    agent = ConsistencyAgent(mock=True)

    async def run() -> list[Inconsistency]:
        await agent.observe(_say("測試計畫由小林負責，下星期三交。", 5), DATE)
        return await agent.observe(_say("測試計畫改成這星期五交。", 12), DATE)

    assert asyncio.run(run()) == []
    assert agent.ledger[0].due == "這星期五"


def test_llm_verdict_is_applied_to_ledger(monkeypatch) -> None:
    finding = Inconsistency(
        kind="time",
        task="API 串接",
        previous="下星期三",
        current="這星期五",
        detail="事：API 串接｜人：小王｜時間：下星期三 → 這星期五",
        speech="[clears throat] 提醒一下，剛才是下星期三，現在是這星期五。",
    )

    class FakeResponses:
        async def parse(self, **kwargs):
            assert "API 串接" in kwargs["input"]
            return SimpleNamespace(
                output_parsed=ConsistencyVerdict(
                    commitments=[
                        CommitmentUpdate(
                            task="API 串接", owner="小王", due="這星期五", due_date="2026-09-11"
                        )
                    ],
                    conflicts=[finding],
                )
            )

    agent = ConsistencyAgent(client=SimpleNamespace(responses=FakeResponses()), mock=False)
    found = asyncio.run(agent.observe(_say("API 串接這星期五要交。", 14), DATE))
    assert found == [finding]
    assert agent.ledger[0].due_date == "2026-09-11"


class _Socket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def test_session_emits_alert_and_speech_for_a_conflict(monkeypatch) -> None:
    async def fake_speak(text: str, **_) -> bytes:
        assert "這星期五" in text
        return b"ID3fake-mp3"

    monkeypatch.setattr("app.live.session.speak", fake_speak)
    monkeypatch.setattr(settings, "live_provider", "mock")

    async def run() -> tuple[_Socket, LiveSessionManager]:
        socket = _Socket()
        manager = LiveSessionManager(socket, MeetingSession(), KnowledgeStore())  # type: ignore[arg-type]
        manager.consistency = ConsistencyAgent(mock=True)
        for ts, text in (
            (5, "API 串接由小王負責，下星期三交。"),
            (14, "API 串接這星期五要交。"),
            (20, "API 串接改成下星期一交。"),
        ):
            await manager._handle_engine_event(Transcript(text=text, ts=ts, speaker="我"))
        return socket, manager

    socket, manager = asyncio.run(run())
    alerts = [e["payload"] for e in socket.sent if e["type"] == "alert"]
    speech = [e["payload"] for e in socket.sent if e["type"] == "speech"]
    assert len(alerts) == 1 and alerts[0]["kind"] == "inconsistency"
    assert alerts[0]["detail"] == "事：API 串接｜人：小王｜時間：下星期三 → 這星期五"
    assert alerts[0]["speech"] and alerts[0]["title"] == "時間前後不一致"
    assert alerts[0]["evidence"] == ["API 串接由小王負責，下星期三交。", "API 串接這星期五要交。"]
    assert len(speech) == 1 and speech[0]["alert_id"] == alerts[0]["id"]
    assert base64.b64decode(speech[0]["audio_b64"]) == b"ID3fake-mp3"
    assert speech[0]["mime"] == "audio/mpeg"
    # the explicit correction afterwards is not a new conflict; one open card remains
    assert [a.kind for a in manager.session.alerts] == ["inconsistency"]
    linked = [u for u in manager.recorder.utterances if u.alert_ids]
    assert len(linked) == 1 and linked[0].tools == ["flag_inconsistency"]


def test_only_inconsistencies_become_silent_reminders(monkeypatch) -> None:
    """Product default: a silent reminder exists only when the voice reminder does."""

    async def fake_speak(text: str, **_) -> bytes:
        return b"mp3"

    monkeypatch.setattr("app.live.session.speak", fake_speak)
    monkeypatch.setattr(settings, "live_provider", "mock")
    monkeypatch.setattr(settings, "alerts_inconsistency_only", True)

    async def run() -> _Socket:
        socket = _Socket()
        manager = LiveSessionManager(socket, MeetingSession(), KnowledgeStore())  # type: ignore[arg-type]
        manager.consistency = ConsistencyAgent(mock=True)
        await manager._handle_tool_call(
            ToolCall(
                name="notify_speaker", args={"message": "請看第 4 頁", "kind": "slide_mismatch"}
            )
        )
        await manager._handle_tool_call(
            ToolCall(
                name="propose_decision",
                args={"topic": "Q4 主打原型", "chosen": "Prototype B", "alternatives": []},
                ts=3,
            )
        )
        for ts, text in ((5, "API 串接由小王負責，下星期三交。"), (14, "API 串接這星期五要交。")):
            await manager._handle_engine_event(Transcript(text=text, ts=ts, speaker="我"))
        return socket

    socket = asyncio.run(run())
    alerts = [e["payload"] for e in socket.sent if e["type"] == "alert"]
    speech = [e["payload"] for e in socket.sent if e["type"] == "speech"]
    assert [a["kind"] for a in alerts] == ["inconsistency"]
    assert len(speech) == 1 and speech[0]["alert_id"] == alerts[0]["id"]
    assert [e["payload"]["chosen"] for e in socket.sent if e["type"] == "decision"] == [
        "Prototype B"
    ]


def test_tts_strips_audio_tags_for_non_v3_models() -> None:
    assert (
        tts.prepare_text("[clears throat] 嗯，提醒一下。", "eleven_flash_v2_5") == "嗯，提醒一下。"
    )
    assert (
        tts.prepare_text("[clears throat] 嗯，提醒一下。", "eleven_v3")
        == "[clears throat] 嗯，提醒一下。"
    )


def test_tts_is_a_noop_without_a_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    assert asyncio.run(tts.speak("hello")) is None
