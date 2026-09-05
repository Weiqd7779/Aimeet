"""Grade a RunResult against the scenario's `expect` block.

Deterministic rules run first (speaker attribution, script, counts). Anything that
needs semantic reading is delegated to an LLM judge that must return a verdict + reason.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel

from e2e.harness import RunResult

JUDGE_MODEL = os.environ.get("E2E_JUDGE_MODEL", "gpt-5.4")

# Characters that only exist in Simplified Chinese (their Traditional forms differ).
SIMPLIFIED = set(
    "边这动资补开实决们时间发现问题设计电应对关线经产业务认识论际将车马门风飞种类联区"
    "显确结构选择数说话记录进过为会与图续义议规则视频东还没样让给点击备长张页网络库"
    "统优势测试齐"
)


@dataclass
class Verdict:
    scenario_id: str
    passed: bool
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))
        self.passed = self.passed and ok


class JudgeAnswer(BaseModel):
    # `reason` first so the model commits to its evidence before the verdict.
    reason: str
    passed: bool


def _speakers(result: RunResult) -> list[str]:
    # conversational order = speech start time, not transcript arrival order
    ordered = sorted(result.transcripts, key=lambda entry: entry["ts"])
    return [entry.get("speaker") or "?" for entry in ordered]


def _collapse(sequence: list[str]) -> list[str]:
    collapsed: list[str] = []
    for item in sequence:
        if not collapsed or collapsed[-1] != item:
            collapsed.append(item)
    return collapsed


def hard_rules(result: RunResult) -> Verdict:
    expect = result.scenario.expect
    verdict = Verdict(result.scenario.id, True)
    transcripts = result.transcripts
    speakers = _speakers(result)

    if "speakers_only" in expect:
        extra = sorted(set(speakers) - set(expect["speakers_only"]))
        verdict.add("speakers_only", not extra, f"unexpected speakers: {extra}" if extra else "")

    for speaker, minimum in expect.get("min_transcripts_per_speaker", {}).items():
        count = speakers.count(speaker)
        verdict.add(f"min_transcripts[{speaker}]", count >= minimum, f"{count} < {minimum}")

    if "speaker_order" in expect:
        got = _collapse(speakers)
        verdict.add("speaker_order", got == expect["speaker_order"], f"got {got}")

    if "max_transcripts_per_speaker" in expect:
        for speaker, maximum in expect["max_transcripts_per_speaker"].items():
            count = speakers.count(speaker)
            verdict.add(f"max_transcripts[{speaker}]", count <= maximum, f"{count} > {maximum}")

    if expect.get("no_simplified"):
        bad = [
            (entry["text"], sorted(set(entry["text"]) & SIMPLIFIED))
            for entry in transcripts
            if set(entry["text"]) & SIMPLIFIED
        ]
        verdict.add("no_simplified", not bad, f"simplified chars: {bad}" if bad else "")

    for speaker, phrases in expect.get("must_not_contain", {}).items():
        leaked = [
            (entry["text"], phrase)
            for entry in transcripts
            if entry.get("speaker") == speaker
            for phrase in phrases
            if phrase in entry["text"]
        ]
        verdict.add(f"must_not_contain[{speaker}]", not leaked, f"leaked: {leaked}")

    statuses = [s.get("status") for s in result.payloads("status")]
    if "echo_dropped_min" in expect:
        dropped = statuses.count("echo_dropped")
        verdict.add("echo_dropped_min", dropped >= expect["echo_dropped_min"], f"{dropped}")

    decisions = result.payloads("decision")
    if "decision_chosen_contains_any" in expect:
        needles = expect["decision_chosen_contains_any"]
        hit = any(needle in d["chosen"] for d in decisions for needle in needles)
        verdict.add("decision_chosen", hit, f"chosen={[d['chosen'] for d in decisions]}")
    if "max_decisions" in expect:
        verdict.add("max_decisions", len(decisions) <= expect["max_decisions"], f"{len(decisions)}")
    if "max_decision_events" in expect:
        # restating the same decision must update it, not re-announce it over and over
        verdict.add(
            "max_decision_events",
            len(decisions) <= expect["max_decision_events"],
            f"{len(decisions)} decision events",
        )
    if "max_reasons_per_decision" in expect:
        final = {d["id"]: d for d in decisions}
        worst = max(
            (len(d["reasons_for"]) + len(d["reasons_against"]) for d in final.values()), default=0
        )
        verdict.add(
            "max_reasons_per_decision", worst <= expect["max_reasons_per_decision"], f"{worst}"
        )

    grounded = result.payloads("grounded_event")
    if "grounded_min" in expect:
        verdict.add("grounded_min", len(grounded) >= expect["grounded_min"], f"{len(grounded)}")
    if "grounded_max" in expect:
        verdict.add("grounded_max", len(grounded) <= expect["grounded_max"], f"{len(grounded)}")
    if "grounded_speaker" in expect:
        ok = grounded and all(g.get("speaker") == expect["grounded_speaker"] for g in grounded)
        verdict.add("grounded_speaker", bool(ok), f"{[g.get('speaker') for g in grounded]}")
    if expect.get("grounded_has_frame"):
        ok = grounded and all(g.get("frame_id") for g in grounded)
        verdict.add("grounded_has_frame", bool(ok), f"{[g.get('frame_id') for g in grounded]}")

    alerts = result.payloads("alert")
    if "alert_kinds_include" in expect:
        kinds = {a["kind"] for a in alerts}
        missing = set(expect["alert_kinds_include"]) - kinds
        verdict.add("alert_kinds", not missing, f"missing {missing}, got {kinds}")
    if "max_alerts" in expect:
        verdict.add("max_alerts", len(alerts) <= expect["max_alerts"], f"{len(alerts)}")
    if "inconsistency_min" in expect:
        final = {a["id"]: a for a in alerts if a["kind"] == "inconsistency"}
        verdict.add(
            "inconsistency_min",
            len(final) >= expect["inconsistency_min"],
            f"{[a['detail'] for a in final.values()]}",
        )
    if "speech_min" in expect:
        # the voice actually rendered (ElevenLabs returned audio), not just the script
        spoken = [s for s in result.payloads("speech") if s.get("audio_b64")]
        verdict.add(
            "speech_min",
            len(spoken) >= expect["speech_min"],
            f"{len(spoken)} clips, saved: {result.speech_files}",
        )
    if "max_conflicts_per_source" in expect:
        final = {a["id"]: a for a in alerts if a["kind"] == "conflict"}
        per_source: dict[str | None, int] = {}
        for alert in final.values():
            per_source[alert.get("source")] = per_source.get(alert.get("source"), 0) + 1
        worst = max(per_source.values(), default=0)
        verdict.add(
            "max_conflicts_per_source",
            worst <= expect["max_conflicts_per_source"],
            f"{per_source}",
        )

    record = result.record or {}
    scenes = record.get("scenes", [])
    seq_of = {s["id"]: s["seq"] + 1 for s in scenes}  # 1-based page numbers
    if "scenes_min" in expect:
        verdict.add("scenes_min", len(scenes) >= expect["scenes_min"], f"{len(scenes)} pages")
    if "scenes_max" in expect:
        verdict.add("scenes_max", len(scenes) <= expect["scenes_max"], f"{len(scenes)} pages")
    if expect.get("scene_covers_served"):
        bad = [s for s, ok in result.cover_frames_ok.items() if not ok]
        verdict.add("scene_covers_served", bool(scenes) and not bad, f"missing covers: {bad}")
    if "facts_on_page" in expect:
        # phrase -> expected page; pass if the utterance sits on that page or an adjacent one
        misplaced = []
        for phrase, page in expect["facts_on_page"].items():
            # "a|b|c" = accepted spellings of the same fact (830 / 八百三十)
            spellings = phrase.split("|")
            hits = [
                u
                for u in record.get("utterances", [])
                if any(alt in u["text"] for alt in spellings)
            ]
            if not hits:
                misplaced.append((phrase, "not transcribed"))
                continue
            pages = {seq_of.get(u["scene_id"]) for u in hits} | {
                seq_of.get(a) for u in hits for a in u.get("adjacent_scene_ids", [])
            }
            if page not in pages:
                misplaced.append((phrase, f"on {sorted(p for p in pages if p)} want {page}"))
        verdict.add("facts_on_page", not misplaced, f"{misplaced}" if misplaced else "")

    report_pages = (result.report or {}).get("report", {}).get("scenes", [])
    if "report_pages_min" in expect:
        verdict.add(
            "report_pages_min",
            len(report_pages) >= expect["report_pages_min"],
            f"{len(report_pages)}",
        )
    if "report_page_mentions" in expect:
        # page number -> any of these phrases must appear in that page's title or summary
        missing = []
        for page, alternatives in expect["report_page_mentions"].items():
            entry = next((p for p in report_pages if p["seq"] + 1 == int(page)), None)
            blob = f"{entry['title']} {entry['summary']}" if entry else ""
            if not any(alt in blob for alt in alternatives):
                missing.append((page, blob[:60]))
        verdict.add("report_page_mentions", not missing, f"{missing}" if missing else "")

    if expect.get("record_integrity"):
        record = result.record or {}
        utterances = record.get("utterances", [])
        live = [(t["id"], t.get("speaker"), t["text"]) for t in transcripts]
        stored = [(u["id"], u.get("speaker"), u["text"]) for u in utterances]
        verdict.add("record_matches_live", live == stored, f"live={len(live)} stored={len(stored)}")
        pending = [u["id"] for u in utterances if u["intent"] == "pending"]
        verdict.add("record_no_pending", not pending, f"pending={pending}")
        linked = {d for u in utterances for d in u["decision_ids"]}
        decision_ids = {d["id"] for d in record.get("decisions", [])}
        verdict.add(
            "record_decisions_linked", linked == decision_ids, f"{linked} vs {decision_ids}"
        )
        linked_g = {g for u in utterances for g in u["grounded_event_ids"]}
        grounded_ids = {g["id"] for g in record.get("grounded_events", [])}
        verdict.add(
            "record_grounded_linked", linked_g == grounded_ids, f"{linked_g} vs {grounded_ids}"
        )

    if "report_facts_contain_all" in expect:
        blob = json.dumps((result.report or {}).get("report", {}), ensure_ascii=False)
        # each entry is a string or a list of accepted spellings of the same fact
        missing = [
            needle
            for needle in expect["report_facts_contain_all"]
            if not any(alt in blob for alt in ([needle] if isinstance(needle, str) else needle))
        ]
        verdict.add("report_facts_contain_all", not missing, f"missing={missing}")

    if "report_decision_contains_any" in expect:
        rows = (result.report or {}).get("report", {}).get("decision_table", [])
        needles = expect["report_decision_contains_any"]
        hit = any(needle in row["chosen"] for row in rows for needle in needles)
        verdict.add("report_decision", hit, f"rows={[r['chosen'] for r in rows]}")
    if "report_max_seconds" in expect:
        verdict.add(
            "report_max_seconds",
            result.duration <= expect["report_max_seconds"],
            f"{result.duration:.1f}s",
        )
    return verdict


def _summary(result: RunResult) -> dict[str, Any]:
    return {
        "transcripts": sorted(result.transcripts, key=lambda entry: entry["ts"]),
        "decisions": result.payloads("decision"),
        "grounded_events": [
            {k: v for k, v in g.items() if k != "frame_id"}
            for g in result.payloads("grounded_event")
        ],
        "alerts": result.payloads("alert"),
        "speech": [
            {k: v for k, v in s.items() if k != "audio_b64"}
            | {"has_audio": bool(s.get("audio_b64"))}
            for s in result.payloads("speech")
        ],
        "report": (result.report or {}).get("report"),
        "record_utterances": (result.record or {}).get("utterances"),
        "pages": [
            {k: v for k, v in s.items() if k not in {"hash", "frame_ids"}}
            for s in (result.record or {}).get("scenes", [])
        ],
        "echo_dropped": [
            s.get("detail") for s in result.payloads("status") if s.get("status") == "echo_dropped"
        ],
    }


async def llm_judge(result: RunResult, verdict: Verdict) -> None:
    criteria = result.scenario.expect.get("judge")
    if not criteria:
        return
    from app.config import settings

    script = [
        {"at": s.at, "speaker": s.speaker, "say": s.say, "frame": s.frame, "text": s.text}
        for s in result.scenario.steps
    ]
    meeting_date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d（%a）")
    frames_note = ""
    if any(s.frame == "chart" for s in result.scenario.steps):
        frames_note += (
            "\n\n分享畫面（frame=chart）：標題「Q4 Prototype 評估」；左側成本表 Prototype A NT$780、"
            "Prototype B NT$1,020、Prototype C NT$830；右側「使用者滿意度」長條圖 A 低、B 最高、C 中等。"
        )
    if any(s.frame == "timeline" for s in result.scenario.steps):
        frames_note += (
            "\n分享畫面（frame=timeline）：標題「Prototype C 樣品時程」；三個里程碑："
            "樣品交付（供應商 · 2 週）、測試計畫（小林 · 下週三）、握感 issue（高優先）。"
        )
    if frames_note:
        frames_note += "\n系統看得到這些畫面，引用其中的內容屬於合法證據。"
    prompt = (
        "你是會議 AI 產品的驗收裁判。以下是測試腳本（模擬兩位說話者實際說的話）、"
        "系統產出的事件，以及通過條件。請只依通過條件判斷，不要自行加嚴：\n"
        "- 逐字稿比對時，標點、全半形、空白、簡繁與少數同音錯字視為相同；語意明顯不同才算失真。\n"
        "- 說話者標籤要嚴格比對：通過條件提到「我」或「與會者」說了什麼，就必須在該 speaker 的行找到；"
        "同樣內容出現在另一個 speaker 底下不算通過。\n"
        "- 若同一句被切成兩行，只在通過條件明確要求「一行」時才算失敗。\n"
        "- 系統可引用內建知識庫（ADR、過去決議、需求文件，例如 Prototype A 的過去決議、成本上限）；"
        "這些內容出現在報告中不算捏造。只有腳本與知識庫都沒有的內容才算「無中生有」。\n"
        "- 語音辨識的同音錯字（如「握趕」→「握感」）不算系統捏造；看報告是否正確理解即可。\n"
        f"- 會議日期是 {meeting_date}。系統會把腳本裡的相對時間（下週三、兩週內）換算成以會議日期為基準的"
        " YYYY-MM-DD 寫進報告，這是設計行為，不算捏造；只有換算錯誤或腳本根本沒提到的日期才算。\n"
        "- 有證據支持通過就判通過；理由用一兩句繁體中文說明，指出具體依據。\n\n"
        f"腳本：{json.dumps(script, ensure_ascii=False)}{frames_note}\n\n"
        f"系統輸出：{json.dumps(_summary(result), ensure_ascii=False)}\n\n"
        f"通過條件：{criteria}"
    )
    response = await AsyncOpenAI(api_key=settings.openai_api_key).responses.parse(
        model=JUDGE_MODEL, input=prompt, text_format=JudgeAnswer
    )
    answer = response.output_parsed or JudgeAnswer(passed=False, reason="judge returned nothing")
    verdict.add("llm_judge", answer.passed, answer.reason)


async def grade(result: RunResult) -> Verdict:
    verdict = hard_rules(result)
    await llm_judge(result, verdict)
    return verdict
