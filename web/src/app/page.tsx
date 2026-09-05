"use client";

import { useRef } from "react";
import { FocusObjects } from "@/components/FocusObjects";
import { Reminders } from "@/components/Reminders";
import { ReportDrawer } from "@/components/ReportDrawer";
import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import { useMeeting } from "@/hooks/useMeeting";

export default function Home() {
  const meeting = useMeeting();
  const videoRef = useRef<HTMLVideoElement>(null);

  return (
    <main className="flex h-screen flex-col gap-5 bg-[radial-gradient(circle_at_top_right,_#12304a_0,_transparent_35%),#070b14] px-6 py-5 text-slate-200">
      <TopBar meeting={meeting} onStart={() => meeting.start(false, videoRef.current)} />

      {/* min-w-0 on every column: long un-wrappable text (a truncated quote) must shrink
          inside its track, not widen the column under the sidebar. */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(300px,30%)]">
        {/* Two equal halves, each scrolling on its own: what the AI saw, then what it heard. */}
        <div className="grid min-h-0 min-w-0 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] gap-6">
          <FocusObjects events={meeting.groundedEvents} sessionId={meeting.sessionId} />
          <div className="flex min-h-0 min-w-0 flex-col border-t border-white/10 pt-5">
            <Reminders meeting={meeting} />
          </div>
        </div>
        <div className="min-h-0 min-w-0">
          <Sidebar meeting={meeting} videoRef={videoRef} />
        </div>
      </div>

      {meeting.toast && <div role="status" className="fixed bottom-5 left-1/2 z-30 -translate-x-1/2 rounded-lg border border-amber-300/30 bg-slate-900 px-4 py-3 text-sm text-amber-100 shadow-xl">{meeting.toast}</div>}
      {meeting.report && <ReportDrawer envelope={meeting.report} sessionId={meeting.sessionId} onClose={meeting.closeReport} />}
    </main>
  );
}
