# Mutation testing the testbench

A testbench that cannot fail proves nothing. `tb/mutate.sh` injects one bug at
a time into the RTL, runs the real simulation suite (`make sim_all`) on a
scratch copy, and records whether the suite caught it.

    cd hw && tb/mutate.sh

## Why the suite is `sim_all`: against `make sim` alone, 12 of 20 escape

`make sim` runs one stimulus, the real bzip2 block from the benchmark input.
That block is well formed, uses only code lengths 2..15, never runs out of
input mid-code, never presents a code that matches nothing, and never stalls
the consumer - so twelve of the twenty bugs below pass it unnoticed
(reproduce with `SUITE=sim tb/mutate.sh`). That is a property of the
stimulus, not of the design, and it is why `hw/tb/gen_synth_vectors.py`
builds six small streams that reach the corners the benchmark cannot:

| set | what it forces |
|---|---|
| `vectors_lengths` | every code length 1..20, including the all-ones 20-bit code |
| `vectors_eof` | the stream ends exactly on a code boundary |
| `vectors_err` | an incomplete code, so some bit pattern matches nothing |
| `vectors_badidx` | a table whose base row points past the symbol table |
| `vectors_underrun` | the stream ends one bit short of the shortest code |
| `vectors_drain` | a whole number of 32-bit words, so the buffer drains to zero and `done` can assert |

`make sim_bp` reruns the real block with `out_ready` and `in_valid` gated
pseudo-randomly, which is what makes the handshakes testable at all.
`make sim_last_level` presents `LAST` as a level with producer bubbles, the way
a register-mapped host would, and the `drain` set is also run with `+bubble`,
which stalls the producer for 40 cycles just before it hands over the final
word. Mutations 19 and 20 exist only because those two runs do.

## Result with `make sim_all`: 19 of 20 killed, 1 unreachable

RTL fingerprint: 753aafda9d1118f1d90ed59159d783ab  (3 files under hw/rtl/)
The score below was measured on that RTL, in the course VM on 17 September
2026; the run is results/mutation_sweep_guest.log, and tb/mutate.sh prints the
fingerprint at the top of it. scripts/check_report_numbers.py recomputes the
fingerprint and fails if hw/rtl/ has changed since.

One line per injected bug, taken from results/mutation_sweep_guest.log. `make
sim_all` runs the six directed sets before the 148,271-symbol benchmark block,
so most bugs are caught by a small set first and the verdict names that run.
Five verdicts here were corrected against that log: rows 1, 4 and 11 had quoted
the benchmark run, and rows 6 and 17 had named the wrong failure - all from a
sweep made before the suite was reordered.

The verdict names what noticed it: `timeout` is the testbench watchdog, a set
name or plusarg (`+bp`, `+last_level +bubble`) names the run that failed, and a
number comes from an assertion in `tb_huffman.sv`. The directed sets are small,
so `63 errors on vectors_lengths` means every symbol of that 63-symbol set came
out wrong.

| # | mutation | verdict |
|---|---|---|
| 1 | symbol output driven to X | KILLED (63 errors on `vectors_lengths`) |
| 2 | `sym_valid` stuck low | KILLED (timeout) |
| 3 | `hit` compare `<` changed to `<=` | KILLED (bit total wrong) |
| 4 | base adder off by one | KILLED (63 errors on `vectors_lengths`) |
| 5 | priority encoder direction reversed | KILLED (timeout) |
| 6 | barrel shift one bit short | KILLED (bit total: consumed 63, software 690) |
| 7 | end-of-input term dropped from `peek_valid` | KILLED (timeout) |
| 8 | bit-count underflow guard removed | **escapes - unreachable, see below** |
| 9 | `flush` tied low in the top | KILLED (timeout) |
| 10 | decode error no longer halts the engine | KILLED (the engine kept going after err) |
| 11 | refill decided from the stale bit count | KILLED (throughput 67 cycles for 63 symbols) |
| 12 | `level` output stuck at zero | KILLED (timeout) |
| 13 | comparators built only for lengths 2..15 | KILLED (timeout on `vectors_lengths`) |
| 14 | `consume` driven ungated | KILLED (timeout) |
| 15 | output backpressure ignored | KILLED (timeout under `+bp`) |
| 16 | symbol counter counts offers, not takes | KILLED (`sym_count` 296,617 vs 148,271) |
| 17 | short-code guard removed at end of stream | KILLED (timeout on `vectors_underrun`) |
| 18 | symbol index range check removed | KILLED (a corrupt table returned a symbol) |
| 19 | end-of-input also flushed on a producer bubble | KILLED (`drain` under `+last_level +bubble`) |
| 20 | `done` ignores a symbol still waiting to be taken | KILLED (`drain`: done with symbols outstanding) |

## The one that survives, and why that is the right answer

**8 - the bit reader's saturating `cnt_after`.** The decoder only emits a
symbol when its whole code is in the buffer (`fits[L]` in
`huffman_decoder.sv`, folded into `hit[L]`), so `consume` can never exceed
`cnt_q` and the saturation can never be reached from this design. The guard
costs nothing and is kept on the reader's own interface, for any other
consumer that does not make that promise. Unreachable code cannot be killed by
any test, and listing it here is the honest way to say so rather than deleting
the guard to improve a score.

The halt-on-error mutation (10) used to survive too. It is caught now because
the directed error test keeps the engine enabled after `err` asserts and
requires that no further symbols or bits appear in the next hundred cycles -
without that, "a decode error halts the decoder" was a claim no test made.
