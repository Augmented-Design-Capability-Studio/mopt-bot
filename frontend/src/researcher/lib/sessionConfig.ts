import type { Session } from "@shared/api";

export function getOnlyActiveTerms(panel: Session["panel_config"]): boolean {
  if (!panel || typeof panel !== "object" || Array.isArray(panel)) return true;
  const problem = (panel as Record<string, unknown>).problem;
  if (!problem || typeof problem !== "object" || Array.isArray(problem)) return true;
  const flag = (problem as Record<string, unknown>).only_active_terms;
  return typeof flag === "boolean" ? flag : true;
}
