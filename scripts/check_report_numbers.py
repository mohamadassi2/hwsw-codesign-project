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
    (OK if cond else FAIL).append(f"{name}{('  ' + detail) if detail else ''}")


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
    _cells = re.findall(r"^(\d+) cells$", s, re.M); _d = re.search(r"length=(\d+)", s); _ff = re.search(r"^(\d+) flip-flops", s, re.M)
    for label, tok in (("cells", _cells[0] if _cells else None), ("flattened cells", _cells[1] if len(_cells) > 1 else None),
                       ("depth", _d.group(1) if _d else None), ("flip-flops", _ff.group(1) if _ff else None), ("kbit", "19.4")):
        check(f"synthesis {label} ({tok}) quoted in the report", tok is not None and tok in txt_n, "from docs/synthesis_yosys.txt")

# ---------------------------------------------------------------- report
print(f"PASS {len(OK)}   FAIL {len(FAIL)}\n")
for line in OK:
    print("  pass  " + line)
if FAIL:
    print()
    for line in FAIL:
        print("  FAIL  " + line)
sys.exit(1 if FAIL else 0)
