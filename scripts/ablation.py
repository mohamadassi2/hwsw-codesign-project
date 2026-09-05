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
    return _load_without_pyperf(name, os.path.join(D, "run_benchmark%s.py" % ("" if which == "base" else "_opt")))


def variant_from_source(tag, *replacements):
    """Load the optimized module with the given source substitutions applied.

    Reverting a change by monkey-patching only works when the optimized code
    still calls the thing being patched. It does not for move-to-front: the
    optimized decoder inlines the pop/insert into the decode loop and reaches
    the module-level move_to_front only for the six-element selector list, so
    patching that function reverted 2,966 of 92,803 operations and reported the
    change as worth nothing. Substituting the source reverts what actually runs.
    """
    import importlib.util, types
    src = open(os.path.join(D, "run_benchmark_opt.py"), encoding="utf-8").read()
    for old, new in replacements:
        if old not in src:
            raise SystemExit("ablation: source substitution for %s no longer matches:\n%s" % (tag, old))
        src = src.replace(old, new, 1)
    mod = types.ModuleType("pyflate_opt_" + tag)
    mod.__file__ = os.path.join(D, "run_benchmark_opt.py")
    _load_without_pyperf("pyflate_probe_" + tag, os.path.join(D, "run_benchmark_opt.py"))  # ensure the pyperf stub exists
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


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
    """3.3 reverted: move-to-front goes back to the shipped slice rebuild.

    Both call sites, the inlined one in the decode loop and the selector list.
    """
    return variant_from_source(
        "no_mtf",
        ("            o = fav_pop(r - 1)      # move-to-front, inlined\n"
         "            fav_insert(0, o)\n",
         "            o = favourites[r - 1]\n"
         "            favourites[:] = favourites[r - 1:r] + favourites[0:r - 1] + favourites[r:]\n"),
        ("def move_to_front(l, c):\n    l.insert(0, l.pop(c))\n",
         "def move_to_front(l, c):\n    l[:] = l[c:c + 1] + l[0:c] + l[c + 1:]\n"),
    )


def variant_no_rle():
    """3.4 reverted: the final RLE pass goes back to the per-byte loop."""
    return variant_from_source(
        "no_rle",
        ("    out.append(_RLE4.sub(lambda m: m.group(1) * (m.group(2)[0] + 4), nearly_there))",
         "    nt = nearly_there\n"
         "    i = 0\n"
         "    while i < len(nearly_there):\n"
         "        if i < len(nearly_there) - 4 and nt[i] == nt[i + 1] == nt[i + 2] == nt[i + 3]:\n"
         "            out.append(nearly_there[i:i + 1] * (ord(nearly_there[i + 4:i + 5]) + 4))\n"
         "            i += 5\n"
         "        else:\n"
         "            out.append(nearly_there[i:i + 1])\n"
         "            i += 1"),
    )


VARIANTS = [
    ("baseline (as pyperformance ships it)", lambda: fresh("base"), "-"),
    ("optimized (all of 3.1-3.5)", variant_full, "-"),
    ("optimized, 3.1 reverted to the table scan", variant_no_canonical, "3.1"),
    ("optimized, 3.3 reverted to the slice rebuild", variant_no_mtf, "3.3"),
    ("optimized, 3.4 reverted to the per-byte RLE loop", variant_no_rle, "3.4"),
]


def main():
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    dest = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "results", "pyflate", "ablation.txt")

    mods = []
    for label, build, which in VARIANTS:
        m = build()
        m.bench_pyflake(1, DATA)          # the benchmark's own md5 check; raises if a
                                          # reverted piece broke the output
        mods.append((label, which, m))

    # Interleaved, not blocked: running all reps of one variant and then all of
    # the next lets drift between blocks masquerade as a difference between
    # variants. Round-robin spreads any drift evenly.
    # Keyed by position, not by the change name: the baseline and the full
    # optimized row both carry "-", so keying by name pooled their times and
    # made the spread look like the difference between them.
    times = {i: [] for i in range(len(mods))}
    for _ in range(reps):
        for i, (label, which, m) in enumerate(mods):
            t0 = time.perf_counter()
            m.bench_pyflake(1, DATA)
            times[i].append(time.perf_counter() - t0)

    rows = []
    for i, (label, which, _) in enumerate(mods):
        ts = times[i]
        lo, med = min(ts), statistics.median(ts)
        spread = max(ts) - min(ts)
        rows.append((label, which, lo * 1e3, med * 1e3, spread * 1e3))
        print("  %-46s min %8.1f ms  median %8.1f ms  spread %6.1f ms"
              % (label, lo * 1e3, med * 1e3, spread * 1e3))

    base_ms = rows[0][2]
    full_ms = rows[1][2]
    noise = max(r[4] for r in rows[1:])   # the optimized-size rows only
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
    for label, which, lo, med, spread in rows:
        out.append("  %-46s %10.1f %10.1f %8.2fx" % (label, lo, med, base_ms / lo))
    out.append("")
    out.append("  contribution of each separable change (full optimized = %.1f ms):" % full_ms)
    out.append("  These are leave-one-out differences. They do not multiply out to the")
    out.append("  overall speedup and are not meant to: each says what the run costs with")
    out.append("  that one change put back, everything else kept.")
    out.append("  Largest run-to-run spread across variants: %.1f ms - a contribution" % noise)
    out.append("  smaller than that is not resolved by this measurement." )
    for label, which, lo, med, spread in rows[2:]:
        delta = lo - full_ms
        note = "" if abs(delta) > noise else "   (within the noise; not resolved)"
        out.append("    %-6s worth %6.1f ms, i.e. %.2fx of the overall %.2fx%s"
                   % (which, delta, lo / full_ms, base_ms / full_ms, note))
    out.append("")
    out.append("  3.2 (bit reader) and 3.5 (local names, bytearray) are woven through the")
    out.append("  decode loop and cannot be reverted on their own, so they are not listed")
    out.append("  separately; what they are worth is whatever the rows above do not explain.")
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
