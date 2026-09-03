"use client";

import { Copy, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { Report } from "@/lib/types";

export function ReportDrawer({ report, onClose }: { report: Report; onClose: () => void }) {
  const [tab, setTab] = useState("table");
  const [showCode, setShowCode] = useState(false);
  const [diagram, setDiagram] = useState("");

  useEffect(() => {
    if (tab !== "mermaid") return;
    import("mermaid").then(({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, theme: "dark" });
      mermaid.render("aimeet-mermaid", report.mermaid).then(({ svg }) => setDiagram(svg)).catch(() => setDiagram(""));
    });
  }, [report.mermaid, tab]);

  const copyIssue = async (item: Report["work_items"][number]) => {
    await navigator.clipboard.writeText(`## ${item.title}\n\n${item.body}\n\nLabels: ${item.labels.join(", ")}`);
  };

  return (
    <div className="fixed inset-0 z-20 flex justify-end bg-black/60 backdrop-blur-sm">
      <aside className="h-full w-full max-w-3xl overflow-y-auto border-l border-white/10 bg-[#0c1220] p-6 shadow-2xl">
        <div className="flex items-center justify-between"><div><p className="eyebrow">POST-MEETING SYNTHESIS</p><h2 className="text-2xl font-semibold text-white">Decision report</h2></div><button className="button-icon" onClick={onClose}><X size={18} /></button></div>
        <div className="mt-6 flex gap-2 border-b border-white/10 pb-3">{[["table", "Decision Table"], ["mermaid", "Mermaid"], ["prd", "PRD"], ["work", "Work Items"]].map(([id, label]) => <button key={id} onClick={() => setTab(id)} className={`tab ${tab === id ? "active" : ""}`}>{label}</button>)}</div>
        {tab === "table" && <table className="mt-5 w-full text-left text-sm"><thead><tr className="border-b border-white/10 text-xs text-slate-500"><th className="pb-3">Topic</th><th className="pb-3">Chosen</th><th className="pb-3">Status</th></tr></thead><tbody>{report.decisions.map((decision) => <tr key={decision.id} className="border-b border-white/5"><td className="py-3 text-slate-300">{decision.topic}</td><td className="py-3 font-semibold text-white">{decision.chosen}</td><td className="py-3 text-slate-400">{decision.status}</td></tr>)}</tbody></table>}
        {tab === "mermaid" && <div className="mt-5"><div className="rounded-xl border border-white/10 bg-slate-950 p-4" dangerouslySetInnerHTML={{ __html: diagram }} /> <button className="mt-3 text-xs text-cyan-300" onClick={() => setShowCode(!showCode)}>{showCode ? "Hide" : "Show"} Mermaid code</button>{showCode && <pre className="mt-2 overflow-auto rounded-xl bg-slate-950 p-4 text-xs text-slate-300">{report.mermaid}</pre>}</div>}
        {tab === "prd" && <pre className="mt-5 whitespace-pre-wrap rounded-xl border border-white/10 bg-slate-950 p-5 text-sm leading-6 text-slate-300">{report.prd}</pre>}
        {tab === "work" && <div className="mt-5 space-y-3">{report.work_items.map((item) => <article key={item.title} className="rounded-xl border border-white/10 p-4"><div className="flex justify-between gap-3"><h3 className="font-semibold text-white">{item.title}</h3><button className="mini-button" onClick={() => copyIssue(item)}><Copy size={13} /> Copy as GitHub Issue</button></div><p className="mt-2 whitespace-pre-wrap text-sm text-slate-300">{item.body}</p><div className="mt-3 flex gap-1">{item.labels.map((label) => <span className="chip" key={label}>{label}</span>)}</div></article>)}</div>}
      </aside>
    </div>
  );
}
