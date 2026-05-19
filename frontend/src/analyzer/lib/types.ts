/**
 * Shape of a single session as the analyzer consumes it. Matches
 * `GET /sessions/{id}/export` (the researcher JSON export) one-to-one so
 * the JSON path stays a direct passthrough; the .db loader synthesises the
 * same shape from raw SQLite rows.
 */
export type SessionArchive = {
  export_schema_version: number | string;
  exported_at?: string;
  /** JSON exports include this pre-built; .db-derived archives omit it
   *  and let `buildTimelineFromArchive` rebuild from messages/runs/snapshots. */
  timeline?: TimelineRow[];
  session: SessionHeader;
  messages: ArchiveMessage[];
  runs: ArchiveRun[];
  snapshots: ArchiveSnapshot[];
};

export type SessionHeader = {
  id: string;
  created_at: string;
  updated_at: string;
  workflow_mode: string;
  participant_number?: string | null;
  test_problem_id?: string;
  status: string;
  panel_config: Record<string, unknown> | null;
  problem_brief: Record<string, unknown> | null;
  [extra: string]: unknown;
};

export type ArchiveMessage = {
  id: number;
  created_at: string;
  role: string;
  content: string;
  visible_to_participant: boolean;
  kind: string;
  meta?: Record<string, unknown> | null;
};

export type ArchiveRun = {
  id: number;
  session_run_index?: number | null;
  run_number?: number;
  created_at: string;
  run_type: string;
  ok: boolean;
  cost: number | null;
  reference_cost: number | null;
  error_message: string | null;
  request: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
};

export type ArchiveSnapshot = {
  id: number;
  created_at: string;
  event_type: string;
  problem_brief: Record<string, unknown> | null;
  panel_config: Record<string, unknown> | null;
};

export type TimelineRow = {
  kind: string;
  at: string;
  label: string;
  payload_summary: string;
  ref?: Record<string, unknown>;
};

/** Container the UI selects against — JSON gives one session, .db gives many. */
export type SessionStore = {
  source: "json" | "db";
  sourceName: string;
  sessions: SessionArchive[];
};
