import Prism from "prismjs";
import "prismjs/components/prism-python";
import "prismjs/themes/prism.css";
import { useEffect, useRef, useState } from "react";
import Editor from "react-simple-code-editor";

import { describeApiError } from "@shared/api";

import { getDataset, getNotebook, saveNotebook } from "../lib/api";
import { getPyodide, loadDataset, runCell, type CellResult } from "../lib/pyodide";

const highlight = (code: string) => Prism.highlight(code, Prism.languages.python, "python");

// Seed cells. `part`, `plot_xy`, and the raw DataFrames are provided by the
// runtime setup — cells stay short. Users can edit freely.
const SEED_CELLS = [
  `# --- Preview of the loaded DataFrames ---
for _name, _df in [("sessions", sessions), ("messages", messages), ("runs", runs),
                   ("snapshots", snapshots), ("annotations", annotations),
                   ("surveys", surveys), ("part", part)]:
    print(f"{_name:<12} {_df.shape[0]:>6} rows x {_df.shape[1]:>2} cols")
print("\\npart columns:", list(part.columns))
print("\\npart preview (one row per session):")
print(part.head(8).to_string())`,
  `# Convenience table 'part' (one row per session) + plot_xy() are preloaded.
# Raw frames: sessions, messages, runs, annotations, surveys (+ pd, plt).
plot_xy("expertise_score", "init_words",
        "Self-rated expertise", "Initial prompt words",
        "Initial prompt length × expertise")`,
  `plot_xy("expertise_score", "confidence",
        "Self-rated expertise", "Confidence to solve (1–7)",
        "Confidence × expertise")`,
  `plot_xy("expertise_score", "est_time_minutes",
        "Self-rated expertise", "Estimated minutes to solve",
        "Estimated time × expertise")`,
  `# runs per interaction (interaction = user messages + manual saves).
# See n_runs / n_user_msgs / n_saves on 'part' to redefine.
plot_xy("expertise_score", "runs_per_interaction",
        "Self-rated expertise", "Runs / interaction",
        "Runs-to-interaction ratio × expertise")`,
  `# Run timeline: x = minutes since first message; rows ranked by expertise (low→high).
start = messages.groupby("loaded_id")["ts_epoch"].min().rename("start")
r = runs.merge(start, on="loaded_id", how="left").merge(
    part[["loaded_id", "participant", "workflow_mode", "expertise_score"]],
    on="loaded_id", how="left")
r["elapsed_min"] = (r["ts_epoch"] - r["start"]) / 60.0

order = part.sort_values("expertise_score", na_position="last").reset_index(drop=True)
ypos = {lid: i for i, lid in enumerate(order["loaded_id"])}

fig, ax = plt.subplots(figsize=(9, 6))
rr = r.dropna(subset=["elapsed_min"])
for lid, g in rr.groupby("loaded_id"):        # faint guide line per session
    y = ypos.get(lid)
    ax.hlines(y, g["elapsed_min"].min(), g["elapsed_min"].max(), color="#cbd5e1", lw=1, zorder=1)
for wf, g in rr.groupby("workflow_mode"):
    ax.scatter(g["elapsed_min"], g["loaded_id"].map(ypos), s=55, alpha=0.85,
               color=PALETTE.get(wf, "#7c3aed"), label=wf, zorder=3)
ax.set_yticks(range(len(order)))
ax.set_yticklabels([f"{p} (e={e})" for p, e in zip(order["participant"], order["expertise_score"])])
ax.set_xlabel("Minutes since first message")
ax.set_title("Run timeline — rows ranked by expertise (low → high)")
ax.legend(title="workflow")`,
  `# Canonical solution cost per run — one curve per participant, colored by
# workflow. Canonical = each run's schedule re-scored under the OFFICIAL 7-term
# objective, so quality is comparable regardless of the weights the user chose.
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
                   if w in set(rc["workflow_mode"].dropna())], title="workflow")`,
  `# Same canonical cost, but x = MINUTES since first message (wall-clock, not run index).
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
                   if w in set(rc["workflow_mode"].dropna())], title="workflow")`,
  `# Cumulative-best FEASIBLE cost over time — de-noises the curves AND only counts
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
                   if w in set(feas["workflow_mode"].dropna())], title="workflow")`,
  `# Feasibility flag: is each participant's LOWEST-cost run actually valid?
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
print("\\n# whose BEST run is infeasible:", int((~fs["best_feasible"]).sum()), "of", len(fs))
print("median feasible_rate by workflow:")
print(fs.groupby("workflow")["feasible_rate"].median().round(2).to_string())`,
  `# User-action timeline: rows ranked by expertise, faint workflow band per row,
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
ax.legend(loc="upper right")`,
  `# Final formulation quality (from each session's last snapshot), expertise-ranked.
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
ax.set_xlim(0, 3); ax.set_xlabel("Hard constraints captured (0-3)")
ax.set_title("Final formulation: hard constraints captured (color = workflow)")
print(final[["participant", "workflow_mode", "expertise_score", "hard_bonus",
             "objective_as_hard", "soft_as_hard"]].to_string(index=False))
print("\\n(objective_as_hard / soft_as_hard are DESCRIPTIVE — not scored)")
print("by workflow (mean):")
print(final.groupby("workflow_mode")[["hard_bonus"]].mean().round(2).to_string())`,
  `# Heatmap: formulation quality (hard constraints captured, 0-3) over time.
# Rows ranked by expertise; blue=agile / red=waterfall; darker = more captured.
start = messages.groupby("loaded_id")["ts_epoch"].min().rename("start")
sp = snapshots.dropna(subset=["hard_bonus"]).merge(start, on="loaded_id", how="left")
sp["elapsed_min"] = (sp["ts_epoch"] - sp["start"]) / 60.0
sp = sp[sp["elapsed_min"] >= 0]
heatmap_over_time(sp, "hard_bonus", "Hard constraints captured over time (darker = more, 0-3)", vmin=0, vmax=3)`,
  `# Heatmap: best-FEASIBLE canonical cost over time (darker = lower cost = better).
start = messages.groupby("loaded_id")["ts_epoch"].min().rename("start")
rc = runs.merge(start, on="loaded_id").dropna(subset=["canonical_cost"]).copy()
rc["elapsed_min"] = (rc["ts_epoch"] - rc["start"]) / 60.0
rc = rc[rc["feasible"] == True].sort_values(["loaded_id", "elapsed_min"])  # noqa: E712
rc["best_so_far"] = rc.groupby("loaded_id")["canonical_cost"].cummin()
rc["quality"] = -np.log10(rc["best_so_far"].clip(lower=1))  # higher = better = darker
heatmap_over_time(rc, "quality", "Best feasible cost over time (darker = lower cost)")`,
  `# Origin of each hard constraint per participant (from structured brief provenance,
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
          bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)`,
  `# Holistic formulation score (final config) = coverage + hard_bonus + objective_bonus (0-11).
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
print("\\n(objective_as_hard / soft_as_hard are DESCRIPTIVE — not scored)")
print("by workflow (mean):")
print(final.groupby("workflow_mode")[["coverage", "hard_bonus", "objective_bonus", "formulation_score"]].mean().round(2).to_string())`,
  `# Goal-term balancing timeline: when did each participant work on the WEIGHT /
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
print(tot.groupby("workflow_mode")[["weight_edits", "type_edits", "reranked", "addrm"]].mean().round(1).to_string())`,
  `# Formulation score over time, one curve per participant (from config snapshots).
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
                   if w in set(fs["workflow_mode"].dropna())], title="workflow")`,
  `# Formulation quality: agile vs waterfall, and does expertise matter? (EXPLORATORY — small n)
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
print("\\nExpertise vs formulation quality:")
r, pr = stats.pearsonr(fq.expertise_score, fq.formulation_score)
rs, ps = stats.spearmanr(fq.expertise_score, fq.formulation_score)
print(f"  overall  Pearson r={r:.2f} p={pr:.3f} | Spearman rho={rs:.2f} p={ps:.3f}")
for wf in ["agile", "waterfall"]:
    g = fq[fq.workflow_mode == wf]
    rr, pp = stats.pearsonr(g.expertise_score, g.formulation_score)
    print(f"  within {wf:<9} r={rr:.2f} p={pp:.3f} slope={np.polyfit(g.expertise_score, g.formulation_score, 1)[0]:.2f}")
print(f"\\nNOTE: n={len(fq)} ({len(a)} agile / {len(w)} waterfall) — small sample; read effect sizes + CIs, treat p-values cautiously.")

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
fig.tight_layout()`,
  `# Post-session ratings: agile vs waterfall (part already carries the post columns).
from scipy import stats
_need = ["viz_clarity", "comm_accuracy", "solution_confidence"]
if not all(c in part.columns for c in _need) or part[_need].dropna(how="all").empty:
    print("Post ratings not found — upload the POST-task CSV and restart the backend (new survey fields), then Reload data.")
else:
    items = [("viz_clarity", "Visualization"), ("comm_accuracy", "Communication"),
             ("solution_confidence", "Solution confidence")]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), sharey=True)
    for ax, (col, name) in zip(axes, items):
        a = part[part.workflow_mode == "agile"][col].dropna()
        w = part[part.workflow_mode == "waterfall"][col].dropna()
        _se = lambda x: x.std(ddof=1) / np.sqrt(len(x))
        u, p = stats.mannwhitneyu(a, w, alternative="two-sided")
        ax.bar([0, 1], [a.mean(), w.mean()], yerr=[_se(a), _se(w)],
               color=[PALETTE["agile"], PALETTE["waterfall"]], alpha=0.8, capsize=6)
        ax.scatter(np.zeros(len(a)), a, color="k", alpha=0.4, s=15)
        ax.scatter(np.ones(len(w)), w, color="k", alpha=0.4, s=15)
        ax.set_xticks([0, 1]); ax.set_xticklabels(["agile", "waterfall"]); ax.set_title(f"{name} (MW p={p:.2f})")
        print(f"{name:>20}: agile {a.mean():.2f}+/-{_se(a):.2f}  waterfall {w.mean():.2f}+/-{_se(w):.2f}  MW p={p:.3f}")
    axes[0].set_ylabel("Rating (1-7)"); axes[0].set_ylim(0, 7.5); fig.tight_layout()
    _n_post = int(part[_need].notna().any(axis=1).sum())
    print(f"NOTE: n={_n_post} with post ratings, ceilinged (~5-6/7) — small sample; treat as exploratory.")`,
  `# Calibration: does post-session CONFIDENCE track ACTUAL solution quality?
from scipy import stats
if "solution_confidence" not in part.columns or part["solution_confidence"].isna().all():
    print("Post ratings not found — upload the POST-task CSV and restart the backend (new survey fields), then Reload data.")
else:
    bf = runs[runs["feasible"] == True].groupby("loaded_id")["canonical_cost"].min().rename("best_feasible")
    ever = runs.assign(_f=runs["feasible"] == True).groupby("loaded_id")["_f"].any().rename("ever_feasible")
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
    ymax = ok["best_feasible"].max() * 3
    nf = cal[(cal["ever_feasible"] != True) & cal["solution_confidence"].notna()]
    for _, row in nf.iterrows():
        ax.scatter(row["solution_confidence"], ymax, marker="X", color="red", s=90, zorder=5)
        ax.annotate(str(row["participant"]) + " (never feasible)", (row["solution_confidence"], ymax),
                    fontsize=7, color="red", xytext=(4, 0), textcoords="offset points")
    ax.set_xlabel("Post-session confidence (1-7)")
    ax.set_ylabel("Best-feasible canonical cost (log — lower = better)")
    ax.set_title(f"Confidence vs actual quality: r={r:.2f}, p={p:.2f} (flat/scattered = poor calibration)")
    ax.legend(); fig.tight_layout()
    print(f"confidence vs log(best-feasible cost): Pearson r={r:+.2f} p={p:.3f} (~0 => confidence does NOT track quality)")
    print("Red X = participants who NEVER produced a feasible solution; note any rating high confidence.")`,
];

