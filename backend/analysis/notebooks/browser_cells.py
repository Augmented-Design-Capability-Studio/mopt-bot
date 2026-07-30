# %% [markdown]
# # Notebook cells for the Aggregate tab
#
# The source of truth for what the in-browser notebook plots. Edit here in
# VS Code, then use **Import .py** in the Aggregate tab (it autosaves to the
# backend). Cells run inside Pyodide, so DON'T read files or use sqlite3 —
# the data is already loaded for you as DataFrames:
#
#   sessions, messages, runs, snapshots, annotations, surveys
#   part      -> one row per session, joined to survey metrics + effort/time
#               (expertise_score, confidence, est_time_minutes, init_words,
#                n_runs, n_user_msgs, n_saves, interactions, runs_per_interaction,
#                duration_min, active_min, runs_per_min, min_per_run,
#                runs_per_active_min)
#   plot_xy(xcol, ycol, xlabel, ylabel, title)  -> colored scatter by workflow
#   heatmap_over_time(points, value_col, title, vmin, vmax) -> expertise-ranked heatmap
#   PALETTE   -> {"agile": ..., "waterfall": ...}
#   pd, plt, np -> pandas, matplotlib.pyplot, numpy
#
# The next markdown cell explains HOW the backend derives every non-raw metric
# (canonical cost, feasibility, formulation score, constraint origins, edits).

# %%
# --- Preview of the loaded DataFrames ---
for _name, _df in [("sessions", sessions), ("messages", messages), ("runs", runs),
                   ("snapshots", snapshots), ("annotations", annotations),
                   ("surveys", surveys), ("part", part)]:
    print(f"{_name:<12} {_df.shape[0]:>6} rows x {_df.shape[1]:>2} cols")
print("\npart columns:", list(part.columns))
print("\npart preview (one row per session):")
print(part.head(8).to_string())

# %% [markdown]
# ## How the backend derives each metric
#
# Everything below is computed server-side (problem-specific logic lives in the
# VRPTW **study port**, `vrptw_problem/study_port.py`) and shipped ready-to-plot,
# so the notebook never re-implements scoring. Reference for the columns you'll use:
#
# **Per-run outcome quality** (`runs`, from `canonical_evaluation_for_result`):
# each run's produced *schedule* is re-scored under the **official 7-term objective**
# — independent of whatever weights the participant chose — averaged over
# `_CANON_SEEDS` random traffic draws.
#   - `canonical_cost` / `canonical_cost_std` = mean / std across those seeds
#     (the std is the error bar). Log scale everywhere; **lower = better**.
#   - `feasible` = robust flag: valid on >= 80% of traffic draws, where "valid" means
#     lateness = 0 **and** no capacity overflow **and** every shift <= 8h **and**
#     all orders covered. A low cost bought by breaking a hard rule does NOT count.
#
# **Per-config formulation quality** (`snapshots`, from `formulation_quality_for_config`).
# All-positive, no deductions: `formulation_score = coverage + hard_bonus + objective_bonus`
# (0-11, **higher = better**):
#   - `coverage` (0-7): +1 per canonical term present & active (nonzero weight),
#     regardless of type = travel_time + 3 hard + 3 soft.
#   - `hard_bonus` (0-3): +1 per hard constraint correctly **binding** (type `hard`
#     OR weight > every non-hard term's weight).
#   - `objective_bonus` (0-1): +1 if travel_time is present AND not marked `hard`
#     (i.e. it's the target, not a constraint).
#   - `soft_covered` (0-3): soft prefs present (driver pref / workload / express).
#   - `captured_terms`: the list of ALL goal terms present & active at that snapshot
#     (objective + 3 hard + 3 soft + custom) — this is the `coverage` set
#     (len == coverage), "identified" NOT necessarily binding.
#   - `objective_as_hard`, `soft_as_hard`: DESCRIPTIVE behavioral flags — NOT scored.
#
# **Goal-term origins** (`sessions.term_origins`, from `goal_term_origins`; the
# hard-only subset is also kept as `sessions.hard_origins`): who originated each
# goal term, reconstructed per assistant TURN from structured brief provenance —
# joined by `goal_key`, NO text parsing (not the sparse save snapshots). For a term:
# `user_volunteered` (appeared as a `gathered` item, no OQ), `agent_asked` (an
# open-question targeted it — waterfall's ask), `agent_assumed` (a `kind: assumption`
# item — agile's fait accompli), else `mixed` (assumption + OQ) / `present_other`
# (in the config but no provenance signal) / `absent`.
#
# **Goal-term edits** (`snapshots`): `weight_edits` / `type_edits` / `reranked` /
# `terms_added` / `terms_removed`, from structurally diffing each config against the
# previous one (no text parsing). `reranked` = a genuine reorder of terms that
# persisted (excludes the renumbering caused by add/remove).

# %%
# --- Shared helpers (run this cell before the plots below) -------------------
from matplotlib.lines import Line2D


def elapsed(df, cols=()):
    """Add elapsed_min = minutes since that session's FIRST message — the
    wall-clock x-axis for every over-time plot. Optionally left-merge extra
    per-session columns from `part` (e.g. participant, workflow_mode)."""
    start = messages.groupby("loaded_id")["ts_epoch"].min().rename("start")
    d = df.merge(start, on="loaded_id", how="left")
    d["elapsed_min"] = (d["ts_epoch"] - d["start"]) / 60.0
    if cols:
        d = d.merge(part[["loaded_id", *cols]], on="loaded_id", how="left")
    return d


