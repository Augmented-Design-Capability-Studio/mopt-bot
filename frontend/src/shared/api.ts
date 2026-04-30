import { buildApiUrl } from "@shared/backendConfig";

export class ApiError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string) {
    super(`HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

async function parseJson(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function apiFetch<T>(
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<T> {
  const url = buildApiUrl(path);
  const method = (init.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    ...(init.headers as Record<string, string> | undefined),
  };
  if (init.body !== undefined && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(url, {
    ...(method === "GET" || method === "HEAD" ? { cache: init.cache ?? "no-store" } : {}),
    ...init,
    headers,
  });
  const data = await parseJson(res);
  if (!res.ok) {
    const msg = typeof data === "object" && data && "detail" in data
      ? String((data as { detail: unknown }).detail)
      : String(data);
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

/** Public metadata; no auth required (same origin or CORS). */
export async function fetchTestProblemsMeta(): Promise<TestProblemMeta[]> {
  const url = buildApiUrl("/meta/test-problems");
  const res = await fetch(url, { cache: "no-store" });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(text || `HTTP ${res.status}`);
  }
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    throw new Error("Invalid JSON from /meta/test-problems");
  }
  const list = (data as { test_problems?: TestProblemMeta[] } | null)?.test_problems;
  return Array.isArray(list) ? list : [];
}

export type PublicConfig = {
  default_gemini_model: string;
  gemini_model_suggestions: string[];
};

/** Fetch server-driven UI config (no auth required). Falls back gracefully. */
export async function fetchPublicConfig(): Promise<PublicConfig> {
  const url = buildApiUrl("/meta/config");
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return {
      default_gemini_model: typeof data.default_gemini_model === "string" ? data.default_gemini_model : "",
      gemini_model_suggestions: Array.isArray(data.gemini_model_suggestions) ? data.gemini_model_suggestions : [],
    };
  } catch {
    // Fallback: return empty so UI stays functional even if backend is unreachable
    return { default_gemini_model: "", gemini_model_suggestions: [] };
  }
}


/** Fetch filenames available in a problem's upload folder (no auth required). Falls back to []. */
export async function fetchProblemFiles(problemId: string): Promise<string[]> {
  const url = buildApiUrl(`/meta/problem-files/${encodeURIComponent(problemId)}`);
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.files) ? (data.files as string[]) : [];
  } catch {
    return [];
  }
}

/** Build a download URL for a problem upload file (no auth required). */
export function buildProblemFileUrl(problemId: string, filename: string): string {
  return buildApiUrl(`/meta/problem-files/${encodeURIComponent(problemId)}/${encodeURIComponent(filename)}`);
}


export type WeightDefinitionMeta = {
  key: string;
  label: string;
  description: string | null;
  direction: "minimize" | "maximize";
};

export type TestProblemMeta = {
  id: string;
  label: string;
  weight_definitions: WeightDefinitionMeta[];
  extension_ui: string;
  visualization_presets: string[];
  primary_visualization: string | null;
  /** Ordered weight keys that count toward the agile gate. Empty = any-weight fallback. */
  weight_display_keys: string[];
  /** Weight key whose block is conditional on driver_preferences (null = no such concept). */
  worker_preference_key: string | null;
};

export const TUTORIAL_STEP_IDS = [
  "chat-info",
  "upload-files",
  "inspect-definition",
  "update-definition",
  "inspect-config",
  "first-run",
  "update-config",
  "second-run",
] as const;

export type TutorialStepId = (typeof TUTORIAL_STEP_IDS)[number];

export type Session = {
  id: string;
  created_at: string;
  updated_at: string;
  participant_number?: string | null;
  workflow_mode: string;
  /** Active benchmark module for solver + problem config shape (e.g. vrptw, knapsack). */
  test_problem_id: string;
  status: string;
  panel_config: Record<string, unknown> | null;
  problem_brief: ProblemBrief;
  processing: SessionProcessingState;
  optimization_allowed: boolean;
  /** When true, participant Run stays off even if intrinsic readiness or permit would allow it. */
  optimization_runs_blocked_by_researcher: boolean;
  /** Researcher-controlled tutorial visibility toggle for participant UI. */
  participant_tutorial_enabled: boolean;
  /** Researcher-selected tutorial step for soft jump; null means natural progression. */
  tutorial_step_override?: TutorialStepId | null;
  tutorial_chat_started?: boolean;
  tutorial_uploaded_files?: boolean;
  tutorial_definition_tab_visited?: boolean;
  tutorial_definition_saved?: boolean;
  tutorial_config_tab_visited?: boolean;
  tutorial_config_saved?: boolean;
  tutorial_first_run_done?: boolean;
  tutorial_second_run_done?: boolean;
  /** Waterfall: true after first participant chat or once the brief lists open questions (cold start gate). */
  optimization_gate_engaged?: boolean;
  gemini_model: string | null;
  gemini_key_configured: boolean;
  /** Incremented on researcher reset; client may reload when this increases. */
  content_reset_revision?: number;
};

export type SessionProcessingStatus = "idle" | "pending" | "ready" | "failed";

export type SessionProcessingState = {
  processing_revision: number;
  brief_status: SessionProcessingStatus;
  config_status: SessionProcessingStatus;
  processing_error: string | null;
};

export type ProblemBriefItem = {
  id: string;
  text: string;
  kind: "gathered" | "assumption" | "system";
  source: "user" | "upload" | "agent" | "system";
  status: "active" | "confirmed" | "rejected";
  editable: boolean;
};

export type ProblemBriefQuestion = {
  id: string;
  text: string;
  status: "open" | "answered";
  answer_text: string | null;
};

export type ProblemBrief = {
  goal_summary: string;
  items: ProblemBriefItem[];
  open_questions: ProblemBriefQuestion[];
  solver_scope: string;
  backend_template: string;
};

/** Text for the problem-config editor: empty string when there is nothing to show. */
export function sessionPanelToConfigText(panel: Session["panel_config"]): string {
  if (panel == null) return "";
  if (typeof panel !== "object" || Array.isArray(panel)) return "";
  if (Object.keys(panel as object).length === 0) return "";
  return JSON.stringify(panel, null, 2);
}

export type Message = {
  id: number;
  created_at: string;
  role: string;
  content: string;
  visible_to_participant: boolean;
  kind: string;
};

export type PostMessagesResponse = {
  messages: Message[];
  panel_config: Record<string, unknown> | null;
  problem_brief: ProblemBrief | null;
  processing: SessionProcessingState | null;
};

function isLooseMessage(x: unknown): x is Record<string, unknown> {
  if (x === null || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return typeof o.id === "number" && typeof o.role === "string" && typeof o.content === "string";
}

function coerceMessage(o: Record<string, unknown>): Message {
  return {
    id: o.id as number,
    created_at: typeof o.created_at === "string" ? o.created_at : "",
    role: o.role as string,
    content: o.content as string,
    visible_to_participant: typeof o.visible_to_participant === "boolean" ? o.visible_to_participant : true,
    kind: typeof o.kind === "string" ? o.kind : "chat",
  };
}

/**
 * POST /sessions/:id/messages should return `{ messages, panel_config? }`.
 * Also accepts a top-level message array (legacy / misconfigured proxies).
 * If the server returns HTML (e.g. SPA fallback when VITE_API_BASE is unset), `parseJson` yields a string — explain that clearly.
 */
export function normalizePostMessagesResponse(data: unknown): PostMessagesResponse {
  if (data == null) {
    throw new Error(
      "Empty response when sending a message. For production builds served separately from the API, set VITE_API_BASE (see frontend/.env.example).",
    );
  }
  if (typeof data === "string") {
    const t = data.trimStart().toLowerCase();
    if (t.startsWith("<!doctype") || t.startsWith("<html") || t.startsWith("<!")) {
      throw new Error(
        "The server returned a web page instead of JSON for the chat API. Set VITE_API_BASE to your API origin when you build or host the frontend away from the backend (see frontend/.env.example).",
      );
    }
    throw new Error(
      "Invalid message response (body is not JSON). Check the API URL and that the backend is running.",
    );
  }
  if (Array.isArray(data)) {
    if (data.length > 0 && !data.every(isLooseMessage)) {
      throw new Error(
        "Invalid message response (expected an object with a messages array or a JSON array of message objects).",
      );
    }
    return {
      messages: (data as Record<string, unknown>[]).map(coerceMessage),
      panel_config: null,
      problem_brief: null,
      processing: null,
    };
  }
  if (typeof data === "object" && Array.isArray((data as PostMessagesResponse).messages)) {
    const o = data as PostMessagesResponse;
    return {
      messages: o.messages,
      panel_config: o.panel_config ?? null,
      problem_brief: o.problem_brief ?? null,
      processing: o.processing ?? null,
    };
  }
  throw new Error(
    "Invalid message response (expected JSON with a messages array). Check the API URL and that the backend is running.",
  );
}

/** @deprecated Use normalizePostMessagesResponse */
export const assertPostMessagesResponse = normalizePostMessagesResponse;

export type RunScheduleRoute = {
  vehicle_index: number;
  task_indices: number[];
};

export type RunScheduleStop = {
  vehicle_index: number;
  vehicle_name: string;
  task_id: string;
  task_index: number | null;
  region_index: number;
  region_name: string;
  arrival_minutes: number;
  departure_minutes: number;
  window_open_minutes: number;
  window_close_minutes: number;
  service_minutes: number;
  wait_minutes: number;
  time_window_minutes_over: number;
  priority_express?: boolean;
  /** @deprecated Use `priority_express`. */
  priority_urgent?: boolean;
  priority_deadline_missed: boolean;
  constraint_conflict: boolean;
  time_window_conflict: boolean;
  order_size: number;
  load_after_stop: number;
  capacity_limit: number;
  capacity_overflow_after_stop: number;
  capacity_conflict: boolean;
  /** Per-stop driver preference cost units (per_visit rules only). */
  preference_penalty_units?: number;
  preference_conflict?: boolean;
};

export type RunVehicleSummary = {
  vehicle_index: number;
  vehicle_name: string;
  capacity_limit: number;
  assigned_units: number;
  capacity_overflow_units: number;
  shift_start_minutes: number;
  display_end_minutes: number;
  shift_limit_minutes: number;
  stop_count: number;
};

export type RunSchedule = {
  routes: RunScheduleRoute[];
  stops: RunScheduleStop[];
  vehicle_summaries: RunVehicleSummary[];
  time_bounds: {
    start_minutes: number;
    end_minutes: number;
  };
};

export type RunViolations = {
  time_window_minutes_over: number;
  time_window_stop_count: number;
  capacity_units_over: number;
  shift_limit_penalty: number;
  priority_deadline_misses: number;
};

export type RunMetrics = {
  total_travel_minutes: number;
  /** VRPTW: sum of minutes each route exceeds the 8h cap. Knapsack: 0. */
  shift_overtime_minutes: number;
  workload_variance: number;
  /** Raw preference cost units before weighting; same value as driver_preference_penalty. */
  driver_preference_units?: number;
  driver_preference_penalty: number;
};

export type RunVisualization = {
  preset: string;
  version?: number;
  payload?: Record<string, unknown>;
};

export type RunPayload = {
  cost: number;
  reference_cost: number | null;
  schedule: RunSchedule;
  violations: RunViolations;
  metrics: RunMetrics;
  runtime_seconds: number;
  algorithm: string;
  convergence: number[];
  weight_warnings?: string[];
  visualization?: RunVisualization | null;
  edited_evaluation?: Record<string, unknown>;
  original_snapshot?: Record<string, unknown>;
};

export type RunResult = {
  id: number;
  run_number?: number;
  created_at: string;
  run_type: string;
  ok: boolean;
  cost: number | null;
  reference_cost: number | null;
  error_message: string | null;
  request: {
    type?: string;
    problem?: Record<string, unknown>;
    routes?: number[][];
    candidate_seed_run_ids?: number[];
    candidate_seeds?: Array<{ source_run_id: number; routes: number[][] }>;
  } | null;
  result: RunPayload | null;
  /** Client-only: placeholder row while POST /runs (optimize) is in flight */
  clientPending?: boolean;
};

export type SnapshotSummary = {
  id: number;
  created_at: string;
  event_type: string;
  items_count: number;
  questions_count: number;
  has_config: boolean;
  problem_brief: Record<string, unknown> | null;
  panel_config: Record<string, unknown> | null;
};

export async function fetchSnapshots(sessionId: string, token: string): Promise<SnapshotSummary[]> {
  const data = await apiFetch<SnapshotSummary[]>(`/sessions/${sessionId}/snapshots`, token);
  return Array.isArray(data) ? data : [];
}

/** Bookmark current server brief+panel as a snapshot (no PATCH, no chat). */
export async function createSessionSnapshotBookmark(sessionId: string, token: string): Promise<SnapshotSummary> {
  return apiFetch<SnapshotSummary>(`/sessions/${sessionId}/snapshots`, token, { method: "POST" });
}

export async function fetchSessionsForParticipant(
  participantNumber: string,
  token: string,
): Promise<Session[]> {
  const trimmed = participantNumber.trim();
  if (!trimmed) return [];
  const params = new URLSearchParams({ participant_number: trimmed });
  const data = await apiFetch<Session[]>(`/sessions/for-participant?${params}`, token);
  return Array.isArray(data) ? data : [];
}

export function displayRunNumber(run: Pick<RunResult, "id" | "run_number">, fallbackIndex?: number): number {
  if (typeof run.run_number === "number" && Number.isFinite(run.run_number) && run.run_number > 0) {
    return run.run_number;
  }
  if (typeof fallbackIndex === "number" && Number.isFinite(fallbackIndex)) {
    return fallbackIndex + 1;
  }
  return run.id;
}
