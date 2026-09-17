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
import bz2, glob, hashlib, json, os, re, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []
OK = []


def check(name, cond, detail=""):
    # detail says what went wrong, so it is printed only on a failing line
    if cond:
        OK.append(name)
    elif detail:
        FAIL.append(name + "  " + detail)
    else:
        FAIL.append(name)


def input_facts():
    """The benchmark input's own numbers. report_pyflate.txt quotes the compressed
    size, the decompressed size and the md5; all three are properties of the file
    the repository ships, so decompress it and check rather than trusting a copy."""
    raw = open(os.path.join(ROOT, "benchmarks", "pyflate", "data", "interpreter.tar.bz2"), "rb").read()
    out = bz2.decompress(raw)
    return len(raw), len(out), hashlib.md5(out).hexdigest()


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


def results(*parts):
    return os.path.join(ROOT, "results", *parts)


def mean_of(path):
    """mean of every value in a pyperf JSON file, None if the file is missing"""
    if not os.path.exists(path):
        return None
    with open(path) as f:
        d = json.load(f)
    vals = []
    for b in d.get("benchmarks", []):
        for run in b.get("runs", []):
            vals.extend(run.get("values", []))
    return statistics.mean(vals) if vals else None


def perf_counters(path):
    """{event: count} from a `perf stat` text file"""
    r = {}
    for line in open(path):
        m = re.match(r"\s*([\d,\.]+)\s+(?:msec\s+)?([a-z-]+)", line)
        if m:
            r[m.group(2)] = float(m.group(1).replace(",", ""))
    return r


def fingerprint(paths):
    """md5 of the per-file md5s; the stamp `make synth` and results/CODE_ID.txt carry"""
    h = hashlib.md5()
    for p in paths:
        h.update(hashlib.md5(open(p, "rb").read()).hexdigest().encode())
    return h.hexdigest()


def report_text(b):
    p = os.path.join(ROOT, f"report_{b}.txt")
    return open(p).read() if os.path.exists(p) else ""


