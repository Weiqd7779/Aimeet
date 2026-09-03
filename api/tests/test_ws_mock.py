import os

from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from app.main import app
from app.routes import sessions


def test_mock_websocket_replays_demo_script() -> None:
    os.environ["MOCK_SPEED"] = "50"
    client = TestClient(app)
    session_id = client.post("/sessions").json()["id"]
    events: list[dict] = []

    try:
        with client.websocket_connect(f"/ws/live/{session_id}") as websocket:
            while True:
                try:
                    events.append(websocket.receive_json())
                except WebSocketDisconnect:
                    break
    finally:
        os.environ.pop("MOCK_SPEED", None)
        sessions.pop(session_id, None)

    grounded = [event for event in events if event["type"] == "grounded_event"]
    decisions = [event for event in events if event["type"] == "decision"]
    alerts = [event["payload"] for event in events if event["type"] == "alert"]

    assert len(grounded) >= 2
    assert len(decisions) >= 2
    assert any(
        alert["kind"] == "conflict" and ("850" in alert["detail"] or "20%" in alert["detail"])
        for alert in alerts
    )
    assert any(alert["kind"] == "slide_mismatch" for alert in alerts)
