#!/usr/bin/env python3
"""Per-function shares, recomputed from the committed cProfile artifacts.

Prints the per-function self and cumulative shares that the cProfile tables in
sections 2 and 4 of each report quote, as percentages of the benchmark
function's cumulative time, recomputed from results/<b>/cprofile_{base,opt}.txt.
scripts/check_report_numbers.py gates the load-bearing rows against the same
files.

    python3 scripts/cprofile_shares.py [benchmark ...]
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# An entry is either a bare function name, matched against the (function) field
# exactly, or a "file.py:line(function)" fragment matched as a substring. Bare
# substring matching picked getSuccessorsList when asked for getSuccessors, and
# silently dropped every row whose name it could not distinguish.
ROWS = {
    "pyflate": ["find_next_symbol", "decode_huffman_block", "readbits", "snoopbits",
                "move_to_front", "_mask", "bwt_reverse", "bwt_transform", "_more",
                "append", "insert", "pop"],
    "mdp": ["evaluate", "run_benchmark.py:236(<genexpr>)", "run_benchmark.py:238(<genexpr>)",
            "run_benchmark_opt.py:236(<genexpr>)", "run_benchmark_opt.py:238(<genexpr>)",
            "builtins.sum", "builtins.max", "_add", "__new__", "getSuccessors",
            "forward", "getCritDist", "_applyActionSide1", "applyHPChange",
            "_replace", "_richcmp", "gcd"],
}
DENOM = {"pyflate": "bench_pyflake", "mdp": "bench_mdp"}


def rows(path):
    """(ncalls, tottime, cumtime, label) for every line of a pstats table"""
    out = []
    for m in re.finditer(r"^\s+(\d+(?:/\d+)?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+)$",
                         open(path, encoding="utf-8").read(), re.M):
        out.append((m.group(1), float(m.group(2)), float(m.group(4)), m.group(6).strip()))
    return out


def matches(want, label):
    """A bare name must be the whole (function) field; a fragment is a substring.

    Built-ins are the exception: pstats writes them as "{built-in method
    builtins.sum}", with no parenthesised function field at all, so they are
    matched as a substring too.
    """
    if ":" in want or "(" in want or "." in want:
        return want in label
    return label.endswith("(" + want + ")")


def main():
    for b in (sys.argv[1:] or ["pyflate", "mdp"]):
        for tag in ("base", "opt"):
            p = os.path.join(ROOT, "results", b, f"cprofile_{tag}.txt")
            if not os.path.exists(p):
                continue
            rs = rows(p)
            den = next((c for _, _, c, lbl in rs if DENOM[b] in lbl), None)
            if not den:
                print(f"{b}/{tag}: no {DENOM[b]} row"); continue
            print(f"\n{b} {tag}  (denominator: {DENOM[b]} cumulative = {den:.3f} s)")
            print(f"    {'function':26s}{'self':>8s}{'cum':>8s}{'calls':>12s}")
            seen = set()
            for want in ROWS[b]:
                for ncalls, tot, cum, lbl in rs:
                    if matches(want, lbl) and lbl not in seen:
                        seen.add(lbl)
                        short = re.sub(r".*\(|\)$", "", lbl) or want
                        if want.startswith("run_benchmark"):
                            short = "<genexpr>@" + want.split(":")[1].split("(")[0]
                        print(f"    {short:26s}{tot/den*100:7.1f}%{cum/den*100:7.1f}%{ncalls:>12s}")
                        break


if __name__ == "__main__":
    main()
