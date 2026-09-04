import asyncio

import pytest

from app.config import settings
from app.live.events import ToolCall, Transcript
from app.vision import heuristic_verdict
from tests.live_harness import build_manager, jpeg_b64, wait_for

JPEG = jpeg_b64()

FILLERS = ["這件事回去再說", "這個方法昨天討論過"]
REFERENCES = ["你看這邊這個按鈕太小", "你看右邊這張圖的色階怪怪的"]


@pytest.mark.parametrize("text", FILLERS)
def test_heuristic_rejects_filler(text: str) -> None:
    assert heuristic_verdict(text, []).is_grounded_visual_reference is False


@pytest.mark.parametrize("text", REFERENCES)
def test_heuristic_accepts_visual_reference(text: str) -> None:
    assert heuristic_verdict(text, []).is_grounded_visual_reference is True


async def _anchor(text: str, data_dir) -> list[dict]:
    settings.data_dir = str(data_dir)
    manager, websocket, engine = build_manager()
    manager.context_after_seconds = 0.05
    run_task = asyncio.create_task(manager.run())
    await wait_for(lambda: bool(websocket.payloads("status")))

    websocket.incoming.put_nowait(
        {"type": "frame", "jpeg_b64": JPEG, "ts": 10.0, "reason": "deictic"}
    )
    engine.events.put_nowait(Transcript(text=text, ts=10.0))
    await wait_for(lambda: bool(websocket.payloads("transcript")))
    engine.events.put_nowait(ToolCall(name="create_anchor", args={"target": "x"}, ts=10.0))
    await asyncio.sleep(0.3)

    websocket.incoming.put_nowait({"type": "end"})
    await asyncio.wait_for(run_task, timeout=5)
    return websocket.payloads("grounded_visual_event")


@pytest.mark.asyncio
@pytest.mark.parametrize("text", FILLERS)
async def test_filler_does_not_create_event(text: str, tmp_path) -> None:
    assert await _anchor(text, tmp_path) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("text", REFERENCES)
async def test_visual_reference_creates_event(text: str, tmp_path) -> None:
    payloads = await _anchor(text, tmp_path)
    assert payloads
    assert payloads[0]["trigger_text"] == text
    assert payloads[-1]["lifecycle"] == "closed"
