# L1TK Plotter
Reads CMS L1 track ntuples from multiple files, then makes efficiency and resolution plots, all configured by a YAML file. If multiple files are given, then the resulting plots are overlaid together


## Usage

`python main.py --config sample_config.yaml`

```
python main.py --config sample_config.yaml --no-overlay
python main.py --config sample_config.yaml --no-fill
python main.py --config sample_config.yaml --no-export
python main.py --config sample_config.yaml --only eff_eta

# Override any config argument:
python main.py --config sample_config.yaml --minPt 3.0
```

---
It runs in three stages

- Stage 1 (fill):   
    - reads the ntuples and writes histograms into one
                ROOT file (set by output.hist_file in the config). The effective
                config is stored alongside them as a `config` TObjString.
- Stage 2 (overlay):
    - reads that ROOT file and overlays all plots across ntuple files, writing
                the overlay canvases back into the same ROOT file.
- Stage 3 (export):
    - mirrors the whole ROOT file into output.outdir, so the plot directory has
                the same shape as the file and holds *everything* in it:

```
plots/
  config.yaml                      # the effective config for this run
  summary/<label>.txt              # the terminal summary, one file per input
  overlays/eff/eff_eta.pdf         # cross-input overlays
  overlays/res/res_pt_vs_eta.pdf
  eff/<label>/...                  # the per-input source histograms
  res/<label>/res_pt_vs_eta.pdf
  res/<label>/Bin_Projections/...
  nstub/<label>/nstub_pie.png
```

Use --no-fill to re-style plots quickly without reading the ntuples again, and
--no-export to skip writing the file tree (the bin-projection canvases make it
the slow part of a run).

#### Script Aliasing
To run the plotter from other loations, optionally add the following script to path:
```
#!/bin/bash
exec python $PATH_TO_PLOTTER/main.py "$@"
```

### TODO
- [ ] nstub pi chart
- [ ] print duplicate rate etc
- [ ] other cut blocks
- [x] option to save proj hists
- [x] option to overlay other cut blocks
- [ ] General x y plotting options?
- [ ] cut string validations
- [ ] H/L pt regions
- [ ] eta regions

### DISCLAIMER
Unfortunately, a lot of this code is created with the help of AI (I know, I am an awful person). All the overhead and config logistics, including plot overlays and i/o; HOWEVER, the plotting logic WAS implemented by myself.

