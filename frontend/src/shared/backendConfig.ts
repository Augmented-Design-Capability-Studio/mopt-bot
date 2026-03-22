export const DEFAULT_BACKEND_BASE = "http://127.0.0.1:8000";
const BACKEND_BASE_STORAGE_KEY = "mopt_backend_base";

export type BackendBaseSource = "user" | "env" | "default";

export function normalizeBackendBase(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function canUseStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

export function readUserBackendBaseOverride(): string | null {
  if (!canUseStorage()) return null;
  const stored = window.localStorage.getItem(BACKEND_BASE_STORAGE_KEY);
  if (!stored) return null;
  const normalized = normalizeBackendBase(stored);
  return normalized || null;
}

export function setUserBackendBaseOverride(value: string): void {
  if (!canUseStorage()) return;
  const normalized = normalizeBackendBase(value);
  if (!normalized) {
    window.localStorage.removeItem(BACKEND_BASE_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(BACKEND_BASE_STORAGE_KEY, normalized);
}

export function clearUserBackendBaseOverride(): void {
  if (!canUseStorage()) return;
  window.localStorage.removeItem(BACKEND_BASE_STORAGE_KEY);
}

export function resolveBackendBase(): { url: string; source: BackendBaseSource } {
  const userOverride = readUserBackendBaseOverride();
  if (userOverride) return { url: userOverride, source: "user" };

  const envValue = normalizeBackendBase(import.meta.env.VITE_API_BASE ?? "");
  if (envValue) return { url: envValue, source: "env" };

  return { url: DEFAULT_BACKEND_BASE, source: "default" };
}

export function buildApiUrl(path: string): string {
  const base = resolveBackendBase().url;
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

export function buildHealthUrl(base: string): string {
  const normalized = normalizeBackendBase(base) || DEFAULT_BACKEND_BASE;
  return `${normalized}/health`;
}

export function backendSourceLabel(source: BackendBaseSource): string {
  switch (source) {
    case "user":
      return "user input";
    case "env":
      return ".env file";
    default:
      return "default local address";
  }
}
