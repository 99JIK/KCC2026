"""Appendix figures C.1 through C.9.

C.1 per-object coverage, C.2 repair-iteration histogram, C.3 pipeline
token cost, C.4 coverage distribution, C.5 coverage x validity scatter,
C.6 per-category heatmap, C.7 raw failure causes, C.8 BT complexity,
C.9 repair gain.

    python scripts/figures_appendix.py --gpt4 LOG --llama LOG --out DIR
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

STRATEGIES = ["zero_shot", "few_shot_generic", "proposed", "proposed_with_few_shot"]
LABELS = {
    "zero_shot": "Zero-shot",
    "few_shot_generic": "Few-shot",
    "proposed": "Proposed",
    "proposed_with_few_shot": "Proposed + Few-shot",
}
COLORS = ["#d6d6d6", "#9bb8d6", "#3d7bb6", "#1f4e7d"]


def load_results(path):
    rows = []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("type") == "result":
            rows.append(r)
    return rows


# ---------------------------------------------------------------------------
# A1: Per-object coverage by strategy
# ---------------------------------------------------------------------------
def figA1_per_object_coverage(gpt4_rows, llama_rows, out_path):
    object_order_by_domain = []
    for d, objs in [
        ("elevator", ["elevator_car", "building_system", "passenger"]),
        ("drone", ["weather_environment", "airspace_obstacle", "ground_target",
                   "signal_environment"]),
        ("smart_factory", ["conveyor_system", "factory_equipment",
                           "human_worker", "other_agv"]),
    ]:
        object_order_by_domain.extend(objs)

    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    for ax, rows, title in [(axes[0], gpt4_rows, "GPT-4"),
                            (axes[1], llama_rows, "Llama-3 70B")]:
        per_obj = defaultdict(list)
        for r in rows:
            if r["condition"] != "raw":
                continue
            per_obj[(r["object"], r["strategy"])].append(r["coverage"]["ratio"])
        x = np.arange(len(object_order_by_domain))
        w = 0.20
        for j, s in enumerate(STRATEGIES):
            vals = [statistics.mean(per_obj[(o, s)]) * 100 if per_obj[(o, s)] else 0
                    for o in object_order_by_domain]
            ax.bar(x + (j - 1.5) * w, vals, w,
                   color=COLORS[j], edgecolor="black", linewidth=0.5,
                   label=LABELS[s])
        ax.set_ylim(0, 100)
        ax.set_ylabel("Behavior coverage (%)")
        ax.set_title(f"{title} — Per-object coverage (raw)")
        ax.grid(True, axis="y", alpha=0.3, linestyle="--")
        ax.set_axisbelow(True)
        if ax is axes[0]:
            ax.legend(loc="upper left", fontsize=9, framealpha=0.95)

    axes[1].set_xticks(x)
    axes[1].set_xticklabels(object_order_by_domain, rotation=30, ha="right")

    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_path}")


# ---------------------------------------------------------------------------
# A2: Repair iterations distribution
# ---------------------------------------------------------------------------
def figA2_repair_iterations(gpt4_rows, llama_rows, out_path):
    """Histogram of repair_calls per strategy (0 means the BT was already valid)."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), sharey=True)
    bins = [0, 1, 2, 3]
    bin_labels = ["0", "1", "2", "3"]
    w = 0.20

    for ax, rows, title in [(axes[0], gpt4_rows, "GPT-4"),
                            (axes[1], llama_rows, "Llama-3 70B")]:
        per_strat = defaultdict(list)
        for r in rows:
            if r["condition"] != "repaired" or "repair" not in r:
                continue
            per_strat[r["strategy"]].append(r["repair"].get("calls", 0))
        x = np.arange(len(bins))
        for j, s in enumerate(STRATEGIES):
            vals = per_strat[s]
            total = len(vals)
            if total == 0:
                heights = [0] * len(bins)
            else:
                counts = {b: 0 for b in bins}
                for v in vals:
                    v = min(v, 3)
                    counts[v] += 1
                heights = [counts[b] / total * 100 for b in bins]
            ax.bar(x + (j - 1.5) * w, heights, w,
                   color=COLORS[j], edgecolor="black", linewidth=0.5,
                   label=LABELS[s])
        ax.set_xticks(x)
        ax.set_xticklabels(bin_labels)
        ax.set_xlabel("Repair calls used")
        ax.set_ylim(0, 105)
        ax.set_title(f"{title} — Repair iteration distribution")
        ax.grid(True, axis="y", alpha=0.3, linestyle="--")
        ax.set_axisbelow(True)
        if ax is axes[0]:
            ax.set_ylabel("Share of cells (%)")
            ax.legend(loc="upper right", fontsize=9, framealpha=0.95)

    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_path}")


