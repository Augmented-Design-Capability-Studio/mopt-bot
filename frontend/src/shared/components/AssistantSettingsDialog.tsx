import type { ReactNode } from "react";

import { useGeminiConfig } from "@shared/geminiModelSuggestions";
import { DialogShell } from "@shared/components/DialogShell";

const CUSTOM_VALUE = "__custom__";

export type AssistantSettingsDialogProps = {
  open: boolean;
  /** Dialog title — defaults to "Assistant settings". */
  title?: string;
  /** Save button label — defaults to "Save". Researcher uses "Push key". */
  saveLabel?: string;
  /** Optional banner rendered above the form (e.g. researcher push-success message). */
  banner?: ReactNode;
  /** Optional status line above the form (e.g. "API key stored" / "No API key yet"). */
  statusText?: ReactNode;
  modelName: string;
  modelKey: string;
  embeddingModel: string;
  busy: boolean;
  saveDisabled?: boolean;
  modelKeyPlaceholder?: string;
  onModelNameChange: (value: string) => void;
  onModelKeyChange: (value: string) => void;
  onEmbeddingModelChange: (value: string) => void;
  onClose: () => void;
  onSave: () => void | Promise<void>;
};

export function AssistantSettingsDialog({
  open,
  title = "Assistant settings",
  saveLabel = "Save",
  banner,
  statusText,
  modelName,
  modelKey,
  embeddingModel,
  busy,
  saveDisabled = false,
  modelKeyPlaceholder = "Paste key (optional if researcher pushed one)",
  onModelNameChange,
  onModelKeyChange,
  onEmbeddingModelChange,
  onClose,
  onSave,
}: AssistantSettingsDialogProps) {
  const { suggestions, embeddingSuggestions } = useGeminiConfig();

  const isKnown = suggestions.length > 0 && suggestions.includes(modelName);
  const selectValue = isKnown
    ? modelName
    : modelName
      ? CUSTOM_VALUE
      : suggestions[0] ?? CUSTOM_VALUE;

  function handleSelectChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const v = e.target.value;
    if (v === CUSTOM_VALUE) {
      onModelNameChange("");
    } else {
      onModelNameChange(v);
    }
  }

  const isEmbeddingKnown =
    embeddingSuggestions.length > 0 && embeddingSuggestions.includes(embeddingModel);
  const embeddingSelectValue = isEmbeddingKnown
    ? embeddingModel
    : embeddingModel
      ? CUSTOM_VALUE
      : embeddingSuggestions[0] ?? CUSTOM_VALUE;

  function handleEmbeddingSelectChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const v = e.target.value;
    if (v === CUSTOM_VALUE) {
      onEmbeddingModelChange("");
    } else {
      onEmbeddingModelChange(v);
    }
  }

  return (
    <DialogShell
      open={open}
      title={title}
      titleId="assistant-settings-dialog-title"
      maxWidth="500px"
      actions={
        <>
          <button type="button" onClick={onClose}>
            Close
          </button>
          <button type="button" disabled={busy || saveDisabled} onClick={() => void onSave()}>
            {saveLabel}
          </button>
        </>
      }
    >
      <p className="muted" style={{ fontSize: "0.85rem" }}>
        Keys are stored on the server for this session (encrypted if the server is configured for it).
      </p>
      {statusText ? (
        <p className="muted" style={{ fontSize: "0.85rem", marginTop: "0.35rem" }}>
          {statusText}
        </p>
      ) : null}
      {banner ? (
        <p
          className="banner-info"
          style={{ margin: "0.5rem 0 0", fontSize: "0.85rem", padding: "0.5rem" }}
        >
          {banner}
        </p>
      ) : null}
      <label className="muted" style={{ display: "block", marginTop: "0.75rem" }}>
        Gemini model id
        {suggestions.length > 0 ? (
          <select
            style={{ width: "100%", marginTop: "0.2rem" }}
            value={selectValue}
            onChange={handleSelectChange}
          >
            {suggestions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
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
      <label className="muted" style={{ display: "block", marginTop: "0.6rem" }}>
        Embedding model id
        {embeddingSuggestions.length > 0 ? (
          <select
            style={{ width: "100%", marginTop: "0.2rem" }}
            value={embeddingSelectValue}
            onChange={handleEmbeddingSelectChange}
          >
            {embeddingSuggestions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
            <option value={CUSTOM_VALUE}>Custom (type below)…</option>
          </select>
        ) : null}
        {(!isEmbeddingKnown || embeddingSuggestions.length === 0) && (
          <input
            style={{ width: "100%", marginTop: "0.3rem" }}
            value={embeddingModel}
            onChange={(e) => onEmbeddingModelChange(e.target.value)}
            placeholder="e.g. gemini-embedding-001"
            autoComplete="off"
          />
        )}
      </label>
      <p className="muted" style={{ fontSize: "0.75rem", margin: "0.25rem 0 0" }}>
        Used for goal-term anchoring and docs retrieval. Defaults to the server's configured embedding model.
      </p>
      <label className="muted" style={{ display: "block", marginTop: "0.6rem" }}>
        Gemini API key
        <input
          type="password"
          style={{ width: "100%", marginTop: "0.2rem" }}
          value={modelKey}
          onChange={(e) => onModelKeyChange(e.target.value)}
          placeholder={modelKeyPlaceholder}
        />
      </label>
    </DialogShell>
  );
}
