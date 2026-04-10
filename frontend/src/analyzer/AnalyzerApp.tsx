import { useMemo, useState } from "react";

function safeJsonPretty(raw: string): { ok: true; text: string } | { ok: false; text: string } {
  try {
    const v = JSON.parse(raw);
    return { ok: true, text: JSON.stringify(v, null, 2) };
  } catch (e) {
    return { ok: false, text: e instanceof Error ? e.message : "Invalid JSON" };
  }
}

type TimelineRow = {
  kind: string;
  at: string;
  label: string;
  payload_summary: string;
  ref?: Record<string, unknown>;
};

function displayRunNumber(run: Record<string, unknown>, index: number): number {
  const n = run.run_number;
  if (typeof n === "number" && Number.isFinite(n)) return n;
  const idx = run.session_run_index;
  if (typeof idx === "number" && Number.isFinite(idx)) return idx + 1;
  return index + 1;
}

function buildTimelineFromArchive(o: Record<string, unknown>): TimelineRow[] {
  const embedded = o.timeline;
  if (Array.isArray(embedded)) {
    return embedded.filter(
      (row): row is TimelineRow =>
        row !== null &&
        typeof row === "object" &&
        typeof (row as TimelineRow).kind === "string" &&
        typeof (row as TimelineRow).at === "string",
    );
  }

  const rows: { sort: string; row: TimelineRow }[] = [];
  const messages = o.messages;
  if (Array.isArray(messages)) {
    messages.forEach((m, i) => {
      if (!m || typeof m !== "object") return;
      const msg = m as Record<string, unknown>;
      const at = typeof msg.created_at === "string" ? msg.created_at : "";
      const id = msg.id;
      const content = typeof msg.content === "string" ? msg.content : "";
      const summary = content.replace(/\s+/g, " ").trim().slice(0, 200);
      rows.push({
        sort: `${at}\x00message\x00${id ?? i}`,
        row: {
          kind: "message",
          at,
          label: `${String(msg.role ?? "?")}/${String(msg.kind ?? "?")}`,
          payload_summary: summary.length < content.length ? `${summary}…` : summary,
          ref: { message_id: id },
        },
      });
    });
  }
  const snapshots = o.snapshots;
  if (Array.isArray(snapshots)) {
    snapshots.forEach((s, i) => {
      if (!s || typeof s !== "object") return;
      const snap = s as Record<string, unknown>;
      const at = typeof snap.created_at === "string" ? snap.created_at : "";
      const id = snap.id;
      const hasBrief = snap.problem_brief != null;
      const hasPanel = snap.panel_config != null;
      rows.push({
        sort: `${at}\x00snapshot\x00${id ?? i}`,
        row: {
          kind: "snapshot",
          at,
          label: String(snap.event_type ?? "snapshot"),
          payload_summary: `brief=${hasBrief ? "yes" : "no"} panel=${hasPanel ? "yes" : "no"}`,
          ref: { snapshot_id: id },
        },
      });
    });
  }
  const runs = o.runs;
  if (Array.isArray(runs)) {
    runs.forEach((r, i) => {
      if (!r || typeof r !== "object") return;
      const run = r as Record<string, unknown>;
      const at = typeof run.created_at === "string" ? run.created_at : "";
      const id = run.id;
      const rn = displayRunNumber(run, i);
      rows.push({
        sort: `${at}\x00run\x00${id ?? i}`,
        row: {
          kind: "run",
          at,
          label: String(run.run_type ?? "run"),
          payload_summary: `ok=${String(run.ok)} cost=${String(run.cost ?? "—")} (#${rn})`,
          ref: { run_id: id, run_number: rn },
        },
      });
    });
  }
  rows.sort((a, b) => (a.sort < b.sort ? -1 : a.sort > b.sort ? 1 : 0));
  return rows.map((x) => x.row);
}

