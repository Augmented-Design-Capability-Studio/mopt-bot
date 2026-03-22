import type { Session } from "@shared/api";
import type { ClientSessionHistoryEntry } from "./sessionHistory";

export type EditMode = "none" | "definition" | "config" | "results";

export type RecentSessionRow = {
  id: string;
  session?: Session;
  history?: ClientSessionHistoryEntry;
  error?: string;
};
