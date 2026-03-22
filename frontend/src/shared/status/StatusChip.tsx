type StatusChipProps = {
  label: string;
  status: "ok" | "warn" | "neutral";
  icon: string;
  detail?: string;
  title?: string;
  onClick: () => void;
};

export function StatusChip({ label, status, icon, detail, title, onClick }: StatusChipProps) {
  return (
    <button type="button" className={`status-chip status-${status}`} title={title} onClick={onClick}>
      <span className="status-chip-icon" aria-hidden>
        {icon}
      </span>
      <span>{label}</span>
      {detail ? <span className="status-chip-detail">{detail}</span> : null}
    </button>
  );
}
