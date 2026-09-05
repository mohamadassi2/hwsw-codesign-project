#!/usr/bin/env python3
"""Check every derived number in the reports against the measured data.

Two kinds of check:

  measured   a figure quoted in a report must appear in results/ (the JSON the
             pyperf runs wrote, or the perf stat files)
  derived    a figure a report computes from other figures must actually
             recompute: speedups, percentages, the Amdahl estimate, the
             accelerator's cycle counts

Run it after filling the reports:  python3 scripts/check_report_numbers.py
Exit status is non-zero if anything fails, so it can gate a commit.
"""
import json, os, re, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []
OK = []


def check(name, cond, detail=""):
    # `detail` explains what went wrong, so it belongs only on a failing line;
    # appending it to a passing line makes the report read like a contradiction.
    if cond:
        OK.append(name)
    else:
        FAIL.append(f"{name}{('  ' + detail) if detail else ''}")


def _flat(t):
    """collapse whitespace so a line-wrapped sentence matches a one-line expectation"""
    return re.sub(r"\s+", " ", t)


def _sect(text, head, span=2600):
    """the body of one numbered subsection, so a check can be tied to it"""
    i = text.find(head)
    if i < 0:
        return ""
    j = re.search(r"\n\n\n|\n\d+\. [A-Z]", text[i + len(head):])
    return text[i:i + len(head) + (j.start() if j else span)]


def _count(text, needle):
    return len(re.findall(r"(?<![\d.,])" + re.escape(needle) + r"(?![\d.,])", text))


