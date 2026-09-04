#!/usr/bin/env bash
# script_pyflate.sh -- pyflate: environment setup, baseline run, perf + flame graphs,
#                      optimized run, before/after comparison.
#
# Meant to be run as root inside the course QEMU/KVM guest (Ubuntu 22.04), but it
# only assumes: python3 (3.10), perf, git, network for pip/apt.  Everything it
# produces lands in results/pyflate/.
#
#   chmod +x script_pyflate.sh && ./script_pyflate.sh
#
set -euo pipefail
cd "$(dirname "$0")"
B=pyflate
OUT=results/$B; mkdir -p "$OUT"
log(){ printf '\n=== %s  %s ===\n' "$(date +%T)" "$*"; }

# ---------------------------------------------------------------- 0. environment
log "environment"
uname -r; nproc; grep -m1 'model name' /proc/cpuinfo || true
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq python3-venv python3-pip python3-dbg git >/dev/null 2>&1 || true
[ -d FlameGraph ] || git clone -q --depth 1 https://github.com/brendangregg/FlameGraph
[ -d venv ]     || python3 -m venv venv
venv/bin/pip install -q --disable-pip-version-check pyperf pyperformance py-spy
# The guide's own example profiles python3-dbg -m pyperformance; give it its own venv.
if command -v python3-dbg >/dev/null && [ ! -d venv-dbg ]; then
  python3-dbg -m venv venv-dbg && venv-dbg/bin/pip install -q --disable-pip-version-check pyperformance
fi
# perf inside the guest: without these two knobs `perf report` prints
# "Kernel address maps were restricted" and call graphs are empty.
echo 0  > /proc/sys/kernel/kptr_restrict       2>/dev/null || true
echo -1 > /proc/sys/kernel/perf_event_paranoid 2>/dev/null || true
perf --version; venv/bin/python --version

PY=venv/bin/python
BASE=benchmarks/$B/run_benchmark.py         # byte-identical to upstream pyperformance
OPT=benchmarks/$B/run_benchmark_opt.py

# ---------------------------------------------------------------- 1. baseline
log "baseline through the pyperformance framework itself"
$PY -m pyperformance run --bench $B -o "$OUT/${B}_pyperformance_baseline.json" 2>&1 | tail -3
log "baseline, same runner on the vendored copy (what we diff against)"
$PY "$BASE" -o "$OUT/${B}_base.json" 2>&1 | tail -2

# ---------------------------------------------------------------- 2. profile baseline
log "perf record -F 999 -g on the baseline (guide's form, python3-dbg)"
if [ -d venv-dbg ]; then
  perf record -q -F 999 -g -o "$OUT/perf_base_dbg.data" -- \
      venv-dbg/bin/python -m pyperformance run --bench $B --fast -o "$OUT/scratch_dbg.json" >/dev/null 2>&1 || true
  perf report -i "$OUT/perf_base_dbg.data" --stdio > "$OUT/perf_report_base_dbg.txt" 2>/dev/null || true
fi
log "perf record on the benchmark worker directly (cleaner attribution)"
perf record -q -F 999 -g -o "$OUT/perf_base.data" -- \
    $PY "$BASE" --worker --loops 4 -n 3 -w 1 -o "$OUT/scratch.json" >/dev/null
perf report -i "$OUT/perf_base.data" --stdio --no-children --sort dso,symbol > "$OUT/perf_top_base.txt" 2>/dev/null
perf script -i "$OUT/perf_base.data" 2>/dev/null | FlameGraph/stackcollapse-perf.pl > "$OUT/perf_base.folded"
FlameGraph/flamegraph.pl --title "$B baseline: perf -F999 -g (KVM guest)" "$OUT/perf_base.folded" > "$OUT/flame_${B}_base_perf.svg"
log "py-spy (Python-level frames) on the baseline"
venv/bin/py-spy record --rate 500 -f raw -o "$OUT/pyspy_base.folded" -- \
    $PY "$BASE" --worker --loops 4 -n 3 -w 1 -o "$OUT/scratch.json" >/dev/null 2>&1
FlameGraph/flamegraph.pl --title "$B baseline: Python frames (py-spy)" --colors python "$OUT/pyspy_base.folded" > "$OUT/flame_${B}_base_pyspy.svg"

# ---------------------------------------------------------------- 3. optimized
log "optimized version, same pyperf runner"
$PY "$OPT" -o "$OUT/${B}_opt.json" 2>&1 | tail -2
log "profile the optimized version the same way"
perf record -q -F 999 -g -o "$OUT/perf_opt.data" -- \
    $PY "$OPT" --worker --loops 4 -n 3 -w 1 -o "$OUT/scratch.json" >/dev/null
perf report -i "$OUT/perf_opt.data" --stdio --no-children --sort dso,symbol > "$OUT/perf_top_opt.txt" 2>/dev/null
perf script -i "$OUT/perf_opt.data" 2>/dev/null | FlameGraph/stackcollapse-perf.pl > "$OUT/perf_opt.folded"
FlameGraph/flamegraph.pl --title "$B optimized: perf -F999 -g (KVM guest)" "$OUT/perf_opt.folded" > "$OUT/flame_${B}_opt_perf.svg"
venv/bin/py-spy record --rate 500 -f raw -o "$OUT/pyspy_opt.folded" -- \
    $PY "$OPT" --worker --loops 4 -n 3 -w 1 -o "$OUT/scratch.json" >/dev/null 2>&1
FlameGraph/flamegraph.pl --title "$B optimized: Python frames (py-spy)" --colors python "$OUT/pyspy_opt.folded" > "$OUT/flame_${B}_opt_pyspy.svg"

# ---------------------------------------------------------------- 4. compare + hardware counters
log "before/after (pyperf compare_to)"
$PY -m pyperf compare_to "$OUT/${B}_base.json" "$OUT/${B}_opt.json" --table | tee "$OUT/compare_${B}.txt"
log "hardware counters, baseline vs optimized (perf stat -r 3)"
for v in base opt; do
  f=$([ $v = base ] && echo "$BASE" || echo "$OPT")
  perf stat -r 3 -e task-clock,cycles,instructions,branches,branch-misses -o "$OUT/perfstat_${v}.txt" -- \
      $PY "$f" --worker --loops 4 -n 1 -w 0 -o "$OUT/scratch.json" >/dev/null 2>&1 || true
  grep -E 'task-clock|cycles|instructions|branch' "$OUT/perfstat_${v}.txt" | sed "s/^/  $v: /"
done
rm -f "$OUT"/scratch*.json "$OUT"/*.data
log "done -> $OUT"
