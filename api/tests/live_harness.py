import asyncio
import base64
import io
from typing import Any

from PIL import Image

from app.knowledge.store import store
from app.live.events import EngineEvent
from app.live.session import LiveSessionManager
from app.models import MeetingSession


class FakeWebSocket:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def accept(self) -> None:
        return None

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)

    async def receive_json(self) -> dict[str, Any]:
        return await self.incoming.get()

    async def close(self) -> None:
        self.closed = True

    def payloads(self, event_type: str) -> list[Any]:
        return [event["payload"] for event in self.sent if event["type"] == event_type]


class FakeEngine:
    def __init__(self) -> None:
        self.events: asyncio.Queue[EngineEvent] = asyncio.Queue()
        self.audio: list[tuple[bytes, str | None]] = []
        self.frames: list[tuple[bytes, str]] = []
        self.texts: list[str] = []

    async def start(self, session_id: str) -> None:
        del session_id

    async def send_audio(self, audio: bytes, source: str | None = None) -> None:
        self.audio.append((audio, source))

    async def send_frame(self, jpeg_bytes: bytes, reason: str = "manual") -> None:
        self.frames.append((jpeg_bytes, reason))

    async def send_text(self, text: str) -> None:
        self.texts.append(text)

    async def close(self) -> None:
        return None


def build_manager() -> tuple[LiveSessionManager, FakeWebSocket, FakeEngine]:
    websocket = FakeWebSocket()
    session = MeetingSession()
    manager = LiveSessionManager(websocket, session, store)  # type: ignore[arg-type]
    engine = FakeEngine()
    manager.engine = engine  # type: ignore[assignment]
    manager.frame_wait_seconds = 0.0
    return manager, websocket, engine


def jpeg_bytes(shade: int = 200) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (shade, shade, shade)).save(buffer, format="JPEG")
    return buffer.getvalue()


def jpeg_b64(shade: int = 200) -> str:
    return base64.b64encode(jpeg_bytes(shade)).decode("ascii")


async def wait_for(predicate, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Timed out waiting for condition")
