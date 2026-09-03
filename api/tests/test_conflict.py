import asyncio
from types import SimpleNamespace

from app.config import settings
from app.conflict import ConflictVerdict, check_conflict
from app.knowledge.store import store
from app.models import Decision


def test_cost_limit_conflict() -> None:
    decision = Decision(ts=15, topic="Q4 主打原型", chosen="Prototype B")
    alerts = asyncio.run(check_conflict(decision, store.search("Q4 主打原型 Prototype B")))

    assert len(alerts) == 1
    assert alerts[0].kind == "conflict"
    assert "850" in alerts[0].detail
    assert "20%" in alerts[0].detail


def test_direct_database_conflict() -> None:
    decision = Decision(
        ts=24,
        topic="API Gateway 資料存取",
        chosen="API Gateway 直接連資料庫",
    )
    alerts = asyncio.run(check_conflict(decision, store.search("API Gateway 直接連資料庫")))

    assert len(alerts) == 1
    assert alerts[0].kind == "conflict"
    assert "ADR-004" in alerts[0].detail


def test_prototype_c_is_within_cost_limit() -> None:
    decision = Decision(ts=15, topic="Q4 主打原型", chosen="Prototype C")

    assert asyncio.run(check_conflict(decision, store.search("Q4 主打原型 Prototype C"))) == []


def test_openai_conflict_false_preserves_rule_alert(monkeypatch) -> None:
    class FakeResponses:
        async def parse(self, **kwargs):
            return SimpleNamespace(
                output_parsed=ConflictVerdict(
                    has_conflict=False,
                    title="",
                    detail="",
                    source_id="",
                )
            )

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr("app.conflict.AsyncOpenAI", lambda: FakeClient())
    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(settings, "live_provider", "openai")
    monkeypatch.setattr(settings, "gemini_api_key", "")

    decision = Decision(ts=15, topic="Q4 主打原型", chosen="Prototype B")
    alerts = asyncio.run(check_conflict(decision, store.search("Q4 主打原型 Prototype B")))

    assert len(alerts) == 1
    assert "850" in alerts[0].detail
