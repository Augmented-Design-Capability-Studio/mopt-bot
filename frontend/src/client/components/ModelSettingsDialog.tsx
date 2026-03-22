import {
  DEFAULT_SUGGESTED_GEMINI_MODEL,
  GEMINI_MODEL_DATALIST_ID,
  GeminiModelDatalist,
} from "@shared/geminiModelSuggestions";
import { DialogShell } from "@shared/components/DialogShell";

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
    </DialogShell>
  );
}
