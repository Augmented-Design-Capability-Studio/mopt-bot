type ResearcherHeaderProps = {
  tokenInput: string;
  savedToken: string;
  tokenDirty: boolean;
  onTokenInputChange: (value: string) => void;
  onSaveToken: () => void;
  onRefreshList: () => void | Promise<void>;
};

export function ResearcherHeader({
  tokenInput,
  savedToken,
  tokenDirty,
  onTokenInputChange,
  onSaveToken,
  onRefreshList,
}: ResearcherHeaderProps) {
  return (
    <header className="app-header">
      <span className="app-title">Researcher</span>
      <div style={{ display: "flex", gap: "0.35rem", alignItems: "center", flexWrap: "wrap" }}>
        <input
          type="password"
          placeholder="Researcher token (paste, then Save)"
          value={tokenInput}
          onChange={(e) => onTokenInputChange(e.target.value)}
          style={{ minWidth: "12rem" }}
          autoComplete="off"
        />
        <button type="button" onClick={onSaveToken}>
          Save token
        </button>
        <button type="button" disabled={!savedToken.trim()} onClick={() => void onRefreshList()}>
          Refresh list
        </button>
        {tokenDirty && (
          <span className="muted" style={{ fontSize: "0.8rem" }}>
            Unsaved - click Save to use this token
          </span>
        )}
      </div>
    </header>
  );
}
