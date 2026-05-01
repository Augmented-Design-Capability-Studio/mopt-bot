const GOAL_TERM_VALIDATION_PREFIX = "goal_term_validation:";

type GoalTermReason = {
  code?: string;
  message?: string;
};

export function formatProcessingError(raw: string | null | undefined): string | null {
  const text = (raw ?? "").trim();
  if (!text) return null;
  if (!text.startsWith(GOAL_TERM_VALIDATION_PREFIX)) return text;
  const payload = text.slice(GOAL_TERM_VALIDATION_PREFIX.length).trim();
  if (!payload) return "Goal-term validation failed. Please retry sync.";
  try {
    const parsed = JSON.parse(payload) as GoalTermReason[];
    if (!Array.isArray(parsed) || parsed.length === 0) {
      return "Goal-term validation failed. Please retry sync.";
    }
    const top = parsed.slice(0, 2).map((reason) => reason.message?.trim()).filter(Boolean);
    if (top.length === 0) return "Goal-term validation failed. Please retry sync.";
    return `Goal-term validation failed: ${top.join(" ")}`;
  } catch {
    return "Goal-term validation failed. Please retry sync.";
  }
}
