"""Build the structured meeting record handed to the synthesis model.

Live transcription yields fragments (one speaker's sentence may arrive as several lines).
For synthesis what matters is: who said it, in what order, and that nothing is dropped.
So consecutive fragments from the same speaker are merged into one turn, and every other
signal (frames, grounded events, decisions, alerts) is interleaved on the same timeline.
"""

from typing import Any

from app.knowledge.store import KnowledgeStore
from app.models import MeetingSession, TranscriptEntry

MERGE_GAP_SECONDS = 6.0
SPEAKER_ROLES = {"我": "主持人（本機麥克風）", "與會者": "遠端與會者（會議音訊）"}


def merge_turns(entries: list[TranscriptEntry]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for entry in sorted(entries, key=lambda item: item.ts):
        last = turns[-1] if turns else None
        if (
            last
            and last["speaker"] == entry.speaker
            and entry.ts - last["ts_end"] <= MERGE_GAP_SECONDS
        ):
            last["text"] = f"{last['text']}{entry.text}".strip()
            last["ts_end"] = entry.ts
            last["fragments"] += 1
        else:
            turns.append(
                {
                    "speaker": entry.speaker,
                    "ts_start": entry.ts,
                    "ts_end": entry.ts,
                    "text": entry.text.strip(),
                    "fragments": 1,
                }
            )
    return turns


def build_timeline(session: MeetingSession) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [
        {"ts": turn["ts_start"], "type": "utterance", **turn}
        for turn in merge_turns(session.transcript)
    ]
    events += [
        {"ts": frame.ts, "type": "frame", "frame_id": frame.id, "reason": frame.reason}
        for frame in session.frames
    ]
    events += [
        {
            "ts": event.ts,
            "type": "grounded_event",
            "id": event.id,
            "speaker": event.speaker,
            "utterance": event.utterance,
            "target": event.target,
            "observation": event.observation,
            "frame_id": event.frame_id,
            "confidence": event.confidence,
        }
        for event in session.grounded_events
    ]
    events += [
        {"ts": decision.ts, "type": "decision", **decision.model_dump()}
        for decision in session.decision_state.decisions
    ]
    events += [{"ts": alert.ts, "type": "alert", **alert.model_dump()} for alert in session.alerts]
    return sorted(events, key=lambda item: (item["ts"], item["type"] != "frame"))


def build_record(session: MeetingSession, knowledge: KnowledgeStore) -> dict[str, Any]:
    alert_sources = {alert.source for alert in session.alerts if alert.source}
    chunks = [
        {"source": chunk.source, "id": chunk.id, "text": chunk.text}
        for chunk in getattr(knowledge, "_chunks", [])
        if chunk.source in alert_sources
    ]
    speakers = sorted({entry.speaker for entry in session.transcript if entry.speaker})
    return {
        "participants": [
            {"speaker": speaker, "role": SPEAKER_ROLES.get(speaker, "未知")} for speaker in speakers
        ],
        "notes": [
            "utterance 已將同一說話者的連續片段合併；speaker 欄位來自獨立音訊通道，可信。",
            "ts 為會議開始後的秒數；frame_id 可用於引用畫面。",
        ],
        "timeline": build_timeline(session),
        "decision_state": session.decision_state.model_dump(),
        "knowledge_sources": chunks,
    }
