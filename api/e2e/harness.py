"""Drive the live API the way a browser would: two speaker channels + frames over WS.

Speech is synthesised with OpenAI TTS (cached on disk), streamed at real-time pace per
speaker, and every server event is collected for assertion.
"""

import asyncio
import base64
import contextlib
import hashlib
import io
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import websockets
from openai import AsyncOpenAI
from PIL import Image, ImageDraw, ImageFont

from app.live.audio import resample_pcm16

API_URL = os.environ.get("AIMEET_API_URL", "http://localhost:8000").rstrip("/")
CACHE_DIR = Path(__file__).with_name(".cache")
VOICES = {"me": "alloy", "remote": "onyx"}
RATE = 16_000
CHUNK_BYTES = RATE // 10 * 2  # 100 ms of PCM16


@dataclass
class Step:
    at: float
    speaker: str | None = None
    say: str | list[str] | None = None
    frame: str | None = None
    text: str | None = None
    pause: float = 0.4  # gap between `say` list items, seconds


@dataclass
class Scenario:
    id: str
    title: str
    steps: list[Step]
    expect: dict[str, Any]
    settle_seconds: float = 8.0
    synthesize: bool = False

    @classmethod
    def load(cls, path: Path) -> "Scenario":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            id=data["id"],
            title=data["title"],
            steps=[Step(**step) for step in data["steps"]],
            expect=data.get("expect", {}),
            settle_seconds=float(data.get("settle_seconds", 8.0)),
            synthesize=bool(data.get("synthesize", False)),
        )


@dataclass
class RunResult:
    scenario: Scenario
    events: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] | None = None
    record: dict[str, Any] | None = None
    duration: float = 0.0

    def payloads(self, event_type: str) -> list[dict[str, Any]]:
        return [event["payload"] for event in self.events if event["type"] == event_type]

    @property
    def transcripts(self) -> list[dict[str, Any]]:
        return self.payloads("transcript")


def _client() -> AsyncOpenAI:
    from app.config import settings

    return AsyncOpenAI(api_key=settings.openai_api_key)


async def tts(text: str, speaker: str) -> bytes:
    """Return 16 kHz PCM16 for `text`, cached by content."""
    CACHE_DIR.mkdir(exist_ok=True)
    voice = VOICES[speaker]
    key = hashlib.sha1(f"{voice}:{text}".encode()).hexdigest()
    cached = CACHE_DIR / f"{key}.pcm"
    if cached.exists():
        return cached.read_bytes()
    response = await _client().audio.speech.create(
        model="gpt-4o-mini-tts", voice=voice, input=text, response_format="pcm"
    )
    pcm16k = _trim(resample_pcm16(await response.aread(), source_rate=24_000, target_rate=RATE))
    cached.write_bytes(pcm16k)
    return pcm16k


def _trim(pcm: bytes, threshold: int = 300) -> bytes:
    """Strip leading/trailing silence so scripted pauses are the pauses we asked for."""
    samples = np.frombuffer(pcm, dtype="<i2")
    loud = np.flatnonzero(np.abs(samples) > threshold)
    if not len(loud):
        return pcm
    return samples[loud[0] : loud[-1] + 1].tobytes()


