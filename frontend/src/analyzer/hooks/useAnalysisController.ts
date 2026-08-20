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

  // "Coding done" lock. When the selected session is locked, every edit is
  // intercepted here and turned into an unlock prompt instead of a mutation —
  // a single chokepoint so no UI path can slip past it.
  const [unlockPromptOpen, setUnlockPromptOpen] = useState(false);

  const isSelectedLocked = useCallback(
    () => !!loaded.find((s) => s.id === selectedId)?.locked,
    [loaded, selectedId],
  );

  /** True if the edit is BLOCKED (session locked); opens the unlock dialog. */
  const blockedByLock = useCallback(() => {
    if (isSelectedLocked()) {
      setUnlockPromptOpen(true);
      return true;
    }
    return false;
  }, [isSelectedLocked]);

  const setLocked = useCallback(
    async (id: string, locked: boolean) => {
      await withBusy(() => api.setLocked(token.trim(), id, locked), "Lock toggle failed.");
      await refreshList();
      if (selectedId === id) await refreshDetail(selectedId);
    },
    [token, withBusy, refreshList, refreshDetail, selectedId],
  );

  const closeUnlockPrompt = useCallback(() => setUnlockPromptOpen(false), []);

  const unlockSelected = useCallback(async () => {
    setUnlockPromptOpen(false);
    if (selectedId) await setLocked(selectedId, false);
  }, [selectedId, setLocked]);

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
      if (!selectedId || blockedByLock()) return;
      await withBusy(
        () => api.patchCodingMeta(token.trim(), selectedId, patch),
        "Update failed.",
      );
      await refreshDetail(selectedId);
      await refreshList();
    },
    [token, selectedId, blockedByLock, withBusy, refreshDetail, refreshList],
  );

  const addAnnotation = useCallback(
    async (body: Partial<Annotation>) => {
      if (!selectedId || blockedByLock()) return;
      await withBusy(
        () => api.createAnnotation(token.trim(), selectedId, body),
        "Add annotation failed.",
      );
      await refreshDetail(selectedId);
    },
    [token, selectedId, blockedByLock, withBusy, refreshDetail],
  );

  const addManyAnnotations = useCallback(
    async (bodies: Partial<Annotation>[]) => {
      if (!selectedId || !bodies.length || blockedByLock()) return;
      await withBusy(async () => {
        for (const body of bodies) {
          await api.createAnnotation(token.trim(), selectedId, body);
        }
      }, "Bulk add annotations failed.");
      await refreshDetail(selectedId);
    },
    [token, selectedId, blockedByLock, withBusy, refreshDetail],
  );

  const editAnnotation = useCallback(
    async (annoId: number, body: Partial<Annotation>) => {
      if (!selectedId || blockedByLock()) return;
      await withBusy(
        () => api.updateAnnotation(token.trim(), selectedId, annoId, body),
        "Edit annotation failed.",
      );
      await refreshDetail(selectedId);
    },
    [token, selectedId, blockedByLock, withBusy, refreshDetail],
  );

  const removeAnnotation = useCallback(
    async (annoId: number) => {
      if (!selectedId || blockedByLock()) return;
      await withBusy(
        () => api.deleteAnnotation(token.trim(), selectedId, annoId),
        "Delete annotation failed.",
      );
      await refreshDetail(selectedId);
    },
    [token, selectedId, blockedByLock, withBusy, refreshDetail],
  );

  const addPause = useCallback(
    async (body: Partial<Pause>) => {
      if (!selectedId || blockedByLock()) return;
      await withBusy(() => api.createPause(token.trim(), selectedId, body), "Add pause failed.");
      await refreshDetail(selectedId);
    },
    [token, selectedId, blockedByLock, withBusy, refreshDetail],
  );

  const removePause = useCallback(
    async (pauseId: number) => {
      if (!selectedId || blockedByLock()) return;
      await withBusy(() => api.deletePause(token.trim(), selectedId, pauseId), "Delete pause failed.");
      await refreshDetail(selectedId);
    },
    [token, selectedId, blockedByLock, withBusy, refreshDetail],
  );

  const resetTags = useCallback(async () => {
    if (!selectedId || blockedByLock()) return null;
    const res = await withBusy(() => api.resetTags(token.trim(), selectedId), "Reset tags failed.");
    if (res) await refreshDetail(selectedId);
    return res;
  }, [token, selectedId, blockedByLock, withBusy, refreshDetail]);

  const runLlmTags = useCallback(
    async (body: { api_key: string; model: string; loaded_id?: string; purge_tags?: boolean }) => {
      const res = await withBusy(
        () => api.runLlmTags(token.trim(), body),
        "LLM tagging failed.",
      );
      if (res && selectedId) await refreshDetail(selectedId);
      return res;
    },
    [token, withBusy, selectedId, refreshDetail],
  );

  const exportCsv = useCallback(async () => {
    if (!selectedId) return;
    await withBusy(() => api.downloadCsv(token.trim(), selectedId), "CSV export failed.");
  }, [token, selectedId, withBusy]);

  const backupCoding = useCallback(async () => {
    await withBusy(() => api.downloadCodingBackup(token.trim()), "Backup download failed.");
  }, [token, withBusy]);

  const restoreCoding = useCallback(
    async (file: File) => {
      const res = await withBusy(() => api.restoreCoding(token.trim(), file), "Restore failed.");
      if (res) {
        await refreshList();
        if (selectedId) await refreshDetail(selectedId);
      }
      return res;
    },
    [token, withBusy, refreshList, refreshDetail, selectedId],
  );

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
    addManyAnnotations,
    editAnnotation,
    removeAnnotation,
    addPause,
    removePause,
    resetTags,
    runLlmTags,
    exportCsv,
    backupCoding,
    restoreCoding,
    setLocked,
    unlockPromptOpen,
    closeUnlockPrompt,
    unlockSelected,
  };
}

export type AnalysisController = ReturnType<typeof useAnalysisController>;
