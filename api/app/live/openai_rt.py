import asyncio
import base64
import contextlib
import time
from typing import Any

from openai import AsyncOpenAI

from app.config import Settings, settings
from app.live.audio import resample_pcm16
from app.live.events import EngineEvent, EngineStatus, IntentResolved, Transcript
from app.live.reasoner import Reasoner

SPEAKER_LABELS = {"me": "我", "remote": "與會者"}
NOISE_REDUCTION = {"me": "near_field", "remote": "far_field"}
TRANSCRIPTION_PROMPT = (
    "台灣繁體中文的產品與工程會議對話，夾雜英文技術詞彙。請以繁體中文輸出。"
    "常見詞彙：Prototype A、Prototype B、Prototype C、方案A、方案B、Q4、API、Redis、"
    "cache layer、issue、BOM、NT$、矽膠包覆、握感、樣品、供應商。"
)


class _Connection:
    """Thin wrapper around one realtime websocket plus its listener task."""

    def __init__(self, client: AsyncOpenAI, **connect_kwargs: Any) -> None:
        self._manager = client.realtime.connect(**connect_kwargs)
        self.conn: Any = None
        self.listener: asyncio.Task[None] | None = None

    async def open(self) -> Any:
        self.conn = await self._manager.__aenter__()
        return self.conn

    async def close(self) -> None:
        if self.listener and self.listener is not asyncio.current_task():
            self.listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.listener
        if self.conn:
            with contextlib.suppress(Exception):
                await self.conn.close()
        with contextlib.suppress(Exception):
            await self._manager.__aexit__(None, None, None)
        self.conn = None


class OpenAIRealtimeEngine:
    """One transcription socket per speaker channel + a stateless reasoner.

    Speaker channels are never mixed: each source gets its own server-side VAD and
    transcript stream, so overlapping speech stays attributed to the right person.
    Completed utterances (with speaker label and speech-start timestamp) go to the
    Reasoner, which decides per utterance whether any tool should fire.
    """

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.events: asyncio.Queue[EngineEvent] = asyncio.Queue()
        self._client: AsyncOpenAI | None = None
        self.reasoner: Reasoner | None = None
        self._transcribers: dict[str, _Connection] = {}
        self._pending: set[asyncio.Task[None]] = set()
        self._started = time.monotonic()
        self._last_frame = 0.0
        self._buffer_start: dict[str, float] = {}  # source -> elapsed at first audio chunk
        self._speech_start: dict[str, float] = {}  # item_id -> elapsed at speech start
        self._closed = False

    def _elapsed(self) -> float:
        return time.monotonic() - self._started

    async def start(self, session_id: str) -> None:
        del session_id
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI live mode")
        self._started = time.monotonic()
        self._closed = False
        self._client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        self.reasoner = Reasoner(self._client, self.settings.openai_reasoning_model)

        for source in SPEAKER_LABELS:
            transcriber = _Connection(self._client, extra_query={"intent": "transcription"})
            tconn = await transcriber.open()
            await tconn.session.update(
                session={
                    "type": "transcription",
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": 24_000},
                            "noise_reduction": {"type": NOISE_REDUCTION[source]},
                            "transcription": {
                                "model": self.settings.openai_transcribe_model,
                                "language": "zh",
                                "prompt": TRANSCRIPTION_PROMPT,
                            },
                            "turn_detection": {"type": "semantic_vad", "eagerness": "medium"},
                        }
                    },
                }
            )
            transcriber.listener = asyncio.create_task(self._listen_transcriber(tconn, source))
            self._transcribers[source] = transcriber

    async def _listen_transcriber(self, conn: Any, source: str) -> None:
        speaker = SPEAKER_LABELS[source]
        try:
            async for event in conn:
                event_type = getattr(event, "type", "")
                if event_type == "input_audio_buffer.speech_started":
                    # Timestamp utterances by when speech *started*, not when the
                    # transcript arrived, so the record keeps true conversational order.
                    start_ms = getattr(event, "audio_start_ms", None)
                    item_id = getattr(event, "item_id", None)
                    if start_ms is not None and item_id:
                        self._speech_start[item_id] = (
                            self._buffer_start.get(source, self._elapsed()) + start_ms / 1000
                        )
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    text = getattr(event, "transcript", "").strip()
                    ts = self._speech_start.pop(getattr(event, "item_id", None), None)
                    if text:
                        transcript = Transcript(
                            text=text, ts=ts if ts is not None else self._elapsed(), speaker=speaker
                        )
                        await self.events.put(transcript)
                        self._spawn_reasoning(transcript)
                elif event_type == "error":
                    await self._fail(f"{speaker} transcription: {getattr(event, 'error', event)}")
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await self._fail(f"{speaker} transcription: {exc}")

    def _spawn_reasoning(self, transcript: Transcript) -> None:
        task = asyncio.create_task(self._reason(transcript))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _reason(self, transcript: Transcript) -> None:
        if not self.reasoner:
            return
        calls = await self.reasoner.process(
            transcript.speaker or "?", transcript.text, transcript.ts
        )
        for call in calls:
            call.utterance_id = transcript.id
            await self.events.put(call)
        await self.events.put(IntentResolved(transcript.id, [call.name for call in calls]))

    async def _fail(self, detail: str) -> None:
        if not self._closed:
            await self.events.put(EngineStatus("disconnected", detail))

    async def send_audio(self, audio: bytes, source: str | None = None) -> None:
        transcriber = self._transcribers.get(source or "")
        if not transcriber or not transcriber.conn:
            return
        self._buffer_start.setdefault(source or "", self._elapsed())
        pcm24 = resample_pcm16(audio)
        await transcriber.conn.input_audio_buffer.append(
            audio=base64.b64encode(pcm24).decode("ascii")
        )

    async def send_frame(self, jpeg_bytes: bytes) -> None:
        now = time.monotonic()
        if now - self._last_frame < 4 or not self.reasoner:
            return
        self._last_frame = now
        self.reasoner.set_frame(self._elapsed(), jpeg_bytes)

    async def send_text(self, text: str) -> None:
        transcript = Transcript(text=text, ts=self._elapsed(), speaker=SPEAKER_LABELS["me"])
        await self.events.put(transcript)
        self._spawn_reasoning(transcript)

    async def close(self) -> None:
        self._closed = True
        for task in list(self._pending):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        for transcriber in self._transcribers.values():
            await transcriber.close()
        self._transcribers = {}
        self.reasoner = None
