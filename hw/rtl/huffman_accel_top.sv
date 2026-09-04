// huffman_accel_top.sv -- the accelerator as the host sees it.
//
// One decoder + one bit buffer behind a tiny register interface.  The
// software side (see docs/hw_sw_interface.md) does, per bzip2 block:
//   1. write the NTAB tables (limit/base rows + symbol entries),
//   2. stream the compressed bytes in and the 9-bit symbols out (DMA/FIFO),
//   3. drive `tsel` from the block's selector list, one change per 50 symbols.
// The MTF / RLE / BWT stages that follow stay in software: after the
// canonical-decode fix they are cheap, and BWT is a memory-bound pointer
// chase that gains nothing from a datapath.

module huffman_accel_top #(
    parameter int MAXBITS = 20,
    parameter int NSYM    = 258,
    parameter int SYMW    = 9,
    parameter int NTAB    = 6,
    parameter int INW     = 32,
    localparam int TSW    = $clog2(NTAB),
    localparam int IDXW   = $clog2(NSYM)
)(
    input  logic               clk,
    input  logic               rst_n,
    // table programming
    input  logic               tbl_we,
    input  logic [TSW-1:0]     tbl_sel,
    input  logic               tbl_kind,
    input  logic [4:0]         tbl_len,
    input  logic [MAXBITS:0]   tbl_limit,
    input  logic signed [MAXBITS+1:0] tbl_base,
    input  logic [IDXW-1:0]    tbl_idx,
    input  logic [SYMW-1:0]    tbl_sym,
    // compressed input stream
    input  logic [INW-1:0]     in_data,
    input  logic               in_valid,
    output logic               in_ready,
    input  logic               in_last,
    // control
    input  logic               run,          // decode while high
    input  logic [TSW-1:0]     tsel,
    // symbol output stream
    output logic [SYMW-1:0]    sym,
    output logic               sym_valid,
    output logic               err
);
    logic [MAXBITS-1:0] peek;
    logic               peek_valid;
    logic [4:0]         len;
    logic               len_valid;
    logic [$clog2(65)-1:0] level;

    bitreader #(.MAXBITS(MAXBITS), .INW(INW), .BUFW(64)) u_bits (
        .clk(clk), .rst_n(rst_n),
        .in_data(in_data), .in_valid(in_valid), .in_ready(in_ready),
        .flush(in_last & in_valid & in_ready),
        .consume(len), .peek(peek), .peek_valid(peek_valid), .level(level)
    );

    huffman_decoder #(.MAXBITS(MAXBITS), .NSYM(NSYM), .SYMW(SYMW), .NTAB(NTAB)) u_dec (
        .clk(clk), .rst_n(rst_n),
        .tbl_we(tbl_we), .tbl_sel(tbl_sel), .tbl_kind(tbl_kind), .tbl_len(tbl_len),
        .tbl_limit(tbl_limit), .tbl_base(tbl_base), .tbl_idx(tbl_idx), .tbl_sym(tbl_sym),
        .tsel(tsel), .peek(peek), .peek_valid(peek_valid), .enable(run),
        .len(len), .len_valid(len_valid), .sym(sym), .sym_valid(sym_valid), .err(err)
    );
endmodule
