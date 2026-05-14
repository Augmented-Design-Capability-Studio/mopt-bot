import { AssistantSettingsDialog } from "@shared/components/AssistantSettingsDialog";

type ResearcherModelKeyDialogProps = {
  open: boolean;
  configured: boolean;
  geminiKey: string;
  geminiModel: string;
  embeddingModel: string;
  busy: boolean;
  pushKeySuccess: string | null;
  onGeminiKeyChange: (value: string) => void;
  onGeminiModelChange: (value: string) => void;
  onEmbeddingModelChange: (value: string) => void;
  onClose: () => void;
  onPush: () => void | Promise<void>;
};

export function ResearcherModelKeyDialog({
  open,
  configured,
  geminiKey,
  geminiModel,
  embeddingModel,
  busy,
  pushKeySuccess,
  onGeminiKeyChange,
  onGeminiModelChange,
  onEmbeddingModelChange,
  onClose,
  onPush,
}: ResearcherModelKeyDialogProps) {
  return (
    <AssistantSettingsDialog
      open={open}
      title="Assistant settings (participant session)"
      saveLabel="Push key"
      statusText={
        <>
          Server status for this session:{" "}
          <strong>{configured ? "API key stored" : "No API key yet"}</strong>
        </>
      }
      banner={pushKeySuccess || undefined}
      modelName={geminiModel}
      modelKey={geminiKey}
      embeddingModel={embeddingModel}
      busy={busy}
      modelKeyPlaceholder="Gemini API key"
      onModelNameChange={onGeminiModelChange}
      onModelKeyChange={onGeminiKeyChange}
      onEmbeddingModelChange={onEmbeddingModelChange}
      onClose={onClose}
      onSave={onPush}
    />
  );
}
