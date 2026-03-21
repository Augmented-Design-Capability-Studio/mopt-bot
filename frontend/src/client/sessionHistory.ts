import type { Session } from "@shared/api";

const STORAGE_KEY = "mopt_client_session_history_v1";
const MAX_ENTRIES = 30;

export type ClientSessionHistoryEntry = {
  id: string;
  created_at?: string;
  updated_at?: string;
  status?: string;
  workflow_mode?: string;
};

function parseStored(): ClientSessionHistoryEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const data = JSON.parse(raw) as unknown;
    if (!Array.isArray(data)) return [];
    return data.filter(
      (x): x is ClientSessionHistoryEntry =>
        x !== null && typeof x === "object" && typeof (x as ClientSessionHistoryEntry).id === "string",
    );
  } catch {
    return [];
  }
}

function writeStored(entries: ClientSessionHistoryEntry[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
}

/** Last-known sessions for this browser (not sent to the server). */
export function readSessionHistory(): ClientSessionHistoryEntry[] {
  return parseStored();
}

export function upsertSessionHistoryFromServer(s: Session): void {
  const entries = parseStored().filter((e) => e.id !== s.id);
  const next: ClientSessionHistoryEntry = {
    id: s.id,
    created_at: s.created_at,
    updated_at: s.updated_at,
    status: s.status,
    workflow_mode: s.workflow_mode,
  };
  entries.unshift(next);
  writeStored(entries);
}

export function removeSessionHistoryEntry(id: string): void {
  writeStored(parseStored().filter((e) => e.id !== id));
}
