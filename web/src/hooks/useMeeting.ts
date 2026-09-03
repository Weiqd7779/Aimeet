"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { createAudioPipeline } from "@/lib/audio";
import { FrameSampler } from "@/lib/frames";
import { LiveSocket } from "@/lib/ws";
import type {
  Alert,
  ClientMessage,
  Decision,
  Frame,
  GroundedEvent,
  ReportEnvelope,
  ServerEvent,
  TranscriptEntry,
} from "@/lib/types";

type SessionStatus = "idle" | "connecting" | "live" | "ended";

interface State {
  sessionId: string | null;
  status: SessionStatus;
  mockMode: boolean;
  liveProvider: string;
  transcript: TranscriptEntry[];
  frames: Frame[];
  groundedEvents: GroundedEvent[];
  alerts: Alert[];
  decisions: Decision[];
  toast: string | null;
  report: ReportEnvelope | null;
}

type Action =
  | { type: "status"; status: SessionStatus }
  | { type: "session"; id: string }
  | { type: "event"; event: ServerEvent }
  | { type: "health"; mockMode: boolean; liveProvider: string }
  | { type: "toast"; message: string | null }
  | { type: "report"; report: ReportEnvelope | null };

const initialState: State = {
  sessionId: null,
  status: "idle",
  mockMode: false,
  liveProvider: "mock",
  transcript: [],
  frames: [],
  groundedEvents: [],
  alerts: [],
  decisions: [],
  toast: null,
  report: null,
};

function replaceById<T extends { id: string }>(items: T[], item: T) {
  const index = items.findIndex((current) => current.id === item.id);
  if (index < 0) return [...items, item];
  return items.map((current, itemIndex) => (itemIndex === index ? item : current));
}

function reducer(state: State, action: Action): State {
  if (action.type === "status") return { ...state, status: action.status };
  if (action.type === "session") return { ...state, sessionId: action.id };
  if (action.type === "health") return { ...state, mockMode: action.mockMode, liveProvider: action.liveProvider };
  if (action.type === "toast") return { ...state, toast: action.message };
  if (action.type === "report") return { ...state, report: action.report };
  if (action.type !== "event") return state;

  const { event } = action;
  if (event.type === "transcript") {
    return { ...state, transcript: [...state.transcript, event.payload as TranscriptEntry] };
  }
  if (event.type === "grounded_event") {
    return { ...state, groundedEvents: [...state.groundedEvents, event.payload as GroundedEvent] };
  }
  if (event.type === "alert") {
    return { ...state, alerts: replaceById(state.alerts, event.payload as Alert) };
  }
  if (event.type === "decision") {
    return { ...state, decisions: replaceById(state.decisions, event.payload as Decision) };
  }
  if (event.type === "frame_ack") {
    return { ...state, frames: replaceById(state.frames, event.payload as Frame) };
  }
  if (event.type === "status") {
    const payload = event.payload as { status?: string };
    if (payload.status === "connected") return { ...state, status: "live" };
    if (payload.status === "ended" || payload.status === "script_complete") {
      return { ...state, status: "ended" };
    }
  }
  if (event.type === "error") {
    const payload = event.payload as { detail?: string };
    return { ...state, toast: payload.detail || "連線發生錯誤" };
  }
  return state;
}

