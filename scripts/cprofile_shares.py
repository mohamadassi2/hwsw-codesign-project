#!/usr/bin/env python3
"""Per-function shares, recomputed from the committed cProfile artifacts.

The tables in the reports were written by hand from an earlier profiling run and
did not recompute from results/<b>/cprofile_*.txt once the evidence was replaced.
This prints the shares the artifacts actually support, so the tables can be
regenerated from them and gated.

    python3 scripts/cprofile_shares.py [benchmark ...]
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROWS = {
    "pyflate": ["find_next_symbol", "decode_huffman_block", "readbits", "snoopbits",
                "move_to_front", "_mask", "bwt_reverse", "bwt_transform", "_more",
                "append", "insert", "pop"],
    "mdp": ["evaluate", "getSuccessors", "getCritDist", "_add", "_richcmp",
            "__new__", "_replace", "gcd"],
}
DENOM = {"pyflate": "bench_pyflake", "mdp": "bench_mdp"}


def rows(path):
    """(ncalls, tottime, cumtime, label) for every line of a pstats table"""
    out = []
    for m in re.finditer(r"^\s+(\d+(?:/\d+)?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+)$",
                         open(path, encoding="utf-8").read(), re.M):
        out.append((m.group(1), float(m.group(2)), float(m.group(4)), m.group(6).strip()))
    return out


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
                    if want in lbl and lbl not in seen:
                        seen.add(lbl)
                        print(f"    {want:26s}{tot/den*100:7.1f}%{cum/den*100:7.1f}%{ncalls:>12s}")
                        break


if __name__ == "__main__":
    main()
