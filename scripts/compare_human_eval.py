"""Compare automated coverage with human-labeled coverage.

Reads a filled-in human_eval_template.csv (produced by sample_for_human_eval.py)
and reports:

  - Per-behavior agreement: confusion matrix of auto_match vs human_match,
    Cohen's kappa, precision/recall/F1 of the keyword matcher.
  - Per-BT correlation: automated coverage ratio vs human coverage ratio,
    Pearson and Spearman.
  - Top divergences: behaviors where the automated metric is most often
    wrong (false positives, false negatives) — useful for refining keyword
    sets later.

Usage:
    python scripts/compare_human_eval.py experiments/human_eval/human_eval_template.csv \\
        [--out experiments/human_eval/comparison.csv]
"""
from __future__ import annotations

import argparse
import csv
import os
from collections import Counter, defaultdict


def parse_int(s: str) -> int | None:
    s = (s or "").strip()
    if s == "":
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def load(path: str) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


def confusion(rows: list[dict]) -> dict:
    tp = fp = fn = tn = 0
    for r in rows:
        a = parse_int(r["auto_match"])
        h = parse_int(r["human_match"])
        if a is None or h is None:
            continue
        if a == 1 and h == 1: tp += 1
        elif a == 1 and h == 0: fp += 1
        elif a == 0 and h == 1: fn += 1
        elif a == 0 and h == 0: tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def cohens_kappa(c: dict) -> float:
    n = c["tp"] + c["fp"] + c["fn"] + c["tn"]
    if n == 0:
        return 0.0
    po = (c["tp"] + c["tn"]) / n
    p_yes = ((c["tp"] + c["fp"]) / n) * ((c["tp"] + c["fn"]) / n)
    p_no = ((c["fn"] + c["tn"]) / n) * ((c["fp"] + c["tn"]) / n)
    pe = p_yes + p_no
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx * dy > 0 else float("nan")


