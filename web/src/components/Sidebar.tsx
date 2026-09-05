"use client";

import { RefObject, useEffect, useMemo, useRef } from "react";
import { MessageSquareText, Video } from "lucide-react";
import type { MeetingState } from "@/hooks/useMeeting";
import { clock } from "@/lib/format";

const normalize = (s: string) => s.replace(/[\s，,。．.、！!？?：:「」]/g, "");

export function Sidebar({ meeting, videoRef }: { meeting: MeetingState; videoRef: RefObject<HTMLVideoElement | null> }) {
  const listRef = useRef<HTMLDivElement>(null);
  const hasVideo = Boolean(videoRef.current?.srcObject);

  // Utterances a reminder was built on: exact text of any alert's evidence.
  const hits = useMemo(() => {
    const set = new Set<string>();
    for (const alert of meeting.alerts) for (const q of alert.evidence ?? []) set.add(normalize(q));
    return set;
  }, [meeting.alerts]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [meeting.transcript.length]);

  return (
    <aside className="flex h-full min-h-0 min-w-0 flex-col gap-4">
      <div className="relative aspect-video overflow-hidden rounded-xl border border-white/10 bg-slate-950">
        <video ref={videoRef} muted playsInline className="h-full w-full object-contain" />
        {!hasVideo && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-slate-600">
            <Video size={26} />
            <span className="text-sm">分享畫面預覽</span>
          </div>
        )}
      </div>

      <section className="flex min-h-0 flex-1 flex-col">
        <div className="mb-2 flex items-center justify-between">
          <p className="eyebrow flex items-center gap-1.5"><MessageSquareText size={12} /> 即時逐字稿</p>
          <p className="text-xs text-slate-500">{meeting.transcript.length} 句</p>
        </div>
        <div ref={listRef} className="thin-scroll min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
          {meeting.transcript.length === 0 && <p className="empty-state">{meeting.status === "live" ? "等待有人開口…" : "開始會議後，對話會在這裡即時出現"}</p>}
          {meeting.transcript.map((entry, index) => {
            const hit = hits.has(normalize(entry.text));
            const me = entry.speaker === "我" || entry.speaker === "me";
            return (
              <div key={`${entry.id ?? entry.ts}-${index}`} className={`flex gap-3 rounded-md px-2 py-1.5 ${hit ? "transcript-hit" : ""}`}>
                <span className={`speaker-chip mt-0.5 ${me ? "me" : ""}`}>{entry.speaker || "未知"}</span>
                <p className={`min-w-0 flex-1 text-[15px] leading-relaxed ${hit ? "text-white" : "text-slate-300"}`}>{entry.text}</p>
                <time className="shrink-0 pt-0.5 font-mono text-xs text-slate-600">{clock(entry.ts)}</time>
              </div>
            );
          })}
        </div>
      </section>
    </aside>
  );
}
