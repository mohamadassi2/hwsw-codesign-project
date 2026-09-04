# hw/Makefile -- simulate the Huffman accelerator against the real benchmark data.
#   make vectors   dump golden tables/stream/symbols from the software decoder
#   make sim       compile with Icarus Verilog and run the testbench
IVL  ?= iverilog -g2012
VVP  ?= vvp
PY   ?= python3
RTL   = rtl/bitreader.sv rtl/huffman_decoder.sv rtl/huffman_accel_top.sv
TB    = tb/tb_huffman.sv

.PHONY: sim vectors clean
sim: build/tb tb/vectors/expected.txt
	$(VVP) build/tb
build/tb: $(RTL) $(TB)
	@mkdir -p build
	$(IVL) -o $@ $(RTL) $(TB)
vectors tb/vectors/expected.txt: gen_vectors.py ../benchmarks/pyflate/run_benchmark_opt.py
	$(PY) gen_vectors.py
clean:
	rm -rf build
