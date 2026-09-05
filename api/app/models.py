from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.synthesis.schemas import MeetingReport


def new_id() -> str:
    return str(uuid4())


class GroundedEvent(BaseModel):
    """One thing someone pointed at. Visual fields come from the frame it was found in;
    `said` accumulates what speakers said about it across sentences."""

    id: str = Field(default_factory=new_id)
    ts: float
    speaker: str | None = None
    utterance: str
    target: str
    observation: str
    frame_id: str | None = None
    confidence: float = 0.0
    said: list[str] = Field(default_factory=list)
    mention_ids: list[str] = Field(default_factory=list)  # utterance ids that referred to it


class TimeRange(BaseModel):
    start: float
    trigger: float
    end: float | None = None


EventLifecycle = Literal["triggered", "aggregating", "closed"]


class GroundedVisualEvent(BaseModel):
    event_id: str = Field(default_factory=new_id)
    time_range: TimeRange
    trigger_text: str
    speaker: str | None = None
    context_before: list[str] = Field(default_factory=list)
    context_after: list[str] = Field(default_factory=list)
    evidence_frame_ids: list[str] = Field(default_factory=list)
    lifecycle: EventLifecycle = "triggered"


AlertKind = Literal["conflict", "slide_mismatch", "info", "inconsistency"]
AlertStatus = Literal["open", "acknowledged", "dismissed"]


class Alert(BaseModel):
    id: str = Field(default_factory=new_id)
    ts: float
    kind: AlertKind
    title: str
    detail: str
    source: str | None = None
    decision_id: str | None = None
    status: AlertStatus = "open"
    speech: str | None = None  # spoken version of `detail` (what the TTS voice says)
    evidence: list[str] = Field(default_factory=list)  # the utterances that back the alert


DecisionStatus = Literal["candidate", "confirmed", "rejected"]


class Decision(BaseModel):
    id: str = Field(default_factory=new_id)
    ts: float
    topic: str
    chosen: str
    alternatives: list[str] = Field(default_factory=list)
    reasons_for: list[str] = Field(default_factory=list)
    reasons_against: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    status: DecisionStatus = "candidate"
    conflicts: list[str] = Field(default_factory=list)


FrameReason = Literal["deictic", "diff", "periodic", "manual"]


class Frame(BaseModel):
    id: str = Field(default_factory=new_id)
    ts: float
    jpeg_b64: str
    reason: FrameReason
    scene_id: str | None = None


class Scene(BaseModel):
    """One 'page' of the shared screen: a run of visually similar frames."""

    id: str = Field(default_factory=new_id)
    seq: int
    first_ts: float
    last_ts: float
    frame_ids: list[str] = Field(default_factory=list)
    cover_frame_id: str
    hash: int = 0
    title: str | None = None
    summary: str | None = None


class DecisionState(BaseModel):
    options_under_comparison: list[str] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class TranscriptEntry(BaseModel):
    id: str = Field(default_factory=new_id)
    ts: float
    speaker: str | None = None
    text: str


IntentStatus = Literal["pending", "none", "tools"]


class UtteranceRecord(BaseModel):
    """One utterance after intent resolution. Fixed schema for downstream search / RAG."""

    id: str
    session_id: str
    seq: int
    ts: float
    wall_time: datetime
    speaker: str | None
    text: str
    intent: IntentStatus = "pending"
    tools: list[str] = Field(default_factory=list)
    grounded_event_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)
    alert_ids: list[str] = Field(default_factory=list)
    frame_id: str | None = None
    scene_id: str | None = None
    adjacent_scene_ids: list[str] = Field(default_factory=list)
    peak_rms: float | None = None  # mic level during the span (diagnostic, never a gate)


class MeetingSession(BaseModel):
    id: str = Field(default_factory=new_id)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    frames: list[Frame] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    grounded_events: list[GroundedEvent] = Field(default_factory=list)
    grounded_visual_events: list[GroundedVisualEvent] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)
    decision_state: DecisionState = Field(default_factory=DecisionState)
    report: MeetingReport | None = None
    report_model: str | None = None
    report_mock: bool | None = None


EventType = Literal[
    "transcript",
    "grounded_event",
    "grounded_visual_event",
    "alert",
    "decision",
    "frame_ack",
    "utterance_resolved",
    "speech",
    "status",
    "error",
]


class ServerEvent(BaseModel):
    type: EventType
    payload: object
