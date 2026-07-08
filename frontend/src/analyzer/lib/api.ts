// Typed wrappers over the backend /analysis endpoints.
import { apiFetch, apiFetchBlob } from "@shared/api";

import type { Annotation, LoadedDetail, LoadedSummary, Pause } from "./types";

export function listLoaded(token: string): Promise<{ loaded: LoadedSummary[] }> {
  return apiFetch<{ loaded: LoadedSummary[] }>("/analysis/loaded", token);
}

export async function uploadFile(
  token: string,
  file: File,
): Promise<{ loaded: LoadedSummary[] }> {
  const buf = await file.arrayBuffer();
  const qs = `?filename=${encodeURIComponent(file.name)}`;
  return apiFetch<{ loaded: LoadedSummary[] }>(`/analysis/upload${qs}`, token, {
    method: "POST",
    body: buf,
    headers: { "Content-Type": "application/octet-stream" },
  });
}

export function loadLive(
  token: string,
  sourceSessionId: string,
): Promise<{ loaded: LoadedSummary[] }> {
  return apiFetch<{ loaded: LoadedSummary[] }>("/analysis/load-live", token, {
    method: "POST",
    body: JSON.stringify({ source_session_id: sourceSessionId }),
  });
}

export function getTimeline(token: string, id: string): Promise<LoadedDetail> {
  return apiFetch<LoadedDetail>(`/analysis/loaded/${id}/timeline`, token);
}

export function patchCodingMeta(
  token: string,
  id: string,
  patch: Record<string, unknown>,
): Promise<{ session: LoadedSummary }> {
  return apiFetch<{ session: LoadedSummary }>(`/analysis/loaded/${id}/coding-meta`, token, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function createAnnotation(
  token: string,
  id: string,
  body: Partial<Annotation>,
): Promise<Annotation> {
  return apiFetch<Annotation>(`/analysis/loaded/${id}/annotations`, token, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateAnnotation(
  token: string,
  id: string,
  annoId: number,
  body: Partial<Annotation>,
): Promise<Annotation> {
  return apiFetch<Annotation>(`/analysis/loaded/${id}/annotations/${annoId}`, token, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteAnnotation(token: string, id: string, annoId: number): Promise<unknown> {
  return apiFetch<unknown>(`/analysis/loaded/${id}/annotations/${annoId}`, token, {
    method: "DELETE",
  });
}

export function createPause(
  token: string,
  id: string,
  body: Partial<Pause>,
): Promise<Pause> {
  return apiFetch<Pause>(`/analysis/loaded/${id}/pauses`, token, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deletePause(token: string, id: string, pauseId: number): Promise<unknown> {
  return apiFetch<unknown>(`/analysis/loaded/${id}/pauses/${pauseId}`, token, {
    method: "DELETE",
  });
}

export function deleteLoaded(token: string, id: string): Promise<unknown> {
  return apiFetch<unknown>(`/analysis/loaded/${id}`, token, { method: "DELETE" });
}

export async function downloadCsv(token: string, id: string): Promise<void> {
  const { blob, filename } = await apiFetchBlob(`/analysis/loaded/${id}/export.csv`, token);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename ?? `coding-${id}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