def mean_of(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        d = json.load(f)
    vals = []
    for b in d.get("benchmarks", []):
        for run in b.get("runs", []):
            vals.extend(run.get("values", []))
    return statistics.mean(vals) if vals else None


def report_text(b):
    p = os.path.join(ROOT, f"report_{b}.txt")
    return open(p).read() if os.path.exists(p) else ""


def nums(text):
    """Every number in the text, normalized (commas stripped)."""
    return set(m.group(0).replace(",", "") for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", text))


# ---------------------------------------------------------------- measured
for b in ("pyflate", "mdp"):
    d = os.path.join(ROOT, "results", b)
    base, opt = mean_of(f"{d}/{b}_base.json"), mean_of(f"{d}/{b}_opt.json")
    txt = report_text(b)
    if base is None or opt is None:
        check(f"{b}: results present", False, "no results/*.json yet - run script_%s.sh" % b)
        continue
    sp = base / opt
    pct = 100.0 * (1 - opt / base)
    check(f"{b}: speedup > 1", sp > 1, f"{sp:.2f}x")
    check(f"{b}: clears the 7% bar", pct >= 7, f"{pct:.1f}% faster")
    # the report must quote the speedup it measured, to 2 decimals or 1
    quoted = nums(txt)
    want = {f"{sp:.2f}", f"{sp:.1f}"}
    check(f"{b}: report quotes the measured speedup", bool(want & quoted),
          f"measured {sp:.2f}x; report has none of {sorted(want)}")
    wantpct = {f"{pct:.1f}", f"{pct:.0f}"}
    check(f"{b}: report quotes the measured percentage", bool(wantpct & quoted),
          f"measured {pct:.1f}%")
    check(f"{b}: no TODO-VM left", "TODO-VM" not in txt,
          f"{txt.count('TODO-VM')} placeholders remain")

# ---------------------------------------------------------------- prose that quotes the run
# The 4.1 blocks are generated; these sentences are hand-written and must agree with them.
_pf = report_text("pyflate"); _md = report_text("mdp")
_b = mean_of(os.path.join(ROOT, "results", "pyflate", "pyflate_base.json"))
_o = mean_of(os.path.join(ROOT, "results", "pyflate", "pyflate_opt.json"))
if _b and _o:
    check("pyflate conclusion quotes the measured speedup", f"gives {_b/_o:.2f}x in the" in _pf, f"{_b/_o:.2f}x")
    check("pyflate conclusion quotes the measured percentage", f"{100*(1-_o/_b):.1f}% less time" in _pf)
    ps_b = perfstat_counts = None
    import re as _re
    def _ps(p):
        r = {}
        for line in open(p):
            m = _re.match(r"\s*([\d,\.]+)\s+(?:msec\s+)?([a-z-]+)", line)
            if m: r[m.group(2)] = float(m.group(1).replace(",", ""))
        return r
    pb = _ps(os.path.join(ROOT, "results", "pyflate", "perfstat_base.txt"))
    if pb:
        check("section 2 quotes the measured baseline cycles", f"{pb['cycles']/1e9:.1f} billion cycles" in _pf, f"{pb['cycles']/1e9:.1f}")
        check("section 2 quotes the measured baseline instructions", f"{pb['instructions']/1e9:.1f} billion instructions" in _pf, f"{pb['instructions']/1e9:.1f}")
        check("section 2 quotes the measured baseline IPC", f"IPC {pb['instructions']/pb['cycles']:.2f}" in _pf, f"{pb['instructions']/pb['cycles']:.2f}")
# mdp section 2 quotes the same counters; gate them too (it once drifted a whole run)
_mps = _ps(os.path.join(ROOT, "results", "mdp", "perfstat_base.txt"))
if _mps:
    _mflat = re.sub(r"\s+", " ", _md)
    check("mdp section 2 quotes the measured instructions", f"{_mps['instructions']:,.0f}" in _mflat, f"{_mps['instructions']:,.0f}")
    check("mdp section 2 quotes the measured cycles", f"{_mps['cycles']:,.0f}" in _mflat, f"{_mps['cycles']:,.0f}")
    check("mdp section 2 quotes the measured branches", f"{_mps['branches']:,.0f}" in _mflat, f"{_mps['branches']:,.0f}")
    check("mdp section 2 IPC agrees with section 4.1",
          f"IPC of {_mps['instructions']/_mps['cycles']:.2f}" in _mflat,
          f"{_mps['instructions']/_mps['cycles']:.2f}")

_mb = mean_of(os.path.join(ROOT, "results", "mdp", "mdp_base.json"))
_mo = mean_of(os.path.join(ROOT, "results", "mdp", "mdp_opt.json"))
if _mb and _mo:
    # Flattened: these sentences are wrapped at 82 columns, so a literal match
    # breaks whenever a paragraph is re-wrapped rather than when a number is wrong.
    check("mdp conclusion quotes the measured speedup",
          f"gives {_mb/_mo:.2f}x in the course VM" in _flat(_md), f"{_mb/_mo:.2f}x")
    check("mdp conclusion quotes the measured percentage",
          f"{100*(1-_mo/_mb):.1f}% less time" in _flat(_md))

# ---------------------------------------------------------------- reproducibility section
_rb = mean_of(os.path.join(ROOT, "results", "reproducibility", "pyflate", "pyflate_base.json"))
_ro = mean_of(os.path.join(ROOT, "results", "reproducibility", "pyflate", "pyflate_opt.json"))
if _b and _o and _rb and _ro:
    # Both ratios must appear in the reproducibility subsection itself, rather
    # than anywhere in the report: the point is that the section compares the
    # two runs, and tying the check to one particular wording ("... rerun")
    # meant rephrasing the sentence broke the gate.
    def _section(text, head):
        i = text.find(head)
        if i < 0:
            return ""
        j = re.search(r"\n\n\n|\n\d\. ", text[i + len(head):])
        return text[i:i + len(head) + (j.start() if j else 2000)]
    _rep = _flat(_section(_pf, "4.3 Reproducibility"))
    check("reproducibility: pyflate shipped speedup quoted",
          f"{_b/_o:.3f}x" in _rep, f"{_b/_o:.3f}x, in section 4.3")
    check("reproducibility: pyflate rerun speedup quoted",
          f"{_rb/_ro:.3f}x" in _rep, f"{_rb/_ro:.3f}x, in section 4.3")
_rmb = mean_of(os.path.join(ROOT, "results", "reproducibility", "mdp", "mdp_base.json"))
_rmo = mean_of(os.path.join(ROOT, "results", "reproducibility", "mdp", "mdp_opt.json"))
if _mb and _mo and _rmb and _rmo:
    check("reproducibility: mdp both speedups quoted",
          f"{_rmb/_rmo:.3f}x against the shipped {_mb/_mo:.3f}x" in _flat(_md), f"{_rmb/_rmo:.3f} / {_mb/_mo:.3f}")

# every flame graph a report names must exist
for _rep, _txt in (("report_pyflate.txt", _pf), ("report_mdp.txt", _md)):
    for _svg in set(re.findall(r"(flame_[A-Za-z0-9_]+\.svg)", _txt)):
        _found = any(os.path.exists(os.path.join(ROOT, "results", _b, _svg)) for _b in ("pyflate", "mdp"))
        check(f"{_rep} cites {_svg} and it exists", _found, "no such file under results/")

# ---------------------------------------------------------------- derived: accelerator
SYMBOLS, CYCLES = 148271, 148272
txt = report_text("pyflate")
check("hw: symbols/cycle claim", abs(SYMBOLS / CYCLES - 1.0) < 0.001,
      f"{SYMBOLS/CYCLES:.4f}")
check("hw: report states both symbol and cycle counts",
      "148,271" in txt and "148,272" in txt)
for f, mhz in (("0.74", 200), ("0.37", 400)):
    got = CYCLES / (mhz * 1e6) * 1e3
    check(f"hw: {mhz} MHz decode time", abs(got - float(f)) < 0.01, f"{got:.3f} ms vs {f}")
BITS = 531571
check("hw: average bits per symbol", abs(BITS / SYMBOLS - 3.59) < 0.01,
      f"{BITS/SYMBOLS:.3f}")

# 62% may appear only in the sentence that records the earlier double count;
# anywhere else it would mean the corrected share had been lost again.
_flat_pf = re.sub(r"\s+", " ", _pf)
check("the corrected share is used, not the double-counted 62%",
      "51.1%" in _pf and _flat_pf.count("62%") == _flat_pf.count("earlier draft of this report did exactly that and quoted ~62%"),
      f"{_flat_pf.count('62%')} mention(s) of 62%, "
      f"{_flat_pf.count('earlier draft of this report did exactly that and quoted ~62%')} in the sentence that records the mistake")

# The same retracted share used to live in the supporting documents, where the
# guard above could not see it. Nothing outside that one sentence may say 62%.
for _rel in ("docs/hw_sw_interface.md", "docs/presentation_outline.md", "README.md", "docs/presentation.html"):
    _p = os.path.join(ROOT, _rel)
    if os.path.exists(_p):
        _t = re.sub(r"\s+", " ", open(_p, encoding="utf-8").read())
        check(f"{_rel} does not quote the retracted 62%", "62%" not in _t,
              "the corrected cumulative share is 49.7%")

# The conclusion must quote the ratios section 5.6 actually computes, not the
# ones an earlier draft reached from the double count.
_m56 = re.search(r"=\s*~(\d+) ms\s*->\s*~([\d.]+)x over the optimized software,\s*"
                 r"~([\d.]+)x over the shipped benchmark", _pf)
check("section 5.6 states the Amdahl result and both ratios", _m56 is not None)
if _m56:
    _ms, _vs_opt, _vs_base = _m56.group(1), _m56.group(2), _m56.group(3)
    _concl = _pf[_pf.rindex("6. Conclusion"):] if "6. Conclusion" in _pf else ""
    check("the conclusion quotes 5.6's ratio over the optimized code",
          f"{_vs_opt}x" in _concl, f"5.6 computes {_vs_opt}x")
    check("the conclusion quotes 5.6's ratio over the shipped benchmark",
          f"{_vs_base}x" in _concl, f"5.6 computes {_vs_base}x")
    _out = os.path.join(ROOT, "docs", "presentation_outline.md")
    if os.path.exists(_out):
        _o = open(_out, encoding="utf-8").read()
        check("the outline quotes the same two ratios",
              f"{_vs_opt}x" in _o and f"{_vs_base}x" in _o, f"expected {_vs_opt}x / {_vs_base}x")

# ---------------------------------------------------------------- derived: Amdahl
m = re.search(r"Take the optimized run measured in the VM, ([\d.]+) ms, of which that part is\s+"
              r"([\d.]+)% = ~([\d.]+) ms", txt)
if m:
    total, frac, part = float(m.group(1)), float(m.group(2)), float(m.group(3))
    check("amdahl: the stated fraction matches the stated milliseconds",
          abs(total * frac / 100 - part) < max(2.0, 0.03 * part),
          f"{total} ms x {frac}% = {total*frac/100:.1f} ms, report says {part}")
    m2 = re.search(r"([\d.]+) - ([\d.]+) \+ ([\d.]+)\s+=\s+~?([\d.]+) ms", txt)
    if m2:
        a, bb, c, res = (float(x) for x in m2.groups())
        check("amdahl: the subtraction is right", abs((a - bb + c) - res) < 1.5,
              f"{a} - {bb} + {c} = {a-bb+c:.1f}, report says {res}")
        m3 = re.search(r"~([\d.]+)x over the optimized software", txt)
        if m3:
            check("amdahl: speedup over optimized software",
                  abs(a / res - float(m3.group(1))) < 0.2,
                  f"{a}/{res} = {a/res:.2f}x, report says {m3.group(1)}x")
else:
    check("amdahl: paragraph is present and parseable", False,
          "could not find the estimate paragraph in report_pyflate.txt")

# ---------------------------------------------------------------- synthesis
syn = os.path.join(ROOT, "docs", "synthesis_yosys.txt")
if os.path.exists(syn):
    s = open(syn).read()
    txt_n = nums(txt)
    # Each configuration line is "<cells> cells: <ff> flip-flops, <gates> gates[, ...]".
    _cfg = re.findall(r"^(\d+) cells: (\d+) flip-flops, (\d+) gates", s, re.M)
    _d = re.search(r"length=(\d+)", s)
    check("docs/synthesis_yosys.txt reports both configurations", len(_cfg) >= 2,
          f"found {len(_cfg)}")
    if len(_cfg) >= 2:
        (_c, _f, _g), (_cf, _ff2, _gf) = _cfg[0], _cfg[1]
        for label, tok in (("cells", _c), ("flip-flops", _f), ("gates", _g),
                           ("all-logic cells", _cf),
                           ("depth", _d.group(1) if _d else None)):
            pretty = f"{int(tok):,}" if tok else None
            check(f"synthesis {label} ({tok}) quoted in the report",
                  tok is not None and (tok in txt_n or (pretty and pretty in txt)),
                  "from docs/synthesis_yosys.txt")
        # The superseded memory-macro figures must not come back. 2,768 may
        # appear only in the sentence that records why it was withdrawn, the
        # same rule the retracted 62% share is held to above.
        _flat_txt = re.sub(r"\s+", " ", txt)
        check("the superseded 2,768-cell figure appears only where it is retracted",
              _flat_txt.count("2,768") == _flat_txt.count("An earlier draft quoted 2,768 cells"),
              f"{_flat_txt.count('2,768')} mention(s)")
        for stale in ("52,952", "19.4 kbit"):
            check(f"the superseded synthesis figure {stale} is gone from the report",
                  stale not in txt, "it assumed a 20-read-port SRAM")

# ---------------------------------------------------------------- ablation
# Section 3.6 attributes the speedup to individual optimizations. Recompute the
# quoted figures from the artifact rather than trusting the prose.
_abl = os.path.join(ROOT, "results", "pyflate", "ablation.txt")
if os.path.exists(_abl):
    _a = open(_abl, encoding="utf-8").read()
    _rows = dict((m.group(1).strip(), float(m.group(2)))
                 for m in re.finditer(r"^  (.+?)\s{2,}([\d.]+)\s+[\d.]+\s+[\d.]+x$", _a, re.M))
    check("ablation.txt has the baseline and full-optimized rows", len(_rows) >= 3,
          f"parsed {len(_rows)} rows")
    for _lbl, _v in _rows.items():
        check(f"section 3.6 quotes the ablation figure for '{_lbl[:38]}' ({_v:,.1f} ms)",
              f"{_v:,.1f}" in txt, "from results/pyflate/ablation.txt")

_ts = os.path.join(ROOT, "results", "pyflate", "table_stats.txt")
if os.path.exists(_ts):
    _t = open(_ts, encoding="utf-8").read()
    _s36 = _sect(txt, "3.6 Which of those five actually earned the speedup")
    check("section 3.6 exists to carry the table-scan figures", bool(_s36))
    for _label, _rx in (("largest table", r"largest table\s+(\d+) entries"),
                        ("mean compares", r"compared, mean/symbol\s+([\d.]+)"),
                        ("snoopbits total", r"snoopbits\(\) calls, total\s+([\d,]+)")):
        _m = re.search(_rx, _t)
        # Checked inside 3.6, not anywhere in the file: "147" also appears in
        # section 3.1, so a presence-anywhere test passed even after 3.6 was
        # changed to say 258. A gate-mutation run in the VM found exactly that.
        check(f"section 3.6 quotes the measured {_label} ({_m.group(1) if _m else '?'})",
              _m is not None and _m.group(1) in _s36, "from results/pyflate/table_stats.txt")
    # And section 3.1's description of the same table must agree with it.
    _mlt = re.search(r"largest table\s+(\d+) entries", _t)
    if _mlt:
        _s31 = _sect(txt, "3.1 Canonical Huffman decode instead of a table scan")
        check(f"section 3.1 describes the same table size ({_mlt.group(1)})",
              _mlt.group(1) in _s31, "section 3.1 and results/pyflate/table_stats.txt disagree")

# ---------------------------------------------------------------- quoted times
# The generated 4.1 block is filled from results/, but the same figures are
# restated by hand in sections 5.6 and 6. Perturbing one of those restatements
# was not caught until a gate-mutation run in the VM went looking for it, so
# check each place the number is written rather than the file as a whole.
_pb = mean_of(os.path.join(ROOT, "results", "pyflate", "pyflate_base.json"))
_po = mean_of(os.path.join(ROOT, "results", "pyflate", "pyflate_opt.json"))
if _pb and _po:
    _exact = f"{_po * 1e3:.1f}"        # 477.2, as printed in the 4.1 table
    _round = f"{_po * 1e3:.0f}"        # 477,  as used in the prose
    check("section 4.1 prints the measured optimized time",
          _exact in _sect(txt, "4.1 Course VM"), f"expected {_exact} ms")
    check("section 5.6 uses the same optimized time",
          _round in _sect(txt, "5.6 Expected performance"), f"expected {_round} ms")
    _concl = txt[txt.rindex("6. Conclusion"):] if "6. Conclusion" in txt else ""
    check("the conclusion uses the same optimized time", _round in _concl,
          f"expected {_round} ms")
    # No stale value of the same shape may survive anywhere in the report.
    for _stale in ("473.0", "473"):
        if _stale != _exact and _stale != _round:
            check(f"no stale optimized time '{_stale}' remains", _count(txt, _stale) == 0,
                  f"the measured value is {_round} ms")
    # The overlap bound in 5.6 is arithmetic on the same two numbers.
    _mov = re.search(r"the bound becomes (\d+) - (\d+) = (\d+)\s*\n?\s*ms", txt)
    check("the overlap bound in 5.6 subtracts correctly", _mov is not None
          and int(_mov.group(1)) - int(_mov.group(2)) == int(_mov.group(3)),
          f"{_mov.groups() if _mov else 'sentence not found'}")
    if _mov:
        check("the overlap bound starts from the measured optimized time",
              _mov.group(1) == _round, f"expected {_round}")

# ---------------------------------------------------------------- measured times
# A local gate-mutation sweep found that the raw wall-clock means were not
# checked at all: only the ratios derived from them were. Perturbing "1.303" or
# "1.129" in a 4.1 table therefore passed. Check each measured mean where its
# section prints it, for both benchmarks.
for _b, _rep in (("pyflate", _pf), ("mdp", _md)):
    _bs = mean_of(os.path.join(ROOT, "results", _b, f"{_b}_base.json"))
    _os_ = mean_of(os.path.join(ROOT, "results", _b, f"{_b}_opt.json"))
    if not (_bs and _os_):
        continue
    _s41 = _sect(_rep, "4.1 Course VM")
    check(f"{_b}: section 4.1 prints the measured baseline ({_bs:.3f} s)",
          f"{_bs:.3f}" in _s41, f"from results/{_b}/{_b}_base.json")
    _optstr = f"{_os_ * 1e3:.1f}" if _os_ < 1 else f"{_os_:.3f}"
    check(f"{_b}: section 4.1 prints the measured optimized time ({_optstr})",
          _optstr in _s41, f"from results/{_b}/{_b}_opt.json")

# ---------------------------------------------------------------- simulation
# The symbol and cycle counts are quoted throughout section 5 and come from the
# testbench run recorded in results/rtl_sim_guest.log.
_simlog = os.path.join(ROOT, "results", "rtl_sim_guest.log")
if os.path.exists(_simlog):
    _sl = open(_simlog, encoding="utf-8").read()
    _msim = re.search(r"decoded (\d+) symbols in (\d+) cycles", _sl)
    if _msim:
        _sym, _cyc = int(_msim.group(1)), int(_msim.group(2))
        check(f"the report quotes the simulated symbol count ({_sym:,})", f"{_sym:,}" in txt,
              "from results/rtl_sim_guest.log")
        check(f"the report quotes the simulated cycle count ({_cyc:,})", f"{_cyc:,}" in txt,
              "from results/rtl_sim_guest.log")
        # Presence is not enough: these counts are written a dozen times, so one
        # of them can be wrong while the others keep a presence test happy. Every
        # number of this shape in the report must be one of the two real ones.
        _seen = set(re.findall(r"\b148,\d{3}\b", txt))
        _wrong = sorted(_seen - {f"{_sym:,}", f"{_cyc:,}"})
        check("no other 148,xxx figure appears in the report", not _wrong,
              f"found {_wrong}, but the only real values are {_sym:,} and {_cyc:,}")
        # per-symbol CPU cost: the accelerated share of the optimized run,
        # divided by the symbols, at the guest's 2.4 GHz.
        if _po:
            _cps = _po * 0.511 / _sym * 2.4e9
            _want_cps = f"{round(_cps, -2):,.0f}"
            check(f"the per-symbol CPU cost recomputes ({_want_cps} cycles)",
                  _want_cps in txt,
                  f"{_po * 1e3:.0f} ms x 51.1% / {_sym:,} at 2.4 GHz")
            # Same reasoning: check every place the report states a per-symbol
            # cycle cost, not merely that the right number occurs once.
            # Only the CPU-cost sentences, not every "cycles per symbol" in the
            # report: section 5.7 legitimately quotes 3.6 cycles/symbol for a
            # bit-serial alternative and 1 for this design.
            _states = set(re.findall(r"~([\d,]+) cycles of a 2\.4 GHz", txt)) | \
                      set(re.findall(r"~([\d,]+) CPU cycles per symbol", txt))
            _bad = sorted(v for v in _states if v != _want_cps)
            check("every per-symbol cycle figure in the report is the computed one",
                  not _bad, f"found {_bad}, expected {_want_cps}")

# ---------------------------------------------------------------- cited files
# A report that points at a file which is not in the tree is worse than one that
# does not cite anything: the reader goes looking. Check every repository path
# either report names.
_missing = []
for _name, _body in (("report_pyflate.txt", _pf), ("report_mdp.txt", _md)):
    for _m in re.finditer(r"\b((?:results|docs|scripts|hw|benchmarks)/[A-Za-z0-9_./-]+)", _body):
        _path = _m.group(1).rstrip(".,);")
        if "<" in _path or "*" in _path:
            continue
        if not os.path.exists(os.path.join(ROOT, _path)):
            _missing.append(f"{_name} -> {_path}")
check("every file the reports cite exists", not _missing, "; ".join(sorted(set(_missing))[:4]))

# ---------------------------------------------------------------- mutations
# The mutation score is a headline claim in both the report and the slides, and
# hw/tb/MUTATIONS.md is where it is recorded. Recount it from that table rather
# than trusting three documents to be edited together.
_mut = os.path.join(ROOT, "hw", "tb", "MUTATIONS.md")
if os.path.exists(_mut):
    _m = open(_mut, encoding="utf-8").read()
    _killed = len(re.findall(r"\|\s*KILLED", _m))
    _escaped = len(re.findall(r"\*\*escapes", _m))
    _total = _killed + _escaped
    check(f"MUTATIONS.md lists {_total} mutations, {_killed} killed", _total > 0 and _killed > 0)
    # The table and the script that produces it must describe the same suite.
    # Two mutations were added to mutate.sh without MUTATIONS.md following, and
    # nothing noticed because every check downstream reads only the table.
    _sh = os.path.join(ROOT, "hw", "tb", "mutate.sh")
    if os.path.exists(_sh):
        _runs = len(re.findall(r"^run ", open(_sh, encoding="utf-8").read(), re.M))
        check(f"MUTATIONS.md covers every mutation mutate.sh runs ({_runs})",
              _total == _runs, f"the script runs {_runs}, the table lists {_total}")
    for _rel in ("report_pyflate.txt", "docs/presentation.html"):
        _t = re.sub(r"\s+", " ", open(os.path.join(ROOT, _rel), encoding="utf-8").read())
        check(f"{_rel} quotes the mutation score {_killed} of {_total}",
              f"{_killed} of {_total}" in _t or f"{_killed} of the {_total}" in _t,
              f"MUTATIONS.md records {_killed}/{_total}")

# ---------------------------------------------------------------- report
print(f"PASS {len(OK)}   FAIL {len(FAIL)}\n")
for line in OK:
    print("  pass  " + line)
if FAIL:
    print()
    for line in FAIL:
        print("  FAIL  " + line)
sys.exit(1 if FAIL else 0)
