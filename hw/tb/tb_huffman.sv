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
    logic [INW-1:0]     in_data;              // driven by the stimulus block below
    logic               in_valid, in_ready, in_last;
    logic               run, sym_valid, err;
    logic               run_en = 0;
    logic [2:0]         tsel;
    logic [SYMW-1:0]    sym;
    logic               out_ready;
    logic               busy, done, underrun;
    logic [31:0]        sym_count;
    logic [6:0]         level;
    // +bp: gate out_ready and in_valid pseudo-randomly so both handshakes are
    // exercised under backpressure. The throughput check is skipped in this mode.
    logic               bp_mode = 0;
    // +expect_err / +expect_underrun: the real block never trips err or underrun,
    // so these run a purpose-built stream that ends in a bad tail (see
    // gen_synth_vectors.py); PASS requires the matching flag to rise.
    logic               want_err = 0, want_underrun = 0;
    // +last_level: hold in_last high from the final word on, as a register-mapped
    // host would, even on cycles with nothing valid. The DUT must not take that
    // as end of input.
    logic               last_level = 0;
    // +bubble: stall the producer 40 cycles just before the final word, so an
    // end-of-input that fires on LAST alone (in_valid low) is caught.
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
    longint bits_consumed = 0;      // summed from the DUT's len output
    int first_cycle = -1, last_cycle = -1;
    logic err_d = 0, underrun_d = 0;
    logic sv_d = 0, or_d = 0;
    int halt_ndec, halt_nchk; longint halt_bits;
    logic [SYMW-1:0] sym_d = 0;

    // input stream: present word widx while any remain.
    // Explicit sensitivity lists, not @*: Icarus 11 on the course VM aborts on
    // @* over a large array indexed by a variable, and on ?: in a continuous
    // assignment over int. arm_bubble is combinational because a registered
    // version arrives one cycle after the reader has already taken the final word.
    wire arm_bubble = bubble_mode && !bubbled && (widx == nwords - 1);
    always @(widx, nwords, run, bp_mode, lfsr, last_level, bubble, arm_bubble) begin
        in_valid = (widx < nwords) && run && (!bp_mode || lfsr[7])
                   && (bubble == 0) && !arm_bubble;
        in_data  = words[widx];
        // Default: LAST travels with the final valid beat (a one-word stream would
        // otherwise show LAST before run). +last_level holds it as a level.
        in_last  = last_level ? (widx >= nwords - 1) : ((widx == nwords - 1) && in_valid);
    end
    always @(posedge clk) if (in_valid && in_ready) widx <= widx + 1;
    // +bubble: one 40-cycle stall on reaching the last word, long enough for a
    // premature flush to show.
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
        // Default: stop after the last expected symbol. +expect_underrun: run into
        // the bad tail until underrun rises. +expect_err: keep run high even after
        // err, so the halt-on-error check in main proves something.
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
            // A symbol may only be consumed when its whole code is in the buffer;
            // otherwise it was decoded from the zero padding.
            if (dut.len > level) begin
                errors++;
                if (errors < 10)
                    $display("PROTOCOL: consumed %0d bits with only %0d in the buffer, at symbol %0d",
                             dut.len, level, ndec);
            end
            // Past nsym there is nothing to compare (the failure modes run on).
            if (ndec >= nsym) ; else
            // === / !== so an X counts as a mismatch: with != an all-X decoder makes
            // every compare x, which `if` treats as false.
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
        // A symbol offered while out_ready is low must still be there, unchanged,
        // on the next cycle.
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
        // done must not assert while symbols are still expected.
        if (done && nchk < nsym && !want_err && !want_underrun) begin
            errors++;
            if (errors < 10)
                $display("PROTOCOL: done asserted with %0d of %0d symbols still to come", nchk, nsym);
        end
        // err and underrun are sticky, so count rising edges.
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
    int fd, t, l, lim, bas, idx, s, i, w, bpos, b;
    // A packed vector, not `string`: Icarus 11 (the course VM) rejects a string
    // target for $fgets. Vector-file lines are well under 256 characters.
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
        if (i != nsym) begin
            $display("FAIL: expected.txt has %0d lines, meta.txt says %0d", i, nsym);
            $fatal(1);
        end
        // nsym == 0 would pass trivially: wait(nchk == nsym) returns at once.
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
        // err must halt the decoder, or it spins on the unmatchable bits for ever:
        // with run still high, 100 more cycles must add no symbols and no bits.
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
        // first_cycle is still -1 when nothing was decoded.
        if (nchk > 0)
            $display("decoded %0d symbols in %0d cycles (%.3f symbols/cycle), %0d errors",
                     nchk, last_cycle - first_cycle + 1,
                     real'(nchk) / real'(last_cycle - first_cycle + 1), errors);
        else
            $display("decoded 0 symbols (the decoder refused the stream), %0d errors", errors);
        $display("total bits consumed: %0d  (avg %.2f bits/symbol)", bits_consumed,
                 nchk > 0 ? real'(bits_consumed) / real'(nchk) : 0.0);
        // A stream that is a whole number of words drains the buffer to zero, so
        // done must have asserted.
        if (nwords * 32 == nbytes * 8 - skip_bits && !want_err && !want_underrun && done !== 1'b1) begin
            $display("FAIL: the stream drained but done never asserted");
            $fatal(1);
        end
        // A run that checked nothing is not a pass, unless refusing the stream is
        // the point (+expect_err on the badidx set).
        if (nchk == 0 && !want_err) begin
            $display("FAIL: decoded no symbols");
            $fatal(1);
        end
        // Bits consumed by the DUT must match what the software decoder consumed.
        if (!want_err && !want_underrun && bits_consumed !== sum_len()) begin
            $display("FAIL: consumed %0d bits, software consumed %0d", bits_consumed, sum_len());
            $fatal(1);
        end
        // sym_count is what the host reads back; it must match the count on the bus.
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
        // The report claims one symbol per cycle, so assert it; two cycles of slack
        // cover the pipeline fill. Skipped in the modes that stall on purpose.
        if (!bp_mode && !bubble_mode && !want_err && !want_underrun
            && (last_cycle - first_cycle + 1) > nsym + 2) begin
            $display("FAIL: throughput %0d cycles for %0d symbols (expected at most %0d)",
                     last_cycle - first_cycle + 1, nsym, nsym + 2);
            $fatal(1);
        end
        if (errors == 0) $display("PASS");
        else begin
            $display("FAIL (%0d errors)", errors);
            $fatal(1);          // non-zero exit so `make sim` fails
        end
        $finish;
    end

    function automatic longint sum_len();
        longint acc = 0;
        for (int k = 0; k < nsym; k++) acc += exp_len[k];
        return acc;
    endfunction

    // Watchdog: four cycles per expected symbol plus a margin. Generous for a
    // one-symbol-per-cycle design, and still quick on the small directed sets,
    // which keeps tb/mutate.sh affordable.
    always @(posedge clk) begin
        if (run_en && cycles > (longint'(nsym) * 4 + 20000)) begin
            $display("TIMEOUT: decoded %0d/%0d symbols in %0d cycles", nchk, nsym, cycles);
            $display("FAIL (timeout)");
            $fatal(1);
        end
    end
endmodule
