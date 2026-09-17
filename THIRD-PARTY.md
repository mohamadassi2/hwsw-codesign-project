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
   every SVG it writes, so each of the twenty flame graphs under results/ -
   twelve for the shipped run, eight under results/reproducibility/ - contains
   roughly 11 kB of Brendan Gregg's code. That code is his, under the CDDL, and is present here
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

6. IBM Plex - the five font faces embedded in docs/presentation.html
   ------------------------------------------------------------------
   The deck sets its type in IBM Plex. It used to fetch the faces from Google
   Fonts at load time, which meant a lecture-room machine with no network would
   have shown the talk in Arial. They are now embedded in the file as base64
   woff2, so docs/presentation.html renders identically with no network at all:

       IBM Plex Sans            weight 400-700  variable  40,240 bytes
       IBM Plex Sans Condensed  weight 700                14,004 bytes
       IBM Plex Mono            weight 400                10,052 bytes
       IBM Plex Mono            weight 600                10,120 bytes
       IBM Plex Mono            weight 700                10,128 bytes

   These are the latin subsets Google Fonts serves for those weights, taken
   unmodified. They are the five the slides actually render: every element in
   the deck was walked and its computed (family, weight) recorded, which is also
   how we found that the old Google request asked for three weights nothing uses
   and omitted the two bold faces 23 elements do use - so <strong> and <code>
   had been rendering in synthetic bold.

   IBM Plex is licensed under the SIL Open Font License 1.1, which requires the
   copyright notice and the licence to travel with the font. Both are below.

   Copyright © 2017 IBM Corp. with Reserved Font Name "Plex"

   This Font Software is licensed under the SIL Open Font License, Version 1.1.

   This license is copied below, and is also available with a FAQ at: http://scripts.sil.org/OFL


   -----------------------------------------------------------
   SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
   -----------------------------------------------------------

   PREAMBLE
   The goals of the Open Font License (OFL) are to stimulate worldwide
   development of collaborative font projects, to support the font creation
   efforts of academic and linguistic communities, and to provide a free and
   open framework in which fonts may be shared and improved in partnership
   with others.

   The OFL allows the licensed fonts to be used, studied, modified and
   redistributed freely as long as they are not sold by themselves. The
   fonts, including any derivative works, can be bundled, embedded,
   redistributed and/or sold with any software provided that any reserved
   names are not used by derivative works. The fonts and derivatives,
   however, cannot be released under any other type of license. The
   requirement for fonts to remain under this license does not apply
   to any document created using the fonts or their derivatives.

   DEFINITIONS
   "Font Software" refers to the set of files released by the Copyright
   Holder(s) under this license and clearly marked as such. This may
   include source files, build scripts and documentation.

   "Reserved Font Name" refers to any names specified as such after the
   copyright statement(s).

   "Original Version" refers to the collection of Font Software components as
   distributed by the Copyright Holder(s).

   "Modified Version" refers to any derivative made by adding to, deleting,
   or substituting -- in part or in whole -- any of the components of the
   Original Version, by changing formats or by porting the Font Software to a
   new environment.

   "Author" refers to any designer, engineer, programmer, technical
   writer or other person who contributed to the Font Software.

   PERMISSION & CONDITIONS
   Permission is hereby granted, free of charge, to any person obtaining
   a copy of the Font Software, to use, study, copy, merge, embed, modify,
   redistribute, and sell modified and unmodified copies of the Font
   Software, subject to the following conditions:

   1) Neither the Font Software nor any of its individual components,
   in Original or Modified Versions, may be sold by itself.

   2) Original or Modified Versions of the Font Software may be bundled,
   redistributed and/or sold with any software, provided that each copy
   contains the above copyright notice and this license. These can be
   included either as stand-alone text files, human-readable headers or
   in the appropriate machine-readable metadata fields within text or
   binary files as long as those fields can be easily viewed by the user.

   3) No Modified Version of the Font Software may use the Reserved Font
   Name(s) unless explicit written permission is granted by the corresponding
   Copyright Holder. This restriction only applies to the primary font name as
   presented to the users.

   4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
   Software shall not be used to promote, endorse or advertise any
   Modified Version, except to acknowledge the contribution(s) of the
   Copyright Holder(s) and the Author(s) or with their explicit written
   permission.

   5) The Font Software, modified or unmodified, in part or in whole,
   must be distributed entirely under this license, and must not be
   distributed under any other license. The requirement for fonts to
   remain under this license does not apply to any document created
   using the Font Software.

   TERMINATION
   This license becomes null and void if any of the above conditions are
   not met.

   DISCLAIMER
   THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
   EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
   MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
   OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
   COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
   INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
   DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
   FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
   OTHER DEALINGS IN THE FONT SOFTWARE.
