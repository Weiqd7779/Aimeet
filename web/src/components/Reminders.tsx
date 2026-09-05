"use client";

import { AlertTriangle, Bell, Check, EyeOff, GitCompareArrows } from "lucide-react";
import type { MeetingState } from "@/hooks/useMeeting";
import { captionOf, clock } from "@/lib/format";
import type { Alert } from "@/lib/types";

const ICON = { inconsistency: GitCompareArrows, conflict: AlertTriangle, slide_mismatch: Bell, info: Bell } as const;
const TONE = {
  inconsistency: "text-fuchsia-200",
  conflict: "text-red-200",
  slide_mismatch: "text-amber-200",
  info: "text-cyan-200",
} as const;
const TEST_ID = { inconsistency: "inconsistency-alert", conflict: "conflict-alert", slide_mismatch: "alert-card", info: "alert-card" } as const;

/** `事：X｜人：Y｜時間：A → B` -> "X · Y · A → B" with the change rendered as ~~A~~ → B. */
function Summary({ detail }: { detail: string }) {
  const parts = detail.split("｜").map((p) => p.trim()).filter(Boolean);
  const values = parts.length > 1 ? parts.map((p) => p.split("：").slice(1).join("：") || p) : [detail];
  return (
    <p className="text-base leading-relaxed text-slate-100">
      {values.map((v, i) => {
        const [before, ...after] = v.split("→");
        return (
          <span key={i}>
            {i > 0 && <span className="mx-2 text-slate-600">·</span>}
            {after.length ? (
              <>
                <span className="text-slate-400 line-through decoration-slate-600">{before.trim()}</span>
                <span className="mx-1.5 text-fuchsia-300">→</span>
                <span className="font-semibold text-white">{after.join("→").trim()}</span>
              </>
            ) : v}
          </span>
        );
      })}
    </p>
  );
}

export function Reminders({ meeting }: { meeting: MeetingState }) {
  // Silent reminders are exactly the voiced ones: time / assignee inconsistencies.
  const alerts = meeting.alerts
    .filter((a) => a.kind === "inconsistency")
    .sort((a, b) => Number(a.status !== "open") - Number(b.status !== "open") || b.ts - a.ts);
  const open = alerts.filter((a) => a.status === "open").length;

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="sticky top-0 z-10 mb-3 flex items-end justify-between bg-[#070b14]/90 pb-2 backdrop-blur">
        <div>
          <p className="eyebrow flex items-center gap-1.5"><GitCompareArrows size={12} className="text-fuchsia-300" /> 02 · AI 提醒</p>
          <p className="mt-0.5 text-sm text-slate-500">時間、負責人和剛才說的不一樣時提醒</p>
        </div>
        <p className="text-sm text-slate-500">{open} 則待處理</p>
      </div>

      <div className="thin-scroll min-h-0 flex-1 space-y-2.5 overflow-y-auto pr-1">
        {alerts.length === 0 && (
          <p className="empty-state">{meeting.status === "live" ? "正在聆聽，目前沒有前後不一致" : "開始會議後，AI 抓到的問題會顯示在這裡"}</p>
        )}
        {alerts.map((alert: Alert) => {
          const Icon = ICON[alert.kind] ?? Bell;
          const isOpen = alert.status === "open";
          const speaking = meeting.speaking?.alert_id === alert.id;
          const caption = captionOf(alert.speech);
          return (
            <article
              key={alert.id}
              data-testid={TEST_ID[alert.kind] ?? "alert-card"}
              className={`rise rounded-xl border border-white/10 bg-white/[0.03] py-3 pl-4 pr-3 transition ${speaking ? "border-l-[3px] border-l-fuchsia-400 bg-fuchsia-400/[0.06]" : ""} ${isOpen ? "" : "opacity-50"}`}
            >
              <div className="flex items-center justify-between gap-3">
                <p className={`flex items-center gap-2 text-lg font-bold ${TONE[alert.kind] ?? TONE.info}`}>
                  <Icon size={17} /> {alert.kind === "conflict" ? "可能與既有決議衝突" : alert.title}
                  <span className="ml-1 font-mono text-sm font-normal tabular-nums text-slate-500">{clock(alert.ts)}</span>
                </p>
                {isOpen ? (
                  <div className="flex shrink-0 gap-1.5">
                    <button className="mini-button" onClick={() => meeting.ackAlert(alert.id, "acknowledged")}><Check size={14} /> 確認</button>
                    <button className="mini-button muted" onClick={() => meeting.ackAlert(alert.id, "dismissed")}><EyeOff size={14} /> 忽略</button>
                  </div>
                ) : (
                  <span className="text-sm text-slate-500">{alert.status === "acknowledged" ? "已確認" : "已忽略"}</span>
                )}
              </div>

              <div className="mt-1.5"><Summary detail={alert.detail} /></div>

              {(alert.evidence?.length ?? 0) > 0 && (
                <div className="mt-1.5 space-y-0.5 text-sm text-slate-400">
                  {alert.evidence!.map((q, i) => (
                    <p key={i} className="min-w-0 truncate"><span className="mr-1 font-semibold text-slate-500">{i === 0 ? "先前" : "現在"}</span>「{q}」</p>
                  ))}
                </div>
              )}
              {alert.kind === "conflict" && alert.source && <p className="mt-1.5 text-sm text-slate-500">來源：{alert.source}</p>}
              {speaking && caption && <p className="mt-2 text-sm italic text-fuchsia-200">IVY：「{caption}」</p>}
            </article>
          );
        })}
      </div>
    </section>
  );
}
