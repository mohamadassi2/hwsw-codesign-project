#!/usr/bin/env python3
"""Recompute every quantitative claim on the slides from results/ and the docs.

The deck (docs/presentation.html) is hand-written, so a number there can drift
from the evidence when results/ is refreshed. This script derives each figure
the slides state from the measured data and fails if the slide disagrees.

  python3 scripts/check_deck_numbers.py
"""
import base64, bz2, collections, hashlib, json, os, re, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DECK = os.path.join(ROOT, "docs", "presentation.html")


def slide_text():
    s = open(DECK, encoding="utf-8").read()
    s = re.sub(r"data:image/svg\+xml;base64,[A-Za-z0-9+/=]+", "", s)
    s = re.sub(r"<style>.*?</style>|<script>.*?</script>", "", s, flags=re.S)
    s = re.sub(r"<svg.*?</svg>", "", s, flags=re.S)          # inline drawings (the bit strips)
    # The slide number in the header and the "07/23" in the footer are chrome,
    # not claims; leaving them in would let the page numbering satisfy a gate
    # about a measurement - "n = 18 runs" was being propped up by "18/23".
    s = re.sub(r'<span class="kick">\s*\d+\s*</span>', " ", s)
    s = re.sub(r"<span>\s*\d+/\d+\s*</span>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    for a, b in (("&nbsp;", " "), ("&times;", "x"), ("&rarr;", "->"), ("&mdash;", "-"),
                 ("&plusmn;", "+-"), ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&")):
        s = s.replace(a, b)
    # One space everywhere, so a check for a phrase - and especially a check that
    # a retracted figure is absent - cannot be defeated by where the markup put a
    # line break. A negative check against unflattened text passes the moment the
    # phrase wraps, which is the retracted figure back and nobody told.
    return re.sub(r"\s+", " ", s)


def mean(path):
    d = json.load(open(path))
    v = [x for b in d["benchmarks"] for r in b["runs"] for x in r.get("values", [])]
    return statistics.mean(v), len(v)


def stdev(path):
    d = json.load(open(path))
    v = [x for b in d["benchmarks"] for r in b["runs"] for x in r.get("values", [])]
    return statistics.stdev(v)


def cprofile_shares(path, want):
    """(self%, cumulative%) of one function, as shares of the benchmark function"""
    rows, den = [], None
    for m in re.finditer(r"^\s+\d+(?:/\d+)?\s+([\d.]+)\s+[\d.]+\s+([\d.]+)\s+[\d.]+\s+(.+)$",
                         open(path, encoding="utf-8").read(), re.M):
        rows.append((float(m.group(1)), float(m.group(2)), m.group(3).strip()))
    for _, cum, label in rows:
        if "(bench_pyflake)" in label or "(bench_mdp)" in label:
            den = cum
            break
    for own, cum, label in rows:
        if label.endswith("(" + want + ")"):
            return own / den * 100, cum / den * 100
    raise SystemExit(f"{path}: no {want} row")


def perfstat(path):
    r = {}
    for line in open(path):
        m = re.match(r"\s*([\d,\.]+)\s+(?:msec\s+)?([a-z-]+)", line)
        if m:
            r[m.group(2)] = float(m.group(1).replace(",", ""))
    return r


def main():
    txt = slide_text()
    # How many times each number is stated, not merely whether it is. A figure
    # the deck repeats - 2.34x is on slides 1 and 9, 487 ms on 1, 9, 21 and 22 -
    # used to be satisfied by any one of its copies, so a slide could drift from
    # the others and every gate stayed green. Counting is what makes each copy
    # load-bearing; scripts/mutate_gates.py is what proves it.
    present = collections.Counter(m.replace(",", "")
                                  for m in re.findall(r"\d[\d,]*(?:\.\d+)?", txt))
    fails, oks = [], []

    def check(label, ok):
        if ok:
            oks.append(label)
        else:
            fails.append(label)

    def want(label, value, fmt, times=1):
        """The slides must state `value`, printed as `fmt`, exactly `times` times."""
        s = fmt.format(value)
        got = present[s.replace(",", "")]
        if got == times:
            oks.append(f"{label} ({s})")
        elif got == 0:
            fails.append(f"{label}: no slide says {s}")
        else:
            fails.append(f"{label}: {s} is stated {got} times, expected {times}"
                         f" - a copy has drifted, or a slide gained or lost one")

    # ---- measured times and speedups --------------------------------------
    pb, npb = mean(f"{ROOT}/results/pyflate/pyflate_base.json")
    po, npo = mean(f"{ROOT}/results/pyflate/pyflate_opt.json")
    mb, nmb = mean(f"{ROOT}/results/mdp/mdp_base.json")
    mo, nmo = mean(f"{ROOT}/results/mdp/mdp_opt.json")
    want("pyflate baseline (s)", pb, "{:.3f}", times=4)
    want("pyflate optimized (ms)", po * 1e3, "{:.0f}", times=5)
    want("pyflate speedup", pb / po, "{:.2f}", times=3)
    want("pyflate % less time", 100 * (1 - po / pb), "{:.1f}")
    want("pyflate n", npb, "{:d}", times=2)
    want("mdp baseline (s)", mb, "{:.3f}", times=2)
    want("mdp optimized (s)", mo, "{:.3f}", times=2)
    want("mdp speedup", mb / mo, "{:.2f}", times=3)
    want("mdp % less time", 100 * (1 - mo / mb), "{:.1f}")
    want("mdp n", nmb, "{:d}", times=2)
    # the same two runs to one more decimal, and their spread, which slides 9
    # and 14 state as "1.141 +- 0.036 s and 487 +- 28 ms"
    want("pyflate optimized (ms, 1dp)", po * 1e3, "{:.1f}")
    want("pyflate baseline stdev (s)", stdev(f"{ROOT}/results/pyflate/pyflate_base.json"), "{:.3f}")
    want("pyflate optimized stdev (ms)", stdev(f"{ROOT}/results/pyflate/pyflate_opt.json") * 1e3, "{:.0f}")

    # ---- hardware counters ---------------------------------------------------
    b = perfstat(f"{ROOT}/results/pyflate/perfstat_base.txt")
    o = perfstat(f"{ROOT}/results/pyflate/perfstat_opt.txt")
    want("pyflate insn base (B)", b["instructions"] / 1e9, "{:.2f}")
    want("pyflate insn opt (B)", o["instructions"] / 1e9, "{:.2f}")
    want("pyflate cycles base (B)", b["cycles"] / 1e9, "{:.2f}")
    want("pyflate cycles opt (B)", o["cycles"] / 1e9, "{:.2f}")
    want("pyflate IPC base", b["instructions"] / b["cycles"], "{:.2f}", times=2)
    want("pyflate IPC opt", o["instructions"] / o["cycles"], "{:.2f}", times=2)
    want("pyflate insn removed (B)", (b["instructions"] - o["instructions"]) / 1e9, "{:.1f}")
    want("pyflate branch-miss % base", 100 * b["branch-misses"] / b["branches"], "{:.2f}")
    want("pyflate branch-miss % opt", 100 * o["branch-misses"] / o["branches"], "{:.2f}")
    b = perfstat(f"{ROOT}/results/mdp/perfstat_base.txt")
    o = perfstat(f"{ROOT}/results/mdp/perfstat_opt.txt")
    want("mdp insn base (B)", b["instructions"] / 1e9, "{:.1f}")
    want("mdp insn opt (B)", o["instructions"] / 1e9, "{:.1f}")
    want("mdp cycles base (B)", b["cycles"] / 1e9, "{:.2f}")
    want("mdp cycles opt (B)", o["cycles"] / 1e9, "{:.2f}")
    want("mdp IPC base", b["instructions"] / b["cycles"], "{:.2f}")
    want("mdp IPC opt", o["instructions"] / o["cycles"], "{:.2f}")
    want("mdp instructions down", b["instructions"] / o["instructions"], "{:.1f}")

    # ---- PMU diagnosis --------------------------------------------------------
    pmi = re.findall(r"PMI:\s+(\d+)", open(f"{ROOT}/results/pyflate/pmu_diagnosis.txt").read())
    check(f"PMI stays at 0 across a record: measured {pmi}",
          pmi and set(pmi) == {"0"} and "PMI" in txt)

    # ---- how much talk the deck actually holds --------------------------------
    # The guide tells the presenter how long the slides take to read, and that
    # figure was hand-typed and had drifted twice. Count it instead: the words
    # in the paragraphs and bullets of slides 1-22, since 23 is backup the guide
    # says not to narrate, and code blocks and tables are pointed at, not read.
    body = []
    for sec in re.split(r'(?=<section class="s[ "])', open(DECK, encoding="utf-8").read())[1:23]:
        for m in re.finditer(r"<(p|li)\b[^>]*>(.*?)</\1>", sec, re.S):
            body.append(m.group(2))
    spoken = " ".join(body)
    spoken = re.sub(r"<svg.*?</svg>", " ", spoken, flags=re.S)
    spoken = re.sub(r"<[^>]+>|&[a-z]+;", " ", spoken)
    nwords = len(re.findall(r"[A-Za-z][A-Za-z'\u2019-]*", spoken))
    guide = open(f"{ROOT}/docs/presentation_outline.md", encoding="utf-8").read()
    check(f"the guide's word count is the deck's ({nwords} narrated words "
          f"-> about {round(nwords, -2):,})",
          f"about {round(nwords, -2):,} words of prose" in re.sub(r"\s+", " ", guide))
    # and the read-aloud estimate that follows from it, at the guide's own pace
    _mins = {10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
             15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen"}
    _m = round(nwords / 100)
    check(f"the guide's read-aloud estimate follows from it "
          f"({nwords} words at the 100 wpm it assumes is ~{_m} min)",
          _m not in _mins or f"roughly {_mins[_m]} minutes read aloud" in re.sub(r"\s+", " ", guide))

    # ---- the correctness gate, recomputed from the input the benchmark ships --
    # Slide 5 promises 399,360 bytes and an md5. Both are properties of
    # benchmarks/pyflate/data/interpreter.tar.bz2, so decompress it and look,
    # rather than trusting a number someone copied across.
    raw = open(f"{ROOT}/benchmarks/pyflate/data/interpreter.tar.bz2", "rb").read()
    out = bz2.decompress(raw)
    want("what it decompresses to (bytes)", len(out), "{:,}", times=2)
    digest = hashlib.md5(out).hexdigest()
    check(f"the slides quote the real output md5 ({digest[:8]}...)", digest[:8] in txt)

    # ---- what the event probe found, which slide 3 quotes ---------------------
    probe = open(f"{ROOT}/results/pyflate/perf_events_probe.txt", encoding="utf-8").read()
    ms_ = re.search(r"cpu-clock: works \((\d+) samples\)", probe)
    check("the probe recorded a cpu-clock sample count", bool(ms_))
    if ms_:
        want("cpu-clock samples in the probe", int(ms_.group(1)), "{:,}")

    # ---- the table scan slide 7 describes ------------------------------------
    tbl = open(f"{ROOT}/results/pyflate/table_stats.txt", encoding="utf-8").read()
    want("largest table (entries)", int(re.search(r"largest table\s+(\d+) entries", tbl).group(1)), "{:d}")
    want("bzip2's table limit", int(re.search(r"bzip2 permits (\d+)", tbl).group(1)), "{:d}")

    # ---- accelerator ---------------------------------------------------------------
    # Read out of the simulation log rather than typed here: these three used to
    # be literals with this comment pointing at the file, so re-running the RTL
    # could not have moved them and the gate would have kept certifying the old
    # slides.
    sim = open(f"{ROOT}/results/rtl_sim_guest.log", encoding="utf-8").read()
    m = re.search(r"decoded (\d+) symbols in (\d+) cycles", sim)
    check("rtl_sim_guest.log states the symbol and cycle counts", bool(m))
    SYM, CYC = (int(m.group(1)), int(m.group(2))) if m else (0, 1)
    mb_ = re.search(r"total bits consumed:\s*(\d+)", sim)
    check("rtl_sim_guest.log states the bits consumed", bool(mb_))
    BITS = int(mb_.group(1)) if mb_ else 0
    want("symbols decoded", SYM, "{:,}", times=5)
    want("cycles", CYC, "{:,}", times=2)
    want("bits", BITS, "{:,}")
    want("symbols/clock", SYM / CYC, "{:.3f}")      # 1.000
    want("bits/symbol", BITS / SYM, "{:.2f}")
    syn = open(f"{ROOT}/docs/synthesis_yosys.txt").read()
    cfg = re.findall(r"^(\d+) cells: (\d+) flip-flops, (\d+) gates", syn, re.M)
    check(f"synthesis file lists both configurations ({len(cfg)})", len(cfg) >= 2)
    if len(cfg) >= 2:
        want("yosys cells", int(cfg[0][0]), "{:,}")
        want("flip-flops", int(cfg[0][1]), "{:,}")
        want("all-logic variant cells", int(cfg[1][0]), "{:,}")
    levels = int(re.search(r"length=(\d+)", syn).group(1))
    want("gate levels", levels, "{:d}", times=2)
    # docs/synthesis_yosys.txt: "symbols 6 x 258 x 9 = 13,932 bits, about 13.9
    # kbit (1.7 KB), is the SRAM" - take the bit count and do the two conversions
    # here, so the slide cannot keep a size the synthesis note no longer gives.
    sram_bits = int(re.search(r"symbols [\dx\s]+=\s*([\d,]+) bits", syn).group(1).replace(",", ""))
    want("symbol table (kbit)", sram_bits / 1000, "{:.1f}")
    want("symbol table (KB)", sram_bits / 8 / 1024, "{:.1f}")
    for old in ("2,768", "52,952", "19.4"):
        check(f"the superseded synthesis figure {old} is gone from the slides", old not in txt)
    decode_ms = CYC / 200e6 * 1e3
    want("decode at 200 MHz (ms)", decode_ms, "{:.2f}")

    # ---- the two profilers' share of find_next_symbol -------------------------
    _, cp_share = cprofile_shares(f"{ROOT}/results/pyflate/cprofile_opt.txt", "find_next_symbol")
    fold = [l.rsplit(" ", 1) for l in
            open(f"{ROOT}/results/pyflate/pyspy_opt_focus.folded", encoding="utf-8").read().splitlines() if l]
    tot = sum(int(n) for _, n in fold)
    py_share = 100 * sum(int(n) for st, n in fold if "find_next_symbol" in st) / tot
    want("cProfile share of find_next_symbol", cp_share, "{:.1f}", times=2)
    want("py-spy share of find_next_symbol", py_share, "{:.1f}", times=2)

    # ---- Amdahl (from the VM optimized time, as in report_pyflate.txt 5.6) ----
    # The slides accelerate 51.0%, which is not either profiler's number but a
    # round value between them - so gate exactly that, rather than trusting the
    # constant. If the profiles move, 51.0 has to move back between them.
    HUFF_SHARE = 0.510
    check(f"the accelerated share sits between the profilers "
          f"(cProfile {cp_share:.1f}%, deck {HUFF_SHARE*100:.1f}%, py-spy {py_share:.1f}%)",
          min(cp_share, py_share) <= HUFF_SHARE * 100 <= max(cp_share, py_share))
    want("accelerated share (%)", HUFF_SHARE * 100, "{:.1f}", times=2)
    opt_ms = po * 1e3
    part = opt_ms * HUFF_SHARE
    accel = decode_ms + 0.6
    new = opt_ms - part + accel
    want("Amdahl: accelerated part (ms)", part, "{:.0f}", times=2)
    want("Amdahl: result (ms)", new, "{:.0f}", times=3)
    want("Amdahl: vs optimized", opt_ms / new, "{:.1f}")
    want("Amdahl: vs shipped", pb * 1e3 / new, "{:.1f}")
    # what one symbol costs the CPU today: the accelerated share of the optimized
    # run, over the symbols, at the guest's 2.4 GHz. Slides 17 and 22 round it to
    # the nearest hundred to say a clock replaces about this many cycles.
    want("CPU cycles per symbol", round(po * HUFF_SHARE / SYM * 2.4e9, -2), "{:,.0f}", times=2)

    # ---- the ablation figures on the slides come from the artifact ---------------
    abl = os.path.join(ROOT, "results", "pyflate", "ablation.txt")
    if os.path.exists(abl):
        a = open(abl, encoding="utf-8").read()
        # the slide quotes ms per change, which is what the ablation measures
        # (leave-one-out deltas do not compose into ratios)
        for which in ("3.1", "3.3", "3.4"):
            m = re.search(which.replace(".", r"\.") + r"\s+worth\s+([\d.]+) ms", a)
            check(f"slides quote the measured {which} contribution ({m.group(1) if m else '?'} ms)",
                  m and m.group(1) in txt)

    # ---- every ratio column must equal the two cells beside it -------------------
    # The checks above only ask whether a number appears somewhere on the slides;
    # a comparison-table row must also be consistent with itself.
    raw_deck = open(DECK, encoding="utf-8").read()
    def cell(t):
        """A table cell as a number (ms converted to s), or None if it is not one."""
        m = re.match(r"^\s*([\d,.]+)\s*(s|ms|B|%)?\s*$", t)
        if not m:
            return None
        v = float(m.group(1).replace(",", ""))
        return v * 1e-3 if m.group(2) == "ms" else v
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
        check(f"table row '{label.strip()}': {a.strip()} / {b.strip()} = {want_r:.2f}"
              + ("" if ok else f", but the slide says {r.strip()}"), ok)
    check(f"ratio columns checked ({checked} rows)", checked >= 6)

    # ---- claims that come from elsewhere in the repo -----------------------------
    for label, needle in (("4,823 states", "4,823"), ("3,659 getCritDist calls", "3,659"),
                          ("mdp result quoted in full", "0.8987358988699915"), ("md5 prefix", "afa004a6"),
                          ("output bytes", "399,360")):
        check(label, needle.replace(",", "") in present or needle in txt)

    # ---- the baseline slide must carry the BASELINE cProfile figures ----------
    # Recomputed from the profile, not hardcoded: the slide showed the previous
    # run's shares through a re-measure because this gate spelled them out.
    rep = open(os.path.join(ROOT, "report_pyflate.txt"), encoding="utf-8").read()
    base_self, base_cum = cprofile_shares(f"{ROOT}/results/pyflate/cprofile_base.txt", "find_next_symbol")
    check(f"slide 6 quotes the baseline cProfile shares ({base_self:.1f}% self, {base_cum:.1f}% cumulative)",
          f"{base_self:.1f}% self and {base_cum:.1f}%" in txt)
    check("those figures are the report's section 2 numbers",
          f"{base_self:.1f}%" in rep and f"{base_cum:.1f}%" in rep)
    outline = open(os.path.join(ROOT, "docs", "presentation_outline.md"), encoding="utf-8").read()
    check("the speaker guide quotes the same two shares",
          f"{base_self:.1f}%" in outline and f"{base_cum:.1f}%" in outline)

    # ---- the shares on the "what remains" slide come from the folded stacks ----
    # 60% / 30% is the self-plus-helpers double count that report section 5.6 rules out.
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
                check(f"slide quotes the measured {label} ({val:.0f}%)", f"{val:.0f}%" in txt)
            check("the retracted 60/30 double count is gone from the slides",
                  "60%" not in txt and "~30%" not in txt)

    # ---- the embedded figures must be the shipped ones ---------------------------
    # Every base64 picture in the deck must be an .svg file in the tree (matched by
    # md5). results/reproducibility is the other run, so its flame graphs do not count.
    svg_md5 = set()
    for folder, subdirs, files in os.walk(ROOT):
        subdirs[:] = [d for d in subdirs if d not in (".git", "venv", "FlameGraph", "reproducibility")]
        for f in files:
            if f.endswith(".svg"):
                svg_md5.add(hashlib.md5(open(os.path.join(folder, f), "rb").read()).hexdigest())
    embedded = []
    for b in re.findall(r"data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)", raw_deck):
        try:
            embedded.append(base64.b64decode(b))
        except Exception:
            pass
    unknown = []
    for svg in embedded:
        h = hashlib.md5(svg).hexdigest()
        if h not in svg_md5:
            unknown.append(h[:8])
    check("every embedded figure is a file in the shipped tree"
          + (f" (unmatched: {unknown})" if unknown else ""), not unknown)

    # ---- the block diagram is a graded deliverable; gate its figures too -------
    dia_path = os.path.join(ROOT, "docs", "huffman_accel_block_diagram.svg")
    dia = open(dia_path, encoding="utf-8").read()
    for label, needle in (("diagram: symbols", f"{SYM:,}"), ("diagram: cycles", f"{CYC:,}"),
                          ("diagram: symbols/cycle", "1.00")):
        check(f"{label} ({needle})", needle in dia)

    # The deck embeds its own base64 copy of the diagram; it must be the file byte for byte.
    want_b64 = base64.b64encode(open(dia_path, "rb").read()).decode("ascii")
    check("the deck embeds docs/huffman_accel_block_diagram.svg byte-identically", want_b64 in raw_deck)
    stale = []
    for svg in embedded:
        for n in set(re.findall(r"\b148,\d{3}\b", svg.decode("utf-8", "replace"))):
            if n not in (f"{SYM:,}", f"{CYC:,}"):
                stale.append(n)
    check("no embedded slide image quotes a stale cycle count"
          + (f" (found {sorted(set(stale))})" if stale else ""), not stale)

    # ---- per-symbol CPU cost: accelerated ms / 148,271 symbols at 2.4 GHz ------
    cyc_per_sym = po * HUFF_SHARE / SYM * 2.4e9      # the VM runs at 2.4 GHz
    for label, path in (("deck", DECK),
                        ("docs/presentation_outline.md", os.path.join(ROOT, "docs", "presentation_outline.md")),
                        ("report_pyflate.txt", os.path.join(ROOT, "report_pyflate.txt"))):
        body = open(path, encoding="utf-8").read()
        rounded = f"{round(cyc_per_sym, -2):,.0f}"        # to the nearest hundred
        check(f"{label}: CPU cycles per symbol says {rounded}", rounded in body)
        check(f"{label}: the 1,585 ns figure is not restated as 1,600 cycles",
              "1,600 CPU cycles" not in body and "~1,600 cycles" not in body)

    # ---- README headline table must match too ---------------------------------
    rd = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    for label, val, fmt in (("README pyflate speedup", pb / po, "{:.2f}"),
                            ("README mdp speedup", mb / mo, "{:.2f}"),
                            ("README pyflate % less", 100 * (1 - po / pb), "{:.1f}"),
                            ("README mdp % less", 100 * (1 - mo / mb), "{:.1f}"),
                            ("README pyflate baseline s", pb, "{:.3f}"),
                            ("README mdp baseline s", mb, "{:.3f}")):
        s = fmt.format(val)
        if s in rd:
            oks.append(f"{label} ({s})")
        else:
            fails.append(f"{label}: README should say {s}")

    print(f"PASS {len(oks)}   FAIL {len(fails)}")
    for l in oks:
        print("  pass ", l)
    for l in fails:
        print("  FAIL ", l)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
