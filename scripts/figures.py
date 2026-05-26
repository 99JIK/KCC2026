"""Body figures: fig2 (coverage by domain x strategy, 95% CI) and
fig3 (validity raw vs repaired). Fig 1 is hand-drawn and not generated here.

    python scripts/figures.py --gpt4 LOG --llama LOG --out DIR
"""
from __future__ import annotations

import argparse
import json
import math
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
    "proposed_with_few_shot": "Proposed +\nFew-shot",
}
DOMAINS = ["drone", "elevator", "smart_factory"]
DOMAIN_LABELS = {
    "drone": "drone",
    "elevator": "elevator",
    "smart_factory": "smart_factory",
}

# Light gray -> light blue -> blue -> dark blue gradient (by strategy).
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


def mean_ci(values):
    """Return (mean, 95% CI half-width) in percent."""
    if not values:
        return 0.0, 0.0
    m = statistics.mean(values) * 100
    if len(values) < 2:
        return m, 0.0
    sd = statistics.stdev(values) * 100
    half = 1.96 * sd / math.sqrt(len(values))
    return m, half


def coverage_by_domain_strategy(rows):
    """Return {(domain, strategy): (mean%, ci%)}."""
    grouped = defaultdict(list)
    for r in rows:
        if r["condition"] != "raw" or r["strategy"] not in STRATEGIES:
            continue
        grouped[(r["domain"], r["strategy"])].append(r["coverage"]["ratio"])
    return {k: mean_ci(v) for k, v in grouped.items()}


def validity_by_strategy(rows, condition):
    """Return {strategy: mean%}."""
    grouped = defaultdict(list)
    for r in rows:
        if r["condition"] != condition or r["strategy"] not in STRATEGIES:
            continue
        grouped[r["strategy"]].append(1.0 if r["validation"]["is_valid"] else 0.0)
    return {s: (statistics.mean(grouped.get(s, [0])) * 100 if grouped.get(s) else 0)
            for s in STRATEGIES}


def fig2_coverage_by_domain(gpt4_rows, llama_rows, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), sharey=True)
    x = np.arange(len(DOMAINS))
    w = 0.20

    for ax, rows, title in [(axes[0], gpt4_rows, "GPT-4"),
                            (axes[1], llama_rows, "Llama-3 70B")]:
        m = coverage_by_domain_strategy(rows)
        for j, s in enumerate(STRATEGIES):
            vals = [m.get((d, s), (0, 0))[0] for d in DOMAINS]
            errs = [m.get((d, s), (0, 0))[1] for d in DOMAINS]
            ax.bar(x + (j - 1.5) * w, vals, w,
                   yerr=errs, capsize=3,
                   color=COLORS[j],
                   edgecolor="black", linewidth=0.6,
                   label=LABELS[s].replace("\n", " "))
            for i, (v, e) in enumerate(zip(vals, errs)):
                ax.text(x[i] + (j - 1.5) * w, v + e + 1.5, f"{v:.0f}",
                        ha="center", fontsize=9)
        ax.set_xticks(x)
        ax.set_xticklabels([DOMAIN_LABELS[d] for d in DOMAINS])
        ax.set_ylim(0, 100)
        ax.set_title(f"{title} — Coverage by domain × strategy "
                     "(raw, 95% CI)")
        ax.grid(True, axis="y", alpha=0.3, linestyle="--")
        ax.set_axisbelow(True)
        if ax is axes[0]:
            ax.set_ylabel("Behavior coverage (%)")
            ax.legend(loc="upper left", fontsize=10, framealpha=0.95)

    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_path}")


def fig3_validity_by_strategy(gpt4_rows, llama_rows, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), sharey=True)
    x = np.arange(len(STRATEGIES))
    w = 0.38

    for ax, rows, title in [(axes[0], gpt4_rows, "GPT-4"),
                            (axes[1], llama_rows, "Llama-3 70B")]:
        raw_m = validity_by_strategy(rows, "raw")
        rep_m = validity_by_strategy(rows, "repaired")
        raw_vals = [raw_m[s] for s in STRATEGIES]
        rep_vals = [rep_m[s] for s in STRATEGIES]

        ax.bar(x - w/2, raw_vals, w, color=COLORS,
               edgecolor="black", linewidth=0.6, label="Raw")
        ax.bar(x + w/2, rep_vals, w, color=COLORS,
               edgecolor="black", linewidth=0.6, hatch="//", label="Repaired")

        for i, v in enumerate(raw_vals):
            ax.text(i - w/2, v + 2, f"{v:.0f}", ha="center", fontsize=10)
        for i, v in enumerate(rep_vals):
            ax.text(i + w/2, v + 2, f"{v:.0f}", ha="center", fontsize=10)

        ax.set_xticks(x)
        ax.set_xticklabels([LABELS[s] for s in STRATEGIES])
        ax.set_ylim(0, 115)
        ax.set_title(f"{title} — BT.CPP v4 runtime validity by strategy")
        ax.grid(True, axis="y", alpha=0.3, linestyle="--")
        ax.set_axisbelow(True)
        ax.legend(loc="lower right", fontsize=10, framealpha=0.95)
        if ax is axes[0]:
            ax.set_ylabel("Structural validity (%)")

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

    fig2_coverage_by_domain(gpt4, llama,
                            os.path.join(args.out, "fig2_coverage_by_domain.png"))
    fig3_validity_by_strategy(gpt4, llama,
                              os.path.join(args.out, "fig3_validity_by_strategy.png"))


if __name__ == "__main__":
    main()
