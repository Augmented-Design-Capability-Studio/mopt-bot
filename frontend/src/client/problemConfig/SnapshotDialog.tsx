import { useState } from "react";
import type { SnapshotSummary } from "@shared/api";
import { DialogShell } from "@shared/components/DialogShell";
import { parseServerDate } from "@shared/dateTime";

function formatSnapshotTime(iso: string): string {
  try {
    const d = parseServerDate(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function formatSnapshotLabel(snap: SnapshotSummary): string {
  const parts: string[] = [`${snap.items_count} items`, `${snap.questions_count} questions`];
  if (snap.has_config) parts.push("config");
  return parts.join(" · ");
}

function formatSnapshotOrigin(eventType: string): string {
  switch (eventType) {
    case "before_run":
      return "Run snapshot";
    case "manual_save":
      return "Autosave";
    case "bookmark":
      return "Manual snapshot";
    default:
      return "Snapshot";
  }
}

function buildRunSnapshotNumberById(snapshots: SnapshotSummary[]): Map<number, number> {
  const runSnapshotNumberById = new Map<number, number>();
  let runNumber = 0;
  const chronological = [...snapshots].sort((a, b) => {
    const byTime = Date.parse(a.created_at) - Date.parse(b.created_at);
    if (Number.isFinite(byTime) && byTime !== 0) return byTime;
    return a.id - b.id;
  });
  for (const snap of chronological) {
    if (snap.event_type !== "before_run") continue;
    runNumber += 1;
    runSnapshotNumberById.set(snap.id, runNumber);
  }
  return runSnapshotNumberById;
}

function snapshotHasOtherSide(snap: SnapshotSummary, sourceTab: "definition" | "config"): boolean {
  if (sourceTab === "definition") return snap.has_config;
  return snap.problem_brief !== null && typeof snap.problem_brief === "object";
}

type SnapshotDialogProps = {
  open: boolean;
  onClose: () => void;
  snapshots: SnapshotSummary[];
  loading: boolean;
  sourceTab: "definition" | "config";
  sessionTerminated: boolean;
  busy: boolean;
  onRestore: (snapshot: SnapshotSummary, scope: "definition" | "config" | "both") => void;
};

export function SnapshotDialog({
  open,
  onClose,
  snapshots,
  loading,
  sourceTab,
  sessionTerminated,
  busy,
  onRestore,
}: SnapshotDialogProps) {
  const [pendingSnapshot, setPendingSnapshot] = useState<SnapshotSummary | null>(null);
  const runSnapshotNumberById = buildRunSnapshotNumberById(snapshots);

  const closeAndReset = () => {
    setPendingSnapshot(null);
    onClose();
  };

  const handleSelect = (snap: SnapshotSummary) => {
    if (busy || sessionTerminated) return;
    if (snapshotHasOtherSide(snap, sourceTab)) {
      setPendingSnapshot(snap);
      return;
    }
    onRestore(snap, sourceTab);
    closeAndReset();
  };

  const restoreWithScope = (scope: "definition" | "config" | "both") => {
    if (!pendingSnapshot) return;
    onRestore(pendingSnapshot, scope);
    closeAndReset();
  };

  const otherLabel = sourceTab === "definition" ? "configuration" : "definition";
  const primaryLabel = sourceTab === "definition" ? "definition" : "configuration";

  if (pendingSnapshot) {
    const runNumber = runSnapshotNumberById.get(pendingSnapshot.id);
    const origin = pendingSnapshot.event_type === "before_run" && runNumber
      ? `Run snapshot #${runNumber}`
      : formatSnapshotOrigin(pendingSnapshot.event_type);
    return (
      <DialogShell
        open={open}
        title="Also load matching saved data?"
        titleId="snapshot-dlg-title"
        actions={
          <>
            <button type="button" onClick={() => setPendingSnapshot(null)} disabled={busy}>
              Back
            </button>
            <button
              type="button"
              onClick={() => restoreWithScope(sourceTab)}
              disabled={busy || sessionTerminated}
            >
              {primaryLabel === "definition" ? "Definition only" : "Configuration only"}
            </button>
            <button
              type="button"
              className="primary"
              onClick={() => restoreWithScope("both")}
              disabled={busy || sessionTerminated}
            >
              Load both (recommended)
            </button>
          </>
        }
        maxWidth="420px"
      >
        <p style={{ fontSize: "0.9rem", margin: "0 0 0.5rem" }}>
          {origin} · {formatSnapshotTime(pendingSnapshot.created_at)} also includes a saved problem {otherLabel}.
        </p>
        <p className="muted" style={{ fontSize: "0.85rem", margin: 0 }}>
          Loading only the {primaryLabel} may leave it out of sync with the current {otherLabel} and produce inaccurate results. We recommend restoring both together.
        </p>
      </DialogShell>
    );
  }

  return (
    <DialogShell
      open={open}
      title="Load from snapshot"
      titleId="snapshot-dlg-title"
      actions={
        <button type="button" onClick={closeAndReset}>
          Close
        </button>
      }
      maxWidth="360px"
    >
      {loading ? (
        <p className="muted" style={{ fontSize: "0.9rem" }}>
          Loading snapshots...
        </p>
      ) : snapshots.length === 0 ? (
        <p className="muted" style={{ fontSize: "0.9rem" }}>
          No snapshots yet. Use Snapshot → Save to snapshot, or save definition/config after editing.
        </p>
      ) : (
        <ul
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            maxHeight: "16rem",
            overflowY: "auto",
          }}
        >
          {snapshots.map((snap) => {
            const runNumber = runSnapshotNumberById.get(snap.id);
            const origin = snap.event_type === "before_run" && runNumber
              ? `Run snapshot #${runNumber}`
              : formatSnapshotOrigin(snap.event_type);
            return (
            <li key={snap.id}>
              <button
                type="button"
                disabled={busy || sessionTerminated}
                onClick={() => handleSelect(snap)}
                title={`Restore ${origin} from ${formatSnapshotTime(snap.created_at)}`}
                style={{
                  display: "block",
                  width: "100%",
                  padding: "0.5rem 0.4rem",
                  marginBottom: "0.2rem",
                  textAlign: "left",
                  fontSize: "0.9rem",
                  border: "1px solid var(--border)",
                  borderRadius: "2px",
                  background: "transparent",
                  cursor: busy || sessionTerminated ? "default" : "pointer",
                }}
              >
                <span style={{ fontWeight: 500 }}>
                  {origin} · {formatSnapshotTime(snap.created_at)}
                </span>
                <span className="muted" style={{ display: "block", fontSize: "0.8rem", marginTop: "0.15rem" }}>
                  {formatSnapshotLabel(snap)}
                </span>
              </button>
            </li>
          );
          })}
        </ul>
      )}
    </DialogShell>
  );
}
