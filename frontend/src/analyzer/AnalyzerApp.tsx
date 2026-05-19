import { useEffect, useMemo, useState } from "react";

import { SessionAnalyzer } from "./components/SessionAnalyzer";
import { SessionListPanel } from "./components/SessionListPanel";
import { loadFromDb, loadFromJson } from "./lib/sessionStore";
import type { SessionStore } from "./lib/types";

function pickLoader(file: File): (f: File) => Promise<SessionStore> {
  const lower = file.name.toLowerCase();
  if (lower.endsWith(".db") || lower.endsWith(".sqlite") || lower.endsWith(".sqlite3")) {
    return loadFromDb;
  }
  return loadFromJson;
}

export function AnalyzerApp() {
  const [store, setStore] = useState<SessionStore | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [analyzedIds, setAnalyzedIds] = useState<Set<string>>(() => new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedArchive = useMemo(() => {
    if (!store || !selectedId) return null;
    return store.sessions.find((s) => s.session.id === selectedId) ?? null;
  }, [store, selectedId]);

  const showAnalyzer = selectedArchive != null && selectedId != null && analyzedIds.has(selectedId);

  useEffect(() => {
    if (!selectedArchive) {
      document.title = "Analyzer";
      return;
    }
    const pn = (selectedArchive.session.participant_number ?? "").toString().trim();
    document.title = pn ? `Analyzer #${pn}` : "Analyzer";
  }, [selectedArchive]);

  async function handleFile(file: File) {
    setLoading(true);
    setError(null);
    try {
      const loader = pickLoader(file);
      const next = await loader(file);
      setStore(next);
      setAnalyzedIds(new Set());
      // Auto-select the only session in a single-session JSON; otherwise
      // require an explicit click so big .db imports don't render anything
      // until the researcher asks for it.
      if (next.sessions.length === 1) {
        setSelectedId(next.sessions[0].session.id);
      } else {
        setSelectedId(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load file.");
      setStore(null);
      setSelectedId(null);
      setAnalyzedIds(new Set());
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-shell" style={{ padding: "1rem" }}>
      <h1 style={{ fontSize: "1.15rem", marginBottom: "0.5rem" }}>Session archive viewer</h1>
      <label className="muted" style={{ display: "block", marginBottom: "0.5rem" }}>
        Source file
        <input
          type="file"
          accept=".json,.db,.sqlite,.sqlite3,application/json,application/octet-stream"
          style={{ display: "block", marginTop: "0.25rem" }}
          disabled={loading}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            void handleFile(f);
          }}
        />
      </label>
      {loading ? <p className="muted">Loading…</p> : null}
      {error ? <div className="banner-warn">{error}</div> : null}

      <div className="researcher-layout">
        <SessionListPanel
          sessions={store?.sessions ?? []}
          selectedId={selectedId}
          analyzedIds={analyzedIds}
          sourceLabel={store?.sourceName ?? null}
          onSelect={setSelectedId}
          onAnalyze={(sid) => {
            setSelectedId(sid);
            setAnalyzedIds((prev) => {
              const next = new Set(prev);
              next.add(sid);
              return next;
            });
          }}
        />
        <section style={{ flex: 1, minWidth: 0, padding: "0 1rem" }}>
          {showAnalyzer && selectedArchive ? (
            <SessionAnalyzer archive={selectedArchive} />
          ) : selectedArchive ? (
            <p className="muted" style={{ fontSize: "0.88rem" }}>
              Selected session #{selectedArchive.session.participant_number ?? "n/a"}. Click <strong>Analyze</strong> in the
              list to render the timeline.
            </p>
          ) : store && store.sessions.length === 0 ? (
            <p className="muted" style={{ fontSize: "0.88rem" }}>
              The loaded file has no sessions.
            </p>
          ) : store ? (
            <p className="muted" style={{ fontSize: "0.88rem" }}>
              Pick a session from the list, then click <strong>Analyze</strong>.
            </p>
          ) : (
            <p className="muted" style={{ fontSize: "0.88rem" }}>
              No file loaded yet.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
