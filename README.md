# pyperformance: optimization, analysis and a Huffman-decode accelerator

Final project for *HW/SW Co-design* (00460882, Technion).
Mohamad Assi (212343594), Ido Sefi (208008698).

Two benchmarks from the pyperformance suite, **pyflate** and **mdp**, profiled
with `perf record` as root in the setup guide's form, py-spy flame graphs and
`perf stat` counters, optimized in pure Python with byte-identical output, and,
for pyflate, a hardware accelerator for the canonical-Huffman symbol decoder,
written in SystemVerilog and verified against the benchmark's real compressed
block.

| | baseline | optimized | improvement | output |
|---|---|---|---|---|
| pyflate | 1.141 s | 487 ms | **2.34× — 57.3% less time** | byte-identical, md5 `afa004a6…` |
| mdp     | 5.098 s | 1.309 s | **3.90× — 74.3% less time** | bit-identical result |

Measured inside the course QEMU/KVM guest (Ubuntu 22.04, one vCPU, Xeon
E5-2630 v3) by the two scripts below; the raw files are in `results/`, and
`scripts/check_all.sh` recomputes every figure in this table, the reports and
the slides from them. Both improvements are far above the 7% the assignment
asks for.

## Start here

1. `report_pyflate.txt`, `report_mdp.txt` - the two reports, sections in the assignment's order
2. `docs/presentation.html` - the deck (open in a browser); `docs/presentation_outline.md` is the speaker guide
3. `benchmarks/<b>/run_benchmark_opt.py` - the optimized code; `run_benchmark.py` beside it is the untouched original
4. `hw/rtl/huffman_decoder.sv` - the accelerator; `docs/hw_sw_interface.md` - its register map
5. `results/` - the course-VM measurements every number above comes from

What we run live at the presentation (about a minute in total, standard library only):

    python3 scripts/local_check.py                   # both benchmarks: same output as the original, and the speedup
    (cd hw && make sim)                              # the RTL decodes the benchmark's real block: 148271 symbols, 0 errors, PASS
    python3 scripts/check_report_numbers.py | head -1 # every figure in the reports recomputed from results/: PASS <n>   FAIL 0

That `make sim` line is line 7 of `results/rtl_sim_guest.log` - the same testbench
run inside the course VM. `local_check.py` needs no venv (it supplies its own
pyperf stand-in) and prints this machine's speedup, not the VM's; on CPython
3.12+ its mdp line explains a one-ulp difference, see report_mdp.txt section 3.

## Layout

