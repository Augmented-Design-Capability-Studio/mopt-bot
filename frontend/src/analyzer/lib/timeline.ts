import type { ArchiveRun, SessionArchive, TimelineRow } from "./types";

export function displayRunNumber(run: ArchiveRun, index: number): number {
  const n = run.run_number;
  if (typeof n === "number" && Number.isFinite(n)) return n;
  const idx = run.session_run_index;
  if (typeof idx === "number" && Number.isFinite(idx)) return idx + 1;
  return index + 1;
}

/**
 * Reproduces `app.session_export.build_export_timeline` for archives that
 * don't carry a pre-built `timeline` (e.g. SQLite-derived). Idempotent: if
 * the archive already has one, we use it verbatim so the JSON path matches
 * what the backend served.
 */
export function buildTimelineFromArchive(archive: SessionArchive): TimelineRow[] {
  if (Array.isArray(archive.timeline)) {
    return archive.timeline.filter(
      (row): row is TimelineRow =>
        row !== null && typeof row === "object" && typeof row.kind === "string" && typeof row.at === "string",
    );
  }

  const rows: { sort: string; row: TimelineRow }[] = [];

  for (const m of archive.messages ?? []) {
    const at = m.created_at ?? "";
    const content = m.content ?? "";
    const summary = content.replace(/\s+/g, " ").trim().slice(0, 200);
    rows.push({
      sort: `${at}\x00message\x00${m.id}`,
      row: {
        kind: "message",
        at,
        label: `${m.role ?? "?"}/${m.kind ?? "?"}`,
        payload_summary: summary.length < content.length ? `${summary}…` : summary,
        ref: { message_id: m.id },
      },
    });
  }

  for (const s of archive.snapshots ?? []) {
    const at = s.created_at ?? "";
    const hasBrief = s.problem_brief != null;
    const hasPanel = s.panel_config != null;
    rows.push({
      sort: `${at}\x00snapshot\x00${s.id}`,
      row: {
        kind: "snapshot",
        at,
        label: s.event_type ?? "snapshot",
        payload_summary: `brief=${hasBrief ? "yes" : "no"} panel=${hasPanel ? "yes" : "no"}`,
        ref: { snapshot_id: s.id },
      },
    });
  }

  (archive.runs ?? []).forEach((r, i) => {
    const at = r.created_at ?? "";
    const rn = displayRunNumber(r, i);
    rows.push({
      sort: `${at}\x00run\x00${r.id}`,
      row: {
        kind: "run",
        at,
        label: r.run_type ?? "run",
        payload_summary: `ok=${String(r.ok)} cost=${String(r.cost ?? "—")} (#${rn})`,
        ref: { run_id: r.id, run_number: rn },
      },
    });
  });

  rows.sort((a, b) => (a.sort < b.sort ? -1 : a.sort > b.sort ? 1 : 0));
  return rows.map((x) => x.row);
}
