import re

from app.live import prompt as live_prompt
from app.live import tools as live_tools
from app.synthesis import prompt as synth_prompt
from app.synthesis.schemas import KeyFact, MeetingReport, WorkItem
from app.synthesis.service import ungrounded_dates

# 「下週三」 in a prompt *example* ended up in a real PRD. No prompt may contain a concrete
# date-like token again; rules must be stated abstractly.
CONCRETE_DATE = re.compile(
    r"下週[一二三四五六日]|下周|\d{1,2}月\d{1,2}[日號]|20\d{2}-\d{2}-\d{2}|\b\d{1,2}/\d{1,2}\b"
)


def test_prompts_and_tool_schemas_contain_no_concrete_date_examples() -> None:
    texts = [getattr(synth_prompt, name) for name in dir(synth_prompt) if name.isupper()] + [
        getattr(live_prompt, name) for name in dir(live_prompt) if name.isupper()
    ]
    texts.append(str(live_tools.TOOL_DEFINITIONS) + str(live_tools.VISION_TOOL_DEFINITIONS))
    for text in texts:
        assert not CONCRETE_DATE.search(text), CONCRETE_DATE.search(text).group(0)  # type: ignore[union-attr]


def _fact(fact: str, quote: str, resolved: str | None) -> KeyFact:
    return KeyFact(
        fact=fact, quote=quote, speaker="我", ts=1.0, category="date", resolved_date=resolved
    )


def _report(prd: str, facts: list[KeyFact]) -> MeetingReport:
    return MeetingReport(
        summary="s",
        key_facts=facts,
        decision_table=[],
        mermaid="graph TD",
        mermaid_caption="",
        prd_markdown=prd,
        work_items=[
            WorkItem(
                title="t",
                body_markdown=prd,
                labels=[],
                assignee=None,
                evidence_frame_ids=[],
                kind="github_issue",
            )
        ],
        open_questions=[],
        uncertainties=[],
    )


def test_dates_in_derived_text_must_come_from_resolved_facts() -> None:
    facts = [_fact("9月29號推出", "我會在9月29號的時候推出這個東西", "2026-09-29")]
    assert ungrounded_dates(_report("預計 2026-09-29 推出。", facts)) == []
    flagged = ungrounded_dates(_report("預計於下週三推出，即 2026-09-10。", facts))
    assert any("2026-09-10" in p for p in flagged)
    assert any("下週三" in p for p in flagged)


def test_relative_word_is_fine_when_the_speaker_actually_said_it() -> None:
    facts = [_fact("下週三前發測試計畫", "我會在下週三前把測試計畫發給大家", "2026-09-09")]
    assert ungrounded_dates(_report("測試計畫：下週三前（2026-09-09）。", facts)) == []
