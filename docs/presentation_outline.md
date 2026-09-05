# Presentation outline (20-25 min + 5-10 min questions)

The deck built from this outline is docs/presentation.html (arrow keys or
scroll; Cmd-P prints one slide per page). Every "[VM]" below is now a measured
number in results/ and on the slides; scripts/check_deck_numbers.py recomputes
them.

Structure follows the project flow, as the brief recommends: analysis ->
optimization -> hardware. Slides are numbered; "say" is the talk track.
Numbers marked [VM] come from results/ after the guest runs.

1. Title. Two benchmarks, one accelerator. (30 s)
2. What we chose and why. The 13 candidates in one table: hotspot, software
   headroom, hardware story. pyflate and mdp are the two whose algorithm is in
   the benchmark file and whose hotspot is one identifiable thing; nbody and
   raytrace are the crowd's picks. (1.5 min)
3. Method. py-spy record + FlameGraph for "where" (perf record collects no samples in this guest), py-spy for Python
   frames, cProfile for exact counts, perf stat for "why". The two sysctls
   the guest needs. (1 min)

pyflate (about 9 min)
4. What pyflate does: bzip2 block -> header -> Huffman symbols -> MTF ->
   inverse BWT -> RLE. One block, 148,271 symbols, 6 tables, codes 2..15 bits.
5. Baseline flame graph [VM]. Point at the find_next_symbol tower.
6. The code: the linear scan. Say: it walks the whole sorted table per
   symbol; canonical codes make one compare per length enough.
7. The fix: limit[] / base[] tables, one peek, <=15 compares. Plus the bit
   reader (one read, 8-byte refill), MTF pop/insert, regex RLE.
8. Before / after [VM]: pyperf compare_to table, perf stat counters
   (instructions, IPC). Output byte-identical, md5.
9. What is left (optimized flame graph [VM]): Huffman + bits ~53%, inverse
   BWT ~25% (py-spy samples; cProfile says 51% and 18%). Say: the first is bit-serial work, the second is a pointer
   chase; only the first is a datapath problem.

Accelerator (about 7 min)
10. Block diagram (docs/huffman_accel_block_diagram.svg). Walk left to right:
    tables in, bytes in, 20 parallel compares, priority encoder, base+code,
    symbol memory, symbols out; len feeds the barrel shifter the same cycle.
11. Interface: what moves, what stays; register map in one slide; the one
    function that changes in the software; users' code unchanged.
12. Verification: golden vectors from the real block, testbench result:
    148,271/148,271, 0 errors, 148,272 cycles, 1.000 symbol/cycle.
13. Cost: yosys figures, 18,796 cells (5,441 flops) + 13.9 kbit of symbol SRAM;
    98-level longest path -> ~200 MHz FPGA / ~400 MHz ASIC; the flattened
    49,804-cell version as the "why SRAM" argument.
14. Expected gain: Amdahl with the numbers. ~3,900 CPU cycles per symbol vs
    1; accelerated part ~1.3 ms; whole run ~2.0x over optimized, ~4.8x over
    shipped [VM ratio]. Trade-offs: direct-lookup table vs bit-serial FSM vs
    ours; MTF as the next thing to move; BWT stays.

mdp (about 4 min)
15. What mdp does: state graph, value iteration with bounds, tolerance.
16. Baseline flame graph [VM] + the reason it does not show: dict lookups
    keyed by nested namedtuples inside the sweep; Fractions recomputed.
17. The fix: integer index once, sweep on flat lists with identical
    operation order; memoized getCritDist. Result bit-identical.
18. Before / after [VM].

19. Conclusions (1 min). Algorithm first, then interpreter overhead, then
    hardware for what is bit-serial; memory-bound parts stay where the
    memory is. Repository layout, how to reproduce.
20. Questions we expect (keep answers ready):
    - why not a C extension / the bz2 module: changes the benchmark, not the
      code under test;
    - why the result is bit-identical in mdp: same order of float additions;
    - why not accelerate BWT: one dependent memory access per byte;
    - what happens on a corrupt stream: err, no length matched;
    - how the selector switch is handled: TSEL register or selector SRAM;
    - clock and pipeline depth: 100 levels, can split the compare tree.
