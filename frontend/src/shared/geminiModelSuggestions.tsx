/**
 * Gemini model suggestions — driven by GET /meta/config, no hardcoded model names.
 * Falls back to an empty list so the input still works (user can type any id freely).
 *
 * The config is fetched ONCE at module load time and cached in a module-level
 * promise so all components share the same data and the datalist ID collision
 * (duplicate <datalist> elements) is avoided by rendering it at the app root level.
 */
import { useEffect, useState } from "react";
import { fetchPublicConfig, type PublicConfig } from "@shared/api";

export type GeminiConfig = {
  defaultModel: string;
  suggestions: string[];
};

export const GEMINI_MODEL_DATALIST_ID = "mopt-gemini-model-suggestions";

// --- Module-level singleton cache ---
let _cache: GeminiConfig | null = null;
let _promise: Promise<GeminiConfig> | null = null;

function loadGeminiConfig(): Promise<GeminiConfig> {
  if (_cache) return Promise.resolve(_cache);
  if (!_promise) {
    _promise = fetchPublicConfig().then((c: PublicConfig) => {
      _cache = { defaultModel: c.default_gemini_model, suggestions: c.gemini_model_suggestions };
      return _cache;
    });
  }
  return _promise;
}

/** Returns Gemini config fetched from the server (shared singleton, fetched once). */
export function useGeminiConfig(): GeminiConfig {
  const [config, setConfig] = useState<GeminiConfig>(_cache ?? { defaultModel: "", suggestions: [] });
  useEffect(() => {
    if (_cache) return; // already resolved — state was initialized from cache above
    loadGeminiConfig().then(setConfig);
  }, []);
  return config;
}

/**
 * Render this ONCE near the root of each app (ClientApp / ResearcherApp).
 * All inputs with list={GEMINI_MODEL_DATALIST_ID} will see all suggestions.
 */
export function GeminiModelDatalist() {
  const { suggestions } = useGeminiConfig();
  return (
    <datalist id={GEMINI_MODEL_DATALIST_ID}>
      {suggestions.map((id) => (
        <option key={id} value={id} />
      ))}
    </datalist>
  );
}
