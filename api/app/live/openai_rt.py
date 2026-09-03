import asyncio
import base64
import contextlib
import json
import time
from typing import Any

from openai import AsyncOpenAI

from app.config import Settings, settings
from app.live.audio import resample_pcm16
from app.live.events import EngineEvent, EngineStatus, ToolCall, Transcript
from app.live.prompt import SYSTEM_INSTRUCTION
from app.live.tools import openai_tools


class OpenAIRealtimeEngine:
    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.events: asyncio.Queue[EngineEvent] = asyncio.Queue()
        self._client: AsyncOpenAI | None = None
        self._conn: Any = None
        self._connect_context: Any = None
        self._listener: asyncio.Task[None] | None = None
        self._started = time.monotonic()
        self._last_frame = 0.0
        self._response_done = asyncio.Event()
        self._closed = False

    async def start(self, session_id: str) -> None:
        del session_id
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI live mode")
        self._started = time.monotonic()
        self._closed = False
        self._response_done.set()
        self._client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        self._connect_context = self._client.realtime.connect(
            model=self.settings.openai_realtime_model
        )
        self._conn = await self._connect_context.__aenter__()
        await self._conn.session.update(
            session={
                "type": "realtime",
                "output_modalities": ["text"],
                "instructions": SYSTEM_INSTRUCTION,
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": 24_000},
                        "transcription": {
                            "model": self.settings.openai_transcribe_model,
                            "language": "zh",
                        },
                        "turn_detection": {"type": "server_vad"},
                    }
                },
                "tools": openai_tools(),
                "tool_choice": "auto",
            }
        )
        self._listener = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        try:
            async for event in self._conn:
                event_type = getattr(event, "type", "")
                if event_type == "conversation.item.input_audio_transcription.completed":
                    transcript = getattr(event, "transcript", "")
                    if transcript:
                        await self.events.put(
                            Transcript(
                                text=transcript,
                                ts=time.monotonic() - self._started,
                            )
                        )
                elif event_type == "response.function_call_arguments.done":
                    await self.events.put(
                        ToolCall(
                            name=getattr(event, "name", ""),
                            args=json.loads(getattr(event, "arguments", "{}")),
                            id=getattr(event, "call_id", None),
                            ts=time.monotonic() - self._started,
                        )
                    )
                    await self._reply_to_tool_call(getattr(event, "call_id", None))
                elif event_type == "response.done":
                    self._response_done.set()
                elif event_type == "error":
                    await self.events.put(
                        EngineStatus("disconnected", str(getattr(event, "error", event)))
                    )
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not self._closed:
                await self.events.put(EngineStatus("disconnected", str(exc)))

    async def _reply_to_tool_call(self, call_id: str | None) -> None:
        if call_id:
            await self._conn.conversation.item.create(
                item={
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": '{"result":"ok"}',
                }
            )

    async def send_audio(self, audio: bytes) -> None:
        pcm24 = resample_pcm16(audio)
        await self._conn.input_audio_buffer.append(audio=base64.b64encode(pcm24).decode("ascii"))

    async def send_frame(self, jpeg_bytes: bytes) -> None:
        now = time.monotonic()
        if now - self._last_frame < 4:
            return
        self._last_frame = now
        image_url = f"data:image/jpeg;base64,{base64.b64encode(jpeg_bytes).decode('ascii')}"
        await self._conn.conversation.item.create(
            item={
                "type": "message",
                "role": "user",
                "content": [{"type": "input_image", "image_url": image_url}],
            }
        )

    async def send_text(self, text: str) -> None:
        await self._response_done.wait()
        self._response_done.clear()
        await self._conn.conversation.item.create(
            item={
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            }
        )
        await self._conn.response.create()

    async def close(self) -> None:
        self._closed = True
        if self._listener and self._listener is not asyncio.current_task():
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
        if self._conn:
            with contextlib.suppress(Exception):
                await self._conn.close()
        if self._connect_context:
            with contextlib.suppress(Exception):
                await self._connect_context.__aexit__(None, None, None)
        self._conn = None
