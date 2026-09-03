from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.synthesis.schemas import MeetingReport


def new_id() -> str:
    return str(uuid4())


class GroundedEvent(BaseModel):
    id: str = Field(default_factory=new_id)
    ts: float
    speaker: str | None = None
    utterance: str
    target: str
    observation: str
    frame_id: str | None = None
    confidence: float = 0.0


AlertKind = Literal["conflict", "slide_mismatch", "info"]
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


class DecisionState(BaseModel):
    options_under_comparison: list[str] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class TranscriptEntry(BaseModel):
    ts: float
    speaker: str | None = None
    text: str


class MeetingSession(BaseModel):
    id: str = Field(default_factory=new_id)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    frames: list[Frame] = Field(default_factory=list)
    grounded_events: list[GroundedEvent] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)
    decision_state: DecisionState = Field(default_factory=DecisionState)
    report: MeetingReport | None = None
    report_model: str | None = None
    report_mock: bool | None = None


EventType = Literal[
    "transcript",
    "grounded_event",
    "alert",
    "decision",
    "frame_ack",
    "status",
    "error",
]


class ServerEvent(BaseModel):
    type: EventType
    payload: object
