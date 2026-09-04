import asyncio
import base64

import pytest

from app.live import session as session_module
from app.live.events import ToolCall, Transcript
from tests.live_harness import build_manager, wait_for

JPEG = base64.b64encode(b"fake-jpeg").decode("ascii")
PCM = base64.b64encode(b"\x00\x01" * 16).decode("ascii")
ANCHOR_TEXT = "你看這邊這個按鈕太小"


async def seed_anchor_context(websocket, engine) -> None:
    """A create_anchor only survives with a deictic utterance and a frame to point at."""
    engine.events.put_nowait(Transcript(text=ANCHOR_TEXT, ts=1.0, speaker="與會者"))
    websocket.incoming.put_nowait({"type": "frame", "jpeg_b64": JPEG, "ts": 1.0, "reason": "diff"})
    await wait_for(lambda: bool(websocket.payloads("transcript")) and bool(engine.frames))


@pytest.mark.asyncio
async def test_slow_conflict_check_does_not_block_ingestion(monkeypatch) -> None:
    started = asyncio.Event()

    async def slow_check_conflict(decision, hits):
        del decision, hits
        started.set()
        await asyncio.sleep(0.5)
        return []

    monkeypatch.setattr(session_module, "check_conflict", slow_check_conflict)

    manager, websocket, engine = build_manager()
    run_task = asyncio.create_task(manager.run())
    await wait_for(lambda: bool(websocket.payloads("status")))

    engine.events.put_nowait(
        ToolCall(name="propose_decision", args={"topic": "t", "chosen": "c"}, ts=1.0)
    )
    await wait_for(started.is_set)

    for index in range(20):
        websocket.incoming.put_nowait({"type": "audio", "pcm16_b64": PCM})
        websocket.incoming.put_nowait(
            {"type": "frame", "jpeg_b64": JPEG, "ts": float(index), "reason": "diff"}
        )

    await wait_for(lambda: len(engine.audio) == 20 and len(engine.frames) == 20, timeout=0.4)

    websocket.incoming.put_nowait({"type": "end"})
    await asyncio.wait_for(run_task, timeout=5)


@pytest.mark.asyncio
async def test_anchor_verification_is_queued_not_inlined(monkeypatch) -> None:
    verifying = asyncio.Event()

    async def slow_verify(trigger_text, context, jpeg_b64):
        del trigger_text, context, jpeg_b64
        verifying.set()
        await asyncio.sleep(0.5)
        raise AssertionError("cancelled before completion")

    monkeypatch.setattr(session_module, "verify_visual_reference", slow_verify)

    manager, websocket, engine = build_manager()
    run_task = asyncio.create_task(manager.run())
    await wait_for(lambda: bool(websocket.payloads("status")))
    await seed_anchor_context(websocket, engine)

    engine.events.put_nowait(ToolCall(name="create_anchor", args={"target": "x"}, ts=1.0))
    await wait_for(verifying.is_set)

    websocket.incoming.put_nowait({"type": "audio", "pcm16_b64": PCM})
    await wait_for(lambda: len(engine.audio) == 1, timeout=0.5)
    assert not websocket.payloads("grounded_visual_event")

    manager.drain_seconds = 0.0
    websocket.incoming.put_nowait({"type": "end"})
    await asyncio.wait_for(run_task, timeout=5)


@pytest.mark.asyncio
async def test_create_anchor_requests_deictic_frame() -> None:
    manager, websocket, engine = build_manager()
    manager.context_after_seconds = 0.05
    run_task = asyncio.create_task(manager.run())
    await wait_for(lambda: bool(websocket.payloads("status")))
    await seed_anchor_context(websocket, engine)

    engine.events.put_nowait(ToolCall(name="create_anchor", args={"target": "x"}, ts=1.0))
    await wait_for(
        lambda: any(payload.get("reason") == "deictic" for payload in websocket.payloads("status"))
    )

    websocket.incoming.put_nowait(
        {"type": "frame", "jpeg_b64": JPEG, "ts": 1.0, "reason": "deictic"}
    )
    await wait_for(lambda: engine.frames[-1] == (b"fake-jpeg", "deictic"))

    websocket.incoming.put_nowait({"type": "end"})
    await asyncio.wait_for(run_task, timeout=5)
