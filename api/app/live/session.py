import asyncio
import base64
import binascii
import contextlib
import logging
import re
from typing import Any

from fastapi import WebSocket
from rapidfuzz import fuzz
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.conflict import check_conflict
from app.knowledge.store import KnowledgeStore
from app.live.events import (
    EchoDropped,
    EngineStatus,
    IntentResolved,
    Rejected,
    ToolCall,
    Transcript,
)
from app.live.gemini import GeminiLiveEngine
from app.live.mock import MockLiveEngine
from app.live.openai_rt import OpenAIRealtimeEngine
from app.models import (
    Alert,
    Decision,
    Frame,
    GroundedEvent,
    MeetingSession,
    ServerEvent,
    TranscriptEntry,
)
from app.record.store import Recorder

logger = logging.getLogger(__name__)

DEICTIC = re.compile(
    # pointing words
    r"這個|那個|這裡|那裡|這邊|那邊|右邊|左邊|上面|下面|這塊|那塊|這張|那張|這頁|那頁|這行|那行"
    # talking about what is on screen
    r"|螢幕|畫面|這頁|上一頁|下一頁|投影片|簡報|圖表|表格|這張圖|這個圖|柱狀圖|折線圖|截圖"
    # English: only when the pointer is attached to a screen noun, so "this is fine" never fires
    r"|\b(?:this|that|the)\s+(?:one|chart|table|slide|page|graph|diagram|row|column|number|screen)\b"
    r"|\bon\s+(?:the\s+)?screen\b|\b(?:over|right)\s+here\b",
    re.IGNORECASE,
)
# Someone actually committing to something. Evaluating ("先看成本") is not a decision.
COMMIT = re.compile(
    r"決定|採用|就用|就選|就走|定案|拍板|就這樣|敲定|確定|同意|改成|改用|改採|那就|先用|先採"
    r"|\b(?:decide|decided|go with|let's use|we'll use|settle on|approved)\b",
    re.IGNORECASE,
)
# "候選" is deliberately absent: "採用 C，B 留做候選" is a decision *with* a runner-up.
UNDECIDED = re.compile(r"尚未|未定|待定|評估中|考慮中|還沒決定|TBD", re.IGNORECASE)
SAME_MEANING = 85  # rapidfuzz score above which two reasons/constraints are one
MAX_LIST_ITEMS = 6  # reasons/constraints kept per decision list (newest win)
# standalone numbers (850, 1,020) and option letters (A/B/C); "Q4" is neither
DISTINGUISHING = re.compile(r"(?<![A-Za-z])\d[\d,.]*|(?<![A-Za-z0-9])[A-Z](?![A-Za-z0-9])")


def _same_meaning(a: str, b: str) -> bool:
    """Near-duplicate text. Numbers and option letters (A/B/C, 850, 1,020) are facts, so two
    strings that differ in those are never merged no matter how similar the wording is."""
    if set(DISTINGUISHING.findall(a)) != set(DISTINGUISHING.findall(b)):
        return False
    return fuzz.ratio(a, b) >= SAME_MEANING or (
        min(len(a), len(b)) >= 8 and fuzz.partial_ratio(a, b) >= 95
    )


def _extend_unique(target: list[str], items: list[str], cap: int | None = None) -> None:
    for item in items:
        if item and not any(_same_meaning(item, existing) for existing in target):
            target.append(item)
    if cap is not None:
        del target[:-cap]


