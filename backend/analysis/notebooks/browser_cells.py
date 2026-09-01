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
#               (expertise_score, quiz_score, confidence, est_time_minutes,
#                init_words, n_runs, n_user_msgs, n_saves, interactions,
#                runs_per_interaction, duration_min, active_min, runs_per_min,
#                min_per_run, runs_per_active_min)
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
#   - `coverage` (0-7): +1 per CANONICAL (briefed) term present & active (nonzero
#     weight), regardless of type = travel_time + 3 hard + 3 soft. Only the briefed
#     terms count, so the score is comparable across sessions.
#   - `hard_bonus` (0-3): +1 per hard constraint correctly **binding** (type `hard`
#     OR weight > every non-hard term's weight).
#   - `objective_bonus` (0-1): +1 if travel_time is present AND not marked `hard`
#     (i.e. it's the target, not a constraint).
#   - `soft_covered` (0-3): soft prefs present (driver pref / workload / express).
#   - `captured_terms`: the list of ALL goal terms present & active at that snapshot
#     (objective + 3 hard + 3 soft + any un-briefed/custom term), "identified" NOT
#     necessarily binding — a SUPERSET of the canonical `coverage` set. Un-briefed
#     terms a user surfaces (e.g. idle-wait `waiting_time`) appear here but are NOT
#     scored, so the 0-11 total stays comparable.
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
# Overall distribution of self-rated expertise, colored by workflow (agile/waterfall).
# expertise_score = mean of the 5 pre-task Likert items (1-7). Stacked histogram, so
# you see the overall shape AND the per-arm composition in one plot.
_e = part.dropna(subset=["expertise_score"])
_bins = np.arange(1, 7.5, 0.5)
fig, ax = plt.subplots(figsize=(7, 4.5))
ax.hist([_e[_e.workflow_mode == wfm]["expertise_score"].values for wfm in ["agile", "waterfall"]],
        bins=_bins, stacked=True, color=[PALETTE["agile"], PALETTE["waterfall"]],
        label=["agile", "waterfall"], edgecolor="white")
ax.set_xlabel("Self-rated expertise (mean of 5 Likert items, 1-7)")
ax.set_ylabel("participants"); ax.set_title("Distribution of self-rated expertise (stacked by workflow)")
ax.legend(title="workflow"); fig.tight_layout()
print(f"overall: n={len(_e)}  mean={_e['expertise_score'].mean():.2f}  median={_e['expertise_score'].median():.2f}")
for wfm in ["agile", "waterfall"]:
    s = _e[_e.workflow_mode == wfm]["expertise_score"]
    if len(s):
        print(f"  {wfm:<9} n={len(s)}  mean={s.mean():.2f}  median={s.median():.2f}  "
              f"sd={s.std(ddof=1):.2f}  range[{s.min():.1f}, {s.max():.1f}]")

# %%
# Does ELABORATION on the experience question track self-rated expertise? Hypothesis:
# someone with real experience may write MORE on "Have you ever studied or worked with
# optimization, operations research, ...", which need NOT match their self-perceived
# expertise. experience_words = word count of that free-text answer (the TEXT stays
# server-side; only the count is exposed). Counts are right-skewed (many 1-word "no"),
# so read Spearman (rank) over Pearson.
if "experience_words" not in part.columns:
    print("experience_words not in `part` - restart the backend (new survey field), Reload data, re-run.")
else:
    from scipy import stats
    _pe = part.dropna(subset=["experience_words", "expertise_score"])
    plot_xy("experience_words", "expertise_score",
            "Words in experience answer", "Self-rated expertise (1-7)",
            "Self-rated expertise vs elaboration on the experience question")
    r, pr = stats.pearsonr(_pe["experience_words"], _pe["expertise_score"])
    rs, ps = stats.spearmanr(_pe["experience_words"], _pe["expertise_score"])
    print(f"experience_words vs expertise_score (n={len(_pe)}):")
    print(f"  Spearman rho={rs:.2f} p={ps:.3f}   (robust to the word-count skew)")
    print(f"  Pearson  r={r:.2f} p={pr:.3f}")
    print("  A weak correlation would mean elaboration captures experience that the")
    print("  self-rating misses (or vice versa) - a measurement point worth noting.")

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
# Runs per time: agile vs waterfall. runs_per_min = runs / wall-clock minutes;
# runs_per_active_min = runs / ACTIVE minutes (excludes >3min idle gaps). Both from
# `part`. EXPLORATORY (n~13/group): report the effect size + 95% CI, not just a p.
from scipy import stats
_metrics = [("runs_per_min", "Runs / min"),
            ("runs_per_active_min", "Runs / active min (excludes >3min inactivity)")]
_have = [mt for mt in _metrics if mt[0] in part.columns]
if not _have:
    print("runs_per_min not in `part` - Reload data.")
else:
    _se = lambda x: x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0
    fig, axes = plt.subplots(1, len(_have), figsize=(5 * len(_have), 4.4), squeeze=False)
    for ax, (col, name) in zip(axes[0], _have):
        a = part[part.workflow_mode == "agile"][col].dropna()
        w = part[part.workflow_mode == "waterfall"][col].dropna()
        diff = a.mean() - w.mean()                                  # agile - waterfall
        sed = np.sqrt(a.var(ddof=1) / len(a) + w.var(ddof=1) / len(w))
        lo, hi = diff - 1.96 * sed, diff + 1.96 * sed
        pooled = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(w) - 1) * w.var(ddof=1)) / (len(a) + len(w) - 2))
        d = diff / pooled if pooled > 0 else 0.0                    # Cohen's d (+ = agile faster)
        va, vw = a.var(ddof=1), w.var(ddof=1)
        u_stat, pmw = stats.mannwhitneyu(a, w, alternative="two-sided")   # U-test (ranks)
        t_stat, pt = stats.ttest_ind(a, w, equal_var=False)              # Welch t-test (means)
        dof = (sed**4 / ((va / len(a))**2 / (len(a) - 1) + (vw / len(w))**2 / (len(w) - 1))
               if sed > 0 else float("nan"))                            # Welch-Satterthwaite df
        ax.bar([0, 1], [a.mean(), w.mean()], yerr=[_se(a), _se(w)],
               color=[PALETTE["agile"], PALETTE["waterfall"]], capsize=6)
        ax.scatter(np.zeros(len(a)), a, color="k", alpha=0.4, s=15)
        ax.scatter(np.ones(len(w)), w, color="k", alpha=0.4, s=15)
        ax.set_xticks([0, 1]); ax.set_xticklabels(["agile", "waterfall"])
        ax.set_title(f"{name}\nd={d:+.2f}  (t p={pt:.2f}, U p={pmw:.2f})")
        print(f"\n{name}:")
        print(f"   agile     mean={a.mean():.3f} sd={a.std(ddof=1):.3f} n={len(a)}")
        print(f"   waterfall mean={w.mean():.3f} sd={w.std(ddof=1):.3f} n={len(w)}")
        print(f"   diff(a-w)={diff:+.3f}   95% CI [{lo:+.3f}, {hi:+.3f}]   Cohen d={d:+.2f}")
        print(f"   t-test (Welch, MEANS):        t({dof:.1f}) = {t_stat:+.2f}   p = {pt:.3f}")
        print(f"   U-test (Mann-Whitney, RANKS): U = {u_stat:.0f}          p = {pmw:.3f}")
    axes[0][0].set_ylabel("runs per minute")
    fig.suptitle("Run frequency: agile vs waterfall"); fig.tight_layout()
    print("\nEXPLORATORY (n~13/group): read the effect size + CI, not the p-value.")

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
# Cumulative-best canonical cost over time (log): running best-so-far, one line per
# participant, colored by workflow. LEFT counts only FEASIBLE schedules (valid on
# >=80% of traffic seeds; a cheap-but-infeasible run is ignored). RIGHT uses ALL runs
# (no feasibility filter), so a participant with NO feasible run still appears — and
# some sit lower there because an infeasible schedule can be cheaper (rules violated).
rc = elapsed(runs, ["participant", "workflow_mode"]).dropna(subset=["canonical_cost"])


