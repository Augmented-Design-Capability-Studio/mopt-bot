const WEIGHT_INFO: Record<string, { label: string; description: string }> = {
  travel_time: {
    label: "Travel Time",
    description:
      "Penalizes total time spent in transit between stops. Higher values favour shorter, faster routes.",
  },
  fuel_cost: {
    label: "Fuel & Operating Cost",
    description:
      "Penalizes fuel consumption (scaled from travel time). Higher values favour fuel-efficient routes.",
  },
  deadline_penalty: {
    label: "On-Time Delivery",
    description:
      "Penalizes arriving after a stop's allowed time window. Higher values enforce stricter punctuality.",
  },
  capacity_penalty: {
    label: "Load Capacity Limits",
    description:
      "Penalizes loading beyond a vehicle's capacity. Higher values keep loads within safe limits.",
  },
  workload_balance: {
    label: "Workload Balance",
    description:
      "Penalizes unequal shift lengths across workers. Higher values produce a fairer distribution of work.",
  },
  worker_preference: {
    label: "Driver Preferences",
    description: "Weight on preference-rule cost units (per rules below).",
  },
  priority_penalty: {
    label: "Priority Order Deadlines",
    description:
      "Penalizes late delivery of express or high-priority tasks. Higher values protect critical deadlines.",
  },
};

/** Weight keys shown under “Goal terms” (routing / efficiency). */
const WEIGHT_GOAL_KEYS = ["travel_time", "fuel_cost", "workload_balance"] as const;

/** Weight keys shown under “Soft penalties” (violations / lateness), excluding worker_preference. */
const WEIGHT_SOFT_PENALTY_KEYS = ["deadline_penalty", "capacity_penalty", "priority_penalty"] as const;

/** Single panel order: routing, soft violations, then driver preference weight + rules. */
const WEIGHT_DISPLAY_ORDER = [
  ...WEIGHT_GOAL_KEYS,
  ...WEIGHT_SOFT_PENALTY_KEYS,
  "worker_preference",
] as const;

/** Same typography as `WEIGHT_INFO` rows — hard shift cap is not a weight key but sits with goal terms. */
const SHIFT_HARD_PENALTY_INFO = {
  label: "Max Shift Enforcement",
  description:
    "Large cost units applied per worker when a shift exceeds the platform maximum — strongly discourages overtime.",
} as const;

const ALGORITHM_DESC: Record<string, string> = {
  GA: "Genetic Algorithm - evolves a population of candidate solutions through selection, crossover, and mutation.",
  PSO: "Particle Swarm - a swarm of candidates converge collaboratively toward promising search regions.",
  SA: "Simulated Annealing - cools the search gradually to escape local optima and converge to good solutions.",
  SwarmSA:
    "Swarm Simulated Annealing - combines swarm-based exploration with annealing-style cooling.",
  ACOR: "Ant Colony Optimization (Continuous) - guides search by modelling pheromone accumulation along good paths.",
};

const CONDITION_LABEL: Record<string, string> = {
  zone_d: "avoid zone D (Westgate) stops",
  avoid_zone: "avoid a delivery zone (set zone A–E)",
  express_order: "avoid express / priority orders",
  order_priority: "avoid a priority class (express or standard)",
  shift_over_hours: "soft limit on shift length",
  shift_over_limit: "soft limit on shift length (use limit_minutes or hours)",
};

/** Worker index → display name for the QuickBite scenario. */
const WORKER_NAMES = ["Alice", "Bob", "Carol", "Dave", "Eve"] as const;

const PREFERENCE_CONDITIONS = [
  { value: "zone_d", label: "Avoid zone D (legacy)" },
  { value: "avoid_zone", label: "Avoid zone (specify A–E)" },
  { value: "express_order", label: "Avoid express orders (legacy)" },
  { value: "order_priority", label: "Avoid order priority class" },
  { value: "shift_over_hours", label: "Soft shift length (legacy hours)" },
  { value: "shift_over_limit", label: "Soft shift length (limit_minutes)" },
] as const;

export {
  ALGORITHM_DESC,
  SHIFT_HARD_PENALTY_INFO,
  WEIGHT_DISPLAY_ORDER,
  CONDITION_LABEL,
  PREFERENCE_CONDITIONS,
  WEIGHT_GOAL_KEYS,
  WEIGHT_INFO,
  WEIGHT_SOFT_PENALTY_KEYS,
  WORKER_NAMES,
};
