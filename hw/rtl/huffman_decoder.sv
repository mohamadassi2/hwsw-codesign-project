// huffman_decoder.sv -- canonical Huffman symbol decoder, one symbol per cycle.
//
// This is the hardware form of the decode loop that pyflate's optimized
// HuffmanTable.find_next_symbol runs in software:
//
//     v = peek(max_bits)
//     for L in min_bits..max_bits:          # sequential in software
//         code = v >> (max_bits - L)
//         if code < limit[L]:               # limit[L] = first[L] + count[L]
//             consume(L); return syms[base[L] + code]   # base[L] = index[L] - first[L]
//
// In hardware every code length is tested at the same time: MAXBITS
// comparators run in parallel, a priority encoder picks the shortest hit,
// one adder forms the symbol-table index and a small SRAM returns the
// symbol on the next clock.  Throughput 1 symbol/cycle; `len` is
// combinational so the bit buffer can shift in the same cycle, `sym` follows
// one cycle later.
//
// Tables are written by software once per bzip2 block (up to NTAB of them,
// selected per 50-symbol group by `tsel`, mirroring bzip2's selector list).

module huffman_decoder #(
    parameter MAXBITS = 20,    // bzip2 = 20, DEFLATE would be 15
    parameter NSYM    = 258,   // bzip2 alphabet: 256 MTF values + RUNA/RUNB (EOB included)
    parameter SYMW    = 9,
    parameter NTAB    = 6,
    localparam TSW    = $clog2(NTAB),
    localparam IDXW   = $clog2(NSYM),
    localparam CW     = MAXBITS + 1,   // code / limit width (limit can be 2^L)
    localparam BW     = MAXBITS + 2    // signed base width
)(
    input  logic                 clk,
    input  logic                 rst_n,

    // ---- table programming (memory-mapped from the host) -------------------
    input  logic                 tbl_we,
    input  logic [TSW-1:0]       tbl_sel,     // which of the NTAB banks
    input  logic                 tbl_kind,    // 0: {limit,base} row for length tbl_len
                                              // 1: symbol entry at tbl_idx
    input  logic [4:0]           tbl_len,     // 1..MAXBITS
    input  logic [CW-1:0]        tbl_limit,
    input  logic signed [BW-1:0] tbl_base,
    input  logic [IDXW-1:0]      tbl_idx,
    input  logic [SYMW-1:0]      tbl_sym,

    // ---- decode ----------------------------------------------------------
    input  logic [TSW-1:0]       tsel,        // active table this symbol
    input  logic [MAXBITS-1:0]   peek,        // next MAXBITS bits, MSB first
    input  logic                 peek_valid,
    input  logic [6:0]           avail,       // bits really in the buffer
    input  logic                 out_ready,   // symbol consumer can take one
    input  logic                 enable,      // decode a symbol this cycle
    output logic [4:0]           len,         // bits consumed (same cycle)
    output logic                 len_valid,
    output logic [SYMW-1:0]      sym,         // symbol (one cycle later)
    output logic                 sym_valid,
    output logic                 err,         // sticky: no code length matched
    output logic                 underrun     // sticky: a code ran past end of stream
);
    // ---- per-length rows: limit[L], base[L] --------------------------------
    // These are REGISTER FILES, not SRAM, and are marked so that synthesis
    // counts them as the flip-flops they are.  limit_r is read at all MAXBITS
    // code lengths in the same cycle (that is the whole point of the parallel
    // compare) and base_r is read asynchronously; no SRAM macro offers twenty
    // read ports, so leaving them as inferred memories would hide their real
    // cost.  Only symtab below is a genuine single-port SRAM.
    (* mem2reg *) logic [CW-1:0]        limit_r [NTAB][MAXBITS+1];
    (* mem2reg *) logic signed [BW-1:0] base_r  [NTAB][MAXBITS+1];
    // ---- symbol table -------------------------------------------------------
    logic [SYMW-1:0]      symtab  [NTAB][NSYM];

    always_ff @(posedge clk) begin
        if (tbl_we) begin
            // tbl_len is five bits but only 1..MAXBITS are real rows; ignore the
            // rest rather than writing off the end of the array.
            if (!tbl_kind && tbl_len <= MAXBITS[4:0]) begin
                limit_r[tbl_sel][tbl_len] <= tbl_limit;
                base_r [tbl_sel][tbl_len] <= tbl_base;
            end else if (tbl_kind) begin
                symtab[tbl_sel][tbl_idx] <= tbl_sym;
            end
        end
    end

    // ---- parallel compare: one comparator per code length ------------------
    // `fits` is the end-of-stream guard, folded in here rather than applied to
    // the encoder's output. It only depends on `avail`, which is a register, so
    // it is computed alongside the compares and costs nothing on the path from
    // `peek` to `len`. Testing it after the priority encoder instead cost
    // twenty gate levels for no benefit.
    logic [MAXBITS:1] hit_raw, fits, hit;
    logic [CW-1:0]    code [MAXBITS+1];
    always_comb begin
        code[0] = '0;                                   // index used only when nothing matched
        for (int L = 1; L <= MAXBITS; L++) begin
            code[L]    = CW'(peek >> (MAXBITS - L));      // top L bits
            hit_raw[L] = (code[L] < limit_r[tsel][L]);
            fits[L]    = (L <= avail);
            hit[L]     = hit_raw[L] && fits[L];
        end
    end
    // ---- priority encode: the shortest matching length wins ----------------
    logic [4:0] len_c;
    logic       found, found_raw;

    // A code matched but did not fit: the stream ended part-way through it.
    // Derived from a priority-encoder pass rather than from (|hit_raw), because
    // a reduction OR over an unprogrammed table row yields X, and `!short_c`
    // then makes the err assignment below unreachable - the decoder would
    // livelock on a corrupt table instead of halting. `if (hit_raw[L])` treats
    // X as false, which is the same rule `found` already uses.
    always_comb begin
        found_raw = 1'b0;
        for (int L = MAXBITS; L >= 1; L--)
            if (hit_raw[L]) found_raw = 1'b1;
    end
    logic short_c;
    assign short_c = found_raw && !found;

    always_comb begin
        len_c = '0; found = 1'b0;
        for (int L = MAXBITS; L >= 1; L--)   // last assignment = smallest L
            if (hit[L]) begin len_c = 5'(L); found = 1'b1; end
    end

    // ---- index = base[len] + code[len] ---------------------------------------
    logic signed [BW-1:0] idx_s;
    logic [IDXW-1:0]      idx;
    assign idx_s = base_r[tsel][len_c] + $signed({1'b0, code[len_c]});
    assign idx   = idx_s[IDXW-1:0];

    // A decode error is sticky and halts the engine. Without that the failing
    // symbol consumes no bits, so the same bits are presented again the next
    // cycle and the decoder livelocks on a corrupt stream.
    // idx must land inside the symbol table. For a well-formed canonical table
    // it always does; a corrupt one would otherwise return a wrong symbol
    // silently instead of raising err.
    logic idx_ok;
    assign idx_ok = (idx_s >= 0) && (idx_s < BW'(NSYM));

    // The symbol register is a one-deep output buffer. A new decode may only
    // start when it is free - either empty, or being accepted this cycle - so a
    // consumer that stalls holds the whole engine instead of losing symbols.
    // With out_ready tied high this is always true and costs no throughput.
    logic err_q, underrun_q, fire, take, out_free;
    assign out_free  = !sym_valid || out_ready;
    assign fire      = enable && peek_valid && out_free && !err_q && !underrun_q;
    // `take` drives `len`, which the bit reader consumes in the SAME cycle, so
    // it must stay on the short path: enable, the compare tree and the priority
    // encoder, and nothing else. The index range check is
    // deliberately NOT here - it sits after the base adder, and putting it in
    // this path lengthened the critical path from 67 to 122 gate levels. It is
    // applied one stage later instead, where there is a whole clock for it.
    assign take      = fire && found;
    assign len       = take ? len_c : 5'd0;
    assign len_valid = take;

    // ---- stage 2: symbol SRAM read ------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sym <= '0; sym_valid <= 1'b0; err_q <= 1'b0; underrun_q <= 1'b0;
        end else begin
            // Read only on a real decode: idx is X while no length matched
            // (row 0 of base_r is never programmed), and latching that would
            // put X on a top-level output for no reason.
            if (take && idx_ok)
                sym <= symtab[tsel][idx];
            // Hold the symbol until the consumer takes it. A decode whose index
            // left the table produces no symbol and raises err instead.
            if (take && idx_ok)  sym_valid <= 1'b1;
            else if (out_ready)  sym_valid <= 1'b0;
            if (fire && ((!found && !short_c) || (take && !idx_ok)))
                err_q <= 1'b1;
            if (fire && short_c)
                underrun_q <= 1'b1;
        end
    end
    assign err      = err_q;
    assign underrun = underrun_q;
endmodule