def _best_over_time(ax, df):
    for lid, g in df.sort_values(["loaded_id", "elapsed_min"]).groupby("loaded_id"):
        wf = g["workflow_mode"].iloc[0]
        col = PALETTE.get(wf, "#7c3aed")
        best = g["canonical_cost"].cummin()               # running best-so-far
        ax.plot(g["elapsed_min"], best, drawstyle="steps-post", lw=1.8, alpha=0.85, color=col)
        ax.annotate(g.iloc[-1]["participant"], (g.iloc[-1]["elapsed_min"], best.iloc[-1]),
                    fontsize=7, xytext=(3, 0), textcoords="offset points")
    ax.set_yscale("log"); ax.set_xlabel("Minutes since first message")


fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
_best_over_time(ax1, rc[rc["feasible"] == True])         # noqa: E712
_best_over_time(ax2, rc)
ax1.set_ylabel("Best canonical cost so far (log)")
ax1.set_title("FEASIBLE only")
ax2.set_title("ALL runs")
wf_legend(ax1, rc["workflow_mode"])
fig.suptitle("Cumulative-best canonical cost over time"); fig.tight_layout()

# %%
# Feasibility RATES: agile vs waterfall. (1) share of participants who EVER reached a
# feasible solution (the achievement outcome — Fisher exact); (2) per-participant
# fraction of runs that were feasible (how reliably they hit feasibility).
from scipy import stats
rc = runs.merge(part[["loaded_id", "participant", "workflow_mode"]], on="loaded_id").dropna(subset=["canonical_cost"])
rc["_feas"] = rc["feasible"] == True                     # noqa: E712
_pf = rc.groupby(["loaded_id", "workflow_mode"]).agg(
    ever=("_feas", "any"), rate=("_feas", "mean")).reset_index()
order = [w for w in ["agile", "waterfall"] if w in set(_pf.workflow_mode)]
_se = lambda x: x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0
ever = _pf.groupby("workflow_mode")["ever"].agg(["sum", "count"])

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
# (1) EVER reached a feasible solution (proportion of participants) + Fisher exact
props = [ever.loc[w, "sum"] / ever.loc[w, "count"] for w in order]
ax1.bar(range(len(order)), props, color=[PALETTE.get(w, "#7c3aed") for w in order], width=0.6)
for i, w in enumerate(order):
    ax1.text(i, props[i] + 0.02, f"{int(ever.loc[w, 'sum'])}/{int(ever.loc[w, 'count'])}", ha="center", fontweight="bold")
ax1.set_xticks(range(len(order))); ax1.set_xticklabels([w.capitalize() for w in order])
ax1.set_ylim(0, 1.05); ax1.set_ylabel("share who EVER reached feasible"); ax1.set_title("Reached a feasible solution")
if {"agile", "waterfall"} <= set(ever.index):
    ay, an = int(ever.loc["agile", "sum"]), int(ever.loc["agile", "count"])
    wy, wn = int(ever.loc["waterfall", "sum"]), int(ever.loc["waterfall", "count"])
    _, pf = stats.fisher_exact([[ay, an - ay], [wy, wn - wy]])
    ax1.text(0.98, 0.02, f"Fisher p={pf:.2f}", transform=ax1.transAxes, ha="right", va="bottom", fontsize=8, color="#555")
# (2) per-participant fraction of runs feasible, by workflow (mean +/- SE + points)
for i, w in enumerate(order):
    vals = _pf[_pf.workflow_mode == w]["rate"]
    ax2.bar(i, vals.mean(), yerr=_se(vals), color=PALETTE.get(w, "#7c3aed"), capsize=6, width=0.6)
    ax2.scatter(np.full(len(vals), i), vals, color="k", alpha=0.5, s=18)
ax2.set_xticks(range(len(order))); ax2.set_xticklabels([w.capitalize() for w in order])
ax2.set_ylim(0, 1.05); ax2.set_ylabel("fraction of runs feasible (per participant)"); ax2.set_title("Feasible-run rate")
fig.suptitle("Feasibility rates: agile vs waterfall"); fig.tight_layout()
print("ever reached feasible:", {w: f"{int(ever.loc[w, 'sum'])}/{int(ever.loc[w, 'count'])}" for w in order})
print("mean feasible-run rate:", {w: round(float(_pf[_pf.workflow_mode == w]['rate'].mean()), 2) for w in order})

# %%
# Compare the CUMULATIVE (best-achieved) canonical cost: agile vs waterfall. Each
# participant contributes ONE number = the minimum cost they reached (the endpoint of
# the cumulative-best curve). Lower = better. Cost spans orders of magnitude, so plot
# on a LOG axis, summarize with the MEDIAN, and test on log10 (Welch t) + ranks (U).
# LEFT = best FEASIBLE cost, among those who reached feasibility (the quality outcome,
# reduced n). RIGHT = best cost over ALL runs — includes infeasible "cheap" schedules,
# so it is NOT a clean quality measure (a never-feasible participant can look good).
from scipy import stats
rc = runs.merge(part[["loaded_id", "participant", "workflow_mode"]], on="loaded_id").dropna(subset=["canonical_cost"])
_bf = (rc[rc["feasible"] == True].groupby(["loaded_id", "workflow_mode"])["canonical_cost"]  # noqa: E712
       .min().rename("best").reset_index())
_ba = rc.groupby(["loaded_id", "workflow_mode"])["canonical_cost"].min().rename("best").reset_index()


def _compare_cost(ax, frame, title):
    order = [w for w in ["agile", "waterfall"] if w in set(frame.workflow_mode)]
    vals = [frame[frame.workflow_mode == w]["best"].dropna() for w in order]
    for i, (w, v) in enumerate(zip(order, vals)):
        ax.scatter(np.full(len(v), i) + np.linspace(-0.05, 0.05, len(v)), v,
                   color=PALETTE.get(w, "#7c3aed"), alpha=0.7, s=32)
        ax.hlines(v.median(), i - 0.25, i + 0.25, color="black", lw=2)          # median
    ax.set_yscale("log"); ax.set_xticks(range(len(order)))
    ax.set_xticklabels([f"{w}\n(n={len(v)})" for w, v in zip(order, vals)])
    ax.set_title(title)
    if len(order) == 2 and all(len(v) > 1 for v in vals):
        a, w = vals
        _, pmw = stats.mannwhitneyu(a, w, alternative="two-sided")               # ranks (scale-free)
        _, pt = stats.ttest_ind(np.log10(a), np.log10(w), equal_var=False)       # Welch on log10 cost
        ax.text(0.98, 0.97, f"median a={a.median():.0f}  w={w.median():.0f}\nt(log) p={pt:.2f}, U p={pmw:.2f}",
                transform=ax.transAxes, ha="right", va="top", fontsize=8, color="#555")


fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5), sharey=True)
_compare_cost(ax1, _bf, "Best FEASIBLE cost (quality)")
_compare_cost(ax2, _ba, "Best cost, ALL runs (incl. infeasible)")
ax1.set_ylabel("Best-achieved canonical cost (log; lower = better)")
fig.suptitle("Cumulative-best canonical cost: agile vs waterfall"); fig.tight_layout()
print("Best FEASIBLE cost (among reachers) — median by workflow:")
print(_bf.groupby("workflow_mode")["best"].agg(["median", "count"]).round(0).to_string())

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
# GOAL-TERM ORIGINS + FATE — who INITIATED each goal term and what became of it,
# from the MANUAL session-coding tags (annotations, anno_type='code').
#   INITIATOR = origin (user|agent) of the EARLIEST coded tag for that term
#               (row_ref "message:<id>" -> message time); sets the cell COLOR
#               (user=green; agent colored by workflow).
#   FATE (cell SHAPE):
#     - full box            = applied when first coded (no earlier standalone mention)
#     - lower-right half    = MENTIONED first, applied only LATER
#     - X marker            = mentioned but NEVER applied (dropped/declined/ignored)
# TWO figures: the split version above, then a COMBINED version where full and
# half box are folded together (applied at ANY time — immediacy ignored).
# Reads live from the coded tags, so re-code + Reload data + re-run to refresh.
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D as _L2D
_codes = (annotations[annotations.get("anno_type") == "code"].copy()
          if (not annotations.empty and "anno_type" in annotations.columns) else pd.DataFrame())
if "term" in _codes.columns:
    _codes = _codes[_codes["term"].notna()]
if _codes.empty:
    print("No coded origin+term tags in the dataset yet. Tag goal-term changes")
    print("(origin + term) in the Session-coding tab, then Reload data + re-run.")
