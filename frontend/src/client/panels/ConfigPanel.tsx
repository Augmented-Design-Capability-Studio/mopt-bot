import { useState } from "react";

import type { EditMode } from "../participantTypes";
import { ProblemConfigBlocks } from "./ProblemConfigBlocks";

type ConfigPanelProps = {
  configText: string;
  editMode: EditMode;
  busy: boolean;
  sessionTerminated: boolean;
  className: string;
  onConfigTextChange: (value: string) => void;
  onSetEditMode: (mode: EditMode) => void;
  onSaveConfig: () => void | Promise<void>;
};

export function ConfigPanel({
  configText,
  editMode,
  busy,
  sessionTerminated,
  className,
  onConfigTextChange,
  onSetEditMode,
  onSaveConfig,
}: ConfigPanelProps) {
  const [showRaw, setShowRaw] = useState(false);

  const isEditing = editMode === "config";
  const isPanelLocked = editMode !== "none" && !isEditing;
  const editable = isEditing && !sessionTerminated;

  return (
    <section className={className}>
      <div className="panel-header">
        Problem configuration
        {isEditing && <span className="muted"> — editing</span>}
      </div>
      <div className="panel-body">
        {/* ── Natural-language form view ── */}
        <div style={{ flex: 1, overflowY: "auto", paddingRight: "0.1rem" }}>
          <ProblemConfigBlocks
            configJson={configText}
            onChange={onConfigTextChange}
            editable={editable}
          />
        </div>

        {/* ── Raw JSON toggle (collapsed by default) ── */}
        <details
          open={showRaw}
          onToggle={(e) => setShowRaw((e.currentTarget as HTMLDetailsElement).open)}
          style={{ marginTop: "0.6rem" }}
          className="muted"
        >
          <summary
            style={{
              cursor: "pointer",
              fontSize: "0.78rem",
              userSelect: "none",
            }}
          >
            {showRaw ? "Hide" : "Show"} raw JSON
          </summary>
          <textarea
            className="mono"
            style={{
              width: "100%",
              minHeight: "8rem",
              marginTop: "0.35rem",
              fontSize: "0.8rem",
              resize: "vertical",
            }}
            value={configText}
            onChange={(e) => onConfigTextChange(e.target.value)}
            readOnly={!editable}
            disabled={sessionTerminated || isPanelLocked}
            spellCheck={false}
            placeholder="{}"
          />
        </details>

        {/* ── Action buttons ── */}
        <div
          style={{
            display: "flex",
            gap: "0.35rem",
            flexWrap: "wrap",
            marginTop: "0.5rem",
          }}
        >
          {!isEditing ? (
            <button
              type="button"
              onClick={() => onSetEditMode("config")}
              disabled={editMode !== "none" || sessionTerminated}
            >
              Edit
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={() => void onSaveConfig()}
                disabled={busy || sessionTerminated}
              >
                Save
              </button>
              <button type="button" onClick={() => onSetEditMode("none")}>
                Cancel
              </button>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
