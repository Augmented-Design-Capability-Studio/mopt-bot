import { useEffect, useState } from "react";

import { AggregateTab } from "./components/AggregateTab";
import { SessionCodingTab } from "./components/SessionCodingTab";
import { useAnalysisController } from "./hooks/useAnalysisController";

type Tab = "coding" | "aggregate";

function tabFromHash(): Tab {
  return window.location.hash.replace("#/", "") === "aggregate" ? "aggregate" : "coding";
}

export function AnalyzerApp() {
  const ctl = useAnalysisController();
  const [tokenInput, setTokenInput] = useState(ctl.token);
  const [tab, setTab] = useState<Tab>(tabFromHash);

  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function selectTab(next: Tab) {
    window.location.hash = `#/${next}`;
    setTab(next);
  }

  useEffect(() => {
    document.title = tab === "aggregate" ? "Coding · Aggregate" : "Session Coding";
  }, [tab]);

  const tabBtn = (id: Tab, label: string) => (
    <button
      type="button"
      onClick={() => selectTab(id)}
      style={{
        fontSize: "0.85rem",
        padding: "0.3rem 0.75rem",
        border: "none",
        borderBottom: tab === id ? "2px solid #3b82f6" : "2px solid transparent",
        background: "transparent",
        fontWeight: tab === id ? 600 : 400,
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );

  return (
    <div className="app-shell" style={{ padding: "0.75rem", height: "100vh", boxSizing: "border-box" }}>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginBottom: "0.4rem" }}>
        <h1 style={{ fontSize: "1.05rem", margin: 0 }}>Session Coding</h1>
        <input
          type="password"
          placeholder="researcher token"
          value={tokenInput}
          onChange={(e) => setTokenInput(e.target.value)}
          style={{ fontSize: "0.8rem", width: 180 }}
        />
        <button
          type="button"
          style={{ fontSize: "0.8rem" }}
          onClick={() => {
            ctl.saveToken(tokenInput);
            void ctl.refreshList();
          }}
        >
          Save token
        </button>
        {ctl.busy ? <span className="muted">working…</span> : null}
      </div>

      <div style={{ display: "flex", gap: "0.25rem", borderBottom: "1px solid var(--border, #ddd)", marginBottom: "0.5rem" }}>
        {tabBtn("coding", "Session coding")}
        {tabBtn("aggregate", "Aggregate")}
      </div>

      {ctl.error ? (
        <div className="banner-warn" style={{ marginBottom: "0.5rem" }}>
          {ctl.error}
        </div>
      ) : null}

      <div style={{ height: "calc(100% - 5rem)", minHeight: 0 }}>
        {tab === "coding" ? (
          <SessionCodingTab ctl={ctl} />
        ) : (
          <AggregateTab token={ctl.token} />
        )}
      </div>
    </div>
  );
}
