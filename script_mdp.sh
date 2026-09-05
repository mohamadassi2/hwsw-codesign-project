#!/usr/bin/env bash
# script_mdp.sh -- mdp: environment setup, baseline run, perf + flame graphs,
#                      optimized run, before/after comparison.
#
# Meant to be run as root inside the course QEMU/KVM guest (Ubuntu 22.04), but it
# only assumes: python3 (3.10), perf, git, network for pip/apt.  Everything it
# produces lands in results/mdp/.
#
#   chmod +x script_mdp.sh && ./script_mdp.sh
#
set -euo pipefail
cd "$(dirname "$0")"
B=mdp
# This script REPLACES results/$B: the repository ships the set measured in the
# course VM, and a rerun regenerates every file in it. pyperf refuses to write
# an output file that already exists, so the old set is cleared first.
OUT=results/$B; rm -rf "$OUT"; mkdir -p "$OUT"
log(){ printf '\n=== %s  %s ===\n' "$(date +%T)" "$*"; }
# Every command is traced into $OUT/trace.log, and a failing command names itself.
exec 19>"$OUT/trace.log"; export BASH_XTRACEFD=19; set -x
# shellcheck disable=SC2154  # rc is assigned inside the trap itself
trap 'rc=$?; echo "FAILED at line $LINENO (exit $rc): $BASH_COMMAND" >&2; echo "FAILED at line $LINENO (exit $rc): $BASH_COMMAND" >&19' ERR

# ---------------------------------------------------------------- 0. environment
log "environment"
uname -r; nproc; grep -m1 'model name' /proc/cpuinfo || true
export DEBIAN_FRONTEND=noninteractive

# --- network inside the course VM --------------------------------------------
# QEMU's user-mode NAT forwards the guest's DNS queries to the host's resolver.
# When the host runs systemd-resolved (Ubuntu 24.04, as on the course VM hosts)
# that resolver is the 127.0.0.53 stub, which the NAT cannot reach: names fail
# in the guest while plain TCP works, so apt and pip silently die.  Point the
# guest at the real upstream servers (Technion's) instead.
#
# This REWRITES /etc/resolv.conf, which is not harmless on a normal machine, so
# it only happens when name resolution is already broken, the previous file is
# kept as /etc/resolv.conf.bak, and the change is announced.
if ! getent hosts pypi.org >/dev/null 2>&1; then
  echo "dns: pypi.org does not resolve - rewriting /etc/resolv.conf (previous file saved as /etc/resolv.conf.bak)"
  cp -f /etc/resolv.conf /etc/resolv.conf.bak 2>/dev/null || true
  rm -f /etc/resolv.conf 2>/dev/null || true
  printf 'nameserver 132.68.39.127\nnameserver 132.68.32.5\nnameserver 8.8.8.8\n' > /etc/resolv.conf 2>/dev/null || true
fi
if getent hosts pypi.org >/dev/null 2>&1 && timeout 15 curl -fsI https://pypi.org/simple/ >/dev/null 2>&1; then
  ONLINE=1; echo "network: online"
else
  ONLINE=0
  # The offline path needs a wheels/ directory and a flamegraph.tgz beside this
  # script. They are not in the repository (too large, and the VM has network),
  # so say plainly whether they are actually there rather than implying they are.
  if [ -d wheels ] && [ -f flamegraph.tgz ]; then
    echo "network: offline - using the wheels/ and flamegraph.tgz found beside this script"
  else
    echo "network: offline, and no wheels/ + flamegraph.tgz to fall back on."
    echo "         This script needs network the first time it runs (pyperf, pyperformance,"
    echo "         py-spy, FlameGraph). See README.md for the guest DNS fix."
    exit 1
  fi
fi
if [ "$ONLINE" = 1 ]; then
  apt-get update -qq >/dev/null 2>&1 || true
  apt-get install -y -qq python3-venv python3-pip python3-dbg git curl >/dev/null 2>&1 || true
fi

