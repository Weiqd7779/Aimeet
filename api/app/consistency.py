"""Consistency agent: catches the meeting contradicting itself.

Separate from the listen-step reasoner (which extracts decisions / anchors): this one
keeps a ledger of commitments — what, who, when — and, for every new utterance, asks
whether it contradicts something already on the ledger. POC scope: *time* and *assignee*
conflicts only.

A finding carries two texts: `detail` (terse, for the silent-reminder card) and `speech`
(a short spoken script for the TTS voice). An explicit correction ("改成星期五", "不是小王，
是小李") is an update, not a conflict — only an unacknowledged different statement is.
"""

import json
import logging
import re
from collections import deque
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from app.config import settings
from app.models import TranscriptEntry, new_id

logger = logging.getLogger(__name__)

CONTEXT_TURNS = 10
LEDGER_MAX = 40
ConflictKind = Literal["time", "assignee"]

# Only sentences that carry a deadline or an owner can create or break a commitment.
TIME_CUE = re.compile(
    r"[這下上本]?(?:星期|週|周|禮拜)[一二三四五六日天]?|月底|月初|年底|明天|後天|今天|下個月|這個月"
    r"|\d{1,2}\s*(?:月|/)\s*\d{1,2}\s*(?:日|號)?|\d{1,2}\s*(?:日|號)|(?:兩|三|[0-9]+)\s*(?:週|周|天)內"
    r"|\b(?:next|this)\s+(?:week|monday|tuesday|wednesday|thursday|friday|month)\b|\btomorrow\b"
    r"|\bby\s+(?:friday|monday|tuesday|wednesday|thursday|eod)\b",
    re.IGNORECASE,
)
OWNER_CUE = re.compile(
    r"負責|交給|由.{1,6}(?:來|處理|做|跟|接)|指派|派給|請.{1,4}(?:處理|做|跟|負責|來)|接手|認領|owner"
    r"|\b(?:assign(?:ed)?|owns?|will handle|takes? (?:it|this))\b",
    re.IGNORECASE,
)
# Explicit corrections: the speaker knows they are changing something.
CORRECTION = re.compile(
    r"改成|改為|更正|修正|更改|不是.{1,12}(?:是|而是)|抱歉|對不起|說錯|講錯|調整為|延到|提前到"
)


def has_cue(text: str) -> bool:
    return bool(TIME_CUE.search(text) or OWNER_CUE.search(text))


class Commitment(BaseModel):
    id: str = Field(default_factory=lambda: new_id()[:8])
    task: str  # 事：what has to be done, as a short noun phrase
    owner: str | None = None  # 人：who, as named in the meeting
    due: str | None = None  # 時間：the speaker's own words（「下星期三」）
    due_date: str | None = None  # YYYY-MM-DD when it can be resolved, else None
    speaker: str | None = None
    quote: str = ""
    ts: float = 0.0


class Inconsistency(BaseModel):
    kind: ConflictKind
    task: str
    previous: str  # earlier value (owner or time) as said
    current: str  # the new, conflicting value as said
    previous_quote: str = ""
    current_quote: str = ""
    detail: str  # terse card text: 事／人／時間
    speech: str  # spoken reminder, conversational, short


class CommitmentUpdate(BaseModel):
    task: str
    owner: str | None = None
    due: str | None = None
    due_date: str | None = None
    replaces_id: str | None = None  # id of the ledger entry this restates / changes


class ConsistencyVerdict(BaseModel):
    commitments: list[CommitmentUpdate] = Field(default_factory=list)
    conflicts: list[Inconsistency] = Field(default_factory=list)


