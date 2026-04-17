/**
 * Generic solver configuration fields shared by all problem modules.
 * Problem-specific extensions live in their own module's frontend/ directory.
 * For example, the VRPTW extension is at vrptw_problem/frontend/types.ts.
 */
export type BaseProblemBlock = {
  weights: Record<string, number>;
  /** Goal-term keys locked against chat/definition-driven backend sync changes. */
  locked_goal_terms: string[];
  only_active_terms: boolean;
  algorithm: string;
  /** Current algorithm's hyperparameters (defaults merged from JSON). */
  algorithm_params: Record<string, number>;
  epochs: number | null;
  /** Default true when omitted from JSON. */
  early_stop: boolean;
  /** Override defaults when set; null omits key (backend defaults). */
  early_stop_patience: number | null;
  early_stop_epsilon: number | null;
  pop_size: number | null;
  random_seed: number | null;
  /** When true (default), seeds part of the initial population with greedy solutions. */
  use_greedy_init: boolean;
};
