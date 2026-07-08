import { useState } from "react";

import { formatClock } from "../lib/format";
import type { LoadedSummary, TimelineRow } from "../lib/types";

interface AnchorControlsProps {
  summary: LoadedSummary;
  playhead: number;
  hasVideo: boolean;
  anchorCandidates: TimelineRow[];
  onSetOffset: (offset: number) => void;
  onMarkFirstKeystroke: () => void;
  onMarkReady: () => void;
  onAddPause: (start: number, end: number) => void;
  onSetT0Iso: (iso: string) => void;
}

export function AnchorControls({
  summary,
  playhead,
  hasVideo,
  anchorCandidates,
  onSetOffset,
  onMarkFirstKeystroke,
  onMarkReady,
  onAddPause,
  onSetT0Iso,
}: AnchorControlsProps) {
  const [anchorRef, setAnchorRef] = useState<string>("");
  const [pauseStart, setPauseStart] = useState<number | null>(null);
  const [t0IsoInput, setT0IsoInput] = useState<string>("");

  const offsetSet = summary.clock_offset_sec != null;
  const t0Set = summary.t0_iso != null;

  function setAnchor() {
    const row = anchorCandidates.find((r) => r.row_ref === anchorRef);
    if (!row || row.epoch == null) return;
    onSetOffset(row.epoch - playhead);
  }

  const btn: React.CSSProperties = {
    fontSize: "0.8rem",
    padding: "0.25rem 0.5rem",
    cursor: hasVideo ? "pointer" : "not-allowed",
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.5rem",
        border: "1px solid var(--border, #ccc)",
        borderRadius: 6,
        padding: "0.6rem",
        fontSize: "0.85rem",
      }}
    >
      <div style={{ fontWeight: 600 }}>Clock & markers</div>

      <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
        <div className="muted">
          1. Anchor the clock: scrub to when a DB event appears on screen, pick it, set anchor.
        </div>
        <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
          <select
            value={anchorRef}
            onChange={(e) => setAnchorRef(e.target.value)}
            style={{ flex: 1, minWidth: 180, fontSize: "0.8rem" }}
          >
            <option value="">— pick a DB event —</option>
            {anchorCandidates.map((r) => (
              <option key={r.row_ref ?? ""} value={r.row_ref ?? ""}>
                {(r.timestamp_iso ?? "").slice(11, 19)} · {r.label} · {(r.summary ?? "").slice(0, 40)}
              </option>
            ))}
          </select>
          <button type="button" style={btn} disabled={!hasVideo || !anchorRef} onClick={setAnchor}>
            Set anchor @ {formatClock(playhead)}
          </button>
        </div>
        <div className="muted">
          Offset: {offsetSet ? `${summary.clock_offset_sec?.toFixed(2)}s` : "not set"}
        </div>
      </div>

      <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", alignItems: "center" }}>
        <button type="button" style={btn} disabled={!hasVideo || !offsetSet} onClick={onMarkFirstKeystroke}>
          Mark first keystroke (t0)
        </button>
        <button type="button" style={btn} disabled={!hasVideo} onClick={onMarkReady}>
          Mark declared-ready
        </button>
        <span className="muted">t0: {t0Set ? summary.t0_iso?.slice(11, 19) : "not set"}</span>
      </div>

      <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", alignItems: "center" }}>
        {pauseStart == null ? (
          <button type="button" style={btn} disabled={!hasVideo} onClick={() => setPauseStart(playhead)}>
            Pause start
          </button>
        ) : (
          <>
            <button
              type="button"
              style={btn}
              disabled={!hasVideo}
              onClick={() => {
                onAddPause(pauseStart, playhead);
                setPauseStart(null);
              }}
            >
              Resume (end pause)
            </button>
            <button type="button" style={btn} onClick={() => setPauseStart(null)}>
              Cancel
            </button>
            <span className="muted">pause from {formatClock(pauseStart)}</span>
          </>
        )}
      </div>

      <details>
        <summary className="muted" style={{ cursor: "pointer" }}>
          t0 wall-clock cross-check (optional)
        </summary>
        <div style={{ display: "flex", gap: "0.35rem", marginTop: "0.35rem" }}>
          <input
            type="text"
            placeholder="ISO e.g. 2026-04-28T15:35:02-04:00"
            value={t0IsoInput}
            onChange={(e) => setT0IsoInput(e.target.value)}
            style={{ flex: 1, fontSize: "0.8rem" }}
          />
          <button type="button" style={btn} disabled={!t0IsoInput.trim()} onClick={() => onSetT0Iso(t0IsoInput.trim())}>
            Set t0
          </button>
        </div>
      </details>
    </div>
  );
}
