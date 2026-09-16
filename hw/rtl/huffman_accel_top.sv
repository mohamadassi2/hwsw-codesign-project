// huffman_accel_top.sv -- the accelerator as the host sees it.
//
// One decoder + one bit buffer behind a tiny register interface.  The
// software side (see docs/hw_sw_interface.md) does, per bzip2 block:
//   1. write the NTAB tables (limit/base rows + symbol entries),
//   2. stream the compressed bytes in and the 9-bit symbols out (DMA/FIFO),
//   3. drive `tsel` from the block's selector list, one change per 50 symbols.
// The MTF / RLE / BWT stages that follow stay in software: MTF and RLE are a
// small share of the optimized profile, and BWT is a memory-bound pointer
// chase that gains nothing from a datapath.

module huffman_accel_top #(
    parameter MAXBITS = 20,
    parameter NSYM    = 258,
    parameter SYMW    = 9,
    parameter NTAB    = 6,
    parameter INW     = 32,
    localparam TSW    = $clog2(NTAB),
    localparam IDXW   = $clog2(NSYM)
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
    input  logic               out_ready,    // the symbol FIFO/DMA can take one
    output logic               err,
    // status, as exposed through the STATUS register (see docs/hw_sw_interface.md)
    output logic               len_valid,    // a code was consumed this cycle
    output logic [6:0]         level,        // bits currently held in the bit buffer
    output logic               busy,         // running, not finished, no error
    output logic               done,         // input flushed and fully consumed
    output logic               underrun,     // a code ran past the end of the stream
    output logic [31:0]        sym_count     // symbols emitted since reset
);
    logic [MAXBITS-1:0] peek;
    logic               peek_valid;
    logic [4:0]         len;

    // `in_last` rides on the final beat, AXI-stream TLAST style: flush on that
    // beat's handshake only.  LAST may stay high afterwards, but a flush on
    // LAST without the handshake would fire on a producer bubble before the
    // last word arrives (and during table programming, when run is low).
    logic flush_c;
    assign flush_c = in_last & in_valid & in_ready;

    logic bits_done;
    bitreader #(.MAXBITS(MAXBITS), .INW(INW), .BUFW(64)) u_bits (
        .clk(clk), .rst_n(rst_n),
        .in_data(in_data), .in_valid(in_valid), .in_ready(in_ready),
        .flush(flush_c),
        .consume(len), .peek(peek), .peek_valid(peek_valid), .level(level),
        .done(bits_done)
    );
    // Not done while a decoded symbol is still waiting to be taken: a host that
    // tears down the DMA on DONE would lose the last symbol of the block.
    assign done = bits_done & ~sym_valid;

    huffman_decoder #(.MAXBITS(MAXBITS), .NSYM(NSYM), .SYMW(SYMW), .NTAB(NTAB)) u_dec (
        .clk(clk), .rst_n(rst_n),
        .tbl_we(tbl_we), .tbl_sel(tbl_sel), .tbl_kind(tbl_kind), .tbl_len(tbl_len),
        .tbl_limit(tbl_limit), .tbl_base(tbl_base), .tbl_idx(tbl_idx), .tbl_sym(tbl_sym),
        .tsel(tsel), .peek(peek), .peek_valid(peek_valid), .avail(level),
        .out_ready(out_ready), .enable(run),
        .len(len), .len_valid(len_valid), .sym(sym), .sym_valid(sym_valid),
        .err(err), .underrun(underrun)
    );

    assign busy = run & ~done & ~err & ~underrun;

    always_ff @(posedge clk or negedge rst_n) begin
        // Count accepted symbols: under backpressure the same symbol is
        // offered for several cycles.
        if (!rst_n) sym_count <= 32'd0;
        else if (sym_valid && out_ready) sym_count <= sym_count + 32'd1;
    end
endmodule
