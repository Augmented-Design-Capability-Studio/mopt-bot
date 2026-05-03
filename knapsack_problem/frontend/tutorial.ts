import type { TutorialContent, TutorialStep } from "@tutorial/types";

export const KNAPSACK_STARTER_PROMPT =
  "I would like to optimize for a simple knapsack problem. I have a list of 22 items with " +
  "various values and weights to put into a bag of 50-weight capacity. I want to maximize the " +
  "value in the bag without exceeding the capacity limit.";

function knapsackStepsForMode(mode: string | undefined): TutorialStep[] {
  const normalized = (mode ?? "demo").toLowerCase();
  const isWaterfall = normalized === "waterfall";

  const chatInfoBody = isWaterfall
    ? "Tell the assistant about the knapsack task in plain language. The agent will work through open questions before suggesting a run — that's expected. You can paste the starter prompt below to skip typing."
    : "Tell the assistant about the knapsack task in plain language. The agent will help you make quick assumptions so you can iterate fast. You can paste the starter prompt below to skip typing.";

  const updateDefinitionBody = isWaterfall
    ? "Click the **Definition** tab. Each open question has an answer field — type your answer inline. Answering them is required before the first run is unlocked. You can also edit any Gathered row, then click **Save**."
    : "Click the **Definition** tab. Promote any agent assumption you agree with using ⬆, edit a row to refine it if you want, then click **Save**.";

  return [
    {
      id: "chat-info",
      title: "Step 1 - Start in chat",
      body: chatInfoBody,
      actions: [
        { kind: "fill-chat-input", label: "Use starter prompt", payload: KNAPSACK_STARTER_PROMPT },
      ],
    },
    {
      id: "upload-files",
      title: "Step 2 - Upload knapsack data",
      body: "Click **Upload file(s)…** in the chat footer and add the knapsack item list. The assistant uses it to populate Gathered Info on the Definition tab.",
    },
    {
      id: "update-definition",
      title: "Step 3 - Update Definition",
      body: updateDefinitionBody,
    },
    {
      id: "inspect-config",
      title: "Step 4 - Set up Run 1 (weak capacity)",
      body: "On the **Problem Config** tab, switch `capacity_overflow` to **Soft** and **Save**. (We are deliberately setting a weak capacity penalty to make the solver pack over the limit.) The bubble will move on once the save lands.",
    },
    {
      id: "first-run",
      title: "Step 5 - First run (probably infeasible)",
      body: isWaterfall
        ? "Click **Run optimization**. With a weak capacity penalty, the solver may pack over the 50-unit limit on purpose — that's expected; we'll fix it next round. If the button is locked, double-check every open question has an answer."
        : "Click **Run optimization**. With a weak capacity penalty, the solver may pack over the 50-unit limit on purpose — that's expected; we'll fix it next round.",
    },
    {
      id: "read-run-summary",
      title: "Step 6 - Read the run summary",
      body: "When the run finishes, the assistant posts a short summary in chat — a plain-language read of cost, feasibility, and what looked off. Skim it before you dig into the visualizations.",
      actions: [
        { kind: "acknowledge-step", label: "Done reading", flag: "tutorial_run_summary_read" },
      ],
    },
    {
      id: "inspect-results",
      title: "Step 7 - Inspect the visualizations",
      body: "Click the **Item Selection** and **Convergence** tabs above the chart to switch between views. Item Selection shows which items the solver packed and the total weight — check whether it exceeds 50 (that's the infeasibility we wanted to surface). Convergence shows how cost dropped over the run.",
    },
    {
      id: "explain-run",
      title: "Step 8 - Ask the assistant to explain",
      body: "Click the **Explain** button on the run card. The assistant will post a plain-language read of what worked and what didn't — including the capacity overrun if there is one.",
    },
    {
      id: "update-config",
      title: "Step 9 - Bump capacity penalty (Run 2 fix)",
      body: "Now fix the infeasibility on the **Problem Config** tab. Switch the `capacity_overflow` row to **Custom** and raise the weight (try `100`), then **Save**. You can only set a specific weight number when the type is Custom — Soft/Hard manage their weights for you. Custom also locks your value: agents will be more reluctant to overwrite it on later turns, which is what you want here. (If you'd rather the constraint be strictly enforced, **Hard** also works.)",
    },
    {
      id: "second-run",
      title: "Step 10 - Run again (should be feasible)",
      body: "Run again. With a much stronger capacity penalty the packing should respect the 50-unit limit. Flip between Run #1 and Run #2 in the Results tabs to see exactly what shifted.",
    },
    {
      id: "mark-candidate",
      title: "Step 11 - Mark Run #2 as a candidate",
      body: "Tick **Include as candidate** on Run #2. The next optimization will seed its starting population from Run #2's solution instead of starting from scratch.",
    },
    {
      id: "third-run",
      title: "Step 12 - Third run from your candidate",
      body: "Run optimization a third time. It starts from Run #2's solution and usually finds a slightly better feasible packing — you should see the cost improve again on a feasible answer.",
    },
    {
      id: "tutorial-complete",
      title: "Nicely done",
      body: "You walked through the full iteration loop: an intentionally infeasible Run 1 → fixed it for Run 2 → seeded Run 3 from your best so far. That's the pattern: describe → run → interpret → adjust → re-run, with candidates carrying progress forward.",
      actions: [
        { kind: "complete-tutorial", label: "Got it!" },
      ],
    },
  ];
}

export const KNAPSACK_TUTORIAL_CONTENT: TutorialContent = {
  stepsForMode: knapsackStepsForMode,
};
