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
  locked: boolean;
  counts: LoadedCounts;
}

export type AnnoType = "code" | "note" | "marker" | "dismiss" | "reason" | "dismiss-reason";

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

/** One coded information-exchange on a row: a single change described by all
 * four facets together (a `code` annotation whose text holds this JSON). */
export interface ChangeTag {
  id: number;
  origin: string | null; // user | agent
  type: string | null; // goal-term | weight | term-type | ranking | search-strategy | search-param
  term: string | null; // which goal term (null for search-strategy/param)
  effect: string | null; // applied | mentioned | dropped | declined | removed
}

/** A change suggestion for a row — deterministic (search tags) or from the
 * cached ✨ LLM tagging pass (goal-term tags, which carry a rationale). */
export interface SuggestedChange {
  origin: string | null;
  type: string | null;
  term: string | null;
  effect: string | null;
  captured?: boolean | null; // term active in the resulting config
  rationale?: string | null; // LLM's one-line evidence (tooltip)
}

/** One changed field of a goal term / solver knob (from → to). */
export interface ConfigFieldChange {
  field: string;
  from?: unknown;
  to?: unknown;
}

/** Structured config diff for a row — rendered as chips in the cfg Δ column. */
export interface ConfigDiff {
  algorithm?: { from: string | null; to: string | null };
  params?: ConfigFieldChange[];
  terms?: { term: string; changes: ConfigFieldChange[] }[];
  added?: { term: string; weight?: number | null; type?: string | null; rank?: number | null }[];
  removed?: string[];
  other?: boolean; // panel changed outside the modeled fields
}

export interface TimelineRow {
  kind: string; // message | run | snapshot | code | marker | note
  timestamp_iso: string | null;
  epoch: number | null;
  t_rel: number | null; // seconds since the first message (video-independent)
  time_since_start: number | null;
  time_since_start_raw: number | null;
  video_pos: number | null;
  event_type: string;
  role: string | null;
  label: string | null;
  summary: string | null;
  definition_change: string | null; // stripped brief-side JSON (no goal_terms/runs)
  config_change: ConfigDiff | null; // structured diff → chips
  latest_run: string | null;
  problem_def: string | null; // full brief JSON as of this chat turn
  problem_config: string | null; // full panel config JSON as of this chat turn
  user_prompt: string | null; // the user turn(s) that prompted this agent response
  codeable: boolean; // whether this row is a coding target (agent reply / manual save)
  changes: ChangeTag[]; // manual coded changes on this row
  dismissed?: ChangeTag[]; // dismissed suggestions (server filters these out)
  suggested_changes: SuggestedChange[]; // search tags + cached LLM tags
  captured_terms: string[];
  color: string | null;
  note: string | null;
  annotation_id: number | null;
  row_ref: string | null;
  // Outcome/formulation scores + session-best flags (run rows carry the
  // canonical fields, codeable message rows carry formulation_score).
  canonical_cost?: number | null; // official re-scored run cost — lower is better
  canonical_feasible?: boolean | null; // valid on the majority of traffic draws
  canonical_contributions?: Record<string, number>; // mean cost per goal term
  formulation_score?: number | null; // 0–11 config quality — higher is better
  best_canonical?: boolean; // this run achieved the session's best canonical cost
  best_formulation?: boolean; // this exchange reached the session's peak formulation score
  // Improvement-reason labeling (run rows + formulation-jump exchanges).
  reasons?: ReasonLabel | null; // accepted label (a `reason` annotation)
  reason_suggestions?: ReasonSuggestion[]; // deterministic + cached LLM verdicts
  dismissed_reasons?: string[]; // rejected suggestions (server filters them out)
  outcome_delta?: OutcomeDelta; // run rows: Δ vs the previous run
}

/** Accepted improvement-reason label on a row (one `reason` annotation). */
export interface ReasonLabel {
  id: number;
  reasons: string[];
  note: string | null;
}

/** One suggested improvement reason (mechanical, LLM, or both agreeing). */
export interface ReasonSuggestion {
  reason: string;
  rationale?: string | null;
  source: "auto" | "llm" | "auto+llm";
}

/** A run's outcome change vs the previous run. */
export interface OutcomeDelta {
  cost_delta: number | null;
  feasible_from: boolean | null;
  feasible_to: boolean | null;
  movers: { term: string; delta: number }[];
}

export interface LoadedDetail {
  session: LoadedSummary;
  annotations: Annotation[];
  pauses: Pause[];
  timeline: TimelineRow[];
  goal_term_keys: string[];
}

export interface AggregateRow {
  loaded_id: string;
  participant: string | null;
  workflow_mode: string | null;
  initial_prompt_words: number | null;
  expertise_score: number | null;
}

export interface AggregateResponse {
  rows: AggregateRow[];
  expertise_available: boolean;
}

export interface SurveyStatus {
  counts: Partial<Record<"pre" | "post", number>>;
  uploaded_at: Partial<Record<"pre" | "post", string>>;
}