def wf_legend(ax, present, title="workflow"):
    """Workflow color legend, showing only the modes that appear in `present`."""
    seen = set(pd.Series(list(present)).dropna())
    ax.legend(handles=[Line2D([0], [0], color=c, label=w)
                       for w, c in PALETTE.items() if w in seen], title=title)


def expertise_rows():
    """Session rows ranked low->high expertise, plus a loaded_id -> y-index map.
    Shared by every 'one row per participant' timeline/heatmap below."""
    order = part.sort_values("expertise_score", na_position="last").reset_index(drop=True)
    return order, {lid: i for i, lid in enumerate(order["loaded_id"])}


def rank_yticks(ax, order):
    """Label y ticks '<participant> (e=<expertise>)' for an expertise-ranked axis."""
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([f"{p} (e={e})" for p, e in zip(order["participant"], order["expertise_score"])])

# %%
# init_words = length of the participant's FIRST REAL prompt. The synthetic
# upload notice ("I'm uploading the following file(s): ...") is skipped when it
# comes first, so this measures how much the participant actually specified up
# front (see backend metrics.initial_prompt_word_count / SETUP's _first_prompt_words).
plot_xy("expertise_score", "init_words",
        "Self-rated expertise", "Initial prompt words (upload notice excluded)",
        "Initial prompt length x expertise")

# %%
plot_xy("expertise_score", "confidence",
        "Self-rated expertise", "Confidence to solve (1-7)",
        "Confidence x expertise")

# %%
plot_xy("expertise_score", "est_time_minutes",
        "Self-rated expertise", "Estimated minutes to solve",
        "Estimated time x expertise")

# %%
# interaction = user messages + manual saves (part[["n_user_msgs","n_saves"]]).
plot_xy("expertise_score", "runs_per_interaction",
        "Self-rated expertise", "Runs / interaction",
        "Runs-to-interaction ratio x expertise")

# %%
# Run timeline: x = minutes since first message; rows ranked by expertise (low->high).
order, ypos = expertise_rows()
r = elapsed(runs, ["workflow_mode"]).dropna(subset=["elapsed_min"])
fig, ax = plt.subplots(figsize=(9, 6))
for lid, g in r.groupby("loaded_id"):  # faint spine spanning each participant's runs
    ax.hlines(ypos.get(lid), g["elapsed_min"].min(), g["elapsed_min"].max(), color="#cbd5e1", lw=1, zorder=1)
for wf, g in r.groupby("workflow_mode"):
    ax.scatter(g["elapsed_min"], g["loaded_id"].map(ypos), s=55, alpha=0.85,
               color=PALETTE.get(wf, "#7c3aed"), label=wf, zorder=3)
rank_yticks(ax, order)
ax.set_xlabel("Minutes since first message")
ax.set_title("Run timeline - rows ranked by expertise (low -> high)")
ax.legend(title="workflow")

# %%
# Canonical cost per RUN INDEX, one curve per participant, colored by workflow.
# Canonical = re-scored under the official objective, so quality is comparable
# regardless of the weights the user chose (see the metrics explanation cell).
rc = runs.merge(part[["loaded_id", "participant", "workflow_mode"]], on="loaded_id", how="left")
rc = rc.dropna(subset=["canonical_cost"]).sort_values(["loaded_id", "session_run_index"])
fig, ax = plt.subplots(figsize=(9, 6))
for lid, g in rc.groupby("loaded_id"):
    wf = g["workflow_mode"].iloc[0]
    ax.errorbar(g["session_run_index"], g["canonical_cost"], yerr=g["canonical_cost_std"],
                marker="o", ms=3, lw=1.4, alpha=0.75, color=PALETTE.get(wf, "#7c3aed"),
                elinewidth=0.6, capsize=1.5)  # error bar = +/-1 std over the traffic seeds
    last = g.iloc[-1]
    ax.annotate(last["participant"], (last["session_run_index"], last["canonical_cost"]),
                fontsize=7, xytext=(3, 0), textcoords="offset points")
ax.set_yscale("log")  # canonical cost spans orders of magnitude
ax.set_xlabel("Run index")
ax.set_ylabel("Canonical cost (log scale - lower is better)")
ax.set_title("Canonical solution cost per run, by participant")
wf_legend(ax, rc["workflow_mode"])

# %%
# Same canonical cost, but x = MINUTES since first message (wall-clock, not run index).
rc = elapsed(runs, ["participant", "workflow_mode"]).dropna(subset=["canonical_cost"])
rc = rc.sort_values(["loaded_id", "elapsed_min"])
fig, ax = plt.subplots(figsize=(9, 6))
for lid, g in rc.groupby("loaded_id"):
    wf = g["workflow_mode"].iloc[0]
    ax.errorbar(g["elapsed_min"], g["canonical_cost"], yerr=g["canonical_cost_std"],
                marker="o", ms=3, lw=1.4, alpha=0.75, color=PALETTE.get(wf, "#7c3aed"),
                elinewidth=0.6, capsize=1.5)  # error bar = +/-1 std over the traffic seeds
    last = g.iloc[-1]
    ax.annotate(last["participant"], (last["elapsed_min"], last["canonical_cost"]),
                fontsize=7, xytext=(3, 0), textcoords="offset points")
