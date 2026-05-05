import type { ProblemModule } from "@problemConfig/problemModule";
import "./styles.css";
import { buildVrptwGoalTermsExtension } from "./VrptwExtras";
import { FleetScheduleViz } from "./FleetScheduleViz";
import { parseRoutesForSolver } from "./schedule";
import { parseProblemConfig } from "./serialization";

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
  getAdditionalGoalTermKeys: (configJson: string) => {
    const { problem } = parseProblemConfig(configJson);
    return problem.max_shift_hours !== null ? ["shift_limit"] : [];
  },
  buildGoalTermsExtension: buildVrptwGoalTermsExtension,
  vizTabs: [{ id: "fleet_gantt", label: "Schedule", component: FleetScheduleViz }],
  parseEvalRoutes: parseRoutesForSolver,
  formatRunViolationSummary,
};
