"""Realtime STT clients under test. Each streams 16 kHz PCM16 at real-time pace and
records when partial / final transcripts arrive relative to speech start / speech end.

All providers use their *server-side automatic VAD* so final latency is comparable;
vocabulary biasing is given to every provider via its native mechanism.
"""

import asyncio
import base64
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types as gtypes
from openai import AsyncOpenAI

from app.config import settings
from app.live.audio import resample_pcm16

RATE = 16_000
CHUNK_BYTES = RATE // 10 * 2  # 100 ms
TAIL_SILENCE_S = 1.5
FINAL_WAIT_S = 12.0

PROMPT = "台灣繁體中文的產品與工程會議對話，夾雜英文技術詞彙。請以繁體中文輸出。"


@dataclass
class SttResult:
    provider: str
    transcript: str = ""
    partials: list[str] = field(default_factory=list)
    first_partial_ms: float | None = None
    final_ms: float | None = None
    error: str | None = None
    finals: int = 0


class _Clock:
    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.speech_start: float | None = None
        self.speech_end: float | None = None

    def now(self) -> float:
        return time.monotonic()


async def _stream(send_chunk: Any, pcm: bytes, clock: _Clock, *, tail: bool = True) -> None:
    silence = b"\x00" * int(RATE * TAIL_SILENCE_S) * 2
    clock.speech_start = clock.now()
    for offset in range(0, len(pcm), CHUNK_BYTES):
        await send_chunk(pcm[offset : offset + CHUNK_BYTES])
        await asyncio.sleep(0.1)
    clock.speech_end = clock.now()
    if not tail:
        return
    for offset in range(0, len(silence), CHUNK_BYTES):
        await send_chunk(silence[offset : offset + CHUNK_BYTES])
        await asyncio.sleep(0.1)


def _mark_partial(result: SttResult, clock: _Clock, text: str) -> None:
    if text:
        result.partials.append(text)
        if result.first_partial_ms is None and clock.speech_start is not None:
            result.first_partial_ms = (clock.now() - clock.speech_start) * 1000


def _mark_final(result: SttResult, clock: _Clock, text: str) -> None:
    result.finals += 1
    result.transcript = (result.transcript + text).strip()
    if clock.speech_end is not None:
        result.final_ms = (clock.now() - clock.speech_end) * 1000


# --- OpenAI (transcription session) ------------------------------------------


async def openai_transcribe(model: str, pcm: bytes, vocabulary: list[str]) -> SttResult:
    result = SttResult(provider=model)
    clock = _Clock()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    transcription: dict[str, Any] = {"model": model}
    # gpt-live-transcribe rejects server turn detection: the client must commit each turn.
    client_commit = model == "gpt-live-transcribe"
    if client_commit:
        transcription |= {
            "prompt": PROMPT,
            "keywords": vocabulary[:100],
            "languages": ["zh-tw", "en"],
        }
    else:
        transcription |= {
            "language": "zh",
            "prompt": PROMPT + " 常見詞彙：" + "、".join(vocabulary[:60]),
        }
    manager = client.realtime.connect(extra_query={"intent": "transcription"})
    done = asyncio.Event()
    try:
        conn = await manager.__aenter__()
        await conn.session.update(
            session={
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": 24_000},
                        "transcription": transcription,
                        "turn_detection": None if client_commit else {"type": "server_vad"},
                    }
                },
            }
        )

        async def listen() -> None:
            async for event in conn:
                kind = getattr(event, "type", "")
                if kind == "conversation.item.input_audio_transcription.delta":
                    _mark_partial(result, clock, getattr(event, "delta", ""))
                elif kind == "conversation.item.input_audio_transcription.completed":
                    _mark_final(result, clock, getattr(event, "transcript", ""))
                    done.set()
                elif kind == "error":
                    result.error = str(getattr(event, "error", event))
                    done.set()

        listener = asyncio.create_task(listen())

        async def send(chunk: bytes) -> None:
            await conn.input_audio_buffer.append(
                audio=base64.b64encode(resample_pcm16(chunk)).decode("ascii")
            )

        await _stream(send, pcm, clock, tail=not client_commit)
        if client_commit:
            clock.speech_end = clock.now()  # commit == client-side end-of-speech signal
            await conn.input_audio_buffer.commit()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(done.wait(), timeout=FINAL_WAIT_S)
        await asyncio.sleep(0.8)  # catch a trailing second final if the turn was split
        listener.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listener
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        with contextlib.suppress(Exception):
            await manager.__aexit__(None, None, None)
    return result


# --- Gemini (gemini-3.5-transcribe-live) --------------------------------------


async def gemini_transcribe(model: str, pcm: bytes, vocabulary: list[str]) -> SttResult:
    result = SttResult(provider=model)
    clock = _Clock()
    client = genai.Client(api_key=settings.gemini_api_key)
    config = gtypes.LiveConnectConfig(
        response_modalities=["TEXT"],
        input_audio_transcription=gtypes.AudioTranscriptionConfig(
            language_codes=[],  # auto; Gemini lists cmn-Hans-CN only, no Traditional Mandarin code
            custom_vocabulary=vocabulary[:100],
        ),
    )
    done = asyncio.Event()
    try:
        async with client.aio.live.connect(model=model, config=config) as session:

            async def listen() -> None:
                async for response in session.receive():
                    content = response.server_content
                    if not content:
                        continue
                    if (
                        content.interim_input_transcription
                        and content.interim_input_transcription.text
                    ):
                        _mark_partial(result, clock, content.interim_input_transcription.text)
                    if content.input_transcription and content.input_transcription.text:
                        _mark_final(result, clock, content.input_transcription.text)
                        done.set()

            listener = asyncio.create_task(listen())

            async def send(chunk: bytes) -> None:
                await session.send_realtime_input(
                    audio=gtypes.Blob(data=chunk, mime_type=f"audio/pcm;rate={RATE}")
                )

            await _stream(send, pcm, clock)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(done.wait(), timeout=FINAL_WAIT_S)
            await asyncio.sleep(0.8)
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
    return result


PROVIDERS = {
    "gemini-3.5-transcribe-live": gemini_transcribe,
    "gpt-live-transcribe": openai_transcribe,
    "gpt-4o-mini-transcribe": openai_transcribe,
}


async def transcribe(provider: str, pcm: bytes, vocabulary: list[str]) -> SttResult:
    return await PROVIDERS[provider](provider, pcm, vocabulary)
