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
#   PALETTE   -> {"agile": ..., "waterfall": ...}
#   pd, plt   -> pandas, matplotlib.pyplot

# %%
# --- Preview of the loaded DataFrames ---
for _name, _df in [("sessions", sessions), ("messages", messages), ("runs", runs),
                   ("snapshots", snapshots), ("annotations", annotations),
                   ("surveys", surveys), ("part", part)]:
    print(f"{_name:<12} {_df.shape[0]:>6} rows x {_df.shape[1]:>2} cols")
print("\npart columns:", list(part.columns))
print("\npart preview (one row per session):")
print(part.head(8).to_string())

# %%
plot_xy("expertise_score", "init_words",
        "Self-rated expertise", "Initial prompt words",
        "Initial prompt length × expertise")

# %%
plot_xy("expertise_score", "confidence",
        "Self-rated expertise", "Confidence to solve (1–7)",
        "Confidence × expertise")

# %%
plot_xy("expertise_score", "est_time_minutes",
        "Self-rated expertise", "Estimated minutes to solve",
        "Estimated time × expertise")

# %%
# interaction = user messages + manual saves (see part[["n_user_msgs","n_saves"]]).
plot_xy("expertise_score", "runs_per_interaction",
        "Self-rated expertise", "Runs / interaction",
        "Runs-to-interaction ratio × expertise")

# %%
# Run timeline: x = minutes since first message; rows ranked by expertise (low→high).
start = messages.groupby("loaded_id")["ts_epoch"].min().rename("start")
r = runs.merge(start, on="loaded_id", how="left").merge(
    part[["loaded_id", "participant", "workflow_mode", "expertise_score"]],
    on="loaded_id", how="left")
r["elapsed_min"] = (r["ts_epoch"] - r["start"]) / 60.0

order = part.sort_values("expertise_score", na_position="last").reset_index(drop=True)
ypos = {lid: i for i, lid in enumerate(order["loaded_id"])}

fig, ax = plt.subplots(figsize=(9, 6))
rr = r.dropna(subset=["elapsed_min"])
for lid, g in rr.groupby("loaded_id"):
    y = ypos.get(lid)
    ax.hlines(y, g["elapsed_min"].min(), g["elapsed_min"].max(), color="#cbd5e1", lw=1, zorder=1)
for wf, g in rr.groupby("workflow_mode"):
    ax.scatter(g["elapsed_min"], g["loaded_id"].map(ypos), s=55, alpha=0.85,
               color=PALETTE.get(wf, "#7c3aed"), label=wf, zorder=3)
ax.set_yticks(range(len(order)))
ax.set_yticklabels([f"{p} (e={e})" for p, e in zip(order["participant"], order["expertise_score"])])
ax.set_xlabel("Minutes since first message")
ax.set_title("Run timeline — rows ranked by expertise (low → high)")
ax.legend(title="workflow")

# %%
# Canonical solution cost per run — one curve per participant, colored by
# workflow. Canonical = each run's schedule re-scored under the OFFICIAL 7-term
# objective, so quality is comparable regardless of the weights the user chose.
# (runs["canonical_cost"] is computed backend-side and shipped in the dataset.)
from matplotlib.lines import Line2D
rc = runs.merge(part[["loaded_id", "participant", "workflow_mode"]], on="loaded_id", how="left")
rc = rc.dropna(subset=["canonical_cost"]).sort_values(["loaded_id", "session_run_index"])
fig, ax = plt.subplots(figsize=(9, 6))
for lid, g in rc.groupby("loaded_id"):
    wf = g["workflow_mode"].iloc[0]
    ax.errorbar(g["session_run_index"], g["canonical_cost"], yerr=g["canonical_cost_std"],
                marker="o", ms=3, lw=1.4, alpha=0.75, color=PALETTE.get(wf, "#7c3aed"),
                elinewidth=0.6, capsize=1.5)  # error bars = +/-1 std over 10 traffic seeds
    last = g.iloc[-1]
    ax.annotate(last["participant"], (last["session_run_index"], last["canonical_cost"]),
                fontsize=7, xytext=(3, 0), textcoords="offset points")
ax.set_yscale("log")
ax.set_xlabel("Run index")
ax.set_ylabel("Canonical cost (log scale — lower is better)")
ax.set_title("Canonical solution cost per run, by participant")
ax.legend(handles=[Line2D([0], [0], color=c, label=w) for w, c in PALETTE.items()
                   if w in set(rc["workflow_mode"].dropna())], title="workflow")

