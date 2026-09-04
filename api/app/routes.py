import base64
import binascii
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import settings
from app.knowledge.store import store
from app.live.session import LiveSessionManager
from app.models import MeetingSession
from app.record.store import load_session, save_report
from app.synthesis.service import synthesize as synthesize_report

router = APIRouter()
sessions: dict[str, MeetingSession] = {}


class SynthesisRequest(BaseModel):
    model: str | None = None
    force: bool = False


def _session(session_id: str) -> MeetingSession:
    """In-memory session, or the one rebuilt from its on-disk record after a restart."""
    session = sessions.get(session_id)
    if session is None:
        session = load_session(settings.record_dir, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        sessions[session_id] = session
    return session


@router.post("/sessions", status_code=201)
async def create_session() -> dict[str, str]:
    session = MeetingSession()
    sessions[session.id] = session
    return {"id": session.id}


@router.websocket("/ws/live/{session_id}")
async def live_websocket(websocket: WebSocket, session_id: str) -> None:
    session = sessions.get(session_id)
    if session is None:
        await websocket.close(code=1008, reason="Session not found")
        return
    try:
        await LiveSessionManager(websocket, session, store).run()
    except WebSocketDisconnect:
        return


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    payload = _session(session_id).model_dump(mode="json")
    for frame in payload["frames"]:
        frame.pop("jpeg_b64", None)
    return payload


@router.get("/sessions/{session_id}/frames/{frame_id}.jpg")
async def get_frame(session_id: str, frame_id: str) -> Response:
    session = _session(session_id)
    frame = next((item for item in session.frames if item.id == frame_id), None)
    if frame is not None and frame.jpeg_b64:
        try:
            data = base64.b64decode(frame.jpeg_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Invalid frame data") from exc
        return Response(content=data, media_type="image/jpeg")
    on_disk = Path(settings.record_dir) / session_id / "frames" / f"{frame_id}.jpg"
    if not on_disk.exists():
        raise HTTPException(status_code=404, detail="Frame not found")
    return Response(content=on_disk.read_bytes(), media_type="image/jpeg")


def _record_path(session_id: str, name: str) -> Path:
    _session(session_id)
    path = Path(settings.record_dir) / session_id / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Record not written yet")
    return path


@router.get("/sessions/{session_id}/record")
async def get_record(session_id: str) -> Response:
    """Fixed-schema meeting record (aimeet.record.v1) as persisted on disk."""
    return Response(
        content=_record_path(session_id, "record.json").read_bytes(),
        media_type="application/json",
    )


@router.get("/sessions/{session_id}/record.md")
async def get_record_markdown(session_id: str) -> Response:
    return Response(
        content=_record_path(session_id, "record.md").read_bytes(),
        media_type="text/markdown; charset=utf-8",
    )


@router.get("/knowledge")
async def list_knowledge() -> list[dict[str, str]]:
    return store.documents()


@router.get("/knowledge/search")
async def search_knowledge(q: str, k: int = 5) -> list[dict]:
    return [chunk.__dict__ for chunk in store.search(q, k=k)]


@router.post("/sessions/{session_id}/synthesize")
async def synthesize(
    session_id: str,
    request: SynthesisRequest | None = None,
) -> dict:
    session = _session(session_id)
    request = request or SynthesisRequest()
    force = request.force
    model = request.model
    if session.report is None or force:
        session.report = await synthesize_report(session, store, model=model)
        session.report_model = model or (
            settings.openai_model_complex
            if any(decision.conflicts for decision in session.decision_state.decisions)
            or len(session.decision_state.decisions) > 3
            else settings.openai_model
        )
        session.report_mock = settings.synthesis_mock or not settings.openai_api_key
        save_report(settings.record_dir, session)
    return {
        "report": session.report.model_dump(mode="json"),
        "model": session.report_model,
        "mock": session.report_mock,
    }


@router.get("/sessions/{session_id}/report")
async def get_report(session_id: str) -> dict:
    session = _session(session_id)
    if session.report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return {
        "report": session.report.model_dump(mode="json"),
        "model": session.report_model,
        "mock": session.report_mock,
    }