```
report_pyflate.txt, report_mdp.txt   the two reports the assignment asks for
script_pyflate.sh,  script_mdp.sh    the two execution scripts (env setup, baseline,
                                     perf + flame graphs, optimized run, comparison)
prompt.txt                           the AI prompts used during the project
THIRD-PARTY.md                       what in here is not ours, and under what terms
benchmarks/<b>/run_benchmark.py      the benchmark exactly as pyperformance ships it
benchmarks/<b>/run_benchmark_opt.py  our optimized version, same pyperf runner
benchmarks/pyflate/data/             the benchmark input (interpreter.tar.bz2)
scripts/check_all.sh                 the one command to run live: gates (1)-(3) below in order, then the drift line (4)
scripts/local_check.py               (1) optimized == original: pyflate byte-for-byte, mdp to the last bit, plus a rough speedup
scripts/check_report_numbers.py      (2) every figure the reports quote recomputes from results/, or it fails
scripts/check_deck_numbers.py        (3) the same for the slides, the block diagram and this README
scripts/compare_runs.py              (4) drift between the shipped run and the independent rerun in results/reproducibility/ (printed, not gated)
scripts/focus_folded.py              called by both script_*.sh: re-roots py-spy stacks at the benchmark function
scripts/table_stats.py               called by script_pyflate.sh: what the shipped table scan costs on this input
scripts/ablation.py                  called by script_pyflate.sh: what each pyflate optimization is worth on its own
scripts/summarize_results.py         prints results/ as the tables the reports quote (read-only)
scripts/fill_reports.py              rewrites section 4.1 of each report and the Amdahl line in pyflate 5.6 from results/ (already run for the shipped run; gate 2 verifies it)
scripts/stamp_results.py             refreshes results/RUN_ID.txt and results/CODE_ID.txt after a re-measure
scripts/cprofile_shares.py           prints the per-function shares the reports' cProfile tables quote, from results/<b>/cprofile_*.txt (read-only)
hw/rtl/*.sv                          the accelerator: bit reader, decoder, top
hw/tb/tb_huffman.sv                  self-checking testbench on the real benchmark block
hw/tb/mutate.sh, hw/tb/MUTATIONS.md  mutation testing: 20 injected bugs, 19 killed, the survivor explained
hw/tb/synth_report.py                turns a yosys run into docs/synthesis_yosys.txt
hw/gen_vectors.py                    dumps tables / bit stream / expected symbols from the software
hw/synth.ys                          the yosys script `make synth` runs
hw/Makefile                          `make vectors`, `make sim`, `make sim_all`, `make synth`
docs/presentation.html               the project presentation (open in a browser)
docs/presentation_outline.md         the slide-by-slide plan behind it
docs/hw_sw_interface.md              register map, data flow, the one software change
docs/huffman_accel_block_diagram.svg block diagram
docs/synthesis_yosys.txt             generic synthesis figures (cells, flops, memories, longest path)
results/                             flame graphs, perf reports, pyperf JSON and comparison tables,
                                     and rtl_sim_guest.log: the accelerator testbench run inside the course VM
results/reproducibility/             an independent from-scratch rerun in the guest, and the drift against it
```

## Reproducing the measurements (course VM)

Inside the course QEMU/KVM guest, as root, with network:

```bash
git clone https://github.com/mohamadassi2/hwsw-codesign-project.git && cd hwsw-codesign-project
./script_pyflate.sh      # ~10 min
./script_mdp.sh          # ~10 min
```

Each script replaces `results/<benchmark>/`. The reports and slides quote the
committed run (`results/RUN_ID.txt` fingerprints those measurement files,
`results/CODE_ID.txt` the code that produced them), so after a rerun
`scripts/check_all.sh` lists every figure that moved; `git checkout -- results/`
restores the shipped evidence.

Both scripts have the same shape. The `=== ... ===` headings they print follow
the numbered sections of the script itself (`# ---- 0. environment` through
`# ---- 4b. contention`; `results/<b>/trace.log` keeps the same sequence as
`+ log ...` lines):

0. environment: a venv with pyperf, pyperformance and py-spy; FlameGraph; the
   two `perf` sysctls the guest needs (`kptr_restrict=0`,
   `perf_event_paranoid=-1`: without them `perf report` shows no kernel symbols
   and empty call graphs); then a probe of which `perf` sampling events
   actually fire in this guest (`pmu_diagnosis.txt`, `perf_events_probe.txt`:
   the hardware `cycles` event never samples - PMI stays at 0 across a record -
   while the software clocks `cpu-clock` and `task-clock` do).
1. baseline: `pyperformance run --bench <b>` itself
   (`<b>_pyperformance_baseline.json`), then the vendored copy through the same
   pyperf runner (`<b>_base.json`) - that is what we diff against.
2. profile the baseline: `perf record -F 999 -g` as root on `cpu-clock`, in
   the guide's form under `python3-dbg` (`perf_report_base_dbg.txt`) and, for
   cleaner attribution, on the benchmark worker under the release interpreter
   with `-e cpu-clock -F 997 -g` (`perf_top_base.txt`,
   `flame_<b>_base_perf.svg`); then `py-spy` flame graphs, re-rooted at the
   benchmark function by `scripts/focus_folded.py`
   (`flame_<b>_base_{pyspy,focus}.svg`). perf names the interpreter's C
   functions but no Python function (CPython 3.10 has no perf trampoline), so
   the Python-level view is py-spy's; report_pyflate.txt section 2 has the
   detail.