def nums(text):
    """Every number in the text, normalized (commas stripped)."""
    return set(m.group(0).replace(",", "") for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", text))


# the reports and every measured mean, read once
_pf = report_text("pyflate")
_md = report_text("mdp")
_flat_pf = _flat(_pf)
_flat_md = _flat(_md)
_concl = _pf[_pf.rindex("6. Conclusion"):] if "6. Conclusion" in _pf else ""

# the testbench run section 5 quotes throughout, read once
_simlog = results("rtl_sim_guest.log")
_sl = open(_simlog, encoding="utf-8").read() if os.path.exists(_simlog) else ""
_msim = re.search(r"decoded (\d+) symbols in (\d+) cycles", _sl)
_mbits = re.search(r"total bits consumed:\s*(\d+)", _sl)
_sym = int(_msim.group(1)) if _msim else None
_cyc = int(_msim.group(2)) if _msim else None
_bits = int(_mbits.group(1)) if _mbits else None

_pf_base = mean_of(results("pyflate", "pyflate_base.json"))
_pf_opt = mean_of(results("pyflate", "pyflate_opt.json"))
_md_base = mean_of(results("mdp", "mdp_base.json"))
_md_opt = mean_of(results("mdp", "mdp_opt.json"))
# the two reruns section 4.3 compares the shipped run with
_pf_base2 = mean_of(results("reproducibility", "pyflate", "pyflate_base.json"))
_pf_opt2 = mean_of(results("reproducibility", "pyflate", "pyflate_opt.json"))
_md_base2 = mean_of(results("reproducibility", "mdp", "mdp_base.json"))
_md_opt2 = mean_of(results("reproducibility", "mdp", "mdp_opt.json"))
_pf_base3 = mean_of(results("reproducibility", "run3", "pyflate", "pyflate_base.json"))
_pf_opt3 = mean_of(results("reproducibility", "run3", "pyflate", "pyflate_opt.json"))
_md_base3 = mean_of(results("reproducibility", "run3", "mdp", "mdp_base.json"))
_md_opt3 = mean_of(results("reproducibility", "run3", "mdp", "mdp_opt.json"))

# ------------------------------------------------- the input's own numbers
# The three figures that define what "correct" means for pyflate were quoted
# and never recomputed. They belong to the file the repository ships, so open it.
_in_bytes, _out_bytes, _out_md5 = input_facts()
check(f"pyflate: the report's compressed size is the input's ({_in_bytes:,} bytes)",
      f"{_in_bytes:,}" in _pf)
check(f"pyflate: the report's decompressed size is the input's ({_out_bytes:,} bytes)",
      f"{_out_bytes:,}" in _pf)
check(f"pyflate: the report's md5 is the input's ({_out_md5[:8]}...)",
      _out_md5[:8] in _pf, f"expected {_out_md5}")

# ---------------------------------------------------------------- measured
for b, base, opt, rep in (("pyflate", _pf_base, _pf_opt, _pf), ("mdp", _md_base, _md_opt, _md)):
    if base is None or opt is None:
        check(f"{b}: results present", False, f"no results/*.json yet - run script_{b}.sh")
        continue
    sp = base / opt
    pct = 100.0 * (1 - opt / base)
    check(f"{b}: speedup > 1", sp > 1, f"{sp:.2f}x")
    check(f"{b}: clears the 7% bar", pct >= 7, f"{pct:.1f}% faster")
    # the report must quote the speedup it measured, to 2 decimals or 1
    quoted = nums(rep)
    want = {f"{sp:.2f}", f"{sp:.1f}"}
    check(f"{b}: report quotes the measured speedup", bool(want & quoted),
          f"measured {sp:.2f}x; report has none of {sorted(want)}")
    wantpct = {f"{pct:.1f}", f"{pct:.0f}"}
    check(f"{b}: report quotes the measured percentage", bool(wantpct & quoted),
          f"measured {pct:.1f}%")
    check(f"{b}: no TODO-VM left", "TODO-VM" not in rep,
          f"{rep.count('TODO-VM')} placeholders remain")

# ---------------------------------------------------------------- prose that quotes the run
# The 4.1 blocks are generated; these sentences are hand-written and must agree with them.
if _pf_base and _pf_opt:
    check("pyflate conclusion quotes the measured speedup", f"gives {_pf_base/_pf_opt:.2f}x in the" in _pf, f"{_pf_base/_pf_opt:.2f}x")
    check("pyflate conclusion quotes the measured percentage", f"{100*(1-_pf_opt/_pf_base):.1f}% less time" in _pf)
    pb = perf_counters(results("pyflate", "perfstat_base.txt"))
    if pb:
        check("section 2 quotes the measured baseline cycles", f"{pb['cycles']/1e9:.1f} billion cycles" in _pf, f"{pb['cycles']/1e9:.1f}")
        check("section 2 quotes the measured baseline instructions", f"{pb['instructions']/1e9:.1f} billion instructions" in _pf, f"{pb['instructions']/1e9:.1f}")
        check("section 2 quotes the measured baseline IPC", f"IPC {pb['instructions']/pb['cycles']:.2f}" in _pf, f"{pb['instructions']/pb['cycles']:.2f}")
# mdp section 2 quotes the same counters
_mps = perf_counters(results("mdp", "perfstat_base.txt"))
if _mps:
    check("mdp section 2 quotes the measured instructions", f"{_mps['instructions']:,.0f}" in _flat_md, f"{_mps['instructions']:,.0f}")
    check("mdp section 2 quotes the measured cycles", f"{_mps['cycles']:,.0f}" in _flat_md, f"{_mps['cycles']:,.0f}")
    check("mdp section 2 quotes the measured branches", f"{_mps['branches']:,.0f}" in _flat_md, f"{_mps['branches']:,.0f}")
    check("mdp section 2 IPC agrees with section 4.1",
          f"IPC of {_mps['instructions']/_mps['cycles']:.2f}" in _flat_md,
          f"{_mps['instructions']/_mps['cycles']:.2f}")

if _md_base and _md_opt:
    # matched on the flattened text: these sentences are line-wrapped in the report
    check("mdp conclusion quotes the measured speedup",
          f"gives {_md_base/_md_opt:.2f}x in the course VM" in _flat_md, f"{_md_base/_md_opt:.2f}x")
    check("mdp conclusion quotes the measured percentage",
          f"{100*(1-_md_opt/_md_base):.1f}% less time" in _flat_md)

# ---------------------------------------------------------------- reproducibility section
# Section 4.3 of each report compares the shipped run with two reruns. Every
# ratio, and the spread the section states, is recomputed and looked for
# inside that section only.
if _pf_base and _pf_opt and _pf_base2 and _pf_opt2:
    _rep = _flat(_sect(_pf, "4.3 Reproducibility", 3200))
    if _pf_base3 and _pf_opt3:
        check("reproducibility: the third run's pyflate ratio is quoted",
              f"{_pf_base3/_pf_opt3:.3f}x" in _rep, f"{_pf_base3/_pf_opt3:.3f}x")
        _ratios = [_pf_base/_pf_opt, _pf_base2/_pf_opt2, _pf_base3/_pf_opt3]
        _spread = (max(_ratios) - min(_ratios)) / min(_ratios) * 100
        check(f"reproducibility: the stated pyflate spread matches the three runs ({_spread:.1f}%)",
              f"{_spread:.1f}%" in _rep, f"expected {_spread:.1f}%")
    if _md_base3 and _md_opt3 and _md_base2 and _md_opt2 and _md_base and _md_opt:
        _ratios = [_md_base/_md_opt, _md_base2/_md_opt2, _md_base3/_md_opt3]
        _mspread = (max(_ratios) - min(_ratios)) / min(_ratios) * 100
        check(f"reproducibility: the stated mdp spread matches the three runs ({_mspread:.1f}%)",
              f"{_mspread:.1f}%" in _rep, f"expected {_mspread:.1f}%")
    check("reproducibility: pyflate shipped speedup quoted",
          f"{_pf_base/_pf_opt:.3f}x" in _rep, f"{_pf_base/_pf_opt:.3f}x, in section 4.3")
    check("reproducibility: pyflate rerun speedup quoted",
          f"{_pf_base2/_pf_opt2:.3f}x" in _rep, f"{_pf_base2/_pf_opt2:.3f}x, in section 4.3")
if _md_base and _md_opt and _md_base2 and _md_opt2:
    # section 4.3 lists the runs as a table; every ratio must appear in it
    _mrep = _flat(_sect(_md, "4.3 Reproducibility", 3200))
    check("reproducibility: mdp quotes the shipped ratio",
          f"{_md_base/_md_opt:.3f}x" in _mrep, f"{_md_base/_md_opt:.3f}x, in section 4.3")
    check("reproducibility: mdp quotes the second run's ratio",
          f"{_md_base2/_md_opt2:.3f}x" in _mrep, f"{_md_base2/_md_opt2:.3f}x, in section 4.3")
    if _md_base3 and _md_opt3:
        check("reproducibility: mdp quotes the third run's ratio",
              f"{_md_base3/_md_opt3:.3f}x" in _mrep, f"{_md_base3/_md_opt3:.3f}x, in section 4.3")

# every flame graph a report names must exist
for _name, _body in (("report_pyflate.txt", _pf), ("report_mdp.txt", _md)):
    for _svg in set(re.findall(r"(flame_[A-Za-z0-9_]+\.svg)", _body)):
        _found = any(os.path.exists(results(b, _svg)) for b in ("pyflate", "mdp"))
        check(f"{_name} cites {_svg} and it exists", _found, "no such file under results/")

# ---------------------------------------------------------------- derived: accelerator
# Everything here used to be script constants compared with script constants -
# the decode times divided 148272 by a frequency and compared the answer to the
# string "0.74" on the same line, so the report could have said any number at
# all and this gate would still have passed. Read the simulation log, derive the
# figures from it, and require the report to state what comes out.
check("hw: results/rtl_sim_guest.log records a run to read these from",
      _sym is not None and _bits is not None)
if _sym and _cyc and _bits:
    check("hw: symbols/cycle claim", abs(_sym / _cyc - 1.0) < 0.001, f"{_sym/_cyc:.4f}")
    for mhz in (200, 400):
        _ms = _cyc / (mhz * 1e6) * 1e3
        check(f"hw: {mhz} MHz decode time ({_ms:.2f} ms)", f"{_ms:.2f}" in _pf,
              f"{_cyc:,} cycles at {mhz} MHz is {_ms:.2f} ms; the report does not say so")
    _bps = _bits / _sym
    check(f"hw: average bits per symbol ({_bps:.2f})", f"{_bps:.2f}" in _pf,
          f"{_bits:,} bits over {_sym:,} symbols is {_bps:.2f}")

# 62% was a double-counted share; it may appear only in the sentence that retracts it
_retract = "earlier draft of this report did exactly that and quoted ~62%"
check("the corrected share is used, not the double-counted 62%",
      "51.0%" in _pf and _flat_pf.count("62%") == _flat_pf.count(_retract),
      f"{_flat_pf.count('62%')} mention(s) of 62%, "
      f"{_flat_pf.count(_retract)} in the sentence that records the mistake")

# the supporting documents may not quote it at all
for _rel in ("docs/hw_sw_interface.md", "docs/presentation_outline.md", "README.md", "docs/presentation.html"):
    _p = os.path.join(ROOT, _rel)
    if os.path.exists(_p):
        _t = _flat(open(_p, encoding="utf-8").read())
        check(f"{_rel} does not quote the retracted 62%", "62%" not in _t,
              "the corrected cumulative share is 49.7%")

# the conclusion and the slide outline must quote the ratios section 5.6 computes
_m56 = re.search(r"=\s*~(\d+) ms\s*->\s*~([\d.]+)x over the optimized software,\s*"
                 r"~([\d.]+)x over the shipped benchmark", _pf)
check("section 5.6 states the Amdahl result and both ratios", _m56 is not None)
if _m56:
    _vs_opt, _vs_base = _m56.group(2), _m56.group(3)
    check("the conclusion quotes 5.6's ratio over the optimized code",
          f"{_vs_opt}x" in _concl, f"5.6 computes {_vs_opt}x")
    check("the conclusion quotes 5.6's ratio over the shipped benchmark",
          f"{_vs_base}x" in _concl, f"5.6 computes {_vs_base}x")
    _out = os.path.join(ROOT, "docs", "presentation_outline.md")
    if os.path.exists(_out):
        # the outline may write the ratio as 2.0\u00d7 rather than 2.0x
        _outline = open(_out, encoding="utf-8").read().replace("\u00d7", "x")
        check("the outline quotes the same two ratios",
              f"{_vs_opt}x" in _outline and f"{_vs_base}x" in _outline, f"expected {_vs_opt}x / {_vs_base}x")

# ---------------------------------------------------------------- derived: Amdahl
m = re.search(r"Take the optimized run measured in the VM, ([\d.]+) ms, of which that part is\s+"
              r"([\d.]+)% = ~([\d.]+) ms", _pf)
if m:
    total, frac, part = float(m.group(1)), float(m.group(2)), float(m.group(3))
    check("amdahl: the stated fraction matches the stated milliseconds",
          abs(total * frac / 100 - part) < max(2.0, 0.03 * part),
          f"{total} ms x {frac}% = {total*frac/100:.1f} ms, report says {part}")
    m2 = re.search(r"([\d.]+) - ([\d.]+) \+ ([\d.]+)\s+=\s+~?([\d.]+) ms", _pf)
    if m2:
        a, bb, c, res = (float(x) for x in m2.groups())
        check("amdahl: the subtraction is right", abs((a - bb + c) - res) < 1.5,
              f"{a} - {bb} + {c} = {a-bb+c:.1f}, report says {res}")
        m3 = re.search(r"~([\d.]+)x over the optimized software", _pf)
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
    txt_n = nums(_pf)
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
                  tok is not None and (tok in txt_n or (pretty and pretty in _pf)),
                  "from docs/synthesis_yosys.txt")
        # 2,768 cells came from a memory-macro estimate; like the 62% share, it
        # may appear only in the sentence that withdraws it
        check("the superseded 2,768-cell figure appears only where it is retracted",
              _flat_pf.count("2,768") == _flat_pf.count("An earlier draft quoted 2,768 cells"),
              f"{_flat_pf.count('2,768')} mention(s)")
        for stale in ("52,952", "19.4 kbit"):
            # against the flattened text: "19.4 kbit" is two words, and a check
            # for its absence in the raw text passes the moment the report wraps
            # between them - a retracted figure would be back and unreported.
            check(f"the superseded synthesis figure {stale} is gone from the report",
                  stale not in _flat_pf, "it assumed a 20-read-port SRAM")

