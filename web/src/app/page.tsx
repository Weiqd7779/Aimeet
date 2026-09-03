"use client";

import { useRef, useState } from "react";
import { Activity, CircleHelp, Radio, ToggleLeft, ToggleRight } from "lucide-react";
import { AlertsPanel } from "@/components/AlertsPanel";
import { CapturePanel } from "@/components/CapturePanel";
import { DecisionPanel } from "@/components/DecisionPanel";
import { ReportDrawer } from "@/components/ReportDrawer";
import { useMeeting } from "@/hooks/useMeeting";

export default function Home() {
  const meeting = useMeeting();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [comparison, setComparison] = useState(false);
  const statusLabel = { idle: "Idle", connecting: "Connecting", live: "Live", ended: "Ended" };

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_right,_#12304a_0,_transparent_35%),#070b14] px-4 py-5 text-slate-200 sm:px-6 lg:px-8">
      <header className="mx-auto mb-5 flex max-w-[1800px] flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-300 text-slate-950"><Activity size={21} /></div>
          <div><p className="eyebrow">AIMEET / MULTIMODAL INTELLIGENCE</p><h1 className="text-xl font-bold tracking-tight text-white sm:text-2xl">Live Decision Agent</h1></div>
        </div>
        <div className="flex items-center gap-3">
          {meeting.mockMode && <span className="rounded-full border border-amber-300/30 bg-amber-300/10 px-2.5 py-1 text-[10px] font-bold tracking-widest text-amber-200">MOCK</span>}
          <span className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold ${meeting.status === "live" ? "border-emerald-300/30 bg-emerald-300/10 text-emerald-200" : "border-white/10 bg-white/5 text-slate-400"}`}><Radio size={13} className={meeting.status === "live" ? "animate-pulse" : ""} /> {statusLabel[meeting.status]}</span>
          <button className="flex items-center gap-2 text-xs text-slate-400 hover:text-cyan-200" onClick={() => setComparison(!comparison)}>{comparison ? <ToggleRight className="text-cyan-300" size={22} /> : <ToggleLeft size={22} />} Compare with plain transcript</button>
          <CircleHelp className="hidden text-slate-500 sm:block" size={18} />
        </div>
      </header>
      <div className="mx-auto grid max-w-[1800px] grid-cols-1 gap-4 xl:grid-cols-[minmax(300px,1fr)_minmax(320px,1.05fr)_minmax(300px,1fr)]">
        <CapturePanel meeting={meeting} videoRef={videoRef} comparison={comparison} />
        <AlertsPanel meeting={meeting} dimmed={comparison} />
        <DecisionPanel meeting={meeting} dimmed={comparison} />
      </div>
      {meeting.toast && <div role="status" className="fixed bottom-5 left-1/2 z-30 -translate-x-1/2 rounded-lg border border-amber-300/30 bg-slate-900 px-4 py-3 text-sm text-amber-100 shadow-xl">{meeting.toast}</div>}
      {meeting.report && <ReportDrawer report={meeting.report} onClose={meeting.closeReport} />}
    </main>
  );
}
