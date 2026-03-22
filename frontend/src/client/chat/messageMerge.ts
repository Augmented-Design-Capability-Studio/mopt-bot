import type { Message } from "@shared/api";

export function mergeMessagesFromPoll(existing: Message[], incoming: Message[]): Message[] {
  const seen = new Set(existing.map((message) => message.id));
  const hasOptimisticUser = existing.some(
    (message) => message.id < 0 && message.role === "user" && message.kind === "chat",
  );

  const toAdd = incoming.filter((message) => {
    if (seen.has(message.id)) return false;
    if (hasOptimisticUser && message.role === "user" && message.kind === "chat") return false;
    return true;
  });

  return toAdd.length ? [...existing, ...toAdd] : existing;
}

export function mergeMessagesFromPost(existing: Message[], incoming: Message[]): Message[] {
  const base = existing.filter((message) => message.id >= 0);
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
