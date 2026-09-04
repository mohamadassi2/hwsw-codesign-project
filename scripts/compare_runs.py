#!/usr/bin/env python3
"""Compare two results/ directories: the shipped one against an independent rerun.

  python3 scripts/compare_runs.py results /path/to/other/results

For each benchmark it prints the mean of the baseline and optimized runs in both
sets, the speedup each set gives, and the drift between them, plus the drift of
the perf stat counters. This is how we check that a fresh run of the shipped
repository in the course VM reproduces the committed numbers.
"""
import json, os, re, statistics, sys


def mean(p):
    if not os.path.exists(p):
        return None
    d = json.load(open(p))
    v = [x for b in d["benchmarks"] for r in b["runs"] for x in r.get("values", [])]
    return statistics.mean(v) if v else None


def perfstat(p):
    r = {}
    if not os.path.exists(p):
        return r
    for line in open(p):
        m = re.match(r"\s*([\d,\.]+)\s+(?:msec\s+)?([a-z-]+)", line)
        if m:
            r[m.group(2)] = float(m.group(1).replace(",", ""))
    return r


def pct(a, b):
    return 100.0 * (b - a) / a if a else float("nan")


def main(a, b):
    worst = 0.0
    for bench in ("pyflate", "mdp"):
        print(f"== {bench}")
        ab, ao = mean(f"{a}/{bench}/{bench}_base.json"), mean(f"{a}/{bench}/{bench}_opt.json")
        bb, bo = mean(f"{b}/{bench}/{bench}_base.json"), mean(f"{b}/{bench}/{bench}_opt.json")
        if None in (ab, ao, bb, bo):
            print("   (missing data in one set)"); continue
        print(f"   baseline   {ab:9.4f} s   vs {bb:9.4f} s   drift {pct(ab, bb):+6.2f}%")
        print(f"   optimized  {ao:9.4f} s   vs {bo:9.4f} s   drift {pct(ao, bo):+6.2f}%")
        print(f"   speedup    {ab/ao:9.3f}x    vs {bb/bo:9.3f}x    drift {pct(ab/ao, bb/bo):+6.2f}%")
        worst = max(worst, abs(pct(ab, bb)), abs(pct(ao, bo)))
        for v in ("base", "opt"):
            pa, pb = perfstat(f"{a}/{bench}/perfstat_{v}.txt"), perfstat(f"{b}/{bench}/perfstat_{v}.txt")
            for k in ("instructions", "cycles", "branch-misses"):
                if k in pa and k in pb:
                    print(f"   {v:4s} {k:14s} {pa[k]:16,.0f} vs {pb[k]:16,.0f}   drift {pct(pa[k], pb[k]):+6.2f}%")
    print(f"\nlargest wall-clock drift: {worst:.2f}%")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