# ---------------------------------------------------------------- ablation
# section 3.6 quotes the per-optimization times from results/pyflate/ablation.txt
_abl = results("pyflate", "ablation.txt")
if os.path.exists(_abl):
    _a = open(_abl, encoding="utf-8").read()
    _rows = {m.group(1).strip(): float(m.group(2))
             for m in re.finditer(r"^  (.+?)\s{2,}([\d.]+)\s+[\d.]+\s+[\d.]+x$", _a, re.M)}
    check("ablation.txt has the baseline and full-optimized rows", len(_rows) >= 3,
          f"parsed {len(_rows)} rows")
    for _lbl, _v in _rows.items():
        check(f"section 3.6 quotes the ablation figure for '{_lbl[:38]}' ({_v:,.1f} ms)",
              f"{_v:,.1f}" in _pf, "from results/pyflate/ablation.txt")

_ts = results("pyflate", "table_stats.txt")
if os.path.exists(_ts):
    _t = open(_ts, encoding="utf-8").read()
    _s36 = _sect(_pf, "3.6 Which of those five actually earned the speedup")
    check("section 3.6 exists to carry the table-scan figures", bool(_s36))
    for _label, _rx in (("largest table", r"largest table\s+(\d+) entries"),
                        ("mean compares", r"compared, mean/symbol\s+([\d.]+)"),
                        ("snoopbits total", r"snoopbits\(\) calls, total\s+([\d,]+)")):
        _m = re.search(_rx, _t)
        # looked for inside 3.6 only: "147" also appears in section 3.1
        check(f"section 3.6 quotes the measured {_label} ({_m.group(1) if _m else '?'})",
              _m is not None and _m.group(1) in _s36, "from results/pyflate/table_stats.txt")
    # section 3.1 describes the same table and must agree
    _mlt = re.search(r"largest table\s+(\d+) entries", _t)
    if _mlt:
        _s31 = _sect(_pf, "3.1 Canonical Huffman decode instead of a table scan")
        check(f"section 3.1 describes the same table size ({_mlt.group(1)})",
              _mlt.group(1) in _s31, "section 3.1 and results/pyflate/table_stats.txt disagree")

