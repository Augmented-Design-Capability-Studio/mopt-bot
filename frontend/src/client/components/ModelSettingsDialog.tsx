import { useGeminiConfig } from "@shared/geminiModelSuggestions";
import { DialogShell } from "@shared/components/DialogShell";

const CUSTOM_VALUE = "__custom__";

type ModelSettingsDialogProps = {
  open: boolean;
  modelName: string;
  modelKey: string;
  busy: boolean;
  sessionTerminated: boolean;
  onModelNameChange: (value: string) => void;
  onModelKeyChange: (value: string) => void;
  onClose: () => void;
  onSave: () => void | Promise<void>;
};

export function ModelSettingsDialog({
  open,
  modelName,
  modelKey,
  busy,
  sessionTerminated,
  onModelNameChange,
  onModelKeyChange,
  onClose,
  onSave,
}: ModelSettingsDialogProps) {
  const { suggestions } = useGeminiConfig();
  const isKnown = suggestions.length > 0 && suggestions.includes(modelName);
  const selectValue = isKnown ? modelName : (modelName ? CUSTOM_VALUE : (suggestions[0] ?? CUSTOM_VALUE));

  function handleSelectChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const v = e.target.value;
    if (v === CUSTOM_VALUE) {
      onModelNameChange("");
    } else {
      onModelNameChange(v);
    }
  }

  return (
    <DialogShell
      open={open}
      title="Model & API key"
      titleId="model-dlg-title"
      actions={
        <>
          <button type="button" onClick={onClose}>
            Close
          </button>
          <button type="button" disabled={busy || sessionTerminated} onClick={() => void onSave()}>
            Save
          </button>
        </>
      }
    >
        <p className="muted" style={{ fontSize: "0.85rem" }}>
          Keys are stored on the server for this session (encrypted if the server is configured for it).
        </p>
        <label className="muted">
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
              style={{ width: "100%", marginTop: "0.3rem" }}
              value={modelName}
              onChange={(e) => onModelNameChange(e.target.value)}
              placeholder="e.g. gemini-3.1-flash-lite-preview"
              autoComplete="off"
            />
          )}
        </label>
        <p className="muted" style={{ fontSize: "0.75rem", margin: "0.25rem 0 0" }}>
          Pick a suggestion or choose Custom to type any model id your key supports.
        </p>
        <label className="muted" style={{ display: "block", marginTop: "0.5rem" }}>
          API key
          <input
            type="password"
            style={{ width: "100%", marginTop: "0.2rem" }}
            value={modelKey}
            onChange={(e) => onModelKeyChange(e.target.value)}
            placeholder="Paste key (optional if researcher pushed one)"
          />
        </label>
    </DialogShell>
  );
}