else:
    # time of each coded change: row_ref "message:<source_id>" -> message ts_epoch
    _mt = messages[["source_id", "ts_epoch"]].copy()
    _mt["src"] = _mt["source_id"].astype(str)
    _codes["src"] = _codes["row_ref"].fillna("").astype(str).str.split(":").str[-1]
    _codes = _codes.merge(_mt[["src", "ts_epoch"]], on="src", how="left")

    # Per (session, term): initiator = origin of the earliest tag; fate from the
    # effect sequence. Within one exchange `applied` outranks a co-tagged mention
    # (sort key), so "applied on its first coded exchange" reads as a full box.
    _codes["_applied"] = _codes["effect"].isin(["applied", "removed"])  # removed ⇒ was applied
    _c = _codes.sort_values(["ts_epoch", "_applied"], ascending=[True, False], na_position="last")
    _g = _c.groupby(["loaded_id", "term"])
    _init = _g.agg(origin=("origin", "first"), first_applied=("_applied", "first"),
                   ever_applied=("_applied", "any")).reset_index()
    _init["fate"] = np.where(_init["first_applied"], "applied",
                    np.where(_init["ever_applied"], "applied_later", "never_applied"))
    _init = _init.merge(part[["loaded_id", "participant", "workflow_mode"]], on="loaded_id")

    CANON = ["travel_time", "lateness_penalty", "capacity_penalty", "shift_limit",
             "workload_balance", "worker_preference", "express_miss_penalty"]
    TLABEL = {"travel_time": "travel time", "lateness_penalty": "lateness", "capacity_penalty": "capacity",
              "shift_limit": "shift", "workload_balance": "workload", "worker_preference": "driver pref",
              "express_miss_penalty": "express", "waiting_time": "idle wait (optional)"}
    _seen = list(_init["term"].unique())
    rows_terms = [t for t in CANON if t in _seen] + sorted(t for t in _seen if t not in CANON)
    # ALL participants as columns (uniform width with the solver-change grid;
    # a fully gray column = no coded goal-term tags yet).
    cols = (part[["loaded_id", "participant", "workflow_mode"]].drop_duplicates()
            .assign(_o=lambda d: d.workflow_mode.map({"agile": 0, "waterfall": 1}).fillna(2))
            .sort_values(["_o", "participant"]).reset_index(drop=True))
    USER = "#16a34a"                          # user-initiated = green
    ABSENT_EDGE = "#e5e7eb"                   # faint outline keeps the grid visible on white
    def _cell(origin, wf):
        # user=green; agent-initiated colored BY WORKFLOW (agile=blue, waterfall=red).
        # Un-briefed terms (idle wait) use the SAME colors as everything else.
        if origin == "user":
            return USER
        if origin == "agent":
            return PALETTE.get(wf, "#7c3aed")
        return None                            # not coded / absent
    _look = {(r.loaded_id, r.term): (r.origin, r.fate) for r in _init.itertuples()}

    def _draw_fate_grid(combine):
        """The initiation+fate grid. combine=True folds `applied_later` into
        `applied` (full box), i.e. ignores WHEN the term was applied."""
        fig, ax = plt.subplots(figsize=(0.42 * len(cols) + 3.0, 0.5 * len(rows_terms) + 1.8))
        for xi, c in cols.iterrows():
            for yi, tm in enumerate(rows_terms):
                origin, fate = _look.get((c.loaded_id, tm), (None, None))
                col = _cell(origin, c.workflow_mode)
                if combine and fate == "applied_later":
                    fate = "applied"
                if fate == "applied":                      # full box
                    ax.add_patch(mpatches.Rectangle((xi, yi), 1, 1, edgecolor="white", facecolor=col))
                elif fate == "applied_later":              # mentioned first → lower-right half
                    ax.add_patch(mpatches.Rectangle((xi, yi), 1, 1, edgecolor=ABSENT_EDGE, facecolor="white"))
                    # y is inverted: (yi+1) is the visually LOWER edge of the cell.
                    ax.add_patch(mpatches.Polygon([(xi + 1, yi), (xi + 1, yi + 1), (xi, yi + 1)],
                                                  closed=True, edgecolor="white", facecolor=col))
                elif fate == "never_applied":              # mentioned, never landed → X
                    ax.add_patch(mpatches.Rectangle((xi, yi), 1, 1, edgecolor=ABSENT_EDGE, facecolor="white"))
                    ax.plot([xi + 0.22, xi + 0.78], [yi + 0.22, yi + 0.78], color=col, lw=2.2, zorder=3)
                    ax.plot([xi + 0.22, xi + 0.78], [yi + 0.78, yi + 0.22], color=col, lw=2.2, zorder=3)
                else:                                      # not coded / absent → white
                    ax.add_patch(mpatches.Rectangle((xi, yi), 1, 1, edgecolor=ABSENT_EDGE, facecolor="white"))
        _na = int((cols.workflow_mode == "agile").sum())          # agile | waterfall divider
        if 0 < _na < len(cols):
            ax.axvline(_na, color="black", lw=2)
        ax.set_xlim(0, len(cols)); ax.set_ylim(0, len(rows_terms)); ax.invert_yaxis()
        ax.set_xticks([x + 0.5 for x in range(len(cols))])
        ax.set_xticklabels(cols["participant"], rotation=90, fontsize=11)
        ax.set_yticks([y + 0.5 for y in range(len(rows_terms))])
        ax.set_yticklabels([TLABEL.get(t, t) for t in rows_terms], fontsize=12)
        ax.set_title("Goal-term initiation + fate (manual codes)"
                     + (" — applied immediately/later combined" if combine else ""), fontsize=13)
        # Legend BELOW the grid (not beside it) so the axes use the full width and
        # match the solver-change grid. The full-box and X entries are TEXT-ONLY
        # (empty handle) — the wording already says what the shape is.
        handles = [mpatches.Patch(color=USER, label="user-initiated"),
                   mpatches.Patch(color=PALETTE["agile"], label="agent-initiated (agile)"),
                   mpatches.Patch(color=PALETTE["waterfall"], label="agent-initiated (waterfall)"),
                   mpatches.Patch(facecolor="white", edgecolor=ABSENT_EDGE, label="empty = not coded / absent"),
                   _L2D([], [], ls="", label="full box = mentioned → applied"
                        + ("" if combine else " immediately"))]
        if not combine:
            handles.append(_L2D([0], [0], marker=6, ls="", color="#6b7280",
                                label="half box = mentioned → applied later"))
        handles.append(_L2D([], [], ls="", label="X = mentioned → never applied"))
        fig.legend(handles=handles, loc="lower center", ncol=4, fontsize=11)
        fig.tight_layout(rect=[0, 0.14, 1, 1])  # leave room for the bottom legend

    _draw_fate_grid(combine=False)   # split: immediate (full) vs later (half)
    _draw_fate_grid(combine=True)    # combined: applied at any time = full box

    # FATE SUMMARY — the "record this in our analysis" numbers: how many terms per
    # fate, split by workflow and by initiator origin.
    print("Goal-term fate counts (per session-term, from manual codes):")
    print(_init.pivot_table(index="workflow_mode", columns="fate", values="term",
                            aggfunc="count", fill_value=0).to_string())
    print("\nBy initiator origin:")
    print(_init.pivot_table(index="origin", columns="fate", values="term",
                            aggfunc="count", fill_value=0).to_string())
    _mna = _init[_init["fate"] == "never_applied"]
    if len(_mna):
        print("\nMentioned-but-never-applied terms:")
        for r in _mna.sort_values(["workflow_mode", "participant"]).itertuples():
            print(f"  {r.participant} ({r.workflow_mode}): {r.term} — raised by {r.origin or '?'}")

    print("Initiator of each goal term (earliest coded change), by workflow:")
    for wfm in ["agile", "waterfall"]:
        s = _init[_init.workflow_mode == wfm]
        ag, us = int((s.origin == "agent").sum()), int((s.origin == "user").sum())
        print(f"  {wfm:<9} agent-initiated {ag:>2} / user-initiated {us:>2}"
              + (f"  ({ag / (ag + us):.0%} agent)" if (ag + us) else ""))
    print("\nPer-term agent-initiated count (agile | waterfall):")
    for t in rows_terms:
        line = f"  {TLABEL.get(t, t):<12}"
        for wfm in ["agile", "waterfall"]:
            s = _init[(_init.term == t) & (_init.workflow_mode == wfm)]
            line += f"  {wfm[0]}:{int((s.origin == 'agent').sum())}/{len(s)}" if len(s) else f"  {wfm[0]}:-"
        print(line)
    print("\nNOTE: initiator = FIRST coded change for the term; re-code + Reload + re-run to update.")