# ---------------------------------------------------------------- quoted times
# the optimized time is printed in the 4.1 table and restated by hand in 5.6
# and 6, so each place is checked, not the file as a whole
if _pf_base and _pf_opt:
    _exact = f"{_pf_opt * 1e3:.1f}"        # one decimal, as printed in the 4.1 table
    _round = f"{_pf_opt * 1e3:.0f}"        # rounded, as used in the prose
    check("section 4.1 prints the measured optimized time",
          _exact in _sect(_pf, "4.1 Course VM"), f"expected {_exact} ms")
    check("section 5.6 uses the same optimized time",
          _round in _sect(_pf, "5.6 Expected performance"), f"expected {_round} ms")
    check("the conclusion uses the same optimized time", _round in _concl,
          f"expected {_round} ms")
    # no stale optimized time anywhere else; section 4.3 lists the other runs'
    # times on purpose, so it is skipped
    _outside_43 = _pf.replace(_sect(_pf, "4.3 Reproducibility", 3200), "")
    for _stale in ("473.0", "473"):
        if _stale != _exact and _stale != _round:
            check(f"no stale optimized time '{_stale}' outside section 4.3",
                  _count(_outside_43, _stale) == 0,
                  f"the measured value is {_round} ms")
    # the overlap bound in 5.6 is arithmetic on the same number
    _mov = re.search(r"the bound becomes (\d+) - (\d+) = (\d+)\s*\n?\s*ms", _pf)
    check("the overlap bound in 5.6 subtracts correctly", _mov is not None
          and int(_mov.group(1)) - int(_mov.group(2)) == int(_mov.group(3)),
          f"{_mov.groups() if _mov else 'sentence not found'}")
    if _mov:
        check("the overlap bound starts from the measured optimized time",
              _mov.group(1) == _round, f"expected {_round}")

