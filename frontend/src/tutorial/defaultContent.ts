import type { TutorialContent, TutorialStep } from "./types";

/**
 * Generic, problem-agnostic tutorial bodies used as a fallback when the active
 * problem module does not export `tutorialContent`. The step list mirrors the
 * 11-step participant journey:
 *
 *   1. chat-info             — start in chat
 *   2. upload-files          — upload data
 *   3. update-definition     — review + save Definition (the read-only inspect
 *                              step was dropped because the Definition tab is
 *                              already visible by default)
 *   4. inspect-config        — open Problem Config (no need to change anything)
 *   5. first-run             — first optimization run
 *   6. inspect-results       — review the convergence + visualization
 *   7. explain-run           — use Explain for a plain-language read
 *   8. update-config         — try one targeted change + Save
 *   9. second-run            — re-run and compare
 *  10. mark-candidate        — tick "Include as candidate"
 *  11. third-run             — third run, seeded by the candidate
 */
function defaultStepsForMode(mode: string | undefined): TutorialStep[] {
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
      id: "update-definition",
      title: "Step 3 - Update Definition",
      body: isAgile
        ? "Click the **Definition** tab. Adjust assumptions or gathered facts inline, then click **Save**."
        : isWaterfall
          ? "Click the **Definition** tab and answer the open questions inline — those answers gate the first run. You can also edit any Gathered row, then click **Save**."
          : "Click the **Definition** tab, update content as needed, and click **Save**.",
    },
    {
      id: "inspect-config",
      title: "Step 4 - Inspect Problem Config",
      body: "Click the **Problem Config** tab and review the numeric setup the solver will use. You don't need to change anything yet.",
    },
    {
      id: "first-run",
      title: "Step 5 - First run",
      body: isWaterfall
        ? "Start the first optimization run with the Run button. If the button is locked, double-check that every open question in the Definition tab has an answer."
        : "Start the first optimization run with the Run button (or by asking in chat).",
    },
    {
      id: "inspect-results",
      title: "Step 6 - Look at the results",
      body: "Review the convergence plot and the problem-specific visualization in the Results panel to see what the solver produced.",
    },
    {
      id: "explain-run",
      title: "Step 7 - Ask for an explanation",
      body: "Click the Explain button to ask the assistant for a plain-language read of the run in chat.",
    },
    {
      id: "update-config",
      title: "Step 8 - Try a targeted change",
      body: "Open Problem Config, edit one value (a weight, a term type, or a parameter), and Save.",
    },
    {
      id: "second-run",
      title: "Step 9 - Run again",
      body: "Run optimization again and compare the new run against the previous one.",
    },
    {
      id: "mark-candidate",
      title: "Step 10 - Mark a candidate",
      body: "Tick Include as candidate on a run you'd like to seed the next optimization from.",
    },
    {
      id: "third-run",
      title: "Step 11 - Third run from a candidate",
      body: "Run one more time. The new run will start from your selected candidate's solution.",
    },
    {
      id: "tutorial-complete",
      title: "All set",
      body: "That's the loop: describe, review, run, interpret, adjust. Keep iterating — small changes one at a time tend to teach you the most about your problem. You can always re-run, mark different candidates, or revisit Definition and Problem Config to refine the setup.",
      actions: [
        { kind: "complete-tutorial", label: "Got it!" },
      ],
    },
  ];
}

export const DEFAULT_TUTORIAL_CONTENT: TutorialContent = {
  stepsForMode: defaultStepsForMode,
};