ax.set_yscale("log")
ax.set_xlabel("Minutes since first message")
ax.set_ylabel("Canonical cost (log - lower is better)")
ax.set_title("Canonical solution cost over time, by participant")
wf_legend(ax, rc["workflow_mode"])

# %%
# Cumulative-best FEASIBLE cost over time. De-noises the raw curves AND only
# counts schedules that satisfy the true hard constraints (feasible == valid on
# >=80% of traffic seeds; see metrics cell). A cheap-but-infeasible run is ignored.
rc = elapsed(runs, ["participant", "workflow_mode"]).dropna(subset=["canonical_cost"])
feas = rc[rc["feasible"] == True].sort_values(["loaded_id", "elapsed_min"])  # noqa: E712
fig, ax = plt.subplots(figsize=(9, 6))
for lid, g in feas.groupby("loaded_id"):
    wf = g["workflow_mode"].iloc[0]
    col = PALETTE.get(wf, "#7c3aed")
    best = g["canonical_cost"].cummin()               # running best-so-far
    best_std = g["canonical_cost_std"].where(g["canonical_cost"] <= best).ffill()  # std of that best run
    ax.plot(g["elapsed_min"], best, drawstyle="steps-post", lw=1.8, alpha=0.85, color=col)
    ax.errorbar(g["elapsed_min"], best, yerr=best_std, fmt="none", ecolor=col,
                elinewidth=0.6, capsize=1.5, alpha=0.7)
    ax.annotate(g.iloc[-1]["participant"], (g.iloc[-1]["elapsed_min"], best.iloc[-1]),
                fontsize=7, xytext=(3, 0), textcoords="offset points")
ax.set_yscale("log")
ax.set_xlabel("Minutes since first message")
ax.set_ylabel("Best FEASIBLE canonical cost so far (log)")
ax.set_title("Cumulative-best feasible solution over time")
wf_legend(ax, feas["workflow_mode"])

# %%
# Feasibility check: is each participant's LOWEST-cost run actually valid?
# (A low canonical cost can be "bought" by violating hard constraints.)
rc = runs.merge(part[["loaded_id", "participant", "workflow_mode"]], on="loaded_id").dropna(subset=["canonical_cost"])
rows = []
for lid, g in rc.groupby("loaded_id"):
    best = g.loc[g["canonical_cost"].idxmin()]          # the single cheapest run
    fe = g[g["feasible"] == True]                        # noqa: E712  (its feasible runs)
    rows.append(dict(
        participant=g["participant"].iloc[0], workflow=g["workflow_mode"].iloc[0],
        best_cost=round(best["canonical_cost"]), best_feasible=bool(best["feasible"]),
        best_feasible_cost=(round(fe["canonical_cost"].min()) if len(fe) else None),
        feasible_rate=round((g["feasible"] == True).mean(), 2), n_runs=len(g)))  # noqa: E712
fs = pd.DataFrame(rows).sort_values("best_feasible")
print(fs.to_string(index=False))
print("\n# whose BEST run is infeasible:", int((~fs["best_feasible"]).sum()), "of", len(fs))
print("median feasible_rate by workflow:")
print(fs.groupby("workflow")["feasible_rate"].median().round(2).to_string())

# %%
# User-action timeline: rows ranked by expertise, faint workflow band per row,
# markers for each participant action (message | save | run).
order, ypos = expertise_rows()


def _ev(df):  # add elapsed_min + a y-position, dropping rows we can't place
    d = elapsed(df)
    d["y"] = d["loaded_id"].map(ypos)
    return d.dropna(subset=["y", "elapsed_min"])


um = messages[messages["role"].str.lower() == "user"].copy()
um = um[~um["content"].fillna("").str.strip().str.lower().str.startswith("i'm uploading")]  # drop upload notice
um, ru = _ev(um), _ev(runs)
sv = _ev(snapshots[snapshots["event_type"] == "manual_save"]) if not snapshots.empty else runs.iloc[0:0]

fig, ax = plt.subplots(figsize=(10, 7))
for lid, i in ypos.items():
    wf = order.loc[order["loaded_id"] == lid, "workflow_mode"].iloc[0]
    ax.axhspan(i - 0.5, i + 0.5, color=PALETTE.get(wf, "#7c3aed"), alpha=0.06)
ax.scatter(um["elapsed_min"], um["y"], marker="|", s=120, color="#475569", label="message", alpha=0.7)
if len(sv):
    ax.scatter(sv["elapsed_min"], sv["y"], marker="s", s=26, color="#f59e0b", label="save", alpha=0.85)
ax.scatter(ru["elapsed_min"], ru["y"], marker="o", s=34, color="#10b981", label="run", alpha=0.85)
rank_yticks(ax, order)
ax.set_xlabel("Minutes since first message")
ax.set_title("User-action timeline - rows ranked by expertise (band = workflow)")
ax.legend(loc="upper right")

