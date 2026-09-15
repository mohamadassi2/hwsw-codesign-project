#!/usr/bin/env python3
"""Measure the shipped decoder's linear table scan on the real benchmark input.

report_pyflate.txt section 3.1 says the baseline's linear scan of the Huffman
code table is the algorithmic problem the optimized decoder removes. This
measures that scan on the benchmark input:

  * how many entries the tables really have (bzip2 permits 258),
  * how many entries the scan touches per symbol, mean and worst case.

The counts are properties of the input file and the format, so they are the
same on any machine; they are written to results/pyflate/table_stats.txt as
the artifact the report cites.

    python3 scripts/table_stats.py [output-file]
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from local_check import load_benchmark  # noqa: E402


def main():
    d = os.path.join(ROOT, "benchmarks", "pyflate")
    data = os.path.join(d, "data", "interpreter.tar.bz2")
    m = load_benchmark("pyflate_base_stats", os.path.join(d, "run_benchmark.py"))

    scans = []          # table entries compared, one entry per decoded symbol
    peeks = []          # snoopbits() calls made while scanning, per symbol
    sizes = set()       # table sizes actually built

    original = m.HuffmanTable.find_next_symbol

    def counting(self, field, reversed=True):
        """The shipped find_next_symbol with the three counters added."""
        sizes.add(len(self.table))
        cached_length = -1
        cached = None
        n = 0
        p = 0
        for x in self.table:
            n += 1
            if cached_length != x.bits:
                cached = field.snoopbits(x.bits)
                cached_length = x.bits
                p += 1
            if (reversed and x.reverse_symbol == cached) or (not reversed and x.symbol == cached):
                field.readbits(x.bits)
                scans.append(n)
                peeks.append(p)
                return x.code
        scans.append(n)
        peeks.append(p)
        raise Exception("unfound symbol, even after end of table @%r" % field.tell())

    m.HuffmanTable.find_next_symbol = counting
    try:
        m.bench_pyflake(1, data)
    finally:
        m.HuffmanTable.find_next_symbol = original

    out = [
        "Linear table scan in the shipped pyflate decoder (benchmarks/pyflate/run_benchmark.py),",
        "measured on the benchmark input benchmarks/pyflate/data/interpreter.tar.bz2.",
        "The decoder is instrumented with counters only; its behaviour is unchanged.",
        "",
        f"symbols decoded                       {len(scans):,}",
        f"distinct table sizes built            {sorted(sizes)}",
        f"largest table                         {max(sizes)} entries (bzip2 permits 258)",
        f"table entries compared, total         {sum(scans):,}",
        f"table entries compared, mean/symbol   {sum(scans) / len(scans):.1f}",
        f"table entries compared, worst symbol  {max(scans)}",
        f"snoopbits() calls, total              {sum(peeks):,}",
        f"snoopbits() calls, mean/symbol        {sum(peeks) / len(peeks):.1f}",
        "",
        "The scan is short on average because the table is sorted by code length and",
        "the short codes carry most of the symbols. What the canonical decoder removes",
        "is therefore not a long walk but the scan itself together with its repeated",
        "bit peeks: one peek and a handful of integer operations replace both.",
    ]
    text = "\n".join(out) + "\n"
    dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "results", "pyflate", "table_stats.txt")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w") as f:
        f.write(text)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