# ---------------------------------------------------------------------------
# A3: Pipeline token cost breakdown
# ---------------------------------------------------------------------------
def figA3_pipeline_token_cost(gpt4_rows, llama_rows, out_path):
    """Stacked bar: total tokens per pipeline step (decompose / elicit / synthesize),
    averaged across all 110 proposed runs per model."""
    fig, ax = plt.subplots(figsize=(8, 4.8))
    steps = ["decompose", "elicit", "synthesize"]
    step_colors = {"decompose": "#9bb8d6", "elicit": "#3d7bb6", "synthesize": "#1f4e7d"}
    model_labels = ["GPT-4", "Llama-3 70B"]
    avgs_per_model = []
    for rows in [gpt4_rows, llama_rows]:
        sums = {s: [] for s in steps}
        for r in rows:
            if r["condition"] != "raw" or r["strategy"] != "proposed":
                continue
            p = r.get("pipeline")
            if not p:
                continue
            for s in steps:
                sums[s].append(p[s]["usage"]["total_tokens"])
        avgs_per_model.append({s: statistics.mean(sums[s]) if sums[s] else 0
                               for s in steps})

    x = np.arange(len(model_labels))
    bottoms = np.zeros(len(model_labels))
    for s in steps:
        heights = [avgs_per_model[i][s] for i in range(len(model_labels))]
        bars = ax.bar(x, heights, 0.5, bottom=bottoms,
                      color=step_colors[s], edgecolor="black", linewidth=0.5,
                      label=s.capitalize())
        for i, h in enumerate(heights):
            if h > 50:
                ax.text(x[i], bottoms[i] + h / 2, f"{h:.0f}",
                        ha="center", va="center", fontsize=10,
                        color="white" if s != "decompose" else "black")
        bottoms += np.array(heights)

    for i, total in enumerate(bottoms):
        ax.text(x[i], total + 80, f"Σ {total:.0f}", ha="center", fontsize=10,
                fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(model_labels)
    ax.set_ylabel("Tokens per generation (avg)")
    ax.set_title("Proposed pipeline — token cost per step")
    ax.set_ylim(0, max(bottoms) * 1.15)
    ax.grid(True, axis="y", alpha=0.3, linestyle="--")
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", fontsize=10, framealpha=0.95)

    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_path}")


# ---------------------------------------------------------------------------
# A4: Coverage distribution (boxplot)
# ---------------------------------------------------------------------------
def figA4_coverage_distribution(gpt4_rows, llama_rows, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), sharey=True)
    for ax, rows, title in [(axes[0], gpt4_rows, "GPT-4"),
                            (axes[1], llama_rows, "Llama-3 70B")]:
        data = [
            [r["coverage"]["ratio"] * 100 for r in rows
             if r["condition"] == "raw" and r["strategy"] == s]
            for s in STRATEGIES
        ]
        bp = ax.boxplot(data, patch_artist=True, widths=0.55,
                        medianprops=dict(color="black", linewidth=1.4),
                        flierprops=dict(marker="o", markersize=3,
                                        markerfacecolor="#444",
                                        markeredgecolor="#444", alpha=0.5))
        for patch, c in zip(bp["boxes"], COLORS):
            patch.set_facecolor(c)
            patch.set_edgecolor("black")
            patch.set_linewidth(0.6)
        for whisker in bp["whiskers"]:
            whisker.set_color("black")
            whisker.set_linewidth(0.8)
        for cap in bp["caps"]:
            cap.set_color("black")
        means = [statistics.mean(d) if d else 0 for d in data]
        ax.scatter(range(1, len(STRATEGIES) + 1), means,
                   marker="D", color="white", edgecolor="black",
                   s=36, zorder=3, label="mean")
        ax.set_xticks(range(1, len(STRATEGIES) + 1))
        ax.set_xticklabels([LABELS[s] for s in STRATEGIES], rotation=15,
                           ha="right")
        ax.set_ylim(0, 100)
        ax.grid(True, axis="y", alpha=0.3, linestyle="--")
        ax.set_axisbelow(True)
        ax.set_title(f"{title} — Coverage distribution (110 raw cells)")
        if ax is axes[0]:
            ax.set_ylabel("Behavior coverage (%)")
            ax.legend(loc="upper left", fontsize=9, framealpha=0.95)

    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_path}")


