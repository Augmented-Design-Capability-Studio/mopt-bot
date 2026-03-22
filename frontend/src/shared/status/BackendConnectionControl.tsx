import { useCallback, useEffect, useMemo, useState } from "react";

import {
  backendSourceLabel,
  buildHealthUrl,
  clearUserBackendBaseOverride,
  normalizeBackendBase,
  readUserBackendBaseOverride,
  resolveBackendBase,
  setUserBackendBaseOverride,
} from "@shared/backendConfig";
import { DialogShell } from "@shared/components/DialogShell";

import { StatusChip } from "./StatusChip";

type HealthState = {
  status: "ok" | "warn" | "neutral";
  detail: string;
};

function nextDraftValue(): string {
  const userOverride = readUserBackendBaseOverride();
  return userOverride ?? resolveBackendBase().url;
}

export function BackendConnectionControl() {
  const [open, setOpen] = useState(false);
  const [draftBase, setDraftBase] = useState(() => nextDraftValue());
  const [resolved, setResolved] = useState(() => resolveBackendBase());
  const [health, setHealth] = useState<HealthState>({ status: "neutral", detail: "checking" });

  const refreshHealth = useCallback(async () => {
    const nextResolved = resolveBackendBase();
    setResolved(nextResolved);
    try {
      const response = await fetch(buildHealthUrl(nextResolved.url), { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setHealth({ status: "ok", detail: "connected" });
    } catch {
      setHealth({ status: "warn", detail: "offline" });
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
    const timer = window.setInterval(() => void refreshHealth(), 5000);
    return () => window.clearInterval(timer);
  }, [refreshHealth]);

  useEffect(() => {
    if (!open) return;
    setDraftBase(nextDraftValue());
  }, [open, resolved.url]);

  const handleSave = useCallback(async () => {
    const normalized = normalizeBackendBase(draftBase);
    if (normalized) {
      setUserBackendBaseOverride(normalized);
    } else {
      clearUserBackendBaseOverride();
    }
    await refreshHealth();
    setOpen(false);
  }, [draftBase, refreshHealth]);

  const handleUseAutomatic = useCallback(async () => {
    clearUserBackendBaseOverride();
    const nextResolved = resolveBackendBase();
    setDraftBase(nextResolved.url);
    await refreshHealth();
  }, [refreshHealth]);

  const statusTitle = useMemo(
    () => `Backend: ${resolved.url} (${backendSourceLabel(resolved.source)}, ${health.detail})`,
    [health.detail, resolved.source, resolved.url],
  );
  const hasUserOverride = resolved.source === "user";

  return (
    <>
      <StatusChip
        label="Backend"
        status={health.status}
        icon={health.status === "ok" ? "✓" : health.status === "warn" ? "⚠" : "○"}
        detail={health.detail}
        title={statusTitle}
        onClick={() => setOpen(true)}
      />
      <DialogShell
        open={open}
        title="Backend connection"
        titleId="backend-connection-dialog-title"
        maxWidth="500px"
        actions={
          <>
            <button type="button" onClick={() => setOpen(false)}>
              Close
            </button>
            <button type="button" onClick={() => void handleUseAutomatic()}>
              Use automatic
            </button>
            <button type="button" onClick={() => void handleSave()}>
              Save
            </button>
          </>
        }
      >
        <p className="muted" style={{ fontSize: "0.85rem" }}>
          Requests use this priority: user input, then <code>VITE_API_BASE</code>, then the default local backend.
        </p>
        <p className="muted" style={{ fontSize: "0.85rem", marginTop: "0.35rem" }}>
          Active URL: <code>{resolved.url}</code>
        </p>
        <p className="muted" style={{ fontSize: "0.85rem", marginTop: "0.2rem" }}>
          Source: <strong>{backendSourceLabel(resolved.source)}</strong> · Status: <strong>{health.detail}</strong>
        </p>
        <label className="muted" style={{ display: "block", marginTop: "0.75rem" }}>
          Backend URL
          <input
            style={{ width: "100%", marginTop: "0.2rem" }}
            value={draftBase}
            onChange={(e) => setDraftBase(e.target.value)}
            placeholder={resolved.url}
            autoComplete="off"
          />
        </label>
        <p className="muted" style={{ fontSize: "0.75rem", marginTop: "0.25rem" }}>
          {hasUserOverride
            ? "A browser-local override is active right now."
            : "No browser-local override is set right now."}
        </p>
      </DialogShell>
    </>
  );
}
