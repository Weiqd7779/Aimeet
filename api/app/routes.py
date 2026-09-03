import base64
import binascii

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import settings
from app.knowledge.store import store
from app.live.session import LiveSessionManager
from app.models import MeetingSession
from app.synthesis.service import synthesize as synthesize_report

router = APIRouter()
sessions: dict[str, MeetingSession] = {}


class SynthesisRequest(BaseModel):
    model: str | None = None
    force: bool = False


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
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    payload = session.model_dump(mode="json")
    for frame in payload["frames"]:
        frame.pop("jpeg_b64", None)
    return payload


@router.get("/sessions/{session_id}/frames/{frame_id}.jpg")
async def get_frame(session_id: str, frame_id: str) -> Response:
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    frame = next((item for item in session.frames if item.id == frame_id), None)
    if frame is None:
        raise HTTPException(status_code=404, detail="Frame not found")
    try:
        data = base64.b64decode(frame.jpeg_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid frame data") from exc
    return Response(content=data, media_type="image/jpeg")


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
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
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
    return {
        "report": session.report.model_dump(mode="json"),
        "model": session.report_model,
        "mock": session.report_mock,
    }


@router.get("/sessions/{session_id}/report")
async def get_report(session_id: str) -> dict:
    session = sessions.get(session_id)
    if session is None or session.report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return {
        "report": session.report.model_dump(mode="json"),
        "model": session.report_model,
        "mock": session.report_mock,
    }
