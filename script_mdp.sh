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
# perf can only sample everything as root (course forum, 5 Sept): re-run under sudo.
if [ "$(id -u)" != 0 ]; then
  if sudo -n true 2>/dev/null; then exec sudo -E "$0" "$@"; fi
  echo "warning: not root and sudo wants a password - perf record may collect nothing" >&2
fi
B=mdp
# A rerun regenerates all of results/$B. pyperf refuses to overwrite an existing
# output file, so the old set is cleared first.
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
# QEMU's user-mode NAT hands guest DNS to the host resolver; with systemd-resolved
# that is the 127.0.0.53 stub, which the NAT cannot reach, so names fail in the
# guest while TCP works and apt/pip die. Point the guest at Technion's resolvers,
# only when resolution is already broken, keeping the old file as resolv.conf.bak
# (README: "Guest DNS fix").
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
  # Offline needs wheels/ and flamegraph.tgz beside this script (not in the repo: too large).
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
# perf records the debug build (full symbols); timings and py-spy keep the normal venv.
# PMU probe: if the PMI count in /proc/interrupts does not move across a
# hardware-event record, the counter is emulated and never overflows (the
# failure described in the report). The target must burn CPU: an idle sleep
# retires nothing and fires no PMI even on bare metal.
{ echo "probe target: ~3 s of CPU-bound Python (not an idle sleep)"
  echo "PMI/NMI before:"; grep -E "^\s*(NMI|PMI)" /proc/interrupts || true
  perf record -q -e cycles -F 999 -o /tmp/probe.data -- \
      python3 -c 'x=0
for i in range(30000000): x+=i' >/dev/null 2>&1 || true
  echo "PMI/NMI after a cycles record over that workload:"; grep -E "^\s*(NMI|PMI)" /proc/interrupts || true
  echo "samples in that cycles record: $(perf script -i /tmp/probe.data 2>/dev/null | wc -l)"
  echo "counting (not sampling) the same workload, to show the PMU is present:"
  perf stat -e cycles,instructions -- python3 -c 'x=0
for i in range(30000000): x+=i' 2>&1 | grep -E "cycles|instructions" || true
  echo "dmesg PMU line: $(dmesg 2>/dev/null | grep -i 'Performance Events' | tail -1)"
} > "$OUT/pmu_diagnosis.txt" 2>&1
cat "$OUT/pmu_diagnosis.txt"
echo "--- sampling events available in this guest (probed over ~3 s of CPU-bound Python):"
for e in cycles cpu-clock task-clock; do
  if perf record -q -e $e -F 999 -o /tmp/probe.data -- \
       python3 -c 'x=0
for i in range(30000000): x+=i' >/dev/null 2>&1 && \
     [ "$(perf script -i /tmp/probe.data 2>/dev/null | wc -l)" -gt 0 ]; then
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
# perf_probe: pick a sampling setup that actually collects stacks, once, on a
# short CPU-bound command (a DWARF capture of the real benchmark takes minutes
# to unwind on one vCPU). A KVM guest usually has no sampling PMU, so `cycles`
# never fires; cpu-clock is an hrtimer software event and always works. Python
# has no frame pointers, so plain -g gives one-deep stacks and DWARF unwinding
# gives the real call graph. Best option first, then fall back.
PERF_OPT=""
perf_probe(){
  local opt probe="$OUT/.probe.data"
  # Frame-pointer call graphs only: DWARF unwinding of a debug-build capture
  # took perf report and perf script twenty minutes each in this guest.
  for opt in "-e cpu-clock -F 997 -g" \
             "-e task-clock -F 997 -g" \
             "-F 999 -g"; do
    # ~3 s of work, same target as the PMU probe: a short run gives the sampler no time to fire.
    # shellcheck disable=SC2086
    perf record -q $opt -o "$probe" -- "$PY" -c 'x=0
for i in range(30000000): x+=i' >/dev/null 2>&1 || true
    # count the samples; `head -1` would kill perf script with SIGPIPE, which pipefail turns into a failure
    if [ "$(perf script -i "$probe" 2>/dev/null | wc -l)" -gt 0 ]; then
      PERF_OPT="$opt"; echo "sampling event: $opt"; rm -f "$probe"; return 0
    fi
    echo "sampling event '$opt' collected nothing, trying the next"
  done
  echo "no sampling event works in this environment; flame graphs will be from py-spy only"
  rm -f "$probe"; return 0
}
perf_probe
echo "${PERF_OPT:-none}" > "$OUT/perf_event_chosen.txt"

