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
    check("mdp conclusion quotes the measured speedup", f"gives {_mb/_mo:.2f}x in the course VM" in _md, f"{_mb/_mo:.2f}x")
    check("mdp conclusion quotes the measured percentage", f"{100*(1-_mo/_mb):.1f}% less time" in _md)

# ---------------------------------------------------------------- reproducibility section
_rb = mean_of(os.path.join(ROOT, "results", "reproducibility", "pyflate", "pyflate_base.json"))
_ro = mean_of(os.path.join(ROOT, "results", "reproducibility", "pyflate", "pyflate_opt.json"))
def _flat(t):
    """collapse whitespace so a line-wrapped sentence matches a one-line expectation"""
    return re.sub(r"\s+", " ", t)
if _b and _o and _rb and _ro:
    check("reproducibility: pyflate shipped speedup quoted", f"{_b/_o:.3f}x shipped" in _flat(_pf), f"{_b/_o:.3f}x")
    check("reproducibility: pyflate rerun speedup quoted",
          f"{_rb/_ro:.3f}x rerun" in _flat(_pf) or f"{_rb/_ro:.3f}x earlier" in _flat(_pf), f"{_rb/_ro:.3f}x")
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
      "49.7%" in _pf and _flat_pf.count("62%") == _flat_pf.count("earlier draft of this report did exactly that and quoted ~62%"),
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
