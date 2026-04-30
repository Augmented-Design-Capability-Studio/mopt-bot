import {
  ALGORITHM_DESC,
  ALLOWED_ALGORITHM_PARAMS,
  ALGORITHM_PARAM_FIELD_META,
  DEFAULT_EPOCHS,
  DEFAULT_POP_SIZE,
  defaultParamsForAlgorithm,
} from "./algorithmCatalog";
import { FieldRow } from "./layout";
import type { BaseProblemBlock } from "./types";
import type { MarkerKind } from "./useProblemConfigDiffMarkers";
import { ConfigNumberInput, ConfigSelect, type ActivateHint } from "./controls";

type SearchStrategySectionProps = {
  problem: BaseProblemBlock;
  editable: boolean;
  markerKindFor: (key: string) => MarkerKind | null;
  updateProblem: (patch: Record<string, unknown>) => void;
  runEditingAction: (action: () => void, event?: ActivateHint) => void;
  ensureEditing: (event?: ActivateHint) => void;
};

export function SearchStrategySection({
  problem,
  editable,
  markerKindFor,
  updateProblem,
  runEditingAction,
  ensureEditing,
}: SearchStrategySectionProps) {
  function markerClassFor(key: string): string {
    const marker = markerKindFor(key);
    if (marker === "new") return "problem-config-control-external-mark--new";
    if (marker === "upd") return "problem-config-control-external-mark--upd";
    return "";
  }

  return (
    <>
      {problem.algorithm && (
        <FieldRow label="Algorithm">
          <ConfigSelect
            editable={editable}
            value={problem.algorithm}
            className={markerClassFor("field:algorithm")}
            displayLabel={problem.algorithm}
            onChange={(e) => {
              const nextAlgo = e.target.value;
              runEditingAction(() =>
                updateProblem({
                  algorithm: nextAlgo,
                  algorithm_params: defaultParamsForAlgorithm(nextAlgo),
                }),
              );
            }}
            onActivate={(hint) => ensureEditing(hint)}
            focusKey="search-algorithm"
            style={{ fontFamily: "monospace", fontSize: "0.85rem" }}
          >
            {["GA", "PSO", "SA", "SwarmSA", "ACOR"].map((algorithm) => (
              <option key={algorithm} value={algorithm}>
                {algorithm}
              </option>
            ))}
          </ConfigSelect>
          {ALGORITHM_DESC[problem.algorithm] && (
            <div className="muted" style={{ fontSize: "0.75rem", marginTop: "0.25rem" }}>
              {ALGORITHM_DESC[problem.algorithm]}
            </div>
          )}
        </FieldRow>
      )}

      {problem.algorithm && (
        <FieldRow label="Greedy initialization">
          <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            <ConfigSelect
              editable={editable}
              value={problem.use_greedy_init ? "1" : "0"}
              className={markerClassFor("field:use_greedy_init")}
              displayLabel={problem.use_greedy_init ? "On" : "Off"}
              onChange={(e) => runEditingAction(() => updateProblem({ use_greedy_init: e.target.value === "1" }))}
              onActivate={(hint) => ensureEditing(hint)}
              focusKey="greedy-init"
              style={{ fontFamily: "monospace", fontSize: "0.85rem", maxWidth: "8rem" }}
            >
              <option value="1">On</option>
              <option value="0">Off</option>
            </ConfigSelect>
            <span className="muted" style={{ fontSize: "0.72rem" }}>
              Seeds part of the initial population with time-window-aware solutions — much better than purely random starts. Recommended on.
            </span>
          </div>
        </FieldRow>
      )}

      {problem.algorithm &&
        (ALLOWED_ALGORITHM_PARAMS[problem.algorithm] ?? []).map((paramKey) => {
          const meta = ALGORITHM_PARAM_FIELD_META[problem.algorithm]?.[paramKey];
          const value = problem.algorithm_params[paramKey];
          const safe = typeof value === "number" && Number.isFinite(value) ? value : (meta?.min ?? 0);
          return (
            <FieldRow key={paramKey} label={meta?.label ?? paramKey}>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <ConfigNumberInput
                  editable={editable}
                  value={safe}
                  className={markerClassFor(`algo:${paramKey}`)}
                  min={meta?.min}
                  max={meta?.max}
                  step={meta?.step ?? 0.01}
                  onValueChange={(nextVal) => {
                    if (nextVal == null) return;
                    runEditingAction(() =>
                      updateProblem({
                        algorithm_params: {
                          ...problem.algorithm_params,
                          [paramKey]: nextVal,
                        },
                      }),
                    );
                  }}
                  onActivate={(hint) => ensureEditing(hint)}
                  focusKey={`algo-param-${paramKey}`}
                  style={{ width: "7rem", fontFamily: "monospace", fontSize: "0.85rem" }}
                />
                {meta?.description ? (
                  <span className="muted" style={{ fontSize: "0.72rem" }}>
                    {meta.description}
                  </span>
                ) : null}
              </div>
            </FieldRow>
          );
        })}

      {(problem.algorithm !== "" || problem.epochs !== null) && (
        <FieldRow label="Max iterations">
          <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <ConfigNumberInput
                editable={editable}
                value={problem.epochs ?? DEFAULT_EPOCHS}
                className={markerClassFor("field:epochs")}
                min={1}
                max={50000}
                onValueChange={(value) => {
                  if (value == null) return;
                  runEditingAction(() => updateProblem({ epochs: Math.max(1, Math.trunc(value)) }));
                }}
                onActivate={(hint) => ensureEditing(hint)}
                focusKey="epochs"
                style={{ width: "6rem", fontFamily: "monospace" }}
              />
              <span className="muted" style={{ fontSize: "0.75rem" }}>
                {(problem.epochs ?? DEFAULT_EPOCHS) < 100 ? "quick (may not fully converge)" : (problem.epochs ?? DEFAULT_EPOCHS) < 500 ? "moderate" : "thorough"}
              </span>
            </div>
            {problem.early_stop && (
              <span className="muted" style={{ fontSize: "0.72rem" }}>
                Ceiling only — search may stop earlier if the best score stops improving.
              </span>
            )}
          </div>
        </FieldRow>
      )}

      {(problem.algorithm || problem.epochs !== null) && (
        <FieldRow label="Stop early on plateau">
          <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            <ConfigSelect
              editable={editable}
              value={problem.early_stop ? "1" : "0"}
              className={markerClassFor("field:early_stop")}
              displayLabel={problem.early_stop ? "Yes" : "No (run all iterations)"}
              onChange={(e) => runEditingAction(() => updateProblem({ early_stop: e.target.value === "1" }))}
              onActivate={(hint) => ensureEditing(hint)}
              focusKey="early-stop"
              style={{ fontFamily: "monospace", fontSize: "0.85rem", maxWidth: "16rem" }}
            >
              <option value="1">Yes</option>
              <option value="0">No (run all iterations)</option>
            </ConfigSelect>
            {problem.early_stop && (
              <span className="muted" style={{ fontSize: "0.72rem" }}>
                Ends when the best cost barely changes for several epochs in a row (defaults apply if fields below are empty).
              </span>
            )}
          </div>
        </FieldRow>
      )}

      {problem.early_stop && (problem.algorithm || problem.epochs !== null) && (
        <>
          <FieldRow label="Plateau patience (epochs)">
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <ConfigNumberInput
                editable={editable}
                value={problem.early_stop_patience ?? NaN}
                className={markerClassFor("field:early_stop_patience")}
                min={1}
                max={5000}
                onValueChange={(value) => {
                  if (value == null) return;
                  runEditingAction(() =>
                    updateProblem({
                      early_stop_patience: Math.max(1, Math.min(5000, Math.trunc(value))),
                    }),
                  );
                }}
                onActivate={(hint) => ensureEditing(hint)}
                focusKey="early-stop-patience"
                style={{ width: "6rem", fontFamily: "monospace" }}
              />
              <span className="muted" style={{ fontSize: "0.75rem" }}>
                default 20
              </span>
            </div>
          </FieldRow>
          <FieldRow label="Min score improvement">
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <ConfigNumberInput
                editable={editable}
                value={problem.early_stop_epsilon ?? NaN}
                className={markerClassFor("field:early_stop_epsilon")}
                min={0}
                step={0.0001}
                onValueChange={(value) => {
                  if (value == null) return;
                  runEditingAction(() =>
                    updateProblem({
                      early_stop_epsilon: value <= 0 ? null : value,
                    }),
                  );
                }}
                onActivate={(hint) => ensureEditing(hint)}
                focusKey="early-stop-epsilon"
                style={{ width: "8rem", fontFamily: "monospace" }}
              />
              <span className="muted" style={{ fontSize: "0.75rem" }}>
                default 1e-4
              </span>
            </div>
          </FieldRow>
        </>
      )}

      {(problem.algorithm !== "" || problem.pop_size !== null) && (
        <FieldRow label="Population / swarm size">
          <ConfigNumberInput
            editable={editable}
            value={problem.pop_size ?? DEFAULT_POP_SIZE}
            className={markerClassFor("field:pop_size")}
            min={2}
            max={500}
            onValueChange={(value) => {
              if (value == null) return;
              runEditingAction(() => updateProblem({ pop_size: Math.max(2, Math.trunc(value)) }));
            }}
            onActivate={(hint) => ensureEditing(hint)}
            focusKey="pop-size"
            style={{ width: "6rem", fontFamily: "monospace" }}
          />
        </FieldRow>
      )}

      {problem.random_seed !== null && (
        <FieldRow label="Random seed">
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <ConfigNumberInput
              editable={editable}
              value={problem.random_seed}
              className={markerClassFor("field:random_seed")}
              onValueChange={(value) => {
                if (value == null) return;
                runEditingAction(() => updateProblem({ random_seed: Math.trunc(value) }));
              }}
              onActivate={(hint) => ensureEditing(hint)}
              focusKey="random-seed"
              style={{ width: "6rem", fontFamily: "monospace" }}
            />
            <span className="muted" style={{ fontSize: "0.75rem" }}>
              fix to reproduce results
            </span>
          </div>
        </FieldRow>
      )}
    </>
  );
}
