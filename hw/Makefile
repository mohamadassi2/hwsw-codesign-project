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
	@$(VVP) build/tb > build/sim.log 2>&1; rc=$$?; cat build/sim.log; \
	if [ $$rc -ne 0 ]; then echo "make sim: simulator exited $$rc"; exit $$rc; fi; \
	grep -q '^PASS' build/sim.log || { echo "make sim: FAILED - no PASS line (see build/sim.log)"; exit 1; }
build/tb: $(RTL) $(TB)
	@mkdir -p build
	$(IVL) -o $@ $(RTL) $(TB)
vectors tb/vectors/expected.txt: gen_vectors.py ../benchmarks/pyflate/run_benchmark_opt.py
	$(PY) gen_vectors.py
clean:
	rm -rf build

# Regenerate docs/synthesis_yosys.txt from the RTL (Yosys, generic gates).
synth:
	@mkdir -p build
	yosys -q synth.ys
	@python3 tb/synth_report.py > ../docs/synthesis_yosys.txt && echo "wrote docs/synthesis_yosys.txt"