# venv: the normal way, or (image without python3-venv) without ensurepip plus pip from a wheel
if [ ! -x venv/bin/python ]; then
  rm -rf venv
  if ! python3 -m venv venv 2>/dev/null; then
    python3 -m venv --without-pip venv
    PIPWHL=$(ls wheels/pip-*.whl 2>/dev/null | head -1 || true)
    [ -n "$PIPWHL" ] || { echo "python3-venv is missing and there is no wheels/pip-*.whl to bootstrap from"; exit 1; }
    venv/bin/python "$PIPWHL/pip" install -q --no-index --find-links wheels pip
  fi
fi
PIPOPT=""
[ "$ONLINE" = 1 ] || PIPOPT="--no-index --find-links wheels"
venv/bin/pip install -q --disable-pip-version-check $PIPOPT pyperf pyperformance py-spy

# FlameGraph scripts
if [ ! -d FlameGraph ]; then
  git clone -q --depth 1 https://github.com/brendangregg/FlameGraph 2>/dev/null || tar xzf flamegraph.tgz
fi

# pyperformance normally builds its own venv per run (needs ensurepip and PyPI);
# offline it reuses ours and pip resolves from wheels/.
PPVENV=""
if [ "$ONLINE" != 1 ]; then
  PPVENV="--venv $PWD/venv"
  export PIP_NO_INDEX=1 PIP_FIND_LINKS="$PWD/wheels"
fi
# The guide's own example profiles python3-dbg -m pyperformance; give it its own venv (online only).
if [ "$ONLINE" = 1 ] && command -v python3-dbg >/dev/null && [ ! -d venv-dbg ]; then
  python3-dbg -m venv venv-dbg && venv-dbg/bin/pip install -q --disable-pip-version-check pyperformance || rm -rf venv-dbg
fi
# perf inside the guest: without these two knobs `perf report` prints
# "Kernel address maps were restricted" and call graphs are empty.
echo 0  > /proc/sys/kernel/kptr_restrict       2>/dev/null || true
echo -1 > /proc/sys/kernel/perf_event_paranoid 2>/dev/null || true
perf --version; venv/bin/python --version
# Does the PMU overflow interrupt actually reach the guest? If the PMI line in
# /proc/interrupts does not move across a hardware-event record, the counter is
# emulated but never overflows, which is exactly the failure described in the report.
#
# The probe target has to BURN CPU. An earlier version of this script recorded
# against `sleep 3`, which retires almost no instructions: a per-task cycles
# counter then never overflows and no PMI fires even on bare metal, so that
# probe could not distinguish a broken PMU from a healthy one. The probe now
# records over a few seconds of pure Python arithmetic instead.
{ echo "probe target: ~3 s of CPU-bound Python (not an idle sleep)"
  echo "PMI/NMI before:"; grep -E "^\s*(NMI|PMI)" /proc/interrupts || true
  perf record -q -e cycles -F 999 -o /tmp/probe.data -- \
      python3 -c 'x=0
for i in range(30000000): x+=i' >/dev/null 2>&1 || true
  echo "PMI/NMI after a cycles record over that workload:"; grep -E "^\s*(NMI|PMI)" /proc/interrupts || true
  echo "samples in that cycles record: $(perf script -i /tmp/probe.data 2>/dev/null | grep -c . || echo 0)"
  echo "counting (not sampling) the same workload, to show the PMU is present:"
  perf stat -e cycles,instructions -- python3 -c 'x=0
for i in range(30000000): x+=i' 2>&1 | grep -E "cycles|instructions" || true
  echo "dmesg PMU line: $(dmesg 2>/dev/null | grep -i 'Performance Events' | tail -1)"
} > "$OUT/pmu_diagnosis.txt" 2>&1
cat "$OUT/pmu_diagnosis.txt"
# Same correction here: probe each event against the CPU-bound workload, not
# against `true`, which exits in about a millisecond and yields zero samples
# for any event on any machine.
echo "--- sampling events available in this guest (probed over ~3 s of CPU-bound Python):"
for e in cycles cpu-clock task-clock; do
  if perf record -q -e $e -F 999 -o /tmp/probe.data -- \
       python3 -c 'x=0
