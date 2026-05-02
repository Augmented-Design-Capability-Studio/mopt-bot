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
    ? "Resolve the open questions in the Definition tab — those are gating the first run. You can also edit any Gathered row inline if a confirmed fact needs adjustment. Then **Save**."
    : "On the Definition tab, promote any agent assumption you agree with using ⬆, edit a row if you want to refine it, then **Save**.";

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
      actions: [
        { kind: "switch-tab", label: "Open Definition", target: "definition" },
      ],
    },
    {
      id: "inspect-config",
      title: "Step 4 - Inspect Problem Config",
      body: "Open Problem Config and have a look at the numeric setup. Each goal term has a **type** (Obj / Soft / Hard / Custom), a **rank** (drag to reorder), and an **importance level** you can edit. You don't need to change anything yet.",
      actions: [
        { kind: "switch-tab", label: "Open Problem Config", target: "config" },
      ],
    },
    {
      id: "first-run",
      title: "Step 5 - First run",
      body: "Click **Run optimization** to get a baseline.",
    },
    {
      id: "inspect-results",
      title: "Step 6 - Look at the results",
      body: "Switch to the Results panel. Look at the cost, the convergence trace, and the **Item Selection** view — that's exactly which items the solver picked for the bag.",
    },
    {
      id: "explain-run",
      title: "Step 7 - Ask the assistant to explain",
      body: "Click the **Explain** button on the run card. The assistant will post a plain-language read of strengths, weak spots, and suggested next steps in chat.",
    },
    {
      id: "update-config",
      title: "Step 8 - Targeted change",
      body: "Try one targeted change — bump the capacity penalty, switch a term's type from soft to hard, or re-rank priorities — then Save. One lever at a time keeps comparisons clean.",
    },
    {
      id: "second-run",
      title: "Step 9 - Run again and compare",
      body: "Run again. The Results tabs let you flip between Run #1 and Run #2 to see what shifted.",
    },
    {
      id: "mark-candidate",
      title: "Step 10 - Mark the better run as a candidate",
      body: "Tick **Include as candidate** on the run you like better. The next optimization will seed its initial population from that run instead of starting from scratch.",
    },
    {
      id: "third-run",
      title: "Step 11 - Third run from your candidate",
      body: "Run optimization a third time. It starts from the candidate you ticked, which usually produces a faster refinement than starting fresh.",
    },
    {
      id: "tutorial-complete",
      title: "Nicely done",
      body: "You've walked the full loop on the knapsack practice: chat → upload → review → run → interpret → adjust → re-run. Keep experimenting — try different term types, re-rank priorities, or seed multiple candidates. The more you iterate, the better feel you'll get for the trade-offs.",
      actions: [
        { kind: "complete-tutorial", label: "Got it!" },
      ],
    },
  ];
}

export const KNAPSACK_TUTORIAL_CONTENT: TutorialContent = {
  stepsForMode: knapsackStepsForMode,
};
