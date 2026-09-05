"""Build the structured meeting record handed to the synthesis model.

Live transcription yields fragments (one speaker's sentence may arrive as several lines).
For synthesis what matters is: who said it, in what order, and that nothing is dropped.
So consecutive fragments from the same speaker are merged into one turn — a turn only ends
when the speaker changes, never on a pause, because where one topic ends and the next
begins is a judgement the model makes after reading the whole turn, not something a
silence timer should decide. Every other signal (frames, grounded events, decisions,
alerts) is interleaved on the same timeline.
"""

from datetime import timedelta, timezone
from typing import Any

from app.knowledge.store import KnowledgeStore
from app.models import MeetingSession, TranscriptEntry
from app.synthesis.schemas import SceneIndex, ScenePage

SPEAKER_ROLES = {"我": "主持人（本機麥克風）", "與會者": "遠端與會者（會議音訊）"}
MEETING_TZ = timezone(timedelta(hours=8))  # Asia/Taipei (no tzdata dependency on Windows)
WEEKDAYS = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


def _ts(value: float) -> float:
    return round(value, 1)


def merge_turns(entries: list[TranscriptEntry]) -> list[dict[str, Any]]:
    """One turn per stretch of the same speaker; each fragment keeps its own ts so the
    model can still point at the sentence it is quoting."""
    turns: list[dict[str, Any]] = []
    for entry in sorted(entries, key=lambda item: item.ts):
        last = turns[-1] if turns else None
        if last and last["speaker"] == entry.speaker:
            last["text"] = f"{last['text']}{entry.text}".strip()
            last["ts_end"] = _ts(entry.ts)
            last["sentences"].append({"ts": _ts(entry.ts), "text": entry.text.strip()})
        else:
            turns.append(
                {
                    "speaker": entry.speaker,
                    "ts_start": _ts(entry.ts),
                    "ts_end": _ts(entry.ts),
                    "text": entry.text.strip(),
                    "sentences": [{"ts": _ts(entry.ts), "text": entry.text.strip()}],
                }
            )
    return turns


def build_timeline(session: MeetingSession) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [
        {"ts": turn["ts_start"], "type": "utterance", **turn}
        for turn in merge_turns(session.transcript)
    ]
    events += [
        {"ts": _ts(frame.ts), "type": "frame", "frame_id": frame.id, "reason": frame.reason}
        for frame in session.frames
    ]
    events += [
        {
            "ts": _ts(event.ts),
            "type": "grounded_event",
            "id": event.id,
            "speaker": event.speaker,
            "utterance": event.utterance,
            "target": event.target,
            "observation": event.observation,
            "said": event.said,
            "frame_id": event.frame_id,
            "confidence": event.confidence,
        }
        for event in session.grounded_events
    ]
    events += [
        {**decision.model_dump(), "ts": _ts(decision.ts), "type": "decision"}
        for decision in session.decision_state.decisions
    ]
    events += [
        {**alert.model_dump(), "ts": _ts(alert.ts), "type": "alert"} for alert in session.alerts
    ]
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


def _page_items(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pages are about *when* something was said, so a long single-speaker turn is
    re-split into its sentences here; the turn stays whole in the timeline."""
    items: list[dict[str, Any]] = []
    for item in timeline:
        if item["type"] == "utterance":
            items += [
                {"ts": s["ts"], "type": "utterance", "speaker": item["speaker"], "text": s["text"]}
                for s in item["sentences"]
            ]
        elif item["type"] != "frame":
            items.append(item)
    return items


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
    for item in _page_items(timeline):
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
    started = session.started_at.astimezone(MEETING_TZ)
    return {
        "meeting_date": {
            "date": started.strftime("%Y-%m-%d"),
            "weekday": WEEKDAYS[started.weekday()],
            "note": "相對時間（下週三、兩週內）一律以此為基準換算；原話沒有年份就用這一年。",
        },
        "participants": [
            {"speaker": speaker, "role": SPEAKER_ROLES.get(speaker, "未知")} for speaker in speakers
        ],
        "notes": [
            (
                "utterance 是同一說話者連續講的整段話（只有換人才切開），sentences 是其中每句與時間；"
                "speaker 欄位來自獨立音訊通道，可信。"
            ),
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
