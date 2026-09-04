#!/usr/bin/env python3
"""Re-root folded stacks at a frame, so a flame graph shows the work and not the harness.

py-spy records the whole process stack, which under pyperf means ten frames of
runner and worker before the benchmark's own entry point. Re-rooting drops that
prefix: every stack that passes through the named frame is kept, starting there;
stacks that never reach it (imports, interpreter start-up) are dropped, and the
sample count they held is reported so nothing is silently lost.

  python3 scripts/focus_folded.py bench_pyflake < in.folded > out.folded
"""
import sys


def main(root):
    kept = dropped = 0
    out = []
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line:
            continue
        stack, _, count = line.rpartition(" ")
        try:
            n = int(count)
        except ValueError:
            continue
        frames = stack.split(";")
        hit = next((i for i, f in enumerate(frames) if f.split(" (")[0] == root), None)
        if hit is None:
            dropped += n
            continue
        kept += n
        out.append(";".join(frames[hit:]) + " " + str(n))
    sys.stdout.write("\n".join(out) + "\n")
    total = kept + dropped
    pct = 100.0 * kept / total if total else 0.0
    print(f"{root}: kept {kept} of {total} samples ({pct:.1f}%), dropped {dropped} outside it",
          file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