# %%
# SEARCH-STRATEGY / SEARCH-PARAM initiation — who drives the SOLVER side of the
# work, from the accepted session-coding tags (type 'search-strategy' = algorithm
# switched; 'search-param' = solver knobs tuned within the same algorithm).
# Each accepted tag = one change EVENT (not first-only): stacked user/agent bars,
# grouped agile vs waterfall. user=green; agent colored by workflow (as in the
# fate map above).
# NOTE: each session's FIRST search-strategy tag is EXCLUDED — a strategy must be
# set before anything can run, so the initial selection is mandatory setup, not a
# "change". Only later switches count.
import matplotlib.patches as mpatches
_sc = (annotations[(annotations.get("anno_type") == "code")
                   & (annotations.get("type").isin(["search-strategy", "search-param"]))].copy()
       if (not annotations.empty and "type" in annotations.columns) else pd.DataFrame())
if _sc.empty:
    print("No accepted search-strategy/search-param tags yet. Accept them in the")
    print("Session-coding tab, then Reload data + re-run.")
else:
    _sc = _sc.merge(part[["loaded_id", "workflow_mode"]], on="loaded_id", how="left")
    _sc["origin"] = _sc["origin"].fillna("agent")
    # Timestamp each tag (row_ref "message:<source_id>" -> message time) so the
    # per-session FIRST strategy tag — the mandatory initial selection — can be
    # dropped from the counts.
    _mt = messages[["source_id", "ts_epoch"]].copy()
    _mt["src"] = _mt["source_id"].astype(str)
    _sc["src"] = _sc["row_ref"].fillna("").astype(str).str.split(":").str[-1]
    _sc = _sc.merge(_mt[["src", "ts_epoch"]], on="src", how="left")
    _strat = _sc[_sc["type"] == "search-strategy"].sort_values("ts_epoch", na_position="last")
    _initial_idx = _strat.groupby("loaded_id").head(1).index          # first per session
    _n_initial = len(_initial_idx)
    _sc = _sc.drop(index=_initial_idx)
    USER = "#16a34a"
    _n_sess = part.groupby("workflow_mode")["loaded_id"].nunique()
    counts = _sc.pivot_table(index=["workflow_mode", "type"], columns="origin",
                             values="loaded_id", aggfunc="count", fill_value=0)
    for col in ("user", "agent"):
        if col not in counts.columns:
            counts[col] = 0

    GROUPS = [("agile", "search-strategy"), ("agile", "search-param"),
              ("waterfall", "search-strategy"), ("waterfall", "search-param")]
    xs = [0, 1, 2.6, 3.6]  # gap between the agile and waterfall groups
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    for x, (wf, tp) in zip(xs, GROUPS):
        u = int(counts.loc[(wf, tp), "user"]) if (wf, tp) in counts.index else 0
        a = int(counts.loc[(wf, tp), "agent"]) if (wf, tp) in counts.index else 0
        ax.bar(x, u, width=0.8, color=USER)
        ax.bar(x, a, width=0.8, bottom=u, color=PALETTE.get(wf, "#7c3aed"))
        for y, v in ((u / 2, u), (u + a / 2, a)):
            if v:
                ax.text(x, y, str(v), ha="center", va="center", color="white",
                        fontsize=9, fontweight="bold")
        ax.text(x, u + a + 0.4, f"n={u + a}", ha="center", fontsize=8, color="#555")
    ax.set_xticks(xs)
    ax.set_xticklabels(["algo switch", "param tune", "algo switch", "param tune"])
    ax.text(0.5, -0.13, "agile", transform=ax.get_xaxis_transform(), ha="center", fontweight="bold")
    ax.text(3.1, -0.13, "waterfall", transform=ax.get_xaxis_transform(), ha="center", fontweight="bold")
    ax.set_ylabel("coded change events")
    ax.set_title("Who initiates search-strategy / search-parameter CHANGES\n"
                 "(each session's initial strategy selection excluded — mandatory setup)")
    ax.legend(handles=[mpatches.Patch(color=USER, label="user-initiated"),
                       mpatches.Patch(color=PALETTE["agile"], label="agent-initiated (agile)"),
                       mpatches.Patch(color=PALETTE["waterfall"], label="agent-initiated (waterfall)")],
              fontsize=8, bbox_to_anchor=(1.02, 1), loc="upper left")  # outside, clear of the bars
    fig.tight_layout()

    print(f"Excluded {_n_initial} initial strategy selection(s) (one per session — mandatory setup).")
    print("Search-CHANGE events by workflow / type / origin (per-session mean in parens):")
    for wf, tp in GROUPS:
        u = int(counts.loc[(wf, tp), "user"]) if (wf, tp) in counts.index else 0
        a = int(counts.loc[(wf, tp), "agent"]) if (wf, tp) in counts.index else 0
        ns = int(_n_sess.get(wf, 0)) or 1
        print(f"  {wf:<9} {tp:<15} user {u:>3} ({u / ns:.1f}/session)   agent {a:>3} ({a / ns:.1f}/session)"
              + (f"   ({u / (u + a):.0%} user)" if (u + a) else ""))

# %%
# SOLVER-CHANGE GRID — which sessions changed WHAT, field-level (cell-21 style).
# Rows = change kinds (strategy switch, epochs, population, early-stop knobs,
# per-algorithm params like cooling_rate/c1/pc…); columns = participants
# (agile | waterfall). From the `search_changes` frame — the VERIFIED structural
# diff layer (same source as the cfg Δ chips), so it needs no tagging and can't
# miss an event. Cell = COUNT of changes; fill = who drove them: user green,
# agent workflow-colored, DIAGONAL SPLIT when both (agent upper-left, user
# lower-right). Origin = deterministic (manual panel edit → user, else agent),
# overridden by an accepted search tag's origin on the same exchange. Each
# session's INITIAL strategy selection is excluded (mandatory setup, as in the
# bars above).
import matplotlib.patches as mpatches
if search_changes.empty:
    print("`search_changes` missing/empty — restart the backend (new dataset field)")
    print("and click Re-fetch & run all.")
