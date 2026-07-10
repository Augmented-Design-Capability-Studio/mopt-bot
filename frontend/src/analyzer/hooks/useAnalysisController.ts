import { useCallback, useEffect, useState } from "react";

import { describeApiError } from "@shared/api";

import * as api from "../lib/api";
import type { Annotation, LoadedDetail, LoadedSummary, Pause } from "../lib/types";

const TOKEN_KEY = "mopt_researcher_token"; // shared with the researcher SPA

export function useAnalysisController() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? "");
  const [loaded, setLoaded] = useState<LoadedSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<LoadedDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const saveToken = useCallback((value: string) => {
    const trimmed = value.trim();
    sessionStorage.setItem(TOKEN_KEY, trimmed);
    setToken(trimmed);
  }, []);

  const refreshList = useCallback(async () => {
    if (!token.trim()) return;
    try {
      const res = await api.listLoaded(token.trim());
      setLoaded(res.loaded);
      setError(null);
    } catch (e) {
      setError(describeApiError(e, "Failed to list loaded sessions."));
    }
  }, [token]);

  const refreshDetail = useCallback(
    async (id: string) => {
      if (!token.trim()) return;
      try {
        const d = await api.getTimeline(token.trim(), id);
        setDetail(d);
        setError(null);
      } catch (e) {
        setError(describeApiError(e, "Failed to load session timeline."));
      }
    },
    [token],
  );

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  useEffect(() => {
    if (selectedId) void refreshDetail(selectedId);
    else setDetail(null);
  }, [selectedId, refreshDetail]);

  const withBusy = useCallback(
    async <T,>(fn: () => Promise<T>, fallback: string): Promise<T | null> => {
      setBusy(true);
      try {
        const out = await fn();
        setError(null);
        return out;
      } catch (e) {
        setError(describeApiError(e, fallback));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const uploadFile = useCallback(
    async (file: File) => {
      const res = await withBusy(() => api.uploadFile(token.trim(), file), "Upload failed.");
      if (res) {
        await refreshList();
        if (res.loaded[0]) setSelectedId(res.loaded[0].id);
      }
    },
    [token, withBusy, refreshList],
  );

  const loadLive = useCallback(
    async (sourceSessionId: string) => {
      const res = await withBusy(
        () => api.loadLive(token.trim(), sourceSessionId),
        "Load from study DB failed.",
      );
      if (res) {
        await refreshList();
        if (res.loaded[0]) setSelectedId(res.loaded[0].id);
      }
    },
    [token, withBusy, refreshList],
  );

  const removeLoaded = useCallback(
    async (id: string) => {
      await withBusy(() => api.deleteLoaded(token.trim(), id), "Delete failed.");
      if (selectedId === id) setSelectedId(null);
      await refreshList();
    },
    [token, withBusy, refreshList, selectedId],
  );

  const removeManyLoaded = useCallback(
    async (ids: string[]) => {
      if (!ids.length) return;
      await withBusy(() => api.deleteLoadedBulk(token.trim(), ids), "Bulk delete failed.");
      if (selectedId && ids.includes(selectedId)) setSelectedId(null);
      await refreshList();
    },
    [token, withBusy, refreshList, selectedId],
  );

  const patchMeta = useCallback(
    async (patch: Record<string, unknown>) => {
      if (!selectedId) return;
      await withBusy(
        () => api.patchCodingMeta(token.trim(), selectedId, patch),
        "Update failed.",
      );
      await refreshDetail(selectedId);
      await refreshList();
    },
    [token, selectedId, withBusy, refreshDetail, refreshList],
  );

  const addAnnotation = useCallback(
    async (body: Partial<Annotation>) => {
      if (!selectedId) return;
      await withBusy(
        () => api.createAnnotation(token.trim(), selectedId, body),
        "Add annotation failed.",
      );
      await refreshDetail(selectedId);
    },
    [token, selectedId, withBusy, refreshDetail],
  );

  const editAnnotation = useCallback(
    async (annoId: number, body: Partial<Annotation>) => {
      if (!selectedId) return;
      await withBusy(
        () => api.updateAnnotation(token.trim(), selectedId, annoId, body),
        "Edit annotation failed.",
      );
      await refreshDetail(selectedId);
    },
    [token, selectedId, withBusy, refreshDetail],
  );

  const removeAnnotation = useCallback(
    async (annoId: number) => {
      if (!selectedId) return;
      await withBusy(
        () => api.deleteAnnotation(token.trim(), selectedId, annoId),
        "Delete annotation failed.",
      );
      await refreshDetail(selectedId);
    },
    [token, selectedId, withBusy, refreshDetail],
  );

  const addPause = useCallback(
    async (body: Partial<Pause>) => {
      if (!selectedId) return;
      await withBusy(() => api.createPause(token.trim(), selectedId, body), "Add pause failed.");
      await refreshDetail(selectedId);
    },
    [token, selectedId, withBusy, refreshDetail],
  );

  const removePause = useCallback(
    async (pauseId: number) => {
      if (!selectedId) return;
      await withBusy(() => api.deletePause(token.trim(), selectedId, pauseId), "Delete pause failed.");
      await refreshDetail(selectedId);
    },
    [token, selectedId, withBusy, refreshDetail],
  );

  const exportCsv = useCallback(async () => {
    if (!selectedId) return;
    await withBusy(() => api.downloadCsv(token.trim(), selectedId), "CSV export failed.");
  }, [token, selectedId, withBusy]);

  return {
    token,
    saveToken,
    loaded,
    selectedId,
    setSelectedId,
    detail,
    busy,
    error,
    setError,
    refreshList,
    uploadFile,
    loadLive,
    removeLoaded,
    removeManyLoaded,
    patchMeta,
    addAnnotation,
    editAnnotation,
    removeAnnotation,
    addPause,
    removePause,
    exportCsv,
  };
}

export type AnalysisController = ReturnType<typeof useAnalysisController>;
