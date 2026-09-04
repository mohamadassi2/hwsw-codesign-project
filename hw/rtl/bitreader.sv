// bitreader.sv -- MSB-first bit buffer feeding the Huffman decoder.
//
// Holds up to BUFW bits left-aligned (bit BUFW-1 is the next bit of the
// stream, exactly like pyflate's RBitfield).  Every cycle it exposes the next
// MAXBITS bits on `peek`; the decoder answers with `consume` (0..MAXBITS) and
// the buffer barrel-shifts them out in the same cycle.  Refill is INW bits at
// a time from a simple valid/ready stream, so at one symbol per cycle the
// buffer never starves for codes up to INW bits.
//
// `flush` marks end of input: from then on missing bits read as zero, which is
// what the software decoder does too (it pads at EOF).

module bitreader #(
    parameter int MAXBITS = 20,   // widest code the decoder may ask to see
    parameter int INW     = 32,   // refill width
    parameter int BUFW    = 64    // must be >= MAXBITS + INW
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
    output logic [$clog2(BUFW+1)-1:0] level // bits currently buffered
);
    logic [BUFW-1:0]            buf_q, buf_d;
    logic [$clog2(BUFW+1)-1:0]  cnt_q, cnt_d, cnt_after;
    logic                       eof_q;

    // Level after this cycle's consume. Saturating, because peek_valid also
    // holds after flush with as little as one bit left while the decoder may
    // still ask to consume up to MAXBITS; an unguarded subtraction wraps the
    // counter and the reader then reports a full buffer of zeros forever.
    assign cnt_after = (cnt_q > consume) ? (cnt_q - consume) : '0;

    // Accept a refill when there is room for a whole word AFTER the consume.
    // Testing cnt_q instead would refuse a refill in the very cycle that makes
    // room, which costs throughput once codes get long (measured: 0.84
    // symbols/cycle at 19-bit codes, 1.000 with this form). There is no
    // combinational loop: consume comes from the decoder, which depends on
    // peek and peek_valid, and both are functions of the registers only.
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
endmodule
