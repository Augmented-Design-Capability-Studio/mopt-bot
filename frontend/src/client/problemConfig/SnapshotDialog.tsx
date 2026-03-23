import type { SnapshotSummary } from "@shared/api";
import { DialogShell } from "@shared/components/DialogShell";

function formatSnapshotTime(iso: string): string {
  try {
    const d = new Date(iso);
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

type SnapshotDialogProps = {
  open: boolean;
  onClose: () => void;
  snapshots: SnapshotSummary[];
  loading: boolean;
  sourceTab: "definition" | "config";
  sessionTerminated: boolean;
  busy: boolean;
  onRestore: (snapshot: SnapshotSummary, sourceTab: "definition" | "config") => void;
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
  const handleSelect = (snap: SnapshotSummary) => {
    if (busy || sessionTerminated) return;
    onRestore(snap, sourceTab);
    onClose();
  };

  return (
    <DialogShell
      open={open}
      title="Load from snapshot"
      titleId="snapshot-dlg-title"
      actions={
        <button type="button" onClick={onClose}>
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
          No snapshots yet. Save the definition or config to create one.
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
          {snapshots.map((snap) => (
            <li key={snap.id}>
              <button
                type="button"
                disabled={busy || sessionTerminated}
                onClick={() => handleSelect(snap)}
                title={`Restore from ${formatSnapshotTime(snap.created_at)}`}
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
                <span style={{ fontWeight: 500 }}>{formatSnapshotTime(snap.created_at)}</span>
                <span className="muted" style={{ display: "block", fontSize: "0.8rem", marginTop: "0.15rem" }}>
                  {formatSnapshotLabel(snap)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </DialogShell>
  );
}
