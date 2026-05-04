import { useEffect } from "react";

type DismissibleBannerKind = "info" | "warn";

type DismissibleBannerProps = {
  kind: DismissibleBannerKind;
  message: string;
  onDismiss: () => void;
  /** When set (>0), auto-dismiss after this many milliseconds. */
  autoDismissMs?: number;
};

export function DismissibleBanner({
  kind,
  message,
  onDismiss,
  autoDismissMs,
}: DismissibleBannerProps) {
  useEffect(() => {
    if (!autoDismissMs || autoDismissMs <= 0) return;
    const id = window.setTimeout(onDismiss, autoDismissMs);
    return () => window.clearTimeout(id);
  }, [message, autoDismissMs, onDismiss]);

  return (
    <div
      className={`dismissible-banner dismissible-banner-${kind}`}
      role={kind === "warn" ? "alert" : "status"}
    >
      <span className="dismissible-banner-message">{message}</span>
      <button
        type="button"
        className="dismissible-banner-close"
        aria-label="Dismiss"
        title="Dismiss"
        onClick={onDismiss}
      >
        ×
      </button>
    </div>
  );
}
