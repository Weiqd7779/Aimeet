"""Durable, fixed-schema meeting record.

Write-first: every utterance is persisted the moment transcription completes
(`intent=pending`); intent/tool links are patched in when the reasoning model answers.

Layout under `<record_dir>/<session_id>/`:
    events.jsonl   append-only log (source of truth): utterance | resolved | frame | ...
    record.json    snapshot rebuilt from memory on every change (what search/RAG should read)
    record.md      human-readable rendering derived from record.json
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import MeetingSession, UtteranceRecord

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
        self.dir.mkdir(parents=True, exist_ok=True)
        self.utterances: list[UtteranceRecord] = []
        self._by_id: dict[str, UtteranceRecord] = {}

    # --- writes -------------------------------------------------------------

    def _append_event(self, kind: str, payload: dict[str, Any]) -> None:
        line = json.dumps(
            {"event": kind, "wall_time": datetime.now(UTC).isoformat(), **payload},
            ensure_ascii=False,
            default=str,
        )
        with (self.dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def add_utterance(
        self, *, id: str, ts: float, speaker: str | None, text: str
    ) -> UtteranceRecord:
        record = UtteranceRecord(
            id=id,
            session_id=self.session.id,
            seq=len(self.utterances),
            ts=ts,
            wall_time=datetime.now(UTC),
            speaker=speaker,
            text=text,
            frame_id=self.session.frames[-1].id if self.session.frames else None,
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
            "| time | speaker | text | intent | links |",
            "|------|---------|------|--------|-------|",
        ]
        for u in data["utterances"]:
            links = [
                *(f"decision:{i}" for i in u["decision_ids"]),
                *(f"grounded:{i}" for i in u["grounded_event_ids"]),
                *(f"alert:{i}" for i in u["alert_ids"]),
            ]
            tools = ",".join(u["tools"]) if u["tools"] else u["intent"]
            text = u["text"].replace("|", "\\|")
            lines.append(
                f"| {_clock(u['ts'])} | {u['speaker'] or '-'} | {text} | {tools} | {' '.join(links)} |"
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
