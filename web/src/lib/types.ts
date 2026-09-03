export type AlertKind = "conflict" | "slide_mismatch" | "info";
export type AlertStatus = "open" | "acknowledged" | "dismissed";
export type DecisionStatus = "candidate" | "confirmed" | "rejected";
export type FrameReason = "deictic" | "diff" | "periodic" | "manual";

export interface TranscriptEntry {
  ts: number;
  speaker: string | null;
  text: string;
}

export interface Frame {
  id: string;
  ts: number;
  jpeg_b64?: string;
  reason: FrameReason;
}

export interface GroundedEvent {
  id: string;
  ts: number;
  speaker: string | null;
  utterance: string;
  target: string;
  observation: string;
  frame_id: string | null;
  confidence: number;
}

export interface Alert {
  id: string;
  ts: number;
  kind: AlertKind;
  title: string;
  detail: string;
  source: string | null;
  decision_id: string | null;
  status: AlertStatus;
}

export interface Decision {
  id: string;
  ts: number;
  topic: string;
  chosen: string;
  alternatives: string[];
  reasons_for: string[];
  reasons_against: string[];
  constraints: string[];
  status: DecisionStatus;
  conflicts: string[];
}

export interface DecisionState {
  options_under_comparison: string[];
  decisions: Decision[];
  constraints: string[];
}

export interface MeetingSession {
  id: string;
  started_at: string;
  transcript: TranscriptEntry[];
  frames: Frame[];
  grounded_events: GroundedEvent[];
  alerts: Alert[];
  decision_state: DecisionState;
}

export type ServerEventType =
  | "transcript"
  | "grounded_event"
  | "alert"
  | "decision"
  | "frame_ack"
  | "status"
  | "error";

export interface ServerEvent {
  type: ServerEventType;
  payload: unknown;
}

export type ClientMessage =
  | { type: "audio"; pcm16_b64: string }
  | { type: "frame"; jpeg_b64: string; ts: number; reason: FrameReason }
  | { type: "text"; text: string }
  | { type: "confirm_decision"; id: string; status: DecisionStatus }
  | { type: "ack_alert"; id: string; status: AlertStatus }
  | { type: "end" };

export interface Report {
  decisions: Decision[];
  mermaid: string;
  prd: string;
  work_items: { title: string; body: string; labels: string[] }[];
}
