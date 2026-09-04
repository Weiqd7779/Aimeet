import asyncio
import base64
import binascii
import contextlib
from typing import Any

from fastapi import WebSocket
from rapidfuzz import fuzz
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.conflict import check_conflict
from app.knowledge.store import KnowledgeStore
from app.live.events import EngineStatus, IntentResolved, ToolCall, Transcript
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

    def _elapsed(self) -> float:
        return asyncio.get_running_loop().time() - self._started

    async def _emit(self, event_type: str, payload: Any) -> None:
        event = ServerEvent(type=event_type, payload=payload)
        await self.websocket.send_json(event.model_dump(mode="json"))

    async def run(self) -> None:
        await self.websocket.accept()
        reader_task: asyncio.Task[Any] | None = None
        event_task: asyncio.Task[Any] | None = None
        try:
            await self.engine.start(self.session.id)
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
                    except WebSocketDisconnect:
                        break
                    if await self._handle_client_message(message):
                        break
                    reader_task = asyncio.create_task(self.websocket.receive_json())
                if event_task in done:
                    event = event_task.result()
                    if await self._handle_engine_event(event):
                        break
                    event_task = asyncio.create_task(self.engine.events.get())
        finally:
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
                await self.engine.send_audio(
                    base64.b64decode(message["pcm16_b64"], validate=True),
                    source=message.get("source"),
                )
            elif message_type == "frame":
                jpeg_bytes = base64.b64decode(message["jpeg_b64"], validate=True)
                frame = Frame(
                    ts=float(message.get("ts", self._elapsed())),
                    jpeg_b64=message["jpeg_b64"],
                    reason=message.get("reason", "manual"),
                )
                self.session.frames.append(frame)
                del self.session.frames[:-200]
                await self.engine.send_frame(jpeg_bytes)
                await self._emit("frame_ack", frame.model_dump(exclude={"jpeg_b64"}))
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
        elif isinstance(event, EngineStatus):
            await self._emit("status", {"status": event.status, "detail": event.detail})
            return event.status in {"script_complete", "disconnected"}
        return False

    async def _handle_tool_call(self, event: ToolCall) -> None:
        if event.name == "create_anchor":
            latest = self.session.transcript[-1] if self.session.transcript else None
            grounded = GroundedEvent(
                ts=event.ts or self._elapsed(),
                speaker=event.args.get("speaker") or (latest.speaker if latest else None),
                utterance=latest.text if latest else "",
                target=str(event.args.get("target", "")),
                observation=str(event.args.get("observation", "")),
                frame_id=self.session.frames[-1].id if self.session.frames else None,
                confidence=float(event.args.get("confidence", 0.0)),
            )
            self.session.grounded_events.append(grounded)
            self.recorder.link(event.utterance_id, event.name, grounded.id)
            await self._emit("grounded_event", grounded.model_dump())
        elif event.name == "propose_decision":
            proposal = Decision(
                ts=event.ts or self._elapsed(),
                topic=str(event.args.get("topic", "")),
                chosen=str(event.args.get("chosen", "")),
                alternatives=list(event.args.get("alternatives", [])),
                reasons_for=list(event.args.get("reasons_for", [])),
                reasons_against=list(event.args.get("reasons_against", [])),
                constraints=list(event.args.get("constraints", [])),
            )
            decision = self._merge_decision(proposal)
            options = self.session.decision_state.options_under_comparison
            for option in [decision.chosen, *decision.alternatives]:
                if option not in options:
                    options.append(option)
            for constraint in decision.constraints:
                if constraint not in self.session.decision_state.constraints:
                    self.session.decision_state.constraints.append(constraint)
            hits = self.knowledge.search(f"{decision.topic} {decision.chosen}")
            alerts = await check_conflict(decision, hits)
            decision.conflicts.extend(alert.id for alert in alerts)
            self.session.alerts.extend(alerts)
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

    def _merge_decision(self, proposal: Decision) -> Decision:
        """Fold a proposal into an existing candidate on the same topic instead of
        stacking near-duplicates; the latest wording wins, lists are unioned."""
        for existing in self.session.decision_state.decisions:
            if existing.status != "candidate":
                continue
            same_topic = fuzz.token_set_ratio(existing.topic, proposal.topic) >= 70
            same_choice = fuzz.partial_ratio(existing.chosen, proposal.chosen) >= 70
            if same_topic or same_choice:
                existing.chosen = proposal.chosen
                existing.ts = proposal.ts
                for field in ("alternatives", "reasons_for", "reasons_against", "constraints"):
                    merged = getattr(existing, field)
                    merged.extend(item for item in getattr(proposal, field) if item not in merged)
                if existing.chosen in existing.alternatives:
                    existing.alternatives.remove(existing.chosen)
                return existing
        self.session.decision_state.decisions.append(proposal)
        return proposal

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
