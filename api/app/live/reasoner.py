"""In-meeting reasoning over labelled utterances via the Responses API.

Two steps per utterance, both run after the transcript is complete (nothing here is
real-time; anchors may appear a few seconds after the words):

A. Listen (text only). Given recent dialogue + current decisions/anchors, decide which
   tools this utterance needs. If it points at something ("這個指甲剪", "右邊那張表"),
   the model calls `look_at_screen(object)` naming the thing *as the speaker called it*.
B. Look (vision, only when A asked). Frames captured during the utterance's speech span
   [start, end] are fetched from the frame timeline and shown together; the model says
   which frame shows the named object and where (`create_anchor` with `frame_index`).
   If none of them shows it, the search widens backwards (people lift things before they
   speak), then gives up - no anchor is better than a wrong one.

Frames and speech share the session clock (server-stamped), so "what was on screen while
this was said" is a lookup, not a guess.
"""

import asyncio
import base64
import json
import logging
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from app.live.deictic import DEICTIC
from app.live.events import ToolCall
from app.live.prompt import LOOK_INSTRUCTION, SYSTEM_INSTRUCTION
from app.live.tools import look_tools, openai_tools

logger = logging.getLogger(__name__)

CONTEXT_TURNS = 12
FRAME_HISTORY = 120  # ~4 min at one frame / 2 s
MAX_CANDIDATE_FRAMES = 3
SPAN_BEFORE_S = 1.5  # people lift the object slightly before they start talking
SPAN_AFTER_S = 1.0
LOOKBACK_S = 10.0  # second attempt: the object may have been shown just before the sentence
LOOK_TOOL = "look_at_screen"


_POINTED = re.compile(
    r"(?:這個|那個|這張|那張|這塊|那塊|右邊的?|左邊的?|上面的?|下面的?|這頁|那頁)+是?"
    r"(?!是|有|的)([\u4e00-\u9fffA-Za-z0-9 ]{1,8}?)(?:顯示|是|有|的|，|,|。|$)"
)


def _pointed_object(text: str) -> str:
    """Best-effort noun after the pointer: 「右邊這塊圖表顯示…」 -> 圖表. Falls back to a
    generic label; the vision step decides what is actually there."""
    match = _POINTED.search(text)
    noun = match.group(1).strip() if match else ""
    return noun or "說話者指的東西"


@dataclass
class FrameRef:
    ts: float
    frame_id: str | None
    data_url: str