3. optimized: the same runner and the same profiles on `run_benchmark_opt.py`
   (`<b>_opt.json`, `perf_report_opt_dbg.txt`, `perf_top_opt.txt`,
   `flame_<b>_opt_{perf,pyspy,focus}.svg`), then cProfile on both for the
   per-function shares the reports quote (`cprofile_{base,opt}.txt`).
   pyflate only: `scripts/table_stats.py` (what the shipped table scan costs on
   this input, `table_stats.txt`) and `scripts/ablation.py` (what each
   optimization is worth on its own, `ablation.txt`).
4. compare: `pyperf compare_to` (`compare_<b>.txt`), `perf stat -r 3` on both
   (`perfstat_{base,opt}.txt`), and a contention check that marks the
   wall-clock figures untrustworthy if the guest did not have the whole core
   (`contention.txt`).

### Guest DNS fix

QEMU's user-mode NAT forwards the guest's DNS queries to the host's resolver.
When the host runs systemd-resolved, that is the 127.0.0.53 stub, which the
NAT cannot reach: names fail in the guest while plain TCP works, so `apt` and
`pip` silently die. If `pypi.org` does not resolve, the scripts rewrite
`/etc/resolv.conf` once to Technion's resolvers plus 8.8.8.8, keep the old
file as `/etc/resolv.conf.bak`, and say so. If a script still stops with
`network: offline`, apply the same fix by hand and re-run it:

```bash
printf 'nameserver 132.68.39.127\nnameserver 132.68.32.5\nnameserver 8.8.8.8\n' > /etc/resolv.conf
```

## Showing the change live (any Python 3.8+, no packages needed)

```bash
python3 scripts/local_check.py all 1     # both benchmarks, one timed repetition each, a few seconds
diff -u benchmarks/pyflate/run_benchmark.py benchmarks/pyflate/run_benchmark_opt.py
diff -u benchmarks/mdp/run_benchmark.py benchmarks/mdp/run_benchmark_opt.py
```

The first line runs each benchmark's own correctness gate on the optimized
code, checks it against the baseline (pyflate byte-for-byte, mdp to the last
bit) and prints a rough local speedup; the speedups quoted in this README and
the reports are the VM's, from `results/`. Without `all 1` it runs five
repetitions. The two diffs are the whole optimization (pyflate's is the
longer); section 3 of each report walks them change by change - 3.1-3.5 for
pyflate, 3.1-3.2 for mdp - and that is the order to read them in.

## Hardware

```bash
cd hw
make vectors     # plain python3, no packages needed; writes tb/vectors/
make sim         # the real bzip2 block, Icarus Verilog (iverilog -g2012)
make sim_all     # the above plus backpressure, level-LAST, and six directed streams
make synth       # regenerates docs/synthesis_yosys.txt
tb/mutate.sh     # ~25 min: injects 20 bugs one at a time, reports which the suite catches
ONLY=comparators tb/mutate.sh   # just one of them, live: control passes, then vectors_lengths kills it
```

`make sim_all` is the one to run if you only run one: `sim` alone passes on
twelve of those twenty injected bugs, because a single well-formed stream never
reaches end-of-input, an unmatchable code, a stalled consumer or the extreme
code lengths. `hw/tb/MUTATIONS.md` records the whole table.

Expected: `decoded 148271 symbols in 148272 cycles (1.000 symbols/cycle), 0 errors` / `PASS`.
Synthesis figures in `docs/synthesis_yosys.txt` are regenerated by `make synth`,
which runs `hw/synth.ys` (`proc; flatten; opt; memory -nomap; techmap; abc;
opt_clean; stat; ltp`). `memory -nomap` is what keeps the tables as memories;
the second, 49,804-cell figure in that file is the same design synthesised
again with every table flattened into logic.

## Commit history

The history is meant to be read: baseline vendored → pyflate optimization →
mdp optimization → scripts → RTL + testbench → docs/synthesis. Each commit
message states what was measured and why the change was made.
