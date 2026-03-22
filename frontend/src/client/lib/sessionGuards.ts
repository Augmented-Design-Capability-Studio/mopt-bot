import { ApiError, type Message, type Session } from "@shared/api";

export function isSessionGoneError(error: unknown): error is ApiError {
  return error instanceof ApiError && (error.status === 404 || error.status === 410);
}

export function isAbortError(error: unknown): boolean {
  return (
    (typeof DOMException !== "undefined" && error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

/** Drop out-of-order GET /sessions/:id snapshots. */
export function isOlderSessionSnapshot(incoming: Session, previous: Session | null): boolean {
  if (!previous || previous.id !== incoming.id) return false;
  return Date.parse(incoming.updated_at) < Date.parse(previous.updated_at);
}

export function coerceParticipantMessages(list: unknown): Message[] {
  if (!Array.isArray(list)) return [];
  return list.filter(
    (entry): entry is Message =>
      entry !== null && typeof entry === "object" && typeof (entry as Message).id === "number",
  );
}
