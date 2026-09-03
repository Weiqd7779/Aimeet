import os

from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from app.config import settings
from app.main import app
from app.routes import sessions


def test_mock_replay_synthesis_report() -> None:
    os.environ["MOCK_SPEED"] = "50"
    previous_synthesis_mock = settings.synthesis_mock
    settings.synthesis_mock = True
    client = TestClient(app)
    session_id = client.post("/sessions").json()["id"]
    try:
        with client.websocket_connect(f"/ws/live/{session_id}") as websocket:
            while True:
                try:
                    websocket.receive_json()
                except WebSocketDisconnect:
                    break

        response = client.post(
            f"/sessions/{session_id}/synthesize",
            json={"model": "mock", "force": True},
        )
        assert response.status_code == 200
        payload = response.json()
        report = payload["report"]
        assert payload["mock"] is True
        assert len(report["decision_table"]) == 2
        assert report["mermaid"].startswith(("flowchart", "graph"))
        assert len(report["work_items"]) >= 1
    finally:
        settings.synthesis_mock = previous_synthesis_mock
        os.environ.pop("MOCK_SPEED", None)
        sessions.pop(session_id, None)
