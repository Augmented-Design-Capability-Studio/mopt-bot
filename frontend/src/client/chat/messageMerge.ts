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

  return toAdd.length ? [...existing, ...toAdd] : existing;
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

  return merged;
}
