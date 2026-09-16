#!/usr/bin/env python3
"""Attribute the mdp speedup to its two optimizations.

report_mdp.txt section 3 lists two changes: 3.1 replaces the dictionaries keyed
by nested namedtuples with flat lists indexed by integers, and 3.2 memoizes
getCritDist. Each variant below is the optimized module with exactly one of them
put back, so the gap to the full optimized row is what that change is worth.

Both revert by substituting source rather than by patching a function. 3.1
cannot be a patch because the baseline's evaluate() would then run against the
baseline module's globals, taking the unmemoized getCritDist with it and
reverting both changes at once; splicing its source into the optimized module
keeps 3.2 in place, which is the point of a leave-one-out row.

Timings must come from the course VM like every other timing in this project.

    python3 scripts/ablation_mdp.py [reps] [output-file]
"""
import os, re, statistics, sys, time, types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from local_check import ensure_pyperf, load_benchmark  # noqa: E402

D = os.path.join(ROOT, "benchmarks", "mdp")
EXPECTED = 0.89873589887


def source(which):
    fname = "run_benchmark.py" if which == "base" else "run_benchmark_opt.py"
    return open(os.path.join(D, fname), encoding="utf-8").read()


def evaluate_src(text):
    """The body of Battle.evaluate, from its def line to the next line at or
    above its indentation."""
    lines = text.splitlines(keepends=True)
    start = next(i for i, l in enumerate(lines) if re.match(r"\s*def evaluate\(", l))
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = next((j for j in range(start + 1, len(lines))
                if lines[j].strip() and (len(lines[j]) - len(lines[j].lstrip())) <= indent),
               len(lines))
    return "".join(lines[start:end])


def build(tag, src):
    mod = types.ModuleType("mdp_" + tag)
    mod.__file__ = os.path.join(D, "run_benchmark_opt.py")
    ensure_pyperf()
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


def fresh(which):
    fname = "run_benchmark.py" if which == "base" else "run_benchmark_opt.py"
    return load_benchmark("mdp_" + which + "_ablation", os.path.join(D, fname))


def variant_no_flat():
    """3.1 reverted: the sweep goes back to dictionaries keyed by state tuples."""
    src = source("opt").replace(evaluate_src(source("opt")), evaluate_src(source("base")), 1)
    if "vmin[i0]" in evaluate_src(src):
        raise SystemExit("ablation_mdp: the flat-list sweep is still in evaluate()")
    return build("no_flat", src)


def variant_no_memo():
    """3.2 reverted: getCritDist recomputes instead of consulting the cache."""
    src = source("opt")
    for old, new in (("    hit = _CRITDIST_CACHE.get(key)\n"
                      "    if hit is not None:\n"
                      "        return hit\n", ""),
                     ("    _CRITDIST_CACHE[key] = dist\n", "")):
        if old not in src:
            raise SystemExit("ablation_mdp: the memo no longer matches:\n" + old)
        src = src.replace(old, new, 1)
    return build("no_memo", src)


VARIANTS = [
    ("baseline (as pyperformance ships it)", lambda: fresh("base"), "-"),
    ("optimized (both 3.1 and 3.2)", lambda: fresh("opt"), "-"),
    ("optimized, 3.1 reverted to the dict sweep", variant_no_flat, "3.1"),
    ("optimized, 3.2 reverted to recomputing", variant_no_memo, "3.2"),
]


def main():
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    dest = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "results", "mdp", "ablation.txt")

    mods = []
    for label, make, which in VARIANTS:
        m = make()
        got = m.Battle().evaluate(0.192)          # the benchmark's own gate
        if abs(got - EXPECTED) >= 1e-6:
            raise SystemExit("ablation_mdp: %s returned %r, not %r" % (label, got, EXPECTED))
        mods.append((label, which, m))

    # round-robin over the variants, so slow drift hits all of them equally
    times = [[] for _ in mods]
    for _ in range(reps):
        for ts, (label, which, m) in zip(times, mods):
            t0 = time.perf_counter()
            m.bench_mdp(1)
            ts.append(time.perf_counter() - t0)

    rows = []
    for ts, (label, which, _) in zip(times, mods):
        lo, med = min(ts), statistics.median(ts)
        rows.append((label, which, lo * 1e3, med * 1e3, (max(ts) - min(ts)) * 1e3))
        print("  %-44s min %8.1f ms  median %8.1f ms  spread %6.1f ms" % (label, lo * 1e3, med * 1e3, (max(ts) - min(ts)) * 1e3))

    base_ms, full_ms = rows[0][2], rows[1][2]
    out = [
        "Per-optimization ablation for mdp (scripts/ablation_mdp.py).",
        "",
        "Each row is the optimized module with exactly one change reverted to the",
        "shipped implementation, so the gap to the full optimized row is what that",
        "change is worth. Every variant is checked against the benchmark's own",
        "tolerance before it is timed, so a row that computed the wrong value could",
        "not appear here.",
        "",
        "  %-44s %10s %10s %9s" % ("variant", "min (ms)", "median", "vs base"),
    ]
    for label, which, lo, med, spread in rows:
        out.append("  %-44s %10.1f %10.1f %8.2fx" % (label, lo, med, base_ms / lo))
    out += ["", "What each change is worth (reverted row minus the full optimized row):"]
    for label, which, lo, med, spread in rows[2:]:
        out.append("    %-6s worth %6.1f ms, i.e. %.2fx of the overall %.2fx"
                   % (which, lo - full_ms, lo / full_ms, base_ms / full_ms))
    out += ["",
            "  reps per variant: %d, minimum reported (medians in the table above)." % reps]
    open(dest, "w").write("\n".join(out) + "\n")
    print("\nwrote " + os.path.relpath(dest, ROOT))


if __name__ == "__main__":
    main()
