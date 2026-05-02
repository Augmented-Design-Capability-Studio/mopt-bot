import type { TutorialStepId } from "@shared/api";

type TutorialAnchor =
  | "chat-composer"
  | "upload-button"
  | "definition-tab"
  | "definition-save"
  | "config-tab"
  | "config-save"
  | "run-optimize"
  | "results-viz"
  | "explain-button"
  | "candidate-checkbox";

type TutorialEditMode = "none" | "definition" | "config" | "results";

export function anchorForTutorialStep(stepId: TutorialStepId, editMode: TutorialEditMode): TutorialAnchor {
  switch (stepId) {
    case "chat-info":
      return "chat-composer";
    case "upload-files":
      return "upload-button";
    case "inspect-definition":
      // Legacy step. Anchor at the Definition tab so the bubble still has a
      // sensible target if a researcher jumps a session here.
      return "definition-tab";
    case "update-definition":
      return editMode === "definition" ? "definition-save" : "definition-tab";
    case "inspect-config":
      return "config-tab";
    case "first-run":
      return "run-optimize";
    case "inspect-results":
      return "results-viz";
    case "explain-run":
      return "explain-button";
    case "update-config":
      return editMode === "config" ? "config-save" : "config-tab";
    case "second-run":
      return "run-optimize";
    case "mark-candidate":
      return "candidate-checkbox";
    case "third-run":
      return "run-optimize";
    case "tutorial-complete":
      // Wrap-up has no specific action target; anchor at the run button so the
      // bubble lands somewhere visible without picking a misleading element.
      return "run-optimize";
  }
}
