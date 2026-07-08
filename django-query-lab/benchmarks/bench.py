#!/usr/bin/env python3
"""
benchmarks/bench.py — produces the before/after numbers for the README table.

Usage:
    python manage.py runserver  (in another terminal)
    python benchmarks/bench.py --suite slow
    python benchmarks/bench.py --suite fast
    python benchmarks/bench.py --suite both -o benchmarks/results/run1.json

Reports p50 / p95 / mean over N runs after warmup. Commit the JSON results —
reproducible numbers are the whole point of the lab.
"""

import argparse
import json
import statistics
import time

import requests

BASE = "http://127.0.0.1:8000/api"

# (name, path) — user_id 1..50 are Pareto-head heavy users from the seeder
ENDPOINTS = [
    ("user_orders",   "/{suite}/users/3/orders/"),
    ("review_feed",   "/{suite}/reviews/feed/"),
    ("search",        "/{suite}/products/search/?q=wireless"),
    ("orders_page",   "/{suite}/orders/?page=45000&after=900000"),
    ("top_customers", "/{suite}/dashboard/top-customers/"),
]


def bench(url, runs, warmup):
    times = []
    for i in range(warmup + runs):
        t0 = time.perf_counter()
        r = requests.get(url, timeout=300)
        elapsed = (time.perf_counter() - t0) * 1000
        r.raise_for_status()
        if i >= warmup:
            times.append(elapsed)
    times.sort()
    return {
        "p50_ms": round(statistics.median(times), 1),
        "p95_ms": round(times[max(0, int(len(times) * 0.95) - 1)], 1),
        "mean_ms": round(statistics.fmean(times), 1),
        "runs": len(times),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=["slow", "fast", "both"], default="both")
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    suites = ["slow", "fast"] if args.suite == "both" else [args.suite]
    results = {}
    for suite in suites:
        for name, path in ENDPOINTS:
            url = BASE + path.format(suite=suite)
            print(f"benchmarking {suite}/{name} ...", end=" ", flush=True)
            try:
                res = bench(url, args.runs, args.warmup)
                print(f"p50={res['p50_ms']}ms  p95={res['p95_ms']}ms")
                results[f"{suite}/{name}"] = res
            except Exception as e:  # keep going; one broken endpoint shouldn't kill the run
                print(f"FAILED: {e}")
                results[f"{suite}/{name}"] = {"error": str(e)}

    # markdown table for the README
    if args.suite == "both":
        print("\n| Endpoint | before p95 | after p95 | speedup |")
        print("|---|---|---|---|")
        for name, _ in ENDPOINTS:
            b = results.get(f"slow/{name}", {}).get("p95_ms")
            a = results.get(f"fast/{name}", {}).get("p95_ms")
            if b and a:
                print(f"| {name} | {b} ms | {a} ms | {b / a:.0f}× |")

    if args.output:
        with open(args.output, "w") as f:
            json.dump({"timestamp": time.strftime("%Y-%m-%d %H:%M"),
                       "results": results}, f, indent=2)
        print(f"\nsaved -> {args.output}")


if __name__ == "__main__":
    main()
