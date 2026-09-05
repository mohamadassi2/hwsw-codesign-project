#!/usr/bin/env python3
"""Attribute the pyflate speedup to the individual optimizations.

report_pyflate.txt section 3 lists five changes. Quoting one overall speedup
for all five says nothing about which of them earned it, and section 3.1 is
labelled "the main fix" - a claim worth measuring rather than asserting.

Each variant below is the optimized module with exactly one change put back to
the shipped implementation, so the difference from the full optimized run is
that change's contribution. Only the changes that are separable this way are
measured; 3.2 (the bit reader) and 3.5 (local names) are woven through the
decode loop and cannot be reverted without rewriting it, so they are reported
together as the remainder.

Timings must come from the course VM like every other timing in this project.

    python3 scripts/ablation.py [reps] [output-file]
"""
import os, statistics, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from local_check import _load_without_pyperf  # noqa: E402

D = os.path.join(ROOT, "benchmarks", "pyflate")
DATA = os.path.join(D, "data", "interpreter.tar.bz2")


def fresh(which):
    name = "pyflate_" + which + "_ablation"
    sys.modules.pop(name, None)
    return _load_without_pyperf(name, os.path.join(D, "run_benchmark%s.py" % ("" if which == "base" else "_opt")))


def timed(fn, reps):
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return min(ts), statistics.median(ts)


def variant_full():
    return fresh("opt")


def variant_no_canonical():
    """3.1 reverted: the canonical decode goes back to the shipped linear scan."""
    m = fresh("opt")
    b = fresh("base")
    m.HuffmanTable.find_next_symbol = b.HuffmanTable.find_next_symbol
    return m


def variant_no_mtf():
    """3.3 reverted: move-to-front goes back to the shipped slice rebuild."""
    m = fresh("opt")
    b = fresh("base")
    m.move_to_front = b.move_to_front
    return m


VARIANTS = [
    ("baseline (as pyperformance ships it)", lambda: fresh("base"), "-"),
    ("optimized (all of 3.1-3.5)", variant_full, "-"),
    ("optimized, 3.1 reverted to the table scan", variant_no_canonical, "3.1"),
    ("optimized, 3.3 reverted to the slice rebuild", variant_no_mtf, "3.3"),
]


def main():
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    dest = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "results", "pyflate", "ablation.txt")

    rows = []
    for label, build, which in VARIANTS:
        m = build()
        m.bench_pyflake(1, DATA)          # the benchmark's own md5 check; raises if a
                                          # reverted piece broke the output
        lo, med = timed(lambda: m.bench_pyflake(1, DATA), reps)
        rows.append((label, which, lo * 1e3, med * 1e3))
        print("  %-46s min %8.1f ms  median %8.1f ms" % (label, lo * 1e3, med * 1e3))

    base_ms = rows[0][2]
    full_ms = rows[1][2]
    out = [
        "Per-optimization ablation for pyflate (scripts/ablation.py).",
        "",
        "Each row is the optimized decoder with exactly one change reverted to the",
        "shipped implementation, so the gap to the full optimized row is what that",
        "change is worth. Every variant is checked against the benchmark's own md5",
        "before it is timed, so a row that decoded wrongly could not appear here.",
        "",
        "  %-46s %10s %10s %9s" % ("variant", "min (ms)", "median", "vs base"),
    ]
    for label, which, lo, med in rows:
        out.append("  %-46s %10.1f %10.1f %8.2fx" % (label, lo, med, base_ms / lo))
    out.append("")
    out.append("  contribution of each separable change (full optimized = %.1f ms):" % full_ms)
    for label, which, lo, med in rows[2:]:
        out.append("    %-6s worth %6.1f ms, i.e. %.2fx of the overall %.2fx"
                   % (which, lo - full_ms, lo / full_ms, base_ms / full_ms))
    out.append("")
    out.append("  3.2 (bit reader) and 3.5 (local names, bytearray) are inside the decode")
    out.append("  loop and cannot be reverted in isolation; they account for the remainder.")
    out.append("")
    out.append("  reps per variant: %d, minimum reported (medians in the table above)." % reps)
    text = "\n".join(out) + "\n"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w") as f:
        f.write(text)
    print()
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
