"use client";

import Image from "next/image";
import { Check, ScanEye } from "lucide-react";
import { apiUrl, clock } from "@/lib/format";
import type { GroundedEvent } from "@/lib/types";

const MAX_SAID = 3;
const SURE = 0.8;

export function FocusObjects({ events, sessionId }: { events: GroundedEvent[]; sessionId: string | null }) {
  const ordered = [...events].sort((a, b) => b.ts - a.ts);
  return (
    <section className="flex min-h-0 min-w-0 flex-col">
      <div className="sticky top-0 z-10 mb-3 flex items-end justify-between bg-[#070b14]/90 pb-2 backdrop-blur">
        <div>
          <p className="eyebrow flex items-center gap-1.5"><ScanEye size={12} className="text-cyan-300" /> 01 · 會議焦點物件</p>
          <p className="mt-0.5 text-sm text-slate-500">AI 從畫面辨識出的討論對象</p>
        </div>
        <p className="text-sm text-slate-500">{events.length} 個</p>
      </div>

      <div className="thin-scroll min-h-0 flex-1 space-y-2.5 overflow-y-auto pr-1">
        {ordered.length === 0 && (
          <p className="empty-state">有人指著畫面說「這個」「右邊那張」時，AI 會把它認出來放在這裡</p>
        )}
        {ordered.map((event) => {
          const said = event.said ?? [];
          return (
            <article key={event.id} data-testid="grounded-event" className="rise flex gap-4 rounded-xl border border-cyan-300/15 bg-cyan-300/[0.04] p-3">
              <div className="relative h-[112px] w-[200px] shrink-0 overflow-hidden rounded-lg border border-white/10 bg-slate-900">
                {event.frame_id && sessionId ? (
                  <Image fill unoptimized src={`${apiUrl()}/sessions/${sessionId}/frames/${event.frame_id}.jpg`} alt={event.target} className="object-cover" />
                ) : (
                  <div className="flex h-full items-center justify-center text-sm text-slate-600">無畫面</div>
                )}
                {event.confidence >= SURE && (
                  <span className="absolute bottom-1.5 right-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-cyan-300 text-slate-950"><Check size={12} strokeWidth={3} /></span>
                )}
              </div>
              <div className="min-w-0 flex-1 py-0.5">
                <div className="flex items-baseline justify-between gap-3">
                  <h3 className="truncate text-lg font-bold text-white">{event.target}</h3>
                  <span className="shrink-0 text-sm text-slate-500">{event.speaker || "未知"} · {clock(event.ts)}</span>
                </div>
                {said.length > 0 ? (
                  <ul className="mt-1.5 space-y-0.5 text-base leading-relaxed text-cyan-50">
                    {said.slice(0, MAX_SAID).map((line) => <li key={line}>· {line}</li>)}
                    {said.length > MAX_SAID && <li className="text-sm text-slate-500">+{said.length - MAX_SAID} 條</li>}
                  </ul>
                ) : (
                  <p className="mt-1.5 text-base text-slate-500">「{event.utterance}」</p>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