else:
    _ev = search_changes.merge(part[["loaded_id", "participant", "workflow_mode"]], on="loaded_id")
    # drop each session's first algorithm event (the mandatory initial selection)
    _alg = _ev[_ev["field"] == "algorithm"].sort_values("ts_epoch", na_position="last")
    _ev = _ev.drop(index=_alg.groupby("loaded_id").head(1).index)
    # accepted-tag origin overrides, joined per exchange (row_ref)
    _tags = (annotations[(annotations.get("anno_type") == "code")
                         & (annotations.get("type").isin(["search-strategy", "search-param"]))]
             [["loaded_id", "row_ref", "type", "origin"]].dropna(subset=["origin"])
             if (not annotations.empty and "type" in annotations.columns) else pd.DataFrame())
    if not _tags.empty:
        _ev["_tag_type"] = np.where(_ev["field"] == "algorithm", "search-strategy", "search-param")
        _ev = _ev.merge(_tags.rename(columns={"origin": "_tag_origin", "type": "_tag_type"}),
                        on=["loaded_id", "row_ref", "_tag_type"], how="left")
        _ev["origin"] = _ev["_tag_origin"].fillna(_ev["origin"])

    # Collapse to the headline rows; every algorithm-specific hyperparameter
    # (pc/pm, c1/c2/w, cooling_rate, temp_init, sample_count, …) folds into one
    # "other knobs" row. Early-stop sub-knobs (patience/epsilon) fold into
    # "early stop".
    def _row_of(f):
        if f == "algorithm":
            return "strategy switch"
        if f == "epochs":
            return "epochs"
        if f == "pop_size":
            return "population"
        if f in ("early_stop", "early_stop_patience", "early_stop_epsilon"):
            return "early stop"
        if f == "max_sub_iter":
            return "max sub-iter"
        return "other knobs"
    _ev["field"] = _ev["field"].map(_row_of)
    # One event per EXCHANGE per row: co-changed knobs (e.g. c1+c2+w tuned
    # together in one reply) count once, not once per key.
    _ev = _ev.drop_duplicates(subset=["loaded_id", "row_ref", "field"])
    FLABEL = {}  # rows already carry their display names
    rows_f = [r for r in ["strategy switch", "epochs", "population", "early stop",
                          "max sub-iter", "other knobs"] if r in set(_ev["field"])]
    # ALL participants as columns (a fully gray column = never touched the solver)
    cols = (part[["loaded_id", "participant", "workflow_mode"]].drop_duplicates()
            .assign(_o=lambda d: d.workflow_mode.map({"agile": 0, "waterfall": 1}).fillna(2))
            .sort_values(["_o", "participant"]).reset_index(drop=True))
    USER = "#16a34a"; ABSENT = "#eceff1"
    agg = (_ev.groupby(["loaded_id", "field"])
           .agg(n=("field", "count"),
                has_user=("origin", lambda s: bool((s == "user").any())),
                has_agent=("origin", lambda s: bool((s != "user").any())))
           .reset_index())
    _look = {(r.loaded_id, r.field): (r.n, r.has_user, r.has_agent) for r in agg.itertuples()}
    fig, ax = plt.subplots(figsize=(0.42 * len(cols) + 3.0, 0.42 * len(rows_f) + 1.6))
    for xi, c in cols.iterrows():
        wf_col = PALETTE.get(c.workflow_mode, "#7c3aed")
        for yi, f in enumerate(rows_f):
            n, hu, ha = _look.get((c.loaded_id, f), (0, False, False))
            if not n:
                ax.add_patch(mpatches.Rectangle((xi, yi), 1, 1, edgecolor="white", facecolor=ABSENT))
                continue
            if hu and ha:   # both drove changes → diagonal split (y is inverted)
                ax.add_patch(mpatches.Polygon([(xi, yi), (xi + 1, yi), (xi, yi + 1)],
                                              closed=True, edgecolor="white", facecolor=wf_col))
                ax.add_patch(mpatches.Polygon([(xi + 1, yi), (xi + 1, yi + 1), (xi, yi + 1)],
                                              closed=True, edgecolor="white", facecolor=USER))
            else:
                ax.add_patch(mpatches.Rectangle((xi, yi), 1, 1, edgecolor="white",
                                                facecolor=USER if hu else wf_col))
            ax.text(xi + 0.5, yi + 0.5, str(n), ha="center", va="center",
                    color="white", fontsize=8, fontweight="bold")
    _na = int((cols.workflow_mode == "agile").sum())
    if 0 < _na < len(cols):
        ax.axvline(_na, color="black", lw=2)
    ax.set_xlim(0, len(cols)); ax.set_ylim(0, len(rows_f)); ax.invert_yaxis()
    ax.set_xticks([x + 0.5 for x in range(len(cols))])
    ax.set_xticklabels(cols["participant"], rotation=90, fontsize=7)
    ax.set_yticks([y + 0.5 for y in range(len(rows_f))])
    ax.set_yticklabels([FLABEL.get(f, f) for f in rows_f])
    ax.set_title("Solver changes per session — count + who drove them\n"
                 "(initial strategy selection excluded)")
    # Legend BELOW the grid — full-width axes, same as the fate map.
    fig.legend(handles=[mpatches.Patch(color=USER, label="user-driven"),
                        mpatches.Patch(color=PALETTE["agile"], label="agent-driven (agile)"),
                        mpatches.Patch(color=PALETTE["waterfall"], label="agent-driven (waterfall)"),
                        mpatches.Patch(facecolor="white", edgecolor="#374151", label="diagonal split = both"),
                        mpatches.Patch(color=ABSENT, label="never changed")],
               loc="lower center", ncol=5, fontsize=8)
    fig.tight_layout(rect=[0, 0.10, 1, 1])  # leave room for the bottom legend

    print("Change events per kind (agile | waterfall):")
    for f in rows_f:
        line = f"  {FLABEL.get(f, f):<16}"
        for wfm in ("agile", "waterfall"):
            s = _ev[(_ev["field"] == f) & (_ev["workflow_mode"] == wfm)]
            line += f"  {wfm[0]}:{len(s):>3} ({int((s['origin'] == 'user').sum())} user)"
        print(line)

# %%
# INTERACTIONS → OUTCOMES (print-only): breakthrough runs, big scoring jumps,
# and infeasible→feasible flips — from the accepted REASON labels + canonical
# run scores. All counts depend on the researcher's accepted labels: re-label +
# Re-fetch & run all to refresh.
if runs.empty or "canonical_cost" not in runs.columns:
    print("`runs` lacks canonical_cost — restart backend + Re-fetch & run all.")
else:
    _rr = (runs.dropna(subset=["canonical_cost"])
           .merge(part[["loaded_id", "participant", "workflow_mode"]], on="loaded_id")
           .sort_values(["loaded_id", "ts_epoch"]))
    _rr["ref"] = "run:" + _rr["source_id"].astype(str)
    _reas = (annotations[(annotations.get("anno_type") == "reason")]
             [["loaded_id", "row_ref", "reasons"]]
             if (not annotations.empty and "reasons" in annotations.columns) else pd.DataFrame())
    _rmap = {(r.loaded_id, r.row_ref): (r.reasons or []) for r in _reas.itertuples()} if not _reas.empty else {}

    # --- breakthroughs: first run reaching session-best (feasible-first) -----
    print("BREAKTHROUGH — first run reaching session-best (feasible-first):")
    from collections import Counter as _C
    _pos = {"agile": [], "waterfall": []}; _kept = _C()
    for lid, g in _rr.groupby("loaded_id"):
        g = g.reset_index(drop=True); wf = g["workflow_mode"].iloc[0]
        best = max(g.itertuples(), key=lambda r: (bool(r.feasible), -r.canonical_cost))
        bi = next(i for i, r in enumerate(g.itertuples())
                  if bool(r.feasible) == bool(best.feasible) and abs(r.canonical_cost - best.canonical_cost) < 1e-6)
        _pos[wf].append((bi + 1) / len(g))
        last = g.iloc[-1]
        _kept[(wf, bool(last.feasible) == bool(best.feasible)
               and abs(last.canonical_cost - best.canonical_cost) < 1e-6)] += 1
    for wf in ("agile", "waterfall"):
        med = float(np.median(_pos[wf])) if _pos[wf] else float("nan")
        print(f"  {wf:<10} median breakthrough position {med:.2f} of the run sequence "
              f"(n={len(_pos[wf])}); ended ON best: {_kept[(wf, True)]}, lost it: {_kept[(wf, False)]}")

    # --- big jumps: top-quartile improving transitions -----------------------
    _trans = []  # (wf, lid, prev_ts, ts, delta, reasons, flip)
    for lid, g in _rr.groupby("loaded_id"):
        g = g.reset_index(drop=True); wf = g["workflow_mode"].iloc[0]
        for i in range(1, len(g)):
            d = g["canonical_cost"].iloc[i] - g["canonical_cost"].iloc[i - 1]
            _trans.append((wf, lid, g["ts_epoch"].iloc[i - 1], g["ts_epoch"].iloc[i], d,
                           _rmap.get((lid, g["ref"].iloc[i]), []),
                           (not bool(g["feasible"].iloc[i - 1])) and bool(g["feasible"].iloc[i])))
    _imp = [t for t in _trans if t[4] < -1e-6]
    _thr = float(np.percentile([abs(t[4]) for t in _imp], 75)) if _imp else 0.0
    _jumps = [t for t in _imp if abs(t[4]) >= _thr]
    def _mix(ts):
        c = _C()
        for t in ts:
            for r in t[5]:
                c[r] += 1
        return c
    print(f"\nBIG JUMPS — improving transitions: {len(_imp)}; top-quartile threshold |Δ|≥{_thr:,.0f}; jumps: {len(_jumps)}")
    print(f"  reason mix on jumps:  {dict(_mix(_jumps).most_common(8))}")
    print(f"  reason mix over ALL labeled transitions: {dict(_mix([t for t in _trans if t[5]]).most_common(8))}")

    # jump-window dominance from accepted change tags (who made the changes)
    _mt = messages[["loaded_id", "source_id", "ts_epoch"]].copy()
    _mt["row_ref"] = "message:" + _mt["source_id"].astype(str)
    _ct = (annotations[(annotations.get("anno_type") == "code") & annotations.get("origin").notna()]
           .merge(_mt[["loaded_id", "row_ref", "ts_epoch"]], on=["loaded_id", "row_ref"], how="left"))
    _dom = {"agile": _C(), "waterfall": _C()}
    for wf, lid, t0, t1, _d, _rs, _f in _jumps:
        win = _ct[(_ct["loaded_id"] == lid) & (_ct["ts_epoch"] > t0) & (_ct["ts_epoch"] <= t1)]
        ao = int((win["origin"] == "agent").sum()); uo = int((win["origin"] == "user").sum())
        if ao or uo:
            _dom[wf]["agent-dominated" if ao > uo else ("user-dominated" if uo > ao else "tie")] += 1
    for wf in ("agile", "waterfall"):
        print(f"  {wf:<10} jump windows by dominant change origin: {dict(_dom[wf])}")

    # --- feasibility flips ---------------------------------------------------
    _flips = [t for t in _trans if t[6]]
    _partners = _C()
    for t in _flips:
        for r in t[5]:
            if r != "feasibility-fix":
                _partners[r] += 1
    print(f"\nFEASIBILITY — infeasible→feasible flips: {len(_flips)}")
    print(f"  causal partners of the flips (reason labels minus feasibility-fix): {dict(_partners.most_common(8))}")