for i in range(30000000): x+=i' >/dev/null 2>&1 && \
     [ "$(perf script -i /tmp/probe.data 2>/dev/null | grep -c . || echo 0)" -gt 0 ]; then
    echo "    $e: works ($(perf script -i /tmp/probe.data 2>/dev/null | grep -c .) samples)"
  else echo "    $e: no samples"; fi
done | tee "$OUT/perf_events_probe.txt"
rm -f /tmp/probe.data

PY=venv/bin/python
BASE=benchmarks/$B/run_benchmark.py         # byte-identical to upstream pyperformance
OPT=benchmarks/$B/run_benchmark_opt.py

# flame FOLDED SVG TITLE [flamegraph.pl options...]: render, but do not abort the run on empty data
flame(){
  local folded=$1 svg=$2 title=$3; shift 3
  if [ -s "$folded" ] && perl FlameGraph/flamegraph.pl --title "$title" "$@" "$folded" > "$svg" 2>/dev/null; then
    echo "flame graph: $svg ($(wc -l < "$folded") stacks)"
  else
    echo "flame graph: no stacks for $svg" ; rm -f "$svg"
  fi
}
# perf_rec TAG -- CMD...: record a profile that actually contains stacks.
# A KVM guest usually has no sampling PMU, so the default `cycles` event never
# fires and perf.data comes out empty ("The perf.data data has no samples!").
# cpu-clock is a software event driven by an hrtimer and always works. Python
# is built without frame pointers, so plain -g gives one-deep stacks; DWARF
# unwinding gives the real call graph. Try the best option first and fall back.
# Which sampling event actually collects anything here? Probe ONCE against a
# trivial command rather than re-running the benchmark for every candidate:
# unwinding a full DWARF capture takes minutes on a single-vCPU guest, and
# doing that five times is what made an earlier run take an hour.
PERF_OPT=""
perf_probe(){
  local opt probe="$OUT/.probe.data"
  for opt in "-e cpu-clock -F 499 --call-graph dwarf,32768" \
             "-e cpu-clock -F 997 --call-graph dwarf,16384" \
             "-e cpu-clock -F 997 --call-graph fp" \
             "-e cpu-clock -F 997" \
             "-e task-clock -F 997 --call-graph dwarf,16384" \
             "-e task-clock -F 997" \
             "-F 999 -g"; do
    # shellcheck disable=SC2086
    perf record -q $opt -o "$probe" -- "$PY" -c 'x=0
for i in range(3000000): x+=i' >/dev/null 2>&1 || true
    if [ -s "$probe" ] && perf script -i "$probe" 2>/dev/null | head -1 | grep -q .; then
      PERF_OPT="$opt"; echo "sampling event: $opt"; rm -f "$probe"; return 0
    fi
    echo "sampling event '$opt' collected nothing, trying the next"
  done
  echo "no sampling event works in this environment; flame graphs will be from py-spy only"
  rm -f "$probe"; return 0
}
perf_probe
echo "${PERF_OPT:-none}" > "$OUT/perf_event_chosen.txt"

perf_rec(){
  local tag=$1; shift; [ "$1" = "--" ] && shift
  local data="$OUT/perf_$tag.data"
  [ -n "$PERF_OPT" ] || { echo "perf record ($tag): skipped, no working event"; return 0; }
  # shellcheck disable=SC2086
  perf record -q $PERF_OPT -o "$data" -- "$@" >/dev/null 2>&1 || true
  if [ -s "$data" ] && perf script -i "$data" 2>/dev/null | head -1 | grep -q .; then
    echo "perf record ($tag): captured with '$PERF_OPT'"
    echo "$PERF_OPT" > "$OUT/perf_${tag}.event"
  else
    echo "perf record ($tag): no samples despite the probe succeeding"
  fi
  return 0
}
# perf_flame TAG TITLE: perf report + folded stacks + flame graph for $OUT/perf_TAG.data
perf_flame(){
  local tag=$1 title=$2
  perf report -i "$OUT/perf_$tag.data" --stdio --no-children --sort dso,symbol 2>/dev/null > "$OUT/perf_top_$tag.txt" || true
  perf script -i "$OUT/perf_$tag.data" 2>/dev/null | perl FlameGraph/stackcollapse-perf.pl > "$OUT/perf_$tag.folded" || true
  echo "perf samples ($tag): $(grep -m1 -oE 'Samples: [0-9KMG.]+' "$OUT/perf_top_$tag.txt" 2>/dev/null || echo '?')"
  flame "$OUT/perf_$tag.folded" "$OUT/flame_${B}_${tag}_perf.svg" "$title"
}

