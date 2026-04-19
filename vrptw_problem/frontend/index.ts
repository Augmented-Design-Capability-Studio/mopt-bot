import type { ProblemModule } from "@problemConfig/problemModule";
import { buildVrptwGoalTermsExtension } from "./VrptwExtras";
import { FleetScheduleViz } from "./FleetScheduleViz";
import { ViolationSummary } from "./ViolationSummary";
import { parseRoutesForSolver } from "./schedule";

function formatRunViolationSummary(result: unknown): string | null {
  if (!result || typeof result !== "object") return null;
  const violations = (result as Record<string, unknown>).violations as Record<string, unknown> | undefined;
  if (!violations) return null;
  const parts = [
    violations.time_window_stop_count ? `${violations.time_window_stop_count} time-window stops late` : "",
    violations.priority_deadline_misses ? `${violations.priority_deadline_misses} priority misses` : "",
    violations.capacity_units_over ? `${violations.capacity_units_over} units over capacity` : "",
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(", ") : "no violations";
}

export const MODULE: ProblemModule = {
  buildGoalTermsExtension: buildVrptwGoalTermsExtension,
  vizTabs: [{ id: "fleet_gantt", label: "Schedule", component: FleetScheduleViz }],
  ViolationSummary,
  parseEvalRoutes: parseRoutesForSolver,
  formatRunViolationSummary,
};
