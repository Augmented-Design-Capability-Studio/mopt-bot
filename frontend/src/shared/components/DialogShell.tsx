import type { ReactNode } from "react";

type DialogShellProps = {
  open: boolean;
  title: string;
  titleId: string;
  children: ReactNode;
  actions?: ReactNode;
  maxWidth?: string;
};

export function DialogShell({ open, title, titleId, children, actions, maxWidth = "420px" }: DialogShellProps) {
  if (!open) return null;

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <div className="dialog" style={{ maxWidth }}>
        <h2 id={titleId} style={{ margin: "0 0 0.5rem", fontSize: "1rem" }}>
          {title}
        </h2>
        {children}
        {actions && <div className="dialog-actions">{actions}</div>}
      </div>
    </div>
  );
}
