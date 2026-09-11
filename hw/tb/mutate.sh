#!/usr/bin/env bash
# Mutation test for the testbench: inject one bug at a time into the RTL, run
# the real simulation suite, and report whether the test KILLED it (the suite
# failed) or let it ESCAPE (the suite passed). A testbench that cannot fail
# proves nothing, so this is how we know tb_huffman.sv's PASS means something.
#
# The suite here is `make sim_all`, not `make sim`. That matters: the benchmark
# block is one well-formed bzip2 block, and against it alone twelve of the
# twenty mutations below pass unnoticed (`SUITE=sim tb/mutate.sh` reproduces
# that), because one good stream never reaches end-of-input, never presents an
# unmatchable code or an out-of-range table index, never stalls the consumer or
# the producer, and never uses a code shorter than 2 or longer than 15 bits.
# The directed vector sets and the throttled runs exist to close exactly those
# gaps.
#
#   cd hw && tb/mutate.sh                    # all twenty (~25 min)
#   cd hw && ONLY=comparators tb/mutate.sh   # one bug: the control run passes, then vectors_lengths kills it
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
  local summary; summary=$(echo "$out" | grep -E 'decoded|errors|PASS|FAIL|TIMEOUT|X on' | tail -2 | tr '\n' ' ' | cut -c1-150)
  # The suite's own exit status is the verdict. Do not second-guess it from the
  # log: one directed set decodes zero symbols on purpose (a corrupt table must
  # be refused, not decoded), so "decoded 0 symbols" is a pass there.
  if [ "$rc" -ne 0 ]; then echo "[$name] KILLED   (suite exit $rc)  $summary"
  else                     echo "[$name] ESCAPED  (suite exit 0)   $summary"; fi
}

echo "suite: make $SUITE"
echo "control (no mutation): $( (rm -rf build; make $SUITE 2>&1) | grep -E 'all simulations passed|FAILED' | tail -1)"
run "symbol output driven to X"         's/sym <= symtab\[tsel\]\[idx\];/sym <= '"'"'x;/'                          rtl/huffman_decoder.sv
run "sym_valid stuck low"               's/if (take \&\& idx_ok)  sym_valid <= 1.b1;/if (1'"'"'b0)               sym_valid <= 1'"'"'b1;/' rtl/huffman_decoder.sv
run "hit compare < changed to <="       's/code\[L\] < limit_r\[tsel\]\[L\]/code[L] <= limit_r[tsel][L]/'       rtl/huffman_decoder.sv
run "base adder off by one"             's/idx_s = base_r\[tsel\]\[len_c\] + /idx_s = base_r[tsel][len_c] + 1 + /' rtl/huffman_decoder.sv
run "priority encoder direction"        's/for (int L = MAXBITS; L >= 1; L--)/for (int L = 1; L <= MAXBITS; L++)/' rtl/huffman_decoder.sv
run "barrel shift one bit short"        's/buf_d = buf_q << consume;/buf_d = buf_q << (consume - 1);/'          rtl/bitreader.sv

# ---- the corners the directed vector sets and the throttled runs were built to
# reach: end of input, an unmatchable code, an out-of-range table index, a
# stalled consumer or producer, and the extreme code lengths.
run "end-of-input term dropped from peek_valid" 's/(eof_q \&\& cnt_q != 0)/(1'"'"'b0)/'                       rtl/bitreader.sv
# Expected to escape, and that is the correct result: the decoder only emits a
# symbol when `fits[L]` says its whole code is in the buffer (folded into
# `hit[L]` in huffman_decoder.sv), so it never consumes more bits than the
# buffer holds and the reader's saturation can no longer be reached from this
# design. It is kept as a contract guard for any other consumer, and listed
# here so the escape is a recorded conclusion rather than an untested corner.
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
