import asyncio
import json
from pathlib import Path

import pytest

from app.config import settings
from app.live.events import ToolCall, Transcript
from app.models import Frame
from tests.live_harness import build_manager, jpeg_b64, jpeg_bytes, wait_for

JPEG = jpeg_b64()


@pytest.mark.asyncio
async def test_event_lifecycle_time_range_and_nearest_frame(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))

    manager, websocket, engine = build_manager()
    manager.context_after_seconds = 1.0
    run_task = asyncio.create_task(manager.run())
    await wait_for(lambda: bool(websocket.payloads("status")))

    engine.events.put_nowait(Transcript(text="這段太舊了", ts=70.0))
    engine.events.put_nowait(Transcript(text="我們看一下設定頁", ts=95.0))
    engine.events.put_nowait(Transcript(text="你看這邊這個按鈕太小", ts=100.0))
    await wait_for(lambda: len(websocket.payloads("transcript")) == 3)

    # Frames carry the session clock, which the fake transcript timestamps do not follow,
    # so they are placed on the session buffer directly.
    manager.session.frames.extend(
        Frame(ts=ts, jpeg_b64=JPEG, reason="diff") for ts in (90.0, 99.6, 103.0)
    )
    nearest = min(manager.session.frames, key=lambda frame: abs(frame.ts - 100.0))
    assert nearest.ts == 99.6

    engine.events.put_nowait(ToolCall(name="create_anchor", args={"target": "按鈕"}, ts=100.0))
    await wait_for(lambda: bool(websocket.payloads("grounded_visual_event")))

    triggered = websocket.payloads("grounded_visual_event")[0]
    assert triggered["lifecycle"] == "aggregating"
    assert triggered["time_range"]["trigger"] == 100.0
    assert triggered["time_range"]["start"] == 80.0
    assert triggered["time_range"]["end"] is None
    assert triggered["trigger_text"] == "你看這邊這個按鈕太小"
    assert triggered["context_before"] == ["我們看一下設定頁", "你看這邊這個按鈕太小"]
    assert triggered["evidence_frame_ids"] == [nearest.id]

    engine.events.put_nowait(Transcript(text="那我改成 40 px", ts=100.1))
    engine.events.put_nowait(Transcript(text="這句超出視窗", ts=104.0))
    await wait_for(lambda: len(websocket.payloads("transcript")) == 5)
    await wait_for(
        lambda: any(
            payload["lifecycle"] == "closed"
            for payload in websocket.payloads("grounded_visual_event")
        )
    )

    closed = websocket.payloads("grounded_visual_event")[-1]
    assert closed["event_id"] == triggered["event_id"]
    assert closed["time_range"]["end"] == pytest.approx(100.0 + manager.context_after_seconds)
    assert closed["context_after"] == ["那我改成 40 px"]

    events_path = tmp_path / f"session_{manager.session.id}" / "events.json"
    frame_path = tmp_path / f"session_{manager.session.id}" / "frames" / f"{nearest.id}.jpg"
    assert frame_path.read_bytes() == jpeg_bytes()
    stored = json.loads(events_path.read_text(encoding="utf-8"))
    assert len(stored) == 1
    assert stored[0]["event_id"] == triggered["event_id"]
    assert stored[0]["lifecycle"] == "closed"
    assert "jpeg_b64" not in json.dumps(stored)

    websocket.incoming.put_nowait({"type": "end"})
    await asyncio.wait_for(run_task, timeout=5)


@pytest.mark.asyncio
async def test_buffers_keep_only_recent_window() -> None:
    manager, websocket, engine = build_manager()
    manager.buffer_seconds = 60.0
    run_task = asyncio.create_task(manager.run())
    await wait_for(lambda: bool(websocket.payloads("status")))

    manager.session.transcript.clear()
    engine.events.put_nowait(Transcript(text="很久以前", ts=-120.0))
    engine.events.put_nowait(Transcript(text="剛剛", ts=-1.0))
    await wait_for(lambda: len(manager.session.transcript) == 1)
    assert manager.session.transcript[0].text == "剛剛"

    websocket.incoming.put_nowait({"type": "end"})
    await asyncio.wait_for(run_task, timeout=5)
