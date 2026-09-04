import asyncio
import base64
import contextlib
import re
import time
from typing import Any

from openai import AsyncOpenAI

from app.config import Settings, settings
from app.live.audio import resample_pcm16
from app.live.echo import HOLD_SECONDS, MAX_HOLD_SECONDS, EchoFilter
from app.live.events import (
    EchoDropped,
    EngineEvent,
    EngineStatus,
    IntentResolved,
    Rejected,
    Transcript,
)
from app.live.hallucination import EnergyTrack, looks_like_prompt, prompt_terms, rms
from app.live.reasoner import Reasoner

DEICTIC_HINT = re.compile(r"這個|那個|這裡|這邊|那邊|右邊|左邊|這張|那張|這頁|螢幕|畫面|圖表|表格")
FRESH_FRAME_WAIT = 1.5  # seconds to wait for the deictic-triggered screenshot before reasoning

SPEAKER_LABELS = {"me": "我", "remote": "與會者"}
NOISE_REDUCTION = {"me": "near_field", "remote": "far_field"}
# Keep the vocabulary short: the transcriber regurgitates these words as fake speech when
# the audio has no clear talker (see hallucination.py), and every extra term feeds that.
TRANSCRIPTION_PROMPT = (
    "台灣繁體中文的產品會議對話，夾雜英文技術詞彙。請以繁體中文輸出，"
    "例如「我們這場會議先討論進度與問題，請確認時間。」"
    "詞彙：Prototype A、Prototype B、Prototype C、Q4、BOM、滿意度、握感、矽膠包覆、樣品。"
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
        self._echo = EchoFilter()
        self._energy = {source: EnergyTrack() for source in SPEAKER_LABELS}
        self._terms = prompt_terms(TRANSCRIPTION_PROMPT)
        self._frame_seq = 0  # bumps on every frame; lets deictic utterances wait for a fresh one
        self._remote_talking = False  # remote VAD: speech_started .. transcription.completed
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
                    if source == "remote":
                        self._remote_talking = True
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    text = getattr(event, "transcript", "").strip()
                    ts = self._speech_start.pop(getattr(event, "item_id", None), None)
                    if source == "remote":
                        self._remote_talking = False
                    if text:
                        transcript = Transcript(
                            text=text, ts=ts if ts is not None else self._elapsed(), speaker=speaker
                        )
                        rejected = self._hallucination_reason(source, transcript)
                        if rejected:
                            await self.events.put(
                                Rejected(transcript.text, transcript.ts, speaker, rejected)
                            )
                            continue
                        if source == "remote":
                            self._echo.note_remote(transcript.ts, transcript.text)
                            await self._commit(transcript)
                        else:
                            self._spawn(self._commit_me(transcript))
                elif event_type == "error":
                    await self._fail(f"{speaker} transcription: {getattr(event, 'error', event)}")
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await self._fail(f"{speaker} transcription: {exc}")

    def _hallucination_reason(self, source: str, transcript: Transcript) -> str | None:
        if not self._energy[source].had_speech(transcript.ts, self._elapsed()):
            peak = self._energy[source].peak(transcript.ts, self._elapsed())
            return f"no speech energy (peak rms {peak:.0f})"
        if looks_like_prompt(transcript.text, self._terms):
            return "prompt vocabulary regurgitated"
        return None

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _commit(self, transcript: Transcript) -> None:
        await self.events.put(transcript)
        self._spawn(self._reason(transcript))

    async def _commit_me(self, transcript: Transcript) -> None:
        # The remote twin of an echoed sentence may finish later (the echo is quieter, so
        # its VAD often closes first). Wait a grace period, and keep waiting while the
        # remote channel is still mid-sentence - an echo can only exist while they talk.
        await asyncio.sleep(HOLD_SECONDS)
        waited = HOLD_SECONDS
        while self._remote_talking and waited < MAX_HOLD_SECONDS:
            await asyncio.sleep(0.2)
            waited += 0.2
        if self._echo.is_echo(transcript.ts, transcript.text):
            await self.events.put(EchoDropped(transcript.text, transcript.ts))
            return
        await self._commit(transcript)

    async def _reason(self, transcript: Transcript) -> None:
        if not self.reasoner:
            return
        pointing = bool(DEICTIC_HINT.search(transcript.text))
        if pointing:
            # The browser grabs a screenshot when it sees the pointing word in this very
            # transcript; give that frame a moment to land so we reason about what the
            # speaker is looking at *now*, not the periodic frame from 10 s ago.
            seq, waited = self._frame_seq, 0.0
            while self._frame_seq == seq and waited < FRESH_FRAME_WAIT:
                await asyncio.sleep(0.1)
                waited += 0.1
        calls = await self.reasoner.process(
            transcript.speaker or "?", transcript.text, transcript.ts, look_closely=pointing
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
        self._energy[source or ""].add(self._elapsed(), rms(audio))
        pcm24 = resample_pcm16(audio)
        await transcriber.conn.input_audio_buffer.append(
            audio=base64.b64encode(pcm24).decode("ascii")
        )

    async def send_frame(self, jpeg_bytes: bytes, reason: str = "manual") -> None:
        del reason
        if not self.reasoner:
            return
        self._last_frame = time.monotonic()
        self._frame_seq += 1
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
