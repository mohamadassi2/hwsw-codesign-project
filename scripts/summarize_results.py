#!/usr/bin/env python3
"""Summarize what script_<benchmark>.sh wrote into results/<benchmark>/.

Prints, per benchmark: the pyperformance-framework baseline, the pyperf
baseline and optimized runs (mean +- std, number of values), the speedup,
the pyperf compare_to table, and the perf stat counters for both builds.
Read-only: the quickest way to see what the course VM measured.
scripts/fill_reports.py is what writes these figures into the reports.

    python3 scripts/summarize_results.py [benchmark ...]
"""
import json, os, re, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COUNTERS = ('task-clock', 'cycles', 'instructions', 'IPC', 'branches', 'branch-misses', 'branch-miss %')
DERIVED = ('IPC', 'branch-miss %')       # ratios, printed with decimals and no base/opt ratio


def load_values(path):
    with open(path) as f:
        d = json.load(f)
    out = {}
    for b in d.get('benchmarks', []):
        name = (b.get('metadata') or {}).get('name') or d['metadata'].get('name')
        vals = []
        for run in b.get('runs', []):
            vals.extend(run.get('values', []))
        out[name] = vals
    return out


def fmt(vals):
    if not vals:
        return "n/a"
    m = statistics.mean(vals)
    s = statistics.stdev(vals) if len(vals) > 1 else 0.0
    if m < 1:
        return f"{m*1e3:9.2f} +- {s*1e3:6.2f} ms  (n={len(vals)})"
    return f"{m:9.2f} +- {s:6.2f} s  (n={len(vals)})"


def perfstat(path):
    if not os.path.exists(path):
        return {}
    rows = {}
    for line in open(path):
        m = re.match(r'\s*([\d,\.]+)\s+(msec\s+)?([a-z-]+)', line)
        if m and m.group(3) in ('task-clock', 'cycles', 'instructions', 'branches', 'branch-misses'):
            rows[m.group(3)] = float(m.group(1).replace(',', ''))
    if 'cycles' in rows and 'instructions' in rows and rows['cycles']:
        rows['IPC'] = rows['instructions'] / rows['cycles']
    if 'branches' in rows and 'branch-misses' in rows and rows['branches']:
        rows['branch-miss %'] = 100.0 * rows['branch-misses'] / rows['branches']
    return rows


def summarize(b):
    d = os.path.join(ROOT, 'results', b)
    print("=" * 78)
    print(f"{b}   ({d})")
    print("=" * 78)
    fw = os.path.join(d, f'{b}_pyperformance_baseline.json')
    base = os.path.join(d, f'{b}_base.json')
    opt = os.path.join(d, f'{b}_opt.json')
    if os.path.exists(fw):
        for name, vals in load_values(fw).items():
            print(f"  pyperformance run --bench {b:8s} {name:18s} {fmt(vals)}")
    bv = ov = None
    if os.path.exists(base):
        for name, vals in load_values(base).items():
            print(f"  pyperf baseline  {name:18s} {fmt(vals)}")
            bv = bv or vals
    if os.path.exists(opt):
        for name, vals in load_values(opt).items():
            print(f"  pyperf optimized {name:18s} {fmt(vals)}")
            ov = ov or vals
    if bv and ov:
        print(f"  speedup (mean/mean): {statistics.mean(bv)/statistics.mean(ov):.2f}x")

    cmp_ = os.path.join(d, f'compare_{b}.txt')
    if os.path.exists(cmp_):
        print("  --- pyperf compare_to:")
        for l in open(cmp_).read().strip().splitlines():
            print('    ' + l)

    ps = {v: perfstat(os.path.join(d, f'perfstat_{v}.txt')) for v in ('base', 'opt')}
    if ps['base'] or ps['opt']:
        print("  --- perf stat (worker, 4 loops):")
        print(f"    {'counter':16s} {'baseline':>18s} {'optimized':>18s} {'ratio':>8s}")
        for k in COUNTERS:
            a, c = ps['base'].get(k), ps['opt'].get(k)
            if a is None and c is None:
                continue
            spec = '18,.3f' if k in DERIVED else '18,.0f'
            fa = f"{a:{spec}}" if a is not None else ' ' * 18
            fc = f"{c:{spec}}" if c is not None else ' ' * 18
            r = f"{a/c:8.2f}" if (a and c and k not in DERIVED) else ''
            print(f"    {k:16s} {fa} {fc} {r}")

    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.startswith('flame_'):
                print(f"  flame graph: {f}")
    print()


if __name__ == '__main__':
    for b in (sys.argv[1:] or ['pyflate', 'mdp']):
        summarize(b)