def silence(seconds: float) -> bytes:
    return np.zeros(int(RATE * seconds), dtype="<i2").tobytes()


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for candidate in ("msjh.ttc", "C:/Windows/Fonts/msjh.ttc", "NotoSansCJK-Regular.ttc"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_frame(kind: str) -> bytes:
    """Synthesise a slide-like JPEG. `chart` = table on the left, bar chart on the right."""
    image = Image.new("RGB", (1280, 720), "white")
    draw = ImageDraw.Draw(image)
    title, body = _font(40), _font(26)
    draw.text((60, 40), "Q4 Prototype 評估", fill="black", font=title)
    if kind == "chart":
        rows = [("Prototype A", "NT$780"), ("Prototype B", "NT$1,020"), ("Prototype C", "NT$830")]
        for index, (name, cost) in enumerate(rows):
            y = 160 + index * 60
            draw.rectangle((60, y, 560, y + 50), outline="gray")
            draw.text((80, y + 10), name, fill="black", font=body)
            draw.text((400, y + 10), cost, fill="black", font=body)
        draw.text((700, 120), "使用者滿意度", fill="black", font=body)
        for index, (label, height) in enumerate([("A", 220), ("B", 380), ("C", 260)]):
            x = 720 + index * 150
            draw.rectangle((x, 600 - height, x + 90, 600), fill="#2c7be5")
            draw.text((x + 30, 620), label, fill="black", font=body)
    else:
        draw.text((60, 200), kind, fill="black", font=body)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


def _audio_message(speaker: str, chunk: bytes) -> str:
    return json.dumps(
        {"type": "audio", "source": speaker, "pcm16_b64": base64.b64encode(chunk).decode("ascii")}
    )


async def _stream_audio(ws: Any, speaker: str, pcm: bytes) -> None:
    for offset in range(0, len(pcm), CHUNK_BYTES):
        await ws.send(_audio_message(speaker, pcm[offset : offset + CHUNK_BYTES]))
        await asyncio.sleep(0.1)


async def _room_tone(ws: Any, speaker: str, speaking: asyncio.Lock) -> None:
    """Like a real microphone, keep sending silence whenever this speaker is not talking.
    Server VAD needs the trailing silence to close a turn, and `audio_start_ms` only tracks
    wall time if the buffer is continuous."""
    chunk = silence(0.1)
    with contextlib.suppress(asyncio.CancelledError, websockets.ConnectionClosed):
        while True:
            if not speaking.locked():
                await ws.send(_audio_message(speaker, chunk))
            await asyncio.sleep(0.1)


async def _utterance_pcm(step: Step) -> bytes:
    """One or more clips; list items are joined with a short (sub-VAD) pause."""
    parts = step.say if isinstance(step.say, list) else [step.say or ""]
    clips = [await tts(part, step.speaker or "me") for part in parts]
    joined = silence(step.pause).join(clips)
    return joined + silence(1.2)  # tail so server VAD closes the turn


async def _run_step(ws: Any, step: Step) -> None:
    if step.say is not None and step.speaker:
        await _stream_audio(ws, step.speaker, await _utterance_pcm(step))
    elif step.frame:
        jpeg = render_frame(step.frame)
        await ws.send(
            json.dumps(
                {
                    "type": "frame",
                    "jpeg_b64": base64.b64encode(jpeg).decode("ascii"),
                    "reason": "manual",
                    "ts": step.at,
                }
            )
        )
    elif step.text:
        await ws.send(json.dumps({"type": "text", "text": step.text}))


async def _collect(ws: Any, sink: list[dict[str, Any]]) -> None:
    try:
        async for raw in ws:
            sink.append(json.loads(raw))
    except websockets.ConnectionClosed:
        return


async def run_scenario(scenario: Scenario) -> RunResult:
    started = time.monotonic()
    result = RunResult(scenario=scenario)
    async with httpx.AsyncClient(base_url=API_URL, timeout=120) as http:
        health = (await http.get("/health")).json()
        if health.get("live_provider") != "openai":
            raise RuntimeError(f"API must run with LIVE_PROVIDER=openai, got {health}")
        session_id = (await http.post("/sessions")).json()["id"]
        ws_url = f"{API_URL.replace('http', 'ws', 1)}/ws/live/{session_id}"
        async with websockets.connect(ws_url, max_size=None) as ws:
            collector = asyncio.create_task(_collect(ws, result.events))
            deadline = time.monotonic() + 20
            while not any(
                e["type"] == "status" and e["payload"].get("status") == "connected"
                for e in result.events
            ):
                if collector.done() or time.monotonic() > deadline:
                    raise RuntimeError(
                        f"live session never reached 'connected' (events={result.events})"
                    )
                await asyncio.sleep(0.05)

            # A real person cannot talk over themselves: serialise steps per speaker channel.
            locks = {speaker: asyncio.Lock() for speaker in VOICES}
            room_tone = [
                asyncio.create_task(_room_tone(ws, speaker, lock))
                for speaker, lock in locks.items()
            ]

            async def scheduled(step: Step) -> None:
                await asyncio.sleep(step.at)
                if step.speaker:
                    async with locks[step.speaker]:
                        await _run_step(ws, step)
                else:
                    await _run_step(ws, step)

            try:
                await asyncio.gather(*(scheduled(step) for step in scenario.steps))
                await asyncio.sleep(scenario.settle_seconds)
                for task in room_tone:
                    task.cancel()
                await ws.send(json.dumps({"type": "end"}))
                # wait for the server to finish (it closes the socket after persisting)
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(collector, timeout=15)
            except websockets.ConnectionClosed as exc:
                statuses = [e["payload"] for e in result.events if e["type"] == "status"]
                print(
                    f"    ! server closed the session early ({exc}); last status: {statuses[-1:]}"
                )
            for task in room_tone:
                task.cancel()
            collector.cancel()
        record = await http.get(f"/sessions/{session_id}/record")
        if record.status_code == 200:
            result.record = record.json()
        if scenario.synthesize:
            response = await http.post(f"/sessions/{session_id}/synthesize")
            response.raise_for_status()
            result.report = response.json()
    result.duration = time.monotonic() - started
    return result
