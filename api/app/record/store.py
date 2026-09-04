"""Durable, fixed-schema meeting record.

Write-first: every utterance is persisted the moment transcription completes
(`intent=pending`); intent/tool links are patched in when the reasoning model answers.

Layout under `<record_dir>/<session_id>/`:
    events.jsonl   append-only log (source of truth): utterance | resolved | frame | ...
    record.json    snapshot rebuilt from memory on every change (what search/RAG should read)
    record.md      human-readable rendering derived from record.json
    report.json    post-meeting synthesis, once generated
    frames/<id>.jpg every captured frame; scenes reference them by id
"""

import base64
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import (
    Alert,
    Decision,
    Frame,
    GroundedEvent,
    MeetingSession,
    Scene,
    TranscriptEntry,
    UtteranceRecord,
)
from app.record.scenes import ADJACENT_SECONDS, SceneTracker
from app.synthesis.schemas import MeetingReport

TOOL_LINKS = {
    "create_anchor": "grounded_event_ids",
    "propose_decision": "decision_ids",
    "notify_speaker": "alert_ids",
}


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


class Recorder:
    def __init__(self, session: MeetingSession, root: str | Path) -> None:
        self.session = session
        self.dir = Path(root) / session.id
        (self.dir / "frames").mkdir(parents=True, exist_ok=True)
        self.utterances: list[UtteranceRecord] = []
        self._by_id: dict[str, UtteranceRecord] = {}
        self.scenes = SceneTracker(session.scenes)

    # --- writes -------------------------------------------------------------

    def _append_event(self, kind: str, payload: dict[str, Any]) -> None:
        line = json.dumps(
            {"event": kind, "wall_time": datetime.now(UTC).isoformat(), **payload},
            ensure_ascii=False,
            default=str,
        )
        with (self.dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def add_frame(self, frame: Frame, jpeg_bytes: bytes) -> Scene:
        (self.dir / "frames" / f"{frame.id}.jpg").write_bytes(jpeg_bytes)
        scene = self.scenes.add_frame(frame, jpeg_bytes)
        # Utterances just before a page change now have a neighbour they could not see yet.
        for record in reversed(self.utterances):
            if scene.first_ts - record.ts > ADJACENT_SECONDS:
                break
            main = self.scenes.scene_at(record.ts)
            record.scene_id = main.id if main else None
            record.adjacent_scene_ids = self.scenes.adjacent(record.ts, main)
        self._append_event(
            "frame", {**frame.model_dump(mode="json", exclude={"jpeg_b64"}), "scene_seq": scene.seq}
        )
        self.snapshot()
        return scene

    def add_utterance(
        self, *, id: str, ts: float, speaker: str | None, text: str
    ) -> UtteranceRecord:
        scene = self.scenes.scene_at(ts)
        record = UtteranceRecord(
            id=id,
            session_id=self.session.id,
            seq=len(self.utterances),
            ts=ts,
            wall_time=datetime.now(UTC),
            speaker=speaker,
            text=text,
            frame_id=self.session.frames[-1].id if self.session.frames else None,
            scene_id=scene.id if scene else None,
            adjacent_scene_ids=self.scenes.adjacent(ts, scene),
        )
        self.utterances.append(record)
        self._by_id[record.id] = record
        self._append_event("utterance", record.model_dump(mode="json"))
        self.snapshot()
        return record

    def link(self, utterance_id: str | None, tool: str, target_id: str) -> None:
        record = self._by_id.get(utterance_id or "")
        if record:
            if field := TOOL_LINKS.get(tool):
                getattr(record, field).append(target_id)
            if tool not in record.tools:
                record.tools.append(tool)
        self._append_event(
            "tool", {"utterance_id": utterance_id, "tool": tool, "target_id": target_id}
        )

    def resolve(self, utterance_id: str | None, tools: list[str]) -> None:
        record = self._by_id.get(utterance_id or "")
        if record:
            for tool in tools:
                if tool not in record.tools:
                    record.tools.append(tool)
            record.intent = "tools" if record.tools else "none"
        self._append_event("resolved", {"utterance_id": utterance_id, "tools": tools})
        self.snapshot()

    def note(self, kind: str, payload: dict[str, Any]) -> None:
        """Append an informational event that is not part of the transcript."""
        self._append_event(kind, payload)

    def close(self) -> None:
        for record in self.utterances:
            if record.intent == "pending":
                record.intent = "none"
        self._append_event("ended", {"utterances": len(self.utterances)})
        self.snapshot()

    # --- reads --------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "aimeet.record.v1",
            "session_id": self.session.id,
            "started_at": self.session.started_at.isoformat(),
            "speakers": sorted({u.speaker for u in self.utterances if u.speaker}),
            "utterances": [u.model_dump(mode="json") for u in self.utterances],
            "scenes": [s.model_dump(mode="json") for s in self.session.scenes],
            "grounded_events": [e.model_dump(mode="json") for e in self.session.grounded_events],
            "decisions": [d.model_dump(mode="json") for d in self.session.decision_state.decisions],
            "alerts": [a.model_dump(mode="json") for a in self.session.alerts],
            "frames": [
                f.model_dump(mode="json", exclude={"jpeg_b64"}) for f in self.session.frames
            ],
        }

    def to_markdown(self) -> str:
        data = self.to_dict()
        lines = [
            f"# Meeting {data['session_id']}",
            "",
            f"- started_at: {data['started_at']}",
            f"- speakers: {', '.join(data['speakers']) or '-'}",
            f"- utterances: {len(data['utterances'])}",
            "",
            "## Transcript",
            "",
            "| time | page | speaker | text | intent | links |",
            "|------|------|---------|------|--------|-------|",
        ]
        scene_seq = {s["id"]: s["seq"] + 1 for s in data["scenes"]}
        for u in data["utterances"]:
            links = [
                *(f"decision:{i}" for i in u["decision_ids"]),
                *(f"grounded:{i}" for i in u["grounded_event_ids"]),
                *(f"alert:{i}" for i in u["alert_ids"]),
            ]
            tools = ",".join(u["tools"]) if u["tools"] else u["intent"]
            text = u["text"].replace("|", "\\|")
            page = scene_seq.get(u["scene_id"], "-")
            if u["adjacent_scene_ids"]:
                page = f"{page}~{'/'.join(str(scene_seq[i]) for i in u['adjacent_scene_ids'])}"
            lines.append(
                f"| {_clock(u['ts'])} | {page} | {u['speaker'] or '-'} | {text} | {tools} "
                f"| {' '.join(links)} |"
            )
        if data["scenes"]:
            lines += ["", "## Pages (scenes)", ""]
            for s in data["scenes"]:
                title = s["title"] or "(untitled)"
                lines.append(
                    f"- p{s['seq'] + 1} {_clock(s['first_ts'])}–{_clock(s['last_ts'])} "
                    f"**{title}** — {s['summary'] or ''}（cover: frames/{s['cover_frame_id']}.jpg; "
                    f"id: {s['id']}）"
                )
        if data["decisions"]:
            lines += ["", "## Decisions", ""]
            for d in data["decisions"]:
                alts = ", ".join(d["alternatives"]) or "-"
                lines.append(
                    f"- [{d['status']}] **{d['topic']}** → {d['chosen']}"
                    f"（alternatives: {alts}; id: {d['id']}）"
                )
        if data["grounded_events"]:
            lines += ["", "## Grounded events", ""]
            for g in data["grounded_events"]:
                lines.append(
                    f"- {_clock(g['ts'])} {g['speaker'] or '-'}: {g['target']} — "
                    f"{g['observation']}（frame: {g['frame_id']}; id: {g['id']}）"
                )
        if data["alerts"]:
            lines += ["", "## Alerts", ""]
            for a in data["alerts"]:
                lines.append(
                    f"- [{a['kind']}/{a['status']}] {a['title']}: {a['detail']}"
                    f"（source: {a['source']}; id: {a['id']}）"
                )
        return "\n".join(lines) + "\n"

    def snapshot(self) -> None:
        _atomic_write(
            self.dir / "record.json", json.dumps(self.to_dict(), ensure_ascii=False, indent=1)
        )
        _atomic_write(self.dir / "record.md", self.to_markdown())


