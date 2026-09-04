"use client";

import Image from "next/image";
import { Copy, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { ReportEnvelope, WorkItem } from "@/lib/types";

function apiUrl() {
  return (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
}

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
  const [diagram, setDiagram] = useState("");
  const { report } = envelope;

  useEffect(() => {
    if (tab !== "mermaid") return;
    import("mermaid").then(({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, theme: "dark" });
      mermaid.render("aimeet-mermaid", report.mermaid).then(({ svg }) => setDiagram(svg)).catch(() => setDiagram(""));
    });
  }, [report.mermaid, tab]);

  const copyIssue = async (item: WorkItem) => {
    await navigator.clipboard.writeText(`## ${item.title}\n\n${item.body_markdown}\n\nLabels: ${item.labels.join(", ")}`);
  };
  const frameUrl = (frameId: string) => sessionId ? `${apiUrl()}/sessions/${sessionId}/frames/${frameId}.jpg` : "";
  const clock = (ts: number) => `${Math.floor(ts / 60).toString().padStart(2, "0")}:${Math.floor(ts % 60).toString().padStart(2, "0")}`;
  const scenes = report.scenes ?? [];

  return (
    <div className="fixed inset-0 z-20 flex justify-end bg-black/60 backdrop-blur-sm">
      <aside className="h-full w-full max-w-4xl overflow-y-auto border-l border-white/10 bg-[#0c1220] p-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <div><p className="eyebrow">POST-MEETING SYNTHESIS</p><h2 className="text-2xl font-semibold text-white">Decision report</h2><p className="mt-1 text-xs text-slate-400">Model: <span className="text-cyan-200">{envelope.model}</span>{envelope.mock && <span className="ml-2 text-amber-200">· MOCK</span>}</p></div>
          <button className="button-icon" onClick={onClose} aria-label="Close report"><X size={18} /></button>
        </div>
        <p className="mt-4 text-sm leading-6 text-slate-300">{report.summary}</p>
        <div className="mt-6 flex gap-2 overflow-x-auto border-b border-white/10 pb-3">{[["facts", `Key Facts (${report.key_facts?.length ?? 0})`], ["pages", `Pages (${scenes.length})`], ["table", "Decision Table"], ["mermaid", "Mermaid"], ["prd", "PRD"], ["work", "Work Items"]].map(([id, label]) => <button key={id} onClick={() => setTab(id)} className={`tab whitespace-nowrap ${tab === id ? "active" : ""}`}>{label}</button>)}</div>
        {tab === "facts" && <div className="mt-5 space-y-2">{(report.key_facts ?? []).length === 0 && <p className="empty-state">沒有擷取到具體資訊</p>}{(report.key_facts ?? []).map((fact, index) => <div key={`${fact.ts}-${index}`} className="flex gap-3 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm"><span className="speaker-chip shrink-0">{fact.speaker || "—"}</span><p className="min-w-0 flex-1 text-slate-200">{fact.fact}</p><span className="chip shrink-0">{fact.category}</span>{fact.ts !== null && <time className="shrink-0 font-mono text-[10px] text-slate-500">{Math.floor(fact.ts / 60).toString().padStart(2, "0")}:{Math.floor(fact.ts % 60).toString().padStart(2, "0")}</time>}</div>)}</div>}
        {tab === "pages" && <div className="mt-5 space-y-3">{scenes.length === 0 && <p className="empty-state">沒有分享畫面，無頁面索引</p>}{scenes.map((page) => <article key={page.id} className="flex gap-4 rounded-xl border border-white/10 bg-white/[0.03] p-4"><div className="relative h-24 w-40 shrink-0 overflow-hidden rounded border border-white/10"><Image fill unoptimized src={frameUrl(page.cover_frame_id)} alt={`Page ${page.seq + 1}`} className="object-cover" /></div><div className="min-w-0 flex-1"><div className="flex items-baseline justify-between gap-3"><h3 className="font-semibold text-white">p{page.seq + 1} · {page.title}</h3><span className="font-mono text-[10px] text-slate-500">{clock(page.first_ts)}–{clock(page.last_ts)} · {page.utterance_count} 句</span></div><p className="mt-2 text-sm leading-6 text-slate-300">{page.summary || "此頁無討論"}</p></div></article>)}</div>}
        {tab === "table" && <div className="mt-5 space-y-3">{report.decision_table.map((row) => <article key={`${row.topic}-${row.chosen}`} className="rounded-xl border border-white/10 bg-white/[0.03] p-4"><div className="flex items-start justify-between gap-3"><div><p className="text-xs text-slate-400">{row.topic}</p><p className="mt-1 text-lg font-bold text-white">{row.chosen}</p></div><span className={`status-mini ${row.status}`}>{row.status}</span></div><p className="mt-3 text-sm text-slate-300">{row.rationale}</p><div className="mt-3 flex flex-wrap gap-2 text-[10px]">{row.sources.map((source) => <span className="chip" key={source}>Source: {source}</span>)}{row.evidence_ts.map((ts) => <span className="chip" key={ts}>Transcript {Math.floor(ts / 60).toString().padStart(2, "0")}:{Math.floor(ts % 60).toString().padStart(2, "0")}</span>)}</div>{row.evidence_frame_ids.length > 0 && <div className="mt-3 flex gap-2">{row.evidence_frame_ids.map((frameId) => <div className="relative h-14 w-20 overflow-hidden rounded border border-white/10" key={frameId}><Image fill unoptimized src={frameUrl(frameId)} alt="Evidence frame" className="object-cover" /></div>)}</div>}<div className="mt-3 flex items-center gap-2 text-[10px] text-slate-400"><div className="h-1 flex-1 rounded-full bg-slate-800"><div className="h-full rounded-full bg-cyan-300" style={{ width: `${Math.round(row.confidence * 100)}%` }} /></div>{Math.round(row.confidence * 100)}% confidence</div>{row.conflict_resolution && <p className="mt-3 text-xs text-amber-200">Conflict resolution: {row.conflict_resolution}</p>}</article>)}</div>}
        {tab === "mermaid" && <div className="mt-5"><p className="mb-3 text-xs text-slate-400">{report.mermaid_caption}</p><div className="rounded-xl border border-white/10 bg-slate-950 p-4" dangerouslySetInnerHTML={{ __html: diagram }} /><button className="mt-3 text-xs text-cyan-300" onClick={() => setShowCode(!showCode)}>{showCode ? "Hide" : "Show"} Mermaid code</button>{showCode && <pre className="mt-2 overflow-auto rounded-xl bg-slate-950 p-4 text-xs text-slate-300">{report.mermaid}</pre>}</div>}
        {tab === "prd" && <pre className="mt-5 whitespace-pre-wrap rounded-xl border border-white/10 bg-slate-950 p-5 text-sm leading-6 text-slate-300">{report.prd_markdown}</pre>}
        {tab === "work" && <div className="mt-5 space-y-3">{report.work_items.map((item) => <article key={item.title} className="rounded-xl border border-white/10 p-4"><div className="flex flex-wrap justify-between gap-3"><h3 className="font-semibold text-white">{item.title}</h3><button className="mini-button" onClick={() => copyIssue(item)}><Copy size={13} /> Copy as GitHub Issue</button></div><p className="mt-2 whitespace-pre-wrap text-sm text-slate-300">{item.body_markdown}</p><div className="mt-3 flex gap-1">{item.labels.map((label) => <span className="chip" key={label}>{label}</span>)}</div></article>)}</div>}
        {(report.open_questions.length > 0 || report.uncertainties.length > 0) && <div className="mt-6 border-t border-white/10 pt-4 text-xs text-slate-400"><p>Open questions: {report.open_questions.join(" · ") || "None"}</p><p className="mt-2">Uncertainties: {report.uncertainties.join(" · ") || "None"}</p></div>}
      </aside>
    </div>
  );
}
