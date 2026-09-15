#!/usr/bin/env python3
"""Dump golden test vectors for the Huffman decoder from the real benchmark input.

Runs the optimized pyflate decoder on data/interpreter.tar.bz2 with
HuffmanTable.find_next_symbol instrumented, and writes, for the first bzip2
block:

  tb/vectors/tables.txt    one line per programmed entry:
                             R <tsel> <L> <limit> <base>      (per code length)
                             S <tsel> <idx> <sym>             (symbol table)
  tb/vectors/stream.hex    the compressed bytes starting at the byte that holds
                           the first Huffman symbol, one byte per line (hex)
  tb/vectors/meta.txt      skip_bits=<leading bits of the first byte to drop>
                           nsym=<number of expected symbols>
  tb/vectors/expected.txt  one line per decoded symbol: <tsel> <sym> <len>

The testbench feeds stream.hex through the bit reader, drives tsel from
expected.txt and checks every (sym, len) against the software decoder.
"""
import hashlib, importlib.util, os, sys, time, types

def _load_without_pyperf(name, path):
    """Import a benchmark module, with a pyperf stub if pyperf is not installed.

    The benchmark uses pyperf only for perf_counter and (under __main__) the
    Runner, so a fresh clone can run this before script_pyflate.sh has built the venv.
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
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC  = os.path.join(ROOT, 'benchmarks', 'pyflate', 'run_benchmark_opt.py')
DATA = os.path.join(ROOT, 'benchmarks', 'pyflate', 'data', 'interpreter.tar.bz2')
VEC  = os.path.join(HERE, 'tb', 'vectors')
NBLOCKS = int(sys.argv[1]) if len(sys.argv) > 1 else 1

pf = _load_without_pyperf('pyflate_opt', SRC)

rows   = []          # ("R"/"S", ...)
expected = []        # (tsel, sym, len)
first_bit = None
state = {'blocks': 0, 'tsel_of': {}}

orig_decode_block = pf.decode_huffman_block
def decode_block_wrapper(b, out):
    state['blocks'] += 1
    state['tsel_of'] = {}          # tables are per block
    return orig_decode_block(b, out)
pf.decode_huffman_block = decode_block_wrapper

orig_find = pf.HuffmanTable.find_next_symbol
def find_logged(self, field, reversed=True):
    global first_bit
    if state['blocks'] > NBLOCKS:
        return orig_find(self, field, reversed)
    tid = id(self)
    if tid not in state['tsel_of']:
        tsel = len(state['tsel_of'])
        state['tsel_of'][tid] = tsel
        for L in range(1, 21):                      # every length the RTL has a row for
            if L <= self.max_bits:
                rows.append(('R', tsel, L, self._limit[L], self._base[L]))
            else:
                rows.append(('R', tsel, L, 0, 0))      # unused length: never matches
        for i, s in enumerate(self._syms):
            rows.append(('S', tsel, i, s))
    tsel = state['tsel_of'][tid]
    pos0 = field.count * 8 - field.bits
    if first_bit is None:
        first_bit = pos0
    sym = orig_find(self, field, reversed)
    pos1 = field.count * 8 - field.bits
    expected.append((tsel, sym, pos1 - pos0))
    return sym
pf.HuffmanTable.find_next_symbol = find_logged

with open(DATA, 'rb') as f:
    raw = f.read()
with open(DATA, 'rb') as f:
    field = pf.RBitfield(f)
    assert field.readbits(16) == 0x425a
    outb = pf.bzip2_main(field)
# the hooks must not change what the decoder produces
assert hashlib.md5(outb).hexdigest() == "afa004a630fe072901b1d9628b960974"

os.makedirs(VEC, exist_ok=True)
start_byte = first_bit // 8
skip_bits  = first_bit % 8
last_bit   = first_bit + sum(l for _, _, l in expected)
end_byte   = (last_bit + 7) // 8 + 8            # a little slack for the final peek
ntab   = max(t for t, _, _ in expected) + 1
minlen = min(l for _, _, l in expected)
maxlen = max(l for _, _, l in expected)
with open(os.path.join(VEC, 'tables.txt'), 'w') as fo:
    for r in rows:
        fo.write(' '.join(str(x) for x in r) + '\n')
with open(os.path.join(VEC, 'stream.hex'), 'w') as fo:
    for byte in raw[start_byte:end_byte]:
        fo.write(f'{byte:02x}\n')
with open(os.path.join(VEC, 'expected.txt'), 'w') as fo:
    for t, s, l in expected:
        fo.write(f'{t} {s} {l}\n')
with open(os.path.join(VEC, 'meta.txt'), 'w') as fo:
    fo.write(f'skip_bits={skip_bits}\nnsym={len(expected)}\nnbytes={end_byte-start_byte}\n'
             f'ntables={ntab}\nmaxbits={maxlen}\n')
print(f"blocks covered: {NBLOCKS}; tables: {ntab}; symbols: {len(expected)}; "
      f"stream bytes: {end_byte-start_byte}; first symbol at bit {first_bit} (byte {start_byte} +{skip_bits}); "
      f"code lengths used: {minlen}..{maxlen}; "
      f"table rows: {sum(1 for r in rows if r[0]=='R')}, symbol entries: {sum(1 for r in rows if r[0]=='S')}")