def save_report(root: str | Path, session: MeetingSession) -> None:
    """Persist the synthesis output next to the record (and scene titles it produced)."""
    folder = Path(root) / session.id
    if not folder.exists() or session.report is None:
        return
    _atomic_write(
        folder / "report.json",
        json.dumps(
            {
                "report": session.report.model_dump(mode="json"),
                "model": session.report_model,
                "mock": session.report_mock,
            },
            ensure_ascii=False,
            indent=1,
        ),
    )
    record_path = folder / "record.json"
    if record_path.exists():
        data = json.loads(record_path.read_text(encoding="utf-8"))
        data["scenes"] = [s.model_dump(mode="json") for s in session.scenes]
        _atomic_write(record_path, json.dumps(data, ensure_ascii=False, indent=1))


def load_session(root: str | Path, session_id: str) -> MeetingSession | None:
    """Rebuild a MeetingSession (and its report) from what the Recorder wrote to disk."""
    folder = Path(root) / session_id
    record_path = folder / "record.json"
    if not record_path.exists():
        return None
    data = json.loads(record_path.read_text(encoding="utf-8"))
    frames = []
    for item in data["frames"]:
        jpeg_path = folder / "frames" / f"{item['id']}.jpg"
        jpeg_b64 = (
            base64.b64encode(jpeg_path.read_bytes()).decode("ascii") if jpeg_path.exists() else ""
        )
        frames.append(Frame(**item, jpeg_b64=jpeg_b64))
    session = MeetingSession(
        id=data["session_id"],
        started_at=datetime.fromisoformat(data["started_at"]),
        transcript=[
            TranscriptEntry(id=u["id"], ts=u["ts"], speaker=u["speaker"], text=u["text"])
            for u in data["utterances"]
        ],
        frames=frames,
        scenes=[Scene(**s) for s in data.get("scenes", [])],
        grounded_events=[GroundedEvent(**g) for g in data["grounded_events"]],
        alerts=[Alert(**a) for a in data["alerts"]],
    )
    session.decision_state.decisions = [Decision(**d) for d in data["decisions"]]
    report_path = folder / "report.json"
    if report_path.exists():
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        session.report = MeetingReport(**saved["report"])
        session.report_model = saved.get("model")
        session.report_mock = saved.get("mock")
    return session
