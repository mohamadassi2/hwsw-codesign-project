# Huffman decode accelerator: hardware/software interface

This describes how the accelerator in `hw/rtl/` plugs into pyflate. The
software side is the optimized decoder in `benchmarks/pyflate/run_benchmark_opt.py`;
the hardware replaces exactly one call site, `HuffmanTable.find_next_symbol`,
which, with the bit-extraction helpers it calls, is 51.0% of the optimized run
(report_pyflate.txt sections 4.2 and 5.6).

## What moves to hardware, what stays

| Stage of `decode_huffman_block` | Where | Why |
|---|---|---|
| Parse block header, selectors, code lengths (`compute_used`, `compute_selectors_list`, `compute_tables`) | software | once per 900 KB block, negligible |
| Canonical-Huffman symbol decode (`find_next_symbol` + `snoopbits`/`readbits`) | **hardware** | 51.0% of the optimized run, cumulative; bit-serial work, one symbol per clock in hardware |
| Move-to-front, RUNA/RUNB run expansion | software | cheap after the decode fix (`pop`/`insert`, ~4% of the profile) |
| Inverse BWT (`bwt_transform`, `bwt_reverse`) | software | a 400 KB pointer chase; memory-latency bound, no datapath helps it |
| Final RLE, output assembly | software | one regex pass |

The interface is therefore: *tables in, bytes in, symbols out*.

## Register map (memory-mapped, 32-bit registers)

| Offset | Name | R/W | Meaning |
|---|---|---|---|
| 0x00 | `CTRL` | RW | bit0 `RUN` decode enabled (drives `run`); bit2 `LAST` the buffer now being streamed is the last one. It reaches the core as `in_last`, and the flush is the `in_valid & in_ready` handshake of the final beat (AXI-stream TLAST style), so `LAST` may stay high afterwards but must not be high before that beat is offered - `make sim_last_level` presents it as a held level, with producer bubbles, to keep that fixed. |
| 0x04 | `STATUS` | R | bit0 `BUSY` (`run & ~done & ~err & ~underrun`); bit1 `ERR` (no code length matched, or the table index left the symbol table); bit2 `DONE` (input flushed, buffer empty, and no symbol still waiting to be taken - see the note below); bit3 `UNDERRUN` (the stream ended part-way through a code); bits[15:8] bit-buffer level |
| 0x08 | `TSEL` | RW | active table 0..5 (software writes it every 50 symbols, mirroring the bzip2 selector list) |
| 0x0C | `TBL_ADDR` | W | `{bank[2:0], kind, index[8:0]}`: kind 0: length row `index`=L (1..20); kind 1: symbol entry |
| 0x10 | `TBL_DATA` | W | kind 0: two writes, `limit[20:0]` then `base[21:0]`, and `tbl_we` pulses on the second; kind 1: one write, the 9-bit symbol, and `tbl_we` pulses on it. One `tbl_we` pulse per table entry. |
| 0x14 | `IN_ADDR` / `IN_LEN` | W | DMA source (compressed bytes): the accelerator pulls 32-bit words |
| 0x1C | `OUT_ADDR` / `OUT_LEN` | W | DMA destination for the 9-bit symbols (stored as `uint16`) |
| 0x24 | `SYM_COUNT` | R | symbols *accepted* by the output so far (a symbol held while the consumer is not ready is counted once) |

There is deliberately no soft-reset bit: the block is reset by `rst_n` with the
rest of the design. `RUN` low is enough to hold it.

**`DONE` is not the end-of-block signal, and a host must not wait for it.** It
means the input stream was flushed and every buffered bit consumed. A bzip2
block is byte-padded, so after the last real symbol there are still up to seven
pad bits in the buffer and `DONE` never rises - in the benchmark run the reader
finishes with 45 bits left. The hardware cannot tell padding from data; only the
decoder's caller knows the block ended, because it recognises the EOB symbol.
So the host stops on EOB (or on the symbol count it already tracks for `TSEL`),
and reads `DONE` only to distinguish "input exhausted" from "still running".
`ERR` is the fault worth polling for.

