"use client";

import { AlertTriangle, Bell, Check, EyeOff, Target } from "lucide-react";
import Image from "next/image";
import type { MeetingState } from "@/hooks/useMeeting";

function timestamp(seconds: number) {
  return `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${Math.floor(seconds % 60).toString().padStart(2, "0")}`;
}

export function AlertsPanel({ meeting, dimmed = false }: { meeting: MeetingState; dimmed?: boolean }) {
  const unread = meeting.alerts.filter((alert) => alert.status === "open").length;
  const alertColor = (kind: string) =>
    kind === "conflict" ? "border-red-400/30 bg-red-500/10" : kind === "slide_mismatch" ? "border-amber-300/30 bg-amber-400/10" : "border-blue-300/30 bg-blue-400/10";

  return (
    <div className={`space-y-4 ${dimmed ? "opacity-45" : ""}`}>
      <section className="panel">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <p className="eyebrow">02 · 即時提醒</p>
            <h2 className="text-xl font-semibold text-white">靜默提醒</h2>
          </div>
          <div className="relative text-slate-400">
            <Bell size={19} />
            {unread > 0 && <span className="absolute -right-2 -top-2 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[9px] font-bold text-white">{unread}</span>}
          </div>
        </div>
        <div className="space-y-3">
          {meeting.alerts.length === 0 && <p className="empty-state">沒有需要注意的事項</p>}
          {meeting.alerts.map((alert) => (
            <article key={alert.id} data-testid={alert.kind === "conflict" ? "conflict-alert" : "alert-card"} className={`rounded-xl border p-3 ${alertColor(alert.kind)} ${alert.status !== "open" ? "opacity-60" : ""}`}>
              <div className="flex items-start gap-2">
                {alert.kind === "conflict" ? <AlertTriangle className="mt-0.5 shrink-0 text-red-300" size={16} /> : <Bell className="mt-0.5 shrink-0 text-amber-200" size={16} />}
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-white">{alert.kind === "conflict" ? "⚠ 可能與既有決議衝突" : alert.title}</p>
                  <p className="mt-1 text-xs leading-5 text-slate-200">{alert.detail}</p>
                  {alert.source && <p className="mt-2 text-[10px] text-slate-400">來源：{alert.source}</p>}
                </div>
              </div>
              {alert.status === "open" && (
                <div className="mt-3 flex gap-2 pl-6">
                  <button className="mini-button" onClick={() => meeting.ackAlert(alert.id, "acknowledged")}><Check size={13} /> 確認</button>
                  <button className="mini-button muted" onClick={() => meeting.ackAlert(alert.id, "dismissed")}><EyeOff size={13} /> 忽略</button>
                </div>
              )}
            </article>
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="mb-4 flex items-center gap-2">
          <Target className="text-cyan-300" size={18} />
          <div>
            <p className="eyebrow">畫面指涉</p>
            <h2 className="text-xl font-semibold text-white">指涉物件</h2>
          </div>
        </div>
        <div className="space-y-3">
          {meeting.groundedEvents.length === 0 && <p className="empty-state">畫面指涉事件會顯示在這裡</p>}
          {meeting.groundedEvents.map((event) => (
            <article key={event.id} data-testid="grounded-event" className="rounded-xl border border-cyan-300/15 bg-cyan-300/[0.04] p-3">
              <div className="flex gap-3">
                <div className="relative h-16 w-24 shrink-0 overflow-hidden rounded-lg border border-white/10 bg-slate-900">
                  {event.frame_id && meeting.sessionId ? <Image fill unoptimized src={`${(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000")}/sessions/${meeting.sessionId}/frames/${event.frame_id}.jpg`} alt={event.target} className="object-cover" /> : <div className="flex h-full items-center justify-center text-[10px] text-slate-600">無畫面</div>}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-white">{event.target}</p>
                  {(event.said ?? []).length > 0 && (
                    <ul className="mt-1 space-y-0.5 text-xs text-cyan-100">
                      {(event.said ?? []).map((line) => <li key={line}>· {line}</li>)}
                    </ul>
                  )}
                  <p className="mt-1 text-[11px] text-slate-400">{event.observation}</p>
                  <p className="mt-2 text-[10px] text-slate-500">{event.speaker || "未知"} · {timestamp(event.ts)}{(event.mention_ids ?? []).length > 1 ? ` · 提到 ${event.mention_ids!.length} 次` : ""}</p>
                </div>
              </div>
              <div className="mt-3 flex items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-800"><div className="h-full rounded-full bg-cyan-300" style={{ width: `${Math.round(event.confidence * 100)}%` }} /></div>
                <span className="font-mono text-[10px] text-cyan-200">{Math.round(event.confidence * 100)}%</span>
              </div>
            </article>
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="mb-4 flex items-center gap-2">
          <Target className="text-emerald-300" size={18} />
          <div>
            <p className="eyebrow">VERIFIED VISUAL EVENTS</p>
            <h2 className="text-xl font-semibold text-white">Grounded Visual Events</h2>
          </div>
        </div>
        <div className="space-y-3">
          {meeting.visualEvents.length === 0 && <p className="empty-state">通過畫面驗證的事件會顯示在這裡</p>}
          {meeting.visualEvents.map((event) => (
            <article key={event.event_id} data-testid="grounded-visual-event" className="rounded-xl border border-emerald-300/15 bg-emerald-300/[0.04] p-3">
              <div className="flex gap-3">
                <div className="relative h-16 w-24 shrink-0 overflow-hidden rounded-lg border border-white/10 bg-slate-900">
                  {event.evidence_frame_ids[0] && meeting.sessionId ? <Image fill unoptimized src={`${(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000")}/sessions/${meeting.sessionId}/frames/${event.evidence_frame_ids[0]}.jpg`} alt={event.trigger_text} className="object-cover" /> : <div className="flex h-full items-center justify-center text-[10px] text-slate-600">No frame</div>}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-white">{event.trigger_text}</p>
                  <p className="mt-1 text-[10px] uppercase tracking-wide text-emerald-200">{event.lifecycle}</p>
                  <p className="mt-1 text-[10px] text-slate-500">{event.speaker || "Speaker"} · {timestamp(event.time_range.trigger)}{event.time_range.end !== null ? ` – ${timestamp(event.time_range.end)}` : ""}</p>
                </div>
              </div>
              {(event.context_before.length > 0 || event.context_after.length > 0) && (
                <p className="mt-3 text-xs leading-5 text-slate-300">
                  {[...event.context_before.slice(-2), ...event.context_after.slice(0, 2)].join(" / ")}
                </p>
              )}
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
