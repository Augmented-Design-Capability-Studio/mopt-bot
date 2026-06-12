import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  apiFetch,
  apiFetchBlob,
  describeApiError,
  displayRunNumber,
  fetchProblemFiles,
  fetchTestProblemsMeta,
  type Message,
  type RunResult,
  type Session,
  type TestProblemMeta,
} from "@shared/api";
import { useGeminiConfig } from "@shared/geminiModelSuggestions";

import { getOnlyActiveTerms } from "../lib/sessionConfig";

const TOKEN_KEY = "mopt_researcher_token";
const RESEARCHER_DETAIL_POLL_MS = 10000;
const TUTORIAL_REFRESH_SIGNAL_KEY = "mopt_participant_tutorial_refresh";

export function useResearcherController() {
  /** Value in the input; not sent to the API until "Save token". */
  const [tokenInput, setTokenInput] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? "");
  /** Bearer token used for all requests after the user confirms the input. */
  const [savedToken, setSavedToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? "");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [detail, setDetail] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [runs, setRuns] = useState<RunResult[]>([]);
  const [steerText, setSteerText] = useState("");
  const [geminiKey, setGeminiKey] = useState("");
  const { defaultModel: defaultGeminiModel, defaultEmbeddingModel } = useGeminiConfig();
  const [geminiModel, setGeminiModel] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pushKeySuccess, setPushKeySuccess] = useState<string | null>(null);
  const [testProblemsMeta, setTestProblemsMeta] = useState<TestProblemMeta[]>([]);

  // Every mutation increments this generation counter so older poll responses
  // cannot overwrite fresher researcher state.
  const detailPollGen = useRef(0);
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selected;

  const refreshList = useCallback(async () => {
    if (!savedToken.trim()) return;
    try {
      const list = await apiFetch<Session[]>("/sessions", savedToken.trim());
      setSessions(list);
      setSelectedIds((current) => current.filter((id) => list.some((session) => session.id === id)));
      setError(null);
    } catch (e) {
      setError(describeApiError(e, "List failed"));
      setNotice(null);
    }
  }, [savedToken]);

  const createNewSession = useCallback(
    async (body: { participant_number: string; workflow_mode: string; test_problem_id: string }) => {
      if (!savedToken.trim()) return;
      detailPollGen.current += 1;
      setBusy(true);
      setNotice(null);
      try {
        const session = await apiFetch<Session>("/sessions", savedToken.trim(), {
          method: "POST",
          body: JSON.stringify({
            workflow_mode: body.workflow_mode,
            participant_number: body.participant_number.trim() || null,
            test_problem_id: body.test_problem_id,
          }),
        });
        await refreshList();
        setSelected(session.id);
        setSelectedIds([]);
        setError(null);
        setNotice(`Created session ${session.id.slice(0, 8)}…`);
      } catch (e) {
        setError(describeApiError(e, "Create session failed"));
      } finally {
        setBusy(false);
      }
    },
    [refreshList, savedToken],
  );

  const loadDetail = useCallback(async () => {
    if (!savedToken.trim() || !selected) return;
    const sessionId = selected;
    const gen = detailPollGen.current;
    try {
      const session = await apiFetch<Session>(`/sessions/${sessionId}/researcher`, savedToken.trim());
      if (gen !== detailPollGen.current || sessionId !== selectedRef.current) return;
      setDetail(session);

      const nextMessages = await apiFetch<Message[]>(
        `/sessions/${sessionId}/messages/researcher?after_id=0`,
        savedToken.trim(),
      );
      if (gen !== detailPollGen.current || sessionId !== selectedRef.current) return;
      setMessages(nextMessages);

      const nextRuns = await apiFetch<RunResult[]>(`/sessions/${sessionId}/runs`, savedToken.trim());
      if (gen !== detailPollGen.current || sessionId !== selectedRef.current) return;
      setRuns(nextRuns);
    } catch (e) {
      if (gen !== detailPollGen.current || sessionId !== selectedRef.current) return;
      setError(describeApiError(e, "Load failed"));
      setNotice(null);
    }
  }, [savedToken, selected]);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  useEffect(() => {
    if (!savedToken.trim()) {
      setTestProblemsMeta([]);
      return;
    }
    let cancelled = false;
    void fetchTestProblemsMeta()
      .then((list) => {
        if (!cancelled) setTestProblemsMeta(list);
      })
      .catch(() => {
        if (!cancelled) setTestProblemsMeta([]);
      });
    return () => {
      cancelled = true;
    };
  }, [savedToken]);

  useEffect(() => {
    void loadDetail();
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void loadDetail();
    }, RESEARCHER_DETAIL_POLL_MS);
    return () => window.clearInterval(timer);
  }, [loadDetail]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void loadDetail();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [loadDetail]);

  useEffect(() => {
    if (!detail) return;
    setGeminiModel(detail.gemini_model?.trim() || defaultGeminiModel);
    setEmbeddingModel(detail.embedding_model?.trim() || defaultEmbeddingModel);
  }, [detail?.id, defaultGeminiModel, defaultEmbeddingModel]);

  function saveToken() {
    const trimmed = tokenInput.trim();
    sessionStorage.setItem(TOKEN_KEY, trimmed);
    setSavedToken(trimmed);
    setTokenInput(trimmed);
    setError(null);
  }

  /**
   * Shared PATCH helper for researcher controls. Returning a boolean lets the
   * caller decide whether to clear UI state like inputs or success banners.
   */
  const patchSession = useCallback(
    async (patch: Record<string, unknown>): Promise<boolean> => {
      if (!savedToken.trim() || !selected) return false;
      detailPollGen.current += 1;
      setBusy(true);
      try {
        const session = await apiFetch<Session>(`/sessions/${selected}`, savedToken.trim(), {
          method: "PATCH",
          body: JSON.stringify(patch),
        });
        setDetail(session);
        if ("participant_tutorial_enabled" in patch || "tutorial_step_override" in patch) {
          try {
            localStorage.setItem(
              TUTORIAL_REFRESH_SIGNAL_KEY,
              JSON.stringify({
                session_id: selected,
                enabled: Boolean(session.participant_tutorial_enabled),
                tutorial_step_override: patch.tutorial_step_override ?? null,
                ts: Date.now(),
              }),
            );
          } catch {
            // ignore storage errors
          }
        }
        await refreshList();
        setError(null);
        return true;
      } catch (e) {
        setError(describeApiError(e, "Update failed"));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [refreshList, savedToken, selected],
  );

  async function sendSteer() {
    if (!steerText.trim() || !savedToken.trim() || !selected) return;
    const text = steerText.trim();
    const tempId = -Date.now();
    const optimistic: Message = {
      id: tempId,
      created_at: new Date().toISOString(),
      role: "researcher",
      content: text,
      visible_to_participant: false,
      kind: "chat",
    };
    setMessages((current) => [...current, optimistic]);
    setSteerText("");
    setBusy(true);
    try {
      const saved = await apiFetch<Message>(`/sessions/${selected}/steer`, savedToken.trim(), {
        method: "POST",
        body: JSON.stringify({ content: text }),
      });
      setMessages((current) => [...current.filter((message) => message.id !== tempId), saved]);
    } catch (e) {
      setMessages((current) => current.filter((message) => message.id !== tempId));
      setSteerText(text);
      setError(describeApiError(e, "Steer failed"));
    } finally {
      setBusy(false);
    }
  }

  async function terminate() {
    if (!selected || !savedToken.trim()) return;
    detailPollGen.current += 1;
    setBusy(true);
    try {
      await apiFetch(`/sessions/${selected}/terminate`, savedToken.trim(), { method: "POST" });
      await refreshList();
      await loadDetail();
    } catch (e) {
      setError(describeApiError(e, "Terminate failed"));
    } finally {
      setBusy(false);
    }
  }

  async function resyncPanelFromBrief() {
    if (!selected || !savedToken.trim()) return;
    setBusy(true);
    try {
      const next = await apiFetch<Session>(
        `/sessions/${selected}/resync-panel-from-brief`,
        savedToken.trim(),
        { method: "POST" },
      );
      setDetail(next);
      setError(null);
      setNotice(
        next.brief_panel_drift && next.brief_panel_drift.length > 0
          ? `Synced panel from brief. ${next.brief_panel_drift.length} drift entr${next.brief_panel_drift.length === 1 ? "y" : "ies"} remain — try "Sync to def." for keys the panel has but the brief doesn't.`
          : "Synced panel from brief. No drift remaining.",
      );
    } catch (e) {
      setNotice(null);
      setError(describeApiError(e, "Sync to config failed"));
    } finally {
      setBusy(false);
    }
  }

  async function resyncBriefFromPanel() {
    if (!selected || !savedToken.trim()) return;
    setBusy(true);
    try {
      const next = await apiFetch<Session>(
        `/sessions/${selected}/resync-brief-from-panel`,
        savedToken.trim(),
        { method: "POST" },
      );
      setDetail(next);
      setError(null);
      setNotice(
        next.brief_panel_drift && next.brief_panel_drift.length > 0
          ? `Mirrored panel into brief. ${next.brief_panel_drift.length} drift entr${next.brief_panel_drift.length === 1 ? "y" : "ies"} remain — try "Sync to config" for keys the brief has but the panel doesn't.`
          : "Mirrored panel into brief. No drift remaining.",
      );
    } catch (e) {
      setNotice(null);
      setError(describeApiError(e, "Mirror to def. failed"));
    } finally {
      setBusy(false);
    }
  }

  async function resetSession() {
    if (!selected || !savedToken.trim()) return;
    if (!window.confirm("Reset this session? This clears chat, runs, and snapshots, but keeps participant number and model settings.")) {
      return;
    }
    detailPollGen.current += 1;
    setBusy(true);
    try {
      const next = await apiFetch<Session>(`/sessions/${selected}/reset`, savedToken.trim(), { method: "POST" });
      setDetail(next);
      setMessages([]);
      setRuns([]);
      await refreshList();
      setError(null);
      setNotice("Session reset.");
    } catch (e) {
      setNotice(null);
      setError(describeApiError(e, "Reset failed"));
    } finally {
      setBusy(false);
    }
  }

  async function resetStuckRun() {
    if (!selected || !savedToken.trim()) return;
    const sessionId = selected;
    detailPollGen.current += 1;
    setBusy(true);
    try {
      const result = await apiFetch<{ signalled: boolean; cleared: number }>(
        `/sessions/${sessionId}/runs/reset-stuck`,
        savedToken.trim(),
        { method: "POST" },
      );
      const [nextDetail, nextRuns] = await Promise.all([
        apiFetch<Session>(`/sessions/${sessionId}/researcher`, savedToken.trim()),
        apiFetch<RunResult[]>(`/sessions/${sessionId}/runs`, savedToken.trim()),
      ]);
      if (sessionId !== selectedRef.current) return;
      setDetail(nextDetail);
      setRuns(nextRuns);
      await refreshList();
      setError(null);
      setNotice(
        result.cleared > 0
          ? `Cleared ${result.cleared} stuck run${result.cleared === 1 ? "" : "s"}.`
          : "No stuck run found.",
      );
    } catch (e) {
      setNotice(null);
      setError(describeApiError(e, "Reset stuck run failed"));
    } finally {
      setBusy(false);
    }
  }

  async function removeSession() {
    if (!selected || !savedToken.trim()) return;
    if (!window.confirm("Delete this session and all logs?")) return;
    setBusy(true);
    let deleteError: string | null = null;
    try {
      await apiFetch(`/sessions/${selected}`, savedToken.trim(), { method: "DELETE" });
    } catch (e) {
      deleteError = describeApiError(e, "Delete failed");
    }
    // Always clear local detail state + refresh the sidebar list so the UI
    // reflects whatever actually happened in the DB. Without this, a failed
    // single delete left the sidebar showing the row that the DB may or
    // may not still have (same class of stale-UI bug the bulk path had).
    setSelected(null);
    setDetail(null);
    setMessages([]);
    setRuns([]);
    try {
      await refreshList();
    } catch {
      // refreshList errors are surfaced separately; don't mask the
      // delete result.
    }
    setError(deleteError);
    setBusy(false);
  }

  async function removeSelectedSessions() {
    if (!savedToken.trim() || selectedIds.length === 0) return;
    if (!window.confirm(`Delete ${selectedIds.length} selected session(s) and all logs?`)) return;
    detailPollGen.current += 1;
    setBusy(true);
    // Per-iteration catch so one failure (404 already-deleted, stale token,
    // transient network blip) doesn't abort the rest of the batch. We
    // collect failures and refresh the list regardless — the user gets a
    // concrete count of what landed, not a generic "Batch delete failed"
    // that leaves the sidebar lying about what's still in the DB.
    const failures: Array<{ sessionId: string; error: string }> = [];
    let successCount = 0;
    try {
      for (const sessionId of selectedIds) {
        try {
          await apiFetch(`/sessions/${sessionId}`, savedToken.trim(), { method: "DELETE" });
          successCount += 1;
        } catch (e) {
          failures.push({ sessionId, error: describeApiError(e, "Delete failed") });
        }
      }
      if (selected && selectedIds.includes(selected)) {
        setSelected(null);
        setDetail(null);
        setMessages([]);
        setRuns([]);
      }
      setSelectedIds([]);
      // Always refresh — partial successes still updated the DB.
      await refreshList();
      if (failures.length === 0) {
        setError(null);
      } else {
        const sample = failures
          .slice(0, 3)
          .map((f) => `${f.sessionId.slice(0, 8)}: ${f.error}`)
          .join("; ");
        const more = failures.length > 3 ? ` (+${failures.length - 3} more)` : "";
        setError(
          `Deleted ${successCount} of ${selectedIds.length}; ${failures.length} failed: ${sample}${more}`,
        );
      }
    } finally {
      setBusy(false);
    }
  }

  async function removeRun(run: RunResult) {
    if (!selected || !savedToken.trim()) return;
    const sessionId = selected;
    if (
      !window.confirm(
        `Delete run #${displayRunNumber(run)} from this session? This removes the stored run record from the database.`,
      )
    ) {
      return;
    }
    detailPollGen.current += 1;
    setBusy(true);
    try {
      await apiFetch(`/sessions/${sessionId}/runs/${run.id}`, savedToken.trim(), { method: "DELETE" });
      const [nextDetail, nextRuns] = await Promise.all([
        apiFetch<Session>(`/sessions/${sessionId}/researcher`, savedToken.trim()),
        apiFetch<RunResult[]>(`/sessions/${sessionId}/runs`, savedToken.trim()),
      ]);
      if (sessionId !== selectedRef.current) return;
      setDetail(nextDetail);
      setRuns(nextRuns);
      await refreshList();
      setError(null);
    } catch (e) {
      setError(describeApiError(e, "Delete run failed"));
    } finally {
      setBusy(false);
    }
  }

  async function pushParticipantStarterPanel() {
    if (!savedToken.trim() || !selected) return;
    detailPollGen.current += 1;
    setBusy(true);
    try {
      const session = await apiFetch<Session>(
        `/sessions/${selected}/participant-starter-panel`,
        savedToken.trim(),
        { method: "POST" },
      );
      setDetail(session);
      await refreshList();
      setError(null);
    } catch (e) {
      setError(describeApiError(e, "Push starter config failed"));
    } finally {
      setBusy(false);
    }
  }

  async function pushDummyParticipantUpload() {
    if (!savedToken.trim() || !selected) return;
    detailPollGen.current += 1;
    setBusy(true);
    try {
      const problemId = detail?.test_problem_id ?? "vrptw";
      const availableFiles = await fetchProblemFiles(problemId);
      const fileNames = availableFiles.length > 0 ? availableFiles : undefined;
      await apiFetch(`/sessions/${selected}/researcher/simulate-participant-upload`, savedToken.trim(), {
        method: "POST",
        body: JSON.stringify({ invoke_model: true, ...(fileNames ? { file_names: fileNames } : {}) }),
      });
      await loadDetail();
      await refreshList();
      setError(null);
    } catch (e) {
      setError(describeApiError(e, "Push dummy files failed"));
    } finally {
      setBusy(false);
    }
  }

  async function setOnlyActiveTerms(enabled: boolean) {
    if (!detail) return;
    const panel =
      detail.panel_config && typeof detail.panel_config === "object" && !Array.isArray(detail.panel_config)
        ? { ...(detail.panel_config as Record<string, unknown>) }
        : {};
    const problem =
      panel.problem && typeof panel.problem === "object" && !Array.isArray(panel.problem)
        ? { ...(panel.problem as Record<string, unknown>) }
        : {};
    problem.only_active_terms = enabled;
    panel.problem = problem;
    await patchSession({ panel_config: panel });
  }

  async function downloadSelectedSessionsDb() {
    if (!savedToken.trim() || selectedIds.length === 0) return;
    setBusy(true);
    try {
      const { blob, filename } = await apiFetchBlob("/sessions/export-db", savedToken.trim(), {
        method: "POST",
        body: JSON.stringify({ session_ids: selectedIds }),
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename ?? `mopt-sessions-${selectedIds.length}.db`;
      anchor.click();
      URL.revokeObjectURL(url);
      setError(null);
      setNotice(`Downloaded ${selectedIds.length} session(s) as a SQLite file.`);
    } catch (e) {
      setNotice(null);
      setError(describeApiError(e, "Download failed"));
    } finally {
      setBusy(false);
    }
  }

  async function exportJson() {
    if (!selected || !savedToken.trim()) return;
    try {
      const data = await apiFetch<unknown>(`/sessions/${selected}/export`, savedToken.trim());
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `session-${selected}-archive.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(describeApiError(e, "Export failed"));
    }
  }

  async function pushGeminiKey() {
    const key = geminiKey.trim();
    if (!key) {
      setError("Enter a Gemini API key to push.");
      return;
    }
    const ok = await patchSession({
      gemini_api_key: key,
      gemini_model: geminiModel.trim() || undefined,
      embedding_model: embeddingModel.trim() || undefined,
    });
    if (ok) {
      setGeminiKey("");
      setPushKeySuccess(
        "Key saved on the server. The participant app will show a check on the Assistant chip after the next sync.",
      );
    }
  }

  async function copySessionLink() {
    if (!selected) return;
    const url = new URL("/client.html", window.location.origin);
    url.searchParams.set("session", selected);
    const link = url.toString();
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(link);
      } else {
        window.prompt("Copy session link", link);
      }
      setError(null);
      setNotice("Session link copied.");
    } catch (e) {
      setNotice(null);
      setError(describeApiError(e, "Could not copy session link"));
    }
  }

  const tokenDirty = useMemo(() => tokenInput.trim() !== savedToken.trim(), [savedToken, tokenInput]);

  const toggleSessionSelected = useCallback((sessionId: string, checked: boolean) => {
    setSelectedIds((current) =>
      checked ? (current.includes(sessionId) ? current : [...current, sessionId]) : current.filter((id) => id !== sessionId),
    );
  }, []);

  const toggleAllSessionsSelected = useCallback(
    (checked: boolean) => {
      setSelectedIds(checked ? sessions.map((session) => session.id) : []);
    },
    [sessions],
  );

  return {
    tokenInput,
    savedToken,
    sessions,
    selected,
    selectedIds,
    detail,
    messages,
    runs,
    steerText,
    geminiKey,
    geminiModel,
    embeddingModel,
    busy,
    error,
    notice,
    pushKeySuccess,
    tokenDirty,
    setTokenInput,
    setSelected,
    setSteerText,
    setGeminiKey,
    setGeminiModel,
    setEmbeddingModel,
    setPushKeySuccess,
    setNotice,
    setError,
    toggleSessionSelected,
    toggleAllSessionsSelected,
    refreshList,
    createNewSession,
    saveToken,
    patchSession,
    sendSteer,
    terminate,
    resetSession,
    resetStuckRun,
    resyncPanelFromBrief,
    resyncBriefFromPanel,
    removeSession,
    removeSelectedSessions,
    downloadSelectedSessionsDb,
    removeRun,
    pushParticipantStarterPanel,
    pushDummyParticipantUpload,
    setOnlyActiveTerms,
    exportJson,
    pushGeminiKey,
    copySessionLink,
    getOnlyActiveTerms,
    testProblemsMeta,
  };
}
