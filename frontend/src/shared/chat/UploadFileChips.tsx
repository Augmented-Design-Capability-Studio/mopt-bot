import { buildProblemFileUrl } from "@shared/api";

type UploadFileChipsProps = {
  fileNames: string[];
  problemId?: string;
  removable?: boolean;
  onRemove?: (fileName: string) => void;
  className?: string;
  removeDisabled?: boolean;
};

export function UploadFileChips({
  fileNames,
  problemId,
  removable = false,
  onRemove,
  className,
  removeDisabled = false,
}: UploadFileChipsProps) {
  return (
    <div className={["chat-upload-chips", className ?? ""].join(" ").trim()} aria-label="Uploaded files">
      {fileNames.map((name) => {
        const downloadUrl = problemId ? buildProblemFileUrl(problemId, name) : null;
        return (
          <span key={name} className="chat-upload-chip" title={name}>
            {downloadUrl ? (
              <a
                href={downloadUrl}
                download={name}
                className="chat-upload-chip-name chat-upload-chip-link"
                title={`Download ${name}`}
              >
                {name}
              </a>
            ) : (
              <span className="chat-upload-chip-name">{name}</span>
            )}
            {removable && onRemove ? (
              <button
                type="button"
                className="chat-upload-chip-remove"
                aria-label={`Remove ${name} from upload list`}
                disabled={removeDisabled}
                onClick={() => onRemove(name)}
              >
                ×
              </button>
            ) : null}
          </span>
        );
      })}
    </div>
  );
}

