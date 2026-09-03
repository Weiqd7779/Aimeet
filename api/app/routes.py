import base64
import binascii

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from app.knowledge.store import store
from app.live.session import LiveSessionManager
from app.models import MeetingSession

router = APIRouter()
sessions: dict[str, MeetingSession] = {}


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
async def synthesize(session_id: str) -> None:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    raise HTTPException(status_code=501, detail="Synthesis is not implemented yet")
