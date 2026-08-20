import { useState } from "react";

import { DialogShell } from "@shared/components/DialogShell";
import { useGeminiConfig } from "@shared/geminiModelSuggestions";

interface LlmTagDialogProps {
  open: boolean;
  onClose: () => void;
  currentLoadedId: string | null;
  onRun: (body: {
    api_key: string;
    model: string;
    loaded_id?: string;
    purge_tags?: boolean;
  }) => Promise<{
    sessions: number;
    tagged_exchanges: number;
    ran_llm: boolean;
    skipped_locked: number;
    failed: number;
    purged_tags: number;
  } | null>;
}

const MODEL_KEY = "mopt_llm_tag_model";
const DATALIST_ID = "mopt-llm-tag-model-suggestions";

/** Runs (and caches) the ✨ LLM change-tagging pass — reads every exchange plus
 * the verified structural evidence and proposes composite change tags (origin ·
 * type · goal term · effect, with a one-line rationale). Suggestions render as
 * dashed cards for the researcher to accept; nothing is auto-materialized. */
export function LlmTagDialog({ open, onClose, currentLoadedId, onRun }: LlmTagDialogProps) {
  const { suggestions } = useGeminiConfig();
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(
    () => sessionStorage.getItem(MODEL_KEY) ?? suggestions[0] ?? "gemini-2.5-flash",
  );
  const [allSessions, setAllSessions] = useState(true);
  const [purgeTags, setPurgeTags] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setStatus(null);
    setError(null);
    sessionStorage.setItem(MODEL_KEY, model);
    const body: { api_key: string; model: string; loaded_id?: string; purge_tags?: boolean } = {
      api_key: apiKey,
      model,
      purge_tags: purgeTags,
    };
    if (!allSessions && currentLoadedId) body.loaded_id = currentLoadedId;
    const res = await onRun(body);
    setBusy(false);
    if (!res) {
      setError("Tagging request failed — check the researcher token and server.");
      return;
    }
    if (!res.ran_llm) {
      setStatus("No API key — nothing was run; the existing tag cache AND accepted tags were kept.");
    } else {
      const extras = [
        res.purged_tags ? `purged ${res.purged_tags} previously accepted tag(s) (auto-backed-up)` : null,
        res.failed ? `${res.failed} session(s) FAILED (old cache and tags kept)` : null,
        res.skipped_locked ? `${res.skipped_locked} locked session(s) skipped` : null,
      ]
        .filter(Boolean)
        .join("; ");
      setStatus(
        `Tagged ${res.tagged_exchanges} exchange(s) across ${res.sessions} session(s).` +
          (extras ? ` ${extras}.` : "") +
          " Suggestions are cached — accept them per row or via Accept all.",
      );
    }
  }

  return (
    <DialogShell open={open} title="LLM change tagging" titleId="llm-tag-dialog" maxWidth="460px">
      <p className="muted" style={{ fontSize: "0.82rem", marginTop: 0 }}>
        Reads every <strong>exchange</strong> (conversation + verified config-change facts) and proposes the
        composite change tags: each goal term&apos;s true <strong>origin</strong>, when it was{" "}
        <strong>first applied</strong>, and terms that were mentioned but never implemented (acknowledged /
        dropped / declined). Search-strategy and parameter tags stay deterministic and merge in automatically.
        Results are <strong>cached</strong> per session and land as suggestions for you to accept — nothing is
        written to your tags without a click.
      </p>

      <label className="muted" style={{ display: "block", marginTop: "0.6rem" }}>
        Gemini model
        <input
          type="text"
          list={DATALIST_ID}
          style={{ width: "100%", marginTop: "0.2rem" }}
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder="gemini-2.5-flash"
        />
        <datalist id={DATALIST_ID}>
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      </label>

      <label className="muted" style={{ display: "block", marginTop: "0.6rem" }}>
        Gemini API key
        <input
          type="password"
          style={{ width: "100%", marginTop: "0.2rem" }}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="AIza… (not stored; sent once for this run)"
        />
      </label>

      <label
        style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginTop: "0.7rem", fontSize: "0.85rem" }}
      >
        <input type="checkbox" checked={allSessions} onChange={(e) => setAllSessions(e.target.checked)} />
        All loaded sessions {allSessions ? "" : currentLoadedId ? "(off — current session only)" : "(no session selected)"}
      </label>

      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.4rem",
          marginTop: "0.45rem",
          fontSize: "0.85rem",
          color: purgeTags ? "#b91c1c" : undefined,
        }}
        title="Deletes the previously ACCEPTED change tags of each scoped session so you can re-accept from the fresh suggestions. Runs only after that session's LLM pass succeeded, with an automatic backup first. Notes, markers and pauses are untouched; locked sessions are skipped."
      >
        <input type="checkbox" checked={purgeTags} onChange={(e) => setPurgeTags(e.target.checked)} />
        Purge existing tags &amp; re-label (auto-backup first; only on successful runs)
      </label>

      {status ? (
        <div className="banner-info" style={{ marginTop: "0.7rem" }}>
          {status}
        </div>
      ) : null}
      {error ? (
        <div className="banner-warn" style={{ marginTop: "0.7rem" }}>
          {error}
        </div>
      ) : null}

      <div className="dialog-actions">
        <button type="button" onClick={onClose}>
          Close
        </button>
        <button type="button" disabled={busy || (!allSessions && !currentLoadedId)} onClick={() => void run()}>
          {busy ? "Running…" : "Run tagging"}
        </button>
      </div>
    </DialogShell>
  );
}
