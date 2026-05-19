import initSqlJs, { type Database } from "sql.js";
import wasmUrl from "sql.js/dist/sql-wasm.wasm?url";

import type {
  ArchiveMessage,
  ArchiveRun,
  ArchiveSnapshot,
  SessionArchive,
  SessionHeader,
  SessionStore,
} from "./types";

const SQL_PROMISE = initSqlJs({ locateFile: () => wasmUrl });

/** Load a researcher JSON export. Accepts a single-session archive (current
 *  shape of `GET /sessions/{id}/export`); silently wraps it into a one-item
 *  store so the rest of the analyzer can stay store-shaped. */
export async function loadFromJson(file: File): Promise<SessionStore> {
  const text = await file.text();
  const obj = JSON.parse(text) as SessionArchive;
  if (!obj || typeof obj !== "object" || obj.session == null) {
    throw new Error("JSON does not look like a session archive (missing `session` key).");
  }
  return { source: "json", sourceName: file.name, sessions: [obj] };
}

/** Load a SQLite .db produced by `POST /sessions/export-db` (one or many
 *  sessions). Reads in-browser via sql.js; no server round-trip. */
export async function loadFromDb(file: File): Promise<SessionStore> {
  const SQL = await SQL_PROMISE;
  const buf = await file.arrayBuffer();
  const db = new SQL.Database(new Uint8Array(buf));
  try {
    const sessions = projectSessions(db);
    return { source: "db", sourceName: file.name, sessions };
  } finally {
    db.close();
  }
}

function projectSessions(db: Database): SessionArchive[] {
  const sessionRows = rows(db, "SELECT * FROM sessions ORDER BY created_at ASC");
  const messageRows = rows(db, "SELECT * FROM messages ORDER BY id ASC");
  const runRows = rows(db, "SELECT * FROM runs ORDER BY id ASC");
  const snapshotRows = rows(db, "SELECT * FROM session_snapshots ORDER BY id ASC");

  const messagesBySession = groupBy(messageRows, "session_id");
  const runsBySession = groupBy(runRows, "session_id");
  const snapshotsBySession = groupBy(snapshotRows, "session_id");

  return sessionRows.map((s) => {
    const sid = String(s.id);
    return {
      export_schema_version: "db",
      session: rowToHeader(s),
      messages: (messagesBySession.get(sid) ?? []).map(rowToMessage),
      runs: (runsBySession.get(sid) ?? []).map(rowToRun),
      snapshots: (snapshotsBySession.get(sid) ?? []).map(rowToSnapshot),
    };
  });
}

function rows(db: Database, sql: string): Record<string, unknown>[] {
  const result = db.exec(sql);
  if (result.length === 0) return [];
  const { columns, values } = result[0];
  return values.map((v) => {
    const obj: Record<string, unknown> = {};
    columns.forEach((c, i) => (obj[c] = v[i]));
    return obj;
  });
}

function groupBy<T extends Record<string, unknown>>(items: T[], key: keyof T): Map<string, T[]> {
  const map = new Map<string, T[]>();
  for (const item of items) {
    const k = String(item[key] ?? "");
    const bucket = map.get(k);
    if (bucket) bucket.push(item);
    else map.set(k, [item]);
  }
  return map;
}

function parseJsonField(value: unknown): Record<string, unknown> | null {
  if (value == null) return null;
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function asBool(value: unknown): boolean {
  return value === 1 || value === true || value === "1" || value === "true";
}

function rowToHeader(s: Record<string, unknown>): SessionHeader {
  return {
    id: String(s.id),
    created_at: String(s.created_at ?? ""),
    updated_at: String(s.updated_at ?? s.created_at ?? ""),
    workflow_mode: String(s.workflow_mode ?? "waterfall"),
    participant_number: (s.participant_number ?? null) as string | null,
    test_problem_id: (s.test_problem_id as string | undefined) ?? undefined,
    status: String(s.status ?? "active"),
    panel_config: parseJsonField(s.panel_config_json),
    problem_brief: parseJsonField(s.problem_brief_json),
    processing_revision: Number(s.processing_revision ?? 0),
    brief_status: String(s.brief_status ?? "idle"),
    config_status: String(s.config_status ?? "idle"),
    processing_error: (s.processing_error as string | null) ?? null,
    optimization_allowed: asBool(s.optimization_allowed),
    optimization_runs_blocked_by_researcher: asBool(s.optimization_runs_blocked_by_researcher),
    optimization_gate_engaged: asBool(s.optimization_gate_engaged),
    gemini_model: (s.gemini_model as string | null) ?? null,
    embedding_model: (s.embedding_model as string | null) ?? null,
    gemini_key_configured: Boolean(s.gemini_key_encrypted),
    content_reset_revision: Number(s.content_reset_revision ?? 0),
  };
}

function rowToMessage(m: Record<string, unknown>): ArchiveMessage {
  return {
    id: Number(m.id),
    created_at: String(m.created_at ?? ""),
    role: String(m.role ?? ""),
    content: String(m.content ?? ""),
    visible_to_participant: asBool(m.visible_to_participant),
    kind: String(m.kind ?? "chat"),
    meta: parseJsonField(m.meta_json),
  };
}

function rowToRun(r: Record<string, unknown>): ArchiveRun {
  const idx = r.session_run_index == null ? null : Number(r.session_run_index);
  return {
    id: Number(r.id),
    session_run_index: idx,
    run_number: idx != null && Number.isFinite(idx) ? idx + 1 : Number(r.id),
    created_at: String(r.created_at ?? ""),
    run_type: String(r.run_type ?? "optimize"),
    ok: asBool(r.ok),
    cost: r.cost == null ? null : Number(r.cost),
    reference_cost: r.reference_cost == null ? null : Number(r.reference_cost),
    error_message: (r.error_message as string | null) ?? null,
    request: parseJsonField(r.request_json),
    result: parseJsonField(r.result_json),
  };
}

function rowToSnapshot(s: Record<string, unknown>): ArchiveSnapshot {
  return {
    id: Number(s.id),
    created_at: String(s.created_at ?? ""),
    event_type: String(s.event_type ?? "snapshot"),
    problem_brief: parseJsonField(s.problem_brief_json),
    panel_config: parseJsonField(s.panel_config_json),
  };
}
