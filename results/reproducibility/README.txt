An independent second run of the two benchmark scripts in the course VM, kept
so the shipped measurements in results/<benchmark>/ can be checked against a
different session rather than taken on trust:

    python3 scripts/compare_runs.py results results/reproducibility

Both sets come from the same guest (Ubuntu 22.04, one vCPU, Xeon E5-2630 v3).
The shipped set is the later run, of commit 8dcd92b, which also carries the
cProfile tables, the table-scan statistics, the per-optimization ablation and
the contention record. The set here is the earlier run, of commit 195dcd8,
made by extracting that commit into an empty directory and running
script_pyflate.sh and script_mdp.sh exactly as a grader would.

Largest wall-clock drift between them: under 1%.

A third run of the same scripts, made while the shared host was busy, is not
included and must not be: it reported mdp at 2.33 s against 1.30 s while
executing the same 31.5 billion instructions, because "CPUs utilized" had
fallen to 0.58. That is what the contention check in both scripts now catches,
and results/<benchmark>/contention.txt records the figure for the runs that
are shipped.
