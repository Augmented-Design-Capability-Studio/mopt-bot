/**
 * Gemini model ids for UI presets (datalist). Align defaults with backend `MOPT_DEFAULT_GEMINI_MODEL`.
 * Users can always type another id in the linked input.
 */
export const DEFAULT_SUGGESTED_GEMINI_MODEL = "gemini-3-flash-preview";

export const GEMINI_MODEL_SUGGESTIONS: readonly string[] = [
  "gemini-3-flash-preview",
  "gemini-3.1-flash-lite-preview",
];

export const GEMINI_MODEL_DATALIST_ID = "mopt-gemini-model-suggestions";

export function GeminiModelDatalist() {
  return (
    <datalist id={GEMINI_MODEL_DATALIST_ID}>
      {GEMINI_MODEL_SUGGESTIONS.map((id) => (
        <option key={id} value={id} />
      ))}
    </datalist>
  );
}
