# Speaker guide

The deck is `docs/presentation.html` — arrow keys or scroll, Cmd-P prints one
slide per page. This file is the talk track, not a spec: for each slide, why
it is there and the one sentence that has to land. Everything numeric on the
slides is recomputed by `scripts/check_deck_numbers.py`, so nothing here needs
to be defended from memory.

## Shape

Three acts. Each benchmark is finished before the next one starts, and the
hardware arrives only after the software has run out of room.

| slides | act | minutes |
|---|---|---|
| 1-3 | setup: what we chose, how we measured | 3 |
| 4-9 | **pyflate** | 6 |
| 10-14 | **mdp** | 4 |
| 15 | what is left to accelerate — the hinge | 1 |
| 16-21 | **the accelerator** | 6 |
| 22 | conclusions | 1 |
| 23 | questions — backup, do not narrate | — |

The minutes above are the target pacing and come to 21, which is the slot. The
words on the slides do not fill it on their own: about 1,300 words of prose,
plus ten code blocks and tables that are pointed at rather than read, is
roughly thirteen minutes read aloud, and the three live commands add two. The
gap is the part you say and the slide does not — why each change was the right one,
what the profile looked like before you believed it, what you would do next.
Treat the slides as the floor of the talk, not the script; a slide you can
only read is a slide you have not rehearsed.

Do not rush slide 15. It is the shortest slide and the one that makes the
second half legitimate.

If you are running long, the compressible slides are 3 (method), 8 (the
ablation table can be one sentence) and 20 (cost — the SRAM argument can
become "ask me why only the symbol table is SRAM"). Do not compress 7, 15
or 19. If you are running short, slide 19 rewards it most: the testbench
that passed on a decoder emitting nothing but X is the best story here.

## Live demo (three commands, under half a minute of running)

Have a terminal open in the repository before the talk. None of them needs
the venv; the second needs Icarus Verilog (`brew install icarus-verilog` /
`apt install iverilog`). They write only to ignored directories, so nothing in
the tree changes.

**On slide 13 or 14 — both benchmarks still produce the original answer, about
10 s:**

    python3 scripts/local_check.py all 2

Point at two lines: `pyflate: output identical to baseline (399360 bytes, md5
afa004a6…)` and `mdp: optimized result is bit-identical to the baseline`. The
line between them — baseline and optimized agreeing on eight further bzip2
streams — is the answer to "did you test more than one input?". The speedup it
prints is this laptop's, not the VM's; say so before anyone asks, because the
slides quote the VM. On CPython 3.12 or newer the mdp line instead reports a
last-bit (about one ulp) difference and names report_mdp.txt section 3 — that
is the sum() caveat we documented, not a failure.

**On slide 19 — the accelerator on the real block, about 8 s:**

    cd hw && make vectors && make sim

`make vectors` comes first because the vectors are generated from the optimized
decoder, not committed. The run ends with `decoded 148271 symbols in 148272
cycles (1.000 symbols/cycle), 0 errors`, then the bits-per-symbol line, then
`PASS` (a `$finish` line follows it). Then open `hw/tb/MUTATIONS.md` for the
table; do not run `tb/mutate.sh` live — it re-runs the whole `sim_all` suite
once per mutation on a scratch copy and will not finish inside the slot. If the
laptop has no simulator, `cat results/rtl_sim_guest.log` is the same run inside
the course VM.

**On slide 22 — the slides recompute themselves, instantly:**

    python3 scripts/check_deck_numbers.py | head -1

prints `PASS <n>   FAIL 0` (`head`, not `tail`: the summary is the first line).
`scripts/check_report_numbers.py | head -1` does the same for the reports. Do
not run `scripts/check_all.sh` live — it re-runs both benchmarks and takes
minutes; keep it for the reproducibility question at the end.

If asked for the profile, open `results/pyflate/flame_pyflate_base_focus.svg`
in the browser and click `find_next_symbol` — the SVG zooms.

## Act 0 — setup

**1. Title.** Say the two verbs: profile and optimize two benchmarks, then
design hardware for the one part that earns it. *Land:* every number in this
talk was measured inside the course VM.

