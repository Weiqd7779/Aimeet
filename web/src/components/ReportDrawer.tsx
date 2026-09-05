"use client";

import Image from "next/image";
import { ChevronDown, ChevronRight, Copy, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { KeyFact, ReportEnvelope, Topic, WorkItem } from "@/lib/types";

function apiUrl() {
  return (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
}

const CATEGORY_LABEL: Record<KeyFact["category"], string> = {
  number: "數字",
  date: "日期",
  person: "人員",
  constraint: "限制",
  requirement: "需求",
  action: "待辦",
  other: "其他",
};
const STATUS_LABEL: Record<string, string> = { candidate: "候選", confirmed: "已確認", rejected: "已否決" };

let mermaidSeq = 0;

export function ReportDrawer({
  envelope,
  sessionId,
  onClose,
}: {
  envelope: ReportEnvelope;
  sessionId: string | null;
  onClose: () => void;
}) {
  const [tab, setTab] = useState("facts");
  const [showCode, setShowCode] = useState(false);
  const [showNotes, setShowNotes] = useState(false);
  const [diagram, setDiagram] = useState<{ svg: string; error: string | null }>({ svg: "", error: null });
  const { report } = envelope;

  // Render once per report, not per tab switch: mermaid.render() refuses a reused element id,
  // which is why the diagram used to vanish the second time the tab was opened.
  useEffect(() => {
    if (!report.mermaid.trim()) {
      setDiagram({ svg: "", error: "模型沒有產出圖表" });
      return;
    }
    let cancelled = false;
    import("mermaid").then(async ({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, theme: "dark" });
      try {
        const { svg } = await mermaid.render(`aimeet-mermaid-${++mermaidSeq}`, report.mermaid);
        if (!cancelled) setDiagram({ svg, error: null });
      } catch (err) {
        if (!cancelled) setDiagram({ svg: "", error: err instanceof Error ? err.message : "圖表語法錯誤" });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [report.mermaid]);

  const copyIssue = async (item: WorkItem) => {
    await navigator.clipboard.writeText(`## ${item.title}\n\n${item.body_markdown}\n\n標籤：${item.labels.join(", ")}`);
  };
  const frameUrl = (frameId: string) => sessionId ? `${apiUrl()}/sessions/${sessionId}/frames/${frameId}.jpg` : "";
  const clock = (ts: number) => `${Math.floor(ts / 60).toString().padStart(2, "0")}:${Math.floor(ts % 60).toString().padStart(2, "0")}`;
  const scenes = report.scenes ?? [];
  const facts = report.key_facts ?? [];
  const topics = report.topics ?? [];
  const notes = [...report.open_questions.map((q) => ({ kind: "待釐清", text: q })), ...report.uncertainties.map((u) => ({ kind: "不確定", text: u }))];

  // Facts grouped by the topic the segmenter assigned; anything unassigned goes last.
  const groups: { topic: Topic | null; facts: KeyFact[] }[] = topics.map((topic) => ({ topic, facts: facts.filter((f) => f.topic === topic.id) }));
  const loose = facts.filter((f) => !topics.some((t) => t.id === f.topic));
  if (loose.length) groups.push({ topic: null, facts: loose });

  const renderFact = (fact: KeyFact, index: number) => (
    <div key={`${fact.ts}-${index}`} className="flex gap-3 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm">
      <span className="speaker-chip shrink-0">{fact.speaker || "—"}</span>
      <p className="min-w-0 flex-1 text-slate-200">{fact.fact}{fact.resolved_date && <span className="ml-2 font-mono text-[11px] text-cyan-200">{fact.resolved_date}</span>}</p>
      <span className="chip shrink-0">{CATEGORY_LABEL[fact.category] ?? fact.category}</span>
      {fact.ts !== null && <time className="shrink-0 font-mono text-[10px] text-slate-500">{clock(fact.ts)}</time>}
    </div>
  );

  const tabs: [string, string][] = [
    ["facts", `重點資訊 (${facts.length})`],
    ["pages", `頁面 (${scenes.length})`],
    ["table", "決策表"],
    ["mermaid", "關係圖"],
    ["prd", "PRD"],
    ["work", "工作項目"],
  ];

  return (
    <div className="fixed inset-0 z-20 flex justify-end bg-black/60 backdrop-blur-sm">
      <aside className="h-full w-full max-w-4xl overflow-y-auto border-l border-white/10 bg-[#0c1220] p-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <div><p className="eyebrow">會後整理</p><h2 className="text-2xl font-semibold text-white">會議報告</h2><p className="mt-1 text-xs text-slate-400">模型：<span className="text-cyan-200">{envelope.model}</span>{envelope.mock && <span className="ml-2 text-amber-200">· 模擬資料</span>}</p></div>
          <button className="button-icon" onClick={onClose} aria-label="關閉報告"><X size={18} /></button>
        </div>
        <p className="mt-4 text-sm leading-6 text-slate-300">{report.summary}</p>
        <div className="mt-6 flex gap-2 overflow-x-auto border-b border-white/10 pb-3">{tabs.map(([id, label]) => <button key={id} onClick={() => setTab(id)} className={`tab whitespace-nowrap ${tab === id ? "active" : ""}`}>{label}</button>)}</div>

        {tab === "facts" && (
          <div className="mt-5 space-y-5">
            {facts.length === 0 && <p className="empty-state">沒有擷取到具體資訊</p>}
            {groups.map(({ topic, facts: items }, gi) => (
              <section key={topic?.id ?? `loose-${gi}`}>
                {topic ? (
                  <div className="mb-2 flex items-baseline justify-between gap-3">
                    <h3 className="font-semibold text-white">{topic.title}</h3>
                    <span className="font-mono text-[10px] text-slate-500">{clock(topic.ts_start)}–{clock(topic.ts_end)}</span>
                  </div>
                ) : (
                  <h3 className="mb-2 font-semibold text-white">其他</h3>
                )}
                {topic && <p className="mb-2 text-sm leading-6 text-slate-400">{topic.gist}</p>}
                <div className="space-y-2">{items.map(renderFact)}</div>
              </section>
            ))}
            {notes.length > 0 && (
              <div className="border-t border-white/10 pt-3">
                <button className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200" onClick={() => setShowNotes(!showNotes)}>
                  {showNotes ? <ChevronDown size={14} /> : <ChevronRight size={14} />}備註（{notes.length}）— 待釐清與不確定事項
                </button>
                {showNotes && <ul className="mt-2 space-y-1 text-xs text-slate-400">{notes.map((n, i) => <li key={i} className="flex gap-2"><span className="chip shrink-0">{n.kind}</span><span>{n.text}</span></li>)}</ul>}
              </div>
            )}
          </div>
        )}

        {tab === "pages" && <div className="mt-5 space-y-3">{scenes.length === 0 && <p className="empty-state">沒有分享畫面，無頁面索引</p>}{scenes.map((page) => <article key={page.id} className="flex gap-4 rounded-xl border border-white/10 bg-white/[0.03] p-4"><div className="relative h-24 w-40 shrink-0 overflow-hidden rounded border border-white/10"><Image fill unoptimized src={frameUrl(page.cover_frame_id)} alt={`第 ${page.seq + 1} 頁`} className="object-cover" /></div><div className="min-w-0 flex-1"><div className="flex items-baseline justify-between gap-3"><h3 className="font-semibold text-white">第 {page.seq + 1} 頁 · {page.title}</h3><span className="font-mono text-[10px] text-slate-500">{clock(page.first_ts)}–{clock(page.last_ts)} · {page.utterance_count} 句</span></div><p className="mt-2 text-sm leading-6 text-slate-300">{page.summary || "此頁無討論"}</p></div></article>)}</div>}

        {tab === "table" && <div className="mt-5 space-y-3">{report.decision_table.length === 0 && <p className="empty-state">會中沒有做出決策</p>}{report.decision_table.map((row) => <article key={`${row.topic}-${row.chosen}`} className="rounded-xl border border-white/10 bg-white/[0.03] p-4"><div className="flex items-start justify-between gap-3"><div><p className="text-xs text-slate-400">{row.topic}</p><p className="mt-1 text-lg font-bold text-white">{row.chosen}</p></div><span className={`status-mini ${row.status}`}>{STATUS_LABEL[row.status] ?? row.status}</span></div><p className="mt-3 text-sm text-slate-300">{row.rationale}</p><div className="mt-3 flex flex-wrap gap-2 text-[10px]">{row.sources.map((source) => <span className="chip" key={source}>來源：{source}</span>)}{row.evidence_ts.map((ts) => <span className="chip" key={ts}>逐字稿 {clock(ts)}</span>)}</div>{row.evidence_frame_ids.length > 0 && <div className="mt-3 flex gap-2">{row.evidence_frame_ids.map((frameId) => <div className="relative h-14 w-20 overflow-hidden rounded border border-white/10" key={frameId}><Image fill unoptimized src={frameUrl(frameId)} alt="佐證畫面" className="object-cover" /></div>)}</div>}<div className="mt-3 flex items-center gap-2 text-[10px] text-slate-400"><div className="h-1 flex-1 rounded-full bg-slate-800"><div className="h-full rounded-full bg-cyan-300" style={{ width: `${Math.round(row.confidence * 100)}%` }} /></div>信心 {Math.round(row.confidence * 100)}%</div>{row.conflict_resolution && <p className="mt-3 text-xs text-amber-200">衝突處理：{row.conflict_resolution}</p>}</article>)}</div>}

        {tab === "mermaid" && (
          <div className="mt-5">
            <p className="mb-3 text-xs text-slate-400">{report.mermaid_caption}</p>
            {diagram.error
              ? <p className="rounded-xl border border-amber-300/30 bg-amber-300/5 p-4 text-xs text-amber-200">圖表無法顯示：{diagram.error}</p>
              : <div className="rounded-xl border border-white/10 bg-slate-950 p-4" dangerouslySetInnerHTML={{ __html: diagram.svg }} />}
            {report.mermaid && <button className="mt-3 text-xs text-cyan-300" onClick={() => setShowCode(!showCode)}>{showCode ? "隱藏" : "顯示"}原始碼</button>}
            {showCode && <pre className="mt-2 overflow-auto rounded-xl bg-slate-950 p-4 text-xs text-slate-300">{report.mermaid}</pre>}
          </div>
        )}

        {tab === "prd" && <pre className="mt-5 whitespace-pre-wrap rounded-xl border border-white/10 bg-slate-950 p-5 text-sm leading-6 text-slate-300">{report.prd_markdown}</pre>}

        {tab === "work" && <div className="mt-5 space-y-3">{report.work_items.length === 0 && <p className="empty-state">沒有明確的待辦事項</p>}{report.work_items.map((item) => <article key={item.title} className="rounded-xl border border-white/10 p-4"><div className="flex flex-wrap justify-between gap-3"><h3 className="font-semibold text-white">{item.title}</h3><button className="mini-button" onClick={() => copyIssue(item)}><Copy size={13} /> 複製為 GitHub Issue</button></div><p className="mt-2 whitespace-pre-wrap text-sm text-slate-300">{item.body_markdown}</p><div className="mt-3 flex gap-1">{item.labels.map((label) => <span className="chip" key={label}>{label}</span>)}</div></article>)}</div>}
      </aside>
    </div>
  );
}
