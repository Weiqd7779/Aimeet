"use client";

import { Activity, FileText, Radio, Square, Video, Volume2, VolumeX } from "lucide-react";
import type { MeetingState } from "@/hooks/useMeeting";
import { clock } from "@/lib/format";

const STATUS_LABEL = { idle: "待機", connecting: "連線中", live: "進行中", ended: "已結束" } as const;

export function TopBar({ meeting, onStart }: { meeting: MeetingState; onStart: () => void }) {
  const live = meeting.status === "live";
  const busy = live || meeting.status === "connecting";

  return (
    <header className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-4">
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-cyan-300 text-slate-950"><Activity size={22} /></div>
        <div>
          <p className="eyebrow">AIMEET</p>
          <h1 className="text-2xl font-bold tracking-tight text-white">會議即時提醒助理</h1>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className={`flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm font-semibold ${live ? "border-emerald-300/30 bg-emerald-300/10 text-emerald-200" : "border-white/10 bg-white/5 text-slate-400"}`}>
          <Radio size={14} className={live ? "animate-pulse" : ""} />
          {STATUS_LABEL[meeting.status]}
          {(live || meeting.status === "ended") && <span className="font-mono tabular-nums text-slate-300">{clock(meeting.elapsed)}</span>}
        </span>

        <button
          type="button"
          data-testid="voice-toggle"
          aria-pressed={meeting.voiceEnabled}
          title={meeting.voiceEnabled ? "語音提醒：開（點擊關閉）" : "語音提醒：關（點擊開啟）"}
          onClick={() => meeting.setVoiceEnabled(!meeting.voiceEnabled)}
          className={`flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm font-semibold transition ${meeting.voiceEnabled ? "border-fuchsia-300/40 bg-fuchsia-400/10 text-fuchsia-200" : "border-white/10 bg-white/5 text-slate-500 hover:text-slate-300"}`}
        >
          {meeting.voiceEnabled ? <Volume2 size={15} /> : <VolumeX size={15} />}
          {meeting.voiceEnabled ? "語音提醒 開" : "語音提醒 關"}
        </button>

        <button className="button-ghost" disabled={meeting.status === "idle" || meeting.status === "connecting"} onClick={meeting.generateReport}>
          <FileText size={15} /> 產生報告
        </button>

        {busy ? (
          <button className="button-danger" onClick={meeting.end}><Square size={13} fill="currentColor" /> 結束會議</button>
        ) : (
          <button className="button-primary" onClick={onStart}><Video size={15} /> 開始會議</button>
        )}
      </div>
    </header>
  );
}