**2. Choosing the benchmarks.** The table is three rows — pyflate, mdp, and
the kind we rejected (nbody, raytrace); point at the last column, the hardware
story, and do not read the rows.
*Land:* we needed the hot code to be the benchmark's own, so that an
optimization is ours and not a library swap — and the output had to stay
identical, byte-for-byte in pyflate and bit-for-bit in mdp. That constraint is
what makes the speedups mean anything.

**3. Method.** py-spy for the flame graphs, cProfile for exact counts, perf
stat for why, and `perf record` as root in the guide's form. *Land:* the
hardware `cycles` event never samples in this guest — PMI in
`/proc/interrupts` stays at 0 across a record — so `perf record -F 999 -g`
runs on `cpu-clock`. It names the interpreter's C functions
(`_PyEval_EvalFrameDefault` alone is 39% of the baseline pyflate worker) and
no Python function, because Python 3.10 has no perf trampoline: perf answers
"how much is interpreter overhead", py-spy answers "which Python function".
Saying what did not work here costs ten seconds and buys credibility for the
rest.

## Act 1 — pyflate (slides 4-9)

**4. Divider.** One line: a bzip2 block decoded in pure Python — 148,271
Huffman symbols, six tables, codes 2 to 15 bits.

**5. The workload.** Five stages, all of them spelled out in the benchmark
file. *Land:* the algorithm is what we measure and what we are allowed to
change; the gate is the same 399,360 bytes, md5-checked on every run.

**6. Baseline profile.** Point at the `find_next_symbol` tower. *Land:* 15.2%
self, 48.8% cumulative — nearly half the run inside one function.

**7. The problem.** This is the slide the whole talk turns on, and the honest
version is better than the obvious one. The obvious story is "it scans the
whole table"; our own instrumentation says otherwise - 6.0 entries per symbol
on average, 147 at worst, because short codes carry most of the symbols
(`results/pyflate/table_stats.txt`). The cost is the 2.3 `snoopbits()` calls
per symbol around the scan, each a Python method call and a mask, 148,271
times over. Say that: it is the same interpreter overhead the whole talk is
about, and it is why the fix is one peek rather than a faster walk.
*Land:* these are **canonical** Huffman codes - within one length the codes
are consecutive integers, so an entire length collapses to two numbers.

If asked "so the scan was not the problem?" - correct, and report_pyflate.txt
section 2 says so in those words. The accelerator removes both.

**8. The fix.** `limit[L]` and `base[L]`: one compare per length instead of
one per entry. Then the ablation — the three separable changes reverted in
turn, md5-checked, re-timed in the VM (3.2 and 3.5 are woven through the decode
loop and cannot be reverted alone; what they are worth is the remainder). *Land:* the algorithmic change is the
*smallest* of the three that matter (+85.3 ms, against +163.1 ms for
move-to-front and +161.8 ms for the RLE regex). That is the honest reading, and
it is also the setup for the hardware: what justifies an accelerator is the
half of the run that is still interpreter work after all five fixes.

*If asked to see the code:* `benchmarks/pyflate/run_benchmark_opt.py` line 291, `find_next_symbol`, next to `benchmarks/pyflate/run_benchmark.py` line 224; the `limit`/`base` arrays it reads are built in `_build_canonical` at line 264.

**9. Result.** 1.141 s → 487 ms, 2.34×, n=30; pyperf's own ± is 3% on the
baseline and 6% on the optimized run. *Land:* IPC barely moved, 2.58 → 2.62.
The processor was already running well — it was running too much. We removed
16.0 billion instructions, not stalls and not cache misses.

## Act 2 — mdp (slides 10-14)

**10. Divider.** Value iteration over a battle state graph — where the cost
turned out not to be the mathematics.

**11. The workload.** Upper and lower bounds iterated to convergence over
4,823 states, damage distributions built from `Fraction` so the arithmetic is
exact. *Land:* that sets a hard bar — preserve not just the answer but the
exact sequence of floating-point additions that produced it.

**12. Baseline profile.** *Land:* the two tallest towers are generator
expressions inside the sweep. Every successor lookup went through a dict keyed
by a nested namedtuple, re-hashing the same keys millions of times; and
`getCritDist` ran 3,659 times with three distinct arguments.

