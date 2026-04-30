type RawJsonDialogProps = {
  open: boolean;
  title: string;
  helperText?: string;
  jsonText: string;
  onClose: () => void;
};

export function RawJsonDialog({ open, title, helperText, jsonText, onClose }: RawJsonDialogProps) {
  if (!open) return null;
  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div className="dialog json-dialog" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        {helperText ? (
          <div className="muted" style={{ marginBottom: "0.45rem" }}>
            {helperText}
          </div>
        ) : null}
        <pre className="mono json-dialog-pre">{jsonText}</pre>
        <div className="dialog-actions">
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
