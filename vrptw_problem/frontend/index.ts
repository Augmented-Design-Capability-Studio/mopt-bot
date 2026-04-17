import type { ProblemModule } from "@problemConfig/problemModule";
import { buildVrptwGoalTermsExtension } from "./VrptwExtras";
import { FleetScheduleViz } from "./FleetScheduleViz";
import { ViolationSummary } from "./ViolationSummary";

export const MODULE: ProblemModule = {
  buildGoalTermsExtension: buildVrptwGoalTermsExtension,
  vizTabs: [{ id: "fleet_gantt", label: "Schedule", component: FleetScheduleViz }],
  ViolationSummary,
};