# ---------------------------------------------------------------------------
# A5: Coverage x Validity Pareto
# ---------------------------------------------------------------------------
def _mean_ci(values):
    import math
    if not values:
        return 0.0, 0.0
    m = statistics.mean(values) * 100
    if len(values) < 2:
        return m, 0.0
    sd = statistics.stdev(values) * 100
    return m, 1.96 * sd / math.sqrt(len(values))


def figA5_coverage_validity_pareto(gpt4_rows, llama_rows, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), sharex=True, sharey=True)
    for ax, rows, title in [(axes[0], gpt4_rows, "GPT-4"),
                            (axes[1], llama_rows, "Llama-3 70B")]:
        for j, s in enumerate(STRATEGIES):
            covs = [r["coverage"]["ratio"] for r in rows
                    if r["condition"] == "raw" and r["strategy"] == s]
            vals = [1.0 if r["validation"]["is_valid"] else 0.0
                    for r in rows
                    if r["condition"] == "raw" and r["strategy"] == s]
            cm, cci = _mean_ci(covs)
            vm, vci = _mean_ci(vals)
            ax.errorbar(vm, cm, xerr=vci, yerr=cci,
                        fmt="o", markersize=11,
                        color=COLORS[j], markeredgecolor="black",
                        ecolor="#444", elinewidth=0.9, capsize=3,
                        label=LABELS[s])
            ax.annotate(LABELS[s], xy=(vm, cm),
                        xytext=(8, 6), textcoords="offset points",
                        fontsize=9)
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.set_xlabel("Raw structural validity (%)")
        ax.grid(True, alpha=0.3, linestyle="--")
        ax.set_axisbelow(True)
        ax.set_title(f"{title} — Coverage vs validity (raw, 95% CI)")
        if ax is axes[0]:
            ax.set_ylabel("Behavior coverage (%)")

    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_path}")


# ---------------------------------------------------------------------------
# A6: Per-category coverage heatmap
# ---------------------------------------------------------------------------
def figA6_category_coverage(gpt4_rows, llama_rows, out_path):
    all_rows = [r for r in gpt4_rows + llama_rows
                if r["condition"] == "raw"]
    cat_by_domain = defaultdict(set)
    bucket = defaultdict(list)
    for r in all_rows:
        for cat, agg in r["coverage"].get("per_category", {}).items():
            cat_by_domain[r["domain"]].add(cat)
            bucket[(r["domain"], cat, r["strategy"])].append(agg["ratio"])

    domains = ["elevator", "drone", "smart_factory"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 6.8),
                             gridspec_kw={"width_ratios": [1, 1, 1]})
    cmap = plt.get_cmap("Blues")
    for ax, d in zip(axes, domains):
        cats = sorted(cat_by_domain[d])
        mat = np.zeros((len(cats), len(STRATEGIES)))
        for i, c in enumerate(cats):
            for j, s in enumerate(STRATEGIES):
                vals = bucket[(d, c, s)]
                mat[i, j] = statistics.mean(vals) * 100 if vals else 0
        im = ax.imshow(mat, cmap=cmap, vmin=0, vmax=100, aspect="auto")
        ax.set_xticks(range(len(STRATEGIES)))
        ax.set_xticklabels([LABELS[s] for s in STRATEGIES],
                           rotation=30, ha="right", fontsize=9)
        ax.set_yticks(range(len(cats)))
        ax.set_yticklabels(cats, fontsize=8)
        ax.set_title(d, fontsize=11)
        for i in range(len(cats)):
            for j in range(len(STRATEGIES)):
                v = mat[i, j]
                ax.text(j, i, f"{v:.0f}",
                        ha="center", va="center",
                        fontsize=7,
                        color="white" if v > 55 else "black")

    cbar_ax = fig.add_axes([0.92, 0.18, 0.012, 0.65])
    fig.colorbar(im, cax=cbar_ax, label="Coverage (%)")
    fig.suptitle("Per-category coverage by strategy "
                 "(both models, raw)", y=0.995, fontsize=12)
    plt.tight_layout(rect=[0, 0, 0.91, 0.97])
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_path}")


# ---------------------------------------------------------------------------
# A7: Raw error types
# ---------------------------------------------------------------------------
def _err_class(msg):
    if "[ID] is not allowed in <Sequence>" in msg \
            or "[ID] is not allowed in <Fallback>" in msg:
        return "Composite ID misuse"
    if "must have exactly 1 child" in msg and "BehaviorTree" in msg:
        return "Multi-rooted tree"
    if "main_tree_to_execute" in msg:
        return "Missing root attr"
    if "Repeat" in msg and ("child" in msg or "children" in msg):
        return "Repeat: wrong arity"
    if "Inverter" in msg and ("child" in msg or "children" in msg):
        return "Inverter: wrong arity"
    if "ForceSuccess" in msg or "ForceFailure" in msg:
        return "Decorator: wrong arity"
    if "no children" in msg:
        return "Empty composite"
    if "providedPorts" in msg:
        return "Unknown port"
    if "XML" in msg or "parse error" in msg.lower():
        return "XML parse error"
    if msg.startswith("BT.CPP tick failed"):
        return "Tick error"
    return "Other"


