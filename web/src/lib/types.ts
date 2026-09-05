export type AlertKind = "conflict" | "slide_mismatch" | "info" | "inconsistency";
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
  scene_id?: string | null;
  scene_seq?: number;
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
  said?: string[];
  mention_ids?: string[];
}

export type EventLifecycle = "triggered" | "aggregating" | "closed";

export interface TimeRange {
  start: number;
  trigger: number;
  end: number | null;
}

export interface GroundedVisualEvent {
  event_id: string;
  time_range: TimeRange;
  trigger_text: string;
  speaker: string | null;
  context_before: string[];
  context_after: string[];
  evidence_frame_ids: string[];
  lifecycle: EventLifecycle;
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
  speech?: string | null;
  evidence?: string[];
}

/** Rendered voice for an alert (ElevenLabs, server-side). */
export interface SpeechEvent {
  alert_id: string;
  text: string | null;
  audio_b64: string;
  mime: string;
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
  grounded_visual_events: GroundedVisualEvent[];
  alerts: Alert[];
  decision_state: DecisionState;
}

export type ServerEventType =
  | "transcript"
  | "grounded_event"
  | "grounded_visual_event"
  | "alert"
  | "decision"
  | "frame_ack"
  | "utterance_resolved"
  | "speech"
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
  resolved_date?: string | null;
  topic?: string | null;
}

export interface Topic {
  id: string;
  title: string;
  ts_start: number;
  ts_end: number;
  gist: string;
  quotes: string[];
}

export interface ScenePage {
  id: string;
  seq: number;
  first_ts: number;
  last_ts: number;
  cover_frame_id: string;
  title: string;
  summary: string;
  utterance_count: number;
}

export interface MeetingReport {
  summary: string;
  topics?: Topic[];
  key_facts: KeyFact[];
  decision_table: DecisionRow[];
  mermaid: string;
  mermaid_caption: string;
  prd_markdown: string;
  work_items: WorkItem[];
  open_questions: string[];
  uncertainties: string[];
  scenes?: ScenePage[];
}

export interface ReportEnvelope {
  report: MeetingReport;
  model: string;
  mock: boolean;
}
