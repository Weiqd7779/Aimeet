import json

from openai import AsyncOpenAI

from app.config import settings
from app.knowledge.store import KnowledgeStore
from app.models import MeetingSession
from app.synthesis.mock import build_mock_report
from app.synthesis.prompt import INSTRUCTIONS
from app.synthesis.schemas import MeetingReport


def _frame_ids(session: MeetingSession) -> list[str]:
    referenced = [event.frame_id for event in session.grounded_events if event.frame_id]
    ordered = list(dict.fromkeys(referenced))
    for frame in reversed(session.frames):
        if frame.id not in ordered:
            ordered.append(frame.id)
        if len(ordered) == 6:
            break
    return ordered[:6]


def _input_text(session: MeetingSession, knowledge: KnowledgeStore) -> str:
    alert_sources = {alert.source for alert in session.alerts if alert.source}
    source_chunks = [
        chunk for chunk in getattr(knowledge, "_chunks", []) if chunk.source in alert_sources
    ]
    return "\n".join(
        [
            "逐字稿：",
            json.dumps([entry.model_dump() for entry in session.transcript], ensure_ascii=False),
            "Grounded events：",
            json.dumps(
                [event.model_dump() for event in session.grounded_events], ensure_ascii=False
            ),
            "決策：",
            json.dumps(
                [decision.model_dump() for decision in session.decision_state.decisions],
                ensure_ascii=False,
            ),
            "提醒與衝突處理：",
            json.dumps([alert.model_dump() for alert in session.alerts], ensure_ascii=False),
            "知識庫來源：",
            json.dumps(
                [
                    {"source": chunk.source, "id": chunk.id, "text": chunk.text}
                    for chunk in source_chunks
                ],
                ensure_ascii=False,
            ),
        ]
    )


async def synthesize(
    session: MeetingSession,
    knowledge: KnowledgeStore,
    *,
    model: str | None = None,
) -> MeetingReport:
    selected_model = model or (
        settings.openai_model_complex
        if any(decision.conflicts for decision in session.decision_state.decisions)
        or len(session.decision_state.decisions) > 3
        else settings.openai_model
    )
    if settings.synthesis_mock or not settings.openai_api_key:
        return build_mock_report(session)

    content: list[dict[str, str]] = [
        {"type": "input_text", "text": _input_text(session, knowledge)}
    ]
    frames = {frame.id: frame for frame in session.frames}
    for frame_id in _frame_ids(session):
        frame = frames.get(frame_id)
        if frame:
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{frame.jpeg_b64}",
                    "detail": "low",
                }
            )
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.responses.parse(
        model=selected_model,
        instructions=INSTRUCTIONS,
        input=[{"role": "user", "content": content}],
        text_format=MeetingReport,
    )
    if response.output_parsed is None:
        raise ValueError("OpenAI returned no parsed MeetingReport")
    return response.output_parsed