**13. The fix.** Index the graph once, then sweep flat arrays; memoize
`getCritDist`. *Land:* the additions still happen in the original order, which
is what makes bit-identity possible — both versions run in one process and
their results are compared directly: same double, 0.8987358988699915,
difference exactly zero.

*If asked to see the code:* `benchmarks/mdp/run_benchmark_opt.py` line 291, the sweep, next to `benchmarks/mdp/run_benchmark.py` line 224 — the same loop with `dmin[sp]` replaced by `vmin[i]`; the cache is `getCritDist` at line 55. `python3 scripts/local_check.py all 1` runs both correctness gates in a few seconds (no venv needed). On CPython 3.12+ the mdp line reports a one-ulp difference and says why; the VM's 3.10 is bit-identical — report_mdp.txt section 3.

**14. Result.** 5.098 s → 1.309 s, 3.90×. *Land:* same story as pyflate — IPC
flat, instruction count down 3.8×. And say the negative result out loud: no
hardware for mdp. One accelerator for one benchmark per the TA's ruling, and
the sweep would map onto a MAC array cleanly enough - it is just too small a
share of a 1.3 s run to be worth it, and what remains is exact-Fraction graph
building, not a datapath. (report_mdp.txt section 5 makes that case; do not
say "not bit-serial enough" - a different reason, and a weaker one.)

## The hinge (slide 15)

**15. What is left to accelerate.** Short slide, slow delivery. Two things
remain in the optimized pyflate run: 52% is Huffman decode and bit extraction
— a peek, a few integer compares, a shift, still paying a Python call per
symbol. 25% is the inverse BWT — one dependent memory access per byte through
400 KB. *Land:* only the first is a datapath problem. That sentence is what
chooses the accelerator, and it is also the answer to "why not the BWT?"
before anyone asks.

## Act 3 — the accelerator (slides 16-21)

**16. Divider.** Twenty comparators, a priority encoder, one symbol per clock.

**17. Datapath.** Walk the diagram left to right, once, in the RTL's own
names. (1) `bitreader` holds up to 64 bits left-aligned and presents the top
20 as `peek` every cycle. (2) Twenty comparators test the top L bits of `peek`
against `limit_r[tsel][L]`, every length at the same time — `hit[20:1]`. (3)
The priority encoder picks the shortest hit, `len_c`, and that is `len`; the
same `len` goes straight back to the bit reader as `consume` (`.consume(len)`
in `huffman_accel_top.sv`). (4) `base_r[tsel][len_c] + code[len_c]` indexes
the symbol table, and `sym` comes out one clock later with `sym_valid`.
*Land:* the matched length drives the barrel shifter in the *same* cycle,
which is why the next symbol is ready on the next clock — one symbol per clock
by construction, not by luck.
*If asked to show it:* `cd hw && make sim` prints `decoded 148271 symbols in
148272 cycles (1.000 symbols/cycle), 0 errors` and `PASS` — the same lines as
`results/rtl_sim_guest.log`.

**18. Interface.** Memory-mapped registers - say that these are the proposed
wrapper and that the RTL exposes the raw ports the testbench drives, because it
is the first thing a hardware examiner will look for. Then: one function changes,
`decode_huffman_block` calls the driver instead of its symbol loop, and
`bzip2_main` and every caller are untouched — lecture 5's first rule, do not make users change their
code. *Land:* then the limit, volunteered: the selector list is supplied by
the host on TSEL rather than sequenced in hardware, and a production version
puts a mod-50 counter and a small FIFO inside the block. Saying where you
stopped is worth more than implying you did not stop.

**19. Verification.** 148,271 / 148,271 symbols, 0 errors, 148,272 cycles,
1.000 symbol/clock. Then the part that is actually interesting: *the testbench
used to pass on a decoder that emitted nothing but X.* Mutation testing found
it — twenty bugs injected one at a time, and against the benchmark block alone
twelve went unnoticed. *Land:* that was a weakness of one well-formed
stimulus, not of the design; the stimulus grew to six directed streams plus
three throttled runs, and 19 of 20 are now caught. The survivor is an
unreachable guard — reported, not removed.

