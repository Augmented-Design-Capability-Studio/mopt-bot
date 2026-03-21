import {
  DEFAULT_SUGGESTED_GEMINI_MODEL,
  GEMINI_MODEL_DATALIST_ID,
  GeminiModelDatalist,
} from "@shared/geminiModelSuggestions";

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
  if (!open) return null;

  return (
    <div
      className="dialog-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="model-dlg-title"
    >
      <div className="dialog">
        <h2 id="model-dlg-title" style={{ margin: "0 0 0.5rem", fontSize: "1rem" }}>
          Model & API key
        </h2>
        <p className="muted" style={{ fontSize: "0.85rem" }}>
          Keys are stored on the server for this session (encrypted if the server is configured for it).
        </p>
        <GeminiModelDatalist />
        <label className="muted">
          Gemini model id
          <input
            style={{ width: "100%", marginTop: "0.2rem" }}
            list={GEMINI_MODEL_DATALIST_ID}
            value={modelName}
            onChange={(e) => onModelNameChange(e.target.value)}
            placeholder={DEFAULT_SUGGESTED_GEMINI_MODEL}
            autoComplete="off"
          />
        </label>
        <p className="muted" style={{ fontSize: "0.75rem", margin: "0.25rem 0 0" }}>
          Pick a suggestion or type any model id your key supports.
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
        <div
          style={{
            marginTop: "1rem",
            display: "flex",
            gap: "0.5rem",
            justifyContent: "flex-end",
          }}
        >
          <button type="button" onClick={onClose}>
            Close
          </button>
          <button
            type="button"
            disabled={busy || sessionTerminated}
            onClick={() => void onSave()}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
