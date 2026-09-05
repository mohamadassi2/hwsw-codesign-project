#!/usr/bin/env python3
"""Quick correctness + speed check of baseline vs optimized, in-process.

Not the official measurement (that is pyperformance/pyperf inside the course VM);
this is the fast inner loop while developing: it verifies each benchmark's own
correctness gate on the optimized code and prints a rough speedup.
"""
import math
import importlib.util, os, sys, time, hashlib, statistics

def _load_without_pyperf(name, path):
    """Import a benchmark module without needing pyperf installed.

    The benchmarks import pyperf at the top level and use it only for
    perf_counter and the Runner in __main__. This harness needs neither, and a
    grader running from a fresh clone will not have pyperf until a benchmark
    script has built the virtual environment - so a minimal stand-in is
    installed first if the real package is absent.
    """
    import importlib.util, sys, time, types
    if "pyperf" not in sys.modules:
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
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load(path, name):
    return _load_without_pyperf(name, path)

def timeit(fn, reps):
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter(); fn(); ts.append(time.perf_counter() - t0)
    return min(ts), statistics.median(ts)

def _try(fn, *a):
    """Run fn, returning either its result or a tag for the exception it raised.

    The two decoders are allowed to fail on the same input; what they are not
    allowed to do is disagree about whether it decodes, or about the bytes."""
    try:
        return fn(*a)
    except Exception as e:
        return ("exception", type(e).__name__)


def check_pyflate(reps):
    d = os.path.join(ROOT, 'benchmarks', 'pyflate')
    data = os.path.join(d, 'data', 'interpreter.tar.bz2')
    base = load(os.path.join(d, 'run_benchmark.py'), 'pyflate_base')
    opt  = load(os.path.join(d, 'run_benchmark_opt.py'), 'pyflate_opt')
    # correctness gate: the benchmark's own md5 check runs inside bench_pyflake()
    for tag, m in (('base', base), ('opt', opt)):
        m.bench_pyflake(1, data)   # raises on md5 mismatch
    # additionally compare the raw decompressed bytes
    def decomp(m, path=data):
        with open(path, 'rb') as f:
            field = m.RBitfield(f)
            # Not inside an assert: under python -O the whole statement would
            # vanish, the 16 magic bits would never be consumed, and the check
            # would fail for the wrong reason.
            magic = field.readbits(16)
            if magic != 0x425a:
                raise SystemExit(f"not a bzip2 stream: magic {magic:#06x}")
            return m.bzip2_main(field)
    ob, oo = decomp(base), decomp(opt)
    if ob != oo:
        raise SystemExit("optimized output differs from baseline!")
    print(f"pyflate: output identical to baseline ({len(oo)} bytes, md5 {hashlib.md5(oo).hexdigest()})")
    # One input proves one input. These are cheap and cover the shapes the
    # benchmark file happens not to contain: a different block size, several
    # blocks, an empty payload and a single repeated byte.
    import bz2, tempfile
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
    base = load(os.path.join(d, 'run_benchmark.py'), 'mdp_base')
    opt  = load(os.path.join(d, 'run_benchmark_opt.py'), 'mdp_opt')
    rb = base.Battle().evaluate(0.192); ro = opt.Battle().evaluate(0.192)
    exp = 0.89873589887
    print(f"mdp: base result {rb!r}  opt result {ro!r}  |diff| {abs(rb-ro):.3e}  "
          f"gate |opt-expected| {abs(ro-exp):.3e} (must be < 1e-6) {'OK' if abs(ro-exp) < 1e-6 else 'FAIL'}")
    if abs(ro - exp) >= 1e-6:
        raise SystemExit(f"mdp: optimized result {ro!r} is not the expected {exp!r}")
    # The real equivalence check: optimized against baseline, not against a
    # constant. Comparing only to the constant, with the benchmark's own 1e-6
    # tolerance, would pass an optimized version that is systematically wrong
    # by 9e-7.
    if rb != ro:
        # CPython 3.12 (gh-100425) made sum() use compensated summation for
        # floats. The baseline sums with sum(); the optimized version keeps a
        # running total in a loop, which is what makes it fast. On 3.12+ the
        # BASELINE therefore moves by an ulp and the two differ in the last
        # bit. The course VM runs CPython 3.10, where they are identical, and
        # every shipped number comes from there.
        ulp = math.ulp(max(abs(rb), abs(ro))) if hasattr(math, "ulp") else 2 ** -52
        if sys.version_info >= (3, 12) and abs(rb - ro) <= 8 * ulp:
            print(f"mdp: baseline and optimized differ by {abs(rb-ro):.3e} "
                  f"({abs(rb-ro)/ulp:.1f} ulp) on CPython {sys.version_info.major}."
                  f"{sys.version_info.minor}; see report_mdp.txt section 3 - "
                  f"they are bit-identical on the course VM's 3.10")
        else:
            raise SystemExit(f"mdp: optimized {ro!r} differs from baseline {rb!r}")
    else:
        print("mdp: optimized result is bit-identical to the baseline")
    base.bench_mdp(1); opt.bench_mdp(1)      # each raises on its own check
    bmin, bmed = timeit(lambda: base.bench_mdp(1), reps)
    omin, omed = timeit(lambda: opt.bench_mdp(1), reps)
    print(f"mdp:     base min {bmin*1e3:8.1f} ms   opt min {omin*1e3:8.1f} ms   speedup {bmin/omin:5.2f}x   (median {bmed/omed:.2f}x)")

if __name__ == '__main__':
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if which in ('all', 'pyflate'): check_pyflate(reps)
    if which in ('all', 'mdp'): check_mdp(reps)