ERROR_CLASSES = [
    "Composite ID misuse",
    "Multi-rooted tree",
    "Repeat: wrong arity",
    "Inverter: wrong arity",
    "Decorator: wrong arity",
    "Empty composite",
    "Missing root attr",
    "Unknown port",
    "XML parse error",
    "Tick error",
    "Other",
]
ERROR_COLORS = [
    "#1f4e7d", "#3d7bb6", "#6f9fce", "#9bb8d6",
    "#bcd0e3", "#c9b29b", "#a07854", "#7a4f2a",
    "#5e3a1f", "#393939", "#aaaaaa",
]


def figA7_raw_error_types(gpt4_rows, llama_rows, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.0), sharey=True)
    for ax, rows, title in [(axes[0], gpt4_rows, "GPT-4"),
                            (axes[1], llama_rows, "Llama-3 70B")]:
        counts = {s: {c: 0 for c in ERROR_CLASSES} for s in STRATEGIES}
        for r in rows:
            if r["condition"] != "raw":
                continue
            classes_seen = set()
            for e in r["validation"]["errors"]:
                classes_seen.add(_err_class(e))
            for c in classes_seen:
                counts[r["strategy"]][c] += 1

        x = np.arange(len(STRATEGIES))
        bottoms = np.zeros(len(STRATEGIES))
        denom = 110.0
        for c, color in zip(ERROR_CLASSES, ERROR_COLORS):
            heights = np.array([counts[s][c] / denom * 100 for s in STRATEGIES])
            if heights.sum() == 0:
                continue
            ax.bar(x, heights, 0.55, bottom=bottoms,
                   color=color, edgecolor="black", linewidth=0.4, label=c)
            bottoms += heights

        ax.set_xticks(x)
        ax.set_xticklabels([LABELS[s] for s in STRATEGIES], rotation=15,
                           ha="right")
        ax.set_ylim(0, max(110, bottoms.max() + 8))
        ax.set_title(f"{title} — Raw failure causes (% of 110 cells)")
        ax.grid(True, axis="y", alpha=0.3, linestyle="--")
        ax.set_axisbelow(True)
        for i, total in enumerate(bottoms):
            if total > 0:
                ax.text(i, total + 1.5, f"{total:.0f}%",
                        ha="center", fontsize=9)
        if ax is axes[0]:
            ax.set_ylabel("Cells failing (%)")

    fig.legend(*axes[1].get_legend_handles_labels(),
               loc="center right", bbox_to_anchor=(1.0, 0.5),
               fontsize=9, framealpha=0.95)
    plt.tight_layout(rect=[0, 0, 0.86, 1])
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_path}")


# ---------------------------------------------------------------------------
# A8: BT structural complexity
# ---------------------------------------------------------------------------
def figA8_bt_complexity(gpt4_rows, llama_rows, out_path):
    fig, axes = plt.subplots(2, 2, figsize=(13, 7.6), sharex="col")
    metric_keys = [("total_nodes", "Total nodes"),
                   ("max_depth", "Max depth")]
    rowsets = [("GPT-4", gpt4_rows), ("Llama-3 70B", llama_rows)]

    for ri, (title, rows) in enumerate(rowsets):
        for ci, (key, label) in enumerate(metric_keys):
            ax = axes[ri][ci]
            data = [
                [r["validation"]["metrics"][key] for r in rows
                 if r["condition"] == "raw" and r["strategy"] == s
                 and key in r["validation"]["metrics"]]
                for s in STRATEGIES
            ]
            bp = ax.boxplot(data, patch_artist=True, widths=0.55,
                            medianprops=dict(color="black", linewidth=1.4),
                            flierprops=dict(marker="o", markersize=3,
                                            markerfacecolor="#444",
                                            markeredgecolor="#444",
                                            alpha=0.5))
            for patch, c in zip(bp["boxes"], COLORS):
                patch.set_facecolor(c)
                patch.set_edgecolor("black")
                patch.set_linewidth(0.6)
            for whisker in bp["whiskers"]:
                whisker.set_color("black")
            ax.set_xticks(range(1, len(STRATEGIES) + 1))
            ax.set_xticklabels([LABELS[s] for s in STRATEGIES],
                               rotation=15, ha="right")
            ax.grid(True, axis="y", alpha=0.3, linestyle="--")
            ax.set_axisbelow(True)
            ax.set_title(f"{title} — {label}")
            if ci == 0:
                ax.set_ylabel(label)

    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_path}")


