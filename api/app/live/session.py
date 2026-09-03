import asyncio
import base64
import binascii
import contextlib
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.conflict import check_conflict
from app.knowledge.store import KnowledgeStore
from app.live.events import EngineStatus, ToolCall, Transcript
from app.live.gemini import GeminiLiveEngine
from app.live.mock import MockLiveEngine
from app.live.openai_rt import OpenAIRealtimeEngine
from app.models import (
    Alert,
    Decision,
    Frame,
    GroundedEvent,
    GroundedVisualEvent,
    MeetingSession,
    ServerEvent,
    TimeRange,
    TranscriptEntry,
)
from app.storage import save_events, save_frame
from app.vision import verify_visual_reference

logger = logging.getLogger(__name__)


@dataclass
class VerifyJob:
    event: GroundedVisualEvent
    anchor: GroundedEvent


@dataclass
class CloseJob:
    event: GroundedVisualEvent


@dataclass
class ConflictJob:
    decision: Decision


ProcessingJob = VerifyJob | CloseJob | ConflictJob


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
        self._started = asyncio.get_running_loop().time()
        self.queue: asyncio.Queue[ProcessingJob] = asyncio.Queue()
        self.context_before_seconds = settings.context_before_seconds
        self.context_after_seconds = settings.context_after_seconds
        self.buffer_seconds = settings.buffer_seconds
        self.frame_wait_seconds = 0.0 if isinstance(self.engine, MockLiveEngine) else 2.0
        self.drain_seconds = 10.0
        self._worker: asyncio.Task[None] | None = None
        self._timers: set[asyncio.Task[None]] = set()

    def _elapsed(self) -> float:
        return asyncio.get_running_loop().time() - self._started

    async def _emit(self, event_type: str, payload: Any) -> None:
        event = ServerEvent(type=event_type, payload=payload)
        await self.websocket.send_json(event.model_dump(mode="json"))

    async def _try_emit(self, event_type: str, payload: Any) -> None:
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await self._emit(event_type, payload)

    async def run(self) -> None:
        await self.websocket.accept()
        reader_task: asyncio.Task[Any] | None = None
        event_task: asyncio.Task[Any] | None = None
        try:
            await self.engine.start(self.session.id)
            self._worker = asyncio.create_task(self._process_jobs())
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
            with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                await asyncio.wait_for(self.queue.join(), timeout=self.drain_seconds)
            for task in (reader_task, event_task, self._worker, *self._timers):
                if task and not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            await self.engine.close()
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await self.websocket.close()

    async def _handle_client_message(self, message: dict[str, Any]) -> bool:
        message_type = message.get("type")
        try:
            if message_type == "audio":
                await self.engine.send_audio(base64.b64decode(message["pcm16_b64"], validate=True))
            elif message_type == "frame":
                jpeg_bytes = base64.b64decode(message["jpeg_b64"], validate=True)
                frame = Frame(
                    ts=float(message.get("ts", self._elapsed())),
                    jpeg_b64=message["jpeg_b64"],
                    reason=message.get("reason", "manual"),
                )
                self.session.frames.append(frame)
                self._trim_buffers()
                await self.engine.send_frame(jpeg_bytes, frame.reason)
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
            transcript = TranscriptEntry(ts=event.ts, speaker=event.speaker, text=event.text)
            self.session.transcript.append(transcript)
            self._trim_buffers()
            await self._emit("transcript", transcript.model_dump())
        elif isinstance(event, ToolCall):
            await self._handle_tool_call(event)
        elif isinstance(event, EngineStatus):
            await self._emit("status", {"status": event.status, "detail": event.detail})
            return event.status in {"script_complete", "disconnected"}
        return False

    def _trim_buffers(self) -> None:
        now = self._elapsed()
        cutoff = now - self.buffer_seconds
        self.session.transcript[:] = [
            entry for entry in self.session.transcript if entry.ts >= cutoff
        ]
        self.session.frames[:] = [frame for frame in self.session.frames if frame.ts >= cutoff]
        del self.session.frames[:-200]

    def _nearest_frame(self, ts: float) -> Frame | None:
        if not self.session.frames:
            return None
        return min(self.session.frames, key=lambda frame: abs(frame.ts - ts))

    def _texts_between(self, start: float, end: float) -> list[str]:
        return [entry.text for entry in self.session.transcript if start <= entry.ts <= end]

    async def _handle_tool_call(self, event: ToolCall) -> None:
        if event.name == "create_anchor":
            trigger = event.ts or self._elapsed()
            latest = self.session.transcript[-1] if self.session.transcript else None
            speaker = event.args.get("speaker") or (latest.speaker if latest else None)
            utterance = latest.text if latest else ""
            nearest = self._nearest_frame(trigger)
            grounded = GroundedEvent(
                ts=trigger,
                speaker=speaker,
                utterance=utterance,
                target=str(event.args.get("target", "")),
                observation=str(event.args.get("observation", "")),
                frame_id=nearest.id if nearest else None,
                confidence=float(event.args.get("confidence", 0.0)),
            )
            start = trigger - self.context_before_seconds
            visual_event = GroundedVisualEvent(
                time_range=TimeRange(start=start, trigger=trigger),
                trigger_text=utterance or str(event.args.get("observation", "")),
                speaker=speaker,
                context_before=self._texts_between(start, trigger),
            )
            await self._emit(
                "status",
                {"status": "request_frame", "request_frame": True, "reason": "deictic"},
            )
            self.queue.put_nowait(VerifyJob(visual_event, grounded))
        elif event.name == "propose_decision":
            decision = Decision(
                ts=event.ts or self._elapsed(),
                topic=str(event.args.get("topic", "")),
                chosen=str(event.args.get("chosen", "")),
                alternatives=list(event.args.get("alternatives", [])),
                reasons_for=list(event.args.get("reasons_for", [])),
                reasons_against=list(event.args.get("reasons_against", [])),
                constraints=list(event.args.get("constraints", [])),
            )
            self.session.decision_state.decisions.append(decision)
            options = self.session.decision_state.options_under_comparison
            for option in [decision.chosen, *decision.alternatives]:
                if option not in options:
                    options.append(option)
            for constraint in decision.constraints:
                if constraint not in self.session.decision_state.constraints:
                    self.session.decision_state.constraints.append(constraint)
            await self._emit("decision", decision.model_dump())
            self.queue.put_nowait(ConflictJob(decision))
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
            await self._emit("alert", alert.model_dump())
        elif event.name == "capture_context":
            await self._emit(
                "status",
                {
                    "status": "request_frame",
                    "request_frame": True,
                    "reason": event.args.get("reason"),
                },
            )

    async def _process_jobs(self) -> None:
        while True:
            job = await self.queue.get()
            try:
                await self._process_job(job)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Processing job failed: %s", type(job).__name__)
            finally:
                self.queue.task_done()

    async def _process_job(self, job: ProcessingJob) -> None:
        if isinstance(job, VerifyJob):
            await self._verify_event(job.event, job.anchor)
        elif isinstance(job, CloseJob):
            await self._close_event(job.event)
        elif isinstance(job, ConflictJob):
            await self._run_conflict_check(job.decision)

    async def _wait_for_frame(self, trigger: float) -> Frame | None:
        deadline = self._elapsed() + self.frame_wait_seconds
        while self._elapsed() < deadline:
            if any(frame.ts >= trigger for frame in self.session.frames):
                break
            await asyncio.sleep(0.05)
        return self._nearest_frame(trigger)

    async def _verify_event(self, event: GroundedVisualEvent, anchor: GroundedEvent) -> None:
        frame = await self._wait_for_frame(event.time_range.trigger)
        context = [*event.context_before, event.trigger_text]
        verdict = await verify_visual_reference(
            event.trigger_text,
            context,
            frame.jpeg_b64 if frame else None,
        )
        if not verdict.is_grounded_visual_reference:
            logger.info("Rejected visual reference: %s (%s)", event.trigger_text, verdict.reason)
            return
        if frame:
            event.evidence_frame_ids = [frame.id]
            anchor.frame_id = frame.id
            save_frame(self.session.id, frame.id, frame.jpeg_b64)
        self.session.grounded_events.append(anchor)
        await self._try_emit("grounded_event", anchor.model_dump())
        event.lifecycle = "aggregating"
        self.session.grounded_visual_events.append(event)
        await self._try_emit("grounded_visual_event", event.model_dump())
        timer = asyncio.create_task(self._schedule_close(event))
        self._timers.add(timer)
        timer.add_done_callback(self._timers.discard)

    async def _schedule_close(self, event: GroundedVisualEvent) -> None:
        await asyncio.sleep(self.context_after_seconds)
        self.queue.put_nowait(CloseJob(event))

    async def _close_event(self, event: GroundedVisualEvent) -> None:
        end = event.time_range.trigger + self.context_after_seconds
        event.time_range.end = end
        event.context_after = [
            entry.text
            for entry in self.session.transcript
            if event.time_range.trigger < entry.ts <= end
        ]
        event.lifecycle = "closed"
        save_events(self.session.id, self.session.grounded_visual_events)
        await self._try_emit("grounded_visual_event", event.model_dump())

    async def _run_conflict_check(self, decision: Decision) -> None:
        hits = self.knowledge.search(f"{decision.topic} {decision.chosen}")
        alerts = await check_conflict(decision, hits)
        if not alerts:
            return
        decision.conflicts.extend(alert.id for alert in alerts)
        self.session.alerts.extend(alerts)
        await self._try_emit("decision", decision.model_dump())
        for alert in alerts:
            await self._try_emit("alert", alert.model_dump())

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
