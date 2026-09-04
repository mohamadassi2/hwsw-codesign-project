#!/usr/bin/env python3
"""Turn the yosys stat/ltp files written by synth.ys into docs/synthesis_yosys.txt."""
import re, subprocess, sys, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ver = subprocess.run(["yosys", "-V"], capture_output=True, text=True).stdout.strip().split("(")[0].strip()
nomap = open("build/stat_nomap.txt").read(); flat = open("build/stat_flat.txt").read(); ltp = open("build/ltp.txt").read()
def cells(s): return int(re.search(r"^\s+(\d+)\s+cells$", s, re.M).group(1))
def breakdown(s):
    return "\n".join(l.rstrip() for l in s.splitlines() if re.match(r"^\s+\d+\s+\$", l))
depth = int(re.search(r"length=(\d+)", ltp).group(1))
ff = sum(int(m.group(1)) for m in re.finditer(r"^\s+(\d+)\s+\$_DFF", nomap, re.M))
print(f"""# Generic synthesis of huffman_accel_top, tables kept as memories.
# {ver}. Flow: hw/synth.ys (read_verilog -sv; hierarchy; proc; flatten; opt;
# memory -nomap; techmap; abc -g <2-input gates + MUX>; opt_clean; stat; ltp -noff).
# Regenerate with `make synth` in hw/.

=== tables kept as memories (the proposed design) ===
{cells(nomap)} cells
{breakdown(nomap)}

Longest combinational path (ltp -noff): length={depth}
{ff} flip-flops
# (ltp -noff: the path stops at flip-flops, so this is the combinational depth
#  between registers: peek -> 20 parallel comparators -> priority encoder ->
#  base+code adder -> symbol memory address.)

# Memory bits (6 banks): limit 126 x 21 = 2,646; base 126 x 22 = 2,772;
# symbols 1,548 x 9 = 13,932; total 19,350 bits, about 19.4 kbit (2.4 KB) of SRAM.

=== the alternative: the same tables flattened into logic (memory_map) ===
{cells(flat)} cells
{breakdown(flat)}
""")
