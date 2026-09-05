import asyncio
import base64
import contextlib
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
from app.live.hallucination import EnergyTrack, looks_like_prompt, rms
from app.live.reasoner import Reasoner

SPEAKER_LABELS = {"me": "我", "remote": "與會者"}
NOISE_REDUCTION = {"me": "near_field", "remote": "far_field"}
# The prompt only describes the recording setting (OpenAI's docs: "Use prompt to describe
# the recording or its setting"). No example sentences, no output instructions, no
# vocabulary list: everything that looks like speech in here has come back out as a fake
# transcript at some point (see hallucination.py). Domain terms belong in `keywords`,
# which gpt-4o-mini-transcribe does not support, so we go without.
TRANSCRIPTION_PROMPT = "台灣繁體中文的產品會議對話，夾雜英文與技術詞彙。"


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
        self._remote_talking = False  # remote VAD: speech_started .. transcription.completed
        self._pending: set[asyncio.Task[None]] = set()
        self._started = time.monotonic()
        self._buffer_start: dict[str, float] = {}  # source -> elapsed at first audio chunk
        self._speech_start: dict[str, float] = {}  # item_id -> elapsed at speech start
        self._speech_end: dict[str, float] = {}  # item_id -> elapsed at speech stop
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
                elif event_type == "input_audio_buffer.speech_stopped":
                    end_ms = getattr(event, "audio_end_ms", None)
                    item_id = getattr(event, "item_id", None)
                    if end_ms is not None and item_id:
                        self._speech_end[item_id] = (
                            self._buffer_start.get(source, self._elapsed()) + end_ms / 1000
                        )
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    text = getattr(event, "transcript", "").strip()
                    item_id = getattr(event, "item_id", None)
                    ts = self._speech_start.pop(item_id, None)
                    ended = self._speech_end.pop(item_id, None)
                    if source == "remote":
                        self._remote_talking = False
                    if text:
                        # [ts, ended] is the real speech span on the session clock; the
                        # transcript itself arrives seconds later and must not be used as
                        # the time the words were said.
                        transcript = Transcript(
                            text=text,
                            ts=ts if ts is not None else self._elapsed(),
                            speaker=speaker,
                            ended=ended if ended is not None else self._elapsed(),
                        )
                        transcript.peak_rms = self._energy[source].peak(
                            transcript.ts, transcript.ended or self._elapsed()
                        )
                        # The only thing we refuse is the prompt itself coming back as
                        # speech. Energy / vocabulary gates were removed: they rejected
                        # real sentences (see hallucination.py). peak_rms is recorded so
                        # a genuine silence hallucination can be diagnosed, not guessed.
                        if looks_like_prompt(text, TRANSCRIPTION_PROMPT):
                            await self.events.put(
                                Rejected(text, transcript.ts, speaker, "prompt text echoed back")
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
        calls = await self.reasoner.process(
            transcript.speaker or "?", transcript.text, transcript.ts, ended=transcript.ended
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

    async def send_frame(
        self, jpeg_bytes: bytes, frame_id: str | None = None, ts: float | None = None
    ) -> None:
        if not self.reasoner:
            return
        self.reasoner.set_frame(ts if ts is not None else self._elapsed(), jpeg_bytes, frame_id)

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
