import json
import logging
import re
from typing import Any

from google import genai
from google.genai import types

from app.config import settings
from app.knowledge.store import Chunk
from app.models import Alert, Decision

logger = logging.getLogger(__name__)

COST_PATTERN = re.compile(
    r"(?P<option>Prototype\s+[A-Z])[^。\n]{0,50}?NT\$\s?(?P<cost>[\d,]+)",
    re.IGNORECASE,
)
LIMIT_PATTERN = re.compile(r"上限[^。\n]{0,30}?NT\$\s?(?P<limit>[\d,]+)")


def _number(value: str) -> int:
    return int(value.replace(",", ""))


def _mock_conflicts(decision: Decision, hits: list[Chunk]) -> list[Alert]:
    corpus = "\n".join(hit.text for hit in hits)
    alerts: list[Alert] = []
    limit_match = LIMIT_PATTERN.search(corpus)
    if limit_match:
        limit = _number(limit_match.group("limit"))
        for cost_match in COST_PATTERN.finditer(corpus):
            option = cost_match.group("option")
            if option.lower() not in decision.chosen.lower():
                continue
            cost = _number(cost_match.group("cost"))
            if cost <= limit:
                continue
            percent = round((cost - limit) / limit * 100)
            source = next((hit.source for hit in hits if cost_match.group(0) in hit.text), None)
            alerts.append(
                Alert(
                    ts=decision.ts,
                    kind="conflict",
                    title="Potential Conflict",
                    detail=f"{option} 成本 NT${cost:,} 超出既有上限 NT${limit:,} {percent}%。",
                    source=source,
                    decision_id=decision.id,
                )
            )
            break

    if "直接連資料庫" in decision.chosen and any(
        hit.id.startswith("adr-004") or "API Gateway 不直接連資料庫" in hit.text for hit in hits
    ):
        source = next(
            (
                hit.source
                for hit in hits
                if hit.id.startswith("adr-004") or "API Gateway 不直接連資料庫" in hit.text
            ),
            None,
        )
        alerts.append(
            Alert(
                ts=decision.ts,
                kind="conflict",
                title="Potential Conflict",
                detail="此決策違反 ADR-004：API Gateway 不得直接連資料庫，必須經過 service layer。",
                source=source,
                decision_id=decision.id,
            )
        )
    return alerts


async def _generate_live_conflict(decision: Decision, hits: list[Chunk]) -> list[Alert]:
    client = genai.Client(api_key=settings.gemini_api_key)
    schema = {
        "type": "OBJECT",
        "properties": {
            "has_conflict": {"type": "BOOLEAN"},
            "title": {"type": "STRING"},
            "detail": {"type": "STRING"},
            "source_id": {"type": "STRING"},
        },
        "required": ["has_conflict", "title", "detail", "source_id"],
    }
    prompt = (
        "請檢查以下決策是否與知識庫衝突，只回傳 JSON。\n"
        f"決策：{decision.model_dump_json()}\n"
        f"來源：{json.dumps([hit.__dict__ for hit in hits], ensure_ascii=False)}"
    )
    response = await client.aio.models.generate_content(
        model=settings.gemini_text_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    data: dict[str, Any] = json.loads(response.text or "{}")
    if not data.get("has_conflict"):
        return []
    return [
        Alert(
            ts=decision.ts,
            kind="conflict",
            title=data.get("title") or "Potential Conflict",
            detail=data.get("detail") or "Knowledge base conflict detected.",
            source=data.get("source_id") or None,
            decision_id=decision.id,
        )
    ]


async def check_conflict(decision: Decision, hits: list[Chunk]) -> list[Alert]:
    alerts = _mock_conflicts(decision, hits)
    if settings.mock_mode:
        return alerts
    try:
        live_alerts = await _generate_live_conflict(decision, hits)
    except Exception:
        logger.exception("Live conflict check failed")
        return alerts
    for live_alert in live_alerts:
        if any(
            alert.source == live_alert.source and alert.detail == live_alert.detail
            for alert in alerts
        ):
            continue
        alerts.append(live_alert)
    return alerts