**20. Cost.** 18,796 cells (5,441 flops) plus 13.9 kbit of symbol SRAM.
*Land, if asked or if time allows:* `limit` is compared at all twenty lengths
in one cycle, so it would need twenty read ports — no SRAM macro has those,
and it is counted as the register file it is. Flattening the symbol table into
logic costs 49,804 cells; a comparator-free flat table would need 2^20 entries
per bank. Say the caveat: frequency is inferred from a 98-level topological
path, not static timing — no cell library, no place-and-route.

**21. Expected gain.** Walk the subtraction, do not just show it: 487 ms
optimized, 249 ms of it in `find_next_symbol`, the same work at 200 MHz is
0.74 ms plus about 0.6 ms of DMA setup and transfers — so about 240 ms. Say
that 200 MHz is an assumption this RTL does not reach, before anyone asks, and
that halving it moves the answer by under a millisecond: the bound is Amdahl's,
not the clock's. 2.0× over
the optimized run, 4.8× over the shipped benchmark, and ~4,000 CPU cycles per
symbol become one clock. *Land:* Amdahl sets the ceiling — the inverse BWT and
the remaining interpreter overhead are the floor. That is a bound, not a
headline.

## Close

**22. Conclusions.** Four lines, in order: algorithm first (both speedups came
from removing work, IPC never moved); then interpreter overhead; then hardware
only for what is bit-serial; and not for what is memory-bound. *Land the
fifth:* measure in the environment you claim — including the things that did
not work there.

**23. Questions.** Backup slide. Do not narrate it; leave it up while taking
questions. It already answers: why not `bz2`, why mdp is bit-identical, why
not the BWT, corrupt streams, the table switch, and what sets the clock.

## Questions the slide does not cover

- **"Is 200 MHz realistic?"** Not from this RTL, and say so first. The 98-level
  path runs from `tsel` through the table lookups to the error flag's enable,
  and it has to close every clock. It is not an outlier either: cut that one
  condition and ltp still reports 97 levels, ending at `sym_valid`. So 200 MHz
  is out of reach for this RTL, and a pipeline stage inside the compare tree is
  not the way to it: that tree sits in a feedback loop - peek, compare, length,
  shift, peek - so a register there gives one symbol every two cycles. Raising the clock
  means speculating over candidate bit offsets, which costs area.
  report_pyflate.txt 5.7 says exactly that. What simulation proves is
  throughput, one symbol per cycle; frequency is an estimate, and 5.7 also
  shows how little turns on it (halving the clock moves the projected run by
  under a millisecond).
- **"Why one accelerator and not one per benchmark?"** The TA's ruling, and
  slide 14 gives the technical reason mdp would not have earned one anyway.
- **"How do you know the optimized pyflate is still correct?"** md5 of all
  399,360 output bytes on every run, and the ablation runs are md5-checked
  individually too.
- **"Did you try PyPy / a C extension / Cython?"** That replaces the benchmark
  instead of optimizing the code under test.
- **"How much of this is reproducible?"** `scripts/check_all.sh` — every report and
  slide figure recomputed from `results/`, plus a RUN_ID that
  ties the documents to the measurement files and a CODE_ID that ties the
  measurements to the code that produced them.
- **"Did any perf sampling work?"** Yes, as root. The hardware `cycles`
  event never samples here — PMI stays at 0 in
  `results/pyflate/pmu_diagnosis.txt` — but the software clocks do:
  `cpu-clock` 3,645 and `task-clock` 3,496 samples in
  `results/pyflate/perf_events_probe.txt`. So the scripts record
  `perf record -F 999 -g` on `cpu-clock`, as the guide does:
  `results/pyflate/perf_report_base_dbg.txt` (131K samples under
  `python3-dbg`) and, on the worker under the release interpreter,
  `perf_top_base.txt` and `flame_pyflate_base_perf.svg`. An earlier version
  of the scripts reported no working sampling event; that was a bug in the
  probe (`head -1` under `pipefail` killed `perf script` with SIGPIPE), not
  the guest. What perf shows is the interpreter's C frames, no Python names —
  report section 2.
