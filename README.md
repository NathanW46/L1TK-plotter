# L1TK Plotter
Reads CMS L1 track ntuples from multiple files, then makes efficiency and resolution plots, all configured by a YAML file. If multiple files are given, then the resulting plots are overlaid together


## Usage

`python main.py --config sample_config.yaml`


`python main.py --config sample_config.yaml --no-overlay`
`python main.py --config sample_config.yaml --no-fill`
`python main.py --config sample_config.yaml --only eff_eta`
Override any config argument:
`python main.py --config sample_config.yaml --minPt 3.0` 

---
It runs in two stages

- Stage 1 (fill):   
    - reads the ntuples and writes histograms into one
                ROOT file (set by output.hist_file in the config).
- Stage 2 (overlay):
    - reads that ROOT file and overlays all plots across ntuple files. Also saves the overlay plots as PDF or PNG into output.outdir.

Use --no-fill to re-style plots quickly without reading the ntuples again.

#### Script Aliasing
To run the plotter from other loations, optionally add the following script to path:
```
#!/bin/bash
exec python $PATH_TO_PLOTTER/main.py "$@"
```


### DISCLAIMER
Unfortunately, a lot of this code is AI generated. All the overhead and config logistics, including plot overlays and i/o; HOWEVER, the plotting logic WAS implemented by myself.

