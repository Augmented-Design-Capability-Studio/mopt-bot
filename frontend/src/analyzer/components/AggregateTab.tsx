import { useState } from "react";

import { describeApiError } from "@shared/api";

import { uploadSurvey } from "../lib/api";
import { PyodideNotebook } from "./PyodideNotebook";

/** Tab 2 — cross-session analysis. Survey ingestion + an in-browser Python
 *  notebook (Pyodide) over the de-identified dataset. */
export function AggregateTab({ token }: { token: string }) {
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  async function handleSurvey(file: File) {
    try {
      const res = await uploadSurvey(token.trim(), file, "pre");
      setNote(`Loaded ${res.count} pre-task survey rows. Click “Reload data” in the notebook.`);
      setError(null);
    } catch (e) {
      setError(describeApiError(e, "Survey upload failed."));
    }
  }

  return (
    <div style={{ overflow: "auto", height: "100%", padding: "0 0.25rem" }}>
      <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap", marginBottom: "0.5rem" }}>
        <label className="muted" style={{ fontSize: "0.85rem" }}>
          Load pre-task survey CSV (for expertise / confidence / time columns)
          <input
            type="file"
            accept=".csv,text/csv"
            style={{ display: "block", marginTop: "0.25rem", fontSize: "0.78rem" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void handleSurvey(f);
              e.currentTarget.value = "";
            }}
          />
        </label>
        {note ? <span className="muted">{note}</span> : null}
      </div>
      {error ? <div className="banner-warn" style={{ marginBottom: "0.5rem" }}>{error}</div> : null}
      <p className="muted" style={{ fontSize: "0.8rem", maxWidth: 680 }}>
        Parsed server-side; only de-identified, numeric-derived fields reach the browser (email and
        free-text are dropped).
      </p>

      <PyodideNotebook token={token} />
    </div>
  );
}