# perf_rec TAG -- CMD...: perf record CMD with the probed setup into $OUT/perf_TAG.data
perf_rec(){
  local tag=$1; shift; [ "$1" = "--" ] && shift
  local data="$OUT/perf_$tag.data"
  [ -n "$PERF_OPT" ] || { echo "perf record ($tag): skipped, no working event"; return 0; }
  # shellcheck disable=SC2086
  perf record -q $PERF_OPT -o "$data" -- "$@" >/dev/null 2>&1 || true
  if [ "$(perf script -i "$data" 2>/dev/null | wc -l)" -gt 0 ]; then
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
  perf report -i "$OUT/perf_$tag.data" --stdio 2>/dev/null > "$OUT/perf_report_$tag.txt" || true
  perf script -i "$OUT/perf_$tag.data" 2>/dev/null | perl FlameGraph/stackcollapse-perf.pl > "$OUT/perf_$tag.folded" || true
  echo "perf samples ($tag): $(grep -m1 -oE 'Samples: [0-9KMG.]+' "$OUT/perf_top_$tag.txt" 2>/dev/null || echo '?')"
  flame "$OUT/perf_$tag.folded" "$OUT/flame_${B}_${tag}_perf.svg" "$title"
}

# ---------------------------------------------------------------- 1. baseline
# 6 processes x 3 values: enough for a mean and standard deviation, and keeps
# the run inside one VM session (mdp costs ~8 s per value in the guest).
# Override with PYPERF_OPTS for more.
PYPERF_OPTS=${PYPERF_OPTS:--p 6 -n 3}
# one loop (~5 s on the baseline) is enough to profile mdp
PROF_LOOPS=${PROF_LOOPS:-1}
log "baseline through the pyperformance framework itself"
$PY -m pyperformance run $PPVENV --bench $B --fast -o "$OUT/${B}_pyperformance_baseline.json" 2>&1 | tail -3
log "baseline, same runner on the vendored copy (what we diff against)"
# shellcheck disable=SC2086
$PY "$BASE" $PYPERF_OPTS -o "$OUT/${B}_base.json" 2>&1 | tail -2

# ---------------------------------------------------------------- 2. profile baseline
# perf_guide TAG -- CMD...: the setup guide's capture, `perf record -F 999 -g`, on
# cpu-clock (the guest's cycles counter never overflows), with the full report.
perf_guide(){
  local tag=$1; shift; [ "$1" = "--" ] && shift
  perf record -F 999 -e cpu-clock -g -o "$OUT/perf_$tag.data" -- "$@" >/dev/null 2>&1 || true
  perf report -i "$OUT/perf_$tag.data" --stdio > "$OUT/perf_report_$tag.txt" 2>/dev/null || true
  echo "perf record ($tag, guide form): $(grep -m1 -oE '^# Samples: [0-9KMG.]+' "$OUT/perf_report_$tag.txt" | cut -c3- || echo 'no samples')"
}
log "perf record -F 999 -g on the baseline (guide's form: python3-dbg -m pyperformance run)"
if [ -d venv-dbg ]; then
  perf_guide base_dbg -- venv-dbg/bin/python -m pyperformance run --bench $B --fast -o "$OUT/scratch_dbg.json"
