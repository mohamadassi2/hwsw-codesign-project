#!/usr/bin/env bash
# Mutation test for the testbench: inject one bug at a time into the RTL, run
# `make sim_all`, and report whether the suite KILLED it (failed) or let it
# ESCAPE (passed). A testbench that cannot fail proves nothing.
#
# The suite is sim_all, not sim: against the benchmark block alone twelve of
# the twenty bugs escape (`SUITE=sim tb/mutate.sh` shows it), because one
# well-formed stream never reaches end-of-input, an unmatchable code, a bad
# table index, a stalled handshake, or a code outside 2..15 bits. The directed
# sets and the throttled runs exist to reach those. Results: tb/MUTATIONS.md.
#
#   cd hw && tb/mutate.sh                    # all twenty (~25 min)
#   cd hw && ONLY=comparators tb/mutate.sh   # one bug, matched by name
#
# Runs on a scratch copy; the repository files are never modified.
set -euo pipefail
HW=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cp -r "$HW" "$TMP/hw"; cp -r "$HW/../benchmarks" "$TMP/benchmarks"; cp -r "$HW/../scripts" "$TMP/scripts"
cd "$TMP/hw"
make vectors >/dev/null 2>&1 || { echo "cannot build tb/vectors - is python3 available?"; exit 1; }
[ -s tb/vectors/expected.txt ] || { echo "tb/vectors/expected.txt is empty"; exit 1; }
make synth_vectors >/dev/null 2>&1 || { echo "cannot build the directed vector sets"; exit 1; }
SUITE=${SUITE:-sim_all}

run() {   # run NAME 'sed-expression' FILE
  local name=$1 expr=$2 file=$3
  # ONLY=<any part of a mutation name> runs just that one bug instead of all twenty.
  if [ -n "${ONLY:-}" ] && [[ "$name" != *"$ONLY"* ]]; then return; fi
  cp "$file" "$file.orig"
  if ! sed -i.bak "$expr" "$file" 2>/dev/null; then
    echo "[$name] SED FAILED - the expression is malformed, not a result"
    rm -f "$file.bak"; mv "$file.orig" "$file"; return
  fi
  rm -f "$file.bak"
  if cmp -s "$file" "$file.orig"; then echo "[$name] mutation did not apply - check the pattern"; mv "$file.orig" "$file"; return; fi
  rm -rf build
  local out rc
  out=$(make $SUITE 2>&1) && rc=0 || rc=$?
  mv "$file.orig" "$file"
  # `|| true`, because of `set -o pipefail` above: a mutation that breaks
  # compilation prints "make: *** [build/tb] Error 16", which matches none of
  # these words, and a grep that matches nothing would fail the pipeline, fail
  # the assignment and take the whole sweep down with it - no verdict for that
  # mutation, no error, and the remaining ones never run. The output would look
  # like a clean partial sweep.
  local summary; summary=$(echo "$out" | grep -E 'decoded|errors|PASS|FAIL|TIMEOUT|X on' | tail -2 | tr '\n' ' ' | cut -c1-150 || true)
  [ -n "$summary" ] || summary="(no recognisable line in the suite output)"
  # The suite's exit status is the verdict, not the log: the badidx set decodes
  # zero symbols on purpose, so "decoded 0 symbols" is a pass there.
  if [ "$rc" -ne 0 ]; then echo "[$name] KILLED   (suite exit $rc)  $summary"
  else                     echo "[$name] ESCAPED  (suite exit 0)   $summary"; fi
}

echo "suite: make $SUITE"
# Stamp the RTL these results describe, so a recorded score cannot outlive the
# code it was measured on (the same check docs/synthesis_yosys.txt carries).
echo "RTL fingerprint: $(for f in rtl/*.sv; do md5sum "$f" | cut -d" " -f1; done | tr -d "\n" | md5sum | cut -d" " -f1)  ($(ls rtl/*.sv | wc -l) files under hw/rtl/)"
# The control, and it has to be able to stop the sweep. This used to be one
# echo with the make inside a command substitution, so the status belonged to
# echo and was always 0: if the unmutated suite failed, every mutation below
# would report KILLED for that reason alone and the sweep would print a perfect
# score that meant nothing. scripts/mutate_gates.py does the same check and its
# comment says it does it "as hw/tb/mutate.sh runs one" - now true.
rm -rf build
if ctl=$(make $SUITE 2>&1); then
  echo "control (no mutation): $(echo "$ctl" | grep -E 'all simulations passed|FAILED' | tail -1 || true)"
