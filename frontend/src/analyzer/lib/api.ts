// Typed wrappers over the backend /analysis endpoints.
import { apiFetch, apiFetchBlob } from "@shared/api";

import type {
  AggregateResponse,
  Annotation,
  LoadedDetail,
  LoadedSummary,
  Pause,
  SurveyStatus,
} from "./types";

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

export function runLlmTags(
  token: string,
  body: { api_key: string; model: string; loaded_id?: string; purge_tags?: boolean },
): Promise<{
  sessions: number;
  tagged_exchanges: number;
  ran_llm: boolean;
  skipped_locked: number;
  failed: number;
  purged_tags: number;
}> {
  return apiFetch("/analysis/llm-tags", token, {
    method: "POST",
    body: JSON.stringify(body),
  });
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

export function setLocked(
  token: string,
  id: string,
  locked: boolean,
): Promise<{ session: LoadedSummary }> {
  return apiFetch<{ session: LoadedSummary }>(`/analysis/loaded/${id}/lock`, token, {
    method: "POST",
    body: JSON.stringify({ locked }),
  });
}

export function resetTags(token: string, id: string): Promise<{ deleted: number }> {
  return apiFetch<{ deleted: number }>(`/analysis/loaded/${id}/reset-tags`, token, {
    method: "POST",
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

export function deleteLoadedBulk(token: string, ids: string[]): Promise<{ deleted: number }> {
  return apiFetch<{ deleted: number }>("/analysis/delete-loaded", token, {
    method: "POST",
    body: JSON.stringify({ ids }),
  });
}

export async function uploadSurvey(
  token: string,
  file: File,
  phase: "pre" | "post",
): Promise<{ phase: string; count: number }> {
  const buf = await file.arrayBuffer();
  return apiFetch<{ phase: string; count: number }>(
    `/analysis/surveys/upload?phase=${phase}`,
    token,
    { method: "POST", body: buf, headers: { "Content-Type": "text/csv" } },
  );
}

export function getSurveyStatus(token: string): Promise<SurveyStatus> {
  return apiFetch<SurveyStatus>("/analysis/surveys", token);
}

export function getAggregate(token: string): Promise<AggregateResponse> {
  return apiFetch<AggregateResponse>("/analysis/aggregate", token);
}

export function getDataset(token: string): Promise<Record<string, unknown[]>> {
  return apiFetch<Record<string, unknown[]>>("/analysis/dataset", token);
}

export function getNotebook(
  token: string,
): Promise<{ name: string; cells: string[] | null; updated_at: string | null }> {
  return apiFetch("/analysis/notebook", token);
}

export function saveNotebook(token: string, cells: string[]): Promise<{ saved: number }> {
  return apiFetch<{ saved: number }>("/analysis/notebook", token, {
    method: "PUT",
    body: JSON.stringify({ cells }),
  });
}

export async function downloadCodingBackup(token: string): Promise<void> {
  const { blob, filename } = await apiFetchBlob("/analysis/coding-backup.json", token);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename ?? "mopt-coding-backup.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function restoreCoding(
  token: string,
  file: File,
): Promise<{ sessions: number; annotations: number }> {
  const buf = await file.arrayBuffer();
  return apiFetch<{ sessions: number; annotations: number }>("/analysis/coding-restore", token, {
    method: "POST",
    body: buf,
    headers: { "Content-Type": "application/json" },
  });
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
