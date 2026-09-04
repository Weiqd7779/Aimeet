from app.models import MeetingSession
from app.synthesis.record import scene_pages
from app.synthesis.schemas import DecisionRow, KeyFact, MeetingReport, WorkItem


def _decision_row(session: MeetingSession, decision_id: str) -> DecisionRow:
    decision = next(item for item in session.decision_state.decisions if item.id == decision_id)
    linked_alerts = [alert for alert in session.alerts if alert.id in decision.conflicts]
    evidence = [
        event
        for event in session.grounded_events
        if decision.chosen in event.target or decision.topic in event.utterance
    ]
    sources = [alert.source for alert in linked_alerts if alert.source]
    resolution = None
    if linked_alerts:
        resolution = "; ".join(f"{alert.detail}（{alert.status}）" for alert in linked_alerts)
    rationale = "；".join(decision.reasons_for) or "會議中提出的選擇"
    if decision.reasons_against:
        rationale += f"；考量：{'；'.join(decision.reasons_against)}"
    confidence = sum(event.confidence for event in evidence) / len(evidence) if evidence else 0.6
    return DecisionRow(
        topic=decision.topic,
        chosen=decision.chosen,
        alternatives=decision.alternatives,
        rationale=rationale,
        status=decision.status,
        conflict_resolution=resolution,
        sources=sources,
        evidence_frame_ids=[event.frame_id for event in evidence if event.frame_id],
        evidence_ts=[event.ts for event in evidence] or [decision.ts],
        confidence=confidence,
    )


def build_mock_report(session: MeetingSession) -> MeetingReport:
    rows = [_decision_row(session, decision.id) for decision in session.decision_state.decisions]
    has_gateway_decision = any(
        "直接連資料庫" in decision.chosen for decision in session.decision_state.decisions
    )
    if has_gateway_decision:
        mermaid = "flowchart LR\n  Gateway[API Gateway] --> Service[Service Layer]\n  Service --> Redis[Redis Cache]\n  Redis --> DB[(Database)]"
        caption = "API Gateway 的資料存取路徑"
    else:
        options = session.decision_state.options_under_comparison or ["Decision", "Option"]
        nodes = "\n".join(
            f'  Decision["Decision"] --> Option{index}["{option}"]'
            for index, option in enumerate(options)
        )
        mermaid = f"flowchart LR\n{nodes}"
        caption = "會議選項與決策關係"
    work_items = [
        WorkItem(
            title=f"落地決策：{decision.topic}",
            body_markdown=(
                f"### 背景\n會議決定採用 **{decision.chosen}**。\n\n"
                "### 驗收條件\n- 實作決策內容並記錄驗證結果\n"
                "- 回顧相關衝突與限制條件"
            ),
            labels=["decision", "meeting-follow-up"],
            assignee=None,
            evidence_frame_ids=[
                event.frame_id
                for event in session.grounded_events
                if event.frame_id and (decision.chosen in event.target)
            ],
            kind="github_issue",
        )
        for decision in session.decision_state.decisions
    ]
    key_facts = [
        KeyFact(
            fact=f"{decision.topic}：{decision.chosen}",
            quote=decision.chosen,
            speaker=None,
            ts=decision.ts,
            category="other",
        )
        for decision in session.decision_state.decisions
    ]
    return MeetingReport(
        summary=f"本次會議整理出 {len(rows)} 項決策，並保留其 grounding 與衝突脈絡。",
        key_facts=key_facts,
        decision_table=rows,
        mermaid=mermaid,
        mermaid_caption=caption,
        prd_markdown=(
            "# 會議決策 PRD\n\n## 功能描述\n"
            "將會議中確認的決策轉化為可追蹤的工作項目，並保留證據來源。\n\n"
            "## 驗收標準\n- 每項決策都有狀態與選擇理由\n"
            "- 報告可回溯至逐字稿 timestamp 或 frame id\n"
        ),
        work_items=work_items,
        open_questions=[],
        uncertainties=["Mock synthesis 未使用語意模型補充未明確說出的資訊。"],
        scenes=scene_pages(session),
    )
