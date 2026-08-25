import { useEffect, useMemo, useRef, useState } from "react";

import { DialogShell } from "@shared/components/DialogShell";

import type { AnalysisController } from "../hooks/useAnalysisController";
import { changeKey, changeToBody } from "../lib/facets";
import type { Annotation, ChangeTag, TimelineRow } from "../lib/types";
import { AnchorControls } from "./AnchorControls";
import { EventList } from "./EventList";
import { LlmReasonDialog } from "./LlmReasonDialog";
import { LlmTagDialog } from "./LlmTagDialog";
import { VideoPane } from "./VideoPane";

/** Tab 1 — individual session coding against the video. */
export function SessionCodingTab({ ctl }: { ctl: AnalysisController }) {
  const [playhead, setPlayhead] = useState(0);
  const [liveId, setLiveId] = useState("");
  const [videoReady, setVideoReady] = useState(false);
  // Video coding is paused by default: code the chat/action log on wall-clock
  // alone. Flip this on to re-enable the video pane + clock anchoring.
  const [videoMode, setVideoMode] = useState(false);
  const [showOriginDialog, setShowOriginDialog] = useState(false);
  const [showReasonDialog, setShowReasonDialog] = useState(false);
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

  function addChange(row: TimelineRow, change: Omit<ChangeTag, "id">) {
    if (!row.row_ref) return;
    void ctl.addAnnotation({ ...changeToBody(change), row_ref: row.row_ref });
  }

  /** Dismiss a suggested change: persisted as a `dismiss` annotation so the
   * server filters it out of suggested_changes on every future load. */
  function dismissSuggestion(row: TimelineRow, change: Omit<ChangeTag, "id">) {
    if (!row.row_ref) return;
    void ctl.addAnnotation({
      anno_type: "dismiss",
      row_ref: row.row_ref,
      text: JSON.stringify({
        origin: change.origin, type: change.type, term: change.term, effect: change.effect,
      }),
    });
  }

  /** Reject a suggested reason: persisted as a `dismiss-reason` annotation so
   * the server filters it out of reason_suggestions on every future load. */
  function dismissReason(row: TimelineRow, reason: string) {
    if (!row.row_ref) return;
    void ctl.addAnnotation({
      anno_type: "dismiss-reason",
      row_ref: row.row_ref,
      text: JSON.stringify({ reason }),
    });
  }

  /** Persist a row's improvement-reason set as ONE `reason` annotation
   * (empty set deletes it). */
  function saveReason(row: TimelineRow, reasons: string[], note: string | null) {
    if (!row.row_ref) return;
    if (!reasons.length && !note) {
      if (row.reasons?.id != null) void ctl.removeAnnotation(row.reasons.id);
      return;
    }
    const body = { text: JSON.stringify({ reasons, note }) };
    if (row.reasons?.id != null) void ctl.editAnnotation(row.reasons.id, body);
    else void ctl.addAnnotation({ anno_type: "reason", row_ref: row.row_ref, ...body });
  }

  function editChange(annoId: number, change: Omit<ChangeTag, "id">) {
    void ctl.editAnnotation(annoId, changeToBody(change));
  }

  function acceptAllSuggestions() {
    const rows = detail?.timeline ?? [];
    const bodies: Partial<Annotation>[] = [];
    for (const r of rows) {
      if (!r.row_ref) continue;
      const existing = new Set(r.changes.map(changeKey));
      for (const s of r.suggested_changes) {
        if (existing.has(changeKey(s))) continue;
        existing.add(changeKey(s));
        bodies.push({ ...changeToBody(s), row_ref: r.row_ref });
      }
    }
    if (bodies.length) void ctl.addManyAnnotations(bodies);
  }

  const tagCount = (detail?.annotations ?? []).filter((a) => a.anno_type === "code").length;

  function resetTags() {
    if (tagCount === 0) {
      alert("No coded tags to reset for this session.");
      return;
    }
    if (confirm(`Remove all ${tagCount} coded tag(s) for this session? This can't be undone.`)) {
      void ctl.resetTags();
    }
  }

  const suggestionCount = (detail?.timeline ?? []).reduce((n, r) => {
    if (!r.row_ref) return n;
    const existing = new Set(r.changes.map(changeKey));
    return n + r.suggested_changes.filter((s) => !existing.has(changeKey(s))).length;
  }, 0);

  // --- Reason layer (independent of the change tags) ---
  const reasonCount = (detail?.annotations ?? []).filter((a) => a.anno_type === "reason").length;

  /** Un-labeled rows with reason suggestions (LLM verdicts where checked, else
   * mechanical candidates; dismissed ones already filtered server-side). */
  const suggestedReasonRows = (detail?.timeline ?? []).filter(
    (r) => r.row_ref && !r.reasons && (r.reason_suggestions ?? []).length > 0,
  );
  const reasonSuggestionCount = suggestedReasonRows.reduce(
    (n, r) => n + (r.reason_suggestions ?? []).length,
    0,
  );

  function acceptAllReasons() {
    const bodies: Partial<Annotation>[] = [];
    for (const r of suggestedReasonRows) {
      const reasons = (r.reason_suggestions ?? []).map((s) => s.reason);
      if (reasons.length) {
        bodies.push({
          anno_type: "reason",
          row_ref: r.row_ref!,
          text: JSON.stringify({ reasons, note: null }),
        });
      }
    }
    if (bodies.length) void ctl.addManyAnnotations(bodies);
  }

  function resetReasons() {
    if (reasonCount === 0) {
      alert("No reason labels to reset for this session.");
      return;
    }
    if (confirm(`Remove all ${reasonCount} reason label(s) for this session? Change tags are kept.`)) {
      void ctl.resetReasons();
    }
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
              title={s.locked ? "Coding locked — click to unlock editing" : "Lock coding (mark done)"}
              onClick={(e) => {
                e.stopPropagation();
                void ctl.setLocked(s.id, !s.locked);
              }}
              style={{
                fontSize: "0.8rem",
                cursor: "pointer",
                background: "none",
                border: "none",
                padding: 0,
                lineHeight: 1,
                opacity: s.locked ? 1 : 0.4,
              }}
            >
              {s.locked ? "🔒" : "🔓"}
            </button>
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
            {videoMode ? (
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
            ) : null}

            <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column", gap: "0.4rem" }}>
              {summary.locked ? (
                <div
                  className="banner-info"
                  style={{ display: "flex", alignItems: "center", gap: "0.6rem", fontSize: "0.82rem" }}
                >
                  <span>🔒 Coding locked — editing is disabled for this session.</span>
                  <button
                    type="button"
                    style={{ fontSize: "0.78rem", padding: "0.2rem 0.55rem", cursor: "pointer", marginLeft: "auto" }}
                    onClick={() => ctl.selectedId && void ctl.setLocked(ctl.selectedId, false)}
                  >
                    Unlock
                  </button>
                </div>
              ) : null}
              <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: "0.5rem", fontSize: "0.8rem" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "0.3rem", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={videoMode}
                    onChange={(e) => setVideoMode(e.target.checked)}
                  />
                  Video coding
                </label>
                <button
                  type="button"
                  style={{ fontSize: "0.8rem", padding: "0.25rem 0.6rem" }}
                  onClick={() => void ctl.exportCsv()}
                >
                  Export CSV
                </button>
                <button
                  type="button"
                  style={{ fontSize: "0.8rem", padding: "0.25rem 0.6rem" }}
                  onClick={() => void ctl.backupCoding()}
                  title="Download a portable JSON backup of all your coding"
                >
                  Back up labels
                </button>
                <label
                  style={{ fontSize: "0.8rem", padding: "0.25rem 0.6rem", border: "1px solid #999", borderRadius: 4, cursor: "pointer" }}
                  title="Restore coding from a backup JSON (non-destructive)"
                >
                  Restore…
                  <input
                    type="file"
                    accept=".json,application/json"
                    style={{ display: "none" }}
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      e.currentTarget.value = "";
                      if (f && confirm(`Restore coding from "${f.name}"? Existing tags are kept; duplicates are skipped.`)) {
                        void ctl.restoreCoding(f).then((res) => {
                          if (res) alert(`Restored ${res.annotations} tag(s) across ${res.sessions} session(s).`);
                        });
                      }
                    }}
                  />
                </label>
                {/* ---- change-TAG tools (purple group) ---- */}
                <div
                  style={{
                    display: "flex", alignItems: "center", gap: "0.3rem", marginLeft: "auto",
                    border: "1px solid #8b5cf6", borderRadius: 6, padding: "0.15rem 0.4rem",
                    background: "rgba(139,92,246,0.05)",
                  }}
                >
                  <span style={{ fontSize: "0.7rem", fontWeight: 700, color: "#8b5cf6" }}>tags</span>
                  <button
                    type="button"
                    style={{
                      fontSize: "0.78rem", padding: "0.2rem 0.5rem", fontWeight: 600,
                      border: "1px solid #8b5cf6", borderRadius: 4,
                      background: "rgba(139,92,246,0.1)", color: "#8b5cf6", cursor: "pointer",
                    }}
                    onClick={() => setShowOriginDialog(true)}
                    title="Read every exchange with an LLM to suggest change tags (origin · type · term · effect, with rationale). Cached; lands as suggestions to accept."
                  >
                    ✨ LLM tagging
                  </button>
                  <button
                    type="button"
                    style={{ fontSize: "0.78rem", padding: "0.2rem 0.5rem" }}
                    disabled={suggestionCount === 0}
                    onClick={acceptAllSuggestions}
                    title="Materialize every change-tag suggestion as an editable tag"
                  >
                    Accept all ({suggestionCount})
                  </button>
                  <button
                    type="button"
                    style={{
                      fontSize: "0.78rem", padding: "0.2rem 0.5rem",
                      border: "1px solid #dc2626", borderRadius: 4,
                      background: "rgba(220,38,38,0.08)", color: "#dc2626",
                      cursor: tagCount ? "pointer" : "not-allowed",
                    }}
                    disabled={tagCount === 0}
                    onClick={resetTags}
                    title="Delete every coded change tag for this session (reasons and notes are kept)"
                  >
                    Reset ({tagCount})
                  </button>
                </div>
                {/* ---- improvement-REASON tools (teal group) ---- */}
                <div
                  style={{
                    display: "flex", alignItems: "center", gap: "0.3rem",
                    border: "1px solid #0d9488", borderRadius: 6, padding: "0.15rem 0.4rem",
                    background: "rgba(13,148,136,0.05)",
                  }}
                >
                  <span style={{ fontSize: "0.7rem", fontWeight: 700, color: "#0d9488" }}>reasons</span>
                  <button
                    type="button"
                    style={{
                      fontSize: "0.78rem", padding: "0.2rem 0.5rem", fontWeight: 600,
                      border: "1px solid #0d9488", borderRadius: 4,
                      background: "rgba(13,148,136,0.1)", color: "#0d9488", cursor: "pointer",
                    }}
                    onClick={() => setShowReasonDialog(true)}
                    title="Double-check the mechanical improvement-reason candidates on each run with an LLM (separate cache; never touches change tags)."
                  >
                    ✨ LLM reasons
                  </button>
                  <button
                    type="button"
                    style={{ fontSize: "0.78rem", padding: "0.2rem 0.5rem" }}
                    disabled={reasonSuggestionCount === 0}
                    onClick={acceptAllReasons}
                    title="Accept every suggested reason on runs not yet labeled (LLM verdicts where the LLM has checked; mechanical candidates elsewhere — dismissed ones excluded)"
                  >
                    Accept all ({reasonSuggestionCount})
                  </button>
                  <button
                    type="button"
                    style={{
                      fontSize: "0.78rem", padding: "0.2rem 0.5rem",
                      border: "1px solid #dc2626", borderRadius: 4,
                      background: "rgba(220,38,38,0.08)", color: "#dc2626",
                      cursor: reasonCount ? "pointer" : "not-allowed",
                    }}
                    disabled={reasonCount === 0}
                    onClick={resetReasons}
                    title="Delete every improvement-reason label for this session (change tags and notes are kept)"
                  >
                    Reset ({reasonCount})
                  </button>
                </div>
              </div>
              <EventList
                rows={detail?.timeline ?? []}
                goalTermKeys={detail?.goal_term_keys ?? []}
                playhead={playhead}
                offsetSet={summary.clock_offset_sec != null}
                videoMode={videoMode}
                onSeek={seek}
                onAddChange={addChange}
                onDismissSuggestion={dismissSuggestion}
                onSaveReason={saveReason}
                onDismissReason={dismissReason}
                onEditChange={editChange}
                onSaveNote={saveNote}
                onDeleteAnnotation={(id) => void ctl.removeAnnotation(id)}
              />
            </div>
          </>
        )}
      </main>

      <LlmTagDialog
        open={showOriginDialog}
        onClose={() => setShowOriginDialog(false)}
        currentLoadedId={ctl.selectedId}
        onRun={(body) => ctl.runLlmTags(body)}
      />

      <LlmReasonDialog
        open={showReasonDialog}
        onClose={() => setShowReasonDialog(false)}
        currentLoadedId={ctl.selectedId}
        onRun={(body) => ctl.runLlmReasons(body)}
      />

      <DialogShell
        open={ctl.unlockPromptOpen}
        title="Session coding is locked"
        titleId="unlock-coding-dialog"
        maxWidth="420px"
      >
        <p className="muted" style={{ fontSize: "0.85rem", marginTop: 0 }}>
          This session is marked <strong>done</strong>, so edits are disabled to protect the
          finished coding. Unlock it to make changes — you can re-lock it from the session list
          (🔒) at any time.
        </p>
        <div className="dialog-actions">
          <button type="button" onClick={ctl.closeUnlockPrompt}>
            Keep locked
          </button>
          <button type="button" onClick={() => void ctl.unlockSelected()}>
            Unlock &amp; edit
          </button>
        </div>
      </DialogShell>
    </div>
  );
}
