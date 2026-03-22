import { useState } from "react";

import { displayRunNumber, type RunResult, type Session } from "@shared/api";

import type { EditMode } from "../lib/participantTypes";
import { parseActiveWeightKeys } from "../problemConfig/serialization";
import { RunTimeline } from "./RunTimeline";
import { ViolationSummary } from "./ViolationSummary";

type ResultsPanelProps = {
  runs: RunResult[];
  activeRun: number;
  currentRun?: RunResult;
  scheduleText: string;
  editMode: EditMode;
  busy: boolean;
  optimizing: boolean;
  configText: string;
  session: Session | null;
  sessionTerminated: boolean;
  className: string;
  onSetActiveRun: (index: number) => void;
  onScheduleTextChange: (value: string) => void;
  onSetEditMode: (mode: EditMode) => void;
  onRunOptimize: () => void | Promise<void>;
  onRunEvaluateEdited: () => void | Promise<void>;
};

export function ResultsPanel({
  runs,
  activeRun,
  currentRun,
  scheduleText,
  editMode,
  busy,
  optimizing,
  configText,
  session,
  sessionTerminated,
  className,
  onSetActiveRun,
  onScheduleTextChange,
  onSetEditMode,
  onRunOptimize,
  onRunEvaluateEdited,
}: ResultsPanelProps) {
  const activeWeightKeys = parseActiveWeightKeys(configText);
  const [showRaw, setShowRaw] = useState(false);

  return (
    <section className={className}>
      <div className="panel-header">
        Results &amp; schedule
        {editMode === "results" && <span className="muted"> - editing</span>}
      </div>
      <div className="panel-body">
        <div className="tabs">
          {runs.map((run, index) => (
            <button
              key={run.id}
              type="button"
              className={`tab ${index === activeRun ? "active" : ""}`}
              onClick={() => onSetActiveRun(index)}
            >
              Run #{displayRunNumber(run, index)} {run.ok ? "" : "✗"}
            </button>
          ))}
          {optimizing && (
            <button
              type="button"
              className="tab active"
              disabled
              style={{ display: "flex", alignItems: "center", gap: "0.35rem", opacity: 1 }}
            >
              <span className="chat-spinner" style={{ width: "0.7rem", height: "0.7rem", borderWidth: "2px" }} />
              Running...
            </button>
          )}
        </div>

        {optimizing && <div className="opt-progress-bar" />}

        {currentRun && !optimizing && (
          <div
            className="mono muted"
            style={{ display: "flex", alignItems: "center", gap: "0.45rem", flexWrap: "wrap" }}
          >
            <span>
              cost: {currentRun.cost ?? "-"} · {currentRun.ok ? "ok" : currentRun.error_message}
            </span>
            <button
              type="button"
              disabled={busy || sessionTerminated || !scheduleText.trim()}
              onClick={() => void onRunEvaluateEdited()}
            >
              Recalculate cost
            </button>
          </div>
        )}

        {editMode === "results" ? (
          <textarea
            className="mono"
            style={{ flex: 1, minHeight: "10rem", width: "100%" }}
            value={scheduleText}
            onChange={(e) => onScheduleTextChange(e.target.value)}
            disabled={sessionTerminated}
            spellCheck={false}
            placeholder="Run optimization to populate routes, or paste JSON once a problem configuration exists."
          />
        ) : optimizing ? (
          <div className="muted" style={{ fontSize: "0.85rem", paddingTop: "0.25rem" }}>
            Optimization in progress - the solver is searching for a good solution...
          </div>
        ) : currentRun?.result ? (
          <div className="results-visualization-scroll">
            <ViolationSummary
              violations={currentRun.result.violations}
              metrics={currentRun.result.metrics}
              referenceCost={currentRun.reference_cost}
              runtimeSeconds={currentRun.result.runtime_seconds}
              activeWeightKeys={activeWeightKeys}
            />
            <RunTimeline schedule={currentRun.result.schedule} />
          </div>
        ) : (
          <div className="muted">Run optimization to populate a timeline view, or switch to edit mode to paste schedule JSON.</div>
        )}

        {currentRun?.result && editMode !== "results" && (
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
              {showRaw ? "Hide" : "Show"} raw schedule / violations JSON
            </summary>
            <pre className="mono run-json-preview" style={{ marginTop: "0.35rem" }}>
              {JSON.stringify(
                {
                  schedule: currentRun.result.schedule,
                  violations: currentRun.result.violations,
                },
                null,
                2,
              )}
            </pre>
          </details>
        )}

        <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
          <button
            type="button"
            disabled={busy || !session?.optimization_allowed || editMode !== "none" || sessionTerminated}
            onClick={() => void onRunOptimize()}
          >
            Run optimization
          </button>
          {editMode !== "results" ? (
            <button
              type="button"
              onClick={() => onSetEditMode("results")}
              disabled={editMode !== "none" || sessionTerminated}
            >
              Edit
            </button>
          ) : (
            <>
              <button type="button" disabled={busy || sessionTerminated} onClick={() => void onRunEvaluateEdited()}>
                Recalculate cost
              </button>
              <button type="button" onClick={() => onSetEditMode("none")}>
                Done editing
              </button>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
