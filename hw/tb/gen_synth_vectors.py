#!/usr/bin/env python3
"""Directed vector sets for the cases the real bzip2 block cannot reach.

hw/gen_vectors.py dumps one real block from the benchmark. That block is
well-formed, uses only code lengths 2..15, and ends with slack bits after the
last symbol, so it reaches none of the corners below. One directed set per
corner, in the order `make sim_all` runs them:

  * lengths   every code length 1..20, including the all-ones 20-bit code -
              the widest codes bzip2 allows, and the reason the comparators
              and the 21-bit limit width exist;
  * eof       the stream ends exactly on a code boundary;
  * err       an incomplete code, so some bit pattern matches nothing: err
              must halt the engine;
  * badidx    a base row that points past the symbol table: err, not a
              wrong symbol;
  * underrun  the stream ends short of a whole code: underrun must rise;
  * drain     a whole number of 32-bit words, so the buffer empties and
              `done` can assert.

Each set is written in exactly the format tb_huffman.sv already reads, so the
same testbench runs them.  A mutation-tested design needs stimulus that can
tell a correct decoder from a broken one, and these are the cases that do.

    python3 tb/gen_synth_vectors.py            # writes tb/vectors_*/
"""
import os, sys

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAXBITS = 20


def canonical(lengths):
    """Canonical Huffman code from a list of (symbol, code length).

    Returns (codes, limit, base) with the same meaning as the software
    decoder's _build_canonical: limit[L] is the first code of length L+1
    scaled into L bits, base[L] indexes the symbol table.
    """
    lengths = sorted(lengths, key=lambda t: (t[1], t[0]))
    counts = {}
    for _, L in lengths:
        counts[L] = counts.get(L, 0) + 1
    minb = min(L for _, L in lengths)
    maxb = max(L for _, L in lengths)

    codes, code, index = {}, 0, 0
    first, limit, base = {}, {}, {}
    syms = []
    for L in range(minb, maxb + 1):
        first[L] = code
        n = counts.get(L, 0)
        for sym, LL in lengths:
            if LL == L:
                codes[sym] = (code, L)
                syms.append(sym)
                code += 1
        limit[L] = code                    # one past the last code of length L
        base[L] = index - first[L]
        index += n
        code <<= 1
    return codes, limit, base, minb, maxb, syms


def emit(dirname, lengths, sequence, corrupt_tail=False, exact_end=True, bad_base=None,
         word_align=False):
    codes, limit, base, minb, maxb, syms = canonical(lengths)
    d = os.path.join(HW, dirname)
    os.makedirs(d, exist_ok=True)

    rows = []
    for L in range(1, MAXBITS + 1):
        lim = limit.get(L, 0) if minb <= L <= maxb else 0
        bas = base.get(L, 0) if minb <= L <= maxb else 0
        if bad_base is not None and L == minb:
            bas = bad_base          # deliberately points past the symbol table
        rows.append(("R", 0, L, lim, bas))
    for i, s in enumerate(syms):
        rows.append(("S", 0, i, s))

    bits = []
    expected = []
    for sym in sequence:
        c, L = codes[sym]
        bits.extend((c >> (L - 1 - k)) & 1 for k in range(L))
        expected.append((0, sym, L))
    if corrupt_tail:
        # A run of ones longer than any code: nothing can match, so the decoder
        # must raise err and stop rather than loop on the same bits.
        bits.extend([1] * (MAXBITS + 4))
        # not in `expected`: the testbench stops at nsym and checks err separately

    if word_align:
        # Pad with the shortest code until the stream is a whole number of
        # 32-bit words, so the reader's buffer drains to exactly zero and `done`
        # can actually assert. Every other set leaves byte padding behind, which
        # is why done is unobservable in them.
        short_sym = min(codes, key=lambda k: codes[k][1])
        sc, sl = codes[short_sym]
        while (len(bits) % 32) != 0:
            bits.extend((sc >> (sl - 1 - k)) & 1 for k in range(sl))
            expected.append((0, short_sym, sl))

    if exact_end:
        # Pad to a byte boundary with zeros. Those pad bits are a prefix of the
        # shortest code, which is exactly the case that used to manufacture a
        # phantom symbol out of the padding.
        while len(bits) % 8:
            bits.append(0)
    else:
        bits.extend([0] * 64)

    data = bytearray()
    for i in range(0, len(bits), 8):
        b = 0
        for k in range(8):
            b = (b << 1) | (bits[i + k] if i + k < len(bits) else 0)
        data.append(b)

    with open(os.path.join(d, "tables.txt"), "w") as f:
        for r in rows:
            f.write(" ".join(str(x) for x in r) + "\n")
    with open(os.path.join(d, "stream.hex"), "w") as f:
        for b in data:
            f.write("%02x\n" % b)
    with open(os.path.join(d, "expected.txt"), "w") as f:
        for t, s, L in expected:
            f.write("%d %d %d\n" % (t, s, L))
    with open(os.path.join(d, "meta.txt"), "w") as f:
        f.write("skip_bits=0\nnsym=%d\nnbytes=%d\nntables=1\nmaxbits=%d\n"
                % (len(expected), len(data), maxb))
    print("%-22s %3d symbols, lengths %d..%d, %d bytes%s"
          % (dirname, len(expected), minb, maxb, len(data),
             ", corrupt tail" if corrupt_tail else ""))
    return codes, maxb


