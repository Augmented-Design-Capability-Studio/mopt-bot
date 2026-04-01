import { useEffect, useMemo, useRef, useState } from "react";

import type { ProblemBrief, SnapshotSummary } from "@shared/api";

import type { EditMode } from "../lib/participantTypes";
import { DefinitionPanel } from "../problemDefinition/DefinitionPanel";
import { ProblemConfigBlocks } from "./ProblemConfigBlocks";
import { SnapshotDialog } from "./SnapshotDialog";

type ConfigPanelProps = {
  configText: string;
  problemBrief: ProblemBrief | null;
  editMode: EditMode;
  busy: boolean;
  syncingProblemConfig: boolean;
  backgroundBriefPending: boolean;
  backgroundConfigPending: boolean;
  backgroundProcessingError?: string | null;
  sessionTerminated: boolean;
  className: string;
  onConfigTextChange: (value: string) => void;
  onProblemBriefChange: (value: ProblemBrief | null) => void;
  onSetEditMode: (mode: EditMode) => void;
  onSaveConfig: () => void | Promise<void>;
  onSaveProblemBrief: (
    overrideBrief?: ProblemBrief,
    options?: { chatNote?: string },
  ) => void | Promise<void>;
  onSyncProblemConfig: () => void | Promise<void>;
  onEnterConfigEdit?: () => void;
  onCancelConfigEdit?: () => void;
  onLoadConfigFromLastRun?: () => void;
  onRestoreFromSnapshot?: (snapshot: SnapshotSummary, source: "definition" | "config") => void;
  onLoadSnapshots?: () => void | Promise<void>;
  snapshots?: SnapshotSummary[];
  snapshotsLoading?: boolean;
  canLoadFromLastRun?: boolean;
  canLoadFromSnapshot?: boolean;
};

type PanelTab = "definition" | "config" | "raw";

const PROCESSING_UI_UNLOCK_MS = 90_000;

