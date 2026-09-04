An independent rerun of commit 195dcd8 of this repository, made by
extracting it into an empty directory in the course VM (Ubuntu 22.04 guest,
one vCPU, Xeon E5-2630 v3) and running script_pyflate.sh and script_mdp.sh
exactly as a grader would. Kept so the shipped measurements in
results/<benchmark>/ can be checked against a second run:

    python3 scripts/compare_runs.py results results/reproducibility