# %%
# TUNING STYLE (print-only): who re-ranks, and how much weight tuning
# flip-flops (direction reversals on the same goal term). Uses the accepted
# change tags + the `weight_changes` events (per-exchange weight from→to).
if annotations.empty or "type" not in annotations.columns:
    print("No accepted change tags in the dataset yet.")
else:
    _wfm = dict(part[["loaded_id", "workflow_mode"]].itertuples(index=False))
    _pn = dict(part[["loaded_id", "participant"]].itertuples(index=False))
    # --- reranking -----------------------------------------------------------
    _rk = annotations[(annotations["anno_type"] == "code") & (annotations["type"] == "ranking")]
    from collections import Counter as _C
    print("RERANKING (accepted `ranking` change tags):")
    print(f"  events by origin: {dict(_C(_rk['origin'].dropna()))}")
    for wf in ("agile", "waterfall"):
        lids = [l for l, w in _wfm.items() if w == wf]
        who = sorted({_pn[l] for l in lids if ((_rk["loaded_id"] == l) & (_rk["origin"] == "user")).any()})
        print(f"  {wf:<10} participants who reranked THEMSELVES: {len(who)}/{len(lids)} -> {who}")

    # --- weight oscillation --------------------------------------------------
    if weight_changes.empty:
        print("\n`weight_changes` missing/empty — restart backend + Re-fetch & run all.")
    else:
        _wc = weight_changes.dropna(subset=["ts_epoch"]).copy()
        _wc["delta"] = pd.to_numeric(_wc["to"], errors="coerce") - pd.to_numeric(_wc["from"], errors="coerce")
        _wc = _wc[_wc["delta"].abs() > 1e-9]
        # origin of each weight change = the accepted weight tag on the same exchange+term
        _wt = annotations[(annotations["anno_type"] == "code") & (annotations["type"] == "weight")]
        _wc = _wc.merge(_wt[["loaded_id", "row_ref", "term", "origin"]],
                        on=["loaded_id", "row_ref", "term"], how="left")
        print("\nWEIGHT OSCILLATION (direction reversals on the same term):")
        for wf in ("agile", "waterfall"):
            n_ch = 0; rev = _C()
            for (lid, term), g in _wc[_wc["loaded_id"].map(_wfm) == wf].groupby(["loaded_id", "term"]):
                g = g.sort_values("ts_epoch"); n_ch += len(g)
                deltas = g["delta"].tolist(); origins = g["origin"].tolist()
                for i in range(1, len(deltas)):
                    if deltas[i] * deltas[i - 1] < 0:
                        rev[origins[i] if isinstance(origins[i], str) else "untagged"] += 1
            tot = sum(rev.values())
            print(f"  {wf:<10} {n_ch} weight changes, {tot} reversals"
                  f" ({tot / max(n_ch, 1):.0%}) — reverser origin: {dict(rev)}")

# %%
# IDLE-WAIT — an UNEXPECTED phenomenon (qualitative, NOT scored). The un-briefed
# `waiting_time` term was surfaced mid-session by several WATERFALL participants but
# NO AGILE participant ever revealed it. All who raised it dropped it before their
# final config, so it never entered the 0-11 formulation score. Snapshot-based ⇒ a
# LOWER BOUND (a term set & removed between saves is missed).
from scipy import stats
_ever = (snapshots.groupby("loaded_id")["captured_terms"]
         .apply(lambda s: int(any("waiting_time" in (t or []) for t in s))))
_iw = (_ever.rename("idle_wait_ever").reset_index()
       .merge(part[["loaded_id", "workflow_mode"]], on="loaded_id"))
_tab = _iw.groupby("workflow_mode")["idle_wait_ever"].agg(["sum", "count"])
print("Idle-wait (waiting_time) EVER surfaced during a session:")
for wf, rr in _tab.iterrows():
    print(f"  {wf:<9} {int(rr['sum'])}/{int(rr['count'])}")
if {"agile", "waterfall"} <= set(_tab.index):
    ay, an = int(_tab.loc["agile", "sum"]), int(_tab.loc["agile", "count"])
    wy, wn = int(_tab.loc["waterfall", "sum"]), int(_tab.loc["waterfall", "count"])
    _, pf = stats.fisher_exact([[ay, an - ay], [wy, wn - wy]], alternative="two-sided")
    print(f"  Fisher exact p={pf:.3f}   (agile never revealed idle-wait)")

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
# Does measuring each participant's BEST formulation instead of their FINAL config
# change the agile-vs-waterfall picture? Formulations are non-monotonic (terms get
# added then dropped), so the last snapshot can understate what a participant reached.
# Per participant we take the session-MAX formulation_score and compare it, side by
# side with the FINAL score, agile vs waterfall (both 0-11). (EXPLORATORY.)
from scipy import stats
_ss = snapshots.dropna(subset=["formulation_score"]).sort_values(["loaded_id", "ts_epoch"])
_final = _ss.groupby("loaded_id")["formulation_score"].last().rename("final_score")
_max = _ss.groupby("loaded_id")["formulation_score"].max().rename("max_score")
mm = (pd.concat([_final, _max], axis=1).reset_index()
      .merge(part[["loaded_id", "participant", "workflow_mode"]], on="loaded_id"))
_se = lambda x: x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0

_cols = [("final_score", "FINAL score (0-11)"), ("max_score", "MAX score (0-11)")]
print("agile vs waterfall — final config vs each participant's best-ever formulation:")
for col, lab in _cols:
    a = mm[mm.workflow_mode == "agile"][col]
    w = mm[mm.workflow_mode == "waterfall"][col]
    _, p = stats.ttest_ind(a, w, equal_var=False)          # Welch headline test
    _, pu = stats.mannwhitneyu(a, w, alternative="two-sided")
    print(f"  {lab:<20} agile={a.mean():.2f}  waterfall={w.mean():.2f}  "
          f"diff={w.mean() - a.mean():+.2f}  Welch p={p:.2f}  MW p={pu:.2f}")

fig, axes = plt.subplots(1, 2, figsize=(9, 4), sharey=True)
for ax, (col, lab) in zip(axes, _cols):
    a = mm[mm.workflow_mode == "agile"][col]
    w = mm[mm.workflow_mode == "waterfall"][col]
    ax.bar([0, 1], [a.mean(), w.mean()], yerr=[_se(a), _se(w)],
           color=[PALETTE["agile"], PALETTE["waterfall"]], capsize=6)
    ax.scatter(np.zeros(len(a)), a, color="k", alpha=0.45, s=18)
    ax.scatter(np.ones(len(w)), w, color="k", alpha=0.45, s=18)
    ax.set_xticks([0, 1]); ax.set_xticklabels(["agile", "waterfall"]); ax.set_title(lab)
axes[0].set_ylabel("mean +/- SE"); axes[0].set_ylim(0, 11.5)
fig.suptitle("Formulation score: final config vs each participant's best")
fig.tight_layout()
print("\nNOTE: exploratory; 'max' = highest formulation_score at ANY snapshot (their peak).")

