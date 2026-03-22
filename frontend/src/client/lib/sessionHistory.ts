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
      (entry): entry is ClientSessionHistoryEntry =>
        entry !== null && typeof entry === "object" && typeof (entry as ClientSessionHistoryEntry).id === "string",
    );
  } catch {
    return [];
  }
}

function writeStored(entries: ClientSessionHistoryEntry[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
}

/** Last-known sessions for this browser only; this list is never sent to the server. */
export function readSessionHistory(): ClientSessionHistoryEntry[] {
  return parseStored();
}

export function upsertSessionHistoryFromServer(session: Session): void {
  const entries = parseStored().filter((entry) => entry.id !== session.id);
  entries.unshift({
    id: session.id,
    created_at: session.created_at,
    updated_at: session.updated_at,
    status: session.status,
    workflow_mode: session.workflow_mode,
  });
  writeStored(entries);
}

export function removeSessionHistoryEntry(id: string): void {
  writeStored(parseStored().filter((entry) => entry.id !== id));
}
