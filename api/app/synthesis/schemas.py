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


class KeyFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact: str
    quote: str = Field(..., description="逐字稿原句片段；fact 只能改寫這段，不能補上其中沒有的主詞")
    speaker: str | None = Field(...)
    ts: float | None = Field(...)
    category: Literal["number", "date", "person", "constraint", "requirement", "action", "other"]


# --- Pipeline stage outputs -------------------------------------------------


class Extraction(BaseModel):
    """Stage 1: everything factual, nothing derived."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    key_facts: list[KeyFact] = Field(...)
    decision_table: list[DecisionRow] = Field(...)
    open_questions: list[str] = Field(...)
    uncertainties: list[str] = Field(...)


class Coverage(BaseModel):
    """Stage 2: facts present in the utterances but missing from key_facts."""

    model_config = ConfigDict(extra="forbid")

    missing: list[KeyFact] = Field(...)


class Diagram(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mermaid: str
    mermaid_caption: str


class Prd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prd_markdown: str


class WorkItems(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_items: list[WorkItem] = Field(...)


# --- Final report (shape consumed by the frontend) ---------------------------


class MeetingReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    key_facts: list[KeyFact] = Field(...)
    decision_table: list[DecisionRow] = Field(...)
    mermaid: str
    mermaid_caption: str
    prd_markdown: str
    work_items: list[WorkItem] = Field(...)
    open_questions: list[str] = Field(...)
    uncertainties: list[str] = Field(...)
