import { TUTORIAL_STEP_IDS, type Session, type TutorialStepId } from "@shared/api";

export type TutorialStep = {
  id: TutorialStepId;
  title: string;
  body: string;
};

export type TutorialCompletionByStepId = Record<TutorialStepId, boolean>;

export function tutorialStepsForMode(mode: string | undefined): TutorialStep[] {
  const normalized = (mode ?? "demo").toLowerCase();
  const isAgile = normalized === "agile";
  const isWaterfall = normalized === "waterfall";
  return [
    {
      id: "chat-info",
      title: "Step 1 - Start in chat",
      body: isAgile
        ? "Share your first framing in chat. The agent should gather information from you and help you make quick assumptions."
        : isWaterfall
          ? "Share your first framing in chat. The agent should gather information from you and start asking questions."
          : "Share your first framing in chat so the assistant can initialize the problem context.",
    },
    {
      id: "upload-files",
      title: "Step 2 - Upload files",
      body: "Use Upload file(s)... to add inputs before your first optimization run.",
    },
    {
      id: "inspect-definition",
      title: "Step 3 - Inspect Definition",
      body: isAgile
        ? "Review the Definition tab and check whether key assumptions are captured."
        : isWaterfall
          ? "Review the Definition tab, especially open questions and missing clarifications."
          : "Review the Definition tab before editing.",
    },
    {
      id: "update-definition",
      title: "Step 4 - Update definition",
      body: isAgile
        ? "Adjust assumptions or gathered facts in Definition, then Save."
        : isWaterfall
          ? "Update Definition and resolve clarifications/open questions where possible, then Save."
          : "Update Definition content and click Save.",
    },
    {
      id: "inspect-config",
      title: "Step 5 - Inspect Problem Config",
      body: "Once config is generated, open Problem Config and review what will be run.",
    },
    {
      id: "first-run",
      title: "Step 6 - Trigger first run",
      body: "Start optimization with the Run button (or by asking in chat).",
    },
    {
      id: "update-config",
      title: "Step 7 - Edit problem config",
      body: "Open Problem Config, edit values directly, and Save to test a targeted change.",
    },
    {
      id: "second-run",
      title: "Step 8 - Run again",
      body: "Run optimization again and compare against your first run.",
    },
  ];
}

export function getTutorialStepOverride(session: Session | null): TutorialStepId | null {
  const step = session?.tutorial_step_override;
  if (!step) return null;
  if (!TUTORIAL_STEP_IDS.includes(step)) return null;
  return step;
}

export function completionFromSession(session: Session | null): TutorialCompletionByStepId {
  return {
    "chat-info": Boolean(session?.tutorial_chat_started),
    "upload-files": Boolean(session?.tutorial_uploaded_files),
    "inspect-definition": Boolean(session?.tutorial_definition_tab_visited),
    "update-definition": Boolean(session?.tutorial_definition_saved),
    "inspect-config": Boolean(session?.tutorial_config_tab_visited),
    "first-run": Boolean(session?.tutorial_first_run_done),
    "update-config": Boolean(session?.tutorial_config_saved),
    "second-run": Boolean(session?.tutorial_second_run_done),
  };
}
