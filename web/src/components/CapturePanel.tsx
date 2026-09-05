"use client";

import { FormEvent, RefObject, useState } from "react";
import { Camera, Mic, Send, Square, Video } from "lucide-react";
import type { MeetingState } from "@/hooks/useMeeting";

function timestamp(seconds: number) {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}

export function CapturePanel({
  meeting,
  videoRef,
  comparison = false,
}: {
  meeting: MeetingState;
  videoRef: RefObject<HTMLVideoElement | null>;
  comparison?: boolean;
}) {
  const [text, setText] = useState("");
  const busy = meeting.status === "connecting" || meeting.status === "live";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    meeting.sendText(text);
    setText("");
  };

  return (
    <section className="panel flex min-h-[600px] flex-col">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="eyebrow">01 · 擷取</p>
          <h2 className="text-xl font-semibold text-white">會議畫面</h2>
        </div>
        <Camera className="text-cyan-300" size={20} />
      </div>
      <div className="relative aspect-video overflow-hidden rounded-xl border border-white/10 bg-slate-950">
        <video ref={videoRef} muted playsInline className="h-full w-full object-contain" />
        {!videoRef.current?.srcObject && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-slate-500">
            <Video size={28} />
            <span className="text-xs">分享畫面預覽</span>
          </div>
        )}
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2">
        <button className="button-primary" disabled={busy} onClick={() => meeting.start(false, videoRef.current)}>
          <Video size={15} /> 開始會議
        </button>
        <button className="button-secondary" disabled={busy} onClick={() => meeting.start(true, null)}>
          <Mic size={15} /> 模擬示範
        </button>
        <button className="button-danger" disabled={!busy} onClick={meeting.end}>
          <Square size={14} fill="currentColor" /> 結束
        </button>
      </div>
      <form onSubmit={submit} className="mt-5">
        <label htmlFor="typed-text" className="mb-2 block text-xs font-medium text-slate-400">
          輸入一句話（示範用）
        </label>
        <div className="flex gap-2">
          <input
            id="typed-text"
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="輸入一段會議內容…"
            className="field"
          />
          <button className="button-icon" type="submit" disabled={!busy || !text.trim()} aria-label="送出">
            <Send size={16} />
          </button>
        </div>
      </form>
      <div className={`mt-5 min-h-0 flex-1 ${comparison ? "rounded-xl bg-slate-800/60 p-3" : ""}`}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="section-title">{comparison ? "純逐字稿" : "即時逐字稿"}</h3>
          <span className="text-[10px] tracking-widest text-slate-500">{meeting.transcript.length} 句</span>
        </div>
        <div className="max-h-64 space-y-3 overflow-y-auto pr-1">
          {meeting.transcript.length === 0 && <p className="empty-state">等待語音或示範文字…</p>}
          {meeting.transcript.map((entry, index) => (
            <div key={`${entry.ts}-${index}`} className="flex gap-3 text-sm">
              <span className="speaker-chip">{entry.speaker || "未知"}</span>
              <p className="min-w-0 flex-1 text-slate-200">{entry.text}</p>
              <time className="shrink-0 font-mono text-[10px] text-slate-500">{timestamp(entry.ts)}</time>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