export function ConfigPanel({
  configText,
  problemBrief,
  editMode,
  busy,
  syncingProblemConfig,
  backgroundBriefPending,
  backgroundConfigPending,
  backgroundProcessingError,
  sessionTerminated,
  className,
  onConfigTextChange,
  onProblemBriefChange,
  onSetEditMode,
  onSaveConfig,
  onSaveProblemBrief,
  onSyncProblemConfig,
  onEnterConfigEdit,
  onCancelConfigEdit,
  onLoadConfigFromLastRun,
  onRestoreFromSnapshot,
  onLoadSnapshots,
  snapshots = [],
  snapshotsLoading = false,
  canLoadFromLastRun = false,
  canLoadFromSnapshot = false,
}: ConfigPanelProps) {
  const [activeTab, setActiveTab] = useState<PanelTab>("definition");
  const [loadMenuOpen, setLoadMenuOpen] = useState(false);
  const [snapshotDialogSource, setSnapshotDialogSource] = useState<"definition" | "config" | null>(null);
  const [forceUnlockProcessingUi, setForceUnlockProcessingUi] = useState(false);
  const [processingStallWarn, setProcessingStallWarn] = useState(false);
  const [definitionUnread, setDefinitionUnread] = useState(false);
  const [configUnread, setConfigUnread] = useState(false);
  const loadMenuRef = useRef<HTMLDivElement>(null);
  const prevBriefPending = useRef(backgroundBriefPending);
  const prevConfigPending = useRef(backgroundConfigPending);

  const hasLoadOptions = canLoadFromLastRun || canLoadFromSnapshot;

  useEffect(() => {
    if (!loadMenuOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (loadMenuRef.current && !loadMenuRef.current.contains(e.target as Node)) {
        setLoadMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [loadMenuOpen]);

  const openSnapshotDialog = (source: "definition" | "config") => {
    void onLoadSnapshots?.();
    setSnapshotDialogSource(source);
  };

  useEffect(() => {
    if (editMode === "config" && activeTab !== "config") {
      setActiveTab("config");
      setConfigUnread(false);
    }
    if (editMode === "definition" && activeTab !== "definition") {
      setActiveTab("definition");
      setDefinitionUnread(false);
    }
  }, [activeTab, editMode]);

  useEffect(() => {
    if (prevBriefPending.current && !backgroundBriefPending && activeTab !== "definition") {
      setDefinitionUnread(true);
    }
    prevBriefPending.current = backgroundBriefPending;
  }, [backgroundBriefPending, activeTab]);

  useEffect(() => {
    if (prevConfigPending.current && !backgroundConfigPending && activeTab !== "config") {
      setConfigUnread(true);
    }
    prevConfigPending.current = backgroundConfigPending;
  }, [backgroundConfigPending, activeTab]);

  const definitionEditing = false;
  const configEditing = editMode === "config";
  const editableDefinition = !sessionTerminated;
  const editableConfig = configEditing && !sessionTerminated;
  const tabLocked = editMode !== "none";

  const backgroundProcessingPending =
    backgroundBriefPending || backgroundConfigPending || syncingProblemConfig;

  useEffect(() => {
    if (!backgroundProcessingPending || configEditing) {
      setForceUnlockProcessingUi(false);
      setProcessingStallWarn(false);
      return;
    }
    const timer = window.setTimeout(() => {
      setForceUnlockProcessingUi(true);
      setProcessingStallWarn(true);
    }, PROCESSING_UI_UNLOCK_MS);
    return () => window.clearTimeout(timer);
  }, [backgroundProcessingPending, configEditing]);

  const configOrRawBlockingUi =
    (activeTab === "config" || activeTab === "raw") &&
    !configEditing &&
    backgroundProcessingPending &&
    !forceUnlockProcessingUi;

  const configSurfaceLocked =
    (activeTab === "config" || activeTab === "raw") &&
    backgroundProcessingPending &&
    !forceUnlockProcessingUi &&
    !configEditing;

  const tabTitle =
    activeTab === "definition"
      ? "Definition"
      : activeTab === "config"
        ? "Problem Config"
        : "Raw JSON";
  const rawJsonText = useMemo(() => {
    const trimmedConfig = configText.trim();
    let parsedConfig: unknown = {};
    let invalidConfigText: string | null = null;

    if (trimmedConfig !== "") {
      try {
        parsedConfig = JSON.parse(trimmedConfig) as unknown;
      } catch {
        invalidConfigText = configText;
      }
    }

    return JSON.stringify(
      {
        problem_definition: problemBrief,
        problem_config: parsedConfig,
        ...(invalidConfigText !== null ? { problem_config_raw_text: invalidConfigText } : {}),
      },
      null,
      2,
    );
  }, [configText, problemBrief]);

  return (
    <section className={className}>
      <div className="panel-header">
        Problem setup
        {configEditing && <span className="muted"> - editing {tabTitle.toLowerCase()}</span>}
        {!definitionEditing && !configEditing && (backgroundBriefPending || backgroundConfigPending) && (
          <span className="muted" style={{ display: "inline-flex", alignItems: "center", marginLeft: "0.5rem" }}>
            <span className="inline-spinner" aria-hidden="true" />
          </span>
        )}
      </div>
      <div className="panel-body">
        <div className="tabs">
          {([
            ["definition", "Definition"],
            ["config", "Problem Config"],
            ["raw", "Raw JSON"],
          ] as Array<[PanelTab, string]>).map(([tabId, label]) => (
            <button
              key={tabId}
              type="button"
              className={`tab ${activeTab === tabId ? "active" : ""}`}
              aria-label={
                tabId === "definition" && definitionUnread
                  ? "Definition (updated)"
                  : tabId === "config" && configUnread
                    ? "Problem Config (updated)"
                    : label
              }
              onClick={() => {
                setActiveTab(tabId);
                if (tabId === "definition") setDefinitionUnread(false);
                if (tabId === "config") setConfigUnread(false);
              }}
              disabled={tabLocked && activeTab !== tabId}
            >
              {label}
              {tabId === "definition" && backgroundBriefPending ? (
                <span className="inline-spinner" aria-hidden="true" style={{ marginLeft: "0.35rem" }} />
              ) : null}
              {tabId === "config" && (backgroundConfigPending || syncingProblemConfig) ? (
                <span className="inline-spinner" aria-hidden="true" style={{ marginLeft: "0.35rem" }} />
              ) : null}
              {tabId === "definition" && definitionUnread && !backgroundBriefPending ? (
                <span
                  title="Updated"
                  aria-hidden="true"
                  style={{
                    display: "inline-block",
                    width: "0.45rem",
                    height: "0.45rem",
                    marginLeft: "0.35rem",
                    borderRadius: "50%",
                    background: "#c62828",
                    verticalAlign: "middle",
                  }}
                />
              ) : null}
              {tabId === "config" && configUnread && !backgroundConfigPending && !syncingProblemConfig ? (
                <span
                  title="Updated"
                  aria-hidden="true"
                  style={{
                    display: "inline-block",
                    width: "0.45rem",
                    height: "0.45rem",
                    marginLeft: "0.35rem",
                    borderRadius: "50%",
                    background: "#c62828",
                    verticalAlign: "middle",
                  }}
                />
              ) : null}
            </button>
          ))}
        </div>

        {backgroundProcessingError && !definitionEditing && !configEditing && (
          <p className="muted" style={{ margin: "0.35rem 0 0" }}>
            Background update issue: {backgroundProcessingError}
          </p>
        )}

        {processingStallWarn && backgroundProcessingPending && !configEditing && (
          <p className="muted" style={{ margin: "0.35rem 0 0" }}>
            Background update is taking longer than expected. The config area was unlocked so you can keep working;
            try refreshing or sync again if something looks stale.
          </p>
        )}

        <div className={`config-panel-scroll ${configOrRawBlockingUi ? "config-panel-scroll--shielded" : ""}`}>
          {activeTab === "definition" ? (
            problemBrief ? (
              <>
                <DefinitionPanel
                  problemBrief={problemBrief}
                  editable={editableDefinition}
                  sessionTerminated={sessionTerminated}
                  onChange={onProblemBriefChange}
                  onPersistInlineEdit={onSaveProblemBrief}
                />
              </>
            ) : (
              <p className="muted" style={{ fontSize: "0.85rem", padding: "0.35rem 0" }}>
                Loading problem definition...
              </p>
            )
          ) : activeTab === "config" ? (
            <>
              <ProblemConfigBlocks configJson={configText} onChange={onConfigTextChange} editable={editableConfig} />
            </>
          ) : (
            <textarea
              className="mono config-raw-textarea"
              value={rawJsonText}
              readOnly
              disabled={false}
              spellCheck={false}
              placeholder='{"problem_definition": null, "problem_config": null}'
            />
          )}
          {configOrRawBlockingUi ? (
            <div className="config-panel-processing-shield" aria-live="polite">
              <span className="inline-spinner" aria-hidden="true" />
              <span className="muted">Updating problem config from the latest definition…</span>
            </div>
          ) : null}
        </div>

        <div className="config-panel-actions">
          {activeTab === "definition" ? (
            <>
              <button
                type="button"
                onClick={() => void onSaveProblemBrief()}
                disabled={busy || editMode !== "none" || sessionTerminated || !problemBrief}
                title="Save definition and trigger chat acknowledgement"
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => openSnapshotDialog("definition")}
                disabled={snapshots.length === 0 || sessionTerminated}
                title="Load definition from a snapshot"
              >
                Load
              </button>
              <button
                type="button"
                onClick={() => void onSyncProblemConfig()}
                disabled={busy || editMode !== "none" || sessionTerminated || !problemBrief}
                title="Debug: rebuild the saved problem config from the saved definition"
              >
                {syncingProblemConfig ? (
                  <span style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
                    <span className="inline-spinner" aria-hidden="true" />
                    Syncing...
                  </span>
                ) : (
                  "Sync to config"
                )}
              </button>
            </>
          ) : activeTab === "config" ? !configEditing ? (
            <>
              <button
                type="button"
                onClick={() => (onEnterConfigEdit ? onEnterConfigEdit() : onSetEditMode("config"))}
                disabled={editMode !== "none" || sessionTerminated || configSurfaceLocked}
                title={configSurfaceLocked ? "Wait for background config update or use Unlock after delay" : undefined}
              >
                Edit
              </button>
              {hasLoadOptions && onLoadConfigFromLastRun && (
                <div ref={loadMenuRef} style={{ position: "relative" }}>
                  <button
                    type="button"
                    onClick={() => setLoadMenuOpen((o) => !o)}
                    disabled={sessionTerminated || configSurfaceLocked || (!canLoadFromLastRun && !canLoadFromSnapshot)}
                    title="Load config from run or snapshot"
                    aria-expanded={loadMenuOpen}
                    aria-haspopup="menu"
                  >
                    Load config <span aria-hidden="true">{loadMenuOpen ? "▼" : "▲"}</span>
                  </button>
                  {loadMenuOpen && (
                    <div
                      className="config-load-dropup"
                      role="menu"
                      style={{
                        position: "absolute",
                        bottom: "100%",
                        left: 0,
                        marginBottom: "0.2rem",
                        display: "flex",
                        flexDirection: "column",
                        gap: 0,
                        background: "var(--bg)",
                        border: "1px solid var(--border)",
                        borderRadius: "2px",
                        boxShadow: "0 -2px 6px rgba(0,0,0,0.12)",
                        minWidth: "100%",
                        overflow: "hidden",
                        zIndex: 10,
                      }}
                    >
                      <button
                        type="button"
                        role="menuitem"
                        disabled={!canLoadFromLastRun || sessionTerminated}
                        onClick={() => {
                          onLoadConfigFromLastRun();
                          setLoadMenuOpen(false);
                        }}
                        title="Restore config from the most recent optimization run"
                        style={{ padding: "0.4rem 0.6rem", textAlign: "left", fontSize: "0.9rem" }}
                      >
                        From most recent run
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        disabled={!canLoadFromSnapshot || sessionTerminated}
                        onClick={() => {
                          openSnapshotDialog("config");
                          setLoadMenuOpen(false);
                        }}
                        title="Restore config from a snapshot"
                        style={{ padding: "0.4rem 0.6rem", textAlign: "left", fontSize: "0.9rem" }}
                      >
                        Load from snapshot...
                      </button>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <>
              <button type="button" onClick={() => void onSaveConfig()} disabled={busy || sessionTerminated}>
                Save
              </button>
              <button type="button" onClick={() => (onCancelConfigEdit ? onCancelConfigEdit() : onSetEditMode("none"))}>
                Cancel
              </button>
            </>
          ) : (
            <p className="muted" style={{ margin: 0 }}>
              Raw JSON is read-only. Edit the Definition or Problem Config tab to make changes.
            </p>
          )}
        </div>
      </div>

      {snapshotDialogSource && onRestoreFromSnapshot && (
        <SnapshotDialog
          open={snapshotDialogSource !== null}
          onClose={() => setSnapshotDialogSource(null)}
          snapshots={snapshots}
          loading={snapshotsLoading}
          sourceTab={snapshotDialogSource}
          sessionTerminated={sessionTerminated}
          busy={busy}
          onRestore={onRestoreFromSnapshot}
        />
      )}
    </section>
  );
}
