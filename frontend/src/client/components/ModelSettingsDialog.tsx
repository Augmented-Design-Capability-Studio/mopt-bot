import { AssistantSettingsDialog } from "@shared/components/AssistantSettingsDialog";

type ModelSettingsDialogProps = {
  open: boolean;
  modelName: string;
  modelKey: string;
  embeddingModel: string;
  busy: boolean;
  sessionTerminated: boolean;
  onModelNameChange: (value: string) => void;
  onModelKeyChange: (value: string) => void;
  onEmbeddingModelChange: (value: string) => void;
  onClose: () => void;
  onSave: () => void | Promise<void>;
};

export function ModelSettingsDialog({
  open,
  modelName,
  modelKey,
  embeddingModel,
  busy,
  sessionTerminated,
  onModelNameChange,
  onModelKeyChange,
  onEmbeddingModelChange,
  onClose,
  onSave,
}: ModelSettingsDialogProps) {
  return (
    <AssistantSettingsDialog
      open={open}
      modelName={modelName}
      modelKey={modelKey}
      embeddingModel={embeddingModel}
      busy={busy}
      saveDisabled={sessionTerminated}
      onModelNameChange={onModelNameChange}
      onModelKeyChange={onModelKeyChange}
      onEmbeddingModelChange={onEmbeddingModelChange}
      onClose={onClose}
      onSave={onSave}
    />
  );
}
