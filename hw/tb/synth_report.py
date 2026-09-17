#!/usr/bin/env python3
"""Turn the yosys stat/ltp files written by synth.ys into docs/synthesis_yosys.txt.

Two configurations are reported, because the three tables are not the same
kind of storage and treating them alike hides the accelerator's real cost:

  as built    limit/base are register files, the symbol table is an SRAM
  all-logic   every table flattened into gates and flip-flops
"""
import glob, hashlib, os, re, subprocess
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))       # hw/
ver = subprocess.run([os.environ.get("YOSYS", "yosys"), "-V"], capture_output=True, text=True).stdout.strip().split("(")[0].strip()
asb  = open("build/stat_asbuilt.txt").read()
flat = open("build/stat_flat.txt").read()
ltp  = open("build/ltp.txt").read()

def cells(s):   return int(re.search(r"^\s+(\d+)\s+cells$", s, re.M).group(1))
def ffs(s):     return sum(int(m.group(1)) for m in re.finditer(r"^\s+(\d+)\s+\$_DFF", s, re.M))
def mems(s):
    m = re.search(r"^\s+(\d+)\s+\$mem_v2$", s, re.M)
    return int(m.group(1)) if m else 0
def gates(s):   # every $_ cell that is not a flip-flop
    return sum(int(m.group(1)) for m in re.finditer(r"^\s+(\d+)\s+\$_(?!DFF)(?!mem)(?!scopeinfo)", s, re.M))
def breakdown(s):
    return "\n".join(l.rstrip() for l in s.splitlines() if re.match(r"^\s+\d+\s+\$", l))
depth = int(re.search(r"length=(\d+)", ltp).group(1))
end = [l for l in ltp.splitlines() if l.strip().startswith("ff:")]
endpoint = end[0].split("(via")[0].replace("ff:", "").strip() if end else "a flip-flop"

# Stamp the RTL these figures describe; scripts/check_report_numbers.py
# recomputes the same fingerprint and fails if the file is stale.
rtl_files = sorted(glob.glob("rtl/*.sv"))
fp = hashlib.md5()
for path in rtl_files:
    fp.update(hashlib.md5(open(path, "rb").read()).hexdigest().encode())

print(f"""# Generic synthesis of huffman_accel_top with {ver}.
# RTL fingerprint: {fp.hexdigest()}  ({len(rtl_files)} files under hw/rtl/)
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
# The path runs from tsel through the table lookups to {endpoint}, the enable of
# the sticky error flag. That enable is evaluated on every clock, so this is a
# real single-cycle path: how often the host reads `err` does not enter into it.
# Nor is it an outlier. Two separate ltp runs on modified copies of the RTL,
# not part of this flow: cutting that one condition leaves 97 levels ending at
# sym_valid, the symbol-rate path itself, and moving idx_ok onto the len path
# instead of the register write takes it to 119 - which is why the RTL keeps it
# off. The depth is inherent to the lookup, not an artefact of the error flag. What the
# simulation establishes is throughput, one symbol per cycle for all 148,271
# symbols; the clock this depth would support is a separate question, and
# section 5.7 of report_pyflate.txt says what the frequency estimate assumes.

# Table storage: limit 6 x 21 rows x 21 bits = 2,646 and base 6 x 21 x 22 =
# 2,772 bits are the register files above; symbols 6 x 258 x 9 = 13,932 bits,
# about 13.9 kbit (1.7 KB), is the SRAM.


=== 2. every table flattened into logic (memory_map) ===
{cells(flat)} cells: {ffs(flat)} flip-flops, {gates(flat)} gates
# The other extreme: even the symbol table becomes gates and flops.
{breakdown(flat)}
""")
