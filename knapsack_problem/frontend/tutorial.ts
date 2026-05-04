import type { TutorialContent, TutorialStepOverride } from "@tutorial/types";
import type { TutorialStepId } from "@shared/api";

export const KNAPSACK_STARTER_PROMPT =
  "I would like to optimize for a simple knapsack problem. I have a list of 22 items with " +
  "various values and weights to put into a bag of 50-weight capacity. I want to maximize the " +
  "value in the bag without exceeding the capacity limit.";

/**
 * Knapsack-specific overrides on the default 12-step tutorial. Steps not
 * listed here (Step 6 read-run-summary, Step 11 mark-candidate, Step 12
 * third-run) inherit the generic copy from `defaultContent.ts`.
 */
function knapsackStepOverrides(
  mode: string | undefined,
): Partial<Record<TutorialStepId, TutorialStepOverride>> {
  const normalized = (mode ?? "demo").toLowerCase();
  const isWaterfall = normalized === "waterfall";
  const isAgile = normalized === "agile";
  // Anything that isn't waterfall/agile is treated as demo (the orientation
  // recording mode). Demo leans on open questions like waterfall but does not
  // gate runs on them.

  const chatInfoBody = isWaterfall
    ? "Tell the assistant about the knapsack task in plain language. The agent will work through open questions before suggesting a run — that's expected. You can paste the starter prompt below to skip typing."
    : isAgile
      ? "Tell the assistant about the knapsack task in plain language. The agent will help you make quick assumptions so you can iterate fast. You can paste the starter prompt below to skip typing."
      : "Tell the assistant about the knapsack task in plain language. The agent will work through the setup with you — answering its open questions or refining what it gathers as you go. You can paste the starter prompt below to skip typing.";

  const updateDefinitionBody = isWaterfall
    ? "Click the **Definition** tab. Each open question has an answer field — type your answer inline. Answering them is required before the first run is unlocked. You can also edit any Gathered row, then click **Save**."
    : isAgile
      ? "Click the **Definition** tab. Promote any agent assumption you agree with using the green ✓ button, edit a row to refine it if you want, then click **Save**."
      : "Click the **Definition** tab. Answer any open questions inline, or promote an assumption with the green ✓ button — refine any row as needed, then click **Save**. (Open questions here are advisory — they don't block your run.)";

  const firstRunBody = isWaterfall
    ? "Click **Run optimization**. With a weak capacity penalty, the solver may pack over the 50-unit limit on purpose — that's expected; we'll fix it next round. If the button is locked, double-check every open question has an answer."
    : "Click **Run optimization**. With a weak capacity penalty, the solver may pack over the 50-unit limit on purpose — that's expected; we'll fix it next round.";

  return {
    "chat-info": {
      body: chatInfoBody,
      actions: [{ kind: "fill-chat-input", label: "Use starter prompt", payload: KNAPSACK_STARTER_PROMPT }],
    },
    "upload-files": {
      title: "Step 2 - Upload knapsack data",
      body: "Click **Upload file(s)…** in the chat footer and add the knapsack item list. The assistant uses it to populate Gathered Info on the Definition tab.",
    },
    "update-definition": {
      body: updateDefinitionBody,
    },
    "inspect-config": {
      title: "Step 4 - Set up Run 1",
      body: "Click the **Problem Config** tab. On the `capacity_overflow` row, switch the constraint type to **Custom** and set the weight to `1`, then **Save**. We're deliberately keeping the capacity penalty weak so the solver packs over the limit — you'll see what infeasibility looks like next. (Optional: drag-rank the goal terms to set their relative priority — top of the list carries more weight.) The bubble advances once the save lands.",
    },
    "first-run": {
      title: "Step 5 - First run (probably infeasible)",
      body: firstRunBody,
    },
    "inspect-results": {
      title: "Step 7 - Inspect the visualizations",
      body: "Click the **Item Selection** and **Convergence** tabs above the chart to switch between views. Item Selection shows which items the solver packed and the total weight — check whether it exceeds 50 (that's the infeasibility we wanted to surface). Convergence shows how cost dropped over the run.",
    },
    "explain-run": {
      body: "Click the **Explain** button on the run card. The assistant will post a plain-language read of what worked and what didn't — including the capacity overrun if there is one.",
    },
    "update-config": {
      title: "Step 9 - Bump capacity penalty (Run 2 fix)",
      body: "Back on the **Problem Config** tab, switch the `capacity_overflow` row to **Custom** and raise the weight (try `100`), then **Save**. Custom is the only mode where you set the weight number directly, and your value sticks — agents won't quietly overwrite it later. (Switching to **Hard** also works if you want the limit strictly enforced.)",
    },
    "second-run": {
      title: "Step 10 - Run again (should be feasible)",
      body: "Run again. With a much stronger capacity penalty the packing should respect the 50-unit limit. Flip between Run #1 and Run #2 in the Results tabs to see exactly what shifted.",
    },
    "mark-candidate": {
      title: "Step 11 - Mark Run #2 as a candidate",
      body: "Tick **Include as candidate** on Run #2. The next optimization will seed its starting population from Run #2's solution instead of starting from scratch.",
    },
    "third-run": {
      title: "Step 12 - Third run from your candidate",
      body: "Run optimization a third time. It starts from Run #2's solution and usually finds a slightly better feasible packing — you should see the cost improve again on a feasible answer.",
    },
    "tutorial-complete": {
      title: "Nicely done",
      body: "You walked through the full iteration loop: an intentionally infeasible Run 1 → fixed it for Run 2 → seeded Run 3 from your best so far. That's the pattern: describe → run → interpret → adjust → re-run, with candidates carrying progress forward.",
    },
  };
}

export const KNAPSACK_TUTORIAL_CONTENT: TutorialContent = {
  stepOverrides: knapsackStepOverrides,
};
