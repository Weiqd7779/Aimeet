from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


def _new_id() -> str:
    return str(uuid4())


@dataclass
class Transcript:
    text: str
    ts: float
    speaker: str | None = None
    id: str = field(default_factory=_new_id)


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


EngineEvent = Transcript | ToolCall | IntentResolved | EngineStatus | EchoDropped
