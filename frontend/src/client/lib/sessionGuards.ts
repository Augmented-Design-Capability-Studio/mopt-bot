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
  const incomingTime = Date.parse(incoming.updated_at);
  const previousTime = Date.parse(previous.updated_at);
  if (Number.isNaN(incomingTime) || Number.isNaN(previousTime)) return false;
  if (incomingTime < previousTime) {
    const hadPending =
      previous.processing?.brief_status === "pending" || previous.processing?.config_status === "pending";
    const incomingSettled =
      Boolean(incoming.processing) &&
      incoming.processing.brief_status !== "pending" &&
      incoming.processing.config_status !== "pending";
    if (hadPending && incomingSettled) return false;
    return true;
  }
  return false;
}

export function coerceParticipantMessages(list: unknown): Message[] {
  if (!Array.isArray(list)) return [];
  return list.filter(
    (entry): entry is Message =>
      entry !== null && typeof entry === "object" && typeof (entry as Message).id === "number",
  );
}
