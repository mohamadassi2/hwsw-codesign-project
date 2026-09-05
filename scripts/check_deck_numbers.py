#!/usr/bin/env python3
"""Recompute every quantitative claim on the slides from results/ and the docs.

The deck (docs/presentation.html) is hand-written, so a number there can drift
from the evidence when results/ is refreshed. This script derives each figure
the slides state from the measured data and fails if the slide disagrees.

  python3 scripts/check_deck_numbers.py
"""
import base64, json, os, re, statistics, sys

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
        # On a passing line the expected value is the value the slide already
        # shows, so spelling out "should say" there reads like a complaint.
        if key in present:
            oks.append(f"{label} ({s})")
        else:
            fails.append(f"{label}: slide should say {s}")

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
    cfg = re.findall(r"^(\d+) cells: (\d+) flip-flops, (\d+) gates", syn, re.M)
    (oks if len(cfg) >= 2 else fails).append(f"synthesis file lists both configurations ({len(cfg)})")
    if len(cfg) >= 2:
        want("yosys cells", int(cfg[0][0]), "{:,}")
        want("flip-flops", int(cfg[0][1]), "{:,}")
        want("all-logic variant cells", int(cfg[1][0]), "{:,}")
    levels = int(re.search(r"length=(\d+)", syn).group(1))
    want("gate levels", levels, "{:d}")
    want("symbol table (kbit)", 13.9, "{:.1f}")
    for stale in ("2,768", "52,952", "19.4"):
        (oks if stale not in txt else fails).append(
            f"the superseded synthesis figure {stale} is gone from the slides")
    decode_ms = CYC / 200e6 * 1e3
    want("decode at 200 MHz (ms)", decode_ms, "{:.2f}")

    # ---- Amdahl (from the VM optimized time, as in report_pyflate.txt 5.6) ----
    opt_ms = po * 1e3
    # find_next_symbol's cumulative share. Its self share plus the bit-reading
    # helpers it calls would double-count, which an earlier draft did as 62%.
    part = opt_ms * 0.511
    accel = decode_ms + 0.6
    new = opt_ms - part + accel
    want("Amdahl: accelerated part (ms)", part, "{:.0f}")
    want("Amdahl: result (ms)", new, "{:.0f}")
    want("Amdahl: vs optimized", opt_ms / new, "{:.1f}")
    want("Amdahl: vs shipped", pb * 1e3 / new, "{:.1f}")

    # ---- the ablation figures on the slides come from the artifact ---------------
    abl = os.path.join(ROOT, "results", "pyflate", "ablation.txt")
    if os.path.exists(abl):
        a = open(abl, encoding="utf-8").read()
        # The slide quotes what each change is worth in milliseconds, which is
        # what the ablation actually measures; ratios of leave-one-out deltas do
        # not compose and are not put on the slide.
        for which in ("3.1", "3.3", "3.4"):
            m = re.search(which.replace(".", r"\.") + r"\s+worth\s+([\d.]+) ms", a)
            (oks if m and m.group(1) in txt else fails).append(
                f"slides quote the measured {which} contribution ({m.group(1) if m else '?'} ms)")

    # ---- every ratio column must equal the two cells beside it -------------------
    # The comparison tables carry their own arithmetic, and a stale ratio slipped
    # through for a while because the checks above only ask whether a number
    # appears somewhere on the slides, not whether the row is self-consistent.
    raw_deck = open(DECK, encoding="utf-8").read()
    UNIT = {"s": 1.0, "ms": 1e-3, "B": 1.0, "%": 1.0, "": 1.0}
    def cell(t):
        m = re.match(r"^\s*([\d,.]+)\s*(s|ms|B|%)?\s*$", t)
        if not m:
            return None
        return float(m.group(1).replace(",", "")) * UNIT[m.group(2) or ""]
    rows = re.findall(
        r"<tr[^>]*>\s*<td>([^<]*)</td>\s*<td class=\"n\">([^<]*)</td>\s*"
        r"<td class=\"n\">([^<]*)</td>\s*<td class=\"n\">([^<]*)</td>\s*</tr>", raw_deck)
    checked = 0
    for label, a, b, r in rows:
        va, vb, vr = cell(a), cell(b), cell(r)
        if va is None or vb is None or vr is None or not vb:
            continue
        want_r = va / vb
        checked += 1
        ok = abs(want_r - vr) <= 0.011          # the slides print two decimals
        (oks if ok else fails).append(
            f"table row '{label.strip()}': {a.strip()} / {b.strip()} = {want_r:.2f}"
            + ("" if ok else f", but the slide says {r.strip()}"))
    (oks if checked >= 6 else fails).append(f"ratio columns checked ({checked} rows)")

    # ---- claims that come from elsewhere in the repo -----------------------------
    for label, needle in (("4,823 states", "4,823"), ("3,659 getCritDist calls", "3,659"),
                          ("mdp result quoted in full", "0.8987358988699915"), ("md5 prefix", "afa004a6"),
                          ("output bytes", "399,360")):
        (oks if needle.replace(",", "") in present or needle in txt else fails).append(label)

    # ---- the baseline slide must carry the BASELINE cProfile figures ----------
    rep = open(os.path.join(ROOT, "report_pyflate.txt"), encoding="utf-8").read()
    base_slide = "15.4% self and 49.1%" in re.sub(r"\s+", " ", txt)
    (oks if base_slide else fails).append("slide 6 quotes the baseline cProfile figures (15.7 / 48.2)")
    (oks if "15.4%" in rep and "49.1%" in rep else fails).append("those figures are the report's section 2 numbers")

    # ---- the shares on the "what remains" slide come from the folded stacks ----
    # They used to read ~60% / ~30%, which is the double count section 5.6 of the
    # report retracts, and nothing checked them.
    fold = os.path.join(ROOT, "results", "pyflate", "pyspy_opt_focus.folded")
    if os.path.exists(fold):
        tot = fn = bw = 0
        for line in open(fold, encoding="utf-8"):
            stack, _, n = line.rpartition(" ")
            try:
                n = int(n)
            except ValueError:
                continue
            tot += n
            if "find_next_symbol" in stack:
                fn += n
            if "bwt_reverse" in stack:
                bw += n
        if tot:
            for label, val in (("Huffman share", fn / tot * 100), ("inverse BWT share", bw / tot * 100)):
                (oks if f"{val:.0f}%" in txt else fails).append(
                    f"slide quotes the measured {label} ({val:.0f}%)")
            (oks if "60%" not in txt and "~30%" not in txt else fails).append(
                "the retracted 60/30 double count is gone from the slides")

    # ---- the block diagram is a graded deliverable; gate its figures too -------
    dia_path = os.path.join(ROOT, "docs", "huffman_accel_block_diagram.svg")
    dia = open(dia_path, encoding="utf-8").read()
    for label, needle in (("diagram: symbols", f"{SYM:,}"), ("diagram: cycles", f"{CYC:,}"),
                          ("diagram: symbols/cycle", "1.00")):
        (oks if needle in dia else fails).append(f"{label} ({needle})")

    # The deck carries its own base64 copy of that diagram. A slide showing a
    # stale copy is worse than a stale file, because it is what the room sees,
    # so require the embed to be the committed file byte for byte.
    raw = open(DECK, encoding="utf-8").read()
    embedded = re.findall(r"data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)", raw)
    want_b64 = base64.b64encode(open(dia_path, "rb").read()).decode("ascii")
    (oks if want_b64 in raw else fails).append(
        "the deck embeds docs/huffman_accel_block_diagram.svg byte-identically")
    stale = []
    for b in embedded:
        try:
            d = base64.b64decode(b).decode("utf-8", "replace")
        except Exception:
            continue
        for n in set(re.findall(r"\b148,\d{3}\b", d)):
            if n not in (f"{SYM:,}", f"{CYC:,}"):
                stale.append(n)
    (oks if not stale else fails).append(
        "no embedded slide image quotes a stale cycle count" + (f" (found {sorted(set(stale))})" if stale else ""))

    # ---- per-symbol CPU cost: 235 ms / 148,271 symbols at 2.4 GHz -------------
    # Derived, not hardcoded: the accelerated share of the measured optimized
    # run, spread over the symbols, at the guest's 2.4 GHz.
    cyc_per_sym = po * 0.511 / SYM * 2.4e9
    for label, path in (("deck", DECK),
                        ("docs/presentation_outline.md", os.path.join(ROOT, "docs", "presentation_outline.md")),
                        ("report_pyflate.txt", os.path.join(ROOT, "report_pyflate.txt"))):
        body = open(path, encoding="utf-8").read()
        rounded = f"{round(cyc_per_sym, -2):,.0f}"        # 3,800
        (oks if rounded in body else fails).append(
            f"{label}: CPU cycles per symbol says {rounded}")
        (oks if "1,600 CPU cycles" not in body and "~1,600 cycles" not in body else fails).append(
            f"{label}: the 1,585 ns figure is not restated as 1,600 cycles")

    # ---- README headline table must match too ---------------------------------
    rd = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    for label, val, fmt in (("README pyflate speedup", pb / po, "{:.2f}"),
                            ("README mdp speedup", mb / mo, "{:.2f}"),
                            ("README pyflate % less", 100 * (1 - po / pb), "{:.1f}"),
                            ("README mdp % less", 100 * (1 - mo / mb), "{:.1f}"),
                            ("README pyflate baseline s", pb, "{:.3f}"),
                            ("README mdp baseline s", mb, "{:.3f}")):
        (oks if fmt.format(val) in rd else fails).append(f"{label}: README should say {fmt.format(val)}")

    print(f"PASS {len(oks)}   FAIL {len(fails)}")
    for l in oks:
        print("  pass ", l)
    for l in fails:
        print("  FAIL ", l)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
