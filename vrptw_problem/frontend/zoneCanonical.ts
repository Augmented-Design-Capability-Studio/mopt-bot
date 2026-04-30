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

export const DELIVERY_ZONES: ZoneSpec[] = [
  ...ALL_ZONES.filter((zone) => zone.id >= 1),
];

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
