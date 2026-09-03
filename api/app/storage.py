import base64
import binascii
import json
import logging
from pathlib import Path

from app.config import settings
from app.models import GroundedVisualEvent

logger = logging.getLogger(__name__)


def session_dir(session_id: str) -> Path:
    return Path(settings.data_dir) / f"session_{session_id}"


def save_frame(session_id: str, frame_id: str, jpeg_b64: str) -> Path | None:
    directory = session_dir(session_id) / "frames"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{frame_id}.jpg"
    try:
        path.write_bytes(base64.b64decode(jpeg_b64, validate=True))
    except (binascii.Error, ValueError, OSError):
        logger.exception("Failed to persist frame %s", frame_id)
        return None
    return path


def save_events(session_id: str, events: list[GroundedVisualEvent]) -> Path | None:
    directory = session_dir(session_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "events.json"
    payload = [event.model_dump(mode="json") for event in events if event.lifecycle == "closed"]
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("Failed to persist events for session %s", session_id)
        return None
    return path