INSTRUCTIONS = """你是會議的「資訊一致性」代理。另一個代理負責整理決策；你只做一件事：
盯著會中對「事情、負責人、時間」的承諾，找出前後矛盾。本版只處理兩種衝突：
- time：同一件事，先前說的期限和現在說的不同（「下星期三」vs「這星期五」）。
- assignee：同一件事，先前說的負責人和現在說的不同（「小王負責」vs「交給小李」）。

你會收到：帳本（目前已記錄的承諾，含 id）、最近對話、以及「最新一句」。只針對最新一句判斷。

規則：
1. 最新一句若新增或重述一項承諾（有事情＋負責人或期限），放進 commitments。
   同一件事已在帳本 → 填 replaces_id，並帶上合併後最新的 owner / due（沒提到的欄位沿用帳本）。
   task 用簡短名詞片語（「API 串接」「測試計畫」），不同說法指同一件事就視為同一件。
2. 最新一句對帳本某項承諾給出「不同」的負責人或期限，且說話者沒有明講自己在修改
   （沒有「改成」「更正」「不是 X 是 Y」「延到」這類字眼）→ 這是衝突，放進 conflicts。
   明講在修改的 → 只更新，不算衝突。內容相同、只是換個說法（「週三」＝「星期三」）→ 不算衝突。
   單純重述、追問、確認（「所以是下週三對吧？」）→ 不算衝突。
3. 時間換算：由 due 推 due_date（YYYY-MM-DD，以提供的會議日期為基準）；推不出就 null。
   兩個期限的 due_date 相同就不是衝突。
4. previous_quote 照抄帳本那項承諾的 quote（先前那句原話）；current_quote 照抄最新一句原話。
   兩者都不要改寫或截斷——前端會把它們並排當證據顯示。
5. detail 格式固定、要精簡：「事：{task}｜人：{owner 或 未指定}｜時間：{先前} → {現在}」
   （assignee 衝突則是「人：{先前} → {現在}｜時間：{due 或 未定}」）。
6. speech 是給語音助理唸的口語稿，台灣繁體中文、三句以內、不要條列、不要重複 detail 的符號。
   可以在開頭用一個 ElevenLabs v3 audio tag（例如 [clears throat]）。範例：
   「[clears throat] 嗯，提醒一下，這邊好像跟剛剛說的有一點出入。剛才確認 API 串接是下星期三，
   現在聽到的是這星期五。要不要確認一下以哪個為準？」
沒有事就回空清單。只輸出 JSON，所有文字使用台灣繁體中文。"""


def _dumps(items: list[BaseModel]) -> str:
    return json.dumps([item.model_dump() for item in items], ensure_ascii=False, indent=1)


class ConsistencyAgent:
    def __init__(
        self,
        *,
        client: AsyncOpenAI | None = None,
        model: str | None = None,
        mock: bool | None = None,
    ) -> None:
        self.ledger: list[Commitment] = []
        self.findings: list[Inconsistency] = []
        self._history: deque[tuple[str | None, str]] = deque(maxlen=CONTEXT_TURNS)
        self._mock = (
            mock
            if mock is not None
            else (
                settings.mock_mode
                or settings.live_provider == "mock"
                or not settings.openai_api_key
            )
        )
        self._client = client
        self._model = model or settings.openai_model

    # --- public ---------------------------------------------------------------

    async def observe(self, entry: TranscriptEntry, meeting_date: str) -> list[Inconsistency]:
        """Fold one utterance into the ledger; return the contradictions it introduced."""
        text = entry.text.strip()
        if not text:
            return []
        self._history.append((entry.speaker, text))
        if not has_cue(text):
            return []
        try:
            verdict = (
                self._mock_verdict(entry)
                if self._mock
                else await self._llm_verdict(entry, meeting_date)
            )
        except Exception:
            logger.exception("consistency check failed")
            return []
        self._apply(verdict, entry)
        self.findings.extend(verdict.conflicts)
        return verdict.conflicts

    # --- ledger ---------------------------------------------------------------

    def _apply(self, verdict: ConsistencyVerdict, entry: TranscriptEntry) -> None:
        for update in verdict.commitments:
            existing = self._find(update.replaces_id, update.task)
            if existing:
                existing.owner = update.owner or existing.owner
                if update.due:
                    existing.due, existing.due_date = update.due, update.due_date
                existing.speaker, existing.quote, existing.ts = entry.speaker, entry.text, entry.ts
                continue
            self.ledger.append(
                Commitment(
                    task=update.task,
                    owner=update.owner,
                    due=update.due,
                    due_date=update.due_date,
                    speaker=entry.speaker,
                    quote=entry.text,
                    ts=entry.ts,
                )
            )
        del self.ledger[:-LEDGER_MAX]

    def _find(self, commitment_id: str | None, task: str) -> Commitment | None:
        if commitment_id:
            for item in self.ledger:
                if item.id == commitment_id:
                    return item
        return next(
            (item for item in self.ledger if fuzz.token_set_ratio(item.task, task) >= 75), None
        )

    # --- model ----------------------------------------------------------------

    def _payload(self, entry: TranscriptEntry, meeting_date: str) -> str:
        history = "\n".join(f"[{s or '?'}] {t}" for s, t in list(self._history)[:-1]) or "（無）"
        return (
            f"會議日期：{meeting_date}\n\n"
            f"帳本：\n{_dumps(self.ledger) if self.ledger else '（空）'}\n\n"
            f"最近對話：\n{history}\n\n"
            f"最新一句：\n[{entry.speaker or '?'}] {entry.text}"
        )

    async def _llm_verdict(self, entry: TranscriptEntry, meeting_date: str) -> ConsistencyVerdict:
        client = self._client or AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.responses.parse(
            model=self._model,
            instructions=INSTRUCTIONS,
            input=self._payload(entry, meeting_date),
            text_format=ConsistencyVerdict,
        )
        return response.output_parsed or ConsistencyVerdict()

    # --- mock (no network) ------------------------------------------------------

    def _mock_verdict(self, entry: TranscriptEntry) -> ConsistencyVerdict:
        """Rule-based stand-in for demos and tests: 「<task> 由 <owner> 負責，<time> 交」."""
        text = entry.text
        due = next((m.group(0) for m in TIME_CUE.finditer(text)), None)
        owner_match = _MOCK_OWNER.search(text)
        owner = (owner_match.group(1) or owner_match.group(2)) if owner_match else None
        if not (due or owner) or re.search(r"[？?]|對吧|嗎[。！]?$", text):
            return ConsistencyVerdict()  # questions / confirmations restate, never commit
        task = _mock_task(text, owner, due)
        existing = self._find(None, task) if task else None
        if not task and not existing:
            return ConsistencyVerdict()
        update = CommitmentUpdate(
            task=task or (existing.task if existing else "未命名事項"),
            owner=owner,
            due=due,
            replaces_id=existing.id if existing else None,
        )
        conflicts: list[Inconsistency] = []
        if existing and not CORRECTION.search(text):
            if due and existing.due and _norm_time(due) != _norm_time(existing.due):
                conflicts.append(
                    _finding(
                        "time",
                        existing.task,
                        existing.owner,
                        existing.due,
                        due,
                        existing.quote,
                        text,
                    )
                )
            if owner and existing.owner and owner != existing.owner:
                conflicts.append(
                    _finding(
                        "assignee",
                        existing.task,
                        None,
                        existing.owner,
                        owner,
                        existing.quote,
                        text,
                        due=due or existing.due,
                    )
                )
        return ConsistencyVerdict(commitments=[update], conflicts=conflicts)


