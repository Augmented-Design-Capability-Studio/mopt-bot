import { useEffect, useMemo, useState } from "react";

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
  sessionTerminated: boolean;
  className: string;
  onConfigTextChange: (value: string) => void;
  onProblemBriefChange: (value: ProblemBrief | null) => void;
  onSetEditMode: (mode: EditMode) => void;
  onSaveConfig: () => void | Promise<void>;
  onSaveProblemBrief: () => void | Promise<void>;
  onSyncProblemConfig: () => void | Promise<void>;
};

type PanelTab = "definition" | "config" | "raw";

export function ConfigPanel({
  configText,
  problemBrief,
  editMode,
  busy,
  syncingProblemConfig,
  sessionTerminated,
  className,
  onConfigTextChange,
  onProblemBriefChange,
  onSetEditMode,
  onSaveConfig,
  onSaveProblemBrief,
  onSyncProblemConfig,
}: ConfigPanelProps) {
  const [activeTab, setActiveTab] = useState<PanelTab>("definition");

  useEffect(() => {
    if (editMode === "config" && activeTab !== "config") setActiveTab("config");
    if (editMode === "definition" && activeTab !== "definition") setActiveTab("definition");
  }, [activeTab, editMode]);

  const definitionEditing = editMode === "definition";
  const configEditing = editMode === "config";
  const editableDefinition = definitionEditing && !sessionTerminated;
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
        {(definitionEditing || configEditing) && <span className="muted"> - editing {tabTitle.toLowerCase()}</span>}
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
            </button>
          ))}
        </div>

        <div className="config-panel-scroll">
          {activeTab === "definition" ? (
            problemBrief ? (
              <DefinitionPanel
                problemBrief={problemBrief}
                editable={editableDefinition}
                sessionTerminated={sessionTerminated}
                onChange={onProblemBriefChange}
              />
            ) : (
              <p className="muted" style={{ fontSize: "0.85rem", padding: "0.35rem 0" }}>
                Loading problem definition...
              </p>
            )
          ) : activeTab === "config" ? (
            <ProblemConfigBlocks configJson={configText} onChange={onConfigTextChange} editable={editableConfig} />
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
            !definitionEditing ? (
              <>
                <button
                  type="button"
                  onClick={() => onSetEditMode("definition")}
                  disabled={editMode !== "none" || sessionTerminated || !problemBrief}
                >
                  Edit definition
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
                {syncingProblemConfig && (
                  <span className="muted">Rebuilding config from definition (may use model derivation)...</span>
                )}
              </>
            ) : (
              <>
                <button type="button" onClick={() => void onSaveProblemBrief()} disabled={busy || sessionTerminated}>
                  Save
                </button>
                <button type="button" onClick={() => onSetEditMode("none")}>
                  Cancel
                </button>
              </>
            )
          ) : activeTab === "config" ? !configEditing ? (
            <button
              type="button"
              onClick={() => onSetEditMode("config")}
              disabled={editMode !== "none" || sessionTerminated}
            >
              Edit
            </button>
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
