import { useEffect, useMemo, useRef, useState } from "react";

import type { AnalysisController } from "../hooks/useAnalysisController";
import type { TimelineRow } from "../lib/types";
import { AnchorControls } from "./AnchorControls";
import { EventList } from "./EventList";
import { VideoPane } from "./VideoPane";

/** Tab 1 — individual session coding against the video. */
export function SessionCodingTab({ ctl }: { ctl: AnalysisController }) {
  const [playhead, setPlayhead] = useState(0);
  const [liveId, setLiveId] = useState("");
  const [videoReady, setVideoReady] = useState(false);
  const [sortBy, setSortBy] = useState<"name" | "date">("date");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const videoElRef = useRef<HTMLVideoElement | null>(null);

  const sortedLoaded = useMemo(() => {
    const copy = [...ctl.loaded];
    if (sortBy === "name") {
      copy.sort((a, b) =>
        (a.participant_number ?? a.source_session_id ?? "").localeCompare(
          b.participant_number ?? b.source_session_id ?? "",
          undefined,
          { numeric: true, sensitivity: "base" },
        ),
      );
    } else {
      copy.sort((a, b) => (b.loaded_at ?? "").localeCompare(a.loaded_at ?? ""));
    }
    return copy;
  }, [ctl.loaded, sortBy]);

  // Drop selections for sessions that no longer exist (e.g. after a reload).
  useEffect(() => {
    setSelectedIds((prev) => {
      const live = new Set(ctl.loaded.map((s) => s.id));
      const next = new Set([...prev].filter((id) => live.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [ctl.loaded]);

  const allSelected = sortedLoaded.length > 0 && selectedIds.size === sortedLoaded.length;

  function toggleSelected(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelectedIds(allSelected ? new Set() : new Set(sortedLoaded.map((s) => s.id)));
  }

  function removeSelected() {
    const ids = [...selectedIds];
    if (!ids.length) return;
    if (confirm(`Remove ${ids.length} loaded session(s) and their coding?`)) {
      void ctl.removeManyLoaded(ids);
      setSelectedIds(new Set());
    }
  }

  const detail = ctl.detail;
  const summary = detail?.session ?? null;

  useEffect(() => {
    setPlayhead(0);
  }, [ctl.selectedId]);

  const anchorCandidates = useMemo(
    () =>
      (detail?.timeline ?? []).filter(
        (r) => (r.kind === "message" || r.kind === "run") && r.epoch != null,
      ),
    [detail?.timeline],
  );

  function seek(videoPos: number) {
    const el = videoElRef.current;
    if (el) el.currentTime = videoPos;
    setPlayhead(videoPos);
  }

  function saveNote(row: TimelineRow, text: string) {
    const trimmed = text.trim();
    if (row.annotation_id != null) {
      void ctl.editAnnotation(row.annotation_id, { text: trimmed });
      return;
    }
    if (!row.row_ref) return;
    const existing = (detail?.annotations ?? []).find(
      (a) => a.anno_type === "note" && a.row_ref === row.row_ref,
    );
    if (existing) void ctl.editAnnotation(existing.id, { text: trimmed });
    else if (trimmed) void ctl.addAnnotation({ anno_type: "note", row_ref: row.row_ref, text: trimmed });
  }

  const hasVideo = videoReady;

  return (
    <div style={{ display: "flex", gap: "0.75rem", height: "100%", minHeight: 0 }}>
      {/* Left rail: load + loaded list */}
      <aside style={{ width: 230, flexShrink: 0, overflow: "auto", fontSize: "0.85rem" }}>
        <label className="muted" style={{ display: "block", marginBottom: "0.5rem" }}>
          Load export (.db / .json)
          <input
            type="file"
            accept=".db,.sqlite,.sqlite3,.json,application/octet-stream,application/json"
            style={{ display: "block", marginTop: "0.25rem", fontSize: "0.78rem" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void ctl.uploadFile(f);
              e.currentTarget.value = "";
            }}
          />
        </label>
        <div style={{ display: "flex", gap: "0.25rem", marginBottom: "0.75rem" }}>
          <input
            type="text"
            placeholder="live session id"
            value={liveId}
            onChange={(e) => setLiveId(e.target.value)}
            style={{ flex: 1, fontSize: "0.75rem", minWidth: 0 }}
          />
          <button
            type="button"
            style={{ fontSize: "0.75rem" }}
            disabled={!liveId.trim()}
            onClick={() => {
              void ctl.loadLive(liveId.trim());
              setLiveId("");
            }}
          >
            +
          </button>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.35rem", marginBottom: "0.35rem" }}>
          <span style={{ fontWeight: 600, flex: 1 }}>Loaded ({ctl.loaded.length})</span>
          <label className="muted" style={{ fontSize: "0.72rem" }}>
            sort{" "}
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as "name" | "date")}
              style={{ fontSize: "0.72rem" }}
            >
              <option value="date">date</option>
              <option value="name">name</option>
            </select>
          </label>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.35rem", marginBottom: "0.35rem", fontSize: "0.75rem" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
            <input type="checkbox" checked={allSelected} onChange={toggleSelectAll} />
            all
          </label>
          <button
            type="button"
            disabled={selectedIds.size === 0}
            onClick={removeSelected}
            style={{ fontSize: "0.72rem", cursor: selectedIds.size ? "pointer" : "not-allowed" }}
          >
            Remove selected ({selectedIds.size})
          </button>
        </div>
        {sortedLoaded.map((s) => (
          <div
            key={s.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.25rem",
              padding: "0.3rem",
              borderRadius: 4,
              background: s.id === ctl.selectedId ? "rgba(59,130,246,0.15)" : undefined,
              cursor: "pointer",
            }}
            onClick={() => ctl.setSelectedId(s.id)}
          >
            <input
              type="checkbox"
              checked={selectedIds.has(s.id)}
              onClick={(e) => e.stopPropagation()}
              onChange={() => toggleSelected(s.id)}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600 }}>
                {s.participant_number ?? s.source_session_id?.slice(0, 8) ?? "—"}
              </div>
              <div className="muted" style={{ fontSize: "0.72rem" }}>
                {s.workflow_mode ?? "?"} · {s.counts.messages}m/{s.counts.runs}r
              </div>
            </div>
            <button
              type="button"
              title="remove"
              onClick={(e) => {
                e.stopPropagation();
                if (confirm("Remove this loaded session and its coding?")) void ctl.removeLoaded(s.id);
              }}
              style={{ fontSize: "0.75rem", cursor: "pointer" }}
            >
              ✕
            </button>
          </div>
        ))}
      </aside>

      {/* Main workspace */}
      <main style={{ flex: 1, minWidth: 0, display: "flex", gap: "0.75rem", minHeight: 0 }}>
        {!summary ? (
          <p className="muted">Load an export, then pick a session to code.</p>
        ) : (
          <>
            <div
              style={{
                width: "38%",
                minWidth: 320,
                display: "flex",
                flexDirection: "column",
                gap: "0.5rem",
                overflow: "auto",
              }}
            >
              <VideoPane
                playhead={playhead}
                onPlayheadChange={setPlayhead}
                onDurationChange={(d) => {
                  if (d != null) void ctl.patchMeta({ video_duration_sec: d });
                }}
                onVideoElReady={(el) => {
                  videoElRef.current = el;
                  setVideoReady(el != null);
                }}
                onFileChosen={(name) => void ctl.patchMeta({ video_filename: name })}
              />
              <AnchorControls
                summary={summary}
                playhead={playhead}
                hasVideo={hasVideo}
                anchorCandidates={anchorCandidates}
                onSetOffset={(offset) => void ctl.patchMeta({ clock_offset_sec: offset })}
                onMarkFirstKeystroke={() => void ctl.patchMeta({ t0_video_pos: playhead })}
                onMarkReady={() =>
                  void ctl.addAnnotation({
                    anno_type: "marker",
                    label: "declared-ready",
                    color: "#0ea5e9",
                    video_pos_sec: playhead,
                  })
                }
                onAddPause={(start, end) => void ctl.addPause({ start_video_pos: start, end_video_pos: end })}
                onSetT0Iso={(iso) => void ctl.patchMeta({ t0_iso: iso })}
              />
              <button
                type="button"
                style={{ fontSize: "0.85rem", padding: "0.35rem" }}
                onClick={() => void ctl.exportCsv()}
              >
                Export CSV
              </button>
              {detail && detail.pauses.length > 0 ? (
                <div style={{ fontSize: "0.8rem" }}>
                  <div style={{ fontWeight: 600 }}>Pauses</div>
                  {detail.pauses.map((p) => (
                    <div key={p.id} style={{ display: "flex", gap: "0.35rem" }}>
                      <span className="muted">
                        {p.start_video_pos.toFixed(0)}s → {p.end_video_pos?.toFixed(0) ?? "?"}s
                      </span>
                      <button
                        type="button"
                        onClick={() => void ctl.removePause(p.id)}
                        style={{ fontSize: "0.7rem", cursor: "pointer" }}
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>

            <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" }}>
              <EventList
                rows={detail?.timeline ?? []}
                playhead={playhead}
                offsetSet={summary.clock_offset_sec != null}
                onSeek={seek}
                onAddCode={(label, color) =>
                  void ctl.addAnnotation({
                    anno_type: "code",
                    label,
                    color,
                    video_pos_sec: playhead,
                  })
                }
                onSaveNote={saveNote}
                onDeleteAnnotation={(id) => void ctl.removeAnnotation(id)}
              />
            </div>
          </>
        )}
      </main>
    </div>
  );
}