# %%
# Same canonical cost, but x = MINUTES since first message (wall-clock, not run index).
from matplotlib.lines import Line2D
start = messages.groupby("loaded_id")["ts_epoch"].min().rename("start")
rc = runs.merge(start, on="loaded_id", how="left").merge(
    part[["loaded_id", "participant", "workflow_mode"]], on="loaded_id", how="left")
rc = rc.dropna(subset=["canonical_cost"]).copy()
rc["elapsed_min"] = (rc["ts_epoch"] - rc["start"]) / 60.0
rc = rc.sort_values(["loaded_id", "elapsed_min"])
fig, ax = plt.subplots(figsize=(9, 6))
for lid, g in rc.groupby("loaded_id"):
    wf = g["workflow_mode"].iloc[0]
    ax.errorbar(g["elapsed_min"], g["canonical_cost"], yerr=g["canonical_cost_std"],
                marker="o", ms=3, lw=1.4, alpha=0.75, color=PALETTE.get(wf, "#7c3aed"),
                elinewidth=0.6, capsize=1.5)  # error bars = +/-1 std over 10 traffic seeds
    last = g.iloc[-1]
    ax.annotate(last["participant"], (last["elapsed_min"], last["canonical_cost"]),
                fontsize=7, xytext=(3, 0), textcoords="offset points")
ax.set_yscale("log")
ax.set_xlabel("Minutes since first message")
ax.set_ylabel("Canonical cost (log — lower is better)")
ax.set_title("Canonical solution cost over time, by participant")
ax.legend(handles=[Line2D([0], [0], color=c, label=w) for w, c in PALETTE.items()
                   if w in set(rc["workflow_mode"].dropna())], title="workflow")

# %%
# Cumulative-best FEASIBLE cost over time — de-noises the curves AND only counts
# schedules that satisfy the true hard constraints (lateness, capacity, shift<=8h,
# all orders covered). A low cost bought by violating constraints doesn't count.
from matplotlib.lines import Line2D
start = messages.groupby("loaded_id")["ts_epoch"].min().rename("start")
rc = runs.merge(start, on="loaded_id").merge(part[["loaded_id", "participant", "workflow_mode"]], on="loaded_id")
rc = rc.dropna(subset=["canonical_cost"]).copy()
rc["elapsed_min"] = (rc["ts_epoch"] - rc["start"]) / 60.0
feas = rc[rc["feasible"] == True].sort_values(["loaded_id", "elapsed_min"])  # noqa: E712
fig, ax = plt.subplots(figsize=(9, 6))
for lid, g in feas.groupby("loaded_id"):
    g = g.sort_values("elapsed_min")
    wf = g["workflow_mode"].iloc[0]
    col = PALETTE.get(wf, "#7c3aed")
    best = g["canonical_cost"].cummin()
    is_min = g["canonical_cost"] <= best  # rows that (re)set the running best
    best_std = g["canonical_cost_std"].where(is_min).ffill()  # std of the best-so-far run
    ax.plot(g["elapsed_min"], best, drawstyle="steps-post", lw=1.8, alpha=0.85, color=col)
    ax.errorbar(g["elapsed_min"], best, yerr=best_std, fmt="none", ecolor=col,
                elinewidth=0.6, capsize=1.5, alpha=0.7)
    ax.annotate(g.iloc[-1]["participant"], (g.iloc[-1]["elapsed_min"], best.iloc[-1]),
                fontsize=7, xytext=(3, 0), textcoords="offset points")
ax.set_yscale("log")
ax.set_xlabel("Minutes since first message")
ax.set_ylabel("Best FEASIBLE canonical cost so far (log)")
ax.set_title("Cumulative-best feasible solution over time")
ax.legend(handles=[Line2D([0], [0], color=c, label=w) for w, c in PALETTE.items()
                   if w in set(feas["workflow_mode"].dropna())], title="workflow")

