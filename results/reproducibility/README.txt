Two further runs of the two benchmark scripts in the course VM, kept so the
shipped measurements in results/<benchmark>/ can be checked against different
sessions rather than taken on trust:

    python3 scripts/compare_runs.py results results/reproducibility

All three sets come from the same guest (Ubuntu 22.04, one vCPU, Xeon
E5-2630 v3). The shipped set is the latest, made on 15 September 2026; the set
here is the earlier of the two kept runs, and a third is under run3/. Each was
made by extracting the tree into an empty directory and running
script_pyflate.sh and script_mdp.sh exactly as a grader would.

Across the three, pyflate's ratio spreads 3.0% (2.32x to 2.39x) and mdp's 2.0%
(3.82x to 3.90x). Section 4.3 of each report gives the table and reads it.

These two runs predate the 15 September revision, so they are a check on the
measurement rather than a byte-identical rerun. Two consequences are visible
here:

  - The perf files in these directories are empty, and perf_event_chosen.txt
    says "none". That is the bug section 2 of report_pyflate.txt describes: the
    event probe tested each capture with `perf script | head -1` under
    `set -o pipefail`, so head exited, perf script died of SIGPIPE, and the
    pipeline reported failure on a capture full of samples. Every capture was
    discarded by the check. The shipped set, made after the fix and as root,
    has these files full. The wall-clock and perf stat numbers in these
    directories were never affected - counting is not sampling.

  - The benchmark code also lost comments and dead code in that revision, and
    mdp now builds its successor rows with a generator expression where these
    runs appended to a list. That one is in the measured path and is part of
    the mdp spread above. What times the benchmarks - the pyperf runner and its
    arguments - is unchanged, and the decoders produce the same output, so the
    wall clocks are comparable.

A further run, made while the shared host was busy, is not included and must
not be: it reported mdp at 2.33 s against 1.30 s while executing the same 31.5
billion instructions, because "CPUs utilized" had fallen to 0.58. That is what
the contention check in both scripts now catches, and
results/<benchmark>/contention.txt records the figure for the runs that are
shipped.
