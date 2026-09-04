# Huffman decode accelerator: hardware/software interface

This describes how the accelerator in `hw/rtl/` plugs into pyflate. The
software side is the optimized decoder in `benchmarks/pyflate/run_benchmark_opt.py`;
the hardware replaces exactly one call site, `HuffmanTable.find_next_symbol`,
which the profile shows is still ~50% of the optimized run.

## What moves to hardware, what stays

| Stage of `decode_huffman_block` | Where | Why |
|---|---|---|
| Parse block header, selectors, code lengths (`compute_used`, `compute_selectors_list`, `compute_tables`) | software | once per 900 KB block, negligible |
| Canonical-Huffman symbol decode (`find_next_symbol` + `snoopbits`/`readbits`) | **hardware** | ~62% of remaining time; bit-serial work, one symbol per clock in hardware |
| Move-to-front, RUNA/RUNB run expansion | software | cheap after the decode fix (`pop`/`insert`, ~4% of the profile) |
| Inverse BWT (`bwt_transform`, `bwt_reverse`) | software | a 400 KB pointer chase; memory-latency bound, no datapath helps it |
| Final RLE, output assembly | software | one regex pass |

The interface is therefore: *tables in, bytes in, symbols out*.

## Register map (memory-mapped, 32-bit registers)

| Offset | Name | R/W | Meaning |
|---|---|---|---|
| 0x00 | `CTRL` | RW | bit0 `RUN` decode enabled; bit1 `RESET` soft reset; bit2 `LAST` the current DMA buffer is the end of the stream |
| 0x04 | `STATUS` | R | bit0 `BUSY`; bit1 `ERR` (no code length matched); bits[15:8] bit-buffer level |
| 0x08 | `TSEL` | RW | active table 0..5 (software writes it every 50 symbols, mirroring the bzip2 selector list) |
| 0x0C | `TBL_ADDR` | W | `{bank[2:0], kind, index[8:0]}`: kind 0: length row `index`=L (1..20); kind 1: symbol entry |
| 0x10 | `TBL_DATA` | W | kind 0: `{base[21:0], limit[20:0]}` packed over two writes; kind 1: 9-bit symbol. A write to `TBL_DATA` pulses `tbl_we`. |
| 0x14 | `IN_ADDR` / `IN_LEN` | W | DMA source (compressed bytes): the accelerator pulls 32-bit words |
| 0x1C | `OUT_ADDR` / `OUT_LEN` | W | DMA destination for the 9-bit symbols (stored as `uint16`) |
| 0x24 | `SYM_COUNT` | R | symbols emitted so far |

Table programming for one block is at most 6 × (20 rows + 258 symbols) ≈ 1,700
register writes, done once per 900 KB block: microseconds against a decode
that the software spends tens of milliseconds on.

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
wait for STATUS.BUSY == 0
MTF / run expansion / BWT / RLE on the symbol buffer (unchanged code)
```

The selector switch every 50 symbols is the one piece of control that crosses
the boundary at symbol rate. Two options are implemented/considered:

1. **Software-driven `TSEL`** (what the register map above does): simple, but
   the host must poll `SYM_COUNT` and write `TSEL` 2,965 times for this block.
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

| Signal | Width | Notes |
|---|---|---|
| `in_data` | 32 bit | compressed stream, MSB-first; `in_ready` throttles the DMA |
| `peek` (internal) | 20 bit | longest bzip2 code |
| `sym` | 9 bit | bzip2 alphabet ≤ 258 |
| `len` | 5 bit | 1..20 |
| `tsel` | 3 bit | 6 tables |
| table row | 21 + 22 bit | `limit[L]` unsigned, `base[L]` signed |

Sustained throughput is one symbol per clock; on the benchmark's block that is
148,275 cycles for 148,271 symbols (measured in `hw/tb`). The bit buffer holds
64 bits and refills 32 per cycle, and the average code is 3.6 bits (max 15 in
this file, 20 by the format), so the reader never starves the decoder.
