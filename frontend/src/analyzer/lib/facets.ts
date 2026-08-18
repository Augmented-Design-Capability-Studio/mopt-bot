// The coding scheme: each coded information-exchange is ONE change described by
// four fields together — origin, type, goal term, effect. A change is stored as
// a `code` annotation whose `text` is the JSON {origin, type, term, effect}.

import type { ChangeTag, SuggestedChange } from "./types";

export const ORIGIN_VALUES = ["user", "agent"];
export const TYPE_VALUES = [
  "goal-term",
  "detail", // refined an existing term's specifics (properties)
  "weight",
  "term-type",
  "ranking",
  "search-strategy",
  "search-param",
];
export const EFFECT_VALUES = ["applied", "acknowledged", "dropped", "declined", "removed"];

// The four fields of a change, with the dropdown label + fixed options. `term`
// options are dynamic (the session's goal-term keys), so its list is empty here.
export interface ChangeField {
  key: "origin" | "type" | "term" | "effect";
  label: string;
  values: string[];
}

export const CHANGE_FIELDS: ChangeField[] = [
  { key: "origin", label: "origin", values: ORIGIN_VALUES },
  { key: "type", label: "type", values: TYPE_VALUES },
  { key: "term", label: "goal term", values: [] },
  { key: "effect", label: "effect", values: EFFECT_VALUES },
];

const ORIGIN_COLOR: Record<string, string> = { user: "#3b82f6", agent: "#8b5cf6" };
const EFFECT_COLOR: Record<string, string> = {
  applied: "#10b981",
  acknowledged: "#f59e0b",
  dropped: "#ef4444",
  declined: "#a855f7",
  removed: "#6b7280",
};

/** A change card is tinted by origin (who) with an effect-colored left accent. */
export function originColor(origin: string | null | undefined): string {
  return (origin && ORIGIN_COLOR[origin]) || "#9ca3af";
}

export function effectColor(effect: string | null | undefined): string {
  return (effect && EFFECT_COLOR[effect]) || "#9ca3af";
}

/** Serialize a change to the annotation body stored on the server. */
export function changeToBody(c: {
  origin: string | null;
  type: string | null;
  term: string | null;
  effect: string | null;
}) {
  return {
    anno_type: "code" as const,
    text: JSON.stringify({ origin: c.origin, type: c.type, term: c.term, effect: c.effect }),
    color: originColor(c.origin),
  };
}

/** Identity of a change for de-duping suggestions vs already-added changes. */
export function changeKey(c: { origin: string | null; type: string | null; term: string | null; effect: string | null }) {
  return `${c.origin ?? ""}|${c.type ?? ""}|${c.term ?? ""}|${c.effect ?? ""}`;
}

export type AnyChange = ChangeTag | SuggestedChange;
