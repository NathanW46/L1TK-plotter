"""L1Track plotter — CLI entry point.

Two-stage pipeline:
    stage 1 (fill):    open each input as an RDataFrame, fill histograms,
                       write them into output.hist_file.
    stage 2 (overlay): read those histograms back, draw per-input overlays,
                       save as PDF/PNG into output.outdir.

Run from inside plotter/:
    python main.py --config config.yaml
    python main.py --config config.yaml --no-overlay      # fill only
    python main.py --config config.yaml --no-fill         # overlay only
    python main.py --config config.yaml --minPt 3.0 --tag v2
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace

import ROOT

import config as cfg_mod
import rdfio

# Plot modules and the overlay renderer are written separately. Import
# lazily so `python main.py --help` and config validation still work before
# they exist.
try:
    from plotters import efficiency, resolution
except ImportError:
    efficiency = None
    resolution = None

try:
    import overlay as overlay_mod
except ImportError:
    overlay_mod = None


ROOT.gROOT.SetBatch(True)
ROOT.gErrorIgnoreLevel = ROOT.kWarning


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("--config", required=True, help="path to YAML config")

    # Stage toggles
    p.add_argument("--no-fill", action="store_true",
                   help="skip stage 1 (assume hist_file already exists)")
    p.add_argument("--no-overlay", action="store_true",
                   help="skip stage 2 (just fill the hist_file)")

    # Plot subset
    p.add_argument("--only", default=None,
                   help="comma-separated plot keys to render; default = all")

    # Output overrides
    p.add_argument("--hist-file", default=None)
    p.add_argument("--outdir", default=None)
    p.add_argument("--tag", default=None)
    p.add_argument("--format", choices=("pdf", "png"), default=None)

    # Cut-parameter overrides (one per CutParams field)
    p.add_argument("--minPt", type=float, default=None)
    p.add_argument("--maxEta", type=float, default=None)
    p.add_argument("--minNstub", type=int, default=None)
    p.add_argument("--maxD0", type=float, default=None)
    p.add_argument("--maxLxy", type=float, default=None)
    p.add_argument("--primaryOnly", action="store_true", default=None,
                   help="override primaryOnly to True")

    return p.parse_args()


def apply_cli_overrides(cfg: cfg_mod.Config,
                        args: argparse.Namespace) -> cfg_mod.Config:
    """Return a new Config with CLI flags substituted where given."""
    cut_overrides = {
        f: getattr(args, f)
        for f in ("minPt", "maxEta", "minNstub", "maxD0", "maxLxy", "primaryOnly")
        if getattr(args, f) is not None
    }
    cuts = replace(cfg.cuts, **cut_overrides) if cut_overrides else cfg.cuts

    out_overrides = {
        k: v for k, v in (
            ("hist_file", args.hist_file),
            ("outdir",    args.outdir),
            ("tag",       args.tag),
            ("format",    args.format),
        ) if v is not None
    }
    output = replace(cfg.output, **out_overrides) if out_overrides else cfg.output

    return replace(cfg, cuts=cuts, output=output)


def _selected(keys: list[str], only: set[str] | None) -> list[str]:
    return keys if only is None else [k for k in keys if k in only]


def stage_fill(cfg: cfg_mod.Config) -> None:
    """Open RDataFrames for every input; dispatch to plot modules' fill()."""
    if efficiency is None or resolution is None:
        sys.exit("stage 1 needs plotters/efficiency.py and plotters/resolution.py "
                 "— not yet implemented.")

    rdfs = [(rdfio.open_rdf(i.file), i.label) for i in cfg.inputs]
    print(f"[fill] opened {len(rdfs)} input(s): "
          f"{', '.join(i.label for i in cfg.inputs)}")

    with rdfio.hist_file_writer(cfg.output.hist_file) as f:
        res_dir = f.mkdir("res")
        resolution.fill(cfg, rdfs, res_dir)
        eff_dir = f.mkdir("eff")
        efficiency.fill(cfg, rdfs, eff_dir)
    print(f"[fill] wrote {cfg.output.hist_file}")


def stage_overlay(cfg: cfg_mod.Config, only: set[str] | None) -> None:
    """Read hist_file, draw per-plot overlays, save to outdir."""
    if efficiency is None or resolution is None or overlay_mod is None:
        sys.exit("stage 2 needs plotters/{efficiency,resolution}.py and "
                 "overlay.py — not yet implemented.")

    os.makedirs(cfg.output.outdir, exist_ok=True)
    labels = [i.label for i in cfg.inputs]

    with rdfio.hist_file_updater(cfg.output.hist_file) as f:
        overlays  = rdfio.ensure_dir(f, "overlays")
        eff_overs = rdfio.ensure_dir(overlays, "eff")
        res_overs = rdfio.ensure_dir(overlays, "res")

        for plot_key, curves in efficiency.load(cfg, f.Get("eff"), labels).items():
            if only is None or plot_key in only:
                overlay_mod.draw_overlay(curves, plot_key=plot_key,
                                        output=cfg.output, legend_corner="br",
                                        ymin=0, ymax=1,
                                        write_to=eff_overs)
        for plot_key, curves in resolution.load(cfg, f.Get("res"), labels).items():
            if only is None or plot_key in only:
                overlay_mod.draw_overlay(curves, plot_key=plot_key,
                                        output=cfg.output, legend_corner="tr",
                                        write_to=res_overs)
    print(f"[overlay] wrote {cfg.output.outdir}/*.{cfg.output.format}")
    print(f"[overlay] also saved canvases to {cfg.output.hist_file}:/overlays/")


def main() -> None:
    args = parse_args()
    cfg = cfg_mod.load_config(args.config)
    cfg = apply_cli_overrides(cfg, args)

    only = set(args.only.split(",")) if args.only else None

    if not args.no_fill:
        stage_fill(cfg)
    if not args.no_overlay:
        stage_overlay(cfg, only)


if __name__ == "__main__":
    main()
