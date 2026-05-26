"""Sample BTs from an experiment log for human evaluation of coverage.

Stratifies by (strategy x domain) and picks BTs spanning the coverage range
(low / mid / high) so the human-vs-automated comparison covers the whole
spectrum, not just easy or hard cases.

Output:
    <out>/sampled_bts/<id>_<strategy>_<object>_<rep>.xml   one BT per file
    <out>/human_eval_template.csv                          spreadsheet to fill in
    <out>/sample_index.csv                                 map id -> source row

Usage:
    python scripts/sample_for_human_eval.py \\
        experiments/logs/sitl_env_bt_gen_<ts>.jsonl \\
        --n 36 --condition raw --out experiments/human_eval/

After filling in the `human_match` column (0 / 1) for every behavior row in
human_eval_template.csv, run scripts/compare_human_eval.py to compute
correlation between automated coverage and human-judged coverage.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
from collections import defaultdict


def load_results(path: str, condition: str, domain: str | None = None) -> list[dict]:
    rows = [json.loads(l) for l in open(path) if l.strip()]
    out = [
        r for r in rows
        if r.get("type") == "result"
        and r.get("condition") == condition
        and r.get("bt_xml")
    ]
    if domain:
        out = [r for r in out if r.get("domain") == domain]
    return out


def stratified_pick(results: list[dict], n: int, seed: int) -> list[dict]:
    """Pick ~n BTs balanced across (strategy x domain) and the coverage range.

    For each (strategy, domain) bucket, sort by coverage ratio and pick from
    low / mid / high tertiles in a round-robin fashion until we hit n.
    """
    rng = random.Random(seed)
    by_bucket: dict[tuple, list[dict]] = defaultdict(list)
    for r in results:
        by_bucket[(r["strategy"], r["domain"])].append(r)

    # Within each bucket, sort by coverage ratio and split into 3 tertiles.
    tertile_pools: dict[tuple, list[list[dict]]] = {}
    for k, rs in by_bucket.items():
        rs_sorted = sorted(rs, key=lambda r: r["coverage"]["ratio"])
        third = max(1, len(rs_sorted) // 3)
        tertile_pools[k] = [
            rs_sorted[:third],
            rs_sorted[third:2 * third],
            rs_sorted[2 * third:],
        ]

    picked: list[dict] = []
    bucket_keys = list(by_bucket.keys())
    rng.shuffle(bucket_keys)

    # Round-robin: for each bucket, pick one from each tertile in turn.
    for tertile_idx in range(3):
        for k in bucket_keys:
            if len(picked) >= n:
                break
            pool = tertile_pools[k][tertile_idx]
            if pool:
                pick = rng.choice(pool)
                pool.remove(pick)
                picked.append(pick)
        if len(picked) >= n:
            break
    return picked[:n]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("log", help="Path to experiment JSONL log")
    p.add_argument("--n", type=int, default=36, help="Number of BTs to sample")
    p.add_argument("--condition", default="raw", choices=["raw", "repaired"])
    p.add_argument("--domain", default=None,
                   help="Restrict sampling to a single domain (e.g. elevator)")
    p.add_argument("--out", default="experiments/human_eval/")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    results = load_results(args.log, args.condition, args.domain)
    suffix = f" [{args.domain}]" if args.domain else ""
    print(f"Loaded {len(results)} {args.condition} rows{suffix} from {args.log}")
    if not results:
        raise SystemExit("No usable rows (need bt_xml + condition match)")

    samples = stratified_pick(results, args.n, args.seed)
    print(f"Picked {len(samples)} BTs across "
          f"{len({(s['strategy'], s['domain']) for s in samples})} buckets")

    bt_dir = os.path.join(args.out, "sampled_bts")
    os.makedirs(bt_dir, exist_ok=True)

    index_rows = []
    eval_rows = []
    for sid, r in enumerate(samples):
        bt_fname = (
            f"{sid:03d}_{r['strategy']}_{r['object']}_rep{r['rep_index']}.xml"
        )
        bt_path = os.path.join(bt_dir, bt_fname)
        with open(bt_path, "w") as f:
            f.write(r["bt_xml"])

        index_rows.append({
            "sample_id": sid,
            "domain": r["domain"],
            "object": r["object"],
            "strategy": r["strategy"],
            "rep_index": r["rep_index"],
            "bt_file": bt_fname,
            "auto_total": r["coverage"]["total"],
            "auto_covered": r["coverage"]["covered"],
            "auto_ratio": round(r["coverage"]["ratio"], 4),
            "is_valid": r["validation"]["is_valid"],
        })

        # One row per (sample, expected_behavior). The rater will judge each
        # row independently, then compare_human_eval.py aggregates per BT.
        per_b = {pb["behavior"]: pb for pb in r["coverage"]["per_behavior"]}
        for bid, eb in enumerate(r["expected_behaviors"]):
            text = eb["text"] if isinstance(eb, dict) else str(eb)
            cat = eb.get("category", "") if isinstance(eb, dict) else ""
            auto = per_b.get(text, {})
            eval_rows.append({
                "sample_id": sid,
                "bt_file": bt_fname,
                "domain": r["domain"],
                "object": r["object"],
                "strategy": r["strategy"],
                "behavior_id": bid,
                "behavior_category": cat,
                "behavior_text": text,
                "auto_match": int(bool(auto.get("matched"))),
                "human_match": "",   # 0 or 1 — fill in
                "confidence": "",    # optional 1-3
                "notes": "",
            })

    idx_path = os.path.join(args.out, "sample_index.csv")
    with open(idx_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(index_rows[0].keys()))
        w.writeheader()
        w.writerows(index_rows)
    print(f"  wrote {idx_path}")

    eval_path = os.path.join(args.out, "human_eval_template.csv")
    with open(eval_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(eval_rows[0].keys()))
        w.writeheader()
        w.writerows(eval_rows)
    print(f"  wrote {eval_path}  ({len(eval_rows)} judgments to make)")

    print(f"\nNext steps:")
    print(f"  1. Open {eval_path} in a spreadsheet.")
    print(f"  2. For each row, read {bt_dir}/<bt_file> and decide whether the BT")
    print(f"     implements the behavior_text. Fill 'human_match' with 0 or 1.")
    print(f"  3. Run: python scripts/compare_human_eval.py {eval_path}")


if __name__ == "__main__":
    main()
