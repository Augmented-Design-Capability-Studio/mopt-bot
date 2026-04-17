import { useEffect, useRef, useState } from "react";

import { displayRunNumber, type ProblemBrief, type RunResult, type Session, type TestProblemMeta } from "@shared/api";

import type { EditMode } from "../lib/participantTypes";
import { computeCanRunOptimization, runOptimizationDisabledHint } from "../lib/optimizationGate";
import { ConvergencePlot } from "./ConvergencePlot";
import { getProblemModule } from "../problemRegistry";

type ResultsPanelProps = {
  runs: RunResult[];
  activeRun: number;
  currentRun?: RunResult;
  scheduleText: string;
  editMode: EditMode;
  busy: boolean;
  optimizing: boolean;
  session: Session | null;
  configText: string;
  problemBrief: ProblemBrief | null;
  problemMeta?: TestProblemMeta | null;
  sessionTerminated: boolean;
  className: string;
  onSetActiveRun: (index: number) => void;
  onScheduleTextChange: (value: string) => void;
  onSetEditMode: (mode: EditMode) => void;
  onRunOptimize: () => void | Promise<void>;
  onCancelOptimize: () => void | Promise<void>;
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
  session,
  configText,
  problemBrief,
  problemMeta,
  sessionTerminated,
  className,
  onSetActiveRun,
  onScheduleTextChange,
  onSetEditMode,
  onRunOptimize,
  onCancelOptimize,
  onRunEvaluateEdited,
}: ResultsPanelProps) {
  const canRunOptimization = computeCanRunOptimization(session, configText, problemBrief, problemMeta);
  const runDisabledHint = runOptimizationDisabledHint(session, configText, problemBrief, problemMeta);
  const [showRaw, setShowRaw] = useState(false);
  const [vizTabId, setVizTabId] = useState<string>("__convergence__");
  const [unreadRunIndex, setUnreadRunIndex] = useState<number | null>(null);
  const prevRunsLenRef = useRef<number | null>(null);

  const currentResult = currentRun?.result ?? null;
  const runProblem = (currentRun?.request?.problem ?? {}) as Record<string, unknown>;
  const runWeights =
    runProblem.weights && typeof runProblem.weights === "object" && !Array.isArray(runProblem.weights)
      ? (runProblem.weights as Record<string, unknown>)
      : {};
  const runSoftConstraints = Array.isArray(runProblem.soft_constraints)
    ? runProblem.soft_constraints.map((entry) => String(entry))
    : [];
  const runHardConstraints = Array.isArray(runProblem.hard_constraints)
    ? runProblem.hard_constraints.map((entry) => String(entry))
    : [];
  const runAlgorithm =
    typeof runProblem.algorithm === "string"
      ? runProblem.algorithm
      : typeof currentResult?.algorithm === "string"
        ? currentResult.algorithm
        : null;
  const hasResult = currentResult !== null;
  const showOptimizeProgress = optimizing || Boolean(currentRun?.clientPending);
  const convergence = currentResult?.convergence ?? [];
  const runActiveWeightKeys = Object.keys(runWeights).filter((key) => Number.isFinite(Number(runWeights[key])));

  const problemId = (session?.test_problem_id ?? "").trim().toLowerCase();
  const mod = getProblemModule(problemId);

  // Default viz tab: first problem tab, or convergence if no problem tabs
  const defaultVizTab = mod.vizTabs[0]?.id ?? "__convergence__";

  useEffect(() => {
    setVizTabId(defaultVizTab);
  }, [activeRun, defaultVizTab]);

  useEffect(() => {
    const n = runs.length;
    if (prevRunsLenRef.current === null) {
      prevRunsLenRef.current = n;
      return;
    }
    if (n > prevRunsLenRef.current && n > 0) {
      const latest = n - 1;
      if (activeRun !== latest) {
        setUnreadRunIndex(latest);
      }
    }
    prevRunsLenRef.current = n;
  }, [runs.length, activeRun]);

  useEffect(() => {
    if (unreadRunIndex !== null && activeRun === unreadRunIndex) {
      setUnreadRunIndex(null);
    }
  }, [activeRun, unreadRunIndex]);

  const allVizTabs = [
    ...mod.vizTabs,
    ...(convergence.length > 0 ? [{ id: "__convergence__", label: "Convergence" }] : []),
  ];

  return (
    <section className={className}>
      <div className="panel-header">
        Results &amp; visualization
        {editMode === "results" && <span className="muted"> - editing</span>}
      </div>
      <div className="panel-body">
        <div className="tabs">
          {runs.map((run, index) => {
            const unreadHere = unreadRunIndex === index && index !== activeRun;
            return (
              <button
                key={run.clientPending ? `pending-${run.id}` : run.id}
                type="button"
                className={`tab ${index === activeRun ? "active" : ""} ${unreadHere ? "tab-has-update" : ""}`}
                onClick={() => onSetActiveRun(index)}
              >
                {run.clientPending ? (
                  <span className="chat-spinner" style={{ width: "0.7rem", height: "0.7rem", borderWidth: "2px" }} />
                ) : null}
                Run #{displayRunNumber(run, index)} {run.ok ? "" : "✗"}
                {unreadHere ? <span title="New results" aria-hidden="true" className="tab-update-dot" /> : null}
              </button>
            );
          })}
        </div>

        {showOptimizeProgress ? <div className="opt-progress-bar" /> : null}

        {currentRun && !showOptimizeProgress && (
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
            placeholder="Edit schedule JSON for this run."
          />
        ) : showOptimizeProgress ? (
          <div className="muted" style={{ fontSize: "0.85rem", paddingTop: "0.25rem" }}>
            Optimization in progress - the solver is searching for a good solution...
          </div>
        ) : hasResult ? (
          <div className="results-visualization-scroll">
            <div className="run-summary-grid">
              <div className="run-summary-card">
                <div className="muted">Algorithm</div>
                <div className="mono">{runAlgorithm ?? "not captured in this run snapshot"}</div>
              </div>
              <div className="run-summary-card">
                <div className="muted">Objective Weights</div>
                <div className="mono">
                  {runActiveWeightKeys.length > 0
                    ? runActiveWeightKeys.map((key) => `${key}: ${runWeights[key]}`).join(" · ")
                    : "not captured in this run snapshot"}
                </div>
              </div>
              <div className="run-summary-card">
                <div className="muted">Constraints</div>
                <div className="mono">
                  {[
                    runHardConstraints.length ? `hard: ${runHardConstraints.join(", ")}` : "",
                    runSoftConstraints.length ? `soft: ${runSoftConstraints.join(", ")}` : "",
                  ].filter(Boolean).join(" · ") || "not captured in this run snapshot"}
                </div>
              </div>
            </div>

            {mod.ViolationSummary && currentRun ? (
              <mod.ViolationSummary currentRun={currentRun} />
            ) : null}

            {allVizTabs.length > 1 && (
              <div className="tabs" style={{ marginTop: "0.6rem" }}>
                {allVizTabs.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    className={`tab ${vizTabId === tab.id ? "active" : ""}`}
                    onClick={() => setVizTabId(tab.id)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            )}

            {vizTabId === "__convergence__" && convergence.length > 0 ? (
              <ConvergencePlot convergence={convergence} referenceCost={currentRun?.reference_cost} />
            ) : currentRun ? (
              (() => {
                const tab = mod.vizTabs.find((t) => t.id === vizTabId) ?? mod.vizTabs[0];
                if (!tab) return null;
                const VizComponent = tab.component;
                return <VizComponent currentRun={currentRun} />;
              })()
            ) : null}
          </div>
        ) : (
          <div className="muted">Run optimization to populate a timeline view and schedule details.</div>
        )}

        {hasResult && editMode !== "results" && (
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
                  schedule: currentResult?.schedule,
                  violations: currentResult?.violations,
                },
                null,
                2,
              )}
            </pre>
          </details>
        )}

        <div className="results-panel-actions" style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
          <button
            type="button"
            className="btn-primary"
            disabled={busy || !canRunOptimization || editMode !== "none" || sessionTerminated}
            title={
              !canRunOptimization && !sessionTerminated && editMode === "none"
                ? runDisabledHint || "Cannot run optimization yet."
                : undefined
            }
            onClick={() => void onRunOptimize()}
          >
            Run optimization
          </button>
          <button
            type="button"
            disabled={!showOptimizeProgress || sessionTerminated}
            onClick={() => void onCancelOptimize()}
            title="Ask the server to stop the current optimization early"
          >
            Cancel run
          </button>
          {editMode !== "results" ? (
            <button
              type="button"
              onClick={() => onSetEditMode("results")}
              disabled={!hasResult || editMode !== "none" || sessionTerminated}
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