# %%
# Formulation quality: agile vs waterfall (11-point total = coverage(0-7) +
# hard_bonus(0-3) + objective_bonus(0-1)). Headline test on the FINAL snapshot;
# stacked composition for BOTH the FINAL config and each participant's best
# (MAX-score) snapshot; plus vs expertise (EXPLORATORY).
from scipy import stats
fq = (snapshots.dropna(subset=["formulation_score"]).sort_values(["loaded_id", "ts_epoch"])
      .groupby("loaded_id").tail(1)
      .merge(part[["loaded_id", "participant", "workflow_mode", "expertise_score"]], on="loaded_id"))
# best (MAX-score) snapshot per session: sort by score then time, take the top (ties -> latest)
fq_max = (snapshots.dropna(subset=["formulation_score"])
          .sort_values(["loaded_id", "formulation_score", "ts_epoch"])
          .groupby("loaded_id").tail(1)
          .merge(part[["loaded_id", "participant", "workflow_mode"]], on="loaded_id"))
SCORE, COV = "formulation_score", "coverage"  # the briefed 7-term coverage / 0-11 total
_se = lambda x: x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0


def _by_workflow(col):
    """agile vs waterfall arrays for one metric column (FINAL snapshot)."""
    return (fq[fq.workflow_mode == "agile"][col].dropna(),
            fq[fq.workflow_mode == "waterfall"][col].dropna())


# --- headline significance test: WELCH'S two-sample t-test on the FINAL TOTAL score
# Simplest widely-understood test for "do two groups differ on a numeric score",
# and — unlike Student's t or a pooled test — it does NOT assume the two groups
# share the same spread (your "are the distributions similar enough?" worry). Read
# the gap with a 95% CI + Cohen's d, not the p-value alone.
a, w = _by_workflow(SCORE)
diff = w.mean() - a.mean()                                       # waterfall - agile
va, vw = a.var(ddof=1), w.var(ddof=1)
se_diff = np.sqrt(va / len(a) + vw / len(w))
t, pt = stats.ttest_ind(a, w, equal_var=False)                  # Welch (unequal variance)
dof = se_diff**4 / ((va / len(a))**2 / (len(a) - 1) + (vw / len(w))**2 / (len(w) - 1))
tcrit = stats.t.ppf(0.975, dof)
pooled = np.sqrt(((len(a) - 1) * va + (len(w) - 1) * vw) / (len(a) + len(w) - 2))
d = diff / pooled                                               # Cohen's d (effect size)
print("TOTAL formulation score (0-11), FINAL config:")
print(f"  agile     n={len(a)}  mean={a.mean():.2f} +/- {_se(a):.2f} (SE)   sd={a.std(ddof=1):.2f}")
print(f"  waterfall n={len(w)}  mean={w.mean():.2f} +/- {_se(w):.2f} (SE)   sd={w.std(ddof=1):.2f}")
print(f"  Welch t({dof:.1f}) = {t:.2f}, p = {pt:.3f}   <-- headline test")
print(f"  gap (waterfall-agile) = {diff:.2f}   95% CI [{diff - tcrit * se_diff:.2f}, {diff + tcrit * se_diff:.2f}]   Cohen d = {d:.2f}")
u, pu = stats.mannwhitneyu(a, w, alternative="two-sided")       # rank-based confirmation
print(f"  Mann-Whitney U = {u:.0f}, p = {pu:.3f}   (nonparametric backup — also valid here)")
print("  READ: a >1-SE gap is NOT significance. For p~0.05 the gap must clear ~2x the SE")
print(f"        of the DIFFERENCE (wider than either group's SE). With n={len(a)}+{len(w)} this is")
print("        underpowered — if the 95% CI spans 0, call 'waterfall better' suggestive.")

# expertise correlation
r, pr = stats.pearsonr(fq.expertise_score, fq[SCORE])
print(f"\nExpertise vs formulation quality: Pearson r={r:.2f} p={pr:.3f} | "
      f"Spearman rho={stats.spearmanr(fq.expertise_score, fq[SCORE])[0]:.2f}")

# --- STACKED composition: total height = mean score, segments = its 3 parts
# (coverage + hard_bonus + objective_bonus == the total EXACTLY). Two panels: the
# FINAL config and each participant's BEST (MAX-score) snapshot; each panel carries
# its own agile-vs-waterfall gap + Welch t p + Mann-Whitney U p.
# Fills are WORKFLOW-themed (agile = blues, waterfall = reds — the same PALETTE
# hues as every other plot); the three score components are told apart by
# TINT + HATCH pattern, so the legend stays workflow-neutral (gray swatches).
import matplotlib.colors as _mcolors
import matplotlib.patches as mpatches


def _tint(color, f):
    """Mix a color toward white by fraction f (0 = base hue, 1 = white)."""
    r, g, b = _mcolors.to_rgb(color)
    return (r + (1 - r) * f, g + (1 - g) * f, b + (1 - b) * f)


# (column, label, hatch, tint-fraction): coverage = solid base hue at the bottom,
# bonuses get lighter tints + hatches.
comps = [(COV, "coverage (0-7)", "", 0.0),
         ("hard_bonus", "hard constraints (0-3)", "//", 0.35),
         ("objective_bonus", "objective (0-1)", "xx", 0.62)]
groups = ["agile", "waterfall"]


def _stacked(ax, frame, title, show_labels):
    bottom = np.zeros(len(groups))
    for col, lab, hatch, f in comps:
        vals = np.array([frame[frame.workflow_mode == g][col].mean() for g in groups])
        ax.bar(np.arange(len(groups)), vals, bottom=bottom, width=0.62,
               color=[_tint(PALETTE.get(g, "#7c3aed"), f) for g in groups],
               hatch=hatch, edgecolor="white", linewidth=1.0)
        for xi, v, b, g in zip(range(len(groups)), vals, bottom, groups):  # label tall-enough segments
            if v >= 0.6:
                ax.text(xi, b + v / 2, f"{v:.1f}", ha="center", va="center",
                        color=("white" if f < 0.5 else "#1f2937"), fontsize=8, fontweight="bold")
        bottom += vals
    for i, g in enumerate(groups):              # error bar (SE) + value on the TOTAL height
        tt = frame[frame.workflow_mode == g][SCORE]
        m, se = tt.mean(), _se(tt)
        ax.errorbar(i, m, yerr=se, color="black", capsize=7, lw=1.6, zorder=5)
        ax.text(i, m + se + 0.25, f"{m:.1f}", ha="center", fontweight="bold")
    _a = frame[frame.workflow_mode == "agile"][SCORE]
    _w = frame[frame.workflow_mode == "waterfall"][SCORE]
    if len(_a) and len(_w):                     # this panel's own gap + both tests
        _, _pt = stats.ttest_ind(_a, _w, equal_var=False)              # Welch t-test (means)
        _, _pu = stats.mannwhitneyu(_a, _w, alternative="two-sided")   # Mann-Whitney U (ranks)
        ax.text(0.98, 0.02, f"gap={_w.mean() - _a.mean():+.1f} (t p={_pt:.2f}, U p={_pu:.2f})",
                transform=ax.transAxes, ha="right", va="bottom", fontsize=8, color="#555")
    ax.set_xticks(range(len(groups))); ax.set_xticklabels([g.capitalize() for g in groups])
    ax.set_ylim(0, 11.5); ax.set_title(title)


fig, axes = plt.subplots(1, 2, figsize=(11, 5.5), sharey=True)
_stacked(axes[0], fq, "FINAL config", True)
_stacked(axes[1], fq_max, "MAX (best snapshot)", False)
axes[0].set_ylabel("Mean formulation score (0-11)")
# Workflow-neutral component legend: gray swatches carrying the tint + hatch.
_legend_handles = [
    mpatches.Patch(facecolor=_tint("#6b7280", f), hatch=hatch, edgecolor="white", label=lab)
    for _, lab, hatch, f in comps
]
fig.legend(handles=_legend_handles, loc="lower center", ncol=3, fontsize=8)
fig.suptitle("Formulation score and its components: agile vs waterfall (excluding the optional idle_wait goal term)")
fig.tight_layout(rect=[0, 0.06, 1, 1])