class Reasoner:
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model
        self._history: deque[tuple[str, str]] = deque(maxlen=CONTEXT_TURNS)
        self._frames: deque[FrameRef] = deque(maxlen=FRAME_HISTORY)
        self._lock = asyncio.Lock()
        self.context_provider: Callable[[], str] | None = None

    # --- frame timeline ------------------------------------------------------

    def set_frame(self, ts: float, jpeg_bytes: bytes, frame_id: str | None = None) -> None:
        data = base64.b64encode(jpeg_bytes).decode("ascii")
        self._frames.append(FrameRef(ts, frame_id, f"data:image/jpeg;base64,{data}"))

    def frames_between(self, start: float, end: float) -> list[FrameRef]:
        span = [f for f in self._frames if start <= f.ts <= end]
        if len(span) > MAX_CANDIDATE_FRAMES:
            span = [span[0], span[len(span) // 2], span[-1]]  # cover the whole span
        return span

    # --- step A: listen -------------------------------------------------------

    def _listen_input(self, speaker: str, text: str) -> list[dict[str, Any]]:
        history = "\n".join(f"[{s}] {t}" for s, t in self._history) or "（無）"
        state = self.context_provider() if self.context_provider else ""
        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "目前已記錄的狀態（若新發言只是修改其中一項，請用相同 topic / 相同物件重新呼叫）：\n"
                            f"{state or '（無）'}\n\n"
                            f"最近對話：\n{history}\n\n"
                            f"最新發言（請只針對這一句判斷是否需要呼叫工具）：\n[{speaker}] {text}"
                        ),
                    }
                ],
            }
        ]

    async def _call(
        self, instructions: str, payload: list, tools: list
    ) -> list[tuple[str, dict, str]]:
        try:
            response = await self._client.responses.create(
                model=self._model,
                instructions=instructions,
                input=payload,
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=True,
            )
        except Exception:
            logger.exception("reasoning call failed")
            return []
        calls = []
        for item in response.output:
            if getattr(item, "type", "") != "function_call":
                continue
            try:
                args = json.loads(item.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append((item.name, args, item.call_id))
        return calls

    # --- step B: look ---------------------------------------------------------

    def _look_input(
        self, speaker: str, text: str, target: str, ts: float, frames: list[FrameRef]
    ) -> list[dict[str, Any]]:
        listing = "、".join(f"畫面 {i + 1}=開口後 {f.ts - ts:+.1f}s" for i, f in enumerate(frames))
        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": (
                    f"發言：[{speaker}] {text}\n"
                    f"說話者所指的東西：「{target}」\n"
                    f"以下 {len(frames)} 張是這句話說出期間的畫面（{listing}）。"
                    "找出哪一張看得到「" + target + "」，用 create_anchor 回報；"
                    "若每一張都沒有，呼叫 not_visible。"
                ),
            }
        ]
        for index, frame in enumerate(frames):
            content.append({"type": "input_text", "text": f"畫面 {index + 1}："})
            content.append({"type": "input_image", "image_url": frame.data_url, "detail": "high"})
        return [{"role": "user", "content": content}]

    async def _look(
        self, speaker: str, text: str, target: str, ts: float, ended: float
    ) -> tuple[dict, str] | None:
        """Return (create_anchor args incl. frame_id, call_id) or None if not visible."""
        windows = [
            (ts - SPAN_BEFORE_S, ended + SPAN_AFTER_S),
            (ts - SPAN_BEFORE_S - LOOKBACK_S, ts - SPAN_BEFORE_S),
        ]
        for start, end in windows:
            frames = self.frames_between(start, end)
            if not frames:
                continue
            for name, args, call_id in await self._call(
                LOOK_INSTRUCTION, self._look_input(speaker, text, target, ts, frames), look_tools()
            ):
                if name != "create_anchor":
                    continue
                index = args.get("frame_index")
                chosen = (
                    frames[index - 1]
                    if isinstance(index, int) and 1 <= index <= len(frames)
                    else frames[-1]
                )
                args["frame_id"] = chosen.frame_id
                args["frame_ts"] = chosen.ts
                args.setdefault("target", target)
                return args, call_id
        return None

    # --- entry point ----------------------------------------------------------

    async def process(
        self, speaker: str, text: str, ts: float, *, ended: float | None = None
    ) -> list[ToolCall]:
        """Return the tool calls for this utterance (possibly none)."""
        async with self._lock:
            payload = self._listen_input(speaker, text)
            self._history.append((speaker, text))
            heard = await self._call(SYSTEM_INSTRUCTION, payload, openai_tools())

        # A pointing word is decisive: if the model "heard" the sentence as data talk
        # (「右邊這塊圖表顯示 B 最高」) and skipped look_at_screen, look anyway. The vision
        # step can still answer not_visible, so this only costs one image call.
        if DEICTIC.search(text) and not any(name == LOOK_TOOL for name, _, _ in heard):
            heard.append(
                (LOOK_TOOL, {"object": _pointed_object(text), "refers_to": None, "about": ""}, None)
            )

        calls: list[ToolCall] = []
        for name, args, call_id in heard:
            if name == LOOK_TOOL:
                target = str(args.get("object", "")).strip()
                if not target:
                    continue
                about = str(args.get("about") or "").strip()
                refers_to = args.get("refers_to") or None
                if refers_to:
                    # Same thing as an existing anchor: no need to look again, just attach
                    # what was said about it. The session double-checks the reference.
                    calls.append(
                        ToolCall(
                            name="update_anchor",
                            args={"anchor_id": refers_to, "object": target, "about": about},
                            id=call_id,
                            ts=ts,
                        )
                    )
                    continue
                found = await self._look(
                    speaker, text, target, ts, ended if ended is not None else ts
                )
                if found:
                    anchor_args, anchor_call_id = found
                    anchor_args.setdefault("speaker", speaker)
                    anchor_args["about"] = about
                    calls.append(
                        ToolCall(name="create_anchor", args=anchor_args, id=anchor_call_id, ts=ts)
                    )
                else:
                    calls.append(
                        ToolCall(name="not_visible", args={"object": target}, id=call_id, ts=ts)
                    )
            elif name == "create_anchor":
                continue  # step A must not anchor directly; it has not seen any frame
            else:
                calls.append(ToolCall(name=name, args=args, id=call_id, ts=ts))
        return calls