# %%
# Final formulation quality (from each session's LAST snapshot), expertise-ranked.
# hard_bonus (0-3) = hard constraints correctly binding (see metrics cell);
# objective_as_hard / soft_as_hard are DESCRIPTIVE (not scored).
sp = snapshots.dropna(subset=["hard_bonus"]).sort_values(["loaded_id", "ts_epoch"])
final = sp.groupby("loaded_id").tail(1).merge(
    part[["loaded_id", "participant", "workflow_mode", "expertise_score"]], on="loaded_id")
final = final.sort_values("expertise_score", na_position="last")
fig, ax = plt.subplots(figsize=(8, 6))
ax.barh(range(len(final)), final["hard_bonus"],
        color=[PALETTE.get(w, "#7c3aed") for w in final["workflow_mode"]])
ax.set_yticks(range(len(final)))
ax.set_yticklabels([f"{p} (e={e})" for p, e in zip(final["participant"], final["expertise_score"])])
ax.set_xlim(0, 3)
ax.set_xlabel("Hard constraints binding (0-3)")
ax.set_title("Final formulation: hard constraints binding (color = workflow)")
print(final[["participant", "workflow_mode", "expertise_score", "hard_bonus",
             "objective_as_hard", "soft_as_hard"]].to_string(index=False))
print("\n(objective_as_hard / soft_as_hard are DESCRIPTIVE - not scored)")
print("by workflow (mean):")
print(final.groupby("workflow_mode")[["hard_bonus"]].mean().round(2).to_string())

# %%
# GOAL-TERM IDENTIFICATION over time — two coordinated views over ALL goal terms:
# the travel-time OBJECTIVE + 3 hard + 3 soft (+ any custom). This is coverage
# (0-7 canonical). "Captured/identified" = the term is present & active in the
# config (NOT necessarily binding); from the backend `captured_terms` list
# (== the coverage set; see metrics cell).
if "captured_terms" not in snapshots.columns:
    print("`captured_terms` missing from the dataset.")
    print("-> restart the backend (new field) and click Reload data, then re-run.")
else:
    # Canonical display order (objective first, then hard, then soft); unknown
    # custom terms fall back to their raw key and sort last.
    TLABEL = {"travel_time": "travel time (obj)",
              "lateness_penalty": "lateness", "capacity_penalty": "capacity", "shift_limit": "shift",
              "worker_preference": "driver pref", "workload_balance": "workload", "express_miss_penalty": "express"}
    ORDER = list(TLABEL)  # canonical ordering for colors + legend
    sp = elapsed(snapshots).dropna(subset=["elapsed_min"])
    sp = sp[sp["elapsed_min"] >= 0].copy()
    sp["ct"] = sp["captured_terms"].apply(lambda v: v if isinstance(v, list) else [])

    # (a) HOW MANY goal terms captured (= coverage), over time -> heatmap.
    # vmax adapts: 7 canonical, or higher if a custom term (e.g. waiting_time) is used.
    sp["n_terms"] = sp["ct"].apply(len)
    vmax = int(max(sp["n_terms"].max(), 7))
    heatmap_over_time(sp, "n_terms",
                      f"Goal terms captured over time (coverage; darker = more, 0-{vmax})", vmin=0, vmax=vmax)

    # (b) WHEN each INDIVIDUAL goal term was first identified, per participant.
    order, ypos = expertise_rows()
    ex = sp.explode("ct").dropna(subset=["ct"])                       # one row per (snapshot, goal term)
    first = ex.groupby(["loaded_id", "ct"])["elapsed_min"].min().reset_index()  # earliest capture time
    terms = [k for k in ORDER if k in set(first["ct"])] + \
            sorted(set(first["ct"]) - set(ORDER))                    # canonical first, custom last
    cidx = {k: plt.cm.tab10(i % 10) for i, k in enumerate(terms)}    # one color per goal term
    fig, ax = plt.subplots(figsize=(10, 7))
    for lid, i in ypos.items():
        wf = order.loc[order["loaded_id"] == lid, "workflow_mode"].iloc[0]
        ax.axhspan(i - 0.5, i + 0.5, color=PALETTE.get(wf, "#7c3aed"), alpha=0.05)  # band = workflow
    for k in terms:
        g = first[first["ct"] == k]
        ax.scatter(g["elapsed_min"], g["loaded_id"].map(ypos), s=70, color=cidx[k],
                   label=TLABEL.get(k, k), edgecolor="white", linewidth=0.8, zorder=3)
    rank_yticks(ax, order)
    ax.set_xlabel("Minutes since first message")
    ax.set_title("When each goal term was first identified (row band = workflow)")
    ax.legend(title="goal term", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)

# %%
# Origin of EVERY goal term per participant (objective + hard + soft + custom;
# was: hard constraints only).
#
# HOW ORIGINS ARE IDENTIFIED — from structured brief provenance reconstructed per
# assistant TURN, NO natural-language parsing (backend goal_term_origins). Each
# goal term is joined by its `goal_key`; across every turn-brief we read two
# structured signals — the requirement `items` (each carries a `kind`) and the
# `open_questions` (each may carry a `goal_key`) — and classify:
#   user_volunteered = appeared as a `gathered` item and NO OQ ever targeted it
#                      (the user stated it themselves);
#   agent_asked      = an open-question targeted its goal_key (waterfall's
#                      ask-then-confirm; the OQ drops once committed);
#   agent_assumed    = appeared as a `kind: assumption` item (agile's silent
#                      fait accompli);
#   mixed            = both an assumption item AND an OQ were seen for it;
#   present_other    = in the final config but with no provenance signal
#                      (a seeded default, or a panel edit with no brief item);
#   absent           = never present.
import matplotlib.patches as mpatches
if "term_origins" not in sessions.columns:
    print("`term_origins` missing from the dataset.")
    print("-> restart the backend (new field) and click Reload data, then re-run.")
