#!/usr/bin/env python3
"""Quick correctness + speed check of baseline vs optimized, in-process.

Not the official measurement (that is pyperformance/pyperf inside the course VM);
this is the fast inner loop while developing: it verifies each benchmark's own
correctness gate on the optimized code and prints a rough speedup.

  python3 scripts/local_check.py [all|pyflate|mdp] [reps]
"""
import bz2, hashlib, importlib.util, math, os, statistics, sys, tempfile, time, types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_pyperf():
    """Install a minimal pyperf stand-in when the real package is not installed.

    The benchmarks import pyperf at top level but only use perf_counter, and
    Runner under __main__, so a stub is enough to import them here.
    """
    try:
        import pyperf  # noqa: F401
    except ImportError:
        stub = types.ModuleType("pyperf")
        stub.perf_counter = time.perf_counter

        class _Runner:                      # only reached under __main__
            def __init__(self, *a, **k):
                raise SystemExit("this script needs pyperf; run script_<benchmark>.sh first")
        stub.Runner = _Runner
        sys.modules["pyperf"] = stub


def load_benchmark(name, path):
    """Import a benchmark module from its file path."""
    ensure_pyperf()
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def timeit(fn, reps):
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return min(ts), statistics.median(ts)


def _try(fn, *a):
    """Run fn and return its result, or a tag for the exception it raised.

    Lets two decoders be compared on an input neither accepts: they must agree
    on whether it decodes, and on the bytes when it does."""
    try:
        return fn(*a)
    except Exception as e:
        return ("exception", type(e).__name__)


def check_pyflate(reps):
    d = os.path.join(ROOT, 'benchmarks', 'pyflate')
    data = os.path.join(d, 'data', 'interpreter.tar.bz2')
    base = load_benchmark('pyflate_base', os.path.join(d, 'run_benchmark.py'))
    opt = load_benchmark('pyflate_opt', os.path.join(d, 'run_benchmark_opt.py'))
    # the benchmark's own md5 check runs inside bench_pyflake() and raises on mismatch
    base.bench_pyflake(1, data)
    opt.bench_pyflake(1, data)

    def decomp(m, path=data):
        with open(path, 'rb') as f:
            field = m.RBitfield(f)
            # read, not assert: under python -O an assert is skipped and the
            # 16 magic bits would never be consumed
            magic = field.readbits(16)
            if magic != 0x425a:
                raise SystemExit(f"not a bzip2 stream: magic {magic:#06x}")
            return m.bzip2_main(field)

    # compare the raw decompressed bytes as well, not only the md5
    ob, oo = decomp(base), decomp(opt)
    if ob != oo:
        raise SystemExit("optimized output differs from baseline!")
    print(f"pyflate: output identical to baseline ({len(oo)} bytes, md5 {hashlib.md5(oo).hexdigest()})")

    # a few more bzip2 streams, with shapes the benchmark file does not contain
    extra = [("empty", b""), ("one byte", b"x"), ("repeated", b"a" * 70000),
             ("multi-block", bytes(range(256)) * 1200)]
    for name, payload in extra:
        for level in (1, 9):
            blob = bz2.compress(payload, level)
            with tempfile.NamedTemporaryFile(suffix=".bz2", delete=False) as t:
                t.write(blob)          # keep the BZ magic: decomp() reads it
                tmp = t.name
            try:
                rb = _try(decomp, base, tmp)
                ro = _try(decomp, opt, tmp)
                if rb != ro:
                    raise SystemExit(f"pyflate: baseline and optimized differ on '{name}' (level {level}): {rb} vs {ro}")
            finally:
                os.unlink(tmp)
    print(f"pyflate: baseline and optimized agree on {len(extra) * 2} further bzip2 streams "
          f"(empty, 1 byte, 70 KB of one byte, multi-block; levels 1 and 9)")

    bmin, bmed = timeit(lambda: base.bench_pyflake(1, data), reps)
    omin, omed = timeit(lambda: opt.bench_pyflake(1, data), reps)
    print(f"pyflate: base min {bmin*1e3:8.1f} ms   opt min {omin*1e3:8.1f} ms   speedup {bmin/omin:5.2f}x   (median {bmed/omed:.2f}x)")


def check_mdp(reps):
    d = os.path.join(ROOT, 'benchmarks', 'mdp')
    base = load_benchmark('mdp_base', os.path.join(d, 'run_benchmark.py'))
    opt = load_benchmark('mdp_opt', os.path.join(d, 'run_benchmark_opt.py'))
    rb = base.Battle().evaluate(0.192)
    ro = opt.Battle().evaluate(0.192)
    exp = 0.89873589887
    print(f"mdp: base result {rb!r}  opt result {ro!r}  |diff| {abs(rb-ro):.3e}  "
          f"gate |opt-expected| {abs(ro-exp):.3e} (must be < 1e-6) {'OK' if abs(ro-exp) < 1e-6 else 'FAIL'}")
    if abs(ro - exp) >= 1e-6:
        raise SystemExit(f"mdp: optimized result {ro!r} is not the expected {exp!r}")
    # also compare against the baseline directly: the 1e-6 tolerance alone
    # would accept a result that is off by 9e-7
    if rb == ro:
        print("mdp: optimized result is bit-identical to the baseline")
    elif sys.version_info >= (3, 12) and abs(rb - ro) <= 8 * math.ulp(max(abs(rb), abs(ro))):
        # CPython 3.12+ sum() uses compensated summation (gh-100425). The
        # baseline sums with sum() and the optimized loop keeps a running total,
        # so from 3.12 on they differ in the last bit. The course VM's 3.10 is
        # bit-identical, and every shipped number comes from there.
        ulp = math.ulp(max(abs(rb), abs(ro)))
        print(f"mdp: baseline and optimized differ by {abs(rb-ro):.3e} "
              f"({abs(rb-ro)/ulp:.1f} ulp) on CPython {sys.version_info.major}."
              f"{sys.version_info.minor}; see report_mdp.txt section 3 - "
              f"they are bit-identical on the course VM's 3.10")
    else:
        raise SystemExit(f"mdp: optimized {ro!r} differs from baseline {rb!r}")
    base.bench_mdp(1)      # each raises on its own check
    opt.bench_mdp(1)
    bmin, bmed = timeit(lambda: base.bench_mdp(1), reps)
    omin, omed = timeit(lambda: opt.bench_mdp(1), reps)
    print(f"mdp:     base min {bmin*1e3:8.1f} ms   opt min {omin*1e3:8.1f} ms   speedup {bmin/omin:5.2f}x   (median {bmed/omed:.2f}x)")


if __name__ == '__main__':
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    if which in ('all', 'pyflate'):
        check_pyflate(reps)
    if which in ('all', 'mdp'):
        check_mdp(reps)
