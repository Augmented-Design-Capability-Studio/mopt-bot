import type { Message } from "@shared/api";

export function mergeMessagesFromPoll(existing: Message[], incoming: Message[]): Message[] {
  const seen = new Set(existing.map((message) => message.id));
  let optimisticUserSlots = existing.filter(
    (message) => message.id < 0 && message.role === "user" && message.kind === "chat",
  ).length;

  const toAdd = incoming.filter((message) => {
    if (seen.has(message.id)) return false;
    if (message.role === "user" && message.kind === "chat" && optimisticUserSlots > 0) {
      optimisticUserSlots -= 1;
      return false;
    }
    return true;
  });

  // Re-sort by id so a late-arriving poll row (e.g. the "Run #N finished" line
  // appended inside /runs) lands in chronological order rather than at the
  // tail. Otherwise, when a concurrent POST /messages (run_ack) has already
  // pushed its higher-id placeholder into local state, this poll would render
  // "Run #N finished" *after* the run-summary bubble that analyzes it.
  return toAdd.length ? sortCommittedMessagesFirst([...existing, ...toAdd]) : existing;
}

export function mergeMessagesFromPost(existing: Message[], incoming: Message[]): Message[] {
  let optimisticUsersToDrop = incoming.filter((message) => message.role === "user" && message.kind === "chat").length;
  const base = existing.filter((message) => {
    if (message.id >= 0) return true;
    if (message.role === "user" && message.kind === "chat" && optimisticUsersToDrop > 0) {
      optimisticUsersToDrop -= 1;
      return false;
    }
    return true;
  });
  const seen = new Set(base.map((message) => message.id));
  const merged = [...base];

  for (const message of incoming) {
    if (!seen.has(message.id)) {
      seen.add(message.id);
      merged.push(message);
    }
  }

  return sortCommittedMessagesFirst(merged);
}

function sortCommittedMessagesFirst(messages: Message[]): Message[] {
  return [...messages].sort((a, b) => {
    const aCommitted = a.id >= 0;
    const bCommitted = b.id >= 0;
    if (aCommitted && bCommitted) return a.id - b.id;
    if (aCommitted && !bCommitted) return -1;
    if (!aCommitted && bCommitted) return 1;
    return 0;
  });
}

/** Replace an existing message in place (matched by id) with an updated copy
 *  fetched from the server. Used when the async-verification pipeline rewrites
 *  a message's content or clears its `verifying` flag — the standard
 *  `after_id` poll won't see those changes, so we refetch the row directly
 *  and merge it back in. Returns the same array reference when nothing
 *  actually changed (content + meta deep-equal) so React skips a re-render. */
export function mergeMessageUpdate(existing: Message[], updated: Message): Message[] {
  const idx = existing.findIndex((m) => m.id === updated.id);
  if (idx < 0) return existing;
  const current = existing[idx]!;
  if (
    current.content === updated.content
    && JSON.stringify(current.meta ?? null) === JSON.stringify(updated.meta ?? null)
  ) {
    return existing;
  }
  const next = existing.slice();
  next[idx] = updated;
  return next;
}
