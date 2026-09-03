"""第二層驗收：真實 provider 整合測試。

缺 `OPENAI_API_KEY` 時整檔跳過。Realtime 部分另需預錄音訊 fixture，
放置方式見 `docs/e2e_google_meet_checklist.md`：

    api/tests/fixtures/realtime/accept_button.pcm   # 16 kHz mono s16le，內容例：「你看這邊這個按鈕太小」
    api/tests/fixtures/realtime/accept_button.jpg   # 對應畫面
    api/tests/fixtures/realtime/reject_filler.pcm   # 內容例：「這件事回去再說」
    api/tests/fixtures/realtime/reject_filler.jpg
"""

import asyncio
import base64
import os
from pathlib import Path

import pytest

from app.config import settings
from app.live.openai_rt import OpenAIRealtimeEngine
from app.vision import verify_visual_reference
from tests.live_harness import build_manager, wait_for

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set"),
]

FIXTURES = Path(__file__).parent / "fixtures"
REALTIME = FIXTURES / "realtime"
UI_FRAME = base64.b64encode((FIXTURES / "ui_small_button.jpg").read_bytes()).decode("ascii")
CHUNK_SAMPLES = 1600  # 100 ms @ 16 kHz mono s16le


@pytest.fixture(autouse=True)
def live_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(settings, "openai_api_key", os.environ["OPENAI_API_KEY"])
    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(settings, "live_provider", "openai")
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    return settings


@pytest.mark.asyncio
async def test_vision_rejects_filler_utterance() -> None:
    verdict = await verify_visual_reference(
        "這件事回去再說",
        ["剛剛那個排程的事情", "這件事回去再說"],
        UI_FRAME,
    )
    assert verdict.is_grounded_visual_reference is False


@pytest.mark.asyncio
async def test_vision_accepts_real_visual_reference() -> None:
    verdict = await verify_visual_reference(
        "你看這邊這個 Save 按鈕太小",
        ["我們看一下設定頁", "你看這邊這個 Save 按鈕太小"],
        UI_FRAME,
    )
    assert verdict.is_grounded_visual_reference is True


async def _run_realtime_fixture(name: str) -> tuple[list[dict], list[dict]]:
    audio_path = REALTIME / f"{name}.pcm"
    frame_path = REALTIME / f"{name}.jpg"
    if not audio_path.exists() or not frame_path.exists():
        pytest.skip(f"Missing realtime fixture: {audio_path.name} / {frame_path.name}")

    manager, websocket, _ = build_manager()
    manager.engine = OpenAIRealtimeEngine()
    manager.frame_wait_seconds = 2.0
    manager.context_after_seconds = 5.0
    run_task = asyncio.create_task(manager.run())
    await wait_for(lambda: bool(websocket.payloads("status")))

    jpeg_b64 = base64.b64encode(frame_path.read_bytes()).decode("ascii")
    websocket.incoming.put_nowait(
        {"type": "frame", "jpeg_b64": jpeg_b64, "ts": 0.0, "reason": "manual"}
    )
    pcm = audio_path.read_bytes()
    for offset in range(0, len(pcm), CHUNK_SAMPLES * 2):
        chunk = pcm[offset : offset + CHUNK_SAMPLES * 2]
        websocket.incoming.put_nowait(
            {"type": "audio", "pcm16_b64": base64.b64encode(chunk).decode("ascii")}
        )
        await asyncio.sleep(0.1)

    await asyncio.sleep(20)
    websocket.incoming.put_nowait({"type": "end"})
    await asyncio.wait_for(run_task, timeout=30)
    return websocket.payloads("transcript"), websocket.payloads("grounded_visual_event")


@pytest.mark.asyncio
async def test_realtime_filler_does_not_create_event() -> None:
    transcripts, events = await _run_realtime_fixture("reject_filler")
    assert transcripts, "Realtime 沒有回傳任何 transcript"
    assert events == []


@pytest.mark.asyncio
async def test_realtime_visual_reference_runs_full_state_machine() -> None:
    transcripts, events = await _run_realtime_fixture("accept_button")
    assert transcripts, "Realtime 沒有回傳任何 transcript"
    assert events, "真實指涉沒有建立 GroundedVisualEvent"
    assert events[0]["lifecycle"] == "aggregating"
    closed = events[-1]
    assert closed["lifecycle"] == "closed"
    assert closed["evidence_frame_ids"]
    trigger = closed["time_range"]["trigger"]
    # transcript 與 frame 共用同一個 elapsed 時鐘
    assert min(abs(entry["ts"] - trigger) for entry in transcripts) < 5.0