else:
    COLORS = {"user_volunteered": "#16a34a", "agent_asked": "#2563eb", "agent_assumed": "#f59e0b",
              "mixed": "#a855f7", "present_other": "#94a3b8", "absent": "#e5e7eb"}
    TLABEL = {"travel_time": "travel time", "lateness_penalty": "lateness",
              "capacity_penalty": "capacity", "shift_limit": "shift", "worker_preference": "driver pref",
              "workload_balance": "workload", "express_miss_penalty": "express"}
    CANON = list(TLABEL)  # objective, then 3 hard, then 3 soft

    def _od(v):  # origins dict, robust to NaN/None
        return v if isinstance(v, dict) else {}

    seen = set().union(*[set(_od(v)) for v in sessions["term_origins"]]) if len(sessions) else set()
    terms = [k for k in CANON if k in seen] + sorted(seen - set(CANON))  # canonical first, custom last
    srt = sessions.copy()
    srt["wf_order"] = srt["workflow_mode"].map({"waterfall": 0, "agile": 1}).fillna(2)  # group by workflow
    srt = srt.sort_values(["wf_order", "participant"]).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(1.1 * len(terms) + 2, 8))
    for i, row in srt.iterrows():
        origins = _od(row["term_origins"])
        for j, k in enumerate(terms):  # one cell per (participant, goal term)
            ax.add_patch(mpatches.Rectangle((j, i), 1, 1, edgecolor="white",
                                            facecolor=COLORS.get(origins.get(k, "absent"), "#e5e7eb")))
    ax.set_xlim(0, len(terms)); ax.set_ylim(0, len(srt)); ax.invert_yaxis()
    ax.set_xticks([x + 0.5 for x in range(len(terms))])
    ax.set_xticklabels([TLABEL.get(k, k) for k in terms], rotation=40, ha="right")
    ax.set_yticks([y + 0.5 for y in range(len(srt))])
    ax.set_yticklabels([f"{p} ({str(w)[:4]})" for p, w in zip(srt["participant"], srt["workflow_mode"])])
    ax.set_title("Origin of each goal term per participant")
    labels = [("user volunteered", "user_volunteered"), ("agent asked (OQ)", "agent_asked"),
              ("agent assumed", "agent_assumed"), ("mixed", "mixed"),
              ("present (other)", "present_other"), ("absent", "absent")]
    ax.legend(handles=[mpatches.Patch(color=COLORS[c], label=l) for l, c in labels],
              bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)

# %%
# Holistic formulation score (final config) = coverage + hard_bonus + objective_bonus (0-11).
# objective_as_hard / soft_as_hard are DESCRIPTIVE columns, NOT part of the score.
sp = snapshots.dropna(subset=["formulation_score"]).sort_values(["loaded_id", "ts_epoch"])
final = sp.groupby("loaded_id").tail(1).merge(
    part[["loaded_id", "participant", "workflow_mode", "expertise_score"]], on="loaded_id")
final = final.sort_values("expertise_score", na_position="last")
fig, ax = plt.subplots(figsize=(8, 6))
ax.barh(range(len(final)), final["formulation_score"],
        color=[PALETTE.get(w, "#7c3aed") for w in final["workflow_mode"]])
ax.set_yticks(range(len(final)))
ax.set_yticklabels([f"{p} (e={e})" for p, e in zip(final["participant"], final["expertise_score"])])
ax.set_xlabel("Formulation score = coverage + hard-bonus + objective-bonus (0-11)")
ax.set_title("Holistic formulation score (color = workflow)")
print(final[["participant", "workflow_mode", "coverage", "hard_bonus", "objective_bonus",
             "objective_as_hard", "soft_as_hard", "formulation_score"]].to_string(index=False))
print("\n(objective_as_hard / soft_as_hard are DESCRIPTIVE - not scored)")
print("by workflow (mean):")
print(final.groupby("workflow_mode")[["coverage", "hard_bonus", "objective_bonus", "formulation_score"]].mean().round(2).to_string())

# %%
# Goal-term balancing timeline: when did each participant work on the WEIGHT /
# TYPE / RANK of goal terms? Edits are detected STRUCTURALLY by diffing each
# config against the previous one (see metrics cell) - no text parsing.
order, ypos = expertise_rows()
sp = elapsed(snapshots)
sp["y"] = sp["loaded_id"].map(ypos)
ru = elapsed(runs)
ru["y"] = ru["loaded_id"].map(ypos)
fig, ax = plt.subplots(figsize=(10, 7))
for lid, i in ypos.items():
    wf = order.loc[order["loaded_id"] == lid, "workflow_mode"].iloc[0]
    ax.axhspan(i - 0.5, i + 0.5, color=PALETTE.get(wf, "#7c3aed"), alpha=0.05)
