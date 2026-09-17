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
    // 7 bits = $clog2(BUFW+1) for the top's BUFW=64 (BUFW is not a parameter here)
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
    // limit_r is read at all MAXBITS lengths in one cycle and base_r
    // asynchronously, so these are flip-flops, not SRAM; mem2reg makes
    // synthesis count them as such.  Only symtab below is a real SRAM.
    (* mem2reg *) logic [CW-1:0]        limit_r [NTAB][MAXBITS+1];
    (* mem2reg *) logic signed [BW-1:0] base_r  [NTAB][MAXBITS+1];
    // ---- symbol table -------------------------------------------------------
    logic [SYMW-1:0]      symtab  [NTAB][NSYM];

    always_ff @(posedge clk) begin
        if (tbl_we) begin
            // rows exist only for 1..MAXBITS; an out-of-range tbl_len is ignored
            if (!tbl_kind && tbl_len <= MAXBITS[4:0]) begin
                limit_r[tbl_sel][tbl_len] <= tbl_limit;
                base_r [tbl_sel][tbl_len] <= tbl_base;
            end else if (tbl_kind) begin
                symtab[tbl_sel][tbl_idx] <= tbl_sym;
            end
        end
    end

    // ---- parallel compare: one comparator per code length ------------------
    // `fits` guards the end of stream: a code may not run past the bits really
    // left.  `avail` is a register, so masking here costs nothing on the
    // peek -> len path; masking after the priority encoder cost 20 gate levels.
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

    // found_raw: some length matched, ignoring `fits`.  A loop, not (|hit_raw):
    // an unprogrammed row makes the OR X, which would keep err from ever
    // setting; `if (hit_raw[L])` treats X as false, the same rule `found` uses.
    always_comb begin
        found_raw = 1'b0;
        for (int L = MAXBITS; L >= 1; L--)
            if (hit_raw[L]) found_raw = 1'b1;
    end
    // short_c: a code matched but the stream ended part-way through it.
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

    // A corrupt table can push idx outside symtab; flag it instead of
    // returning a wrong symbol silently.
    logic idx_ok;
    assign idx_ok = (idx_s >= 0) && (idx_s < BW'(NSYM));

    // sym is a one-deep output buffer: a new decode starts only when it is
    // empty or being taken this cycle, so backpressure stalls the engine
    // instead of dropping symbols.  With out_ready tied high it never stalls.
    logic err_q, underrun_q, fire, take, out_free;
    assign out_free  = !sym_valid || out_ready;
    assign fire      = enable && peek_valid && out_free && !err_q && !underrun_q;
    // `len` is consumed by the bit reader in the same cycle, so `take` stays on
    // the short path: enable, the compare tree and the priority encoder.  idx_ok
    // gates only the register write below and is kept off this one; putting it
    // here raised the critical path from 67 to 122 gate levels.
    assign take      = fire && found;
    assign len       = take ? len_c : 5'd0;
    assign len_valid = take;

    // ---- stage 2: symbol SRAM read ------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sym <= '0; sym_valid <= 1'b0; err_q <= 1'b0; underrun_q <= 1'b0;
        end else begin
            // idx is X when nothing matched (row 0 is never programmed); do not latch it
            if (take && idx_ok)
                sym <= symtab[tsel][idx];
            // hold sym_valid until the consumer takes it
            if (take && idx_ok)  sym_valid <= 1'b1;
            else if (out_ready)  sym_valid <= 1'b0;
            // err and underrun are sticky and stop the engine: a failed decode
            // consumes no bits, so without the halt the same bits would be
            // retried forever.
            if (fire && ((!found && !short_c) || (take && !idx_ok)))
                err_q <= 1'b1;
            if (fire && short_c)
                underrun_q <= 1'b1;
        end
    end
    assign err      = err_q;
    assign underrun = underrun_q;
endmodule