# ---------------------------------------------------------------- 1. baseline
# Sampling: 10 worker processes x 3 values is well past what a mean and standard
# deviation need, and keeps a two-benchmark run inside one VM session (mdp costs
# about 8 s per value in the guest). Override with PYPERF_OPTS if you want more.
PYPERF_OPTS=${PYPERF_OPTS:--p 6 -n 3}
PROF_LOOPS=${PROF_LOOPS:-1}
log "baseline through the pyperformance framework itself"
$PY -m pyperformance run $PPVENV --bench $B --fast -o "$OUT/${B}_pyperformance_baseline.json" 2>&1 | tail -3
log "baseline, same runner on the vendored copy (what we diff against)"
# shellcheck disable=SC2086
$PY "$BASE" $PYPERF_OPTS -o "$OUT/${B}_base.json" 2>&1 | tail -2

# ---------------------------------------------------------------- 2. profile baseline
log "perf record -F 999 -g on the baseline (guide's form, python3-dbg)"
if [ -d venv-dbg ]; then
  perf_rec base_dbg -- venv-dbg/bin/python -m pyperformance run --bench $B --fast -o "$OUT/scratch_dbg.json"
  perf report -i "$OUT/perf_base_dbg.data" --stdio > "$OUT/perf_report_base_dbg.txt" 2>/dev/null || true
fi
log "perf record on the benchmark worker directly (cleaner attribution)"
# (a --worker run prints its JSON to stdout, which we discard here; pyperf rejects -o in worker mode)
perf_rec base -- $PY "$BASE" --worker --loops "${PROF_LOOPS:-4}" -n 2 -w 0
perf_flame base "$B baseline: perf -F999 -g (KVM guest)"
log "py-spy (Python-level frames) on the baseline"
venv/bin/py-spy record --rate 500 -f raw -o "$OUT/pyspy_base.folded" -- \
    $PY "$BASE" --worker --loops "${PROF_LOOPS:-4}" -n 2 -w 0 >/dev/null 2>&1 || echo "py-spy failed on the baseline (see trace.log)"
flame "$OUT/pyspy_base.folded" "$OUT/flame_${B}_base_pyspy.svg" "$B baseline: Python frames (py-spy)" --colors js
# py-spy records the whole process stack, so ten frames of pyperf runner sit
# under the benchmark. The second graph re-roots at the benchmark's own entry
# point, which is the one worth looking at; the first keeps everything.
python3 scripts/focus_folded.py bench_mdp < "$OUT/pyspy_base.folded" > "$OUT/pyspy_base_focus.folded" 2>>"$OUT/focus.log" || true
flame "$OUT/pyspy_base_focus.folded" "$OUT/flame_${B}_base_focus.svg" "$B baseline: Python frames below bench_mdp (py-spy)" --colors js

# ---------------------------------------------------------------- 3. optimized
log "optimized version, same pyperf runner"
# shellcheck disable=SC2086
$PY "$OPT" $PYPERF_OPTS -o "$OUT/${B}_opt.json" 2>&1 | tail -2
log "profile the optimized version the same way"
perf_rec opt -- $PY "$OPT" --worker --loops "${PROF_LOOPS:-4}" -n 2 -w 0
perf_flame opt "$B optimized: perf -F999 -g (KVM guest)"
venv/bin/py-spy record --rate 500 -f raw -o "$OUT/pyspy_opt.folded" -- \
    $PY "$OPT" --worker --loops "${PROF_LOOPS:-4}" -n 2 -w 0 >/dev/null 2>&1 || echo "py-spy failed on the optimized run (see trace.log)"
