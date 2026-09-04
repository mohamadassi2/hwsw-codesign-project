#!/usr/bin/env python3
"""Recompute every quantitative claim on the slides from results/ and the docs.

The deck (docs/presentation.html) is hand-written, so a number there can drift
from the evidence when results/ is refreshed. This script derives each figure
the slides state from the measured data and fails if the slide disagrees.

  python3 scripts/check_deck_numbers.py
"""
import json, os, re, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DECK = os.path.join(ROOT, "docs", "presentation.html")


def slide_text():
    s = open(DECK, encoding="utf-8").read()
    s = re.sub(r"data:image/svg\+xml;base64,[A-Za-z0-9+/=]+", "", s)
    s = re.sub(r"<style>.*?</style>|<script>.*?</script>", "", s, flags=re.S)
    s = re.sub(r"<svg.*?</svg>", "", s, flags=re.S)          # the bit strips
    s = re.sub(r"<[^>]+>", " ", s)
    for a, b in (("&nbsp;", " "), ("&times;", "x"), ("&rarr;", "->"), ("&mdash;", "-"),
                 ("&plusmn;", "+-"), ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&")):
        s = s.replace(a, b)
    return s


def mean(path):
    d = json.load(open(path))
    v = [x for b in d["benchmarks"] for r in b["runs"] for x in r.get("values", [])]
    return statistics.mean(v), len(v)


def perfstat(path):
    r = {}
    for line in open(path):
        m = re.match(r"\s*([\d,\.]+)\s+(?:msec\s+)?([a-z-]+)", line)
        if m:
            r[m.group(2)] = float(m.group(1).replace(",", ""))
    return r


def main():
    txt = slide_text()
    present = set(m.replace(",", "") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", txt))
    fails, oks = [], []

    def want(label, value, fmt):
        """The slide must contain `value` printed as `fmt` (a format string)."""
        s = fmt.format(value)
        key = s.replace(",", "")
        (oks if key in present else fails).append(f"{label}: slide should say {s}")

    # ---- measured times and speedups --------------------------------------
    pb, npb = mean(f"{ROOT}/results/pyflate/pyflate_base.json")
    po, npo = mean(f"{ROOT}/results/pyflate/pyflate_opt.json")
    mb, nmb = mean(f"{ROOT}/results/mdp/mdp_base.json")
    mo, nmo = mean(f"{ROOT}/results/mdp/mdp_opt.json")
    want("pyflate baseline (s)", pb, "{:.3f}")
    want("pyflate optimized (ms)", po * 1e3, "{:.0f}")
    want("pyflate speedup", pb / po, "{:.2f}")
    want("pyflate % less time", 100 * (1 - po / pb), "{:.1f}")
    want("pyflate n", npb, "{:d}")
    want("mdp baseline (s)", mb, "{:.3f}")
    want("mdp optimized (s)", mo, "{:.3f}")
    want("mdp speedup", mb / mo, "{:.2f}")
    want("mdp % less time", 100 * (1 - mo / mb), "{:.1f}")
    want("mdp n", nmb, "{:d}")

    # ---- hardware counters ---------------------------------------------------
    b, o = perfstat(f"{ROOT}/results/pyflate/perfstat_base.txt"), perfstat(f"{ROOT}/results/pyflate/perfstat_opt.txt")
    want("pyflate insn base (B)", b["instructions"] / 1e9, "{:.2f}")
    want("pyflate insn opt (B)", o["instructions"] / 1e9, "{:.2f}")
    want("pyflate cycles base (B)", b["cycles"] / 1e9, "{:.2f}")
    want("pyflate cycles opt (B)", o["cycles"] / 1e9, "{:.2f}")
    want("pyflate IPC base", b["instructions"] / b["cycles"], "{:.2f}")
    want("pyflate IPC opt", o["instructions"] / o["cycles"], "{:.2f}")
    want("pyflate insn removed (B)", (b["instructions"] - o["instructions"]) / 1e9, "{:.1f}")
    want("pyflate branch-miss % base", 100 * b["branch-misses"] / b["branches"], "{:.2f}")
    want("pyflate branch-miss % opt", 100 * o["branch-misses"] / o["branches"], "{:.2f}")
    b, o = perfstat(f"{ROOT}/results/mdp/perfstat_base.txt"), perfstat(f"{ROOT}/results/mdp/perfstat_opt.txt")
    want("mdp insn base (B)", b["instructions"] / 1e9, "{:.1f}")
    want("mdp insn opt (B)", o["instructions"] / 1e9, "{:.1f}")
    want("mdp cycles base (B)", b["cycles"] / 1e9, "{:.2f}")
    want("mdp cycles opt (B)", o["cycles"] / 1e9, "{:.2f}")
    want("mdp IPC base", b["instructions"] / b["cycles"], "{:.2f}")
    want("mdp IPC opt", o["instructions"] / o["cycles"], "{:.2f}")

    # ---- PMU diagnosis --------------------------------------------------------
    pmi = re.findall(r"PMI:\s+(\d+)", open(f"{ROOT}/results/pyflate/pmu_diagnosis.txt").read())
    (oks if pmi and set(pmi) == {"0"} and "PMI" in txt else fails).append(
        f"PMI stays at 0 across a record: measured {pmi}")

    # ---- accelerator ---------------------------------------------------------------
    SYM, CYC, BITS = 148271, 148272, 531571
    want("symbols decoded", SYM, "{:,}")
    want("cycles", CYC, "{:,}")
    want("bits", BITS, "{:,}")
    want("symbols/clock", SYM / CYC, "{:.3f}")      # 1.000
    want("bits/symbol", BITS / SYM, "{:.2f}")
    syn = open(f"{ROOT}/docs/synthesis_yosys.txt").read()
    cells = int(re.search(r"(\d+) cells", syn).group(1))
    want("yosys cells", cells, "{:,}")
    levels = int(re.search(r"length=(\d+)", syn).group(1))
    want("gate levels", levels, "{:d}")
    want("table bits (kbit)", 19.4, "{:.1f}")
    want("flattened variant cells", 51592, "{:,}")
    decode_ms = CYC / 200e6 * 1e3
    want("decode at 200 MHz (ms)", decode_ms, "{:.2f}")

    # ---- Amdahl (from the VM optimized time, as in report_pyflate.txt 5.6) ----
    opt_ms = po * 1e3
    part = opt_ms * 0.62
    accel = decode_ms + 0.6
    new = opt_ms - part + accel
    want("Amdahl: 62% of optimized (ms)", part, "{:.0f}")
    want("Amdahl: result (ms)", new, "{:.0f}")
    want("Amdahl: vs optimized", opt_ms / new, "{:.1f}")
    want("Amdahl: vs shipped", pb * 1e3 / new, "{:.1f}")

    # ---- claims that come from elsewhere in the repo -----------------------------
    for label, needle in (("4,823 states", "4,823"), ("3,659 getCritDist calls", "3,659"),
                          ("389,711 state updates", "389,711"), ("md5 prefix", "afa004a6"),
                          ("output bytes", "399,360")):
        (oks if needle.replace(",", "") in present or needle in txt else fails).append(label)

    print(f"PASS {len(oks)}   FAIL {len(fails)}")
    for l in oks:
        print("  pass ", l)
    for l in fails:
        print("  FAIL ", l)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
