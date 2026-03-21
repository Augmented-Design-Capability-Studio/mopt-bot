import { ApiError, type Message, type Session } from "@shared/api";

export function isSessionGoneError(e: unknown): e is ApiError {
  return e instanceof ApiError && (e.status === 404 || e.status === 410);
}

export function isAbortError(e: unknown): boolean {
  return (
    (typeof DOMException !== "undefined" &&
      e instanceof DOMException &&
      e.name === "AbortError") ||
    (e instanceof Error && e.name === "AbortError")
  );
}

/** Drop out-of-order GET /sessions/:id snapshots. */
export function isOlderSessionSnapshot(
  incoming: Session,
  prev: Session | null,
): boolean {
  if (!prev || prev.id !== incoming.id) return false;
  return Date.parse(incoming.updated_at) < Date.parse(prev.updated_at);
}

export function coerceParticipantMessages(list: unknown): Message[] {
  if (!Array.isArray(list)) return [];
  return list.filter(
    (x): x is Message =>
      x !== null &&
      typeof x === "object" &&
      typeof (x as Message).id === "number",
  );
}
