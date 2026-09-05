from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


def _new_id() -> str:
    return str(uuid4())


@dataclass
class Transcript:
    text: str
    ts: float  # speech start (session seconds)
    speaker: str | None = None
    id: str = field(default_factory=_new_id)
    ended: float | None = None  # when the transcript completed (upper bound of the speech span)
    peak_rms: float | None = None  # loudest mic level during the span; diagnostic only


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    id: str | None = None
    ts: float = 0.0
    utterance_id: str | None = None


@dataclass
class IntentResolved:
    """The reasoning model finished processing one utterance (with or without tool calls)."""

    utterance_id: str | None
    tools: list[str] = field(default_factory=list)


@dataclass
class EngineStatus:
    status: str
    detail: str | None = None


@dataclass
class EchoDropped:
    """A `me` utterance discarded because it duplicated remote speech (speaker echo)."""

    text: str
    ts: float


@dataclass
class Rejected:
    """A transcript discarded because it was the prompt text echoed back verbatim."""

    text: str
    ts: float
    speaker: str | None
    reason: str


EngineEvent = Transcript | ToolCall | IntentResolved | EngineStatus | EchoDropped | Rejected
