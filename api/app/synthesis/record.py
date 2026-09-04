"""Build the structured meeting record handed to the synthesis model.

Live transcription yields fragments (one speaker's sentence may arrive as several lines).
For synthesis what matters is: who said it, in what order, and that nothing is dropped.
So consecutive fragments from the same speaker are merged into one turn, and every other
signal (frames, grounded events, decisions, alerts) is interleaved on the same timeline.
"""

from typing import Any

from app.knowledge.store import KnowledgeStore
from app.models import MeetingSession, TranscriptEntry
from app.synthesis.schemas import SceneIndex, ScenePage

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


def scene_of(session: MeetingSession, ts: float) -> str | None:
    """Scene on screen at `ts` (last scene that started before it)."""
    active = None
    for scene in session.scenes:
        if scene.first_ts <= ts:
            active = scene.id
        else:
            break
    return active or (session.scenes[0].id if session.scenes else None)


def build_pages(session: MeetingSession, timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Timeline regrouped per page of the shared screen. Utterances near a page change are
    listed under both neighbours (marked `also_in`) so nothing is lost to boundary lag."""
    if not session.scenes:
        return []
    pages = {
        scene.id: {
            "scene_id": scene.id,
            "page": scene.seq + 1,
            "first_ts": scene.first_ts,
            "last_ts": scene.last_ts,
            "cover_frame_id": scene.cover_frame_id,
            "items": [],
        }
        for scene in session.scenes
    }
    order = [scene.id for scene in session.scenes]
    for item in timeline:
        if item["type"] == "frame":
            continue
        main = scene_of(session, item["ts"])
        if main is None:
            continue
        pages[main]["items"].append(item)
        index = order.index(main)
        neighbours = []
        if index > 0 and item["ts"] - session.scenes[index].first_ts <= 4.0:
            neighbours.append(order[index - 1])
        if index + 1 < len(order) and session.scenes[index + 1].first_ts - item["ts"] <= 4.0:
            neighbours.append(order[index + 1])
        for neighbour in neighbours:
            pages[neighbour]["items"].append({**item, "also_in": pages[main]["page"]})
    for page in pages.values():
        page["items"].sort(key=lambda entry: entry["ts"])
    return [pages[scene_id] for scene_id in order]


def scene_pages(session: MeetingSession, index: SceneIndex | None = None) -> list[ScenePage]:
    """Report view of scenes; also writes model-produced titles back onto the session."""
    titles = {entry.scene_id: entry for entry in (index.scenes if index else [])}
    pages = []
    for scene in session.scenes:
        if entry := titles.get(scene.id):
            scene.title, scene.summary = entry.title, entry.summary
        pages.append(
            ScenePage(
                id=scene.id,
                seq=scene.seq,
                first_ts=scene.first_ts,
                last_ts=scene.last_ts,
                cover_frame_id=scene.cover_frame_id,
                title=scene.title or f"第 {scene.seq + 1} 頁",
                summary=scene.summary or "",
                utterance_count=sum(
                    1 for u in session.transcript if scene_of(session, u.ts) == scene.id
                ),
            )
        )
    return pages


def build_record(session: MeetingSession, knowledge: KnowledgeStore) -> dict[str, Any]:
    alert_sources = {alert.source for alert in session.alerts if alert.source}
    chunks = [
        {"source": chunk.source, "id": chunk.id, "text": chunk.text}
        for chunk in getattr(knowledge, "_chunks", [])
        if chunk.source in alert_sources
    ]
    speakers = sorted({entry.speaker for entry in session.transcript if entry.speaker})
    timeline = build_timeline(session)
    return {
        "participants": [
            {"speaker": speaker, "role": SPEAKER_ROLES.get(speaker, "未知")} for speaker in speakers
        ],
        "notes": [
            "utterance 已將同一說話者的連續片段合併；speaker 欄位來自獨立音訊通道，可信。",
            "ts 為會議開始後的秒數；frame_id 可用於引用畫面。",
            (
                "pages 是依分享畫面切出的頁（scene），同一頁上說的內容放在一起；"
                "頁面切換前後 4 秒內的發言會同時列在相鄰兩頁（also_in），屬正常現象，不要視為重複。"
            ),
        ],
        "timeline": timeline,
        "pages": build_pages(session, timeline),
        "decision_state": session.decision_state.model_dump(),
        "knowledge_sources": chunks,
    }
