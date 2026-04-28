import type { TutorialStepId } from "@shared/api";

type TutorialAnchor =
  | "chat-composer"
  | "upload-button"
  | "definition-tab"
  | "definition-save"
  | "config-tab"
  | "config-save"
  | "run-optimize";

type TutorialEditMode = "none" | "definition" | "config" | "results";

export function anchorForTutorialStep(stepId: TutorialStepId, editMode: TutorialEditMode): TutorialAnchor {
  switch (stepId) {
    case "chat-info":
      return "chat-composer";
    case "upload-files":
      return "upload-button";
    case "inspect-definition":
      return "definition-tab";
    case "update-definition":
      return editMode === "definition" ? "definition-save" : "definition-tab";
    case "inspect-config":
      return "config-tab";
    case "first-run":
      return "run-optimize";
    case "update-config":
      return editMode === "config" ? "config-save" : "config-tab";
    case "second-run":
      return "run-optimize";
  }
}
