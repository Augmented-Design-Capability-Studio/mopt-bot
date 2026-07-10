// In-browser Python runtime (Pyodide/WASM) for the aggregate notebook.
//
// SECURITY: all user code runs in the browser WASM sandbox — never on the
// server. The researcher token is NOT passed into Python (data is fetched in
// JS and handed over as plain JSON). For a locked-down, offline, or
// same-origin deployment, self-host the Pyodide distribution and point
// localStorage["mopt_pyodide_index"] at it (then a CSP `connect-src 'self'`
// blocks any exfiltration by pasted code).

const DEFAULT_INDEX_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";

function indexUrl(): string {
  try {
    return localStorage.getItem("mopt_pyodide_index") || DEFAULT_INDEX_URL;
  } catch {
    return DEFAULT_INDEX_URL;
  }
}

// Defines the cell runner inside the Pyodide global scope.
const RUNNER_PY = `
import sys, io, json, base64, traceback
import matplotlib
matplotlib.use("AGG")
import matplotlib.pyplot as plt

_NB_GLOBALS = {}

def _run_cell(code):
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    err = None
    try:
        exec(code, _NB_GLOBALS)
    except Exception:
        err = traceback.format_exc()
    finally:
        sys.stdout = old
    images = []
    for num in plt.get_fignums():
        fig = plt.figure(num)
        b = io.BytesIO()
        fig.savefig(b, format="png", dpi=120, bbox_inches="tight")
        images.append(base64.b64encode(b.getvalue()).decode())
    plt.close("all")
    return json.dumps({"stdout": buf.getvalue(), "images": images, "error": err})
`;

