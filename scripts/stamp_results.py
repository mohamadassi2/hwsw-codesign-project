#!/usr/bin/env python3
"""Refresh results/RUN_ID.txt and results/CODE_ID.txt after a re-measure.

RUN_ID fingerprints the measurement files the reports quote; CODE_ID
fingerprints the benchmark code and scripts that produced them. Both use the
same formulas as scripts/check_all.sh and scripts/check_report_numbers.py.

    python3 scripts/stamp_results.py
"""
import hashlib, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RUN_FILES = ["results/pyflate/pyflate_base.json", "results/pyflate/pyflate_opt.json",
             "results/mdp/mdp_base.json", "results/mdp/mdp_opt.json",
             "results/pyflate/perfstat_base.txt", "results/pyflate/perfstat_opt.txt",
             "results/mdp/perfstat_base.txt", "results/mdp/perfstat_opt.txt"]
CODE_FILES = ["benchmarks/pyflate/run_benchmark.py", "benchmarks/pyflate/run_benchmark_opt.py",
              "benchmarks/mdp/run_benchmark.py", "benchmarks/mdp/run_benchmark_opt.py",
              "script_pyflate.sh", "script_mdp.sh"]


def md5_of_md5s(files):
    h = hashlib.md5()
    for f in files:
        h.update(hashlib.md5(open(os.path.join(ROOT, f), "rb").read()).hexdigest().encode())
    return h.hexdigest()


def stamp(path, digest):
    """Keep the file's comment header, replace the hash line."""
    p = os.path.join(ROOT, path)
    header = [l for l in open(p)] if os.path.exists(p) else []
    header = [l for l in header if l.startswith("#")]
    open(p, "w").write("".join(header) + digest + "\n")
    print(f"{path}: {digest}")


if __name__ == "__main__":
    stamp("results/RUN_ID.txt", md5_of_md5s(RUN_FILES))
    stamp("results/CODE_ID.txt", md5_of_md5s(CODE_FILES))
