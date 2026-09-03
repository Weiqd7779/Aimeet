"use client";

import { Check, GitBranch, X } from "lucide-react";
import type { MeetingState } from "@/hooks/useMeeting";

export function DecisionPanel({ meeting, dimmed = false }: { meeting: MeetingState; dimmed?: boolean }) {
  const alertById = new Map(meeting.alerts.map((alert) => [alert.id, alert]));
  return (
    <section className={`panel flex min-h-[600px] flex-col ${dimmed ? "opacity-45" : ""}`}>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="eyebrow">03 / DECISION STATE</p>
          <h2 className="text-xl font-semibold text-white">Traceable choices</h2>
        </div>
        <GitBranch className="text-violet-300" size={19} />
      </div>
      <div className="space-y-4 overflow-y-auto">
        {meeting.decisions.length === 0 && <p className="empty-state">尚未偵測到團隊決策</p>}
        {meeting.decisions.map((decision) => (
          <article key={decision.id} className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-200">{decision.topic}</h3>
              <span className={`status-mini ${decision.status}`}>{decision.status}</span>
            </div>
            <p className="mt-3 text-lg font-bold text-white">{decision.chosen}</p>
            {decision.alternatives.length > 0 && <div className="mt-3 flex flex-wrap gap-1.5">{decision.alternatives.map((option) => <span key={option} className="chip">{option}</span>)}</div>}
            <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
              <div><p className="label-green">Reasons for</p><ul className="mt-1 space-y-1 text-slate-300">{decision.reasons_for.map((reason) => <li key={reason}>＋ {reason}</li>)}</ul></div>
              <div><p className="label-red">Reasons against</p><ul className="mt-1 space-y-1 text-slate-300">{decision.reasons_against.map((reason) => <li key={reason}>− {reason}</li>)}</ul></div>
            </div>
            {decision.constraints.length > 0 && <div className="mt-3 border-t border-white/10 pt-3"><p className="label-muted">Constraints</p><p className="mt-1 text-xs text-slate-300">{decision.constraints.join(" · ")}</p></div>}
            {decision.conflicts.length > 0 && <div className="mt-3 flex flex-wrap gap-1">{decision.conflicts.map((id) => <span key={id} className="rounded-full bg-red-500/15 px-2 py-1 text-[10px] text-red-200">{alertById.get(id)?.title || "Linked conflict"}</span>)}</div>}
            {decision.status === "candidate" && <div className="mt-4 flex gap-2"><button className="mini-button flex-1" onClick={() => meeting.confirmDecision(decision.id, "confirmed")}><Check size={13} /> 確認</button><button className="mini-button muted flex-1" onClick={() => meeting.confirmDecision(decision.id, "rejected")}><X size={13} /> 否決</button></div>}
          </article>
        ))}
      </div>
      <button className="button-primary mt-auto w-full justify-center" disabled={meeting.status === "idle" || meeting.status === "connecting"} onClick={meeting.generateReport}>Generate Report</button>
    </section>
  );
}
