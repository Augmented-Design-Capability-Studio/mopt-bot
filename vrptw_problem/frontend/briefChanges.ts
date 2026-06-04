/**
 * Human-readable description of VRPTW-specific brief changes between two
 * problem-brief states, used to itemize a definition-panel save in the synthetic
 * "Definition edited:" chat message (mirrors the "Config edited:" flow).
 *
 * The participant edits a goal term's "Rules —" prose; the backend structures it
 * into `goal_terms.worker_preference.properties.driver_preferences` at the save.
 * So this diffs the STRUCTURED carriers of `previous` (pre-save) vs `next`
 * (post-save, post-extraction) — which is why the caller must pass the brief
 * returned by the PATCH, not the locally-edited one.
 */

import type { ProblemBrief } from "@shared/api";

import { WORKER_NAMES, zoneLabelFromId } from "./metadata";
import type { DriverPref } from "./types";

function driverPrefsOf(brief: ProblemBrief | null | undefined): DriverPref[] {
  const gt = ((brief?.goal_terms ?? {}) as Record<string, unknown>);
  const wp = gt["worker_preference"] as { properties?: { driver_preferences?: unknown } } | undefined;
  const arr = wp?.properties?.driver_preferences;
  return Array.isArray(arr) ? (arr as DriverPref[]) : [];
}

function maxShiftOf(brief: ProblemBrief | null | undefined): number | null {
  const gt = ((brief?.goal_terms ?? {}) as Record<string, unknown>);
  const sl = gt["shift_limit"] as { properties?: { max_shift_hours?: unknown } } | undefined;
  const v = sl?.properties?.max_shift_hours;
  return typeof v === "number" ? v : null;
}

function ruleKey(p: DriverPref): string {
  return [p.vehicle_idx, p.condition, p.zone ?? "", p.order_priority ?? "", p.limit_minutes ?? p.hours ?? ""].join("|");
}

function hoursText(p: DriverPref): string {
  const mins = typeof p.limit_minutes === "number"
    ? p.limit_minutes
    : typeof p.hours === "number" ? p.hours * 60 : 390;
  const hrs = Number((mins / 60).toFixed(2));
  return `${hrs}h`;
}

function ruleText(p: DriverPref): string {
  const name = WORKER_NAMES[p.vehicle_idx] ?? `Driver ${p.vehicle_idx}`;
  if (p.condition === "avoid_zone") return `${name} avoids Zone ${zoneLabelFromId(p.zone)}`;
  if (p.condition === "order_priority") return `${name} skips ${p.order_priority ?? "express"}-priority orders`;
  if (p.condition === "shift_over_limit") return `${name} avoids shifts over ${hoursText(p)}`;
  return `${name} preference`;
}

export function vrptwDescribeBriefChanges(previous: ProblemBrief, next: ProblemBrief): string[] {
  const out: string[] = [];
  const prev = driverPrefsOf(previous);
  const cur = driverPrefsOf(next);
  const prevKeys = new Set(prev.map(ruleKey));
  const curKeys = new Set(cur.map(ruleKey));
  for (const p of cur) if (!prevKeys.has(ruleKey(p))) out.push(`Added driver preference — ${ruleText(p)}`);
  for (const p of prev) if (!curKeys.has(ruleKey(p))) out.push(`Removed driver preference — ${ruleText(p)}`);

  const pm = maxShiftOf(previous);
  const cm = maxShiftOf(next);
  if (pm !== cm) {
    if (cm == null) out.push("Removed the max shift-hours cap");
    else out.push(`Set max shift hours to ${cm}h`);
  }
  return out;
}
