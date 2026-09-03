from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DecisionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    chosen: str
    alternatives: list[str] = Field(...)
    rationale: str
    status: Literal["candidate", "confirmed", "rejected"]
    conflict_resolution: str | None = Field(...)
    sources: list[str] = Field(...)
    evidence_frame_ids: list[str] = Field(...)
    evidence_ts: list[float] = Field(...)
    confidence: float


class WorkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    body_markdown: str
    labels: list[str] = Field(...)
    assignee: str | None = Field(...)
    evidence_frame_ids: list[str] = Field(...)
    kind: Literal["github_issue", "jira_task"]


class MeetingReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    decision_table: list[DecisionRow] = Field(...)
    mermaid: str
    mermaid_caption: str
    prd_markdown: str
    work_items: list[WorkItem] = Field(...)
    open_questions: list[str] = Field(...)
    uncertainties: list[str] = Field(...)
