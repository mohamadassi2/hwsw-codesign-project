An earlier, independent run of the same scripts in the same course VM
(Ubuntu 22.04 guest, one vCPU, Xeon E5-2630 v3), kept so the shipped
measurements in results/<benchmark>/ can be checked against a second run:

    python3 scripts/compare_runs.py results results/reproducibility

The shipped set is the later run, made from a clean directory by the scripts
in this repository; this set was made from the same scripts before the
directory-clearing line was added to them (comment and clearing differences
only - the measurement commands are identical).
