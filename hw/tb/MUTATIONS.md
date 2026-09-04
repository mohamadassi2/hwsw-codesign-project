# Mutation test of hw/tb/tb_huffman.sv

A testbench that cannot fail proves nothing. Each row injects one bug into the
RTL, runs the real `make sim`, and records whether the test caught it (make
exits non-zero, because the testbench calls $fatal on any error or timeout).
Reproduce with `cd hw && tb/mutate.sh` (about 25 minutes on a laptop).

| mutation | verdict | make exit | what the testbench printed |
|---|---|---|---|
| control | **PASS** | 0 | `decoded 148271 symbols in 148272 cycles (1.000 symbols/cycle), 0 errors PASS` |
| sym driven to X | **KILLED** | 2 | `decoded 148271 symbols in 148272 cycles (1.000 symbols/cycle), 148271 errors FAIL (148271 errors)` |
| sym_valid stuck low | **KILLED** | 2 | `TIMEOUT: decoded 0/148271 symbols FAIL (timeout)` |
| hit compare < to <= | **KILLED** | 2 | `decoded 148271 symbols in 148272 cycles (1.000 symbols/cycle), 241318 errors FAIL (241318 errors)` |
| base adder +1 | **KILLED** | 2 | `decoded 148271 symbols in 148272 cycles (1.000 symbols/cycle), 148271 errors FAIL (148271 errors)` |
| priority encoder direction reversed | **KILLED** | 2 | `TIMEOUT: decoded 35694/148271 symbols FAIL (timeout)` |
| barrel shift one bit short | **KILLED** | 2 | `TIMEOUT: decoded 136558/148271 symbols FAIL (timeout)` |

**6 of 6 mutations killed.**

Before the testbench was hardened, the first two rows PASSED: a decoder that
emitted nothing but X was invisible because `sym != expected` evaluates to X
when `sym` is X, and `if (X)` is false; and a stalled decoder simply hit the
watchdog, which printed a message and exited 0. The comparisons are now `!==`,
X on `sym` or `len` is counted as an error, a timeout is a failure, and
`make sim` exits non-zero on failure. The remaining rows are logic bugs in the
datapath; they show the test checks the decode itself, not just the plumbing.

Re-run in full on the shipped testbench after it was reworked to run on Icarus
Verilog 11 (packed line buffer for $fgets, plain always blocks, explicit
sensitivity lists for the stimulus): control passes, all six mutations are
still killed with the same outcomes. The RTL was not touched by those changes.
