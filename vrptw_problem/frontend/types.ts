/**
 * VRPTW-specific panel config types.
 * Extends BaseProblemBlock with fields that only exist in the fleet-scheduling problem.
 */

import type { BaseProblemBlock } from "@problemConfig/types";

/** One soft preference rule; optional fields depend on condition (backend validates). */
export type DriverPref = {
  vehicle_idx: number;
  condition: string;
  penalty: number;
  zone?: number;
  order_priority?: string;
  limit_minutes?: number;
  hours?: number;
  aggregation?: string;
};

export type ProblemBlock = BaseProblemBlock & {
  max_shift_hours: number | null;
  early_arrival_threshold_min: number | null;
  /** Fixed task-index → vehicle-index assignments (override decoded routes). */
  locked_assignments: Record<string, number>;
  driver_preferences: DriverPref[];
};