fi
log "perf record on the benchmark worker directly (cleaner attribution)"
# a --worker run prints its JSON to stdout (pyperf rejects -o in worker mode); it is discarded
perf_rec base -- $PY "$BASE" --worker --loops "$PROF_LOOPS" -n 2 -w 0
perf_flame base "$B baseline: perf -F999 -g (KVM guest)"
log "py-spy (Python-level frames) on the baseline"
venv/bin/py-spy record --rate 500 -f raw -o "$OUT/pyspy_base.folded" -- \
    $PY "$BASE" --worker --loops "$PROF_LOOPS" -n 2 -w 0 >/dev/null 2>&1 || true
# py-spy 0.4 sometimes exits 1 ("No child process") after writing a complete file: judge it by the file
[ -s "$OUT/pyspy_base.folded" ] || echo "py-spy failed on the baseline (see trace.log)"
flame "$OUT/pyspy_base.folded" "$OUT/flame_${B}_base_pyspy.svg" "$B baseline: Python frames (py-spy)" --colors js
# py-spy records the whole process, so the pyperf runner frames sit under the
# benchmark; the second graph re-roots at the benchmark's own entry point.
python3 scripts/focus_folded.py bench_mdp < "$OUT/pyspy_base.folded" > "$OUT/pyspy_base_focus.folded" 2>>"$OUT/focus.log" || true
flame "$OUT/pyspy_base_focus.folded" "$OUT/flame_${B}_base_focus.svg" "$B baseline: Python frames below bench_mdp (py-spy)" --colors js

# ---------------------------------------------------------------- 3. optimized
log "optimized version, same pyperf runner"
# shellcheck disable=SC2086
$PY "$OPT" $PYPERF_OPTS -o "$OUT/${B}_opt.json" 2>&1 | tail -2
log "profile the optimized version the same way"
perf_rec opt -- $PY "$OPT" --worker --loops "$PROF_LOOPS" -n 2 -w 0
perf_flame opt "$B optimized: perf -F999 -g (KVM guest)"
if [ -d venv-dbg ]; then
  perf_guide opt_dbg -- venv-dbg/bin/python "$OPT" --worker --loops "$PROF_LOOPS" -n 2 -w 0
fi
venv/bin/py-spy record --rate 500 -f raw -o "$OUT/pyspy_opt.folded" -- \
    $PY "$OPT" --worker --loops "$PROF_LOOPS" -n 2 -w 0 >/dev/null 2>&1 || true
# py-spy 0.4 sometimes exits 1 ("No child process") after writing a complete file: judge it by the file
[ -s "$OUT/pyspy_opt.folded" ] || echo "py-spy failed on the optimized run (see trace.log)"
flame "$OUT/pyspy_opt.folded" "$OUT/flame_${B}_opt_pyspy.svg" "$B optimized: Python frames (py-spy)" --colors js
python3 scripts/focus_folded.py bench_mdp < "$OUT/pyspy_opt.folded" > "$OUT/pyspy_opt_focus.folded" 2>>"$OUT/focus.log" || true
flame "$OUT/pyspy_opt_focus.folded" "$OUT/flame_${B}_opt_focus.svg" "$B optimized: Python frames below bench_mdp (py-spy)" --colors js

# ---------------------------------------------------------------- 3b. cProfile
# Per-function self/cumulative shares quoted in the report (the Amdahl argument
# for the accelerator rests on them). cProfile traces every call, so the shares
# are exact where py-spy's are sampled, but that inflates absolute times: it is
# used for the shares only, never for wall-clock figures.
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
# The guest is one vCPU on a shared host: when the host is busy, wall-clock
# stretches while instruction counts stay put (one rerun: mdp at 2.33 s vs
# 1.30 s for the same 31.4 G instructions). perf's "CPUs utilized" shows this.
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
[ -z "${SUDO_UID:-}" ] || chown -R "$SUDO_UID:${SUDO_GID:-$SUDO_UID}" "$OUT" venv venv-dbg FlameGraph 2>/dev/null || true
log "done -> $OUT"
