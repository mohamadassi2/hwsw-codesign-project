# Mutation testing the testbench

A testbench that cannot fail proves nothing. `tb/mutate.sh` injects one bug at
a time into the RTL, runs the real simulation suite (`make sim_all`) on a
scratch copy, and records whether the suite caught it.

    cd hw && tb/mutate.sh

## Why the suite is `sim_all` and not `sim`

`make sim` runs one stimulus: the real bzip2 block taken from the benchmark
input. That block is well formed, uses only code lengths 2..15, never runs out
of input mid-code, never presents a code that matches nothing, and never
stalls the consumer. Eight of the mutations below pass it unnoticed.

That is a property of the stimulus, not of the design, and it is why the
directed vector sets exist. `hw/tb/gen_synth_vectors.py` builds four small
streams that reach the corners the benchmark cannot:

| set | what it forces |
|---|---|
| `vectors_lengths` | every code length 1..20, including the all-ones 20-bit code |
| `vectors_eof` | the stream ends exactly on a code boundary |
| `vectors_err` | an incomplete code, so some bit pattern matches nothing |
| `vectors_badidx` | a table whose base row points past the symbol table |
| `vectors_underrun` | the stream ends one bit short of the shortest code |

`make sim_bp` reruns the real block with `out_ready` and `in_valid` gated
pseudo-randomly, which is what makes the handshakes testable at all.

## Result: 16 of 18 killed, 2 equivalent

| # | mutation | verdict |
|---|---|---|
| 1 | symbol output driven to X | KILLED (148,271 errors) |
| 2 | `sym_valid` stuck low | KILLED (timeout) |
| 3 | `hit` compare `<` changed to `<=` | KILLED (bit total wrong) |
| 4 | base adder off by one | KILLED (148,271 errors) |
| 5 | priority encoder direction reversed | KILLED (timeout) |
| 6 | barrel shift one bit short | KILLED (timeout) |
| 7 | end-of-input term dropped from `peek_valid` | KILLED (timeout) |
| 8 | bit-count underflow guard removed | **escapes - unreachable, see below** |
| 9 | `flush` tied low in the top | KILLED (timeout) |
| 10 | decode error no longer halts the engine | **escapes - equivalent, see below** |
| 11 | refill decided from the stale bit count | KILLED (throughput 148,275 > 148,273) |
| 12 | `level` output stuck at zero | KILLED (timeout) |
| 13 | comparators built only for lengths 2..15 | KILLED (timeout on `vectors_lengths`) |
| 14 | `consume` driven ungated | KILLED (timeout) |
| 15 | output backpressure ignored | KILLED (timeout under `+bp`) |
| 16 | symbol counter counts offers, not takes | KILLED (`sym_count` 296,617 vs 148,271) |
| 17 | short-code guard removed at end of stream | KILLED (consumed more bits than the buffer held) |
| 18 | symbol index range check removed | KILLED (a corrupt table returned a symbol) |

## The two that survive, and why that is the right answer

**8 - the bit reader's saturating `cnt_after`.** The decoder only emits a
symbol when its whole code is in the buffer (`enough` in
`huffman_decoder.sv`), so `consume` can never exceed `cnt_q` and the
saturation can never be reached from this design. It is kept as a guard on the
reader's own interface, for any other consumer that does not make that
promise. Unreachable code cannot be killed by any test, and listing it here is
the honest way to say so rather than deleting the guard to improve a score.

**10 - gating `fire` on the sticky error flag.** When no code length matches,
`found` is low, so `len` is zero and no bits are consumed. The decoder
therefore cannot advance past the offending bits whether or not the sticky
flag gates the enable, and `err_q` itself is set and never cleared in both
versions. The mutation is *equivalent*: it changes the text, not the
observable behaviour. The gate is kept because it states the halt explicitly
instead of leaving it to emerge from `found` being low.

Both are recorded rather than removed. A mutation score is only meaningful if
the survivors are explained.
