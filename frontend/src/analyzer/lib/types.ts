// Types mirroring the backend /analysis payloads.

export interface LoadedCounts {
  messages: number;
  runs: number;
  snapshots: number;
  annotations: number;
  pauses: number;
}

export interface LoadedSummary {
  id: string;
  source_session_id: string | null;
  participant_number: string | null;
  workflow_mode: string | null;
  test_problem_id: string | null;
  source_kind: string;
  source_filename: string | null;
  loaded_at: string | null;
  video_filename: string | null;
  video_duration_sec: number | null;
  clock_offset_sec: number | null;
  t0_video_pos: number | null;
  t0_iso: string | null;
  counts: LoadedCounts;
}

export type AnnoType = "code" | "note" | "marker";

export interface Annotation {
  id: number;
  anno_type: AnnoType;
  label: string | null;
  color: string | null;
  text: string | null;
  video_pos_sec: number | null;
  row_ref: string | null;
}

export interface Pause {
  id: number;
  start_video_pos: number;
  end_video_pos: number | null;
  note: string | null;
}

export interface TimelineRow {
  kind: string; // message | run | snapshot | code | marker | note
  timestamp_iso: string | null;
  epoch: number | null;
  time_since_start: number | null;
  time_since_start_raw: number | null;
  video_pos: number | null;
  event_type: string;
  role: string | null;
  label: string | null;
  summary: string | null;
  definition_change: string | null;
  config_change: string | null;
  latest_run: string | null;
  color: string | null;
  note: string | null;
  annotation_id: number | null;
  row_ref: string | null;
}

export interface LoadedDetail {
  session: LoadedSummary;
  annotations: Annotation[];
  pauses: Pause[];
  timeline: TimelineRow[];
}