def _norm_time(value: str) -> str:
    return (
        re.sub(r"\s+", "", value)
        .replace("週", "星期")
        .replace("周", "星期")
        .replace("禮拜", "星期")
    )


_NAME = r"(?:[\u4e00-\u9fff]{2,3}?|[A-Za-z]+)"
_MOCK_OWNER = re.compile(
    rf"(?:由|交給|請|派給|讓)\s*({_NAME})(?=\s*(?:負責|來|處理|做|接|跟|，|,|。|$))"
    rf"|({_NAME})\s*(?:負責|來做|接手|處理)"
)
_TASK_STRIP = re.compile(
    rf"(?:由|交給|請|派給|讓)\s*{_NAME}(?:負責|來做|接手|處理)?"
    rf"|{_NAME}\s*(?:負責|來做|接手|處理)"
    r"|那|就|然後|我們|這樣|好|的話|之前|以前|要|會|交|完成|做完|給|吧|喔|嗎|對|也|再|一下|確認"
)


def _mock_task(text: str, owner: str | None, due: str | None) -> str:
    stripped = TIME_CUE.sub("", text)
    stripped = _TASK_STRIP.sub("", stripped)
    if owner:
        stripped = stripped.replace(owner, "")
    first = re.split(r"[，,。．、！!？?：:；;]+", stripped.strip())[0]
    return re.sub(r"\s+", " ", first).strip()[:12]


def _finding(
    kind: ConflictKind,
    task: str,
    owner: str | None,
    previous: str,
    current: str,
    previous_quote: str,
    current_quote: str,
    *,
    due: str | None = None,
) -> Inconsistency:
    if kind == "time":
        detail = f"事：{task}｜人：{owner or '未指定'}｜時間：{previous} → {current}"
        speech = (
            f"[clears throat] 嗯，提醒一下，{task}的時間好像跟剛剛說的有一點出入。"
            f"剛才確認的是{previous}，現在聽到的是{current}。要不要確認一下以哪個為準？"
        )
    else:
        detail = f"事：{task}｜人：{previous} → {current}｜時間：{due or '未定'}"
        speech = (
            f"[clears throat] 嗯，提醒一下，{task}的負責人好像跟剛剛說的不一樣。"
            f"剛才說的是{previous}，現在聽到的是{current}。要不要確認一下是誰負責？"
        )
    return Inconsistency(
        kind=kind,
        task=task,
        previous=previous,
        current=current,
        previous_quote=previous_quote,
        current_quote=current_quote,
        detail=detail,
        speech=speech,
    )
