#!/usr/bin/env python3
"""Summarize what script_<benchmark>.sh wrote into results/<benchmark>/.

Prints, per benchmark: the pyperformance-framework baseline, the pyperf
baseline and optimized runs (mean +- std, number of values), the speedup,
the pyperf compare_to table, and the perf stat counters for both builds.
Used to fill the performance sections of the reports.
"""
import json, os, re, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
    if not vals: return "n/a"
    m = statistics.mean(vals); s = statistics.stdev(vals) if len(vals) > 1 else 0.0
    unit = 'ms' if m < 1 else 's'
    k = 1e3 if unit == 'ms' else 1
    return f"{m*k:9.2f} +- {s*k:6.2f} {unit}  (n={len(vals)})"

def perfstat(path):
    if not os.path.exists(path): return {}
    rows = {}
    for line in open(path):
        m = re.match(r'\s*([\d,\.]+)\s+(msec\s+)?([a-z-]+)', line)
        if m and m.group(3) in ('task-clock','cycles','instructions','branches','branch-misses'):
            rows[m.group(3)] = float(m.group(1).replace(',', ''))
    if 'cycles' in rows and 'instructions' in rows and rows['cycles']:
        rows['IPC'] = rows['instructions'] / rows['cycles']
    if 'branches' in rows and 'branch-misses' in rows and rows['branches']:
        rows['branch-miss %'] = 100.0 * rows['branch-misses'] / rows['branches']
    return rows

def summarize(b):
    d = os.path.join(ROOT, 'results', b)
    print("=" * 78); print(f"{b}   ({d})"); print("=" * 78)
    fw = os.path.join(d, f'{b}_pyperformance_baseline.json')
    base = os.path.join(d, f'{b}_base.json'); opt = os.path.join(d, f'{b}_opt.json')
    if os.path.exists(fw):
        for name, vals in load_values(fw).items():
            print(f"  pyperformance run --bench {b:8s} {name:18s} {fmt(vals)}")
    bv = ov = None
    if os.path.exists(base):
        for name, vals in load_values(base).items():
            print(f"  pyperf baseline  {name:18s} {fmt(vals)}"); bv = bv or vals
    if os.path.exists(opt):
        for name, vals in load_values(opt).items():
            print(f"  pyperf optimized {name:18s} {fmt(vals)}"); ov = ov or vals
    if bv and ov:
        print(f"  speedup (mean/mean): {statistics.mean(bv)/statistics.mean(ov):.2f}x")
    cmp_ = os.path.join(d, f'compare_{b}.txt')
    if os.path.exists(cmp_):
        print("  --- pyperf compare_to:"); print('\n'.join('    ' + l for l in open(cmp_).read().strip().splitlines()))
    ps = {v: perfstat(os.path.join(d, f'perfstat_{v}.txt')) for v in ('base', 'opt')}
    if ps['base'] or ps['opt']:
        print("  --- perf stat (worker, 4 loops):")
        keys = ['task-clock', 'cycles', 'instructions', 'IPC', 'branches', 'branch-misses', 'branch-miss %']
        print(f"    {'counter':16s} {'baseline':>18s} {'optimized':>18s} {'ratio':>8s}")
        for k in keys:
            a, c = ps['base'].get(k), ps['opt'].get(k)
            if a is None and c is None: continue
            fa = f"{a:18,.3f}" if isinstance(a, float) and k in ('IPC','branch-miss %') else (f"{a:18,.0f}" if a is not None else f"{'':>18s}")
            fc = f"{c:18,.3f}" if isinstance(c, float) and k in ('IPC','branch-miss %') else (f"{c:18,.0f}" if c is not None else f"{'':>18s}")
            r = f"{a/c:8.2f}" if (a and c and k not in ('IPC','branch-miss %')) else ''
            print(f"    {k:16s} {fa} {fc} {r}")
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.startswith('flame_'): print(f"  flame graph: {f}")
    print()

if __name__ == '__main__':
    for b in (sys.argv[1:] or ['pyflate', 'mdp']):
        summarize(b)
