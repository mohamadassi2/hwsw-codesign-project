#!/usr/bin/env python3
"""Replace the TODO-VM placeholders in the reports with the measured VM data.

Reads results/<benchmark>/ (written by script_<benchmark>.sh in the course VM)
and rewrites the "4.1 Course VM" block of each report, plus the Amdahl estimate
in report_pyflate.txt section 5.6, so every number in the reports comes from the
same measurement rather than from a hand transcription.

  python3 scripts/fill_reports.py            # write
  python3 scripts/fill_reports.py --dry-run  # show what would change

Afterwards run scripts/check_report_numbers.py, which recomputes everything.
"""
import argparse, json, os, re, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def values(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        d = json.load(f)
    out = []
    for b in d.get("benchmarks", []):
        for run in b.get("runs", []):
            out.extend(run.get("values", []))
    return out


def stat(vals):
    if not vals:
        return None
    m = statistics.mean(vals)
    s = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return m, s, len(vals)


def fmt(t):
    """Seconds -> a string with a sensible unit."""
    m, s, n = t
    if m < 1:
        return f"{m*1e3:.1f} +- {s*1e3:.1f} ms  (n={n})"
    return f"{m:.3f} +- {s:.3f} s  (n={n})"


def perfstat(path):
    if not os.path.exists(path):
        return {}
    rows = {}
    for line in open(path):
        m = re.match(r"\s*([\d,\.]+)\s+(msec\s+)?([a-z-]+)", line)
        if m and m.group(3) in ("task-clock", "cycles", "instructions",
                                "branches", "branch-misses",
                                "cache-references", "cache-misses"):
            rows[m.group(3)] = float(m.group(1).replace(",", ""))
    return rows


def counter_table(b):
    ps = {v: perfstat(os.path.join(ROOT, "results", b, f"perfstat_{v}.txt"))
          for v in ("base", "opt")}
    if not ps["base"] and not ps["opt"]:
        return "    (perf stat produced no counters in this run)"
    lines = [f"    {'counter':18s}{'baseline':>20s}{'optimized':>20s}{'ratio':>9s}"]
    for k in ("task-clock", "cycles", "instructions", "branches",
              "branch-misses", "cache-references", "cache-misses"):
        a, c = ps["base"].get(k), ps["opt"].get(k)
        if a is None and c is None:
            continue
        fa = f"{a:20,.2f}" if a is not None else " " * 20
        fc = f"{c:20,.2f}" if c is not None else " " * 20
        r = f"{a/c:9.2f}" if (a and c) else " " * 9
        lines.append(f"    {k:18s}{fa}{fc}{r}")
    for v, tag in (("base", "baseline"), ("opt", "optimized")):
        cy, ins = ps[v].get("cycles"), ps[v].get("instructions")
        if cy and ins:
            lines.append(f"    IPC ({tag}): {ins/cy:.3f}")
    return "\n".join(lines)


def block(b):
    d = os.path.join(ROOT, "results", b)
    fw = stat(values(f"{d}/{b}_pyperformance_baseline.json"))
    base = stat(values(f"{d}/{b}_base.json"))
    opt = stat(values(f"{d}/{b}_opt.json"))
    if not (base and opt):
        return None, None, None
    sp, pct = base[0] / opt[0], 100 * (1 - opt[0] / base[0])
    cmp_path = f"{d}/compare_{b}.txt"
    cmp_txt = open(cmp_path).read().strip() if os.path.exists(cmp_path) else "(not produced)"
    ev = ""
    for tag in ("base", "opt"):
        p = f"{d}/perf_{tag}.event"
        if os.path.exists(p):
            ev = open(p).read().strip()
            break
    flames = sorted(f for f in (os.listdir(d) if os.path.isdir(d) else []) if f.startswith("flame_"))
    lines = [
        "4.1 Course VM (the numbers this report quotes)",
        "    Guest: Ubuntu 22.04, 1 vCPU, on an Intel Xeon E5-2630 v3 host, booted with",
        "    -cpu host -accel kvm. Measured by script_%s.sh; raw files in results/%s/." % (b, b),
        "",
        f"      pyperformance run --bench {b}     {fmt(fw) if fw else '(not produced)'}",
        f"      pyperf, baseline (vendored copy)  {fmt(base)}",
        f"      pyperf, optimized                 {fmt(opt)}",
        f"      speedup  {sp:.2f}x   ({pct:.1f}% less time; the assignment asks for 7%)",
        "",
        "    pyperf compare_to:",
    ]
    lines += ["      " + l for l in cmp_txt.splitlines()]
    lines += ["", "    perf stat (worker run):", counter_table(b)]
    if ev:
        lines += ["", f"    Sampling used: perf record {ev}",
                  "    (the guest has no sampling PMU, so the default cycles event yields",
                  "     no samples; see section 2)"]
    if flames:
        lines += ["", "    Flame graphs:"] + [f"      results/{b}/{f}" for f in flames]
    return "\n".join(lines), base[0], opt[0]


def replace_41(text, new_block):
    """Swap the 4.1 block, whatever it currently says, up to the 4.2 heading."""
    m = re.search(r"^4\.1 .*?(?=^4\.2 )", text, re.S | re.M)
    if not m:
        return text, False
    return text[:m.start()] + new_block + "\n\n", True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    changed = []
    vm = {}
    for b in ("pyflate", "mdp"):
        blk, base, opt = block(b)
        if blk is None:
            print(f"{b}: no results yet, skipping")
            continue
        vm[b] = (base, opt)
        p = os.path.join(ROOT, f"report_{b}.txt")
        t = open(p).read()
        t2, ok = replace_41(t, blk)
        if not ok:
            print(f"{b}: could not find the 4.1 block", file=sys.stderr)
            continue
        if args.dry_run:
            print(f"--- {b} 4.1 would become ---\n{blk}\n")
        elif t2 != t:
            open(p, "w").write(t2)
            changed.append(p)

    # Amdahl paragraph, from the VM optimized time
    if "pyflate" in vm and not args.dry_run:
        base_s, opt_s = vm["pyflate"]
        opt_ms = opt_s * 1e3
        frac = 62
        part = opt_ms * frac / 100
        accel = 148272 / 200e6 * 1e3 + 0.6      # decode at 200 MHz + DMA/MMIO
        newtot = opt_ms - part + accel
        p = os.path.join(ROOT, "report_pyflate.txt")
        t = open(p).read()
        t = re.sub(r"Take the optimized run [^,]*, [\d.]+ ms, of which the",
                   f"Take the optimized run measured in the VM, {opt_ms:.0f} ms, of which the", t)
        t = re.sub(r"Huffman-and-bit-extraction part is ~\d+% = ~[\d.]+ ms",
                   f"Huffman-and-bit-extraction part is ~{frac}% = ~{part:.0f} ms", t)
        t = re.sub(r"[\d.]+ - [\d.]+ \+ [\d.]+\s+=\s+~?[\d.]+ ms",
                   f"{opt_ms:.0f} - {part:.0f} + {accel:.1f}  =  ~{newtot:.0f} ms", t)
        t = re.sub(r"~[\d.]+x over the optimized software",
                   f"~{opt_ms/newtot:.1f}x over the optimized software", t)
        t = re.sub(r"~[\d.]+x over the shipped benchmark",
                   f"~{base_s*1e3/newtot:.1f}x over the shipped benchmark", t)
        open(p, "w").write(t)
        changed.append(p)

    for c in sorted(set(changed)):
        print("updated", os.path.relpath(c, ROOT))
    if changed:
        print("\nnow run: python3 scripts/check_report_numbers.py")


if __name__ == "__main__":
    main()