def main():
    # 1. Every code length from 1 to 20, including the all-ones 20-bit code.
    #    A complete canonical code needs exactly one symbol per length plus a
    #    second at the longest length: 1/2/4/.../2^19 with the last level full.
    lengths = [(i, i) for i in range(1, MAXBITS + 1)] + [(MAXBITS + 1, MAXBITS)]
    seq = [s for s, _ in lengths] * 3
    emit("tb/vectors_lengths", lengths, seq)

    # 2. The same code, but the stream stops exactly on the final code with
    #    only byte padding after it: flush and eof decide whether the decoder
    #    stops cleanly or invents a symbol out of the padding.
    emit("tb/vectors_eof", lengths, [s for s, _ in lengths])

    # 3. An INCOMPLETE code plus a tail of ones. Incomplete matters: with a
    #    complete code every bit pattern decodes to something, so no stream can
    #    ever reach the error path. Here lengths {1,2} leave the pattern "11"
    #    unassigned, and the decoder must raise err and halt on it.
    emit("tb/vectors_err", [(0, 1), (1, 2)], [0, 1, 0, 1], corrupt_tail=True)

    # 4. A table whose base row points past the end of the symbol table. The
    #    index check is the only thing between that and a silently wrong
    #    symbol, so the decoder must raise err instead of reading out of range.
    emit("tb/vectors_badidx", [(0, 2), (1, 2), (2, 2), (3, 2)], [0, 1, 2, 3],
         bad_base=400)

    # 5. The stream ends short of a whole code. Three symbols take 7 bits, but
    #    the testbench hands over a whole 32-bit word, so the 25 zero bits after
    #    them decode as twelve 2-bit codes that nobody checks (comparison stops
    #    at nsym) and the one bit left is shorter than any code: underrun must
    #    rise there - "UNDERRUN at symbol 15" in the log.
    emit("tb/vectors_underrun", [(0, 2), (1, 2), (2, 2), (3, 3), (4, 3)],
         [0, 1, 3])

    # 6. A stream that is a whole number of 32-bit words, so the buffer drains
    #    to zero and `done` asserts. Without this, done never rises in any test
    #    and anything about it is unverifiable.
    emit("tb/vectors_drain", [(i, i) for i in range(1, 5)] + [(5, 4)],
         [1, 2, 3, 4, 5] * 4, word_align=True)


if __name__ == "__main__":
    main()
