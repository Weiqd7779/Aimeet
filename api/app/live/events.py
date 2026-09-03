from dataclasses import dataclass, field
from typing import Any


@dataclass
class Transcript:
    text: str
    ts: float
    speaker: str | None = None


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    id: str | None = None
    ts: float = 0.0


@dataclass
class EngineStatus:
    status: str
    detail: str | None = None


EngineEvent = Transcript | ToolCall | EngineStatus