else
  ctl_rc=$?
  echo "control (no mutation): FAILED - make $SUITE exits $ctl_rc on the unmutated RTL." >&2
  echo "  Every mutation below would be recorded KILLED for that reason alone, so the" >&2
  echo "  sweep would say nothing. Fix the tree first." >&2
  exit 1
fi
run "symbol output driven to X"         's/sym <= symtab\[tsel\]\[idx\];/sym <= '"'"'x;/'                          rtl/huffman_decoder.sv
run "sym_valid stuck low"               's/if (take \&\& idx_ok)  sym_valid <= 1.b1;/if (1'"'"'b0)               sym_valid <= 1'"'"'b1;/' rtl/huffman_decoder.sv
run "hit compare < changed to <="       's/code\[L\] < limit_r\[tsel\]\[L\]/code[L] <= limit_r[tsel][L]/'       rtl/huffman_decoder.sv
run "base adder off by one"             's/idx_s = base_r\[tsel\]\[len_c\] + /idx_s = base_r[tsel][len_c] + 1 + /' rtl/huffman_decoder.sv
run "priority encoder direction"        's/for (int L = MAXBITS; L >= 1; L--)/for (int L = 1; L <= MAXBITS; L++)/' rtl/huffman_decoder.sv
run "barrel shift one bit short"        's/buf_d = buf_q << consume;/buf_d = buf_q << (consume - 1);/'          rtl/bitreader.sv

# ---- corners only the directed sets and the throttled runs reach: end of
# input, an unmatchable code, a bad table index, a stalled handshake, the
# extreme code lengths.
run "end-of-input term dropped from peek_valid" 's/(eof_q \&\& cnt_q != 0)/(1'"'"'b0)/'                       rtl/bitreader.sv
# Expected to escape: the decoder consumes a code only when fits[L] (folded
# into hit[L] in huffman_decoder.sv) says the whole code is in the buffer, so
# cnt_q < consume cannot happen. Kept as a guard for any other consumer of the
# bit reader; MUTATIONS.md #8.
run "bit-count underflow guard removed"         's/assign cnt_after = (cnt_q > consume) ? (cnt_q - consume) : .0;/assign cnt_after = cnt_q - consume;/' rtl/bitreader.sv
run "flush tied low in the top"                 's/\.flush(flush_c),/.flush(1'"'"'b0),/'                       rtl/huffman_accel_top.sv
run "decode error no longer halts"              's/out_free \&\& !err_q \&\& !underrun_q/out_free/'            rtl/huffman_decoder.sv
run "refill decided from the stale count"       's/assign in_ready = (cnt_after + INW <= BUFW);/assign in_ready = (cnt_q + INW <= BUFW);/' rtl/bitreader.sv
run "level output stuck at zero"                's/assign level      = cnt_q;/assign level      = '"'"'0;/'   rtl/bitreader.sv
run "comparators only for lengths 2..15"        's/for (int L = 1; L <= MAXBITS; L++) begin/for (int L = 2; L <= 15; L++) begin/' rtl/huffman_decoder.sv
run "consume driven ungated"                    's/assign len       = take ? len_c : 5.d0;/assign len       = len_c;/' rtl/huffman_decoder.sv
run "output backpressure ignored"               's/assign out_free  = !sym_valid || out_ready;/assign out_free  = 1'"'"'b1;/' rtl/huffman_decoder.sv
run "symbol counter counts offers not takes"    's/else if (sym_valid \&\& out_ready) sym_count/else if (sym_valid) sym_count/' rtl/huffman_accel_top.sv
run "short-code guard removed at end of stream" 's/hit\[L\]     = hit_raw\[L\] \&\& fits\[L\];/hit[L]     = hit_raw[L];/' rtl/huffman_decoder.sv
run "symbol index range check removed"          's/take \&\& idx_ok/take/g'                                     rtl/huffman_decoder.sv
run "end-of-input flushed on a producer bubble" 's#assign flush_c = in_last \& in_valid \& in_ready;#assign flush_c = in_last \& ((in_valid \& in_ready) \| ~in_valid);#' rtl/huffman_accel_top.sv
run "done ignores the unaccepted last symbol" 's#assign done = bits_done \& ~sym_valid;#assign done = bits_done;#' rtl/huffman_accel_top.sv