flame "$OUT/pyspy_opt.folded" "$OUT/flame_${B}_opt_pyspy.svg" "$B optimized: Python frames (py-spy)" --colors js
python3 scripts/focus_folded.py bench_mdp < "$OUT/pyspy_opt.folded" > "$OUT/pyspy_opt_focus.folded" 2>>"$OUT/focus.log" || true
flame "$OUT/pyspy_opt_focus.folded" "$OUT/flame_${B}_opt_focus.svg" "$B optimized: Python frames below bench_mdp (py-spy)" --colors js

# ---------------------------------------------------------------- 3b. cProfile
# The reports quote per-function self and cumulative shares, and the whole
# Amdahl argument for the accelerator rests on them. py-spy's flame graphs are
# a sampled cross-check; these tables are the deterministic measurement, so
# write them out as evidence rather than quoting numbers with no artifact.
# cProfile inflates absolute times (it traces every call), which is why it is
# used only for the SHARES and never for the wall-clock figures.
for v in base opt; do
  f=$([ $v = base ] && echo "$BASE" || echo "$OPT")
  log "cProfile ($v) - per-function shares, cumulative and self"
  $PY -c "
import cProfile, pstats, runpy, sys, io
sys.argv = [sys.argv[1], '--worker', '--loops', '1', '-n', '1', '-w', '0']
pr = cProfile.Profile()
pr.enable()
try:
    runpy.run_path(sys.argv[0], run_name='__main__')
except SystemExit:
    pass
finally:
    pr.disable()
buf = io.StringIO()
st = pstats.Stats(pr, stream=buf)
buf.write('=== by cumulative time ===\\n')
st.sort_stats('cumulative').print_stats(25)
buf.write('\\n=== by self (tottime) ===\\n')
st.sort_stats('tottime').print_stats(25)
sys.stdout.write(buf.getvalue())
" "$f" > "$OUT/cprofile_${v}.txt" 2>&1 || echo "cProfile failed on $v"
  head -12 "$OUT/cprofile_${v}.txt" | sed "s/^/  $v: /"
done

# ---------------------------------------------------------------- 4. compare + hardware counters
log "before/after (pyperf compare_to)"
$PY -m pyperf compare_to "$OUT/${B}_base.json" "$OUT/${B}_opt.json" --table | tee "$OUT/compare_${B}.txt"
log "hardware counters, baseline vs optimized (perf stat -r 3)"
for v in base opt; do
  f=$([ $v = base ] && echo "$BASE" || echo "$OPT")
  perf stat -r 3 -e task-clock,cycles,instructions,branches,branch-misses -o "$OUT/perfstat_${v}.txt" -- \
      $PY "$f" --worker --loops 4 -n 1 -w 0 >/dev/null 2>&1 || true
  grep -E 'task-clock|cycles|instructions|branch' "$OUT/perfstat_${v}.txt" | sed "s/^/  $v: /"
done
# ---------------------------------------------------------------- 4b. contention
# Wall-clock only means something if the guest actually had the CPU. This VM is
# one vCPU on a host shared with the rest of the class, and a rerun of this very
# script once produced mdp at 2.33 s instead of 1.31 s while executing the same
# 31.5 billion instructions - the host was taking 40% of the core. perf prints
# "CPUs utilized" for exactly this, so check it rather than trusting the clock.
for v in base opt; do
  u=$(grep -m1 'CPUs utilized' "$OUT/perfstat_${v}.txt" 2>/dev/null | sed -E 's/.*# *([0-9.]+) CPUs utilized.*/\1/')
  [ -n "$u" ] || continue
  if [ "$(awk -v u="$u" 'BEGIN{print (u < 0.95) ? 1 : 0}')" = 1 ]; then
    echo "WARNING: only $u CPUs utilized during the $v run."
    echo "         The host was busy, so the wall-clock times above understate this"
    echo "         machine and must not be quoted. Instruction and cycle counts are"
    echo "         unaffected. Re-run when the host is idle."
    echo "$v: CPUs utilized $u - wall clock NOT trustworthy" >> "$OUT/contention.txt"
  else
    echo "$v: CPUs utilized $u - the guest had the core" >> "$OUT/contention.txt"
  fi
done
cat "$OUT/contention.txt" 2>/dev/null

rm -f "$OUT"/scratch*.json "$OUT"/*.data
log "done -> $OUT"
