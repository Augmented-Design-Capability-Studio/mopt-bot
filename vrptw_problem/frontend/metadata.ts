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
  lateness_penalty: {
    label: "Overall Punctuality",
    description:
      "Penalizes arriving after any stop's allowed time window. Higher values enforce stricter overall punctuality.",
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
  express_miss_penalty: {
    label: "Express order misses",
    description:
      "Penalizes each express order delivered after its deadline window. Higher values protect express SLA orders.",
  },
  waiting_time: {
    label: "Idle Wait Time",
    description:
      "Penalizes total idle minutes a driver waits before a time window opens. Use this to minimize schedule slack and discourage routes where drivers arrive far ahead of their service window.",
  },
};

/** Metadata for the configurable maximum shift limit. */
const MAX_SHIFT_HOURS_INFO = {
  label: "Max Shift Hours",
  description:
    "The maximum allowed duration for a driver's shift (including travel and service time). Exceeding this triggers the penalty weight above.",
} as const;

const CONDITION_LABEL: Record<string, string> = {
  avoid_zone: "avoid a delivery zone (set zone A–E)",
  order_priority: "avoid a priority class (express or standard)",
  shift_over_limit: "soft limit on shift length (use limit_minutes or hours)",
};

/** Worker index → display name for the QuickBite scenario. */
const WORKER_NAMES = ["Alice", "Bob", "Carol", "Dave", "Eve"] as const;

const PREFERENCE_CONDITIONS = [
  { value: "avoid_zone", label: "Avoid zone (specify A–E)" },
  { value: "order_priority", label: "Avoid order priority class" },
  { value: "shift_over_limit", label: "Soft shift length (limit_minutes)" },
] as const;

export type ZoneSpec = {
  id: number;
  letter: string;
  name: string;
  label: string;
};

export const ALL_ZONES: ZoneSpec[] = [
  { id: 0, letter: "DEPOT", name: "Depot", label: "Depot (0)" },
  { id: 1, letter: "A", name: "Riverside", label: "A - Riverside" },
  { id: 2, letter: "B", name: "Harbor", label: "B - Harbor" },
  { id: 3, letter: "C", name: "Uptown", label: "C - Uptown" },
  { id: 4, letter: "D", name: "Westgate", label: "D - Westgate" },
  { id: 5, letter: "E", name: "Northgate", label: "E - Northgate" },
];

export const DELIVERY_ZONES: ZoneSpec[] = [...ALL_ZONES.filter((zone) => zone.id >= 1)];

const ZONE_BY_ID = new Map<number, ZoneSpec>(ALL_ZONES.map((zone) => [zone.id, zone]));
const ZONE_BY_LETTER = new Map<string, ZoneSpec>(ALL_ZONES.map((zone) => [zone.letter, zone]));
const ZONE_BY_NAME = new Map<string, ZoneSpec>(ALL_ZONES.map((zone) => [zone.name.toLowerCase(), zone]));

export function zoneById(id: number | null | undefined): ZoneSpec | null {
  if (typeof id !== "number") return null;
  return ZONE_BY_ID.get(id) ?? null;
}

export function zoneLabelFromId(id: number | null | undefined): string {
  return zoneById(id)?.label ?? "?";
}

export function parseZoneValue(raw: unknown): number | null {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string") {
    const cleaned = raw.trim();
    if (!cleaned) return null;
    const numeric = Number.parseInt(cleaned, 10);
    if (!Number.isNaN(numeric)) return numeric;
    const byLetter = ZONE_BY_LETTER.get(cleaned.toUpperCase());
    if (byLetter) return byLetter.id;
    const byName = ZONE_BY_NAME.get(cleaned.toLowerCase());
    if (byName) return byName.id;
  }
  return null;
}

export {
  CONDITION_LABEL,
  MAX_SHIFT_HOURS_INFO,
  PREFERENCE_CONDITIONS,
  WEIGHT_INFO,
  WORKER_NAMES,
};