# %%
# Feasibility flag: is each participant's LOWEST-cost run actually valid?
# (A low canonical cost can be "bought" by violating hard constraints.)
rc = runs.merge(part[["loaded_id", "participant", "workflow_mode"]], on="loaded_id").dropna(subset=["canonical_cost"])
rows = []
for lid, g in rc.groupby("loaded_id"):
    g = g.sort_values("session_run_index")
    best = g.loc[g["canonical_cost"].idxmin()]
    fe = g[g["feasible"] == True]  # noqa: E712
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
order = part.sort_values("expertise_score", na_position="last").reset_index(drop=True)
ypos = {lid: i for i, lid in enumerate(order["loaded_id"])}
start = messages.groupby("loaded_id")["ts_epoch"].min().rename("start")

def _ev(df):
    d = df.merge(start, on="loaded_id", how="left")
    d["elapsed_min"] = (d["ts_epoch"] - d["start"]) / 60.0
    d["y"] = d["loaded_id"].map(ypos)
    return d.dropna(subset=["y", "elapsed_min"])

um = messages[messages["role"].str.lower() == "user"].copy()
um = um[~um["content"].fillna("").str.strip().str.lower().str.startswith("i'm uploading")]
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
ax.set_yticks(range(len(order)))
ax.set_yticklabels([f"{p} (e={e})" for p, e in zip(order["participant"], order["expertise_score"])])
ax.set_xlabel("Minutes since first message")
ax.set_title("User-action timeline — rows ranked by expertise (band = workflow)")
ax.legend(loc="upper right")

# %%
# Final formulation quality (from each session's last snapshot), expertise-ranked.
# hard_bonus 0-3 = the handout's hard constraints (lateness, capacity, shift)
# that are binding (type 'hard' OR weight > every non-hard term). soft_covered =
# of {driver pref, workload, express}. objective_as_hard / soft_as_hard = descriptive (not scored).
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
ax.set_xlabel("Hard constraints captured (0-3)")
ax.set_title("Final formulation: hard constraints captured (color = workflow)")
print(final[["participant", "workflow_mode", "expertise_score", "hard_bonus",
             "objective_as_hard", "soft_as_hard"]].to_string(index=False))
print("\n(objective_as_hard / soft_as_hard are DESCRIPTIVE — not scored)")
print("by workflow (mean):")
print(final.groupby("workflow_mode")[["hard_bonus"]].mean().round(2).to_string())

# %%
# Heatmap: formulation quality (hard constraints captured, 0-3) over time.
# Rows ranked by expertise; blue=agile / red=waterfall; darker = more captured.
start = messages.groupby("loaded_id")["ts_epoch"].min().rename("start")
sp = snapshots.dropna(subset=["hard_bonus"]).merge(start, on="loaded_id", how="left")
sp["elapsed_min"] = (sp["ts_epoch"] - sp["start"]) / 60.0
sp = sp[sp["elapsed_min"] >= 0]
heatmap_over_time(sp, "hard_bonus", "Hard constraints captured over time (darker = more, 0-3)", vmin=0, vmax=3)

# %%
# Heatmap: best-FEASIBLE canonical cost over time (darker = lower cost = better).
start = messages.groupby("loaded_id")["ts_epoch"].min().rename("start")
rc = runs.merge(start, on="loaded_id").dropna(subset=["canonical_cost"]).copy()
rc["elapsed_min"] = (rc["ts_epoch"] - rc["start"]) / 60.0
rc = rc[rc["feasible"] == True].sort_values(["loaded_id", "elapsed_min"])  # noqa: E712
rc["best_so_far"] = rc.groupby("loaded_id")["canonical_cost"].cummin()
rc["quality"] = -np.log10(rc["best_so_far"].clip(lower=1))  # higher = better = darker
heatmap_over_time(rc, "quality", "Best feasible cost over time (darker = lower cost)")

# %%
# Origin of each hard constraint per participant (from structured brief provenance,
# reconstructed per assistant turn). user_volunteered = user stated it;
# agent_asked = agent raised an open-question (waterfall's ask); agent_assumed =
# agent committed it silently (agile fait accompli).
import matplotlib.patches as mpatches
COLORS = {"user_volunteered": "#16a34a", "agent_asked": "#2563eb", "agent_assumed": "#f59e0b",
          "mixed": "#a855f7", "present_other": "#94a3b8", "absent": "#e5e7eb"}
