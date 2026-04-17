import type { ProblemModule } from "@problemConfig/problemModule";
import { KnapsackSelectionViz } from "./KnapsackSelectionViz";

export const MODULE: ProblemModule = {
  vizTabs: [{ id: "knapsack_selection", label: "Item Selection", component: KnapsackSelectionViz }],
};