export function AnalyzerApp() {
  const [fileName, setFileName] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"raw" | "timeline">("timeline");
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);

  const parsed = useMemo(() => safeJsonPretty(text), [text]);

  const archiveObj = useMemo(() => {
    if (!parsed.ok) return null;
    try {
      return JSON.parse(text) as Record<string, unknown>;
    } catch {
      return null;
    }
  }, [parsed.ok, text]);

  const header = useMemo(() => {
    if (!archiveObj) return null;
    try {
      const ver = archiveObj.export_schema_version;
      const sid = (archiveObj.session as Record<string, unknown> | undefined)?.id;
      const messages = archiveObj.messages;
      const runs = archiveObj.runs;
      const snapshots = archiveObj.snapshots;
      const mc = Array.isArray(messages) ? messages.length : "—";
      const rc = Array.isArray(runs) ? runs.length : "—";
      const sc = Array.isArray(snapshots) ? snapshots.length : "—";
      const tc = buildTimelineFromArchive(archiveObj).length;
      return {
        ver: typeof ver === "number" ? ver : String(ver ?? "—"),
        sid: typeof sid === "string" ? sid : "—",
        mc,
        rc,
        sc,
        tc,
      };
    } catch {
      return null;
    }
  }, [archiveObj]);

  const timelineRows = useMemo(() => {
    if (!archiveObj) return [];
    return buildTimelineFromArchive(archiveObj);
  }, [archiveObj]);

  const detailJson = useMemo(() => {
    if (selectedIdx === null || !archiveObj) return null;
    const row = timelineRows[selectedIdx];
    if (!row) return null;
    if (row.kind === "message") {
      const id = row.ref?.message_id;
      const messages = archiveObj.messages;
      if (!Array.isArray(messages)) return null;
      const hit = messages.find((m) => m && typeof m === "object" && (m as Record<string, unknown>).id === id);
      return hit ? JSON.stringify(hit, null, 2) : null;
    }
    if (row.kind === "snapshot") {
      const id = row.ref?.snapshot_id;
      const snapshots = archiveObj.snapshots;
      if (!Array.isArray(snapshots)) return null;
      const hit = snapshots.find((s) => s && typeof s === "object" && (s as Record<string, unknown>).id === id);
      return hit ? JSON.stringify(hit, null, 2) : null;
    }
    if (row.kind === "run") {
      const id = row.ref?.run_id;
      const runs = archiveObj.runs;
      if (!Array.isArray(runs)) return null;
      const hit = runs.find((r) => r && typeof r === "object" && (r as Record<string, unknown>).id === id);
      return hit ? JSON.stringify(hit, null, 2) : null;
    }
    return null;
  }, [selectedIdx, archiveObj, timelineRows]);

  return (
    <div className="app-shell" style={{ maxWidth: "72rem", margin: "0 auto", padding: "1rem" }}>
      <h1 style={{ fontSize: "1.15rem", marginBottom: "0.5rem" }}>Session archive viewer</h1>
      <p className="muted" style={{ fontSize: "0.88rem", marginBottom: "0.75rem" }}>
        Upload a versioned session archive JSON (researcher export). Everything stays in your browser.
      </p>
      <label className="muted" style={{ display: "block", marginBottom: "0.35rem" }}>
        Archive file
        <input
          type="file"
          accept="application/json,.json"
          style={{ display: "block", marginTop: "0.25rem" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            setFileName(f.name);
            setError(null);
            setSelectedIdx(null);
            const reader = new FileReader();
            reader.onload = () => {
              const t = typeof reader.result === "string" ? reader.result : "";
              setText(t);
            };
            reader.onerror = () => setError("Could not read file.");
            reader.readAsText(f, "UTF-8");
          }}
        />
      </label>
      {fileName ? (
        <p className="muted" style={{ fontSize: "0.8rem" }}>
          Loaded: <span className="mono">{fileName}</span>
        </p>
      ) : null}
      {error && <div className="banner-warn">{error}</div>}
      {header ? (
        <div
          className="mono muted"
          style={{ fontSize: "0.78rem", marginBottom: "0.5rem", lineHeight: 1.5 }}
        >
          export_schema_version={header.ver} · session_id={header.sid} · messages={header.mc} · runs={header.rc} ·
          snapshots={header.sc} · timeline_rows={header.tc}
        </div>
      ) : null}
      {!parsed.ok && text.trim() ? <div className="banner-warn">{parsed.text}</div> : null}

      {parsed.ok && archiveObj ? (
        <div className="tabs" style={{ marginBottom: "0.5rem" }}>
          <button type="button" className={`tab ${tab === "timeline" ? "active" : ""}`} onClick={() => setTab("timeline")}>
            Timeline
          </button>
          <button type="button" className={`tab ${tab === "raw" ? "active" : ""}`} onClick={() => setTab("raw")}>
            Raw JSON
          </button>
        </div>
      ) : null}

      {parsed.ok && tab === "raw" ? (
        <pre
          className="mono"
          style={{
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            maxHeight: "70vh",
            overflow: "auto",
            fontSize: "0.75rem",
            padding: "0.5rem",
            border: "1px solid var(--border)",
            borderRadius: 2,
            background: "var(--bg)",
          }}
        >
          {text.trim() ? parsed.text : "Choose a JSON file to preview."}
        </pre>
      ) : null}

      {parsed.ok && tab === "timeline" && archiveObj ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          <div
            style={{
              maxHeight: "42vh",
              overflow: "auto",
              border: "1px solid var(--border)",
              borderRadius: 2,
              background: "var(--bg)",
            }}
          >
            <table
              className="mono"
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: "0.72rem",
              }}
            >
              <thead
                style={{
                  position: "sticky",
                  top: 0,
                  background: "var(--bg)",
                  borderBottom: "1px solid var(--border)",
                  zIndex: 1,
                }}
              >
                <tr>
                  <th style={{ textAlign: "left", padding: "0.35rem 0.5rem" }}>Time</th>
                  <th style={{ textAlign: "left", padding: "0.35rem 0.5rem" }}>Type</th>
                  <th style={{ textAlign: "left", padding: "0.35rem 0.5rem" }}>Label</th>
                  <th style={{ textAlign: "left", padding: "0.35rem 0.5rem" }}>Summary</th>
                </tr>
              </thead>
              <tbody>
                {timelineRows.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="muted" style={{ padding: "0.5rem" }}>
                      No timeline rows (empty session or unrecognized format).
                    </td>
                  </tr>
                ) : (
                  timelineRows.map((row, idx) => (
                    <tr
                      key={`${row.kind}-${row.at}-${idx}`}
                      onClick={() => setSelectedIdx(selectedIdx === idx ? null : idx)}
                      style={{
                        cursor: "pointer",
                        background: selectedIdx === idx ? "rgba(127,127,127,0.12)" : undefined,
                        borderBottom: "1px solid var(--border)",
                      }}
                    >
                      <td style={{ padding: "0.3rem 0.5rem", verticalAlign: "top", whiteSpace: "nowrap" }}>{row.at}</td>
                      <td style={{ padding: "0.3rem 0.5rem", verticalAlign: "top" }}>{row.kind}</td>
                      <td style={{ padding: "0.3rem 0.5rem", verticalAlign: "top" }}>{row.label}</td>
                      <td style={{ padding: "0.3rem 0.5rem", verticalAlign: "top", wordBreak: "break-word" }}>
                        {row.payload_summary}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          {detailJson ? (
            <div>
              <div className="muted" style={{ fontSize: "0.78rem", marginBottom: "0.25rem" }}>
                Selected row (full message / snapshot / run record)
              </div>
              <pre
                className="mono"
                style={{
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  maxHeight: "28vh",
                  overflow: "auto",
                  fontSize: "0.72rem",
                  padding: "0.5rem",
                  border: "1px solid var(--border)",
                  borderRadius: 2,
                  background: "var(--bg)",
                  margin: 0,
                }}
              >
                {detailJson}
              </pre>
            </div>
          ) : null}
        </div>
      ) : null}

      {!parsed.ok && !text.trim() ? (
        <p className="muted" style={{ fontSize: "0.85rem" }}>
          Choose a JSON file to preview.
        </p>
      ) : null}
    </div>
  );
}