HARD = ["lateness_penalty", "capacity_penalty", "shift_limit"]
srt = sessions.copy()
srt["wf_order"] = srt["workflow_mode"].map({"waterfall": 0, "agile": 1}).fillna(2)
srt = srt.sort_values(["wf_order", "participant"]).reset_index(drop=True)
fig, ax = plt.subplots(figsize=(6, 8))
for i, row in srt.iterrows():
    origins = row["hard_origins"] if isinstance(row["hard_origins"], dict) else {}
    for j, k in enumerate(HARD):
        o = origins.get(k, "absent")
        ax.add_patch(mpatches.Rectangle((j, i), 1, 1, facecolor=COLORS.get(o, "#e5e7eb"), edgecolor="white"))
ax.set_xlim(0, len(HARD)); ax.set_ylim(0, len(srt)); ax.invert_yaxis()
ax.set_xticks([x + 0.5 for x in range(len(HARD))]); ax.set_xticklabels(["lateness", "capacity", "shift"])
ax.set_yticks([y + 0.5 for y in range(len(srt))])
ax.set_yticklabels([f"{p} ({str(w)[:4]})" for p, w in zip(srt["participant"], srt["workflow_mode"])])
ax.set_title("Origin of hard constraints per participant")
labels = [("user volunteered", "user_volunteered"), ("agent asked (OQ)", "agent_asked"),
          ("agent assumed", "agent_assumed"), ("mixed", "mixed"), ("absent", "absent")]
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
print("\n(objective_as_hard / soft_as_hard are DESCRIPTIVE — not scored)")
print("by workflow (mean):")
print(final.groupby("workflow_mode")[["coverage", "hard_bonus", "objective_bonus", "formulation_score"]].mean().round(2).to_string())

# %%
# Goal-term balancing timeline: when did each participant work on the WEIGHT /
# TYPE / RANK of goal terms? (edits detected structurally by diffing configs.)
order = part.sort_values("expertise_score", na_position="last").reset_index(drop=True)
ypos = {lid: i for i, lid in enumerate(order["loaded_id"])}
start = messages.groupby("loaded_id")["ts_epoch"].min().rename("start")
sp = snapshots.merge(start, on="loaded_id", how="left")
sp["elapsed_min"] = (sp["ts_epoch"] - sp["start"]) / 60.0
sp["y"] = sp["loaded_id"].map(ypos)
ru = runs.merge(start, on="loaded_id", how="left")
ru["elapsed_min"] = (ru["ts_epoch"] - ru["start"]) / 60.0
ru["y"] = ru["loaded_id"].map(ypos)
fig, ax = plt.subplots(figsize=(10, 7))
for lid, i in ypos.items():
    wf = order.loc[order["loaded_id"] == lid, "workflow_mode"].iloc[0]
    ax.axhspan(i - 0.5, i + 0.5, color=PALETTE.get(wf, "#7c3aed"), alpha=0.05)
ax.scatter(ru["elapsed_min"], ru["y"], marker="o", s=16, color="#cbd5e1", label="run", zorder=1)
sp["addrm"] = sp["terms_added"] + sp["terms_removed"]
# reranked = a genuine reorder of existing terms (not the add/remove cascade).
for col, color, off, lab, sized in [("weight_edits", "#2563eb", -0.28, "weight", True),
                                    ("type_edits", "#f59e0b", -0.09, "type/role", True),
                                    ("reranked", "#16a34a", 0.09, "rerank", False),
                                    ("addrm", "#a855f7", 0.28, "add/remove", True)]:
    e = sp[sp[col] > 0].dropna(subset=["y", "elapsed_min"])
    ax.scatter(e["elapsed_min"], e["y"] + off, marker="s", color=color, alpha=0.85,
               s=(e[col].clip(upper=5) * 16 if sized else 40), label=lab, zorder=3)
ax.set_yticks(range(len(order)))
ax.set_yticklabels([f"{p} (e={e})" for p, e in zip(order["participant"], order["expertise_score"])])
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
from matplotlib.lines import Line2D
start = messages.groupby("loaded_id")["ts_epoch"].min().rename("start")
fs = snapshots.dropna(subset=["formulation_score"]).merge(start, on="loaded_id", how="left")
fs["elapsed_min"] = (fs["ts_epoch"] - fs["start"]) / 60.0
fs = fs[fs["elapsed_min"] >= 0].merge(
    part[["loaded_id", "participant", "workflow_mode"]], on="loaded_id", how="left")
