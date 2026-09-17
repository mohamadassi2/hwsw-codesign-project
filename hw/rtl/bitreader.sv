// bitreader.sv -- MSB-first bit buffer feeding the Huffman decoder.
//
// Holds up to BUFW bits left-aligned (bit BUFW-1 is the next bit of the
// stream, like pyflate's RBitfield).  Every cycle it exposes the next MAXBITS
// bits on `peek`; the decoder answers with `consume` (0..MAXBITS) and the
// buffer barrel-shifts them out in the same cycle.  Refill is INW bits at a
// time from a valid/ready stream, so at one symbol per cycle the buffer never
// starves for codes up to INW bits.
//
// `flush` marks end of input; after it, missing bits read as zero.  The
// software reader does not do this - pyflate's _read raises when the file is
// empty - so the padding is the hardware's own answer to running out, and
// `level` is what keeps it from becoming a symbol: the decoder refuses a code
// longer than the bits really left.
// `done` = flushed and every bit consumed.

module bitreader #(
    parameter MAXBITS = 20,   // widest code the decoder may ask to see
    parameter INW     = 32,   // refill width
    parameter BUFW    = 64    // must be >= MAXBITS + INW
)(
    input  logic               clk,
    input  logic               rst_n,
    // input byte/word stream (MSB-first inside the word)
    input  logic [INW-1:0]     in_data,
    input  logic               in_valid,
    output logic               in_ready,
    input  logic               flush,       // no more input after this
    // decoder side
    input  logic [4:0]         consume,     // bits to drop this cycle
    output logic [MAXBITS-1:0] peek,        // next MAXBITS bits, MSB first
    output logic               peek_valid,  // enough bits (or flushed)
    output logic [$clog2(BUFW+1)-1:0] level, // bits currently buffered
    output logic               done         // flushed and the buffer is empty
);
`ifndef SYNTHESIS
    // A whole word must fit beside a full peek window; otherwise the reader can
    // reach a level where it can neither refill nor show MAXBITS bits, and hangs.
    initial if (BUFW < MAXBITS + INW)
        $fatal(1, "bitreader: BUFW (%0d) must be >= MAXBITS + INW (%0d)", BUFW, MAXBITS + INW);
`endif
    logic [BUFW-1:0]            buf_q, buf_d;
    logic [$clog2(BUFW+1)-1:0]  cnt_q, cnt_d, cnt_after;
    logic                       eof_q;

    // Bits left after this cycle's consume.  Saturating, though this design
    // never reaches the saturation: the decoder only takes a code whose whole
    // length is in the buffer (`fits[L]` in huffman_decoder.sv), so consume is
    // never more than cnt_q.  The guard belongs to the reader's own interface,
    // for a consumer that makes no such promise, and a wrapped count would read
    // as a full buffer of zeros forever.  hw/tb/MUTATIONS.md records removing
    // it as the one injected bug no test can catch, for this reason.
    assign cnt_after = (cnt_q > consume) ? (cnt_q - consume) : '0;

    // Room for a whole word after this cycle's consume.  Testing cnt_q would
    // refuse the refill in the very cycle that makes room, so a long code would
    // wait for bits already on their way and the decoder would drop below one
    // symbol per cycle; this form holds it.  No combinational loop: consume
    // depends only on peek, peek_valid and level, which come from registers.
    assign in_ready = (cnt_after + INW <= BUFW);

    always_comb begin
        // 1. drop the bits the decoder consumed this cycle
        buf_d = buf_q << consume;
        cnt_d = cnt_after;
        // 2. append a new word right after the remaining valid bits
        if (in_valid && in_ready) begin
            buf_d = buf_d | ({{(BUFW-INW){1'b0}}, in_data} << (BUFW - INW - cnt_d));
            cnt_d = cnt_d + INW;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            buf_q <= '0; cnt_q <= '0; eof_q <= 1'b0;
        end else begin
            buf_q <= buf_d; cnt_q <= cnt_d;
            if (flush) eof_q <= 1'b1;
        end
    end

    assign peek       = buf_q[BUFW-1 -: MAXBITS];   // zeros beyond cnt_q
    assign peek_valid = (cnt_q >= MAXBITS) || (eof_q && cnt_q != 0);
    assign level      = cnt_q;
    // Lets the host tell a finished block from a hang.
    assign done       = eof_q && (cnt_q == 0);
endmodule
