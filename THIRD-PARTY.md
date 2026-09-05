Third-party code in this repository
===================================

This is coursework (Technion 00460882). The analysis, the optimizations, the
SystemVerilog accelerator, the testbench, the scripts and the reports are our
own. The files below are not, and are redistributed here under their own terms.


1. pyperformance - benchmarks/pyflate/run_benchmark.py,
                   benchmarks/mdp/run_benchmark.py
   ------------------------------------------------------------------
   Vendored unmodified from the pyperformance benchmark suite (bm_pyflate and
   bm_mdp) so that the optimized versions beside them can be compared against
   exactly what the suite ships. They are byte-identical to the files
   pyperformance installs, which can be checked directly:

       benchmarks/pyflate/run_benchmark.py   md5 71491b1c3bdfef2ce281a7cb4d583303
       benchmarks/mdp/run_benchmark.py       md5 b92d737d20a2bd81d360de1c666b2ed0

   pyperformance is distributed under the MIT licence, reproduced in full below.

   benchmarks/pyflate/run_benchmark_opt.py and benchmarks/mdp/run_benchmark_opt.py
   are our modifications of those files and are therefore derivative works
   covered by the same terms.

   ---- pyperformance, The MIT License ----
   The MIT License
   
   Permission is hereby granted, free of charge, to any person
   obtaining a copy of this software and associated documentation
   files (the "Software"), to deal in the Software without
   restriction, including without limitation the rights to use,
   copy, modify, merge, publish, distribute, sublicense, and/or
   sell copies of the Software, and to permit persons to whom the
   Software is furnished to do so, subject to the following conditions:
   
   The above copyright notice and this permission notice shall be included
   in all copies or substantial portions of the Software.
   
   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
   OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
   THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
   FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
   DEALINGS IN THE SOFTWARE.

2. pyflate - the code inside bm_pyflate
   ------------------------------------------------------------------
   The bzip2/DEFLATE decoder that benchmark contains is Paul Sladen's pyflate.
   Its own header, preserved verbatim in both copies of the file, reads:

       Copyright 2006--2007-01-21 Paul Sladen
       http://www.paul.sladen.org/projects/compression/
       You may use and distribute this code under any DFSG-compatible
       license (eg. BSD, GNU GPLv2).

3. FlameGraph - not vendored as source, but its JavaScript ships in the SVGs
   ------------------------------------------------------------------
   script_pyflate.sh and script_mdp.sh clone Brendan Gregg's FlameGraph tools
   at run time to render the .folded stack files; the flamegraph.pl source is
   not stored here. The rendered flame graphs under results/ are another
   matter: flamegraph.pl embeds its own interactive search/zoom JavaScript in
   every SVG it writes, so each results/*/flame_*.svg contains roughly 11 kB of
   Brendan Gregg's code. That code is his, under the CDDL, and is present here
   only as the output of running his tool.
   https://github.com/brendangregg/FlameGraph

4. Prior art the accelerator draws on - no code copied
   ------------------------------------------------------------------
   The limit[]/base[] formulation of canonical Huffman decoding used in
   benchmarks/pyflate/run_benchmark_opt.py and in hw/rtl/huffman_decoder.sv is
   the standard one, described in the DEFLATE specification (RFC 1951) and
   implemented in zlib's reference decoder puff.c. We wrote both from the
   description; no code was taken from either.

5. The benchmark input
   ------------------------------------------------------------------
   benchmarks/pyflate/data/interpreter.tar.bz2 ships with pyperformance and is
   redistributed unmodified as the benchmark's input.