# --- total score vs expertise (fit line per workflow) ------------------------
fig, ax = plt.subplots(figsize=(7, 5))
for wf in ["agile", "waterfall"]:
    g = fq[fq.workflow_mode == wf]
    ax.scatter(g.expertise_score, g[SCORE], color=PALETTE.get(wf, "#7c3aed"), label=wf, s=45)
    b = np.polyfit(g.expertise_score, g[SCORE], 1)
    xs = np.array([g.expertise_score.min(), g.expertise_score.max()])
    ax.plot(xs, np.polyval(b, xs), color=PALETTE.get(wf, "#7c3aed"), lw=1.2, alpha=0.7)
ax.set_xlabel("Self-rated expertise"); ax.set_ylabel("Formulation score (0-11)")
ax.set_title(f"Formulation quality vs expertise (overall r={r:.2f}, p={pr:.3f})"); ax.legend()
fig.tight_layout()

# %%
# Post-session ratings: agile vs waterfall (part carries the post columns). n~13/group
# and ratings ceiling (~5-6/7) => UNDERPOWERED. We report ESTIMATION (effect size +
# 95% CI), not just a p. MW U is the a-priori test for these single Likert items;
# Welch t + Cohen's d are shown alongside for transparency. Do NOT pick the test by
# whichever gives the smaller p (that's p-hacking) — lead with the effect size.
from scipy import stats
_need = ["viz_clarity", "comm_accuracy", "solution_confidence"]
if not all(c in part.columns for c in _need) or part[_need].dropna(how="all").empty:
    print("Post ratings not found - upload the POST-task CSV and restart the backend (new survey fields), then Reload data.")
else:
    items = [("viz_clarity", "Visualization"), ("comm_accuracy", "Communication"),
             ("solution_confidence", "Solution confidence")]
    _se = lambda x: x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.4), sharey=True)
    for ax, (col, name) in zip(axes, items):
        a = part[part.workflow_mode == "agile"][col].dropna()
        w = part[part.workflow_mode == "waterfall"][col].dropna()
        diff = a.mean() - w.mean()                                  # agile - waterfall
        sed = np.sqrt(a.var(ddof=1) / len(a) + w.var(ddof=1) / len(w))
        lo, hi = diff - 1.96 * sed, diff + 1.96 * sed               # ~95% CI of the diff
        pooled = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(w) - 1) * w.var(ddof=1)) / (len(a) + len(w) - 2))
        d = diff / pooled if pooled > 0 else 0.0                    # Cohen's d (+ = agile higher)
        _, pmw = stats.mannwhitneyu(a, w, alternative="two-sided")  # a-priori test (Likert)
        _, pt = stats.ttest_ind(a, w, equal_var=False)             # Welch, shown for transparency
        ax.bar([0, 1], [a.mean(), w.mean()], yerr=[_se(a), _se(w)],
               color=[PALETTE["agile"], PALETTE["waterfall"]], capsize=6)
        ax.scatter(np.zeros(len(a)), a, color="k", alpha=0.4, s=15)
        ax.scatter(np.ones(len(w)), w, color="k", alpha=0.4, s=15)
        ax.set_xticks([0, 1]); ax.set_xticklabels(["agile", "waterfall"])
        ax.set_title(f"{name}\nd={d:+.2f}  (t p={pt:.2f}, U p={pmw:.2f})")
        print(f"{name:>20}: agile {a.mean():.2f}+/-{_se(a):.2f}  waterfall {w.mean():.2f}+/-{_se(w):.2f}  "
              f"diff(a-w)={diff:+.2f} 95%CI[{lo:+.2f},{hi:+.2f}]  d={d:+.2f}  MW p={pmw:.3f} | Welch p={pt:.3f}")
    axes[0].set_ylabel("Rating (1-7)"); axes[0].set_ylim(0, 7.5); fig.tight_layout()
    print("\nEXPLORATORY (n~13/group, ceiling'd): read the effect size + CI, NOT the p-value.")
    print("At this n only large effects (d>~1.1) are detectable, so non-significance is")
    print("EXPECTED — not evidence of 'no difference'. Report non-null d's (e.g. communication")
    print("favoring agile) as DIRECTIONAL patterns to confirm, with the CI shown.")

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

# %%
# WARM-UP QUIZ (measured conceptual understanding) vs FINAL FORMULATION QUALITY.
# quiz_score (part) = # correct of the 5 pre-task scenario MCQs (validity of a
# constraint-violating solution, trade-off logic, single-run inference,
# stochasticity, proxy objectives) — an OBJECTIVE knowledge measure, unlike the
# self-rated expertise Likerts (which predict nothing; see cells above).
# Three panels against the FINAL config, a decomposition left->right: the 0-11
# formulation total, its canonical-coverage part (0-7), and coverage's
# SOFT-PREFERENCE subset (0-3). The quiz effect CONCENTRATES in soft coverage —
# the discretionary side; hard-side coverage (objective + 3 hard) is flat vs
# quiz (rho~0.00: runs gate on hard constraints, so capturing them takes no
# conceptual insight). Report the total alongside the component, never the
# component alone.
# Both axes are small integers, so dots are JITTERED for visibility; black bar
# = group median; Spearman rho/p computed on the UNJITTERED values.
from scipy import stats
qd = (part[["loaded_id", "workflow_mode", "quiz_score"]]
      .merge(snapshots.dropna(subset=["formulation_score"])
             .sort_values(["loaded_id", "ts_epoch"]).groupby("loaded_id").tail(1)
             [["loaded_id", "formulation_score", "coverage", "soft_covered"]],
             on="loaded_id").dropna(subset=["quiz_score"]))
_rng = np.random.RandomState(0)
fig, axes = plt.subplots(1, 3, figsize=(12, 4), sharex=True)
for ax, (col, ylab) in zip(axes, [("formulation_score", "Formulation score (0-11)"),
                                  ("coverage", "Canonical coverage (0-7)"),
                                  ("soft_covered", "Soft prefs covered (0-3)")]):
    for _, rr in qd.iterrows():
        ax.scatter(rr["quiz_score"] + _rng.uniform(-0.13, 0.13),
                   rr[col] + _rng.uniform(-0.09, 0.09), s=42, alpha=0.75, zorder=3,
                   color=PALETTE.get(rr["workflow_mode"], "#7c3aed"),
                   edgecolors="white", linewidths=0.6)
    med = qd.groupby("quiz_score")[col].median()
    ax.plot(med.index, med.values, "k_", markersize=24, markeredgewidth=2.5,
            linestyle="none", zorder=4)
    ax.plot(med.index, med.values, color="0.4", lw=1.1, alpha=0.7, zorder=2)
    rho, pp = stats.spearmanr(qd["quiz_score"], qd[col])
    ax.set_title(f"{ylab}\nSpearman rho={rho:+.2f}, p={pp:.3f}", fontsize=10)
    ax.set_xlabel("Warm-up quiz score (of 5)")
    ax.set_xticks(sorted(qd["quiz_score"].unique()))
    ax.grid(axis="y", alpha=0.25)
axes[0].set_ylabel("Final-config value")
wf_legend(axes[0], qd["workflow_mode"])
fig.suptitle(f"Warm-up quiz vs final formulation quality (n={len(qd)}; points jittered)", y=1.04)
fig.tight_layout()
# Honesty prints: the hard side of coverage is UNRELATED to quiz (the whole
# coverage effect is the soft subset), and the quiz does NOT predict RUN
# quality (best feasible canonical cost) — only the formulation side.
qd["hard_side"] = qd["coverage"] - qd["soft_covered"]
rho, pp = stats.spearmanr(qd["quiz_score"], qd["hard_side"])
print(f"quiz vs hard-side coverage (objective+3 hard, 0-4): rho={rho:+.2f} p={pp:.3f}")
print("hard-side coverage counts:", qd["hard_side"].value_counts().sort_index().to_dict())
bf = runs[runs["feasible"] == True].groupby("loaded_id")["canonical_cost"].min()  # noqa: E712
qc = qd.merge(bf.rename("best_feasible"), on="loaded_id").dropna(subset=["best_feasible"])
if len(qc) >= 3:
    rho, pp = stats.spearmanr(qc["quiz_score"], np.log10(qc["best_feasible"]))
    print(f"quiz vs log10(best feasible canonical cost): rho={rho:+.2f} p={pp:.3f} n={len(qc)}")
print("quiz_score distribution:", qd["quiz_score"].value_counts().sort_index().to_dict())
