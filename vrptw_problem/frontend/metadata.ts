/**
 * VRPTW-specific weight metadata, driver-preference labels, and scenario constants.
 * Kept here so the vrptw_problem module owns its own frontend representation.
 */

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
    label: "Early Arrival / Wait Time",
    description:
      "Penalizes each excess minute a driver arrives too early. Use only for explicit early-arrival or grace-period constraints, and configure the grace-period threshold below.",
  },
};

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
  CONDITION_LABEL,
  EARLY_ARRIVAL_THRESHOLD_INFO,
  MAX_SHIFT_HOURS_INFO,
  PREFERENCE_CONDITIONS,
  WEIGHT_INFO,
  WORKER_NAMES,
};
