# pyperformance: optimization, analysis and a Huffman-decode accelerator

Final project for *HW/SW Co-design* (00460882, Technion).
Mohamad Assi (212343594), Ido Sefi (208008698).

Two benchmarks from the pyperformance suite, **pyflate** and **mdp**, profiled
with `perf`/flame graphs, optimized in pure Python with byte-identical output,
and: for pyflate: a hardware accelerator for the canonical-Huffman symbol
decoder, written in SystemVerilog and verified against the benchmark's real
compressed block.

| | baseline | optimized | speedup | output |
|---|---|---|---|---|
| pyflate | see `results/pyflate/` | | **2.2×** (dev machine) | byte-identical, md5 `afa004a6…` |
| mdp     | see `results/mdp/`     | | **3.9×** (dev machine) | bit-identical result |

The VM measurements (the ones the reports quote) are produced by the two
scripts below and land in `results/`.

## Layout

```
report_pyflate.txt, report_mdp.txt   the two reports the assignment asks for
script_pyflate.sh,  script_mdp.sh    the two execution scripts (env setup, baseline,
                                     perf + flame graphs, optimized run, comparison)
prompt.txt                           the AI prompts used during the project
benchmarks/<b>/run_benchmark.py      the benchmark exactly as pyperformance ships it
benchmarks/<b>/run_benchmark_opt.py  our optimized version, same pyperf runner
benchmarks/pyflate/data/             the benchmark input (interpreter.tar.bz2)
scripts/local_check.py               in-process correctness + speed check, baseline vs optimized
hw/rtl/*.sv                          the accelerator: bit reader, decoder, top
hw/tb/tb_huffman.sv                  self-checking testbench on the real benchmark block
hw/gen_vectors.py                    dumps tables / bit stream / expected symbols from the software
hw/Makefile                          `make sim`, `make vectors`
docs/hw_sw_interface.md              register map, data flow, the one software change
docs/huffman_accel_block_diagram.svg block diagram
docs/synthesis_yosys.txt             generic synthesis figures (cells, flops, memories, longest path)
results/                             everything the scripts write (created at run time)
```

## Reproducing the measurements (course VM)

Inside the course QEMU/KVM guest, as root, with network:

```bash
git clone <this repo> && cd <repo>
./script_pyflate.sh      # ~10 min
./script_mdp.sh          # ~10 min
```

Each script installs its own venv (pyperf, pyperformance, py-spy) and
FlameGraph, sets the two `perf` sysctls the guest needs
(`kptr_restrict=0`, `perf_event_paranoid=-1`: without them `perf report`
shows no kernel symbols and empty call graphs), then runs:

1. the baseline through `pyperformance run --bench <b>` itself,
2. the baseline and the optimized version through the same pyperf runner
   (`benchmarks/<b>/run_benchmark*.py -o ….json`),
3. `perf record -F 999 -g` + FlameGraph and `py-spy` on both,
4. `pyperf compare_to` and `perf stat -r 3` for both.

Outputs: `results/<b>/<b>_base.json`, `<b>_opt.json`, `compare_<b>.txt`,
`flame_<b>_{base,opt}_{perf,pyspy}.svg`, `perf_top_{base,opt}.txt`,
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
make vectors     # needs python3 with pyperf importable; writes tb/vectors/
make sim         # Icarus Verilog (iverilog -g2012)
```

Expected: `decoded 148271 symbols in 148275 cycles (1.000 symbols/cycle), 0 errors` / `PASS`.
Synthesis figures in `docs/synthesis_yosys.txt` were produced with
`yosys` (`read_verilog -sv …; synth; abc; stat; ltp`).

## Commit history

The history is meant to be read: baseline vendored → pyflate optimization →
mdp optimization → scripts → RTL + testbench → docs/synthesis. Each commit
message states what was measured and why the change was made.
