
all: fle

# Output directory for targets
outdir := out
$(outdir):
	mkdir -p $@
.PHONY: clean
clean:
	rm -r $(outdir)

# Generate ADIF files from FLE
fle_src := $(wildcard src/*.fle)
fle_adi := $(patsubst src/%.fle,$(outdir)/%.adi,$(fle_src))
.PHONY: fle
fle: $(fle_adi)
$(outdir)/%.adi: src/%.fle $(outdir)
	FLEcli adif -o $< $@