`UNDERRUN` needs the same care as `DONE`. It means a code was longer than the
bits left, which on a corrupt or truncated stream is a fault - but a bzip2 block
is byte-padded, so a host that leaves `RUN` high past the EOB symbol will decode
the padding and then hit `UNDERRUN` as the *normal* end of the block. Read it as
"the stream stopped part-way through a code", not as "something went wrong": on a
well-formed block reached through EOB it never asserts, and `hw/tb` asserts
exactly that (`make sim` fails if `underrun` rises on the benchmark block).

The symbol port is a valid/ready stream. `sym_valid` may be asserted while the
DMA is not ready; the symbol is then held unchanged until it is taken, and the
decoder stalls rather than dropping it. `hw/tb` runs the whole benchmark block
with that ready line gated pseudo-randomly (`make sim_bp`) precisely so this is
tested and not merely asserted.

Table programming for one block is at most 6 × (20 rows + 258 symbols) ≈ 1,700
entries, done once per 900 KB block: microseconds against a decode that the
software spends tens of milliseconds on. The benchmark's block is sparser:
`gen_vectors.py` emits 120 length rows and 882 symbol entries, so 1,002
`tbl_we` pulses.

The host must write all twenty length rows of a bank before selecting it. The
table arrays are not reset, so a row left over from a previous block would
otherwise still be compared against.

## Data flow for one bzip2 block

```
software                                   accelerator
--------                                   -----------
parse header, selectors, code lengths
build limit[]/base[]/syms[] per table  --> TBL_ADDR/TBL_DATA writes (x6 tables)
point IN_ADDR at the compressed bytes  --> bitreader refills 32 bits at a time
point OUT_ADDR at a symbol buffer
CTRL.RUN = 1                           --> one symbol per clock:
                                           peek 20 bits -> 20 parallel compares
                                           -> priority encode -> base+code
                                           -> symbol SRAM -> DMA out
write TSEL every 50 symbols            --> (or: hand the selector list to the
                                            accelerator and let a counter do it)
stop RUN on the EOB symbol, poll ERR   --> (STATUS.BUSY drops only on ERR or
                                            UNDERRUN, or on DONE if the input
                                            drains - see the DONE note above)
MTF / run expansion / BWT / RLE on the symbol buffer (unchanged code)
```

The selector switch every 50 symbols is the one piece of control that crosses
the boundary at symbol rate. Two options are implemented/considered:

1. **Software-driven `TSEL`** (what the register map above does): simple, but
   the host must poll `SYM_COUNT` and write `TSEL` 2,966 times for this block.
2. **Selector list in hardware**: write the selector list (≤ 18,002 entries of
   3 bits) into a small SRAM and let a 6-bit counter advance `tsel` every 50
   symbols. This is the better design for a real product and costs ~7 KB of
   SRAM; the RTL's `tsel` input is exactly the signal such a counter would
   drive, so the decoder itself is unchanged.

## Software changes

Only `decode_huffman_block` changes, and only if the accelerator is present:

```python
if accel is not None:
    for i, t in enumerate(tables):
        accel.load_table(i, t._limit, t._base, t._syms)
    syms = accel.decode(b.remaining_bytes(), selectors_list)   # one DMA round trip
    b.skip_bits(accel.bits_consumed())
    # ...then the existing MTF / RUNA-RUNB / BWT / RLE loop runs over `syms`
else:
    # existing pure-Python path
```

No user of the module changes: the benchmark still calls `bzip2_main(field)`
and gets the same bytes. This follows lecture 5's first rule for accelerators
- do not make end users change their code; confine the change to the library.

## Interface widths and rates

Every port and its width: report_pyflate.txt section 5.3, in the order of
huffman_accel_top.sv.

Sustained throughput is one symbol per clock; on the benchmark's block that is
148,272 cycles for 148,271 symbols (measured in `hw/tb`). The bit buffer holds
64 bits and refills 32 per cycle, and the average code is 3.6 bits (max 15 in
this file, 20 by the format), so the reader never starves the decoder.
