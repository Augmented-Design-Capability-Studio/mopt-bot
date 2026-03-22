export type DriverPref = { vehicle_idx: number; condition: string; penalty: number };

export type ProblemBlock = {
  weights: Record<string, number>;
  only_active_terms: boolean;
  algorithm: string;
  epochs: number | null;
  pop_size: number | null;
  random_seed: number | null;
  shift_hard_penalty: number | null;
  locked_assignments: Record<string, number>;
  driver_preferences: DriverPref[];
};
