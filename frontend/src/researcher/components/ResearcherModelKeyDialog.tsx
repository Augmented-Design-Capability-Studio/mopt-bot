import {
  DEFAULT_SUGGESTED_GEMINI_MODEL,
  GEMINI_MODEL_DATALIST_ID,
  GeminiModelDatalist,
} from "@shared/geminiModelSuggestions";
import { DialogShell } from "@shared/components/DialogShell";

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
      <GeminiModelDatalist />
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
        <input
          value={geminiModel}
          onChange={(e) => onGeminiModelChange(e.target.value)}
          list={GEMINI_MODEL_DATALIST_ID}
          placeholder={DEFAULT_SUGGESTED_GEMINI_MODEL}
          autoComplete="off"
          style={{ width: "100%", marginTop: "0.2rem" }}
        />
      </label>
    </DialogShell>
  );
}
