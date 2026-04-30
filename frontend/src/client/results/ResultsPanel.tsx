import { useEffect, useRef, useState } from "react";

import { displayRunNumber, type ProblemBrief, type RunResult, type Session, type TestProblemMeta } from "@shared/api";

import type { EditMode } from "../lib/participantTypes";
import { computeCanRunOptimization, runOptimizationDisabledHint } from "../lib/optimizationGate";
import { ConvergencePlot } from "./ConvergencePlot";
import { getProblemModule } from "../problemRegistry";
import { RawJsonDialog } from "../components/RawJsonDialog";

function normalizeRoutesForCompare(raw: unknown): number[][] | null {
  if (!Array.isArray(raw)) return null;
  const out: number[][] = [];
  for (const row of raw) {
    if (!Array.isArray(row)) return null;
    const parsedRow: number[] = [];
    for (const v of row) {
      const n = Number(v);
      if (!Number.isFinite(n)) return null;
      parsedRow.push(n);
    }
    out.push(parsedRow);
  }
  return out;
}

function routesTextEqual(aText: string, bText: string): boolean {
  try {
    const a = normalizeRoutesForCompare(JSON.parse(aText));
    const b = normalizeRoutesForCompare(JSON.parse(bText));
    if (!a || !b) return false;
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}

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
  hasUploadedData: boolean;
  problemMeta?: TestProblemMeta | null;
  sessionTerminated: boolean;
  className: string;
  onSetActiveRun: (index: number) => void;
  onScheduleTextChange: (value: string) => void;
  onSetEditMode: (mode: EditMode) => void;
  onRunOptimize: () => void | Promise<void>;
  onCancelOptimize: () => void | Promise<void>;
  onRunEvaluateEdited: () => void | Promise<void>;
  onRevertEditedRun: (run: RunResult) => void | Promise<void>;
  onExplainRun: (run: RunResult) => void | Promise<void>;
  onLoadConfigFromRun: (run: RunResult) => void | Promise<void>;
  candidateRunIds: number[];
  onToggleCandidateRun: (runId: number, checked: boolean) => void;
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
  hasUploadedData,
  problemMeta,
  sessionTerminated,
  className,
  onSetActiveRun,
  onScheduleTextChange,
  onSetEditMode,
  onRunOptimize,
  onCancelOptimize,
  onRunEvaluateEdited,
  onRevertEditedRun,
  onExplainRun,
  onLoadConfigFromRun,
  candidateRunIds,
  onToggleCandidateRun,
}: ResultsPanelProps) {
  const canRunOptimization = computeCanRunOptimization(session, configText, problemBrief, hasUploadedData, problemMeta);
  const runDisabledHint = runOptimizationDisabledHint(session, configText, problemBrief, hasUploadedData, problemMeta);
  const [showRawJsonDialog, setShowRawJsonDialog] = useState(false);
  const [vizTabId, setVizTabId] = useState<string>("__convergence__");
  const [unreadRunIndex, setUnreadRunIndex] = useState<number | null>(null);
  const prevRunsLenRef = useRef<number | null>(null);

  const currentResult = currentRun?.result ?? null;
  const runProblem = (currentRun?.request?.problem ?? {}) as Record<string, unknown>;
  const runAlgorithm =
    typeof runProblem.algorithm === "string"
      ? runProblem.algorithm
      : typeof currentResult?.algorithm === "string"
        ? currentResult.algorithm
        : null;
  const hasResult = currentResult !== null;
  const showOptimizeProgress = optimizing || Boolean(currentRun?.clientPending);
  const convergence = currentResult?.convergence ?? [];
  const runtimeSeconds =
    typeof currentResult?.runtime_seconds === "number" && Number.isFinite(currentResult.runtime_seconds)
      ? currentResult.runtime_seconds
      : null;

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
  const originalSnapshot = (currentResult as Record<string, unknown> | null)?.original_snapshot as
    | Record<string, unknown>
    | undefined;
  const originalSnapshotResult =
    originalSnapshot && typeof originalSnapshot.result === "object" && originalSnapshot.result !== null
      ? (originalSnapshot.result as Record<string, unknown>)
      : null;
  const originalSchedule =
    originalSnapshotResult && typeof originalSnapshotResult.schedule === "object" && originalSnapshotResult.schedule !== null
      ? (originalSnapshotResult.schedule as Record<string, unknown>)
      : null;
  const originalBaseRoutes = normalizeRoutesForCompare(originalSchedule?.routes ?? null);
  const currentRoutes = normalizeRoutesForCompare((currentResult?.schedule as { routes?: unknown } | undefined)?.routes ?? null);
  const editorBaseRoutes = originalBaseRoutes ?? currentRoutes;
  const editorBaseText = editorBaseRoutes ? JSON.stringify(editorBaseRoutes, null, 2) : "";
  const isScheduleDirty = editMode === "results" && editorBaseText !== "" && !routesTextEqual(scheduleText, editorBaseText);
  const canSaveSchedule = Boolean(!sessionTerminated && scheduleText.trim().length > 0);

  return (
    <section className={className}>
      <div className="panel-header panel-header-with-action">
        <div>
          Results &amp; visualization
          {editMode === "results" && <span className="muted"> - editing</span>}
        </div>
        <button
          type="button"
          className="panel-header-raw-json-btn"
          onClick={() => setShowRawJsonDialog(true)}
          aria-label="Show raw results JSON"
        >
          raw json
        </button>
      </div>
      <div className="panel-body">
        <div className="tabs">
          {runs.map((run, index) => {
            const unreadHere = unreadRunIndex === index && index !== activeRun;
            const selectedAsCandidate = candidateRunIds.includes(run.id);
            const isEditedRun = Boolean(run.result && typeof run.result === "object" && "edited_evaluation" in run.result);
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
                {isEditedRun ? <span className="tab-candidate-badge" title="Edited schedule result">Edited</span> : null}
                {selectedAsCandidate ? <span className="tab-candidate-badge" title="Included as candidate for next optimization">Candidate</span> : null}
                {unreadHere ? <span title="New results" aria-hidden="true" className="tab-update-dot" /> : null}
              </button>
            );
          })}
        </div>

        {showOptimizeProgress ? <div className="opt-progress-bar" /> : null}

        {currentRun && !showOptimizeProgress && (
          <div className="muted" style={{ display: "flex", alignItems: "center", gap: "0.45rem", flexWrap: "wrap" }}>
            <span>
              cost: {currentRun.cost ?? "-"} · {currentRun.ok ? "ok" : currentRun.error_message}
            </span>
            <button
              type="button"
              className="result-top-action-btn"
              disabled={busy || sessionTerminated}
              title="Explain more about this result"
              onClick={() => void onExplainRun(currentRun)}
            >
              Explain
            </button>
            <button
              type="button"
              className="result-top-action-btn"
              disabled={busy || sessionTerminated}
              title="Revert to this config"
              onClick={() => void onLoadConfigFromRun(currentRun)}
            >
              Use This Config
            </button>
            <label
              className={`result-top-action-btn result-top-action-checkbox ${candidateRunIds.includes(currentRun.id) ? "checked" : ""}`}
            >
              <input
                type="checkbox"
                checked={candidateRunIds.includes(currentRun.id)}
                onChange={(e) => onToggleCandidateRun(currentRun.id, e.target.checked)}
                disabled={busy || sessionTerminated || !currentRun.ok}
              />
              Include as candidate
            </label>
          </div>
        )}
        {currentRun && !showOptimizeProgress && (
          <div className="muted" style={{ marginTop: "0.2rem" }}>
            algorithm: {runAlgorithm ?? "not captured in this run snapshot"} · runtime:{" "}
            {runtimeSeconds !== null ? `${runtimeSeconds.toFixed(1)}s` : "not captured in this run snapshot"}
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

        <div
          className="results-panel-actions"
          style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", alignItems: "flex-end" }}
        >
          <div className="run-optimize-stack">
            <span className="muted" title="Number of prior runs included as candidates for the next optimization">
              Candidates: {candidateRunIds.length}
            </span>
            <button
              type="button"
              className="btn-primary results-main-action-btn"
              data-tutorial-anchor="run-optimize"
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
          </div>
          <button
            type="button"
            className="results-main-action-btn"
            disabled={!showOptimizeProgress || sessionTerminated}
            onClick={() => void onCancelOptimize()}
            title="Ask the server to stop the current optimization early"
          >
            Cancel run
          </button>
          {editMode !== "results" ? (
            <button
              type="button"
              className="results-main-action-btn"
              onClick={() => onSetEditMode("results")}
              disabled={!hasResult || editMode !== "none" || sessionTerminated}
            >
              Edit
            </button>
          ) : (
            <>
              <button
                type="button"
                className={isScheduleDirty ? "btn-save-attention" : undefined}
                disabled={!canSaveSchedule}
                onClick={() => void onRunEvaluateEdited()}
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => {
                  if (currentRun) void onRevertEditedRun(currentRun);
                }}
              >
                Revert
              </button>
              <button
                type="button"
                onClick={() => {
                  if (editorBaseRoutes) onScheduleTextChange(JSON.stringify(editorBaseRoutes, null, 2));
                  onSetEditMode("none");
                }}
              >
                Cancel
              </button>
            </>
          )}
        </div>
      </div>
      <RawJsonDialog
        open={showRawJsonDialog}
        title="Raw result JSON"
        helperText="Raw result fields are read-only."
        jsonText={JSON.stringify(
          {
            schedule: currentResult?.schedule ?? null,
            violations: currentResult?.violations ?? null,
          },
          null,
          2,
        )}
        onClose={() => setShowRawJsonDialog(false)}
      />
    </section>
  );
}
