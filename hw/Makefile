# hw/Makefile -- simulate (Icarus Verilog) and synthesize (Yosys) the Huffman accelerator.
#
#   make vectors          golden data from the software decoder into tb/vectors/
#   make sim              the real bzip2 block at full rate; asserts one symbol per cycle
#   make sim_bp           the same block with both handshakes throttled (+bp)
#   make sim_last_level   the same block with LAST held as a level (+bp +last_level)
#   make sim_all          the six directed sets from tb/gen_synth_vectors.py, then
#                         sim, sim_bp and sim_last_level
#   make synth            regenerate docs/synthesis_yosys.txt with Yosys
#   tb/mutate.sh          inject 20 bugs into the RTL one at a time, sim_all on each
#
# The +bp, +last_level, +bubble, +expect_err and +expect_underrun plusargs are
# explained where tb/tb_huffman.sv declares them.
IVL  ?= iverilog -g2012
VVP  ?= vvp
PY   ?= python3
# The course VM ships Yosys 0.9, which predates `for (int i = ...)`; there run
# `make synth YOSYS=/path/to/a/newer/yosys`.
YOSYS ?= yosys
RTL   = rtl/bitreader.sv rtl/huffman_decoder.sv rtl/huffman_accel_top.sv
TB    = tb/tb_huffman.sv

.PHONY: sim sim_all sim_bp sim_last_level vectors synth_vectors synth clean
sim: build/tb tb/vectors/expected.txt
	@$(VVP) build/tb > build/sim.log 2>&1; rc=$$?; cat build/sim.log; \
	if [ $$rc -ne 0 ]; then echo "make sim: simulator exited $$rc"; exit $$rc; fi; \
	grep -q '^PASS' build/sim.log || { echo "make sim: FAILED - no PASS line (see build/sim.log)"; exit 1; }
# Backpressure: out_ready and in_valid gated pseudo-randomly. The cycle count
# is worse by construction, so the throughput assertion is skipped in this mode.
sim_bp: build/tb tb/vectors/expected.txt
	@$(VVP) build/tb +bp > build/sim_bp.log 2>&1; rc=$$?; tail -4 build/sim_bp.log; \
	if [ $$rc -ne 0 ]; then echo "make sim_bp: simulator exited $$rc"; exit $$rc; fi; \
	grep -q '^PASS' build/sim_bp.log || { echo "make sim_bp: FAILED (see build/sim_bp.log)"; exit 1; }

# LAST held as a level, with producer bubbles: the register-mapped host style.
sim_last_level: build/tb tb/vectors/expected.txt
	@$(VVP) build/tb +bp +last_level > build/sim_last.log 2>&1; rc=$$?; tail -3 build/sim_last.log; \
	if [ $$rc -ne 0 ]; then echo "make sim_last_level: simulator exited $$rc"; exit $$rc; fi; \
	grep -q '^PASS' build/sim_last.log || { echo "make sim_last_level: FAILED (see build/sim_last.log)"; exit 1; }

# tb_huffman.sv always reads tb/vectors/, so each directed set runs from its own
# directory with tb/vectors symlinked to it. (No path plusarg: the course VM's
# Icarus 11 is fussy about them.)
# run_one <dir> <plusargs>
define run_one
	@rm -rf build/run_$(1) && mkdir -p build/run_$(1)/tb
	@ln -s ../../../tb/vectors_$(1) build/run_$(1)/tb/vectors
	@( cd build/run_$(1) && $(VVP) ../../build/tb $(2) > ../$(1).log 2>&1 ) \
	  && grep -qE '^PASS' build/$(1).log \
	  && echo "  $(1): PASS  ($$(grep -m1 decoded build/$(1).log))" \
	  || { echo "  $(1): FAILED"; tail -8 build/$(1).log; exit 1; }
endef

synth_vectors:
	@$(PY) tb/gen_synth_vectors.py

# The directed sets run first: they take milliseconds and a broken decoder
# usually fails one of them, so the 148,271-symbol runs only start on a design
# that already passed the cheap checks. That keeps a twenty-mutation sweep
# affordable on one vCPU.
sim_all: synth_vectors build/tb
	@echo "directed vector sets:"
	$(call run_one,lengths,)
	$(call run_one,eof,)
	$(call run_one,err,+expect_err)
	$(call run_one,badidx,+expect_err)
	$(call run_one,underrun,+expect_underrun)
	$(call run_one,drain,)
	$(call run_one,drain,+last_level +bubble)
	@$(MAKE) --no-print-directory sim
	@$(MAKE) --no-print-directory sim_bp
	@$(MAKE) --no-print-directory sim_last_level
	@echo "all simulations passed"

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
	$(YOSYS) -q synth.ys
	@YOSYS=$(YOSYS) $(PY) tb/synth_report.py > ../docs/synthesis_yosys.txt && echo "wrote docs/synthesis_yosys.txt"
