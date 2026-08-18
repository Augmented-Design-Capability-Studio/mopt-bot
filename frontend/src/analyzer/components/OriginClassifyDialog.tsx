import { useState } from "react";

import { DialogShell } from "@shared/components/DialogShell";
import { useGeminiConfig } from "@shared/geminiModelSuggestions";

interface OriginClassifyDialogProps {
  open: boolean;
  onClose: () => void;
  currentLoadedId: string | null;
  onRun: (body: {
    api_key: string;
    model: string;
    loaded_id?: string;
  }) => Promise<{ sessions: number; classified_messages: number; ran_llm: boolean } | null>;
}

const MODEL_KEY = "mopt_origin_llm_model";
const DATALIST_ID = "mopt-origin-model-suggestions";

/** Runs (and caches) the LLM origin pass — reads each user message to decide
 * which goal terms the user actually raised, overriding the unreliable brief
 * provenance. Styled after the researcher/participant assistant-settings dialog. */
export function OriginClassifyDialog({ open, onClose, currentLoadedId, onRun }: OriginClassifyDialogProps) {
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
      setError("Classification request failed — check the researcher token and server.");
      return;
    }
    if (!res.ran_llm) {
      setStatus(
        `Ran in no-op mode (no API key): cleared origin cache for ${res.sessions} session(s). ` +
          `Enter a key and re-run to actually classify.`,
      );
    } else {
      setStatus(
        `Classified ${res.classified_messages} user message(s) across ${res.sessions} session(s). ` +
          `Origins updated — refresh not needed.`,
      );
    }
  }

  return (
    <DialogShell open={open} title="Auto-detect origin (LLM)" titleId="origin-llm-dialog" maxWidth="460px">
      <p className="muted" style={{ fontSize: "0.82rem", marginTop: 0 }}>
        Reads each <strong>user</strong> message and decides which goal terms the user actually raised, so
        origin isn&apos;t misattributed to the agent. Results are <strong>cached</strong> per session and reused
        on every load — this only re-hits the API when you run it here. Estimated cost for all 28 sessions:
        a few cents on a Flash model.
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
          {busy ? "Running…" : "Run classification"}
        </button>
      </div>
    </DialogShell>
  );
}
