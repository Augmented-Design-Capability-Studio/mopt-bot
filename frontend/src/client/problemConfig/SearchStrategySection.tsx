import {
  ALLOWED_ALGORITHM_PARAMS,
  ALGORITHM_PARAM_FIELD_META,
  defaultParamsForAlgorithm,
} from "./algorithmCatalog";
import { ALGORITHM_DESC } from "./metadata";
import { FieldRow } from "./layout";
import type { ProblemBlock } from "./types";
import type { MarkerKind } from "./useProblemConfigDiffMarkers";
import { ConfigNumberInput, ConfigSelect, type ActivateHint } from "./controls";

type SearchStrategySectionProps = {
  problem: ProblemBlock;
  editable: boolean;
  markerKindFor: (key: string) => MarkerKind | null;
  updateProblem: (patch: Partial<ProblemBlock>) => void;
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
  return (
    <>
      {problem.algorithm && (
        <FieldRow label="Algorithm" markerKind={markerKindFor("field:algorithm")}>
          <ConfigSelect
            editable={editable}
            value={problem.algorithm}
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

      {problem.algorithm &&
        (ALLOWED_ALGORITHM_PARAMS[problem.algorithm] ?? []).map((paramKey) => {
          const meta = ALGORITHM_PARAM_FIELD_META[problem.algorithm]?.[paramKey];
          const value = problem.algorithm_params[paramKey];
          const safe = typeof value === "number" && Number.isFinite(value) ? value : (meta?.min ?? 0);
          return (
            <FieldRow key={paramKey} label={meta?.label ?? paramKey} markerKind={markerKindFor(`algo:${paramKey}`)}>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <ConfigNumberInput
                  editable={editable}
                  value={safe}
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

      {problem.epochs !== null && (
        <FieldRow label="Max iterations" markerKind={markerKindFor("field:epochs")}>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <ConfigNumberInput
                editable={editable}
                value={problem.epochs}
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
                {problem.epochs < 100 ? "quick (may not fully converge)" : problem.epochs < 500 ? "moderate" : "thorough"}
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
        <FieldRow label="Stop early on plateau" markerKind={markerKindFor("field:early_stop")}>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            <ConfigSelect
              editable={editable}
              value={problem.early_stop ? "1" : "0"}
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
          <FieldRow label="Plateau patience (epochs)" markerKind={markerKindFor("field:early_stop_patience")}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <ConfigNumberInput
                editable={editable}
                value={problem.early_stop_patience ?? NaN}
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
          <FieldRow label="Min score improvement" markerKind={markerKindFor("field:early_stop_epsilon")}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <ConfigNumberInput
                editable={editable}
                value={problem.early_stop_epsilon ?? NaN}
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

      {problem.pop_size !== null && (
        <FieldRow label="Population / swarm size" markerKind={markerKindFor("field:pop_size")}>
          <ConfigNumberInput
            editable={editable}
            value={problem.pop_size}
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
        <FieldRow label="Random seed" markerKind={markerKindFor("field:random_seed")}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <ConfigNumberInput
              editable={editable}
              value={problem.random_seed}
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
