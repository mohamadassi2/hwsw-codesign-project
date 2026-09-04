// tb_huffman.sv -- drives the accelerator with the benchmark's real bzip2 block.
//
// Reads the vectors produced by gen_vectors.py, programs the six tables,
// streams the compressed bytes through the bit reader 32 bits at a time,
// drives `tsel` per symbol from the recorded selector sequence, and checks
// every decoded (symbol, code length) against the software decoder.
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

    huffman_accel_top #(.MAXBITS(MAXBITS), .NSYM(NSYM), .SYMW(SYMW), .NTAB(NTAB), .INW(INW)) dut (
        .clk(clk), .rst_n(rst_n),
        .tbl_we(tbl_we), .tbl_sel(tbl_sel), .tbl_kind(tbl_kind), .tbl_len(tbl_len),
        .tbl_limit(tbl_limit), .tbl_base(tbl_base), .tbl_idx(tbl_idx), .tbl_sym(tbl_sym),
        .in_data(in_data), .in_valid(in_valid), .in_ready(in_ready), .in_last(in_last),
        .run(run), .tsel(tsel), .sym(sym), .sym_valid(sym_valid), .err(err));

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
    int first_cycle = -1, last_cycle = -1;

    // input stream: present word widx while any remain
    // Stimulus as plain Verilog-2001 processes with explicit sensitivity lists.
    // Two things the course VM's Icarus Verilog 11.0 cannot simulate: an @*
    // block that reads a word of a large array with a variable index (the whole
    // array lands on the sensitivity list and vvp aborts), and a ?: in a
    // continuous assignment over SystemVerilog int variables (vvp aborts with
    // "recv_real not implemented"). Listing the scalar inputs explicitly avoids
    // both; the behaviour is the same as an @* block.
    always @(widx, nwords, run) begin
        in_valid = (widx < nwords) && run;
        in_data  = words[widx];
        in_last  = (widx == nwords - 1);
    end
    always @(posedge clk) if (in_valid && in_ready) widx <= widx + 1;

    // selector for the symbol about to be decoded
    int cur_tsel;
    always @(ndec, nsym, run_en) begin
        cur_tsel = (ndec < nsym) ? exp_tsel[ndec] : 0;
        tsel     = cur_tsel[2:0];
        run      = run_en && (ndec < nsym);
    end

    // count consumed lengths and check them
    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (dut.len_valid) begin
            if (first_cycle < 0) first_cycle = cycles;
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
        if (sym_valid) begin
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
        if (err) begin
            errors++;
            if (errors < 10) $display("DECODER ERR at symbol %0d (no length matched)", ndec);
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
        if (fd == 0) begin $display("cannot open meta.txt (run from hw/ after gen_vectors.py)"); $finish; end
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
        if (i != nsym) begin $display("expected.txt has %0d lines, meta says %0d", i, nsym); nsym = i; end
        // compressed bytes -> 32-bit words, starting at bit `skip_bits`
        $readmemh("tb/vectors/stream.hex", bytes);
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
        wait (nchk == nsym);
        repeat (4) @(posedge clk);
        $display("----------------------------------------------------------------");
        $display("decoded %0d symbols in %0d cycles (%.3f symbols/cycle), %0d errors",
                 nchk, last_cycle - first_cycle + 1,
                 real'(nchk) / real'(last_cycle - first_cycle + 1), errors);
        $display("total bits consumed: %0d  (avg %.2f bits/symbol)", nbytes*8 - skip_bits > 0 ? sum_len() : 0,
                 real'(sum_len()) / real'(nchk));
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

    // watchdog
    initial begin
        #200_000_000;   // 200 ms sim time = 20M cycles
        // A hang is a failure. Without this the run ends quietly with exit 0,
        // so a decoder that stalls (or an X on sym_valid) looks like success.
        $display("TIMEOUT: decoded %0d/%0d symbols", nchk, nsym);
        $display("FAIL (timeout)");
        $fatal(1);
    end
endmodule