interface Cell {
  id: number;
  code: string;
  result: CellResult | null;
  running: boolean;
}

let _nextId = 1;
const newCell = (code = ""): Cell => ({ id: _nextId++, code, result: null, running: false });

/** Split a jupytext-style `.py` (or plain script) into cells on `# %%` markers. */
function parseCells(text: string): string[] {
  const cells: string[] = [];
  let cur: string[] | null = null;
  for (const line of text.split(/\r?\n/)) {
    if (/^#\s*%%/.test(line)) {
      if (cur) cells.push(cur.join("\n").trim());
      cur = []; // new cell; drop the marker line itself
    } else {
      (cur ??= []).push(line);
    }
  }
  if (cur) cells.push(cur.join("\n").trim());
  return cells.filter((c) => c.length > 0);
}

const runBtn: React.CSSProperties = {
  fontSize: "0.78rem",
  padding: "0.2rem 0.6rem",
  border: "none",
  borderRadius: 4,
  color: "#fff",
  background: "#2563eb",
  cursor: "pointer",
};

export function PyodideNotebook({ token }: { token: string }) {
  const [started, setStarted] = useState(false);
  const [status, setStatus] = useState("");
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cells, setCells] = useState<Cell[]>(() => SEED_CELLS.map((c) => newCell(c)));
  const [hydrated, setHydrated] = useState(false);
  const [savedNote, setSavedNote] = useState<string | null>(null);

  // Load the saved notebook once a token is available; fall back to the seeds.
  useEffect(() => {
    if (hydrated || !token.trim()) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await getNotebook(token.trim());
        if (!cancelled && res.cells && res.cells.length) {
          setCells(res.cells.map((c) => newCell(c)));
        }
      } catch {
        /* no saved notebook yet — keep the seeds */
      }
      if (!cancelled) setHydrated(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [token, hydrated]);

  // Debounced autosave of the code cells (server-side, shared across machines).
  const codesKey = JSON.stringify(cells.map((c) => c.code));
  useEffect(() => {
    if (!hydrated || !token.trim()) return;
    const t = setTimeout(() => {
      saveNotebook(token.trim(), cells.map((c) => c.code))
        .then(() => setSavedNote("saved"))
        .catch(() => setSavedNote("save failed"));
    }, 800);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [codesKey, hydrated, token]);

  function importPy(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      const parsed = parseCells(String(reader.result ?? ""));
      if (parsed.length) {
        setCells(parsed.map((c) => newCell(c)));
        setSavedNote("imported");
      } else {
        setError("No cells found in the file.");
      }
    };
    reader.readAsText(file);
  }

  async function runAll() {
    const py = pyRef.current;
    if (!py) return;
    for (const c of cells) {
      updateCell(c.id, { running: true });
      // eslint-disable-next-line no-await-in-loop
      await new Promise((r) => setTimeout(r, 0));
      const result = runCell(py, c.code);
      updateCell(c.id, { running: false, result });
    }
  }
  const pyRef = useRef<unknown>(null);

  async function start() {
    setStarted(true);
    setError(null);
    try {
      const py = await getPyodide(setStatus);
      pyRef.current = py;
      setStatus("fetching data…");
      const data = await getDataset(token.trim());
      await loadDataset(py, data);
      setReady(true);
      setStatus("ready");
    } catch (e) {
      setError(describeApiError(e, "Failed to start the Python runtime."));
      setStarted(false);
    }
  }

  async function reloadData() {
    if (!pyRef.current) return;
    try {
      setStatus("reloading data…");
      const data = await getDataset(token.trim());
      await loadDataset(pyRef.current, data);
      setStatus("ready");
    } catch (e) {
      setError(describeApiError(e, "Failed to reload data."));
    }
  }

  function updateCell(id: number, patch: Partial<Cell>) {
    setCells((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  }

  async function run(id: number) {
    const py = pyRef.current;
    const cell = cells.find((c) => c.id === id);
    if (!py || !cell) return;
    updateCell(id, { running: true });
    await new Promise((r) => setTimeout(r, 0)); // let the "running" state paint
    const result = runCell(py, cell.code);
    updateCell(id, { running: false, result });
  }

  if (!started) {
    return (
      <div style={{ marginTop: "1rem", borderTop: "1px solid var(--border,#ddd)", paddingTop: "0.75rem" }}>
        <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.35rem" }}>Python notebook (in-browser)</h3>
        <p className="muted" style={{ fontSize: "0.82rem", maxWidth: 640 }}>
          Runs Python (pandas/matplotlib) entirely in your browser via Pyodide — no server-side code
          execution. Starts with <code>sessions, messages, runs, annotations, surveys</code> DataFrames.
          First start downloads ~10&nbsp;MB of WASM.
        </p>
        <button type="button" style={{ fontSize: "0.85rem", padding: "0.35rem 0.6rem" }} onClick={() => void start()}>
          Start Python notebook
        </button>
        {error ? <div className="banner-warn" style={{ marginTop: "0.5rem" }}>{error}</div> : null}
      </div>
    );
  }

  return (
    <div style={{ marginTop: "1rem", borderTop: "1px solid var(--border,#ddd)", paddingTop: "0.75rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
        <h3 style={{ fontSize: "0.95rem", margin: 0 }}>Python notebook (in-browser)</h3>
        <span className="muted" style={{ fontSize: "0.8rem" }}>{status}</span>
        {savedNote ? <span className="muted" style={{ fontSize: "0.75rem" }}>· {savedNote}</span> : null}
        {ready ? (
          <>
            <button
              type="button"
              style={{ ...runBtn, background: "#7c3aed" }}
              onClick={() => void runAll()}
            >
              ▶▶ Run all
            </button>
            <button type="button" style={{ fontSize: "0.78rem" }} onClick={() => void reloadData()}>
              Reload data
            </button>
            <label
              style={{ ...runBtn, background: "#0ea5e9", display: "inline-block" }}
              title="Load cells from a local .py file (split on # %% markers)"
            >
              Import .py
              <input
                type="file"
                accept=".py,text/x-python,text/plain"
                style={{ display: "none" }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) importPy(f);
                  e.currentTarget.value = "";
                }}
              />
            </label>
            <button
              type="button"
              style={{ fontSize: "0.78rem" }}
              title="Replace all cells with the latest starter set"
              onClick={() => {
                if (confirm("Replace all cells with the starter set? Your current cells will be overwritten."))
                  setCells(SEED_CELLS.map((c) => newCell(c)));
              }}
            >
              Reset cells
            </button>
          </>
        ) : null}
      </div>
      {error ? <div className="banner-warn" style={{ marginBottom: "0.5rem" }}>{error}</div> : null}
      {!ready ? <p className="muted">Loading… {status}</p> : null}

      {cells.map((cell, idx) => (
        <div
          key={cell.id}
          style={{
            marginBottom: "0.9rem",
            border: "1px solid #e2e2e8",
            borderLeft: "4px solid #7c3aed",
            borderRadius: 8,
            overflow: "hidden",
            background: "#fff",
            boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
              padding: "0.25rem 0.5rem",
              background: "#f6f6f9",
              borderBottom: "1px solid #ececf0",
            }}
          >
            <span style={{ color: "#7c3aed", fontSize: "0.72rem", fontFamily: "monospace" }}>
              In [{idx + 1}]
            </span>
            <button
              type="button"
              disabled={!ready || cell.running}
              onClick={() => void run(cell.id)}
              style={{ ...runBtn, background: cell.running ? "#9ca3af" : "#16a34a" }}
            >
              {cell.running ? "running…" : "▶ Run"}
            </button>
            <button
              type="button"
              onClick={() => setCells((prev) => [...prev, newCell()])}
              style={{ ...runBtn, background: "#64748b" }}
            >
              + cell
            </button>
            <span style={{ flex: 1 }} />
            {cells.length > 1 ? (
              <button
                type="button"
                onClick={() => setCells((prev) => prev.filter((c) => c.id !== cell.id))}
                style={{ ...runBtn, background: "#dc2626", padding: "0.2rem 0.45rem" }}
              >
                ✕
              </button>
            ) : null}
          </div>
          <Editor
            value={cell.code}
            onValueChange={(code) => updateCell(cell.id, { code })}
            highlight={highlight}
            padding={10}
            textareaClassName="mopt-nb-textarea"
            style={{
              fontFamily: "ui-monospace, Menlo, Consolas, monospace",
              fontSize: "0.8rem",
              lineHeight: 1.5,
              background: "#fbfbfd",
              minHeight: 84,
            }}
          />
          {cell.result ? (
            <div style={{ padding: "0.5rem 0.6rem", background: "#fff", borderTop: "1px solid #f0f0f4" }}>
              {cell.result.error ? (
                <pre style={{ color: "#b91c1c", fontSize: "0.75rem", whiteSpace: "pre-wrap", margin: 0 }}>
                  {cell.result.error}
                </pre>
              ) : null}
              {cell.result.stdout ? (
                <pre
                  style={{
                    fontSize: "0.75rem",
                    whiteSpace: "pre-wrap",
                    overflow: "auto",
                    margin: 0,
                    color: "#334155",
                  }}
                >
                  {cell.result.stdout}
                </pre>
              ) : null}
              {cell.result.images.map((b64, i) => (
                <img
                  key={i}
                  src={`data:image/png;base64,${b64}`}
                  alt="figure"
                  style={{ maxWidth: "100%", display: "block", marginTop: "0.5rem", borderRadius: 4 }}
                />
              ))}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}
