import { useGeminiConfig } from "@shared/geminiModelSuggestions";
import { DialogShell } from "@shared/components/DialogShell";

const CUSTOM_VALUE = "__custom__";

type ResearcherModelKeyDialogProps = {
  open: boolean;
  configured: boolean;
  geminiKey: string;
  geminiModel: string;
  busy: boolean;
  pushKeySuccess: string | null;
  onGeminiKeyChange: (value: string) => void;
  onGeminiModelChange: (value: string) => void;
  onClose: () => void;
  onPush: () => void | Promise<void>;
};

export function ResearcherModelKeyDialog({
  open,
  configured,
  geminiKey,
  geminiModel,
  busy,
  pushKeySuccess,
  onGeminiKeyChange,
  onGeminiModelChange,
  onClose,
  onPush,
}: ResearcherModelKeyDialogProps) {
  const { suggestions } = useGeminiConfig();
  const isKnown = suggestions.length > 0 && suggestions.includes(geminiModel);
  const selectValue = isKnown ? geminiModel : (geminiModel ? CUSTOM_VALUE : (suggestions[0] ?? CUSTOM_VALUE));

  function handleSelectChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const v = e.target.value;
    if (v === CUSTOM_VALUE) {
      onGeminiModelChange("");
    } else {
      onGeminiModelChange(v);
    }
  }

  return (
    <DialogShell
      open={open}
      title="Participant model / API key"
      titleId="researcher-model-key-dialog-title"
      maxWidth="500px"
      actions={
        <>
          <button type="button" onClick={onClose}>
            Close
          </button>
          <button type="button" disabled={busy} onClick={() => void onPush()}>
            Push key
          </button>
        </>
      }
    >
      <p className="muted" style={{ fontSize: "0.85rem" }}>
        Server status for this session: <strong>{configured ? "API key stored" : "No API key yet"}</strong>
      </p>
      {pushKeySuccess ? (
        <p className="banner-info" style={{ margin: "0.5rem 0 0", fontSize: "0.85rem", padding: "0.5rem" }}>
          {pushKeySuccess}
        </p>
      ) : null}
      <label className="muted" style={{ display: "block", marginTop: "0.75rem" }}>
        Gemini API key
        <input
          type="password"
          placeholder="Gemini API key"
          value={geminiKey}
          onChange={(e) => onGeminiKeyChange(e.target.value)}
          style={{ width: "100%", marginTop: "0.2rem" }}
        />
      </label>
      <label className="muted" style={{ display: "block", marginTop: "0.6rem" }}>
        Gemini model id
        {suggestions.length > 0 ? (
          <select
            style={{ width: "100%", marginTop: "0.2rem" }}
            value={selectValue}
            onChange={handleSelectChange}
          >
            {suggestions.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
            <option value={CUSTOM_VALUE}>Custom (type below)…</option>
          </select>
        ) : null}
        {(!isKnown || suggestions.length === 0) && (
          <input
            value={geminiModel}
            onChange={(e) => onGeminiModelChange(e.target.value)}
            placeholder="e.g. gemini-3.1-flash-lite-preview"
            autoComplete="off"
            style={{ width: "100%", marginTop: "0.3rem" }}
          />
        )}
      </label>
    </DialogShell>
  );
}
