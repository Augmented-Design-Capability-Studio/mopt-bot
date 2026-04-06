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

export type ProblemBlock = {
  weights: Record<string, number>;
  only_active_terms: boolean;
  algorithm: string;
  epochs: number | null;
  /** Default true when omitted from JSON. */
  early_stop: boolean;
  /** Override defaults when set; null omits key (backend defaults). */
  early_stop_patience: number | null;
  early_stop_epsilon: number | null;
  pop_size: number | null;
  random_seed: number | null;
  shift_hard_penalty: number | null;
  locked_assignments: Record<string, number>;
  driver_preferences: DriverPref[];
};