ax.scatter(ru["elapsed_min"], ru["y"], marker="o", s=16, color="#cbd5e1", label="run", zorder=1)
sp["addrm"] = sp["terms_added"] + sp["terms_removed"]
# Each edit family gets its own vertical offset; marker size scales with # terms
# touched (rerank is a single reorder event, so it's unsized).
for col, color, off, lab, sized in [("weight_edits", "#2563eb", -0.28, "weight", True),
                                    ("type_edits", "#f59e0b", -0.09, "type/role", True),
                                    ("reranked", "#16a34a", 0.09, "rerank", False),
                                    ("addrm", "#a855f7", 0.28, "add/remove", True)]:
    e = sp[sp[col] > 0].dropna(subset=["y", "elapsed_min"])
    ax.scatter(e["elapsed_min"], e["y"] + off, marker="s", color=color, alpha=0.85,
               s=(e[col].clip(upper=5) * 16 if sized else 40), label=lab, zorder=3)
rank_yticks(ax, order)
ax.set_xlabel("Minutes since first message")
ax.set_title("Goal-term balancing over time (weight/type sized by # terms; rerank = reorder event)")
ax.legend(loc="upper right", fontsize=8)
tot = sp.groupby("loaded_id")[["weight_edits", "type_edits", "reranked", "addrm"]].sum().merge(
    part[["loaded_id", "workflow_mode"]], on="loaded_id")
print("goal-term edits by workflow (mean per participant):")
print(tot.groupby("workflow_mode")[["weight_edits", "type_edits", "reranked", "addrm"]].mean().round(1).to_string())

# %%
# Formulation score over time, one curve per participant (from config snapshots).
# Score = coverage + hard_bonus + objective_bonus (higher = better).
fs = elapsed(snapshots, ["participant", "workflow_mode"]).dropna(subset=["formulation_score"])
fs = fs[fs["elapsed_min"] >= 0].sort_values(["loaded_id", "elapsed_min"])
fig, ax = plt.subplots(figsize=(9, 6))
for lid, g in fs.groupby("loaded_id"):
    wf = g["workflow_mode"].iloc[0]
    ax.plot(g["elapsed_min"], g["formulation_score"], drawstyle="steps-post",
            marker="o", ms=3, lw=1.4, alpha=0.75, color=PALETTE.get(wf, "#7c3aed"))
    last = g.iloc[-1]
    ax.annotate(last["participant"], (last["elapsed_min"], last["formulation_score"]),
                fontsize=7, xytext=(3, 0), textcoords="offset points")
ax.set_xlabel("Minutes since first message")
ax.set_ylabel("Formulation score (higher = better)")
ax.set_title("Formulation score over time, by participant")
wf_legend(ax, fs["workflow_mode"])

# %%
# Formulation quality: agile vs waterfall, BROKEN OUT into the score's three
# components, plus vs expertise (n=16 - EXPLORATORY). Total score and each of
# coverage / hard_bonus / objective_bonus (all from the last snapshot per session).
from scipy import stats
fq = (snapshots.dropna(subset=["formulation_score"]).sort_values(["loaded_id", "ts_epoch"])
      .groupby("loaded_id").tail(1)
      .merge(part[["loaded_id", "participant", "workflow_mode", "expertise_score"]], on="loaded_id"))
_se = lambda x: x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0


def _by_workflow(col):
    """agile vs waterfall arrays for one metric column."""
    return (fq[fq.workflow_mode == "agile"][col].dropna(),
            fq[fq.workflow_mode == "waterfall"][col].dropna())


def _bar(ax, col, name):
    """Mean +/- SE bar (agile vs waterfall) with jittered points + Mann-Whitney p."""
    a, w = _by_workflow(col)
    u, p = stats.mannwhitneyu(a, w, alternative="two-sided")
    ax.bar([0, 1], [a.mean(), w.mean()], yerr=[_se(a), _se(w)],
           color=[PALETTE["agile"], PALETTE["waterfall"]], alpha=0.8, capsize=6)
    ax.scatter(np.zeros(len(a)), a, color="k", alpha=0.45, s=18)
    ax.scatter(np.ones(len(w)), w, color="k", alpha=0.45, s=18)
    ax.set_xticks([0, 1]); ax.set_xticklabels(["agile", "waterfall"])
    ax.set_title(f"{name}\n(MW p={p:.2f})")
    return a, w

