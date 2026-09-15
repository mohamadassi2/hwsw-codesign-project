#!/usr/bin/env python3
"""Directed vector sets for the cases the real bzip2 block cannot reach.

hw/gen_vectors.py dumps one real block from the benchmark. That block is
well-formed, uses only code lengths 2..15, and ends with slack bits after the
last symbol, so it reaches none of the corners below. One set per corner, in
the order `make sim_all` runs them:

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

Each set uses the same file format as tb/vectors/, so tb_huffman.sv runs
them unchanged.

    python3 tb/gen_synth_vectors.py            # writes tb/vectors_*/
"""
import os

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAXBITS = 20


def canonical(lengths):
    """Canonical Huffman code from a list of (symbol, code length).

    Returns (codes, limit, base, minb, maxb, syms). limit and base mean the
    same as in the software decoder's _build_canonical: limit[L] is one past
    the last code of length L, base[L] + code indexes the symbol table.
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


def emit(dirname, lengths, sequence, corrupt_tail=False, bad_base=None, word_align=False):
    codes, limit, base, minb, maxb, syms = canonical(lengths)
    d = os.path.join(HW, dirname)
    os.makedirs(d, exist_ok=True)

    rows = []
    for L in range(1, MAXBITS + 1):
        lim = limit.get(L, 0)           # lengths the code does not use: a row that never matches
        bas = base.get(L, 0)
        if bad_base is not None and L == minb:
            bas = bad_base              # points past the symbol table: the decoder must raise err
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
        # must raise err and stop. Not in `expected`: the testbench stops at
        # nsym and checks err separately.
        bits.extend([1] * (MAXBITS + 4))

    if word_align:
        # Pad with the shortest code until the stream is a whole number of
        # 32-bit words, so the reader's buffer drains to exactly zero and `done`
        # can assert. The other sets leave byte padding behind, so done never
        # rises in them.
        short_sym = min(codes, key=lambda k: codes[k][1])
        sc, sl = codes[short_sym]
        while (len(bits) % 32) != 0:
            bits.extend((sc >> (sl - 1 - k)) & 1 for k in range(sl))
            expected.append((0, short_sym, sl))

    # Pad to a byte boundary with zeros. Those pad bits are a prefix of the
    # shortest code, so a decoder that ignores end-of-input reads a phantom
    # symbol out of them.
    while len(bits) % 8:
        bits.append(0)

    data = bytearray()
    for i in range(0, len(bits), 8):
        b = 0
        for k in range(8):
            b = (b << 1) | bits[i + k]
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


def main():
    # 1. Every code length from 1 to 20, including the all-ones 20-bit code.
    #    One symbol per length is a complete code only with a second symbol
    #    at the longest length.
    lengths = [(i, i) for i in range(1, MAXBITS + 1)] + [(MAXBITS + 1, MAXBITS)]
    seq = [s for s, _ in lengths] * 3
    emit("tb/vectors_lengths", lengths, seq)

    # 2. The same code, but the stream stops exactly on the final code with
    #    only byte padding after it: the decoder must stop cleanly, not invent
    #    a symbol out of the padding.
    emit("tb/vectors_eof", lengths, [s for s, _ in lengths])

    # 3. An incomplete code plus a tail of ones. With a complete code every bit
    #    pattern decodes to something and the error path is unreachable;
    #    lengths {1,2} leave the pattern "11" unassigned.
    emit("tb/vectors_err", [(0, 1), (1, 2)], [0, 1, 0, 1], corrupt_tail=True)

    # 4. A base row that points past the end of the symbol table: the decoder
    #    must raise err instead of reading out of range.
    emit("tb/vectors_badidx", [(0, 2), (1, 2), (2, 2), (3, 2)], [0, 1, 2, 3],
         bad_base=400)

    # 5. The stream ends short of a whole code. Three symbols take 7 bits; the
    #    testbench hands over a whole 32-bit word, so the 25 zero bits after
    #    them decode as twelve unchecked 2-bit codes (comparison stops at nsym)
    #    and the one bit left is shorter than any code: "UNDERRUN at symbol 15".
    emit("tb/vectors_underrun", [(0, 2), (1, 2), (2, 2), (3, 3), (4, 3)],
         [0, 1, 3])

    # 6. A whole number of 32-bit words, so the buffer drains to zero and
    #    `done` asserts.
    emit("tb/vectors_drain", [(i, i) for i in range(1, 5)] + [(5, 4)],
         [1, 2, 3, 4, 5] * 4, word_align=True)


if __name__ == "__main__":
    main()
