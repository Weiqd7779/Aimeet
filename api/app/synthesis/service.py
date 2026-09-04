"""Post-meeting synthesis as a small pipeline; each model call has exactly one job.

1. extract   record JSON (+frames) -> facts / decisions / questions / uncertainties
2. coverage  utterances vs key_facts -> anything the extraction missed, merged back in
3. derive    extraction -> mermaid | prd | work items   (parallel, no raw transcript)
"""

import asyncio
import json
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import settings
from app.knowledge.store import KnowledgeStore
from app.models import MeetingSession
from app.synthesis.mock import build_mock_report
from app.synthesis.prompt import (
    COVERAGE_INSTRUCTIONS,
    DIAGRAM_INSTRUCTIONS,
    EXTRACT_INSTRUCTIONS,
    PRD_INSTRUCTIONS,
    SCENE_INDEX_INSTRUCTIONS,
    WORK_ITEMS_INSTRUCTIONS,
)
from app.synthesis.record import build_record, scene_pages
from app.synthesis.schemas import (
    Coverage,
    Diagram,
    Extraction,
    MeetingReport,
    Prd,
    SceneIndex,
    WorkItems,
)

T = TypeVar("T", bound=BaseModel)
MAX_IMAGES = 8


def _frame_ids(session: MeetingSession) -> list[str]:
    """Frames worth showing the model: anchored ones first, then one cover per page."""
    referenced = [event.frame_id for event in session.grounded_events if event.frame_id]
    ordered = list(dict.fromkeys(referenced))
    for scene in session.scenes:
        if scene.cover_frame_id not in ordered:
            ordered.append(scene.cover_frame_id)
    for frame in reversed(session.frames):
        if frame.id not in ordered:
            ordered.append(frame.id)
        if len(ordered) >= MAX_IMAGES:
            break
    return ordered[:MAX_IMAGES]


def _dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=1)


async def _call(
    client: AsyncOpenAI,
    model: str,
    instructions: str,
    content: list[dict[str, str]],
    schema: type[T],
) -> T:
    response = await client.responses.parse(
        model=model,
        instructions=instructions,
        input=[{"role": "user", "content": content}],
        text_format=schema,
    )
    if response.output_parsed is None:
        raise ValueError(f"OpenAI returned no parsed {schema.__name__}")
    return response.output_parsed


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

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    record = build_record(session, knowledge)

    # 1. extract
    content: list[dict[str, str]] = [
        {"type": "input_text", "text": "會議紀錄：\n" + _dumps(record)}
    ]
    frames = {frame.id: frame for frame in session.frames}
    for frame_id in _frame_ids(session):
        if frame := frames.get(frame_id):
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{frame.jpeg_b64}",
                    "detail": "low",
                }
            )
    extraction = await _call(client, selected_model, EXTRACT_INSTRUCTIONS, content, Extraction)

    # 2. coverage check -> merge anything missed
    utterances = [item for item in record["timeline"] if item["type"] == "utterance"]
    coverage = await _call(
        client,
        selected_model,
        COVERAGE_INSTRUCTIONS,
        [
            {
                "type": "input_text",
                "text": "utterances：\n"
                + _dumps(utterances)
                + "\n\nkey_facts：\n"
                + _dumps([fact.model_dump() for fact in extraction.key_facts]),
            }
        ],
        Coverage,
    )
    key_facts = extraction.key_facts + coverage.missing

    # 3. derive artifacts from the extraction only
    basis = [
        {
            "type": "input_text",
            "text": "決策表：\n"
            + _dumps([row.model_dump() for row in extraction.decision_table])
            + "\n\n關鍵事實：\n"
            + _dumps([fact.model_dump() for fact in key_facts]),
        }
    ]
    scene_input = [
        {
            "type": "input_text",
            "text": "pages：\n"
            + _dumps(
                [
                    {k: v for k, v in page.items() if k != "items"}
                    | {
                        "utterances": [
                            {"speaker": i["speaker"], "text": i["text"]}
                            for i in page["items"]
                            if i["type"] == "utterance"
                        ]
                    }
                    for page in record["pages"]
                ]
            ),
        }
    ]
    diagram, prd, work_items, index = await asyncio.gather(
        _call(client, selected_model, DIAGRAM_INSTRUCTIONS, basis, Diagram),
        _call(client, selected_model, PRD_INSTRUCTIONS, basis, Prd),
        _call(client, selected_model, WORK_ITEMS_INSTRUCTIONS, basis, WorkItems),
        _call(client, selected_model, SCENE_INDEX_INSTRUCTIONS, scene_input, SceneIndex)
        if record["pages"]
        else _no_scenes(),
    )

    return MeetingReport(
        summary=extraction.summary,
        key_facts=key_facts,
        decision_table=extraction.decision_table,
        mermaid=diagram.mermaid,
        mermaid_caption=diagram.mermaid_caption,
        prd_markdown=prd.prd_markdown,
        work_items=work_items.work_items,
        open_questions=extraction.open_questions,
        uncertainties=extraction.uncertainties,
        scenes=scene_pages(session, index),
    )


async def _no_scenes() -> None:
    return None
