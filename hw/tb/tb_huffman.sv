// tb_huffman.sv -- drives the accelerator with the benchmark's real bzip2 block.
//
// Reads the vectors produced by gen_vectors.py, programs the six tables,
// streams the compressed bytes through the bit reader 32 bits at a time,
// drives `tsel` per symbol from the recorded selector sequence, and checks
// every decoded (symbol, code length) against the software decoder.
// The +bp, +last_level, +bubble, +expect_err and +expect_underrun modes are
// explained at their declarations below; hw/Makefile has the target that runs each.
`timescale 1ns/1ps
module tb_huffman;
    localparam int MAXBITS = 20, NSYM = 258, SYMW = 9, NTAB = 6, INW = 32;
    localparam int MAXSYM  = 200000, MAXBYTES = 80000;

    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;                       // 100 MHz simulation clock

    // DUT ports
    logic               tbl_we = 0, tbl_kind = 0;
    logic [2:0]         tbl_sel = 0;
    logic [4:0]         tbl_len = 0;
    logic [MAXBITS:0]   tbl_limit = 0;
    logic signed [MAXBITS+1:0] tbl_base = 0;
    logic [8:0]         tbl_idx = 0;
    logic [SYMW-1:0]    tbl_sym = 0;
    logic [INW-1:0]     in_data;              // driven by assigns below
    logic               in_valid, in_ready, in_last;
    logic               run, sym_valid, err;
    logic               run_en = 0;
    logic [2:0]         tsel;
    logic [SYMW-1:0]    sym;
    logic               out_ready;
    logic               busy, done, underrun;
    logic [31:0]        sym_count;
    logic [6:0]         level;
    // +bp gates out_ready and in_valid pseudo-randomly, to prove the handshakes
    // hold under backpressure. It changes the cycle count by construction, so
    // the throughput check below is only made in the default (full-rate) mode.
    logic               bp_mode = 0;
    // Directed modes for the failure paths. The real bzip2 block is well
    // formed, so err and underrun never assert on it; these run the decoder
    // past the last good symbol on a purpose-built stream and require the
    // corresponding flag to come up.
    logic               want_err = 0, want_underrun = 0;
    // +last_level drives LAST the way a register-mapped host would: set once,
    // held, and therefore high across cycles in which the producer has nothing
    // to hand over. The accelerator must not read that as end of input.
    logic               last_level = 0;
    // +bubble stalls the producer for a long, deterministic run of cycles just
    // before the final word is handed over. That is the one shape that tells a
    // correct end-of-input condition from one that also fires on `LAST` while
    // the producer simply has nothing ready.
    logic               bubble_mode = 0;
    int                 bubble = 0;
    logic               bubbled = 0;
    logic [15:0]        lfsr = 16'hACE1;

    huffman_accel_top #(.MAXBITS(MAXBITS), .NSYM(NSYM), .SYMW(SYMW), .NTAB(NTAB), .INW(INW)) dut (
        .clk(clk), .rst_n(rst_n),
        .tbl_we(tbl_we), .tbl_sel(tbl_sel), .tbl_kind(tbl_kind), .tbl_len(tbl_len),
        .tbl_limit(tbl_limit), .tbl_base(tbl_base), .tbl_idx(tbl_idx), .tbl_sym(tbl_sym),
        .in_data(in_data), .in_valid(in_valid), .in_ready(in_ready), .in_last(in_last),
        .run(run), .tsel(tsel), .sym(sym), .sym_valid(sym_valid), .out_ready(out_ready),
        .err(err), .len_valid(), .level(level),
        .busy(busy), .done(done), .underrun(underrun), .sym_count(sym_count));

    // 16-bit Galois LFSR: deterministic, so a +bp run is reproducible.
    always @(posedge clk) lfsr <= lfsr[0] ? ((lfsr >> 1) ^ 16'hB400) : (lfsr >> 1);
    always @(bp_mode, lfsr) out_ready = bp_mode ? lfsr[3] : 1'b1;

    // ---- golden data ---------------------------------------------------------
    int exp_tsel [0:MAXSYM-1];
    int exp_sym  [0:MAXSYM-1];
    int exp_len  [0:MAXSYM-1];
    logic [7:0]  bytes [0:MAXBYTES-1];
    logic [31:0] words [0:MAXBYTES/4+1];
    int nsym, nbytes, skip_bits, nwords;

    // ---- bookkeeping ---------------------------------------------------------
    int widx = 0;          // next input word
    int ndec = 0;          // symbols whose length has been consumed
    int nchk = 0;          // symbols checked at the output
    int errors = 0;
    longint cycles = 0;
    longint bits_consumed = 0;      // accumulated from the DUT, not from the golden file
    int first_cycle = -1, last_cycle = -1;
    logic err_d = 0, underrun_d = 0;
    logic sv_d = 0, or_d = 0;
    int halt_ndec, halt_nchk; longint halt_bits;
    logic [SYMW-1:0] sym_d = 0;

    // input stream: present word widx while any remain
    // Stimulus as plain Verilog-2001 processes with explicit sensitivity lists.
    // Two things the course VM's Icarus Verilog 11.0 cannot simulate: an @*
    // block that reads a word of a large array with a variable index (the whole
    // array lands on the sensitivity list and vvp aborts), and a ?: in a
    // continuous assignment over SystemVerilog int variables (vvp aborts with
    // "recv_real not implemented"). Listing the scalar inputs explicitly avoids
    // both; the behaviour is the same as an @* block.
    // Armed combinationally: registering it costs a cycle, and with a 64-bit
    // buffer and 32-bit words the reader has already taken the final word by
    // then, so the stall lands after the moment it was meant to test.
    wire arm_bubble = bubble_mode && !bubbled && (widx == nwords - 1);
    always @(widx, nwords, run, bp_mode, lfsr, last_level, bubble, arm_bubble) begin
        in_valid = (widx < nwords) && run && (!bp_mode || lfsr[7])
                   && (bubble == 0) && !arm_bubble;
        in_data  = words[widx];
        // LAST accompanies the final beat. Held as a level from the final word
        // onwards it would flush during table programming, when run is low and
        // in_valid is therefore low, for any stream short enough to be one word.
        in_last  = last_level ? (widx >= nwords - 1) : ((widx == nwords - 1) && in_valid);
    end
    always @(posedge clk) if (in_valid && in_ready) widx <= widx + 1;
    // Stall once, on reaching the last word, for long enough that a premature
    // flush has time to poison the reader before the word arrives.
    always @(posedge clk) begin
        if (!rst_n) begin bubble <= 0; bubbled <= 1'b0; end
        else if (arm_bubble) begin bubble <= 40; bubbled <= 1'b1; end
        else if (bubble > 0) bubble <= bubble - 1;
    end

    // selector for the symbol about to be decoded
    int cur_tsel;
    always @(ndec, nsym, run_en, want_err, want_underrun, err, underrun) begin
        cur_tsel = (ndec < nsym) ? exp_tsel[ndec] : 0;
        tsel     = cur_tsel[2:0];
        // Normally stop once every expected symbol has been consumed. In the
        // directed failure modes keep going into the bad tail until the flag
        // the test is about actually asserts (or the watchdog fires).
        // Keep driving the engine after err in the directed error test: a
        // decode error is claimed to HALT the decoder, and that is only a
        // testable claim if the enable stays asserted afterwards.
        if (want_err)           run = run_en;
        else if (want_underrun) run = run_en && !underrun;
        else                    run = run_en && (ndec < nsym);
    end

    // count consumed lengths and check them
    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (dut.len_valid) begin
            if (first_cycle < 0) first_cycle = cycles;
            bits_consumed <= bits_consumed + dut.len;
            // The contract that makes end-of-stream safe: a symbol may only be
            // emitted when its whole code is really in the buffer. Anything
            // else is a symbol invented out of the zero padding.
            if (dut.len > level) begin
                errors++;
                if (errors < 10)
                    $display("PROTOCOL: consumed %0d bits with only %0d in the buffer, at symbol %0d",
                             dut.len, level, ndec);
            end
            // The directed failure tests deliberately run past the last good
            // symbol into a bad tail, and there is nothing to compare there.
            if (ndec >= nsym) ; else
            // !== so an X compares as a difference; with != an all-X decoder
            // makes every check evaluate to x, which `if` treats as false and
            // the whole run passes with zero errors.
            if (^dut.len === 1'bx) begin
                errors++;
                if (errors < 10) $display("X on len at symbol %0d", ndec);
            end else if (dut.len !== exp_len[ndec]) begin
                errors++;
                if (errors < 10) $display("LEN MISMATCH at symbol %0d: got %0d expected %0d (tsel %0d)",
                                          ndec, dut.len, exp_len[ndec], tsel);
            end
            ndec <= ndec + 1;
        end
        if (sym_valid && out_ready) begin
            if (nchk >= nsym) ; else
            if (^sym === 1'bx) begin
                errors++;
                if (errors < 10) $display("X on sym at symbol %0d (an unprogrammed table bank looks like this)", nchk);
            end else if (sym !== exp_sym[nchk]) begin
                errors++;
                if (errors < 10) $display("SYM MISMATCH at symbol %0d: got %0d expected %0d",
                                          nchk, sym, exp_sym[nchk]);
            end
            nchk <= nchk + 1;
            last_cycle = cycles;
        end
        // err and underrun are sticky, so count the RISING EDGE, not the level.
        // Protocol: a symbol offered while the consumer is not ready must still
        // be there, unchanged, on the next cycle. Without this check out_ready
        // can be ignored entirely and every test still passes.
        sv_d  <= sym_valid;
        or_d  <= out_ready;
        sym_d <= sym;
        if (sv_d && !or_d) begin
            if (sym_valid !== 1'b1 || sym !== sym_d) begin
                errors++;
                if (errors < 10)
                    $display("PROTOCOL: a stalled symbol was dropped or changed at symbol %0d", nchk);
            end
        end
        // DONE means the block is finished: it must not assert while symbols are
        // still expected.
        if (done && nchk < nsym && !want_err && !want_underrun) begin
            errors++;
            if (errors < 10)
                $display("PROTOCOL: done asserted with %0d of %0d symbols still to come", nchk, nsym);
        end
        err_d      <= err;
        underrun_d <= underrun;
        if (err && !err_d) begin
            if (!want_err) errors++;
            $display("DECODER ERR at symbol %0d (no code length matched, or the index left the table)%0s",
                     ndec, want_err ? " - expected by this test" : "");
        end
        if (underrun && !underrun_d) begin
            if (!want_underrun) errors++;
            $display("UNDERRUN at symbol %0d: a code ran past the end of the stream%0s",
                     ndec, want_underrun ? " - expected by this test" : "");
        end
    end

    // ---- main -----------------------------------------------------------------
    int fd, code, t, l, lim, bas, idx, s, i, w, bpos, b;
    // Icarus Verilog 11 (the course VM's version) accepts only a packed vector as
    // $fgets's target; a SystemVerilog `string` is rejected at run time. The
    // vector files' lines are all far shorter than 256 characters.
    reg [8*256-1:0] line;
    initial begin
        // meta
        fd = $fopen("tb/vectors/meta.txt", "r");
        if (fd == 0) begin
            $display("FAIL: cannot open tb/vectors/meta.txt (run from hw/ after gen_vectors.py)");
            $fatal(1);
        end
        bp_mode       = $test$plusargs("bp");
        want_err      = $test$plusargs("expect_err");
        want_underrun = $test$plusargs("expect_underrun");
        last_level    = $test$plusargs("last_level");
        bubble_mode   = $test$plusargs("bubble");
        if (bubble_mode) $display("producer stalls for 40 cycles before handing over the final word");
        if (last_level) $display("host style: LAST held as a level, with bubbles from the producer");
        if (bp_mode) $display("backpressure mode: out_ready and in_valid are gated pseudo-randomly");
        if (want_err) $display("directed mode: the stream ends in a code that matches nothing; err must assert");
        if (want_underrun) $display("directed mode: the stream ends short of a whole code; underrun must assert");
        while ($fgets(line, fd)) begin
            if ($sscanf(line, "skip_bits=%d", skip_bits) == 1) ;
            else if ($sscanf(line, "nsym=%d", nsym) == 1) ;
            else if ($sscanf(line, "nbytes=%d", nbytes) == 1) ;
        end
        $fclose(fd);
        // expected symbols
        fd = $fopen("tb/vectors/expected.txt", "r");
        i = 0;
        while ($fgets(line, fd) && i < MAXSYM) begin
            if ($sscanf(line, "%d %d %d", t, s, l) == 3) begin
                exp_tsel[i] = t; exp_sym[i] = s; exp_len[i] = l; i++;
            end
        end
        $fclose(fd);
        // A testbench with no vectors would otherwise "pass": wait(nchk==nsym)
        // returns at once for nsym==0 and errors stays 0. Refuse to run instead.
        if (i != nsym) begin
            $display("FAIL: expected.txt has %0d lines, meta.txt says %0d", i, nsym);
            $fatal(1);
        end
        if (nsym == 0) begin
            $display("FAIL: no expected symbols - run gen_vectors.py first");
            $fatal(1);
        end
        // compressed bytes -> 32-bit words, starting at bit `skip_bits`
        $readmemh("tb/vectors/stream.hex", bytes, 0, nbytes - 1);   // exactly the bytes the file holds
        nwords = ((nbytes * 8 - skip_bits) + 31) / 32;
        for (w = 0; w < nwords; w++) words[w] = 32'd0;
        for (i = skip_bits; i < nbytes * 8; i++) begin
            bpos = i - skip_bits;
            b = bytes[i / 8][7 - (i % 8)];
            words[bpos / 32][31 - (bpos % 32)] = b;
        end

        // reset
        repeat (3) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        // program tables
        fd = $fopen("tb/vectors/tables.txt", "r");
        while ($fgets(line, fd)) begin
            if ($sscanf(line, "R %d %d %d %d", t, l, lim, bas) == 4) begin
                @(negedge clk);
                tbl_we = 1; tbl_kind = 0; tbl_sel = t; tbl_len = l; tbl_limit = lim; tbl_base = bas;
            end else if ($sscanf(line, "S %d %d %d", t, idx, s) == 3) begin
                @(negedge clk);
                tbl_we = 1; tbl_kind = 1; tbl_sel = t; tbl_idx = idx; tbl_sym = s;
            end
        end
        @(negedge clk); tbl_we = 0;
        $fclose(fd);
        $display("tables programmed; %0d symbols, %0d input words (skip %0d bits)", nsym, nwords, skip_bits);

        // decode
        @(negedge clk); run_en = 1;
        if (want_err)           wait (err);
        else if (want_underrun) wait (underrun);
        else                    wait (nchk == nsym);
        repeat (4) @(posedge clk);
        // A decode error must be terminal. With the engine still enabled, give
        // it a hundred more cycles and require that it made no further
        // progress: an error that does not halt sends the decoder round the
        // same unmatchable bits for ever.
        if (want_err) begin
            halt_ndec = ndec; halt_nchk = nchk; halt_bits = bits_consumed;
            repeat (100) @(posedge clk);
            if (ndec !== halt_ndec || nchk !== halt_nchk || bits_consumed !== halt_bits) begin
                $display("FAIL: the decoder kept going after err (symbols %0d->%0d, bits %0d->%0d)",
                         halt_ndec, ndec, halt_bits, bits_consumed);
                $fatal(1);
            end
            $display("halted after err: no further symbols or bits in 100 cycles");
        end
        $display("----------------------------------------------------------------");
        // first_cycle stays -1 when nothing decoded, which the directed error
        // tests do on purpose; printing a negative window there is nonsense.
        if (nchk > 0)
            $display("decoded %0d symbols in %0d cycles (%.3f symbols/cycle), %0d errors",
                     nchk, last_cycle - first_cycle + 1,
                     real'(nchk) / real'(last_cycle - first_cycle + 1), errors);
        else
            $display("decoded 0 symbols (the decoder refused the stream), %0d errors", errors);
        $display("total bits consumed: %0d  (avg %.2f bits/symbol)", bits_consumed,
                 nchk > 0 ? real'(bits_consumed) / real'(nchk) : 0.0);
        // Belt and braces: a run that checked nothing is not a pass - unless
        // decoding nothing is the point, as when the very first table row is
        // corrupt and the decoder must refuse rather than return a symbol.
        // On a stream that is a whole number of words the buffer drains to
        // zero, so done must be observable. If it never rises here, the signal
        // is untested everywhere.
        if (nwords * 32 == nbytes * 8 - skip_bits && !want_err && !want_underrun && done !== 1'b1) begin
            $display("FAIL: the stream drained but done never asserted");
            $fatal(1);
        end
        if (nchk == 0 && !want_err) begin
            $display("FAIL: decoded no symbols");
            $fatal(1);
        end
        // The bits the DUT actually consumed must equal what the software
        // decoder consumed. Reporting the golden file's total instead would
        // print the right number even for a DUT that consumed nothing.
        if (!want_err && !want_underrun && bits_consumed !== sum_len()) begin
            $display("FAIL: consumed %0d bits, software consumed %0d", bits_consumed, sum_len());
            $fatal(1);
        end
        // sym_count is what the host reads back; it must agree with the symbols
        // the testbench saw on the bus.
        if (!want_err && !want_underrun && sym_count !== nchk) begin
            $display("FAIL: sym_count reads %0d, testbench counted %0d", sym_count, nchk);
            $fatal(1);
        end
        if (!want_underrun && underrun !== 1'b0) begin
            $display("FAIL: underrun asserted on a well-formed stream");
            $fatal(1);
        end
        if (want_err && err !== 1'b1) begin
            $display("FAIL: the stream ends in an unmatchable code but err never asserted");
            $fatal(1);
        end
        if (want_underrun && underrun !== 1'b1) begin
            $display("FAIL: the stream ends short of a whole code but underrun never asserted");
            $fatal(1);
        end
        // One symbol per cycle is a headline claim of the report, so assert it
        // rather than only printing it. Two cycles of slack cover the pipeline
        // fill. Backpressure mode deliberately throttles, so skip it there.
        if (!bp_mode && !bubble_mode && !want_err && !want_underrun
            && (last_cycle - first_cycle + 1) > nsym + 2) begin
            $display("FAIL: throughput %0d cycles for %0d symbols (expected at most %0d)",
                     last_cycle - first_cycle + 1, nsym, nsym + 2);
            $fatal(1);
        end
        if (errors == 0) $display("PASS");
        else begin
            $display("FAIL (%0d errors)", errors);
            $fatal(1);          // non-zero exit, so `make sim` actually fails
        end
        $finish;
    end

    function automatic longint sum_len();
        longint acc = 0;
        for (int k = 0; k < nsym; k++) acc += exp_len[k];
        return acc;
    endfunction

    // Watchdog, proportional to the work: four cycles per expected symbol plus
    // a fixed margin. The design decodes one symbol per cycle, so the bound is
    // generous, yet a stalled decoder fails almost at once even on the smallest
    // directed sets, which decode three or four symbols. That is what keeps the
    // twenty-mutation sweep affordable.
    always @(posedge clk) begin
        if (run_en && cycles > (longint'(nsym) * 4 + 20000)) begin
            $display("TIMEOUT: decoded %0d/%0d symbols in %0d cycles", nchk, nsym, cycles);
            $display("FAIL (timeout)");
            $fatal(1);
        end
    end
endmodule
