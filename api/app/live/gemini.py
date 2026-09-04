import asyncio
import contextlib
import time
from typing import Any

from google import genai
from google.genai import types

from app.config import Settings, settings
from app.live.events import EngineEvent, EngineStatus, ToolCall, Transcript
from app.live.prompt import SYSTEM_INSTRUCTION
from app.live.tools import TOOLS


class GeminiLiveEngine:
    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.events: asyncio.Queue[EngineEvent] = asyncio.Queue()
        self._client: genai.Client | None = None
        self._session: Any = None
        self._connect_context: Any = None
        self._listener: asyncio.Task[None] | None = None
        self._started = time.monotonic()
        self._reconnects = 0
        self._closed = False

    async def _connect(self) -> None:
        if not self.settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required for live mode")
        self._client = self._client or genai.Client(api_key=self.settings.gemini_api_key)
        self._connect_context = self._client.aio.live.connect(
            model=self.settings.gemini_live_model,
            config=types.LiveConnectConfig(
                response_modalities=["TEXT"],
                input_audio_transcription=types.AudioTranscriptionConfig(),
                tools=TOOLS,
                system_instruction=SYSTEM_INSTRUCTION,
            ),
        )
        self._session = await self._connect_context.__aenter__()

    async def start(self, session_id: str) -> None:
        del session_id
        self._started = time.monotonic()
        self._closed = False
        await self._connect()
        self._listener = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        try:
            async for message in self._session.receive():
                if getattr(message, "go_away", None):
                    await self._handle_disconnect("Gemini requested reconnect")
                    return
                server_content = getattr(message, "server_content", None)
                transcription = getattr(server_content, "input_transcription", None)
                if transcription and getattr(transcription, "text", None):
                    await self.events.put(
                        Transcript(
                            text=transcription.text,
                            ts=time.monotonic() - self._started,
                        )
                    )
                tool_call = getattr(message, "tool_call", None)
                if tool_call:
                    for function_call in tool_call.function_calls or []:
                        call_id = getattr(function_call, "id", None)
                        await self._reply_to_tool_call(
                            getattr(function_call, "name", ""),
                            call_id,
                        )
                        await self.events.put(
                            ToolCall(
                                name=getattr(function_call, "name", ""),
                                args=dict(getattr(function_call, "args", {}) or {}),
                                id=call_id,
                                ts=time.monotonic() - self._started,
                            )
                        )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await self._handle_disconnect(str(exc))

    async def _reply_to_tool_call(self, name: str, call_id: str | None) -> None:
        if self._session is None:
            return
        response = types.FunctionResponse(
            id=call_id,
            name=name,
            response={"result": "ok"},
        )
        await self._session.send_tool_response(function_responses=[response])

    async def _handle_disconnect(self, detail: str) -> None:
        if self._closed:
            return
        if self._reconnects < 1:
            self._reconnects += 1
            await self.events.put(EngineStatus("reconnecting", detail))
            with contextlib.suppress(Exception):
                if self._connect_context:
                    await self._connect_context.__aexit__(None, None, None)
            await self._connect()
            self._listener = asyncio.create_task(self._listen())
            return
        await self.events.put(EngineStatus("disconnected", detail))

    async def send_audio(self, audio: bytes, source: str | None = None) -> None:
        del source
        await self._session.send_realtime_input(
            audio=types.Blob(data=audio, mime_type="audio/pcm;rate=16000")
        )

    async def send_frame(
        self, jpeg_bytes: bytes, frame_id: str | None = None, ts: float | None = None
    ) -> None:
        del frame_id, ts
        await self._session.send_realtime_input(
            video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
        )

    async def send_text(self, text: str) -> None:
        await self._session.send_realtime_input(text=text)

    async def close(self) -> None:
        self._closed = True
        if self._listener and self._listener is not asyncio.current_task():
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
        if self._connect_context:
            with contextlib.suppress(Exception):
                await self._connect_context.__aexit__(None, None, None)
        self._session = None
