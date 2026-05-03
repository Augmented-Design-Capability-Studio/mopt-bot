import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import type { Message, ProblemBrief, RunResult, Session, SnapshotSummary, TestProblemMeta } from "@shared/api";
import { StatusBanner } from "@shared/status/StatusBanner";

import type { EditMode } from "../lib/clientTypes";
import type { ClientOpsState } from "../lib/clientOps";
import { DefinitionPanel } from "../problemDefinition/DefinitionPanel";
import { ProblemConfigBlocks } from "./ProblemConfigBlocks";
import { SnapshotDialog } from "./SnapshotDialog";
import { RawJsonDialog } from "../components/RawJsonDialog";

type ConfigPanelProps = {
  configText: string;
  problemBrief: ProblemBrief | null;
  editMode: EditMode;
  invokeModel: boolean;
  busy: boolean;
  syncingProblemConfig: boolean;
  clientOps: ClientOpsState;
  backgroundBriefPending: boolean;
  backgroundConfigPending: boolean;
  backgroundProcessingError?: string | null;
  sessionTerminated: boolean;
  /** Used for workflow-specific definition UI and waterfall run reminders. */
  session: Session | null;
  testProblemMeta: TestProblemMeta | null;
  runs?: RunResult[];
  messages?: Message[];
  className: string;
  onConfigTextChange: (value: string) => void;
  onProblemBriefChange: (value: ProblemBrief | null) => void;
  onSetEditMode: (mode: EditMode) => void;
  onSaveConfig: () => void | Promise<void>;
  onSaveDefinitionEdit: () => void | Promise<void>;
  onCancelDefinitionEdit: () => void;
  onEnsureDefinitionEditing: () => void;
  isDefinitionDirty: boolean;
  onRequestDefinitionCleanup: () => void | Promise<void>;
  onRequestOpenQuestionCleanup: () => void | Promise<void>;
  onSyncProblemConfig: () => void | Promise<void>;
  onRecoverGoalTerms?: () => void | Promise<void>;
  onEnterConfigEdit?: () => void;
  onCancelConfigEdit?: () => void;
  onLoadConfigFromLastRun?: () => void;
  onBookmarkSnapshot?: () => void | Promise<void>;
  onRestoreFromSnapshot?: (snapshot: SnapshotSummary, source: "definition" | "config") => void;
  onLoadSnapshots?: () => void | Promise<void>;
  snapshots?: SnapshotSummary[];
  snapshotsLoading?: boolean;
  canLoadFromLastRun?: boolean;
  canLoadFromSnapshot?: boolean;
  isConfigDirty?: boolean;
  onActiveTabChange?: (tab: PanelTab) => void;
  onUserTabClick?: (tab: PanelTab) => void;
  /**
   * External request to switch the active middle-panel tab. The pair acts like
   * a one-shot signal: when `tabSwitchNonce` increments, the panel switches to
   * `tabSwitchTarget`. Used by the tutorial bubble's switch-tab action.
   */
  tabSwitchNonce?: number;
  tabSwitchTarget?: PanelTab;
};

export type PanelTab = "definition" | "config";

const PROCESSING_UI_UNLOCK_MS = 90_000;

const dropUpMenuStyle: CSSProperties = {
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
};

const menuItemStyle: CSSProperties = { padding: "0.4rem 0.6rem", textAlign: "left", fontSize: "0.9rem" };

