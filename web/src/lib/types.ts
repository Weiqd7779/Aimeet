export type AlertKind = "conflict" | "slide_mismatch" | "info";
export type AlertStatus = "open" | "acknowledged" | "dismissed";
export type DecisionStatus = "candidate" | "confirmed" | "rejected";
export type FrameReason = "deictic" | "diff" | "periodic" | "manual";

export interface TranscriptEntry {
  id: string;
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
  | "utterance_resolved"
  | "status"
  | "error";

export interface ServerEvent {
  type: ServerEventType;
  payload: unknown;
}

export type ClientMessage =
  | { type: "audio"; pcm16_b64: string; source: "me" | "remote" }
  | { type: "frame"; jpeg_b64: string; ts: number; reason: FrameReason }
  | { type: "text"; text: string }
  | { type: "confirm_decision"; id: string; status: DecisionStatus }
  | { type: "ack_alert"; id: string; status: AlertStatus }
  | { type: "end" };

export interface DecisionRow {
  topic: string;
  chosen: string;
  alternatives: string[];
  rationale: string;
  status: DecisionStatus;
  conflict_resolution: string | null;
  sources: string[];
  evidence_frame_ids: string[];
  evidence_ts: number[];
  confidence: number;
}

export interface WorkItem {
  title: string;
  body_markdown: string;
  labels: string[];
  assignee: string | null;
  evidence_frame_ids: string[];
  kind: "github_issue" | "jira_task";
}

export interface KeyFact {
  fact: string;
  quote: string;
  speaker: string | null;
  ts: number | null;
  category: "number" | "date" | "person" | "constraint" | "requirement" | "action" | "other";
}

export interface MeetingReport {
  summary: string;
  key_facts: KeyFact[];
  decision_table: DecisionRow[];
  mermaid: string;
  mermaid_caption: string;
  prd_markdown: string;
  work_items: WorkItem[];
  open_questions: string[];
  uncertainties: string[];
}

export interface ReportEnvelope {
  report: MeetingReport;
  model: string;
  mock: boolean;
}
