import type { Session } from "@shared/api";

export type EditMode = "none" | "config" | "results";

export type RecentSessionRow = {
  id: string;
  session?: Session;
  error?: string;
};
