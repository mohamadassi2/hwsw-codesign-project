#!/usr/bin/env bash
# One command that re-verifies the whole submission from the shipped files:
#   1. both optimizations still produce the original output (pyflate byte-for-byte,
#      mdp to the last bit) and still show a speedup - timed on THIS machine, so the
#      ratio will differ from the VM figures the documents quote,
#   2. every derived number in the two reports recomputes from results/,
#   3. every number on the slides recomputes from results/ and the docs,
#   4. how far the shipped run drifts from the independent rerun in
#      results/reproducibility/ (printed for the reader; compare_runs.py does not fail on it).
# Exit status is non-zero if any of steps 1-3 fails.
set -euo pipefail
cd "$(dirname "$0")/.."
# Prefer the venv the benchmark scripts create; fall back to the system python3
# (every step runs on the standard library alone: local_check.py stubs pyperf when it is absent).
if [ -z "${PY:-}" ]; then
  if [ -x venv/bin/python ]; then PY=venv/bin/python; else PY=python3; fi
fi
# results/RUN_ID.txt fingerprints the run the reports quote. If the benchmarks
# were rerun here the checkers below will flag every figure that moved - that is
# expected, so warn first. Hashing the files (not `git status`) also works when
# the tree came from an archive rather than a clone.
if [ -f results/RUN_ID.txt ]; then
  have=$("$PY" - <<'FP'
import hashlib
fs = ["results/pyflate/pyflate_base.json","results/pyflate/pyflate_opt.json",
      "results/mdp/mdp_base.json","results/mdp/mdp_opt.json",
      "results/pyflate/perfstat_base.txt","results/pyflate/perfstat_opt.txt",
      "results/mdp/perfstat_base.txt","results/mdp/perfstat_opt.txt"]
h = hashlib.md5()
try:
    for f in fs:
        h.update(hashlib.md5(open(f,"rb").read()).hexdigest().encode())
    print(h.hexdigest())
except OSError:
    print("missing")
FP
)
  want=$(grep -v '^#' results/RUN_ID.txt | tr -d '[:space:]')
  if [ "$have" != "$want" ]; then
    echo "note: results/ is not the run the reports quote (fingerprint differs)."
    echo "      The benchmarks have been rerun here, so the figures below will"
    echo "      disagree with the documents by however much the two runs differ."
    echo "      To check the submission as shipped:  git checkout -- results/"
    echo "      To adopt this run:                   python3 scripts/fill_reports.py"
    echo "                                           then update the slides to match."
  fi
fi
echo "== 1/4 optimizations vs originals (speedup timed on this machine; the shipped VM figures are in results/)"; $PY scripts/local_check.py all "${REPS:-3}"
# On success print only a checker's summary line; on failure print the summary
# and the FAIL lines (or the last 20 lines if the checker crashed).
run_gate() {
  local label=$1 script=$2 out
  if out=$("$PY" "$script" 2>&1); then
    echo "$label"; echo "$out" | head -1
  else
    echo "$label"; echo "$out" | grep -E "^PASS|FAIL " || echo "$out" | tail -20
    return 1
  fi
}
run_gate "== 2/4 report numbers" scripts/check_report_numbers.py
run_gate "== 3/4 slide numbers"  scripts/check_deck_numbers.py
echo "== 4/4 drift against the independent rerun (reported, not gated)"; $PY scripts/compare_runs.py results results/reproducibility | tail -1
echo "all checks passed"
