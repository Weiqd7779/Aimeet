"""In-meeting reasoning over labelled utterances via the Responses API.

Stateless per call: each utterance is sent with a rolling window of recent dialogue,
the latest shared frame and the current decision list, so the model revises existing
decisions instead of re-proposing them. Failures affect one utterance only.
"""

import asyncio
import base64
import json
import logging
from collections import deque
from collections.abc import Callable
from typing import Any

from openai import AsyncOpenAI

from app.live.events import ToolCall
from app.live.prompt import SYSTEM_INSTRUCTION
from app.live.tools import openai_tools

logger = logging.getLogger(__name__)

CONTEXT_TURNS = 12
FRAME_MAX_AGE_S = 90.0


class Reasoner:
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model
        self._history: deque[tuple[str, str]] = deque(maxlen=CONTEXT_TURNS)
        self._frame: tuple[float, str] | None = None  # (ts, data-url)
        self._lock = asyncio.Lock()
        self.context_provider: Callable[[], str] | None = None

    def set_frame(self, ts: float, jpeg_bytes: bytes) -> None:
        data = base64.b64encode(jpeg_bytes).decode("ascii")
        self._frame = (ts, f"data:image/jpeg;base64,{data}")

    def _build_input(self, speaker: str, text: str, ts: float) -> list[dict[str, Any]]:
        history = "\n".join(f"[{s}] {t}" for s, t in self._history) or "（無）"
        state = self.context_provider() if self.context_provider else ""
        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": (
                    f"目前已記錄的決策與提醒（若新發言只是修改其中一項，請用相同 topic 重新呼叫 propose_decision）：\n"
                    f"{state or '（無）'}\n\n"
                    f"最近對話：\n{history}\n\n"
                    f"最新發言（請只針對這一句判斷是否需要呼叫工具）：\n[{speaker}] {text}"
                ),
            }
        ]
        if self._frame and ts - self._frame[0] <= FRAME_MAX_AGE_S:
            content.append({"type": "input_image", "image_url": self._frame[1], "detail": "low"})
        return [{"role": "user", "content": content}]

    async def process(self, speaker: str, text: str, ts: float) -> list[ToolCall]:
        """Return the tool calls the model wants for this utterance (possibly none)."""
        async with self._lock:
            payload = self._build_input(speaker, text, ts)
            self._history.append((speaker, text))
            try:
                response = await self._client.responses.create(
                    model=self._model,
                    instructions=SYSTEM_INSTRUCTION,
                    input=payload,
                    tools=openai_tools(),
                    tool_choice="auto",
                    parallel_tool_calls=True,
                )
            except Exception:
                logger.exception("reasoning call failed for utterance")
                return []
        calls: list[ToolCall] = []
        for item in response.output:
            if getattr(item, "type", "") != "function_call":
                continue
            try:
                args = json.loads(item.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(name=item.name, args=args, id=item.call_id, ts=ts))
        return calls
