const WEIGHT_INFO: Record<string, { label: string; description: string }> = {
  travel_time: {
    label: "Travel time",
    description:
      "Penalizes total route and driving minutes (includes distance / time-in-transit goals).",
  },
  shift_limit: {
    label: "Max Shift Penalty",
    description:
      "Penalizes total minutes routes run past the configurable shift cap (summed over drivers). Set a high value to enforce a strict limit.",
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
      "Penalizes unequal drive+service time across workers (idle pre-window wait excluded). Higher values produce a fairer distribution of actual work.",
  },
  worker_preference: {
    label: "Driver Preferences",
    description: "Weight on preference-rule cost units (per rules below).",
  },
  priority_penalty: {
    label: "Express & priority deadlines",
    description:
      "Penalizes each express (or emphasized priority) order delivered after its deadline window. Higher values protect SLA-style orders.",
  },
  waiting_time: {
    label: "Early Arrival Penalty",
    description:
      "Penalizes each excess minute a driver arrives before the early-arrival grace period. Configure the grace-period threshold below.",
  },
};

/** Weight keys shown under "Goal terms" (routing / efficiency). */
const WEIGHT_GOAL_KEYS = ["travel_time", "shift_limit", "workload_balance"] as const;

/** Weight keys shown under "Soft penalties" (violations / lateness), excluding worker_preference. */
const WEIGHT_SOFT_PENALTY_KEYS = ["deadline_penalty", "capacity_penalty", "priority_penalty", "waiting_time"] as const;

/** Single panel order: routing, soft violations, then driver preference weight + rules. */
const WEIGHT_DISPLAY_ORDER = [
  ...WEIGHT_GOAL_KEYS,
  ...WEIGHT_SOFT_PENALTY_KEYS,
  "worker_preference",
] as const;

/** Metadata for the configurable maximum shift limit. */
const MAX_SHIFT_HOURS_INFO = {
  label: "Max Shift Hours",
  description:
    "The maximum allowed duration for a driver's shift (including travel and service time). Exceeding this triggers the penalty weight above.",
} as const;

/** Metadata for the early-arrival grace-period threshold. */
const EARLY_ARRIVAL_THRESHOLD_INFO = {
  label: "Early Arrival Threshold",
  description:
    "Grace period in minutes. Drivers arriving within this window before a time window opens are not penalised; only arrivals beyond this threshold accumulate the early-arrival penalty above.",
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
  EARLY_ARRIVAL_THRESHOLD_INFO,
  MAX_SHIFT_HOURS_INFO,
  WEIGHT_DISPLAY_ORDER,
  CONDITION_LABEL,
  PREFERENCE_CONDITIONS,
  WEIGHT_GOAL_KEYS,
  WEIGHT_INFO,
  WEIGHT_SOFT_PENALTY_KEYS,
  WORKER_NAMES,
};
