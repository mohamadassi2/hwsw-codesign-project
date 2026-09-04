#!/usr/bin/env python3
"""Quick correctness + speed check of baseline vs optimized, in-process.

Not the official measurement (that is pyperformance/pyperf inside the course VM);
this is the fast inner loop while developing: it verifies each benchmark's own
correctness gate on the optimized code and prints a rough speedup.
"""
import importlib.util, os, sys, time, hashlib, statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def timeit(fn, reps):
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter(); fn(); ts.append(time.perf_counter() - t0)
    return min(ts), statistics.median(ts)

def check_pyflate(reps):
    d = os.path.join(ROOT, 'benchmarks', 'pyflate')
    data = os.path.join(d, 'data', 'interpreter.tar.bz2')
    base = load(os.path.join(d, 'run_benchmark.py'), 'pyflate_base')
    opt  = load(os.path.join(d, 'run_benchmark_opt.py'), 'pyflate_opt')
    # correctness gate: the benchmark's own md5 check runs inside bench_pyflake()
    for tag, m in (('base', base), ('opt', opt)):
        m.bench_pyflake(1, data)   # raises on md5 mismatch
    # additionally compare the raw decompressed bytes
    def decomp(m):
        with open(data, 'rb') as f:
            field = m.RBitfield(f); assert field.readbits(16) == 0x425a
            return m.bzip2_main(field)
    ob, oo = decomp(base), decomp(opt)
    assert ob == oo, "optimized output differs from baseline!"
    print(f"pyflate: output identical to baseline ({len(oo)} bytes, md5 {hashlib.md5(oo).hexdigest()})")
    bmin, bmed = timeit(lambda: base.bench_pyflake(1, data), reps)
    omin, omed = timeit(lambda: opt.bench_pyflake(1, data), reps)
    print(f"pyflate: base min {bmin*1e3:8.1f} ms   opt min {omin*1e3:8.1f} ms   speedup {bmin/omin:5.2f}x   (median {bmed/omed:.2f}x)")

def check_mdp(reps):
    d = os.path.join(ROOT, 'benchmarks', 'mdp')
    base = load(os.path.join(d, 'run_benchmark.py'), 'mdp_base')
    opt  = load(os.path.join(d, 'run_benchmark_opt.py'), 'mdp_opt')
    rb = base.Battle().evaluate(0.192); ro = opt.Battle().evaluate(0.192)
    exp = 0.89873589887
    print(f"mdp: base result {rb!r}  opt result {ro!r}  |diff| {abs(rb-ro):.3e}  "
          f"gate |opt-expected| {abs(ro-exp):.3e} (must be < 1e-6) {'OK' if abs(ro-exp) < 1e-6 else 'FAIL'}")
    assert abs(ro - exp) < 1e-6
    base.bench_mdp(1); opt.bench_mdp(1)      # each raises on its own check
    bmin, bmed = timeit(lambda: base.bench_mdp(1), reps)
    omin, omed = timeit(lambda: opt.bench_mdp(1), reps)
    print(f"mdp:     base min {bmin*1e3:8.1f} ms   opt min {omin*1e3:8.1f} ms   speedup {bmin/omin:5.2f}x   (median {bmed/omed:.2f}x)")

if __name__ == '__main__':
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if which in ('all', 'pyflate'): check_pyflate(reps)
    if which in ('all', 'mdp'): check_mdp(reps)
