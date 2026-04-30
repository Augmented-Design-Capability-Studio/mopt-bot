import type { ReactNode } from "react";

export function BlockSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div>
      <div
        style={{
          fontSize: "0.68rem",
          textTransform: "uppercase",
          letterSpacing: "0.07em",
          fontWeight: 700,
          color: "var(--fg-muted, #666)",
          marginBottom: "0.35rem",
          paddingBottom: "0.25rem",
          borderBottom: "2px solid var(--border)",
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

export function FieldRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.2rem",
        padding: "0.35rem 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div
        style={{
          fontSize: "0.7rem",
          color: "var(--fg-muted, #666)",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
      >
        <span className="field-row-label">{label}</span>
      </div>
      <div>{children}</div>
    </div>
  );
}
