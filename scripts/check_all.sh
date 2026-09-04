#!/usr/bin/env bash
# One command that re-verifies the whole submission from the shipped files:
#   1. both optimizations still produce the original output (pyflate byte-for-byte,
#      mdp to the last bit) and still show their speedup,
#   2. every derived number in the two reports recomputes from results/,
#   3. every number on the slides recomputes from results/ and the docs.
# Exit status is non-zero if anything fails.
set -euo pipefail
cd "$(dirname "$0")/.."
# Prefer the venv the benchmark scripts create; fall back to the system python3
# (steps 2 and 3 need only the standard library, step 1 needs pyperf).
if [ -z "${PY:-}" ]; then
  if [ -x venv/bin/python ]; then PY=venv/bin/python; else PY=python3; fi
fi
echo "== 1/3 optimizations vs originals"; $PY scripts/local_check.py all "${REPS:-3}"
echo "== 2/3 report numbers";            $PY scripts/check_report_numbers.py | head -1
echo "== 3/3 slide numbers";             $PY scripts/check_deck_numbers.py   | head -1
echo "== drift against the independent run"; $PY scripts/compare_runs.py results results/reproducibility | tail -1
echo "all checks passed"
