import { useEffect, useMemo, useRef, useState } from "react";

import type { ProblemBrief } from "@shared/api";

import type { EditMode } from "../lib/participantTypes";
import { DefinitionPanel } from "../problemDefinition/DefinitionPanel";
import { ProblemConfigBlocks } from "./ProblemConfigBlocks";

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
  onLoadConfigFromLastRun?: () => void;
  onLoadConfigFromPreviousEdit?: () => void;
  canLoadFromLastRun?: boolean;
  canLoadFromPreviousEdit?: boolean;
};

type PanelTab = "definition" | "config" | "raw";

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
  onLoadConfigFromLastRun,
  onLoadConfigFromPreviousEdit,
  canLoadFromLastRun = false,
  canLoadFromPreviousEdit = false,
}: ConfigPanelProps) {
  const [activeTab, setActiveTab] = useState<PanelTab>("definition");
  const [loadMenuOpen, setLoadMenuOpen] = useState(false);
  const loadMenuRef = useRef<HTMLDivElement>(null);

  const hasLoadOptions = canLoadFromLastRun || canLoadFromPreviousEdit;

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

  useEffect(() => {
    if (editMode === "config" && activeTab !== "config") setActiveTab("config");
    if (editMode === "definition" && activeTab !== "definition") setActiveTab("definition");
  }, [activeTab, editMode]);

  const definitionEditing = false;
  const configEditing = editMode === "config";
  const editableDefinition = !sessionTerminated;
  const editableConfig = configEditing && !sessionTerminated;
  const tabLocked = editMode !== "none";

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
              onClick={() => setActiveTab(tabId)}
              disabled={tabLocked && activeTab !== tabId}
            >
              {label}
              {tabId === "definition" && backgroundBriefPending ? (
                <span className="inline-spinner" aria-hidden="true" style={{ marginLeft: "0.35rem" }} />
              ) : null}
              {tabId === "config" && (backgroundConfigPending || syncingProblemConfig) ? (
                <span className="inline-spinner" aria-hidden="true" style={{ marginLeft: "0.35rem" }} />
              ) : null}
            </button>
          ))}
        </div>

        {backgroundProcessingError && !definitionEditing && !configEditing && (
          <p className="muted" style={{ margin: "0.35rem 0 0" }}>
            Background update issue: {backgroundProcessingError}
          </p>
        )}

        <div className="config-panel-scroll">
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
        </div>

        <div className="config-panel-actions">
          {activeTab === "definition" ? (
            <>
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
                disabled={editMode !== "none" || sessionTerminated}
              >
                Edit
              </button>
              {hasLoadOptions && onLoadConfigFromLastRun && onLoadConfigFromPreviousEdit && (
                <div ref={loadMenuRef} style={{ position: "relative" }}>
                  <button
                    type="button"
                    onClick={() => setLoadMenuOpen((o) => !o)}
                    disabled={sessionTerminated || (!canLoadFromLastRun && !canLoadFromPreviousEdit)}
                    title="Load config from previous run or edit"
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
                        disabled={!canLoadFromPreviousEdit || sessionTerminated}
                        onClick={() => {
                          onLoadConfigFromPreviousEdit();
                          setLoadMenuOpen(false);
                        }}
                        title="Restore config from the previous manual edit"
                        style={{ padding: "0.4rem 0.6rem", textAlign: "left", fontSize: "0.9rem" }}
                      >
                        From previous edit
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
              <button type="button" onClick={() => onSetEditMode("none")}>
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
    </section>
  );
}