# --- inferential detail on the TOTAL score (the headline comparison) ---------
a, w = _by_workflow("formulation_score")
print(f"agile     n={len(a)}  mean={a.mean():.2f} +/- {_se(a):.2f} (SE)   sd={a.std(ddof=1):.2f}")
print(f"waterfall n={len(w)}  mean={w.mean():.2f} +/- {_se(w):.2f} (SE)   sd={w.std(ddof=1):.2f}")
t, pt = stats.ttest_ind(a, w, equal_var=False)              # Welch (unequal variance)
u, pu = stats.mannwhitneyu(a, w, alternative="two-sided")   # rank-based (robust for n=16)
pooled = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(w) - 1) * w.var(ddof=1)) / (len(a) + len(w) - 2))
d = (w.mean() - a.mean()) / pooled                          # Cohen's d (effect size)
diff = w.mean() - a.mean()
se_diff = np.sqrt(a.var(ddof=1) / len(a) + w.var(ddof=1) / len(w))
print(f"diff (waterfall-agile) = {diff:.2f}  ~95% CI [{diff - 1.96 * se_diff:.2f}, {diff + 1.96 * se_diff:.2f}]")
print(f"Welch t={t:.2f}, p={pt:.3f} | Mann-Whitney U={u:.0f}, p={pu:.3f} | Cohen d={d:.2f}")
r, pr = stats.pearsonr(fq.expertise_score, fq.formulation_score)
print("\nExpertise vs formulation quality:")
print(f"  overall  Pearson r={r:.2f} p={pr:.3f} | Spearman rho={stats.spearmanr(fq.expertise_score, fq.formulation_score)[0]:.2f}")
for wf in ["agile", "waterfall"]:
    g = fq[fq.workflow_mode == wf]
    rr, pp = stats.pearsonr(g.expertise_score, g.formulation_score)
    print(f"  within {wf:<9} r={rr:.2f} p={pp:.3f} slope={np.polyfit(g.expertise_score, g.formulation_score, 1)[0]:.2f}")
print("\nNOTE: n=16 (8/group) - underpowered; read effect sizes + CIs, treat p-values cautiously.")

# --- total score + its 3 components, agile vs waterfall ----------------------
fig, axes = plt.subplots(1, 4, figsize=(14, 4))
_bar(axes[0], "formulation_score", "TOTAL score (0-11)")
_bar(axes[1], "coverage", "coverage (0-7)")
_bar(axes[2], "hard_bonus", "hard bonus (0-3)")
_bar(axes[3], "objective_bonus", "objective bonus (0-1)")
axes[0].set_ylabel("mean +/- SE")
fig.suptitle("Formulation score and its components: agile vs waterfall")
fig.tight_layout()

# --- total score vs expertise (fit line per workflow) ------------------------
fig, ax = plt.subplots(figsize=(7, 5))
for wf in ["agile", "waterfall"]:
    g = fq[fq.workflow_mode == wf]
    ax.scatter(g.expertise_score, g.formulation_score, color=PALETTE.get(wf, "#7c3aed"), label=wf, s=45)
    b = np.polyfit(g.expertise_score, g.formulation_score, 1)
    xs = np.array([g.expertise_score.min(), g.expertise_score.max()])
    ax.plot(xs, np.polyval(b, xs), color=PALETTE.get(wf, "#7c3aed"), lw=1.2, alpha=0.7)
ax.set_xlabel("Self-rated expertise"); ax.set_ylabel("Formulation score")
ax.set_title(f"Formulation quality vs expertise (overall r={r:.2f}, p={pr:.3f})"); ax.legend()
fig.tight_layout()

# %%
# Post-session ratings: agile vs waterfall (part already carries the post columns).
from scipy import stats
_need = ["viz_clarity", "comm_accuracy", "solution_confidence"]
if not all(c in part.columns for c in _need) or part[_need].dropna(how="all").empty:
    print("Post ratings not found - upload the POST-task CSV and restart the backend (new survey fields), then Reload data.")
else:
    items = [("viz_clarity", "Visualization"), ("comm_accuracy", "Communication"),
             ("solution_confidence", "Solution confidence")]
    _se = lambda x: x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), sharey=True)
    for ax, (col, name) in zip(axes, items):
        a = part[part.workflow_mode == "agile"][col].dropna()
        w = part[part.workflow_mode == "waterfall"][col].dropna()
        u, p = stats.mannwhitneyu(a, w, alternative="two-sided")
        ax.bar([0, 1], [a.mean(), w.mean()], yerr=[_se(a), _se(w)],
               color=[PALETTE["agile"], PALETTE["waterfall"]], alpha=0.8, capsize=6)
        ax.scatter(np.zeros(len(a)), a, color="k", alpha=0.4, s=15)
        ax.scatter(np.ones(len(w)), w, color="k", alpha=0.4, s=15)
        ax.set_xticks([0, 1]); ax.set_xticklabels(["agile", "waterfall"]); ax.set_title(f"{name} (MW p={p:.2f})")
        print(f"{name:>20}: agile {a.mean():.2f}+/-{_se(a):.2f}  waterfall {w.mean():.2f}+/-{_se(w):.2f}  MW p={p:.3f}")
    axes[0].set_ylabel("Rating (1-7)"); axes[0].set_ylim(0, 7.5); fig.tight_layout()
    print("NOTE: n=16, ratings ceilinged (~5-6/7) - underpowered; treat as exploratory.")

# %%
# Calibration: does post-session CONFIDENCE track ACTUAL solution quality?
from scipy import stats
if "solution_confidence" not in part.columns or part["solution_confidence"].isna().all():
    print("Post ratings not found - upload the POST-task CSV and restart the backend (new survey fields), then Reload data.")
