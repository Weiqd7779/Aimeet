"""Spoken reminders via the ElevenLabs text-to-speech REST API.

POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}  (xi-api-key header)
Returns raw audio in `output_format`. `eleven_v3` understands audio tags such as
[clears throat] / [sighs]; older models would read them aloud, so they are stripped
unless the configured model is a v3 one. v3 has no `speed` setting, so "fast" is a
matter of keeping the script short (that is the consistency agent's job).
"""

import logging
import re

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
AUDIO_TAG = re.compile(r"\[[^\]\n]{1,40}\]\s*")
TIMEOUT_S = 30.0


def tts_enabled() -> bool:
    return bool(settings.elevenlabs_api_key and settings.elevenlabs_voice_id)


def prepare_text(text: str, model: str | None = None) -> str:
    model = model or settings.elevenlabs_model
    cleaned = text if model.startswith("eleven_v3") else AUDIO_TAG.sub("", text)
    return re.sub(r"[ \t]+", " ", cleaned).strip()


def _voice_settings(model: str) -> dict[str, float | bool]:
    if model.startswith("eleven_v3"):
        # v3 only honours stability (0.0 creative / 0.5 natural / 1.0 robust) + similarity
        return {"stability": 0.5, "similarity_boost": 0.8, "use_speaker_boost": True}
    return {"stability": 0.5, "similarity_boost": 0.8, "style": 0.2, "speed": 1.15}


def mime_type(output_format: str | None = None) -> str:
    codec = (output_format or settings.elevenlabs_output_format).split("_", 1)[0]
    return {"mp3": "audio/mpeg", "opus": "audio/ogg", "wav": "audio/wav", "pcm": "audio/pcm"}.get(
        codec, "application/octet-stream"
    )


async def speak(text: str, *, client: httpx.AsyncClient | None = None) -> bytes | None:
    """Audio bytes for `text`, or None when TTS is not configured / the request failed.
    Never raises: a lost reminder voice must not take the meeting session down."""
    if not tts_enabled() or not text.strip():
        return None
    model = settings.elevenlabs_model
    payload = {
        "text": prepare_text(text, model),
        "model_id": model,
        "voice_settings": _voice_settings(model),
    }
    url = ELEVENLABS_URL.format(voice_id=settings.elevenlabs_voice_id)
    params = {"output_format": settings.elevenlabs_output_format}
    headers = {"xi-api-key": settings.elevenlabs_api_key, "Content-Type": "application/json"}
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as own:
                response = await own.post(url, params=params, headers=headers, json=payload)
        else:
            response = await client.post(url, params=params, headers=headers, json=payload)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error("ElevenLabs TTS %s: %s", exc.response.status_code, exc.response.text[:300])
        return None
    except httpx.HTTPError:
        logger.exception("ElevenLabs TTS request failed")
        return None
    return response.content or None
