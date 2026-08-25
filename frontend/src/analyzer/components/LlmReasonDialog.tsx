import { useState } from "react";

import { DialogShell } from "@shared/components/DialogShell";
import { useGeminiConfig } from "@shared/geminiModelSuggestions";

interface LlmReasonDialogProps {
  open: boolean;
  onClose: () => void;
  currentLoadedId: string | null;
  onRun: (body: {
    api_key: string;
    model: string;
    loaded_id?: string;
  }) => Promise<{
    sessions: number;
    checked_runs: number;
    ran_llm: boolean;
    skipped_locked: number;
    failed: number;
  } | null>;
}

const MODEL_KEY = "mopt_llm_reason_model";
const DATALIST_ID = "mopt-llm-reason-model-suggestions";

/** Runs (and caches) the ✨ LLM REASON-verification pass — a fully separate
 * mechanism from LLM change tagging (own cache, own endpoint): for each run it
 * double-checks the mechanical "why did the outcome move" candidates against
 * the conversation, and its verdicts appear as extra reason suggestions. */
export function LlmReasonDialog({ open, onClose, currentLoadedId, onRun }: LlmReasonDialogProps) {
  const { suggestions } = useGeminiConfig();
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(
    () => sessionStorage.getItem(MODEL_KEY) ?? suggestions[0] ?? "gemini-2.5-flash",
  );
  const [allSessions, setAllSessions] = useState(true);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setStatus(null);
    setError(null);
    sessionStorage.setItem(MODEL_KEY, model);
    const body: { api_key: string; model: string; loaded_id?: string } = { api_key: apiKey, model };
    if (!allSessions && currentLoadedId) body.loaded_id = currentLoadedId;
    const res = await onRun(body);
    setBusy(false);
    if (!res) {
      setError("Reason check failed — check the researcher token and server.");
      return;
    }
    if (!res.ran_llm) {
      setStatus("No API key — nothing was run; the existing reason cache was kept.");
    } else {
      const extras = [
        res.failed ? `${res.failed} session(s) FAILED (old cache kept)` : null,
        res.skipped_locked ? `${res.skipped_locked} locked session(s) skipped` : null,
      ]
        .filter(Boolean)
        .join("; ");
      setStatus(
        `Checked ${res.checked_runs} run(s) across ${res.sessions} session(s).` +
          (extras ? ` ${extras}.` : "") +
          " Verdicts appear as ✨ suggestions in the reason column.",
      );
    }
  }

  return (
    <DialogShell open={open} title="LLM reason check" titleId="llm-reason-dialog" maxWidth="460px">
      <p className="muted" style={{ fontSize: "0.82rem", marginTop: 0 }}>
        For each <strong>run</strong>, double-checks the mechanical &quot;why did the score change&quot;
        candidates against the conversation and the verified evidence (cost delta, which goal terms moved,
        config changes since the previous run). Completely separate from LLM change tagging — it never
        touches your tags or their cache. Verdicts are <strong>cached</strong> and land as extra
        suggestions in the reason column for you to accept.
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
          {busy ? "Running…" : "Run reason check"}
        </button>
      </div>
    </DialogShell>
  );
}
