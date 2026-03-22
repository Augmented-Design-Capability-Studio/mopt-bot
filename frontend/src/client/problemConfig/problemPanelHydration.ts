import { sessionPanelToConfigText, type Session } from "@shared/api";

export type ProblemPanelHydration = "follow" | "empty_until_server_panel";

/** When `text` is omitted, leave the textarea unchanged to avoid wiping drafts. */
export function resolveProblemPanelFromServer(
  mode: ProblemPanelHydration,
  panel: Session["panel_config"],
): { text?: string; mode: ProblemPanelHydration } {
  const text = sessionPanelToConfigText(panel);
  if (mode === "empty_until_server_panel") {
    if (text !== "") {
      return { text, mode: "follow" };
    }
    return { mode: "empty_until_server_panel" };
  }
  return { text, mode: "follow" };
}