// Builds the DataFrames + a convenience 'part' table (one row per session,
// joined to survey metrics) and a colorful plot_xy() helper.
const SETUP_PY = `
import json as _json
import pandas as pd
import matplotlib.pyplot as plt

try:
    plt.style.use("seaborn-v0_8-darkgrid")
except OSError:
    plt.style.use("ggplot")
plt.rcParams.update({"figure.facecolor": "white", "axes.titlesize": 12, "font.size": 10})

_d = _json.loads(_data_json)
_NB_GLOBALS.clear()
sessions = pd.DataFrame(_d.get("sessions", []))
messages = pd.DataFrame(_d.get("messages", []))
runs = pd.DataFrame(_d.get("runs", []))
annotations = pd.DataFrame(_d.get("annotations", []))
snapshots = pd.DataFrame(_d.get("snapshots", []))
surveys = pd.DataFrame(_d.get("surveys", []))

_UP = "i'm uploading"
def _first_prompt_words(sid):
    if messages.empty:
        return None
    m = messages[(messages.loaded_id == sid) & (messages.role.str.lower() == "user")]
    for _, r in m.sort_values("ts_epoch").iterrows():
        c = (r.get("content") or "").strip()
        if c and not c.lower().startswith(_UP):
            return len(c.split())
    return None

part = sessions.copy()
if not part.empty:
    part["pid"] = part["participant"].str.upper()
    part["init_words"] = part["loaded_id"].map(_first_prompt_words)
    if not surveys.empty:
        pre = surveys[surveys.phase == "pre"] if "phase" in surveys.columns else surveys
        keep = [c for c in ["participant_id", "expertise_score", "confidence", "est_time_minutes"]
                if c in pre.columns]
        part = part.merge(pre[keep].rename(columns={"participant_id": "pid"}), on="pid", how="left")

    # --- effort / interaction metrics (interaction = user msgs + manual saves) ---
    _rn = runs.groupby("loaded_id").size() if not runs.empty else pd.Series(dtype="int64")
    part["n_runs"] = part["loaded_id"].map(_rn).fillna(0).astype(int)
    if not messages.empty:
        _um = messages[messages["role"].str.lower() == "user"].copy()
        _um = _um[~_um["content"].fillna("").str.strip().str.lower().str.startswith(_UP)]
        _umn = _um.groupby("loaded_id").size()
    else:
        _umn = pd.Series(dtype="int64")
    part["n_user_msgs"] = part["loaded_id"].map(_umn).fillna(0).astype(int)
    if not snapshots.empty and "event_type" in snapshots.columns:
        _sv = snapshots[snapshots["event_type"] == "manual_save"].groupby("loaded_id").size()
    else:
        _sv = pd.Series(dtype="int64")
    part["n_saves"] = part["loaded_id"].map(_sv).fillna(0).astype(int)
    part["interactions"] = part["n_user_msgs"] + part["n_saves"]
    part["runs_per_interaction"] = part["n_runs"] / part["interactions"].replace(0, pd.NA)

    # --- time on task ---------------------------------------------------------
    # duration_min = first→last activity (span, includes any breaks);
    # active_min   = sum of inter-event gaps <= IDLE_GAP_MIN (break-robust proxy).
    _frames = [df[["loaded_id", "ts_epoch"]] for df in (messages, runs, snapshots)
               if not df.empty and "ts_epoch" in df.columns]
    _ev = (pd.concat(_frames, ignore_index=True).dropna(subset=["ts_epoch"])
           if _frames else pd.DataFrame(columns=["loaded_id", "ts_epoch"]))
    IDLE_GAP_MIN = 3.0
    _rows = []
    for _lid, _g in _ev.groupby("loaded_id"):
        _ts = _g["ts_epoch"].sort_values().to_numpy()
        if len(_ts) >= 2:
            _diffs = (_ts[1:] - _ts[:-1]) / 60.0
            _rows.append({"loaded_id": _lid, "duration_min": float((_ts[-1] - _ts[0]) / 60.0),
                          "active_min": float(_diffs[_diffs <= IDLE_GAP_MIN].sum())})
        else:
            _rows.append({"loaded_id": _lid, "duration_min": 0.0, "active_min": 0.0})
    if _rows:
        part = part.merge(pd.DataFrame(_rows), on="loaded_id", how="left")
    else:
        part["duration_min"] = 0.0
        part["active_min"] = 0.0
    part["runs_per_min"] = part["n_runs"] / part["duration_min"].replace(0, pd.NA)
    part["min_per_run"] = part["duration_min"] / part["n_runs"].replace(0, pd.NA)
    part["runs_per_active_min"] = part["n_runs"] / part["active_min"].replace(0, pd.NA)

import numpy as np

_PALETTE = {"agile": "#2563eb", "waterfall": "#dc2626", "demo": "#059669"}

def heatmap_over_time(points, value_col, title, vmin=None, vmax=None):
    # Rows ranked by expertise; hue = workflow (Blues agile / Reds waterfall),
    # darkness = value_col, step-held over time. 'points' has loaded_id,
    # elapsed_min, <value_col>.
    if points.empty or part.empty:
        print("no data for heatmap"); return
    order2 = part.sort_values("expertise_score", na_position="last").reset_index(drop=True)
    n = len(order2)
    tmax = float(points["elapsed_min"].max())
    if not (tmax > 0):
        tmax = 1.0
    bins = np.arange(0.0, tmax + 1.0, 1.0)
    if len(bins) < 2:
        bins = np.array([0.0, tmax])
    grid = np.full((n, len(bins) - 1), np.nan)
    for i, lid in enumerate(order2["loaded_id"]):
        g = points[points["loaded_id"] == lid].sort_values("elapsed_min")
        if g.empty:
            continue
        t = g["elapsed_min"].to_numpy(); v = g[value_col].to_numpy()
        for bi in range(len(bins) - 1):
            m = t <= bins[bi]
            if m.any():
                grid[i, bi] = v[m][-1]
    if vmin is None:
        vmin = np.nanmin(grid)
    if vmax is None:
        vmax = np.nanmax(grid)
    fig, ax = plt.subplots(figsize=(10, 7))
    wf = order2["workflow_mode"].to_numpy()
    Y = np.arange(n + 1) - 0.5
    for name, cmap in (("agile", "Blues"), ("waterfall", "Reds")):
        rm = (wf == name)
        if not rm.any():
            continue
        M = np.where(rm[:, None], grid, np.nan)
        ax.pcolormesh(bins, Y, M, cmap=cmap, vmin=vmin, vmax=vmax, shading="flat")
    ax.set_yticks(range(n))
    ax.set_yticklabels([f"{p} (e={e})" for p, e in zip(order2["participant"], order2["expertise_score"])])
    ax.set_xlabel("Minutes since first message"); ax.set_title(title); ax.set_ylim(-0.5, n - 0.5)

def plot_xy(xcol, ycol, xlabel=None, ylabel=None, title=None):
    if part.empty or xcol not in part.columns or ycol not in part.columns:
        print("no data for", xcol, "x", ycol); return
    sub = part.dropna(subset=[xcol, ycol])
    fig, ax = plt.subplots(figsize=(7, 5))
    for wf, g in sub.groupby("workflow_mode"):
        ax.scatter(g[xcol], g[ycol], s=110, alpha=0.85, label=wf,
                   color=_PALETTE.get(wf, "#7c3aed"), edgecolor="white", linewidth=1.4, zorder=3)
        for _, r in g.iterrows():
            ax.annotate(r["participant"], (r[xcol], r[ycol]), fontsize=8,
                        xytext=(5, 5), textcoords="offset points")
    ax.set_xlabel(xlabel or xcol); ax.set_ylabel(ylabel or ycol)
    ax.set_title(title or (ycol + " vs " + xcol)); ax.legend(title="workflow")
    fig.tight_layout()

for _k in ("pd", "plt", "np", "sessions", "messages", "runs", "annotations", "snapshots",
           "surveys", "part", "plot_xy", "heatmap_over_time"):
    _NB_GLOBALS[_k] = eval(_k)
_NB_GLOBALS["PALETTE"] = _PALETTE
`;

export interface CellResult {
  stdout: string;
  images: string[]; // base64 PNG
  error: string | null;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Pyodide = any;
let _pyodidePromise: Promise<Pyodide> | null = null;

function injectScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.src = src;
    el.onload = () => resolve();
    el.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(el);
  });
}

export async function getPyodide(onStatus?: (s: string) => void): Promise<Pyodide> {
  if (_pyodidePromise) return _pyodidePromise;
  _pyodidePromise = (async () => {
    const idx = indexUrl();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    if (!(window as any).loadPyodide) {
      onStatus?.("downloading Pyodide runtime…");
      await injectScript(`${idx}pyodide.js`);
    }
    onStatus?.("starting Python…");
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const py = await (window as any).loadPyodide({ indexURL: idx });
    onStatus?.("loading pandas + matplotlib…");
    await py.loadPackage(["pandas", "matplotlib"]);
    await py.runPythonAsync(RUNNER_PY);
    onStatus?.("ready");
    return py;
  })();
  return _pyodidePromise;
}

export async function loadDataset(py: Pyodide, dataset: unknown): Promise<void> {
  py.globals.set("_data_json", JSON.stringify(dataset));
  await py.runPythonAsync(SETUP_PY);
}

export function runCell(py: Pyodide, code: string): CellResult {
  const fn = py.globals.get("_run_cell");
  try {
    const raw = fn(code) as string;
    return JSON.parse(raw) as CellResult;
  } finally {
    fn.destroy?.();
  }
}
