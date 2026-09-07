"""L1Track plotter — CLI entry point.

Three-stage pipeline:
    stage 1 (fill):    open each input as an RDataFrame, fill histograms,
                       write them into output.hist_file.
    stage 2 (overlay): read those histograms back, draw per-input overlays,
                       write the canvases into output.hist_file.
    stage 3 (export):  mirror the whole ROOT file into output.outdir as a
                       directory tree of PDF/PNG/TXT files — including the
                       effective config and the per-input run summaries.

Run from inside plotter/:
    python main.py --config config.yaml
    python main.py --config config.yaml --no-overlay      # fill only
    python main.py --config config.yaml --no-fill         # overlay only
    python main.py --config config.yaml --no-export       # skip the file tree
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
# try:
#     from plotters import efficiency, resolution
# except ImportError:
#     efficiency = None
#     resolution = None
try:
    from plotters import efficiency
except ImportError:
    efficiency = None

try:
    from plotters import resolution
except ImportError:
    resolution = None

try:
    from plotters import nstub_piechart
except ImportError:
    nstub_piechart = None

try:
    from plotters import summary as summary_mod
except ImportError:
    summary_mod = None

try:
    import overlay as overlay_mod
except ImportError:
    overlay_mod = None

try:
    import export as export_mod
except ImportError:
    export_mod = None


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
    p.add_argument("--no-export", action="store_true",
                   help="skip stage 3 (don't mirror the hist_file into outdir)")

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
        # Stash the effective config (post CLI overrides) so plots can be
        # traced back to the setup that produced them. Stored as a TObjString
        # named 'config' at the file root; read back with
        #   f.Get("config").GetString().
        f.WriteObject(ROOT.TObjString(cfg_mod.to_yaml(cfg)), "config")
        res_dir = f.mkdir("res")
        resolution.fill(cfg, rdfs, res_dir)
        eff_dir = f.mkdir("eff")
        efficiency.fill(cfg, rdfs, eff_dir)
        if nstub_piechart is not None:
            nstub_dir = f.mkdir("nstub")
            nstub_piechart.fill(cfg, rdfs, nstub_dir)
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
        # Draw style follows resolution.method. The interval half-width has no
        # meaningful per-bin error (fill() pins it to zero), so those plots are
        # drawn as bare connected-line histograms with an unfilled base and a
        # line-only legend. The RMS carries an RMS error, so it keeps markers
        # and error bars.
        res_draw = "HIST" if cfg.resolution.method == "interval" else "E1"

        res_top = f.Get("res")
        for plot_key, curves in resolution.load(cfg, res_top, labels).items():
            if only is not None and plot_key not in only:
                continue
            # Standard overlays (one curve per input) go under overlays/res.
            # Extra-cut block plots instead live in the res/ source tree next
            # to the hists they came from:
            #   <block>/<label>/res_<tag>  -> res/<label>/<block>/
            #   <block>/res_<tag>          -> res/<block>/   (overlaid inputs)
            parts = plot_key.split("/")
            if len(parts) == 1:
                dest = res_overs
            elif len(parts) == 2:
                dest = rdfio.ensure_dir(res_top, parts[0])
            else:
                dest = rdfio.ensure_dir(rdfio.ensure_dir(res_top, parts[1]),
                                        parts[0])
            overlay_mod.draw_overlay(curves, plot_key=plot_key,
                                    output=cfg.output, legend_corner="tr",
                                    write_to=dest, draw_opt=res_draw)

        # nstub pie charts render one image per input (no overlay) plus a
        # combined canvas of all pies, which lands in overlays/. The module
        # saves the images and writes the canvas itself, returning nothing.
        if nstub_piechart is not None:
            nstub_top = f.Get("nstub")
            if nstub_top:
                nstub_piechart.load(cfg, nstub_top, labels, write_to=overlays)
    print(f"[overlay] wrote canvases to {cfg.output.hist_file}:/overlays/")


def stage_summary(cfg: cfg_mod.Config, rdfs) -> None:
    """Print the end-of-run summary and stash it in the ROOT file.

    One TObjString per input under summary/, so stage 3 mirrors them out as
    <outdir>/summary/<label>.txt alongside the plots they describe.
    """
    summaries = summary_mod.print_summary(cfg, rdfs, cfg.output.hist_file)

    with rdfio.hist_file_updater(cfg.output.hist_file) as f:
        d = rdfio.ensure_dir(f, "summary")
        d.cd()
        for label, text in summaries:
            name = summary_mod.clean_label(label)
            d.Delete(f"{name};*")   # replace, don't accumulate write cycles
            d.WriteObject(ROOT.TObjString(text), name)


def main() -> None:
    args = parse_args()
    cfg = cfg_mod.load_config(args.config)
    cfg = apply_cli_overrides(cfg, args)

    only = set(args.only.split(",")) if args.only else None

    if not args.no_fill:
        stage_fill(cfg)

    # Overlay only makes sense across multiple inputs; with a single file
    # there's nothing to overlay, so skip stage 2.
    if not args.no_overlay:
        if len(cfg.inputs) < 2:
            print(f"[overlay] skipped: only {len(cfg.inputs)} input file "
                  "(need >= 2 to overlay)")
        else:
            stage_overlay(cfg, only)

    # End-of-run summary printout (mirrors L1TrackNtuplePlot.C), per input.
    if summary_mod is not None:
        rdfs = [(rdfio.open_rdf(i.file), i.label) for i in cfg.inputs]
        stage_summary(cfg, rdfs)

    # Stage 3: mirror the finished ROOT file into outdir as a directory tree.
    if not args.no_export and export_mod is not None:
        export_mod.dump_tree(cfg.output.hist_file, cfg.output.outdir,
                             cfg.output.format, cfg.output.tag)


if __name__ == "__main__":
    main()
