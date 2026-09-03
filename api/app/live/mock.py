import asyncio
import contextlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from app.live.events import EngineEvent, EngineStatus, ToolCall, Transcript


class MockLiveEngine:
    def __init__(self, speed: float | None = None) -> None:
        self.events: asyncio.Queue[EngineEvent] = asyncio.Queue()
        self.speed = speed or float(os.environ.get("MOCK_SPEED", "1"))
        self.speed = max(self.speed, 0.01)
        self._started = time.monotonic()
        self._script_task: asyncio.Task[None] | None = None
        self._closed = False

    async def start(self, session_id: str) -> None:
        del session_id
        self._started = time.monotonic()
        self._closed = False
        script_path = Path(__file__).with_name("mock_script.json")
        script = json.loads(script_path.read_text(encoding="utf-8"))
        self._script_task = asyncio.create_task(self._replay(script))

    async def _replay(self, script: list[dict[str, Any]]) -> None:
        previous_ts = 0.0
        for item in script:
            if self._closed:
                return
            await asyncio.sleep(max(0.0, (item["ts"] - previous_ts) / self.speed))
            previous_ts = item["ts"]
            await self.events.put(
                Transcript(text=item["text"], ts=float(item["ts"]), speaker=item.get("speaker"))
            )
            tool = item.get("tool")
            if tool:
                await self.events.put(
                    ToolCall(name=tool["name"], args=tool.get("args", {}), ts=float(item["ts"]))
                )
        await self.events.put(EngineStatus("script_complete"))

    async def send_audio(self, audio: bytes) -> None:
        del audio

    async def send_frame(self, jpeg_bytes: bytes, reason: str = "manual") -> None:
        del jpeg_bytes, reason

    async def send_text(self, text: str) -> None:
        ts = time.monotonic() - self._started
        await self.events.put(Transcript(text=text, ts=ts))
        if re.search(r"這個|那個|這裡|右邊這塊|\b(?:this|that|here)\b", text, re.IGNORECASE):
            await self.events.put(
                ToolCall(
                    name="create_anchor",
                    args={
                        "target": "(畫面中被指向的物件)",
                        "observation": text,
                        "confidence": 0.65,
                    },
                    ts=ts,
                )
            )
        if re.search(r"決定|就定|採用", text):
            await self.events.put(
                ToolCall(
                    name="propose_decision",
                    args={
                        "topic": "Typed fallback decision",
                        "chosen": text,
                        "alternatives": [],
                        "reasons_for": [],
                        "reasons_against": [],
                        "constraints": [],
                    },
                    ts=ts,
                )
            )

    async def close(self) -> None:
        self._closed = True
        if self._script_task and not self._script_task.done():
            self._script_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._script_task
