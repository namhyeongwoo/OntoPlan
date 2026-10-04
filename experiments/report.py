"""Summarize benchmark results in the layout of the paper's tables.

    python -m experiments.report --name rerun                     # all methods/variants in the run
    python -m experiments.report --name rerun --methods full sayplan delta

Reads experiments/results/<name>/<method>/<split>/*.json written by experiments.run.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Dict, List

from experiments.benchmark import ENVS, SIZES

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _load(name: str, method: str, split: str) -> List[Dict]:
    d = RESULTS_DIR / name / method / split
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))
            if not p.name.endswith(".retry.json")] if d.exists() else []


def _tokens(r: Dict) -> Dict[str, float]:
    calls = r.get("llm_calls", [])
    inputs = [c["input_tokens"] for c in calls]
    return {"total": sum(c["input_tokens"] + c["output_tokens"] for c in calls),
            "peak_input": max(inputs, default=0), "inputs": inputs}


def general_table(records: List[Dict]) -> Dict[str, float]:
    if not records:
        return {}
    s = [r["score"] for r in records]
    toks = [_tokens(r) for r in records]
    all_inputs = [i for t in toks for i in t["inputs"]]
    return {
        "n": len(records),
        "plan_generation": mean(x["plan_generation"] for x in s),
        "plan_execution": mean(x["plan_execution"] for x in s),
        "goal_success": mean(x["goal_success"] for x in s),
        "task_success": mean(x["task_success"] for x in s),
        "input_tokens_per_call_k": mean(all_inputs) / 1000 if all_inputs else 0.0,
        "total_tokens_per_task_k": mean(t["total"] for t in toks) / 1000,
        "peak_input_tokens_per_call_k": mean(t["peak_input"] for t in toks) / 1000,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="default")
    parser.add_argument("--methods", nargs="*", help="default: every method directory in the run")
    parser.add_argument("--json", help="also write the summary to this file")
    args = parser.parse_args()

    run_dir = RESULTS_DIR / args.name
    methods = args.methods or sorted(p.name for p in run_dir.iterdir() if p.is_dir())
    summary = {}

    print("General tasks by environment (rates; tokens x10^3)")
    print(f"{'env':11s} {'method':15s} {'n':>3s} {'ret':>5s} {'exec':>5s} {'goal':>5s} {'task':>5s} {'in/call':>8s} {'tot/task':>9s}")
    for method in methods:
        records = _load(args.name, method, "general")
        if not records:
            continue
        by_env = defaultdict(list)
        by_size = defaultdict(list)
        for r in records:
            by_env[r["task"]["env"]].append(r)
            by_size[r["task"]["size"]].append(r)
        summary[method] = {"all": general_table(records),
                           "by_env": {e: general_table(by_env[e]) for e in ENVS if by_env[e]},
                           "by_size": {s: general_table(by_size[s]) for s in SIZES if by_size[s]}}
        for env, row in list(summary[method]["by_env"].items()) + [("ALL", summary[method]["all"])]:
            print(f"{env:11s} {method:15s} {row['n']:3d} {row['plan_generation']:5.2f} {row['plan_execution']:5.2f} "
                  f"{row['goal_success']:5.2f} {row['task_success']:5.2f} {row['input_tokens_per_call_k']:8.1f} "
                  f"{row['total_tokens_per_task_k']:9.1f}")

    print("\nBy scene scale: task success | total tokens per task | peak input tokens per call (x10^3)")
    for method, m in summary.items():
        bs = m["by_size"]
        if not all(s in bs for s in SIZES):
            continue
        task = " ".join(f"{bs[s]['task_success']:.2f}" for s in SIZES)
        tot = [bs[s]["total_tokens_per_task_k"] for s in SIZES]
        peak = [bs[s]["peak_input_tokens_per_call_k"] for s in SIZES]
        tot_str = " ".join(f"{t:.1f}" for t in tot)
        peak_str = " ".join(f"{p:.1f}" for p in peak)
        print(f"{method:15s} S/M/L task {task} avg {m['all']['task_success']:.2f}"
              f" | tokens {tot_str} L/S {tot[2] / tot[0]:.2f}x | peak {peak_str} L/S {peak[2] / peak[0]:.2f}x")

    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
