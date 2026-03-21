import { useState } from "react";

import { displayRunNumber, type RunResult, type Session } from "@shared/api";

import type { EditMode } from "../participantTypes";
import { RunTimeline } from "../results/RunTimeline";
import { ViolationSummary } from "../results/ViolationSummary";

/** Extract the keys present in problem.weights from a raw JSON string. */
function parseActiveWeightKeys(configJson: string): string[] {
  try {
    if (!configJson.trim()) return [];
    const parsed = JSON.parse(configJson) as Record<string, unknown>;
    const problem =
      parsed.problem !== null && typeof parsed.problem === "object"
        ? (parsed.problem as Record<string, unknown>)
        : parsed;
    const weights = problem.weights;
    if (weights !== null && typeof weights === "object" && !Array.isArray(weights)) {
      return Object.keys(weights as Record<string, unknown>);
    }
  } catch {
    /* invalid JSON */
  }
  return [];
}

type ResultsPanelProps = {
  runs: RunResult[];
  activeRun: number;
  currentRun?: RunResult;
  scheduleText: string;
  editMode: EditMode;
  busy: boolean;
  /** True while a run request is in-flight (solver is computing). */
  optimizing: boolean;
  /** Current problem configuration JSON — used to derive active weight keys. */
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
        {editMode === "results" && <span className="muted"> — editing</span>}
      </div>
      <div className="panel-body">
        {/* ── Run tabs ── */}
        <div className="tabs">
          {runs.map((r, i) => (
            <button
              key={r.id}
              type="button"
              className={`tab ${i === activeRun ? "active" : ""}`}
              onClick={() => onSetActiveRun(i)}
            >
              Run #{displayRunNumber(r, i)} {r.ok ? "" : "✗"}
            </button>
          ))}
          {optimizing && (
            <button
              type="button"
              className="tab active"
              disabled
              style={{ display: "flex", alignItems: "center", gap: "0.35rem", opacity: 1 }}
            >
              <span
                className="chat-spinner"
                style={{ width: "0.7rem", height: "0.7rem", borderWidth: "2px" }}
              />
              Running…
            </button>
          )}
        </div>

        {/* ── Indeterminate progress bar ── */}
        {optimizing && <div className="opt-progress-bar" />}

        {/* ── Cost line ── */}
        {currentRun && !optimizing && (
          <div
            className="mono muted"
            style={{ display: "flex", alignItems: "center", gap: "0.45rem", flexWrap: "wrap" }}
          >
            <span>
              cost: {currentRun.cost ?? "—"} · {currentRun.ok ? "ok" : currentRun.error_message}
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

        {/* ── Main body ── */}
        {editMode === "results" ? (
          <textarea
            className="mono"
            style={{ flex: 1, minHeight: "10rem", width: "100%" }}
            value={scheduleText}
            onChange={(e) => onScheduleTextChange(e.target.value)}
            readOnly={false}
            disabled={sessionTerminated}
            spellCheck={false}
            placeholder="Run optimization to populate routes, or paste JSON once a problem configuration exists."
          />
        ) : optimizing ? (
          <div className="muted" style={{ fontSize: "0.85rem", paddingTop: "0.25rem" }}>
            Optimization in progress — the solver is searching for a good solution…
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
          <div className="muted">
            Run optimization to populate a timeline view, or switch to edit
            mode to paste schedule JSON.
          </div>
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

        {/* ── Action buttons ── */}
        <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
          <button
            type="button"
            disabled={
              busy ||
              !session?.optimization_allowed ||
              editMode !== "none" ||
              sessionTerminated
            }
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
              <button
                type="button"
                disabled={busy || sessionTerminated}
                onClick={() => void onRunEvaluateEdited()}
              >
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
