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
    parameter int MAXBITS = 20,    // bzip2 = 20, DEFLATE would be 15
    parameter int NSYM    = 258,   // bzip2 alphabet: 256 MTF values + RUNA/RUNB (EOB included)
    parameter int SYMW    = 9,
    parameter int NTAB    = 6,
    localparam int TSW    = $clog2(NTAB),
    localparam int IDXW   = $clog2(NSYM),
    localparam int CW     = MAXBITS + 1,   // code / limit width (limit can be 2^L)
    localparam int BW     = MAXBITS + 2    // signed base width
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
    input  logic                 enable,      // decode a symbol this cycle
    output logic [4:0]           len,         // bits consumed (same cycle)
    output logic                 len_valid,
    output logic [SYMW-1:0]      sym,         // symbol (one cycle later)
    output logic                 sym_valid,
    output logic                 err          // no code length matched
);
    // ---- per-length rows: limit[L], base[L] --------------------------------
    logic [CW-1:0]        limit_r [NTAB][MAXBITS+1];
    logic signed [BW-1:0] base_r  [NTAB][MAXBITS+1];
    // ---- symbol table -------------------------------------------------------
    logic [SYMW-1:0]      symtab  [NTAB][NSYM];

    always_ff @(posedge clk) begin
        if (tbl_we) begin
            if (!tbl_kind) begin
                limit_r[tbl_sel][tbl_len] <= tbl_limit;
                base_r [tbl_sel][tbl_len] <= tbl_base;
            end else begin
                symtab[tbl_sel][tbl_idx] <= tbl_sym;
            end
        end
    end

    // ---- parallel compare: one comparator per code length ------------------
    logic [MAXBITS:1] hit;
    logic [CW-1:0]    code [MAXBITS+1];
    always_comb begin
        for (int L = 1; L <= MAXBITS; L++) begin
            code[L] = CW'(peek >> (MAXBITS - L));         // top L bits
            hit[L]  = (code[L] < limit_r[tsel][L]);
        end
    end

    // ---- priority encode: the shortest matching length wins ----------------
    logic [4:0] len_c;
    logic       found;
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

    logic fire;
    assign fire      = enable && peek_valid;
    assign len       = fire && found ? len_c : 5'd0;
    assign len_valid = fire && found;

    // ---- stage 2: symbol SRAM read ------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sym <= '0; sym_valid <= 1'b0; err <= 1'b0;
        end else begin
            sym       <= symtab[tsel][idx];
            sym_valid <= fire && found;
            err       <= fire && !found;
        end
    end
endmodule
