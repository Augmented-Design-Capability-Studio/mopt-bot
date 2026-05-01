import type { ReactNode } from "react";

type StatusBannerTone = "warning" | "error" | "info";

type StatusBannerProps = {
  tone?: StatusBannerTone;
  children: ReactNode;
  actionLabel?: string;
  onAction?: () => void;
  role?: "status" | "alert";
};

export function StatusBanner({
  tone = "warning",
  children,
  actionLabel,
  onAction,
  role = "status",
}: StatusBannerProps) {
  return (
    <div className={`status-banner status-banner--${tone}`} role={role}>
      <span>{children}</span>
      {actionLabel && onAction ? (
        <button type="button" className="status-banner-action" onClick={onAction}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

