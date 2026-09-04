import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from app.config import settings
from app.main import app
from app.routes import sessions


def _run_mock_session(client: TestClient) -> tuple[str, list[dict]]:
    session_id = client.post("/sessions").json()["id"]
    events: list[dict] = []
    with client.websocket_connect(f"/ws/live/{session_id}") as websocket:
        while True:
            try:
                events.append(websocket.receive_json())
            except WebSocketDisconnect:
                break
    return session_id, events


def test_record_is_written_and_consistent(tmp_path: Path) -> None:
    os.environ["MOCK_SPEED"] = "50"
    previous_dir = settings.record_dir
    settings.record_dir = str(tmp_path)
    client = TestClient(app)
    try:
        session_id, events = _run_mock_session(client)
        folder = tmp_path / session_id
        assert (folder / "events.jsonl").exists()
        assert (folder / "record.md").exists()

        record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
        assert record["schema"] == "aimeet.record.v1"
        transcripts = [e["payload"] for e in events if e["type"] == "transcript"]
        utterances = record["utterances"]

        # every live transcript line is in the record, in order, with the same speaker/text
        assert [u["id"] for u in utterances] == [t["id"] for t in transcripts]
        assert [u["text"] for u in utterances] == [t["text"] for t in transcripts]
        assert [u["speaker"] for u in utterances] == [t["speaker"] for t in transcripts]
        assert [u["seq"] for u in utterances] == list(range(len(utterances)))

        # nothing left pending; every decision is linked back to the utterance that caused it
        assert all(u["intent"] in {"none", "tools"} for u in utterances)
        linked = {d for u in utterances for d in u["decision_ids"]}
        assert linked == {d["id"] for d in record["decisions"]}
        assert any(u["grounded_event_ids"] for u in utterances)

        # event log is append-only and replays to the same utterance set
        lines = [
            json.loads(line) for line in (folder / "events.jsonl").read_text("utf-8").splitlines()
        ]
        assert lines[-1]["event"] == "ended"
        assert {line["id"] for line in lines if line["event"] == "utterance"} == {
            u["id"] for u in utterances
        }

        # served over HTTP straight from disk
        assert client.get(f"/sessions/{session_id}/record").json() == record
        assert client.get(f"/sessions/{session_id}/record.md").text.startswith("# Meeting ")
    finally:
        settings.record_dir = previous_dir
        os.environ.pop("MOCK_SPEED", None)
        sessions.pop(session_id, None)
