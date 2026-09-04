#!/usr/bin/env bash
# Mutation test for the testbench: inject one bug at a time into the RTL, run
# the real `make sim`, and report whether the test KILLED it (make failed) or
# let it ESCAPE (make passed). A testbench that cannot fail proves nothing, so
# this is how we know tb_huffman.sv's PASS means something.
#
#   cd hw && tb/mutate.sh
#
# Runs on a scratch copy; the repository files are never modified.
set -euo pipefail
HW=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cp -r "$HW" "$TMP/hw"; cp -r "$HW/../benchmarks" "$TMP/benchmarks"; cp -r "$HW/../scripts" "$TMP/scripts"
cd "$TMP/hw"
make vectors >/dev/null 2>&1 || { echo "cannot build tb/vectors - is python3 available?"; exit 1; }
[ -s tb/vectors/expected.txt ] || { echo "tb/vectors/expected.txt is empty"; exit 1; }

run() {   # run NAME 'sed-expression' FILE
  local name=$1 expr=$2 file=$3
  cp "$file" "$file.orig"; sed -i.bak "$expr" "$file"; rm -f "$file.bak"
  if cmp -s "$file" "$file.orig"; then echo "[$name] mutation did not apply - check the pattern"; mv "$file.orig" "$file"; return; fi
  rm -rf build
  local out rc
  out=$(make sim 2>&1) && rc=0 || rc=$?
  mv "$file.orig" "$file"
  local summary; summary=$(echo "$out" | grep -E 'decoded|errors|PASS|FAIL|TIMEOUT|X on' | tail -2 | tr '\n' ' ' | cut -c1-150)
  if echo "$out" | grep -q 'decoded 0 symbols'; then
    echo "[$name] INVALID  (the run decoded nothing - vectors missing?)  $summary"
  elif [ "$rc" -ne 0 ]; then echo "[$name] KILLED   (make exit $rc)  $summary"
  else                       echo "[$name] ESCAPED  (make exit 0)   $summary"; fi
}

echo "control (no mutation): $( (rm -rf build; make sim 2>&1) | grep -E 'decoded|PASS|FAIL' | tail -1)"
run "symbol output driven to X"         's/sym <= symtab\[tsel\]\[idx\];/sym <= '"'"'x;/'                          rtl/huffman_decoder.sv
run "sym_valid stuck low"               's/sym_valid <= fire \&\& found;/sym_valid <= 1'"'"'b0;/'                rtl/huffman_decoder.sv
run "hit compare < changed to <="       's/code\[L\] < limit_r\[tsel\]\[L\]/code[L] <= limit_r[tsel][L]/'       rtl/huffman_decoder.sv
run "base adder off by one"             's/idx_s = base_r\[tsel\]\[len_c\] + /idx_s = base_r[tsel][len_c] + 1 + /' rtl/huffman_decoder.sv
run "priority encoder direction"        's/for (int L = MAXBITS; L >= 1; L--)/for (int L = 1; L <= MAXBITS; L++)/' rtl/huffman_decoder.sv
run "barrel shift one bit short"        's/buf_d = buf_q << consume;/buf_d = buf_q << (consume - 1);/'          rtl/bitreader.sv