def spearman(xs: list[float], ys: list[float]) -> float:
    def rank(vs):
        sv = sorted((v, i) for i, v in enumerate(vs))
        r = [0.0] * len(vs)
        i = 0
        while i < len(sv):
            j = i
            while j + 1 < len(sv) and sv[j + 1][0] == sv[i][0]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[sv[k][1]] = avg
            i = j + 1
        return r
    return pearson(rank(xs), rank(ys))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv", nargs="+",
                   help="One or more filled-in human_eval_template.csv "
                        "(rows from all files are concatenated; sample_id is "
                        "remapped to <file_index>_<sample_id> to avoid clashes)")
    p.add_argument("--out", default=None,
                   help="Optional path to write per-BT comparison CSV")
    args = p.parse_args()

    rows: list[dict] = []
    for fi, path in enumerate(args.csv):
        part = load(path)
        for r in part:
            if len(args.csv) > 1:
                r["sample_id"] = f"{fi}_{r.get('sample_id', '')}"
        rows.extend(part)
        print(f"  + {len(part)} rows from {path}")
    print(f"Loaded {len(rows)} (sample, behavior) judgments "
          f"from {len(args.csv)} file(s)")

    labeled = [r for r in rows if parse_int(r["human_match"]) is not None]
    skipped = len(rows) - len(labeled)
    print(f"  human-labeled: {len(labeled)} | unlabeled (skipped): {skipped}")
    if not labeled:
        raise SystemExit("No human labels filled in yet.")

    # 1. Per-behavior confusion matrix
    c = confusion(labeled)
    n = c["tp"] + c["fp"] + c["fn"] + c["tn"]
    accuracy = (c["tp"] + c["tn"]) / n if n else 0.0
    precision = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) else 0.0
    recall = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    kappa = cohens_kappa(c)

    print("\n=== Per-behavior agreement (auto vs human) ===")
    print(f"  N        = {n}")
    print(f"  TP / FP  = {c['tp']:>4} / {c['fp']:>4}")
    print(f"  FN / TN  = {c['fn']:>4} / {c['tn']:>4}")
    print(f"  accuracy = {accuracy:.3f}")
    print(f"  precision (auto positives that are real) = {precision:.3f}")
    print(f"  recall    (real positives auto found)    = {recall:.3f}")
    print(f"  F1                                       = {f1:.3f}")
    print(f"  Cohen's kappa                            = {kappa:.3f}")

    # 2. Per-BT correlation. Key is (model, sample_id) because the merged
    # template contains both models and sample_id resets per model.
    by_bt: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in labeled:
        by_bt[(r.get("model", ""), r.get("sample_id", ""))].append(r)

    auto_ratios, human_ratios = [], []
    bt_compare = []
    for key in sorted(by_bt):
        sub = by_bt[key]
        auto_n = sum(parse_int(r["auto_match"]) or 0 for r in sub)
        hum_n = sum(parse_int(r["human_match"]) or 0 for r in sub)
        total = len(sub)
        auto_r = auto_n / total
        hum_r = hum_n / total
        auto_ratios.append(auto_r)
        human_ratios.append(hum_r)
        bt_compare.append({
            "model": key[0],
            "sample_id": key[1],
            "strategy": sub[0]["strategy"],
            "domain": sub[0]["domain"],
            "object": sub[0]["object"],
            "n_behaviors": total,
            "auto_covered": auto_n,
            "human_covered": hum_n,
            "auto_ratio": round(auto_r, 4),
            "human_ratio": round(hum_r, 4),
            "diff": round(auto_r - hum_r, 4),
        })

    pr = pearson(auto_ratios, human_ratios)
    sr = spearman(auto_ratios, human_ratios)
    print("\n=== Per-BT coverage correlation (auto ratio vs human ratio) ===")
    print(f"  N BTs    = {len(auto_ratios)}")
    print(f"  Pearson  = {pr:.3f}")
    print(f"  Spearman = {sr:.3f}")

    # 3. Most-divergent behaviors (by category & text)
    by_cat: dict[str, dict[str, int]] = defaultdict(lambda: {"fp": 0, "fn": 0, "n": 0})
    by_text: dict[str, dict[str, int]] = defaultdict(lambda: {"fp": 0, "fn": 0, "n": 0})
    for r in labeled:
        a = parse_int(r["auto_match"])
        h = parse_int(r["human_match"])
        cat = r["behavior_category"]
        txt = r["behavior_text"]
        by_cat[cat]["n"] += 1
        by_text[txt]["n"] += 1
        if a == 1 and h == 0:
            by_cat[cat]["fp"] += 1
            by_text[txt]["fp"] += 1
        elif a == 0 and h == 1:
            by_cat[cat]["fn"] += 1
            by_text[txt]["fn"] += 1

    print("\n=== Categories with most disagreement (FP+FN per behavior) ===")
    cat_rank = sorted(by_cat.items(),
                      key=lambda x: -(x[1]["fp"] + x[1]["fn"]))
    print(f"  {'category':<22} {'N':>4} {'FP':>4} {'FN':>4} {'err_rate':>9}")
    for cat, st in cat_rank[:10]:
        if st["n"] == 0:
            continue
        err = (st["fp"] + st["fn"]) / st["n"]
        print(f"  {cat[:22]:<22} {st['n']:>4} {st['fp']:>4} {st['fn']:>4} {err:>9.2%}")

    print("\n=== Top false-positive behaviors (auto says yes, human says no) ===")
    fps = sorted([(t, s) for t, s in by_text.items() if s["fp"] > 0],
                 key=lambda x: -x[1]["fp"])[:5]
    for txt, st in fps:
        print(f"  [{st['fp']}/{st['n']}] {txt[:90]}")

    print("\n=== Top false-negative behaviors (auto says no, human says yes) ===")
    fns = sorted([(t, s) for t, s in by_text.items() if s["fn"] > 0],
                 key=lambda x: -x[1]["fn"])[:5]
    for txt, st in fns:
        print(f"  [{st['fn']}/{st['n']}] {txt[:90]}")

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(bt_compare[0].keys()))
            w.writeheader()
            w.writerows(bt_compare)
        print(f"\nWrote per-BT comparison to {args.out}")

    print("\n=== Reporting recipe for the paper ===")
    print(f'  "We sampled {len(by_bt)} BTs across strategies and domains and had a')
    print(f"   human rater label which expected_behaviors each BT actually")
    print(f"   implements.  The automated keyword-matching coverage agreed with")
    print(f"   the human-labeled coverage at Pearson r = {pr:.2f} (Spearman ρ =")
    print(f"   {sr:.2f}; Cohen's κ at the per-behavior level = {kappa:.2f},")
    print(f"   accuracy = {accuracy:.0%}). This supports our use of the keyword")
    print(f'   metric for cross-strategy comparisons."')


if __name__ == "__main__":
    main()