export function ConfigPanel({
  configText,
  problemBrief,
  editMode,
  invokeModel,
  busy,
  syncingProblemConfig,
  clientOps,
  backgroundBriefPending,
  backgroundConfigPending,
  backgroundProcessingError,
  sessionTerminated,
  session,
  testProblemMeta,
  runs = [],
  messages = [],
  className,
  onConfigTextChange,
  onProblemBriefChange,
  onSetEditMode,
  onSaveConfig,
  onSaveDefinitionEdit,
  onCancelDefinitionEdit,
  onEnsureDefinitionEditing,
  isDefinitionDirty,
  onRequestDefinitionCleanup,
  onRequestOpenQuestionCleanup,
  onSyncProblemConfig,
  onRecoverGoalTerms,
  onEnterConfigEdit,
  onCancelConfigEdit,
  onLoadConfigFromLastRun,
  onBookmarkSnapshot,
  onRestoreFromSnapshot,
  onLoadSnapshots,
  snapshots = [],
  snapshotsLoading = false,
  canLoadFromLastRun = false,
  canLoadFromSnapshot = false,
  isConfigDirty = false,
  onActiveTabChange,
  onUserTabClick,
  tabSwitchNonce,
  tabSwitchTarget,
}: ConfigPanelProps) {
  const [activeTab, setActiveTab] = useState<PanelTab>("definition");
  const [pendingDefinitionOpenQuestionsScroll, setPendingDefinitionOpenQuestionsScroll] = useState(false);
  const [defSnapshotMenuOpen, setDefSnapshotMenuOpen] = useState(false);
  const [defMoreMenuOpen, setDefMoreMenuOpen] = useState(false);
  const [configSnapshotMenuOpen, setConfigSnapshotMenuOpen] = useState(false);
  const [snapshotDialogSource, setSnapshotDialogSource] = useState<"definition" | "config" | null>(null);
  const [showRawJsonDialog, setShowRawJsonDialog] = useState(false);
  const [forceUnlockProcessingUi, setForceUnlockProcessingUi] = useState(false);
  const [processingStallWarn, setProcessingStallWarn] = useState(false);
  const [definitionUnread, setDefinitionUnread] = useState(false);
  const [configUnread, setConfigUnread] = useState(false);
  const defSnapshotMenuRef = useRef<HTMLDivElement>(null);
  const defMoreMenuRef = useRef<HTMLDivElement>(null);
  const configSnapshotMenuRef = useRef<HTMLDivElement>(null);
  const prevBriefPending = useRef(backgroundBriefPending);
  const prevConfigPending = useRef(backgroundConfigPending);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const t = e.target as Node;
      if (defSnapshotMenuOpen && defSnapshotMenuRef.current && !defSnapshotMenuRef.current.contains(t)) {
        setDefSnapshotMenuOpen(false);
      }
      if (configSnapshotMenuOpen && configSnapshotMenuRef.current && !configSnapshotMenuRef.current.contains(t)) {
        setConfigSnapshotMenuOpen(false);
      }
      if (defMoreMenuOpen && defMoreMenuRef.current && !defMoreMenuRef.current.contains(t)) {
        setDefMoreMenuOpen(false);
      }
    };
    if (!defSnapshotMenuOpen && !configSnapshotMenuOpen && !defMoreMenuOpen) return;
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [defSnapshotMenuOpen, configSnapshotMenuOpen, defMoreMenuOpen]);

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
    onActiveTabChange?.(activeTab);
  }, [activeTab, onActiveTabChange]);

  useEffect(() => {
    if (tabSwitchNonce === undefined || !tabSwitchTarget) return;
    setActiveTab(tabSwitchTarget);
    if (tabSwitchTarget === "definition") setDefinitionUnread(false);
    if (tabSwitchTarget === "config") setConfigUnread(false);
    // Watch nonce only; the same target with a fresh nonce should re-fire.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabSwitchNonce]);

  useEffect(() => {
    if (activeTab !== "definition" || !pendingDefinitionOpenQuestionsScroll) return;
    const target = document.getElementById("definition-open-questions");
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setPendingDefinitionOpenQuestionsScroll(false);
  }, [activeTab, pendingDefinitionOpenQuestionsScroll]);

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

  const definitionCleanupEnabled = !sessionTerminated && !busy && invokeModel;
  const definitionCleanupDisabledTitle = sessionTerminated
    ? "Session has ended."
    : busy
      ? "Wait for the current action to finish."
      : !invokeModel
        ? "Turn on Ask model (requires API key) to clean up with the assistant."
        : undefined;

  const definitionEditing = editMode === "definition";
  const configEditing = editMode === "config";
  const editableDefinition = definitionEditing && !sessionTerminated;
  const editableConfig = configEditing && !sessionTerminated;
  const tabLocked = editMode !== "none";

  const backgroundProcessingPending =
    backgroundBriefPending || backgroundConfigPending || syncingProblemConfig;

  useEffect(() => {
    if (!backgroundProcessingPending || configEditing || definitionEditing) {
      setForceUnlockProcessingUi(false);
      setProcessingStallWarn(false);
      return;
    }
    const timer = window.setTimeout(() => {
      setForceUnlockProcessingUi(true);
      setProcessingStallWarn(true);
    }, PROCESSING_UI_UNLOCK_MS);
    return () => window.clearTimeout(timer);
  }, [backgroundProcessingPending, configEditing, definitionEditing]);

  const configBlockingUi = activeTab === "config" && !configEditing && backgroundProcessingPending && !forceUnlockProcessingUi;

  const configSurfaceLocked =
    activeTab === "config" &&
    backgroundProcessingPending &&
    !forceUnlockProcessingUi &&
    !configEditing;

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

  /** Waterfall: show even when researcher permit allows runs (optimization_allowed). */
  const waterfallOpenQuestionsAlert = useMemo(() => {
    if (!session || session.workflow_mode !== "waterfall" || !problemBrief) return null;
    if (!problemBrief.open_questions.some((q) => q.status === "open")) return null;
    return "Answer all open questions before optimization can run.";
  }, [problemBrief, session]);

  /** Waterfall: cold start before first chat or any open questions in the brief. */
  const waterfallClarifyAlert = useMemo(() => {
    if (!session || session.workflow_mode !== "waterfall" || !problemBrief) return null;
    if (session.optimization_gate_engaged) return null;
    if (session.optimization_allowed) return null;
    return "Start in chat (or wait until open questions appear in the definition) before optimization can run.";
  }, [problemBrief, session]);

  const definitionSaveInFlight = clientOps.savingDefinition;
  const configSyncInFlight = clientOps.syncingConfig || syncingProblemConfig;
  const processingSpinnerActive = backgroundProcessingPending && !forceUnlockProcessingUi;
  const definitionSaveShieldActive = definitionEditing && definitionSaveInFlight;
  const canSyncToConfig =
    !busy &&
    editMode === "none" &&
    !sessionTerminated &&
    Boolean(problemBrief) &&
    !backgroundProcessingPending &&
    !configSyncInFlight;

  return (
    <section className={className}>
      <div className="panel-header panel-header-with-action">
        <div>
          Problem setup
          {(configEditing || definitionEditing) && (
            <span className="panel-editing-indicator"> - Editing...</span>
          )}
          {!definitionEditing && !configEditing && processingSpinnerActive && (
            <span className="muted" style={{ display: "inline-flex", alignItems: "center", marginLeft: "0.5rem" }}>
              <span className="inline-spinner" aria-hidden="true" />
            </span>
          )}
        </div>
        <button
          type="button"
          className="panel-header-raw-json-btn"
          onClick={() => setShowRawJsonDialog(true)}
          aria-label="Show raw problem setup JSON"
        >
          raw json
        </button>
      </div>
      <div className="panel-body">
        {waterfallOpenQuestionsAlert ? (
          <StatusBanner
            tone="warning"
            actionLabel="Scroll to open questions"
            onAction={() => {
              setPendingDefinitionOpenQuestionsScroll(true);
              setActiveTab("definition");
              setDefinitionUnread(false);
            }}
          >
            {waterfallOpenQuestionsAlert}
          </StatusBanner>
        ) : null}
        {waterfallClarifyAlert ? (
          <StatusBanner tone="warning">{waterfallClarifyAlert}</StatusBanner>
        ) : null}
        {backgroundProcessingError ? (() => {
          const isGoalTermValidation = backgroundProcessingError.startsWith("goal_term_validation:");
          const message = isGoalTermValidation
            ? "Problem Config is out of sync with the Definition (the goal-term keys don't match). Click Recover to clear the conflicting goal terms and re-derive a clean Problem Config from your Definition."
            : `Background update issue: ${backgroundProcessingError}`;
          return (
            <StatusBanner
              tone="error"
              actionLabel={isGoalTermValidation && onRecoverGoalTerms ? "Recover" : undefined}
              onAction={isGoalTermValidation && onRecoverGoalTerms ? () => void onRecoverGoalTerms() : undefined}
            >
              {message}
            </StatusBanner>
          );
        })() : null}
        <div className="tabs">
          {([
            ["definition", "Definition"],
            ["config", "Problem Config"],
          ] as Array<[PanelTab, string]>).map(([tabId, label]) => (
            <button
              key={tabId}
              type="button"
              className={`tab ${activeTab === tabId ? "active" : ""} ${
                (tabId === "definition" && definitionUnread && !backgroundBriefPending) ||
                (tabId === "config" && configUnread && !backgroundConfigPending && !configSyncInFlight)
                  ? "tab-has-update"
                  : ""
              }`}
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
                onUserTabClick?.(tabId);
              }}
              data-tutorial-anchor={tabId === "definition" ? "definition-tab" : tabId === "config" ? "config-tab" : undefined}
              disabled={tabLocked && activeTab !== tabId}
            >
              {label}
              {tabId === "definition" && backgroundBriefPending && !forceUnlockProcessingUi ? (
                <span className="inline-spinner" aria-hidden="true" style={{ marginLeft: "0.35rem" }} />
              ) : null}
              {tabId === "config" && (backgroundConfigPending || configSyncInFlight) && !forceUnlockProcessingUi ? (
                <span className="inline-spinner" aria-hidden="true" style={{ marginLeft: "0.35rem" }} />
              ) : null}
              {tabId === "definition" && definitionUnread && !backgroundBriefPending ? (
                <span title="Updated" aria-hidden="true" className="tab-update-dot" />
              ) : null}
              {tabId === "config" && configUnread && !backgroundConfigPending && !configSyncInFlight ? (
                <span title="Updated" aria-hidden="true" className="tab-update-dot" />
              ) : null}
            </button>
          ))}
        </div>

        {processingStallWarn && backgroundProcessingPending && !configEditing && !definitionEditing && (
          <p className="muted" style={{ margin: "0.35rem 0 0" }}>
            Background update is taking longer than expected. The config area was unlocked so you can keep working;
            try refreshing or sync again if something looks stale.
          </p>
        )}

        <div className="config-panel-scroll-wrapper">
          <div className="config-panel-scroll">
            {activeTab === "definition" ? (
              problemBrief ? (
                <DefinitionPanel
                  problemBrief={problemBrief}
                  editable={editableDefinition}
                  sessionTerminated={sessionTerminated}
                  workflowMode={session?.workflow_mode ?? null}
                  openQuestionsBusy={clientOps.cleaningOpenQuestions}
                  processingOqIds={clientOps.processingOqIds}
                  suppressTransientMarkers={definitionSaveShieldActive || configBlockingUi}
                  onChange={(b) => onProblemBriefChange(b)}
                  onEnsureDefinitionEditing={onEnsureDefinitionEditing}
                />
              ) : (
                <p className="muted" style={{ fontSize: "0.85rem", padding: "0.35rem 0" }}>
                  Loading problem definition...
                </p>
              )
            ) : activeTab === "config" ? (
              <ProblemConfigBlocks
                configJson={configText}
                onChange={onConfigTextChange}
                editable={editableConfig}
                onInteractionStart={onEnterConfigEdit}
                problemMeta={testProblemMeta}
                runs={runs}
                messages={messages}
              />
            ) : null}
          </div>
          {definitionSaveShieldActive || configBlockingUi ? (
            <div className="config-panel-processing-shield" aria-live="polite">
              <span className="inline-spinner" aria-hidden="true" />
              <span className="muted">
                {definitionSaveShieldActive
                  ? "Saving problem definition…"
                  : "Updating problem config from the latest definition…"}
              </span>
            </div>
          ) : null}
        </div>

        <div className="config-panel-actions">
          {activeTab === "definition" ? (
            definitionEditing ? (
              <>
                <button
                  type="button"
                  className={isDefinitionDirty ? "btn-save-attention" : undefined}
                  onClick={() => void onSaveDefinitionEdit()}
                  data-tutorial-anchor="definition-save"
                  disabled={busy || sessionTerminated || !problemBrief || !isDefinitionDirty}
                  title="Save definition and notify the assistant"
                >
                  Save
                </button>
                <button type="button" onClick={onCancelDefinitionEdit} disabled={busy || sessionTerminated}>
                  Cancel
                </button>
              </>
            ) : (
              <>
                <div ref={defSnapshotMenuRef} style={{ position: "relative" }}>
                  <button
                    type="button"
                    onClick={() => setDefSnapshotMenuOpen((o) => !o)}
                    disabled={sessionTerminated}
                    title="Save or restore a previous problem setup"
                    aria-expanded={defSnapshotMenuOpen}
                    aria-haspopup="menu"
                  >
                    Snapshot <span aria-hidden="true">{defSnapshotMenuOpen ? "▼" : "▲"}</span>
                  </button>
                  {defSnapshotMenuOpen && (
                    <div className="config-load-dropup" role="menu" style={dropUpMenuStyle}>
                      <button
                        type="button"
                        role="menuitem"
                        disabled={sessionTerminated || busy || !onBookmarkSnapshot}
                        onClick={() => {
                          void onBookmarkSnapshot?.();
                          setDefSnapshotMenuOpen(false);
                        }}
                        style={menuItemStyle}
                      >
                        Save to snapshot
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        disabled={!canLoadFromLastRun || sessionTerminated}
                        onClick={() => {
                          onLoadConfigFromLastRun?.();
                          setDefSnapshotMenuOpen(false);
                        }}
                        style={menuItemStyle}
                      >
                        From most recent run
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        disabled={!canLoadFromSnapshot || sessionTerminated}
                        onClick={() => {
                          openSnapshotDialog("definition");
                          setDefSnapshotMenuOpen(false);
                        }}
                        style={menuItemStyle}
                      >
                        Load from snapshot…
                      </button>
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => void onSyncProblemConfig()}
                  disabled={!canSyncToConfig}
                  title="Rebuild the saved problem config from the saved definition"
                >
                  {configSyncInFlight ? (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
                      <span className="inline-spinner" aria-hidden="true" />
                      Syncing...
                    </span>
                  ) : (
                    "Sync to config"
                  )}
                </button>
                <div ref={defMoreMenuRef} style={{ position: "relative" }}>
                  <button
                    type="button"
                    onClick={() => setDefMoreMenuOpen((o) => !o)}
                    disabled={sessionTerminated}
                    aria-expanded={defMoreMenuOpen}
                    aria-haspopup="menu"
                    aria-label="More definition actions"
                    title="More definition actions"
                  >
                    ⋯ <span aria-hidden="true">{defMoreMenuOpen ? "▼" : "▲"}</span>
                  </button>
                  {defMoreMenuOpen ? (
                    <div className="config-load-dropup" role="menu" style={dropUpMenuStyle}>
                      <button
                        type="button"
                        role="menuitem"
                        disabled={!definitionCleanupEnabled}
                        title={
                          definitionCleanupEnabled
                            ? "Ask the assistant to consolidate and deduplicate this definition."
                            : definitionCleanupDisabledTitle
                        }
                        onClick={() => {
                          setDefMoreMenuOpen(false);
                          void onRequestDefinitionCleanup();
                        }}
                        style={menuItemStyle}
                      >
                        Clean up definition
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        disabled={!definitionCleanupEnabled || clientOps.cleaningOpenQuestions}
                        title={
                          definitionCleanupEnabled
                            ? "Clean only the open-questions list by removing resolved or duplicate questions."
                            : definitionCleanupDisabledTitle
                        }
                        onClick={() => {
                          setDefMoreMenuOpen(false);
                          void onRequestOpenQuestionCleanup();
                        }}
                        style={menuItemStyle}
                      >
                        {clientOps.cleaningOpenQuestions ? "Cleaning open questions..." : "Clean up open questions"}
                      </button>
                    </div>
                  ) : null}
                </div>
              </>
            )
          ) : activeTab === "config" ? (
            configEditing ? (
              <>
                <button
                  type="button"
                  className={isConfigDirty ? "btn-save-attention" : undefined}
                  onClick={() => void onSaveConfig()}
                  data-tutorial-anchor="config-save"
                  disabled={busy || sessionTerminated || !isConfigDirty}
                >
                  Save
                </button>
                <button
                  type="button"
                  onClick={() => (onCancelConfigEdit ? onCancelConfigEdit() : onSetEditMode("none"))}
                  disabled={busy || sessionTerminated}
                >
                  Cancel
                </button>
              </>
            ) : (
              <div ref={configSnapshotMenuRef} style={{ position: "relative" }}>
                <button
                  type="button"
                  onClick={() => setConfigSnapshotMenuOpen((o) => !o)}
                  disabled={sessionTerminated || configSurfaceLocked}
                  title={configSurfaceLocked ? "Wait for background config update" : "Save or restore a previous problem setup"}
                  aria-expanded={configSnapshotMenuOpen}
                  aria-haspopup="menu"
                >
                  Snapshot <span aria-hidden="true">{configSnapshotMenuOpen ? "▼" : "▲"}</span>
                </button>
                {configSnapshotMenuOpen && (
                  <div className="config-load-dropup" role="menu" style={dropUpMenuStyle}>
                    <button
                      type="button"
                      role="menuitem"
                      disabled={sessionTerminated || busy || !onBookmarkSnapshot}
                      onClick={() => {
                        void onBookmarkSnapshot?.();
                        setConfigSnapshotMenuOpen(false);
                      }}
                      style={menuItemStyle}
                    >
                      Save to snapshot
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      disabled={!canLoadFromLastRun || sessionTerminated || configSurfaceLocked}
                      onClick={() => {
                        onLoadConfigFromLastRun?.();
                        setConfigSnapshotMenuOpen(false);
                      }}
                      style={menuItemStyle}
                    >
                      From most recent run
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      disabled={!canLoadFromSnapshot || sessionTerminated}
                      onClick={() => {
                        openSnapshotDialog("config");
                        setConfigSnapshotMenuOpen(false);
                      }}
                      style={menuItemStyle}
                    >
                      Load from snapshot…
                    </button>
                  </div>
                )}
              </div>
            )
          ) : null}
        </div>
      </div>

      <RawJsonDialog
        open={showRawJsonDialog}
        title="Raw problem setup JSON"
        helperText="Raw JSON is read-only. Edit Definition or Problem Config to make changes."
        jsonText={rawJsonText}
        onClose={() => setShowRawJsonDialog(false)}
      />

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
