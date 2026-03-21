import type { Message } from "@shared/api";

export function mergeMessagesFromPoll(
  existing: Message[],
  incoming: Message[],
): Message[] {
  const seen = new Set(existing.map((x) => x.id));
  const hasOptimisticUser = existing.some(
    (msg) => msg.id < 0 && msg.role === "user" && msg.kind === "chat",
  );
  const toAdd = incoming.filter((msg) => {
    if (seen.has(msg.id)) return false;
    if (hasOptimisticUser && msg.role === "user" && msg.kind === "chat") return false;
    return true;
  });
  if (!toAdd.length) return existing;
  return [...existing, ...toAdd];
}

export function mergeMessagesFromPost(
  existing: Message[],
  incoming: Message[],
): Message[] {
  const base = existing.filter((x) => x.id >= 0);
  const seen = new Set(base.map((x) => x.id));
  const merged = [...base];
  for (const msg of incoming) {
    if (!seen.has(msg.id)) {
      seen.add(msg.id);
      merged.push(msg);
    }
  }
  return merged;
}
