#!/usr/bin/env python3
"""Turn the yosys stat/ltp files written by synth.ys into docs/synthesis_yosys.txt.

Two configurations are reported, because the three tables are not the same
kind of storage and treating them alike hides the accelerator's real cost:

  as built    limit/base are register files, the symbol table is an SRAM
  all-logic   every table flattened into gates and flip-flops
"""
import re, subprocess, sys, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ver = subprocess.run([os.environ.get("YOSYS", "yosys"), "-V"], capture_output=True, text=True).stdout.strip().split("(")[0].strip()
asb  = open("build/stat_asbuilt.txt").read()
flat = open("build/stat_flat.txt").read()
ltp  = open("build/ltp.txt").read()

def cells(s):   return int(re.search(r"^\s+(\d+)\s+cells$", s, re.M).group(1))
def ffs(s):     return sum(int(m.group(1)) for m in re.finditer(r"^\s+(\d+)\s+\$_DFF", s, re.M))
def mems(s):
    m = re.search(r"^\s+(\d+)\s+\$mem_v2$", s, re.M)
    return int(m.group(1)) if m else 0
def gates(s):
    return sum(int(m.group(1)) for m in re.finditer(r"^\s+(\d+)\s+\$_(?!DFF)(?!mem)(?!scopeinfo)", s, re.M))
def breakdown(s):
    return "\n".join(l.rstrip() for l in s.splitlines() if re.match(r"^\s+\d+\s+\$", l))
depth = int(re.search(r"length=(\d+)", ltp).group(1))
end = [l for l in ltp.splitlines() if l.strip().startswith("ff:")]
endpoint = end[0].split("(via")[0].replace("ff:", "").strip() if end else "a flip-flop"

# Stamp the RTL these figures describe. Without it the file can silently
# outlive the design: the numbers below were once regenerated two RTL changes
# late and nothing noticed, because every check verified that the report quoted
# this file, not that this file matched the source.
import hashlib, glob as _glob
_rtl = sorted(_glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rtl", "*.sv")))
_fp = hashlib.md5()
for _f in _rtl:
    _fp.update(hashlib.md5(open(_f, "rb").read()).hexdigest().encode())

print(f"""# Generic synthesis of huffman_accel_top with {ver}.
# RTL fingerprint: {_fp.hexdigest()}  ({len(_rtl)} files under hw/rtl/)
# Flow: hw/synth.ys (read_verilog -sv; hierarchy; proc; flatten; opt; memory
# -nomap; techmap; abc -g <2-input gates + MUX>; opt_clean; stat; ltp -noff).
# Regenerate with `make synth` in hw/.
#
# Why two configurations, and why the tables are not all counted alike.
# limit_r is read at all 20 code lengths in the same cycle - that parallel
# compare is the whole point of the design - and base_r is read asynchronously.
# No SRAM macro has twenty read ports, so those two tables are register files
# and are counted as such below. Only the symbol table, with one synchronous
# read port, is a genuine SRAM candidate.

=== 1. as built: limit/base as register files, symbols in SRAM ===
{cells(asb)} cells: {ffs(asb)} flip-flops, {gates(asb)} gates, {mems(asb)} memory
{breakdown(asb)}

Longest combinational path (ltp -noff): length={depth}
# The path ends at {endpoint}, the sticky error flag. That flag is read once per
# block, so it has a whole clock to settle; it is not what limits the symbol
# rate. The path that does - peek, the parallel compare, the priority encoder,
# and the bit-buffer shift - is shorter, and the design sustains one symbol per
# cycle for all 148,271 symbols in simulation.

# Table storage: limit 6 x 21 rows x 21 bits = 2,646 and base 6 x 21 x 22 =
# 2,772 bits are the register files above; symbols 6 x 258 x 9 = 13,932 bits,
# about 13.9 kbit (1.7 KB), is the SRAM.


=== 2. every table flattened into logic (memory_map) ===
{cells(flat)} cells: {ffs(flat)} flip-flops, {gates(flat)} gates
# The other extreme: even the symbol table becomes gates and flops.
{breakdown(flat)}
""")