function apiUrl() {
  return (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
}

function socketUrl(base: string, id: string) {
  return `${base.replace(/^http/, "ws")}/ws/live/${id}`;
}

export function useMeeting() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const socketRef = useRef<LiveSocket | null>(null);
  const audioCleanupRef = useRef<(() => void) | null>(null);
  const samplerRef = useRef<FrameSampler | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    fetch(`${apiUrl()}/health`)
      .then((response) => response.json())
      .then((payload: { mock_mode?: boolean; live_provider?: string }) => dispatch({ type: "health", mockMode: Boolean(payload.mock_mode), liveProvider: payload.live_provider || "mock" }))
      .catch(() => dispatch({ type: "toast", message: "無法連線至 API" }));
  }, []);

  const showToast = useCallback((message: string) => {
    dispatch({ type: "toast", message });
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => dispatch({ type: "toast", message: null }), 3500);
  }, []);

  const cleanupMedia = useCallback(() => {
    samplerRef.current?.stop();
    samplerRef.current = null;
    audioCleanupRef.current?.();
    audioCleanupRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const handleEvent = useCallback((event: ServerEvent) => {
    dispatch({ type: "event", event });
    if (event.type === "transcript") {
      const transcript = event.payload as TranscriptEntry;
      if (/這個|那個|這裡|那裡|右邊|左邊|上面|下面|這塊|那張|this|that|here/i.test(transcript.text)) {
        samplerRef.current?.trigger("deictic");
      }
    }
    if (event.type === "status") {
      const payload = event.payload as { request_frame?: boolean; reason?: string; status?: string };
      if (payload.request_frame) samplerRef.current?.trigger("manual");
      if (payload.status === "script_complete" || payload.status === "disconnected") {
        socketRef.current?.close();
      }
    }
  }, []);

  const send = useCallback((message: ClientMessage) => socketRef.current?.send(message), []);

  const start = useCallback(async (mock: boolean, video: HTMLVideoElement | null) => {
    if (state.status === "connecting" || state.status === "live") return;
    dispatch({ type: "status", status: "connecting" });
    try {
      const response = await fetch(`${apiUrl()}/sessions`, { method: "POST" });
      if (!response.ok) throw new Error("建立 session 失敗");
      const { id } = (await response.json()) as { id: string };
      dispatch({ type: "session", id });
      const socket = new LiveSocket(socketUrl(apiUrl(), id), handleEvent, (connected) => {
        if (connected) dispatch({ type: "status", status: "live" });
      });
      socketRef.current = socket;
      socket.connect();

      if (!mock) {
        if (!video) throw new Error("找不到畫面預覽");
        const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
        streamRef.current = stream;
        video.srcObject = stream;
        await video.play();
        samplerRef.current = new FrameSampler(video, (jpeg_b64, reason) =>
          send({ type: "frame", jpeg_b64, reason, ts: performance.now() / 1000 }),
        );
        samplerRef.current.start();
        if (stream.getAudioTracks().length) {
          audioCleanupRef.current = await createAudioPipeline(stream, (pcm16_b64) =>
            send({ type: "audio", pcm16_b64 }),
          );
        }
      }
    } catch (error) {
      socketRef.current?.close();
      socketRef.current = null;
      cleanupMedia();
      dispatch({ type: "status", status: "idle" });
      showToast(error instanceof Error ? error.message : "無法啟動會議");
    }
  }, [cleanupMedia, handleEvent, send, showToast, state.status]);

  const end = useCallback(() => {
    send({ type: "end" });
    socketRef.current?.close();
    socketRef.current = null;
    cleanupMedia();
    dispatch({ type: "status", status: "ended" });
  }, [cleanupMedia, send]);

  const sendText = useCallback((text: string) => {
    if (text.trim()) send({ type: "text", text: text.trim() });
  }, [send]);

  const ackAlert = useCallback((id: string, status: "acknowledged" | "dismissed") => {
    send({ type: "ack_alert", id, status });
  }, [send]);

  const confirmDecision = useCallback((id: string, status: "confirmed" | "rejected") => {
    send({ type: "confirm_decision", id, status });
  }, [send]);

  const generateReport = useCallback(async () => {
    if (!state.sessionId) return;
    const response = await fetch(`${apiUrl()}/sessions/${state.sessionId}/synthesize`, { method: "POST" });
    if (response.status === 501) {
      showToast("尚未實作");
      return;
    }
    if (!response.ok) {
      showToast("報告產生失敗");
      return;
    }
    dispatch({ type: "report", report: (await response.json()) as ReportEnvelope });
  }, [showToast, state.sessionId]);

  useEffect(() => () => {
    socketRef.current?.close();
    cleanupMedia();
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
  }, [cleanupMedia]);

  return {
    ...state,
    sendText,
    start,
    end,
    ackAlert,
    confirmDecision,
    generateReport,
    closeReport: () => dispatch({ type: "report", report: null }),
    dismissToast: () => dispatch({ type: "toast", message: null }),
  };
}

export type MeetingState = ReturnType<typeof useMeeting>;