class LiveSessionManager:
    def __init__(
        self,
        websocket: WebSocket,
        session: MeetingSession,
        knowledge: KnowledgeStore,
    ) -> None:
        self.websocket = websocket
        self.session = session
        self.knowledge = knowledge
        if settings.live_provider == "openai":
            self.engine = OpenAIRealtimeEngine()
        elif settings.live_provider == "gemini":
            self.engine = GeminiLiveEngine()
        else:
            self.engine = MockLiveEngine()
        self.recorder = Recorder(session, settings.record_dir)
        self._started = asyncio.get_running_loop().time()
        self._audio_chunks: dict[str, int] = {}

    def _elapsed(self) -> float:
        return asyncio.get_running_loop().time() - self._started

    async def _emit(self, event_type: str, payload: Any) -> None:
        event = ServerEvent(type=event_type, payload=payload)
        await self.websocket.send_json(event.model_dump(mode="json"))

    async def run(self) -> None:
        await self.websocket.accept()
        reader_task: asyncio.Task[Any] | None = None
        event_task: asyncio.Task[Any] | None = None
        reason = "unknown"
        try:
            await self.engine.start(self.session.id)
            if reasoner := getattr(self.engine, "reasoner", None):
                reasoner.context_provider = self._decision_context
            await self._emit("status", {"status": "connected", "session_id": self.session.id})
            reader_task = asyncio.create_task(self.websocket.receive_json())
            event_task = asyncio.create_task(self.engine.events.get())
            while True:
                done, _ = await asyncio.wait(
                    [reader_task, event_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if reader_task in done:
                    try:
                        message = reader_task.result()
                    except WebSocketDisconnect as exc:
                        reason = f"client disconnected (code={exc.code})"
                        break
                    if await self._handle_client_message(message):
                        reason = "client sent end"
                        break
                    reader_task = asyncio.create_task(self.websocket.receive_json())
                if event_task in done:
                    event = event_task.result()
                    if await self._handle_engine_event(event):
                        reason = f"engine status: {getattr(event, 'detail', None)}"
                        break
                    event_task = asyncio.create_task(self.engine.events.get())
        except Exception as exc:  # we want the reason on disk, then re-raise
            reason = f"server error: {exc!r}"
            logger.exception("live session crashed")
            raise
        finally:
            self.recorder.note(
                "closed",
                {
                    "reason": reason,
                    "elapsed": self._elapsed(),
                    "audio_chunks": self._audio_chunks,
                    "frames": len(self.session.frames),
                },
            )
            for task in (reader_task, event_task):
                if task and not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            await self.engine.close()
            self.recorder.close()
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await self.websocket.close()

    async def _handle_client_message(self, message: dict[str, Any]) -> bool:
        message_type = message.get("type")
        try:
            if message_type == "audio":
                self._audio_chunks[message.get("source") or "?"] = (
                    self._audio_chunks.get(message.get("source") or "?", 0) + 1
                )
                await self.engine.send_audio(
                    base64.b64decode(message["pcm16_b64"], validate=True),
                    source=message.get("source"),
                )
            elif message_type == "frame":
                jpeg_bytes = base64.b64decode(message["jpeg_b64"], validate=True)
                # Always stamp with the session clock: the browser's `ts` is page uptime and
                # would put frames on a different timeline from the utterances.
                frame = Frame(
                    ts=self._elapsed(),
                    jpeg_b64=message["jpeg_b64"],
                    reason=message.get("reason", "manual"),
                )
                self.session.frames.append(frame)
                del self.session.frames[:-200]
                scene = self.recorder.add_frame(frame, jpeg_bytes)
                await self.engine.send_frame(jpeg_bytes)
                await self._emit(
                    "frame_ack", {**frame.model_dump(exclude={"jpeg_b64"}), "scene_seq": scene.seq}
                )
            elif message_type == "text":
                await self.engine.send_text(str(message.get("text", "")))
            elif message_type == "confirm_decision":
                decision = self._update_decision(message["id"], message.get("status", "confirmed"))
                await self._emit("decision", decision.model_dump())
            elif message_type == "ack_alert":
                alert = self._update_alert(message["id"], message.get("status", "acknowledged"))
                await self._emit("alert", alert.model_dump())
            elif message_type == "end":
                await self._emit("status", {"status": "ended"})
                return True
            else:
                await self._emit("error", {"detail": f"Unknown message type: {message_type}"})
        except (KeyError, ValueError, binascii.Error) as exc:
            await self._emit("error", {"detail": str(exc)})
        return False

    async def _handle_engine_event(self, event: Any) -> bool:
        if isinstance(event, Transcript):
            transcript = TranscriptEntry(
                id=event.id, ts=event.ts, speaker=event.speaker, text=event.text
            )
            self.session.transcript.append(transcript)
            self.recorder.add_utterance(
                id=transcript.id, ts=transcript.ts, speaker=transcript.speaker, text=transcript.text
            )
            await self._emit("transcript", transcript.model_dump())
        elif isinstance(event, ToolCall):
            await self._handle_tool_call(event)
        elif isinstance(event, IntentResolved):
            self.recorder.resolve(event.utterance_id, event.tools)
            await self._emit(
                "utterance_resolved", {"utterance_id": event.utterance_id, "tools": event.tools}
            )
        elif isinstance(event, EchoDropped):
            self.recorder.note("echo_dropped", {"ts": event.ts, "text": event.text})
            await self._emit("status", {"status": "echo_dropped", "detail": event.text})
        elif isinstance(event, Rejected):
            self.recorder.note(
                "stt_rejected",
                {"ts": event.ts, "speaker": event.speaker, "text": event.text, "why": event.reason},
            )
            await self._emit(
                "status", {"status": "stt_rejected", "detail": f"{event.reason}: {event.text[:60]}"}
            )
        elif isinstance(event, EngineStatus):
            await self._emit("status", {"status": event.status, "detail": event.detail})
            return event.status in {"script_complete", "disconnected"}
        return False

    def _utterance(self, utterance_id: str | None) -> TranscriptEntry | None:
        if utterance_id:
            for entry in reversed(self.session.transcript):
                if entry.id == utterance_id:
                    return entry
        return self.session.transcript[-1] if self.session.transcript else None

    async def _handle_tool_call(self, event: ToolCall) -> None:
        if event.name == "create_anchor":
            source = self._utterance(event.utterance_id)
            # Grounding is only meaningful when someone actually pointed at something
            # ("這個/右邊/螢幕上…") and there is a frame to point at. The model's own
            # confidence is not a usable signal here (it reports >0.85 for merely naming a
            # thing that is also on screen), so the pointing word is a hard requirement;
            # everything else is still attached to the page via scenes.
            needs_frame = not isinstance(self.engine, MockLiveEngine)
            if (needs_frame and not self.session.frames) or not source:
                return
            if not DEICTIC.search(source.text):
                return
            target = str(event.args.get("target", ""))
            grounded = GroundedEvent(
                ts=event.ts or self._elapsed(),
                speaker=event.args.get("speaker") or source.speaker,
                utterance=source.text,
                target=target,
                observation=str(event.args.get("observation", "")),
                frame_id=self.session.frames[-1].id if self.session.frames else None,
                confidence=float(event.args.get("confidence", 0.0)),
            )
            self.session.grounded_events.append(grounded)
            self.recorder.link(event.utterance_id, event.name, grounded.id)
            await self._emit("grounded_event", grounded.model_dump())
        elif event.name == "propose_decision":
            source = self._utterance(event.utterance_id)
            chosen = str(event.args.get("chosen", ""))
            real_engine = not isinstance(self.engine, MockLiveEngine)
            # Same lesson as anchors: the model proposes "decisions" for evaluation talk.
            # Require a commitment word in the utterance and a definite choice.
            if real_engine and (
                not source or not COMMIT.search(source.text) or UNDECIDED.search(chosen)
            ):
                return
            proposal = Decision(
                ts=event.ts or self._elapsed(),
                topic=str(event.args.get("topic", "")),
                chosen=chosen,
                alternatives=list(event.args.get("alternatives", [])),
                reasons_for=list(event.args.get("reasons_for", [])),
                reasons_against=list(event.args.get("reasons_against", [])),
                constraints=list(event.args.get("constraints", [])),
            )
            decision, choice_changed = self._merge_decision(proposal)
            _extend_unique(
                self.session.decision_state.options_under_comparison,
                [decision.chosen, *decision.alternatives],
            )
            _extend_unique(self.session.decision_state.constraints, decision.constraints)
            alerts: list[Alert] = []
            if choice_changed:
                # Only a new or changed choice can create a new conflict; re-checking the
                # same choice every time someone restates it just stacks identical alerts.
                hits = self.knowledge.search(f"{decision.topic} {decision.chosen}")
                alerts = self._merge_alerts(decision, await check_conflict(decision, hits))
            self.recorder.link(event.utterance_id, event.name, decision.id)
            for alert in alerts:
                self.recorder.link(event.utterance_id, "notify_speaker", alert.id)
            await self._emit("decision", decision.model_dump())
            for alert in alerts:
                await self._emit("alert", alert.model_dump())
        elif event.name == "notify_speaker":
            kind = event.args.get("kind", "info")
            if kind not in {"conflict", "slide_mismatch", "info"}:
                kind = "info"
            alert = Alert(
                ts=event.ts or self._elapsed(),
                kind=kind,
                title="Silent Assist" if kind != "slide_mismatch" else "Slide Mismatch",
                detail=str(event.args.get("message", "")),
            )
            self.session.alerts.append(alert)
            self.recorder.link(event.utterance_id, event.name, alert.id)
            await self._emit("alert", alert.model_dump())
        elif event.name == "capture_context":
            self.recorder.link(event.utterance_id, event.name, "")
            await self._emit(
                "status",
                {
                    "status": "request_frame",
                    "request_frame": True,
                    "reason": event.args.get("reason"),
                },
            )

    def _decision_context(self) -> str:
        lines = [
            f"- decision[{d.status}] topic={d.topic!r} chosen={d.chosen!r}"
            for d in self.session.decision_state.decisions
        ]
        lines += [
            f"- alert[{a.kind}/{a.status}] {a.detail}"
            for a in self.session.alerts
            if a.status == "open"
        ]
        return "\n".join(lines)

    def _merge_decision(self, proposal: Decision) -> tuple[Decision, bool]:
        """Fold a proposal into an existing candidate on the same topic instead of
        stacking near-duplicates; the latest wording wins, lists are unioned by meaning.
        Returns (decision, whether the chosen option is new or changed)."""
        for existing in self.session.decision_state.decisions:
            if existing.status != "candidate":
                continue
            same_topic = fuzz.token_set_ratio(existing.topic, proposal.topic) >= 70
            same_choice = fuzz.partial_ratio(existing.chosen, proposal.chosen) >= 70
            if same_topic or same_choice:
                # Same option only if the wording is close *and* no fact (letter/number) differs.
                changed = not (
                    same_choice
                    and set(DISTINGUISHING.findall(existing.chosen))
                    == set(DISTINGUISHING.findall(proposal.chosen))
                )
                existing.chosen = proposal.chosen
                existing.ts = proposal.ts
                for field in ("alternatives", "reasons_for", "reasons_against", "constraints"):
                    _extend_unique(
                        getattr(existing, field), getattr(proposal, field), cap=MAX_LIST_ITEMS
                    )
                existing.alternatives = [
                    a for a in existing.alternatives if not _same_meaning(a, existing.chosen)
                ]
                return existing, changed
        self.session.decision_state.decisions.append(proposal)
        return proposal, True

    def _merge_alerts(self, decision: Decision, fresh: list[Alert]) -> list[Alert]:
        """One open conflict per (decision, source): update its text instead of adding."""
        kept: list[Alert] = []
        for alert in fresh:
            existing = next(
                (
                    a
                    for a in self.session.alerts
                    if a.kind == "conflict"
                    and a.status == "open"
                    and a.decision_id == decision.id
                    and a.source == alert.source
                ),
                None,
            )
            if existing:
                existing.detail, existing.title, existing.ts = alert.detail, alert.title, alert.ts
                kept.append(existing)
            else:
                self.session.alerts.append(alert)
                decision.conflicts.append(alert.id)
                kept.append(alert)
        return kept

    def _update_decision(self, decision_id: str, status: str) -> Decision:
        if status not in {"candidate", "confirmed", "rejected"}:
            raise ValueError(f"Invalid decision status: {status}")
        for decision in self.session.decision_state.decisions:
            if decision.id == decision_id:
                decision.status = status
                return decision
        raise ValueError(f"Decision not found: {decision_id}")

    def _update_alert(self, alert_id: str, status: str) -> Alert:
        if status not in {"open", "acknowledged", "dismissed"}:
            raise ValueError(f"Invalid alert status: {status}")
        for alert in self.session.alerts:
            if alert.id == alert_id:
                alert.status = status
                return alert
        raise ValueError(f"Alert not found: {alert_id}")
