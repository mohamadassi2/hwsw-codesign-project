# pyperformance: optimization, analysis and a Huffman-decode accelerator

Final project for *HW/SW Co-design* (00460882, Technion).
Mohamad Assi (212343594), Ido Sefi (208008698).

Two benchmarks from the pyperformance suite, **pyflate** and **mdp**, profiled
with `perf`/flame graphs, optimized in pure Python with byte-identical output,
and, for pyflate, a hardware accelerator for the canonical-Huffman symbol
decoder, written in SystemVerilog and verified against the benchmark's real
compressed block.

| | baseline | optimized | improvement | output |
|---|---|---|---|---|
| pyflate | 1.129 s | 477.2 ms | **2.37× — 57.7% less time** | byte-identical, md5 `afa004a6…` |
| mdp     | 4.997 s | 1.303 s | **3.83× — 73.9% less time** | bit-identical result |

Measured inside the course QEMU/KVM guest (Ubuntu 22.04, one vCPU, Xeon
E5-2630 v3) by the two scripts below; the raw files are in `results/`, and
`scripts/check_all.sh` recomputes every figure in this table, the reports and
the slides from them. Both improvements are far above the 7% the assignment
asks for.

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
scripts/check_all.sh                 runs all three gates below in order
scripts/local_check.py               in-process correctness + speed check, baseline vs optimized
scripts/summarize_results.py         turns results/ into the tables quoted in the reports
scripts/fill_reports.py              writes the measured figures into the two reports
scripts/check_report_numbers.py      recomputes every figure the reports quote, and fails on a mismatch
scripts/check_deck_numbers.py        the same gate for the slides, the diagram and this README
scripts/compare_runs.py              drift between two independent runs of the same benchmark
scripts/focus_folded.py              re-roots py-spy stacks at the benchmark function
scripts/table_stats.py               what the shipped pyflate table scan costs on this input
scripts/ablation.py                  what each pyflate optimization is worth on its own
scripts/cprofile_shares.py           per-function shares recomputed from the cProfile artifacts
scripts/record_reproduction.py       captures a from-scratch guest rerun into results/reproducibility/
hw/rtl/*.sv                          the accelerator: bit reader, decoder, top
hw/tb/tb_huffman.sv                  self-checking testbench on the real benchmark block
hw/tb/mutate.sh, hw/tb/MUTATIONS.md  mutation testing: six injected bugs, and that the testbench kills each
hw/tb/synth_report.py                turns a yosys run into docs/synthesis_yosys.txt
hw/gen_vectors.py                    dumps tables / bit stream / expected symbols from the software
hw/synth.ys                          the yosys script `make synth` runs
hw/Makefile                          `make sim`, `make vectors`, `make synth`
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

Each script clears `results/<benchmark>/` before it starts, so running one
replaces the evidence committed here. That also means the reports and slides,
which quote the committed run, will no longer agree with `results/` - and
`scripts/check_all.sh` will say so and list every figure that moved. That is the
checkers working, not a broken submission: they compare the documents against
whatever is in `results/` now. `results/RUN_ID.txt` fingerprints the run the
documents quote, and `check_all.sh` warns before it starts if they differ.

To check the submission as shipped: `git checkout -- results/`.

Each script installs its own venv (pyperf, pyperformance, py-spy) and
FlameGraph, sets the two `perf` sysctls the guest needs
(`kptr_restrict=0`, `perf_event_paranoid=-1`: without them `perf report`
shows no kernel symbols and empty call graphs), then runs:

1. the baseline through `pyperformance run --bench <b>` itself,
2. the baseline and the optimized version through the same pyperf runner
   (`benchmarks/<b>/run_benchmark*.py -o ….json`),
3. `py-spy` flame graphs on both (the scripts also attempt `perf record`, which
   collects nothing in this guest - see report_pyflate.txt section 2),
4. `pyperf compare_to` and `perf stat -r 3` for both.

Outputs: `results/<b>/<b>_base.json`, `<b>_opt.json`, `compare_<b>.txt`,
`flame_<b>_{base,opt}_{focus,pyspy}.svg`, `perf_top_{base,opt}.txt`,
`perfstat_{base,opt}.txt`.

## Quick local check (any machine with Python 3.8+)

```bash
python3 -m venv venv && venv/bin/pip install pyperf
venv/bin/python scripts/local_check.py          # both benchmarks, 5 repetitions
```

Prints the correctness gate of each benchmark on the optimized code and a
rough speedup.

## Hardware

```bash
cd hw
make vectors     # plain python3, no packages needed; writes tb/vectors/
make sim         # the real bzip2 block, Icarus Verilog (iverilog -g2012)
make sim_all     # the above plus backpressure, level-LAST, and five directed streams
make synth       # regenerates docs/synthesis_yosys.txt
tb/mutate.sh     # injects 20 bugs one at a time and reports which the suite catches
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

To re-verify everything from the shipped files in one command (the reports quote the
committed run in `results/`; after rerunning the scripts, regenerate the report blocks
with `scripts/fill_reports.py` before checking, or restore the committed set):

    scripts/check_all.sh

To confirm the hardware testbench can actually fail (mutation test, ~25 min):

    cd hw && tb/mutate.sh
