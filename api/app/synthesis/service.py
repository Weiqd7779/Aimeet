"""Post-meeting synthesis as a small pipeline; each model call has exactly one job.

0. segment   whole transcript -> topics (where one subject ends and the next begins)
1. extract   record JSON + topics (+frames) -> facts / decisions / questions / uncertainties
2. coverage  utterances vs key_facts -> anything the extraction missed, merged back in
3. derive    topics + extraction -> mermaid | prd | work items   (parallel, no raw transcript)
"""

import asyncio
import json
import re
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
    SEGMENT_INSTRUCTIONS,
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
    Segmentation,
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
    utterances = [item for item in record["timeline"] if item["type"] == "utterance"]

    # 0. segment: read everything, then decide where the subject changes
    transcript_only = {
        k: v for k, v in record.items() if k not in ("pages", "decision_state", "knowledge_sources")
    }
    segmentation = (
        await _call(
            client,
            selected_model,
            SEGMENT_INSTRUCTIONS,
            [{"type": "input_text", "text": "會議紀錄：\n" + _dumps(transcript_only)}],
            Segmentation,
        )
        if utterances
        else Segmentation(topics=[])
    )
    topics = [topic.model_dump() for topic in segmentation.topics]

    # 1. extract
    content: list[dict[str, str]] = [
        {
            "type": "input_text",
            "text": "會議紀錄：\n" + _dumps(record) + "\n\ntopics：\n" + _dumps(topics),
        }
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
    coverage = await _call(
        client,
        selected_model,
        COVERAGE_INSTRUCTIONS,
        [
            {
                "type": "input_text",
                "text": "meeting_date：\n"
                + _dumps(record["meeting_date"])
                + "\n\ntopics：\n"
                + _dumps(topics)
                + "\n\nutterances：\n"
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
            "text": "主題段落：\n"
            + _dumps(topics)
            + "\n\n決策表：\n"
            + _dumps([row.model_dump() for row in extraction.decision_table])
            + "\n\n關鍵事實：\n"
            + _dumps([fact.model_dump() for fact in key_facts]),
        }
    ]
    diagram, prd, work_items, index = await asyncio.gather(
        _call(client, selected_model, DIAGRAM_INSTRUCTIONS, basis, Diagram),
        _call(client, selected_model, PRD_INSTRUCTIONS, basis, Prd),
        _call(client, selected_model, WORK_ITEMS_INSTRUCTIONS, basis, WorkItems),
        _index_scenes(client, selected_model, record["pages"]),
    )

    measurable = extraction.decision_table or any(
        fact.category in ("number", "constraint") for fact in key_facts
    )
    report = MeetingReport(
        summary=extraction.summary,
        topics=segmentation.topics,
        key_facts=key_facts,
        decision_table=extraction.decision_table,
        mermaid=diagram.mermaid,
        mermaid_caption=diagram.mermaid_caption,
        prd_markdown=prd.prd_markdown
        if measurable
        else strip_sections(prd.prd_markdown, "驗收標準"),
        work_items=work_items.work_items,
        open_questions=extraction.open_questions,
        uncertainties=extraction.uncertainties,
        scenes=scene_pages(session, index),
    )
    report.uncertainties.extend(ungrounded_dates(report))
    return report


def _scene_input(pages: list[dict]) -> list[dict[str, str]]:
    return [
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
                    for page in pages
                ]
            ),
        }
    ]


async def _index_scenes(client: AsyncOpenAI, model: str, pages: list[dict]) -> SceneIndex | None:
    """Title + summary per page. The model occasionally drops a page from its answer,
    which surfaced as an empty '第 N 頁' card; ask again for just the missing ones."""
    if not pages:
        return None
    index = await _call(client, model, SCENE_INDEX_INSTRUCTIONS, _scene_input(pages), SceneIndex)
    got = {entry.scene_id for entry in index.scenes}
    if missing := [page for page in pages if page["scene_id"] not in got]:
        retry = await _call(
            client, model, SCENE_INDEX_INSTRUCTIONS, _scene_input(missing), SceneIndex
        )
        index.scenes.extend(retry.scenes)
    return index


def strip_sections(markdown: str, heading: str) -> str:
    """Drop every `#… heading` section (through the next heading of equal or higher level).
    Used for acceptance criteria when nothing in the meeting was measurable: the model
    otherwise pads the section by restating the feature description as criteria."""
    out: list[str] = []
    skip_level = 0
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,6})\s+(.*)", line)
        if match:
            level = len(match.group(1))
            if skip_level and level <= skip_level:
                skip_level = 0
            if heading in match.group(2):
                skip_level = level
                continue
        if not skip_level:
            out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
RELATIVE_TIME = re.compile(
    r"下週[一二三四五六日]?|下周|下個月|月底|兩週內|下星期|next week|tomorrow"
)


def ungrounded_dates(report: MeetingReport) -> list[str]:
    """Dates the derived artifacts use that no key fact resolved to. The model was told
    to use only `resolved_date`; anything else is flagged so a wrong date is visible
    instead of silently authoritative (the PRD once said 「下週三」 for a 9/29 launch)."""
    allowed = {f.resolved_date for f in report.key_facts if f.resolved_date}
    derived = [report.prd_markdown, report.summary] + [
        f"{w.title}\n{w.body_markdown}" for w in report.work_items
    ]
    problems: list[str] = []
    for text in derived:
        for match in ISO_DATE.finditer(text):
            if match.group(0) not in allowed:
                problems.append(f"報告出現無法對回逐字稿的日期：{match.group(0)}")
        for match in RELATIVE_TIME.finditer(text):
            if not any(match.group(0) in f.quote for f in report.key_facts):
                problems.append(f"報告出現逐字稿沒有的相對時間：「{match.group(0)}」")
    return list(dict.fromkeys(problems))