else:
    bf = runs[runs["feasible"] == True].groupby("loaded_id")["canonical_cost"].min().rename("best_feasible")  # noqa: E712
    ever = runs.assign(_f=runs["feasible"] == True).groupby("loaded_id")["_f"].any().rename("ever_feasible")  # noqa: E712
    cal = part.merge(bf, on="loaded_id", how="left").merge(ever, on="loaded_id", how="left")
    ok = cal.dropna(subset=["solution_confidence", "best_feasible"])
    r, p = stats.pearsonr(ok["solution_confidence"], np.log10(ok["best_feasible"]))
    fig, ax = plt.subplots(figsize=(8, 5))
    for wf in ["agile", "waterfall"]:
        g = ok[ok.workflow_mode == wf]
        ax.scatter(g["solution_confidence"], g["best_feasible"], color=PALETTE.get(wf), label=wf, s=55)
        for _, row in g.iterrows():
            ax.annotate(row["participant"], (row["solution_confidence"], row["best_feasible"]),
                        fontsize=7, xytext=(4, 0), textcoords="offset points")
    ax.set_yscale("log")
    # Participants who NEVER reached feasibility have no best-feasible cost; park them
    # at the top of the plot as X markers, but COLOR them by workflow (red edge marks
    # the "never feasible" status) so they read consistently with the feasible points.
    ymax = ok["best_feasible"].max() * 3
    nf = cal[(cal["ever_feasible"] != True) & cal["solution_confidence"].notna()]  # noqa: E712
    for _, row in nf.iterrows():
        col = PALETTE.get(row["workflow_mode"], "#7c3aed")
        ax.scatter(row["solution_confidence"], ymax, marker="X", s=120,
                   color=col, edgecolor="red", linewidth=1.6, zorder=5)
        ax.annotate(f'{row["participant"]} (never feasible)', (row["solution_confidence"], ymax),
                    fontsize=7, color=col, xytext=(4, 0), textcoords="offset points")
    ax.set_xlabel("Post-session confidence (1-7)")
    ax.set_ylabel("Best-feasible canonical cost (log - lower = better)")
    ax.set_title(f"Confidence vs actual quality: r={r:.2f}, p={p:.2f} (flat/scattered = poor calibration)")
    ax.legend(); fig.tight_layout()
    print(f"confidence vs log(best-feasible cost): Pearson r={r:+.2f} p={p:.3f} (~0 => confidence does NOT track quality)")
    print("X (red-edged, colored by workflow) = participants who NEVER produced a feasible solution.")

# %%
# Initial prompt length vs OUTCOME quality (best feasible cost).
# init_words already excludes the synthetic upload notice (see cell 3 / metrics cell).
# best_feasible = lowest canonical cost among that participant's FEASIBLE runs
# (lower = better); participants who never reached feasibility are dropped.
from scipy import stats
bf = runs[runs["feasible"] == True].groupby("loaded_id")["canonical_cost"].min().rename("best_feasible")  # noqa: E712
d = part.merge(bf, on="loaded_id", how="left").dropna(subset=["init_words", "best_feasible"])
fig, ax = plt.subplots(figsize=(7, 5))
for wf, g in d.groupby("workflow_mode"):
    ax.scatter(g["init_words"], g["best_feasible"], s=110, alpha=0.85, label=wf,
               color=PALETTE.get(wf, "#7c3aed"), edgecolor="white", linewidth=1.4, zorder=3)
    for _, rr in g.iterrows():
        ax.annotate(rr["participant"], (rr["init_words"], rr["best_feasible"]),
                    fontsize=8, xytext=(5, 5), textcoords="offset points")
ax.set_yscale("log")  # best-feasible cost spans orders of magnitude
ax.set_xlabel("Initial prompt words (upload notice excluded)")
ax.set_ylabel("Best feasible canonical cost (log - lower = better)")
_title = "Initial prompt length x best feasible cost"
if len(d) >= 3:
    rho, pp = stats.spearmanr(d["init_words"], d["best_feasible"])  # rank corr (robust to log-scale outliers)
    _title += f" (Spearman rho={rho:.2f}, p={pp:.2f})"
ax.set_title(_title); ax.legend(title="workflow"); fig.tight_layout()

# %%
# Initial prompt length vs FINAL formulation quality (score 0-11; higher = better).
from scipy import stats
ffq = (snapshots.dropna(subset=["formulation_score"]).sort_values(["loaded_id", "ts_epoch"])
       .groupby("loaded_id").tail(1)[["loaded_id", "formulation_score"]])
d = part.merge(ffq, on="loaded_id", how="left").dropna(subset=["init_words", "formulation_score"])
fig, ax = plt.subplots(figsize=(7, 5))
for wf, g in d.groupby("workflow_mode"):
    ax.scatter(g["init_words"], g["formulation_score"], s=110, alpha=0.85, label=wf,
               color=PALETTE.get(wf, "#7c3aed"), edgecolor="white", linewidth=1.4, zorder=3)
    for _, rr in g.iterrows():
        ax.annotate(rr["participant"], (rr["init_words"], rr["formulation_score"]),
                    fontsize=8, xytext=(5, 5), textcoords="offset points")
ax.set_xlabel("Initial prompt words (upload notice excluded)")
ax.set_ylabel("Final formulation score (0-11)")
_title = "Initial prompt length x formulation quality"
if len(d) >= 3:
    r_, p_ = stats.pearsonr(d["init_words"], d["formulation_score"])
    _title += f" (Pearson r={r_:.2f}, p={p_:.2f})"
ax.set_title(_title); ax.legend(title="workflow"); fig.tight_layout()
