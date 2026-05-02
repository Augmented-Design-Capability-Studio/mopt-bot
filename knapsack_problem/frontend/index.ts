import type { ProblemModule } from "@problemConfig/problemModule";
import { KnapsackSelectionViz } from "./KnapsackSelectionViz";
import { KNAPSACK_TUTORIAL_CONTENT } from "./tutorial";

function formatRunViolationSummary(result: unknown): string | null {
  if (!result || typeof result !== "object") return null;
  const r = result as Record<string, unknown>;
  const violations = r.violations as Record<string, unknown> | undefined;
  const vis = (r.visualization as Record<string, unknown> | undefined)?.payload as
    | Record<string, unknown>
    | undefined;
  const capOver = violations?.capacity_units_over ? Number(violations.capacity_units_over) : 0;
  const feasible = vis?.feasible;
  const parts: string[] = [];
  if (capOver) parts.push("over knapsack capacity");
  if (feasible === false) parts.push("infeasible selection");
  if (parts.length === 0) return "feasible packing";
  return parts.join(", ");
}

export const MODULE: ProblemModule = {
  vizTabs: [{ id: "knapsack_selection", label: "Item Selection", component: KnapsackSelectionViz }],
  formatRunViolationSummary,
  tutorialContent: KNAPSACK_TUTORIAL_CONTENT,
};