# ---------------------------------------------------------------- measured times
# the raw means in each 4.1 table, not only the ratios derived from them
for b, rep, base, opt in (("pyflate", _pf, _pf_base, _pf_opt), ("mdp", _md, _md_base, _md_opt)):
    if not (base and opt):
        continue
    _s41 = _sect(rep, "4.1 Course VM")
    check(f"{b}: section 4.1 prints the measured baseline ({base:.3f} s)",
          f"{base:.3f}" in _s41, f"from results/{b}/{b}_base.json")
    _optstr = f"{opt * 1e3:.1f}" if opt < 1 else f"{opt:.3f}"
    check(f"{b}: section 4.1 prints the measured optimized time ({_optstr})",
          _optstr in _s41, f"from results/{b}/{b}_opt.json")

# ---------------------------------------------------------------- simulation
# the symbol and cycle counts quoted throughout section 5 come from the
# testbench run recorded in results/rtl_sim_guest.log
if _sym and _cyc:
    check(f"the report quotes the simulated symbol count ({_sym:,})", f"{_sym:,}" in _pf,
          "from results/rtl_sim_guest.log")
    check(f"the report quotes the simulated cycle count ({_cyc:,})", f"{_cyc:,}" in _pf,
          "from results/rtl_sim_guest.log")
    # the counts are written a dozen times; every 148,xxx in the report must be one of the two
    _seen = set(re.findall(r"\b148,\d{3}\b", _pf))
    _wrong = sorted(_seen - {f"{_sym:,}", f"{_cyc:,}"})
    check("no other 148,xxx figure appears in the report", not _wrong,
          f"found {_wrong}, but the only real values are {_sym:,} and {_cyc:,}")
    # per-symbol CPU cost: the accelerated 51.0% of the optimized run, divided
    # by the symbols, at the guest's 2.4 GHz
    if _pf_opt:
        _cps = _pf_opt * 0.510 / _sym * 2.4e9
        _want_cps = f"{round(_cps, -2):,.0f}"
        check(f"the per-symbol CPU cost recomputes ({_want_cps} cycles)",
              _want_cps in _pf,
              f"{_pf_opt * 1e3:.0f} ms x 51.0% / {_sym:,} at 2.4 GHz")
        # every CPU-cost sentence must state it; only those sentences, because
        # 5.7 also quotes 3.6 and 1 cycles/symbol for the two decoder designs
        _states = (set(re.findall(r"~([\d,]+) cycles of a 2\.4 GHz", _pf))
                   | set(re.findall(r"~([\d,]+) CPU cycles per symbol", _pf)))
        _bad = sorted(v for v in _states if v != _want_cps)
        check("every per-symbol cycle figure in the report is the computed one",
              not _bad, f"found {_bad}, expected {_want_cps}")
        # 5.2 motivates the accelerator with the same cost, in instructions. It
        # used to say "hundreds", which the cycle figure above contradicts by a
        # factor of forty - and it is the one sentence an examiner would price.
        _o = perf_counters(results("pyflate", "perfstat_opt.txt"))
        if _o.get("cycles"):
            _ipc = _o["instructions"] / _o["cycles"]
            _ins = _cps * _ipc
            check(f"5.2's instruction cost agrees with 5.6's cycle cost "
                  f"({_want_cps} cycles x IPC {_ipc:.2f} = {_ins:,.0f})",
                  2000 <= _ins <= 20000 and "ten thousand instructions" in _flat_pf,
                  f"{_ins:,.0f} instructions per symbol; 5.2 has to say so")
        # ...and 5.2 must not claim the interface is free of run-time traffic,
        # which docs/hw_sw_interface.md and 5.6 both contradict.
        _sel = -(-_sym // 50)          # one selector write per 50 symbols
        check(f"5.2 states the selector traffic it used to deny ({_sel:,} writes)",
              "nothing shared with the CPU" not in _flat_pf and f"{_sel:,}" in _pf,
              f"{_sym:,} symbols is {_sel:,} selector writes")

# ---- mdp: the sweep's share, which was an orphan figure ---------------------
# "sum/max come to 52.7%" appeared once in the repository and reconstructed from
# no denominator in any profile. Recompute the three numbers the sentence needs.
_mcp = results("mdp", "cprofile_base.txt")
if os.path.exists(_mcp):
    _r = [(float(m.group(1)), float(m.group(2)), m.group(3).strip())
          for m in re.finditer(r"^\s+\d+(?:/\d+)?\s+([\d.]+)\s+[\d.]+\s+([\d.]+)\s+[\d.]+\s+(.+)$",
                               open(_mcp, encoding="utf-8").read(), re.M)]
    _den = next((c for _, c, l in _r if "(bench_mdp)" in l), 0)
    if _den:
        # The artifact prints the profile twice, sorted two ways, so every
        # function appears in it twice: take the first row for each name or the
        # shares come out doubled.
        def _first(sub):
            return next((c for _, c, l in _r if sub in l), 0.0)
        _ev = next((o for o, _, l in _r if "(evaluate)" in l), 0.0)
        _sm = _first("builtins.sum") + _first("builtins.max")
        for _label, _v in (("evaluate's own body", 100 * _ev / _den),
                           ("sum and max together", 100 * _sm / _den),
                           ("the sweep in total", 100 * (_ev + _sm) / _den)):
            check(f"mdp: {_label} recomputes ({_v:.1f}%)", f"{_v:.1f}%" in _flat_md,
                  f"from {_mcp.split('/')[-1]}")
        # a reordering left this pointing the wrong way: the MMIO paragraph is above
        check("5.6's pointer to the MMIO paragraph points the right way",
              "the paragraph below prices what it costs the host" not in _flat_pf,
              "the paragraph that prices it comes earlier, not later")
        # The conclusion used to call all 5,441 flip-flops "table registers",
        # which 5.7 spends a paragraph saying they are not.
        check("the conclusion does not attribute every flip-flop to the tables",
              "flip-flops of table registers" not in _flat_pf,
              "5.7 says the bit buffer, counters and status flags are in that count too")
        # run3 keeps timings only; calling it a full run of the submission was
        # wrong twice over - it predates the 15 September revision as well.
        _r3 = glob.glob(os.path.join(ROOT, "results", "reproducibility", "run3", "*", "*"))
        check(f"4.3 does not call run3 a full end-to-end run ({len(_r3)} files in it)",
              "full end-to-end run of the submission" not in _flat_pf,
              "it holds the pyperf JSONs, perf stat and contention, not the profiles")
        # 5.6 prices that traffic at ~5 ms and must then re-check BOTH headline
        # ratios against it, not only the one that survives it. It gave the
        # vs-optimized ratio alone, leaving ~4.8x standing where ~4.7x is right.
        if _pf_base and _pf_opt:
            _mmio_ms = 245.0
            for _lbl, _num in (("optimized", _pf_opt * 1e3), ("shipped", _pf_base * 1e3)):
                _r = _num / _mmio_ms
                check(f"5.6 re-prices the {_lbl} ratio under its MMIO assumption (~{_r:.1f}x)",
                      f"~{_r:.1f}x" in _flat_pf,
                      f"{_num:.0f} ms / {_mmio_ms:.0f} ms is {_r:.2f}x")

# ---------------------------------------------------------------- cited files
# every repository path either report names must exist
_missing = []
for _name, _body in (("report_pyflate.txt", _pf), ("report_mdp.txt", _md)):
    for _m in re.finditer(r"\b((?:results|docs|scripts|hw|benchmarks)/[A-Za-z0-9_./-]+)", _body):
        _path = _m.group(1).rstrip(".,);")
        if "<" in _path or "*" in _path:
            continue
        if not os.path.exists(os.path.join(ROOT, _path)):
            _missing.append(f"{_name} -> {_path}")
check("every file the reports cite exists", not _missing, "; ".join(sorted(set(_missing))[:4]))

# ---------------------------------------------------------------- synth is current
# docs/synthesis_yosys.txt stamps the md5 of the hw/rtl/*.sv it was generated
# from; its figures are only valid while that matches the RTL in the tree
if os.path.exists(syn):
    _stamp = re.search(r"RTL fingerprint: ([0-9a-f]{32})", s)
    check("docs/synthesis_yosys.txt carries an RTL fingerprint", _stamp is not None,
          "regenerate it with `make synth` in hw/")
    if _stamp:
        _rtl = sorted(glob.glob(os.path.join(ROOT, "hw", "rtl", "*.sv")))
        check("the synthesis figures describe the RTL in the tree",
              _stamp.group(1) == fingerprint(_rtl),
              "the file was generated from different RTL; run `make synth` in hw/")

# ---------------------------------------------------------------- headline ratios
# the headline speedup is written three times (4.1 table, compare_to table,
# conclusion). Every d.ddx ratio must be it, except in the ablation section and
# 4.3, which exist to compare variants and runs.
for b, rep, base, opt in (("pyflate", _pf, _pf_base, _pf_opt), ("mdp", _md, _md_base, _md_opt)):
    if not (base and opt):
        continue
    _want = f"{base / opt:.2f}x"
    _body = rep.replace(_sect(rep, "4.3 Reproducibility", 3200), "")
    for _abl in ("3.6 Which of those five actually earned the speedup",
                 "3.3 Which of the two earned the speedup"):
        _body = _body.replace(_sect(_body, _abl, 3000), "")
    _found = re.findall(r"(?<![\d.])(\d\.\d\d)x(?![\d.])", _body)
    _bad = sorted({v + "x" for v in _found} - {_want})
    check(f"report_{b}.txt: every headline ratio outside 4.3 is the measured {_want}",
          not _bad, f"also found {_bad}")

# ---------------------------------------------------------------- cProfile tables
# the per-function shares in both reports' cProfile tables, recomputed from
# results/<b>/cprofile_*.txt
def _cprof(path, want):
    """(self%, cum%, calls) for one row, as shares of the benchmark function"""
    if not os.path.exists(path):
        return None
    txt = open(path, encoding="utf-8").read()
    rows, den = [], None
    for m in re.finditer(r"^\s+(\d+(?:/\d+)?)\s+([\d.]+)\s+[\d.]+\s+([\d.]+)\s+[\d.]+\s+(.+)$", txt, re.M):
        rows.append((m.group(1), float(m.group(2)), float(m.group(3)), m.group(4).strip()))
    for _, _, cum, lbl in rows:
        if "(bench_mdp)" in lbl or "(bench_pyflake)" in lbl:
            den = cum
            break
    if not den:
        return None
    for calls, tot, cum, lbl in rows:
        if lbl.endswith("(" + want + ")"):
            return (tot / den * 100, cum / den * 100, calls)
    return None

for b, rep, _fns in (
        ("pyflate", _pf, ["find_next_symbol", "decode_huffman_block"]),
        ("mdp", _md, ["evaluate", "getSuccessors", "getCritDist"])):
    for _tag in ("base", "opt"):
        for _fn in _fns:
            _r = _cprof(results(b, f"cprofile_{_tag}.txt"), _fn)
            if not _r:
                continue
            _self, _cum, _calls = _r
            # The row itself, not "the number appears somewhere in the report":
            # a stale share used to pass whenever the right value sat in the
            # other table. Find the line whose label names the function and
            # read the two percentages off it.
            _before, _sep, _after = rep.partition("(cProfile, optimized)")
            _region = _after if _tag == "opt" else _before
            _row = re.search(rf"^\s+\S*\b{re.escape(_fn)}\b[^%\n]*?\s([\d.]+)%\s+([\d.]+)%",
                             _region, re.M)
            check(f"report_{b}.txt: the {_tag} cProfile table has a {_fn} row", _row is not None,
                  f"expected a row naming {_fn} with two percentages")
            if _row:
                check(f"report_{b}.txt: the {_tag} cProfile table's {_fn} self share ({_self:.1f}%)",
                      _row.group(1) == f"{_self:.1f}", f"the row says {_row.group(1)}%")
                check(f"report_{b}.txt: the {_tag} cProfile table's {_fn} cumulative share ({_cum:.1f}%)",
                      _row.group(2) == f"{_cum:.1f}", f"the row says {_row.group(2)}%")

# ---------------------------------------------------------------- state count
# section 1 of report_mdp.txt gives the number of nodes topoSort visits: the
# getSuccessorsList call count in the baseline profile, one per visited node
_r = _cprof(results("mdp", "cprofile_base.txt"), "getSuccessorsList")
if _r:
    _nodes = int(_r[2].split("/")[0])
    check(f"report_mdp.txt: section 1 gives the measured node count ({_nodes:,})",
          f"{_nodes:,}" in _sect(_md, "Data structures and algorithm."),
          "from results/mdp/cprofile_base.txt")

# ---------------------------------------------------------------- perf probe
# section 2 quotes the sample counts out of results/<b>/perf_events_probe.txt
for b, rep in (("pyflate", _pf), ("mdp", _md)):
    _pp = results(b, "perf_events_probe.txt")
    if not os.path.exists(_pp):
        continue
    for _ev, _n in re.findall(r"(cpu-clock|task-clock): works \((\d+) samples\)", open(_pp, encoding="utf-8").read()):
        _pretty = f"{int(_n):,}"
        # only required where the report actually discusses that event
        check(f"report_{b}.txt: the {_ev} sample count it quotes ({_pretty})",
              _pretty in rep or _n in rep or _ev not in rep,
              f"from results/{b}/perf_events_probe.txt")

# ---------------------------------------------------------------- evidence age
# results/CODE_ID.txt stamps the md5 of the benchmark code and scripts that
# produced results/; it must match what is in the tree now
_code_id = results("CODE_ID.txt")
_measured_files = [os.path.join(ROOT, f) for f in (
    "benchmarks/pyflate/run_benchmark.py", "benchmarks/pyflate/run_benchmark_opt.py",
    "benchmarks/mdp/run_benchmark.py", "benchmarks/mdp/run_benchmark_opt.py",
    "script_pyflate.sh", "script_mdp.sh")]
if all(os.path.exists(f) for f in _measured_files):
    if os.path.exists(_code_id):
        _stamp = re.search(r"([0-9a-f]{32})", open(_code_id, encoding="utf-8").read())
        check("results/ was measured from the benchmark code now in the tree",
              _stamp is not None and _stamp.group(1) == fingerprint(_measured_files),
              "the benchmarks or their scripts changed after the measurements; re-run them in the VM "
              "and refresh results/CODE_ID.txt")
    else:
        check("results/CODE_ID.txt records the code the measurements describe", False,
              "missing; write it when results/ is captured")

# ---------------------------------------------------------------- mdp ablation
# section 3.3 quotes the per-change times from results/mdp/ablation.txt
_mabl = results("mdp", "ablation.txt")
if os.path.exists(_mabl):
    _a = open(_mabl, encoding="utf-8").read()
    _sec33 = _flat(_sect(_md, "3.3 Which of the two earned the speedup", 3000)).replace(",", "")
    for _m in re.finditer(r"^\s+(3\.\d)\s+worth\s+([\d.]+) ms", _a, re.M):
        _which, _ms = _m.group(1), _m.group(2)
        check(f"report_mdp.txt 3.3 quotes the measured {_which} contribution ({_ms} ms)",
              _ms in _sec33, "from results/mdp/ablation.txt")
    _msp = re.search(r"spread across variants: ([\d.]+) ms", _a)
    if _msp:
        check(f"report_mdp.txt 3.3 quotes the measured run-to-run spread ({_msp.group(1)} ms)",
              _msp.group(1) in _sec33, "from results/mdp/ablation.txt")
    for _m in re.finditer(r"^  (\S.*?)\s{2,}([\d,]+\.\d)\s+[\d,]+\.\d\s+([\d.]+)x$", _a, re.M):
        _row = _m.group(2).replace(",", "")
        check(f"report_mdp.txt 3.3 quotes the {_m.group(1).strip()[:34]} row ({_row} ms)",
              _row in _sec33, "from results/mdp/ablation.txt")

# ---------------------------------------------------------------- accelerated share
# The share of the optimized run the accelerator replaces is written in three
# places: this report, scripts/fill_reports.py (which regenerates the Amdahl
# estimate) and scripts/check_deck_numbers.py. They drifted once - fill_reports
# kept the pre-re-measure 49.7 and silently rewrote the estimate from it - so
# require all three to agree.
_share = re.search(r"takes ([\d.]+)% as the accelerated share", _flat_pf)
if _share:
    _fr = re.search(r"^\s*frac = ([\d.]+)", open(os.path.join(ROOT, "scripts", "fill_reports.py"),
                                                 encoding="utf-8").read(), re.M)
    _hs = re.search(r"HUFF_SHARE = ([\d.]+)", open(os.path.join(ROOT, "scripts", "check_deck_numbers.py"),
                                                   encoding="utf-8").read())
    check(f"scripts/fill_reports.py uses the accelerated share the report states ({_share.group(1)}%)",
          _fr is not None and float(_fr.group(1)) == float(_share.group(1)),
          f"fill_reports.py says {_fr.group(1) if _fr else 'nothing'}")
    check(f"scripts/check_deck_numbers.py uses the same share",
          _hs is not None and float(_hs.group(1)) * 100 == float(_share.group(1)),
          f"check_deck_numbers.py says {float(_hs.group(1))*100 if _hs else 'nothing'}")

# ---------------------------------------------------------------- mutations
# the mutation score is quoted in the report and the slides; recount it from
# hw/tb/MUTATIONS.md, which in turn must list every mutation mutate.sh runs
_mut = os.path.join(ROOT, "hw", "tb", "MUTATIONS.md")
if os.path.exists(_mut):
    _m = open(_mut, encoding="utf-8").read()
    _killed = len(re.findall(r"\|\s*KILLED", _m))
    _escaped = len(re.findall(r"\*\*escapes", _m))
    _total = _killed + _escaped
    check(f"MUTATIONS.md lists {_total} mutations, {_killed} killed", _total > 0 and _killed > 0)
    _sh = os.path.join(ROOT, "hw", "tb", "mutate.sh")
    if os.path.exists(_sh):
        _runs = len(re.findall(r"^run ", open(_sh, encoding="utf-8").read(), re.M))
        check(f"MUTATIONS.md covers every mutation mutate.sh runs ({_runs})",
              _total == _runs, f"the script runs {_runs}, the table lists {_total}")
    for _rel in ("report_pyflate.txt", "docs/presentation.html"):
        _t = _flat(open(os.path.join(ROOT, _rel), encoding="utf-8").read())
        check(f"{_rel} quotes the mutation score {_killed} of {_total}",
              f"{_killed} of {_total}" in _t or f"{_killed} of the {_total}" in _t,
              f"MUTATIONS.md records {_killed}/{_total}")
        # and no OTHER score: one stale "18 of 20" used to pass unnoticed while
        # the right phrase sat elsewhere in the same document.
        _said = set(re.findall(rf"(?<![\d.])(\d+) of (?:the )?{_total}\b", _t))
        check(f"{_rel}: every mutation score it states is {_killed} of {_total}",
              _said <= {str(_killed)}, f"also found {sorted(_said - {str(_killed)})}")

    # the score describes one particular RTL: MUTATIONS.md stamps it, as
    # docs/synthesis_yosys.txt does for the synthesis figures
    _mfp = re.search(r"RTL fingerprint: ([0-9a-f]{32})", _m)
    check("hw/tb/MUTATIONS.md carries an RTL fingerprint", _mfp is not None,
          "re-run tb/mutate.sh in the VM and record the fingerprint it prints")
    # the sweep log is the evidence behind the table: recount it, so neither the
    # table nor the log can drift from the other
    _mlog = results("mutation_sweep_guest.log")
    if os.path.exists(_mlog):
        _lt = open(_mlog, encoding="utf-8").read()
        _lk = len(re.findall(r"^\[.+?\]\s+KILLED", _lt, re.M))
        _le = len(re.findall(r"^\[.+?\]\s+ESCAPED", _lt, re.M))
        check(f"results/mutation_sweep_guest.log records {_killed} killed of {_total}",
              (_lk, _lk + _le) == (_killed, _total),
              f"the log shows {_lk} killed of {_lk + _le}")
        _lfp = re.search(r"RTL fingerprint: ([0-9a-f]{32})", _lt)
        check("the sweep log names the RTL MUTATIONS.md claims",
              _lfp is not None and _mfp is not None and _lfp.group(1) == _mfp.group(1),
              "the log and the table describe different RTL")
    if _mfp:
        check("the mutation score describes the RTL in the tree",
              _mfp.group(1) == fingerprint(sorted(glob.glob(os.path.join(ROOT, "hw", "rtl", "*.sv")))),
              "hw/rtl/ changed after the sweep; re-run SUITE=sim_all tb/mutate.sh in the VM")

# ---------------------------------------------------------------- report
print(f"PASS {len(OK)}   FAIL {len(FAIL)}\n")
for line in OK:
    print("  pass  " + line)
if FAIL:
    print()
    for line in FAIL:
        print("  FAIL  " + line)
sys.exit(1 if FAIL else 0)