fs = fs.sort_values(["loaded_id", "elapsed_min"])
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
ax.legend(handles=[Line2D([0], [0], color=c, label=w) for w, c in PALETTE.items()
                   if w in set(fs["workflow_mode"].dropna())], title="workflow")

# %%
# Formulation quality: agile vs waterfall, and does expertise matter? (n=16 — EXPLORATORY)
from scipy import stats
fq = (snapshots.dropna(subset=["formulation_score"]).sort_values(["loaded_id", "ts_epoch"])
      .groupby("loaded_id").tail(1)
      .merge(part[["loaded_id", "participant", "workflow_mode", "expertise_score"]], on="loaded_id"))
a = fq[fq.workflow_mode == "agile"]["formulation_score"]
w = fq[fq.workflow_mode == "waterfall"]["formulation_score"]
_se = lambda x: x.std(ddof=1) / np.sqrt(len(x))
print(f"agile     n={len(a)}  mean={a.mean():.2f} +/- {_se(a):.2f} (SE)   sd={a.std(ddof=1):.2f}")
print(f"waterfall n={len(w)}  mean={w.mean():.2f} +/- {_se(w):.2f} (SE)   sd={w.std(ddof=1):.2f}")
t, pt = stats.ttest_ind(a, w, equal_var=False)
u, pu = stats.mannwhitneyu(a, w, alternative="two-sided")
pooled = np.sqrt(((len(a)-1)*a.var(ddof=1) + (len(w)-1)*w.var(ddof=1)) / (len(a)+len(w)-2))
d = (w.mean() - a.mean()) / pooled
se_diff = np.sqrt(a.var(ddof=1)/len(a) + w.var(ddof=1)/len(w))
diff = w.mean() - a.mean()
print(f"diff (waterfall-agile) = {diff:.2f}  ~95% CI [{diff-1.96*se_diff:.2f}, {diff+1.96*se_diff:.2f}]")
print(f"Welch t={t:.2f}, p={pt:.3f} | Mann-Whitney U={u:.0f}, p={pu:.3f} | Cohen d={d:.2f}")
print("\nExpertise vs formulation quality:")
r, pr = stats.pearsonr(fq.expertise_score, fq.formulation_score)
rs, ps = stats.spearmanr(fq.expertise_score, fq.formulation_score)
print(f"  overall  Pearson r={r:.2f} p={pr:.3f} | Spearman rho={rs:.2f} p={ps:.3f}")
for wf in ["agile", "waterfall"]:
    g = fq[fq.workflow_mode == wf]
    rr, pp = stats.pearsonr(g.expertise_score, g.formulation_score)
    print(f"  within {wf:<9} r={rr:.2f} p={pp:.3f} slope={np.polyfit(g.expertise_score, g.formulation_score, 1)[0]:.2f}")
print("\nNOTE: n=16 (8/group) — underpowered; read effect sizes + CIs, treat p-values cautiously.")

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))
for i, (wf, g) in enumerate([("agile", a), ("waterfall", w)]):
    ax1.bar(i, g.mean(), yerr=_se(g), color=PALETTE.get(wf, "#7c3aed"), alpha=0.8, capsize=6)
    ax1.scatter(np.full(len(g), i) + np.linspace(-0.05, 0.05, len(g)), g, color="black", alpha=0.5, s=20, zorder=3)
ax1.set_xticks([0, 1]); ax1.set_xticklabels(["agile", "waterfall"])
ax1.set_ylabel("Formulation score"); ax1.set_title(f"By workflow (mean +/- SE; MW p={pu:.3f}, d={d:.2f})")
for wf in ["agile", "waterfall"]:
    g = fq[fq.workflow_mode == wf]
    ax2.scatter(g.expertise_score, g.formulation_score, color=PALETTE.get(wf, "#7c3aed"), label=wf, s=45)
    b = np.polyfit(g.expertise_score, g.formulation_score, 1)
    xs = np.array([g.expertise_score.min(), g.expertise_score.max()])
    ax2.plot(xs, np.polyval(b, xs), color=PALETTE.get(wf, "#7c3aed"), lw=1.2, alpha=0.7)
ax2.set_xlabel("Self-rated expertise"); ax2.set_ylabel("Formulation score")
ax2.set_title(f"vs expertise (overall r={r:.2f}, p={pr:.3f})"); ax2.legend()
fig.tight_layout()