# ---------------------------------------------------------------------------
# A9: Repair delta validity
# ---------------------------------------------------------------------------
def figA9_repair_delta(gpt4_rows, llama_rows, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), sharey=True)
    w = 0.55
    for ax, rows, title in [(axes[0], gpt4_rows, "GPT-4"),
                            (axes[1], llama_rows, "Llama-3 70B")]:
        raw = {s: [] for s in STRATEGIES}
        rep = {s: [] for s in STRATEGIES}
        for r in rows:
            if r["strategy"] not in STRATEGIES:
                continue
            v = 1.0 if r["validation"]["is_valid"] else 0.0
            if r["condition"] == "raw":
                raw[r["strategy"]].append(v)
            else:
                rep[r["strategy"]].append(v)
        raw_vals = [statistics.mean(raw[s]) * 100 if raw[s] else 0
                    for s in STRATEGIES]
        rep_vals = [statistics.mean(rep[s]) * 100 if rep[s] else 0
                    for s in STRATEGIES]
        deltas = [rv - rv0 for rv, rv0 in zip(rep_vals, raw_vals)]

        x = np.arange(len(STRATEGIES))
        ax.bar(x, raw_vals, w, color=COLORS,
               edgecolor="black", linewidth=0.6, label="Raw")
        ax.bar(x, deltas, w, bottom=raw_vals, color=COLORS,
               edgecolor="black", linewidth=0.6,
               hatch="//", alpha=0.65, label="Repair gain")
        for i, (b, d) in enumerate(zip(raw_vals, deltas)):
            ax.text(i, b / 2, f"{b:.0f}", ha="center", va="center",
                    fontsize=10, color="black" if b < 50 else "white")
            if d > 1:
                ax.text(i, b + d / 2, f"+{d:.0f}", ha="center", va="center",
                        fontsize=10, color="black")
            ax.text(i, b + d + 2, f"{b + d:.0f}", ha="center",
                    fontsize=10, fontweight="bold")

        ax.set_xticks(x)
        ax.set_xticklabels([LABELS[s] for s in STRATEGIES],
                           rotation=15, ha="right")
        ax.set_ylim(0, 115)
        ax.set_title(f"{title} — Validity gain from structural repair")
        ax.grid(True, axis="y", alpha=0.3, linestyle="--")
        ax.set_axisbelow(True)
        if ax is axes[0]:
            ax.set_ylabel("Structural validity (%)")
            ax.legend(loc="upper left", fontsize=10, framealpha=0.95)

    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_path}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gpt4", required=True)
    p.add_argument("--llama", required=True)
    p.add_argument("--out", default="experiments/figures/")
    args = p.parse_args()

    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = [
        "DejaVu Sans", "Helvetica", "Arial",
    ]
    plt.rcParams["font.size"] = 11
    os.makedirs(args.out, exist_ok=True)

    gpt4 = load_results(args.gpt4)
    llama = load_results(args.llama)
    print(f"loaded gpt4={len(gpt4)} rows, llama={len(llama)} rows")

    figA1_per_object_coverage(gpt4, llama,
                              os.path.join(args.out, "figA1_per_object_coverage.png"))
    figA2_repair_iterations(gpt4, llama,
                            os.path.join(args.out, "figA2_repair_iterations.png"))
    figA3_pipeline_token_cost(gpt4, llama,
                              os.path.join(args.out, "figA3_pipeline_token_cost.png"))
    figA4_coverage_distribution(gpt4, llama,
                                os.path.join(args.out, "figA4_coverage_distribution.png"))
    figA5_coverage_validity_pareto(gpt4, llama,
                                   os.path.join(args.out, "figA5_coverage_validity_pareto.png"))
    figA6_category_coverage(gpt4, llama,
                            os.path.join(args.out, "figA6_category_coverage.png"))
    figA7_raw_error_types(gpt4, llama,
                          os.path.join(args.out, "figA7_raw_error_types.png"))
    figA8_bt_complexity(gpt4, llama,
                        os.path.join(args.out, "figA8_bt_complexity.png"))
    figA9_repair_delta(gpt4, llama,
                       os.path.join(args.out, "figA9_repair_delta.png"))


if __name__ == "__main__":
    main()
