"""Generic overlay rendering for the L1Track plotter.

Stage 2 of the pipeline: the plot modules in plots/ load curves out of the
intermediate output_plots.root file and hand them here as Curve objects.
`draw_overlay()` then handles the canvas / legend and stores the canvas back
into the ROOT file. Writing images to disk is export.py's job — it mirrors the
whole ROOT file into the output directory in one pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import ROOT

from config import OutputSpec


@dataclass
class Curve:
    """One styled histogram + metadata, ready to be drawn on an overlay.

    label
        Legend text. Typically the input label, optionally with a band
        suffix like " (pT<8)".
    hist
        A TH1 (or subclass). Must already have style.style_hist() applied
        by the plot module that produced it.
    extras
        Free-form per-curve metadata for richer legend entries. Conventions
        used by the existing plot modules:
            {"eps":   <float>}                  # avg efficiency
            {"n_num": <int>, "n_den": <int>}    # entry counts
        draw_overlay does NOT look at `extras` — it just attaches them to
        the Curve for the caller's own bookkeeping. If you want fancier
        legend text, format it into `label` directly.
    """
    label: str
    hist: "ROOT.TH1"
    extras: dict[str, Any] = field(default_factory=dict)


def draw_overlay(
    curves: list[Curve],
    *,
    plot_key: str,
    output: OutputSpec,
    legend_corner: str = "tr",
    ymin: float | None = None,
    ymax: float | None = None,
    write_to: "ROOT.TDirectory | None" = None,
    draw_opt: str = "E1",
    legend_opt: str | None = None,
) -> None:
    """Draw `curves` on one canvas and write it into a TFile directory.

    Parameters
    ----------
    curves
        One styled Curve per input file (and optionally per pT band, for
        resolutions). Drawn in order, first with `draw_opt`, rest with
        `draw_opt + " SAME"`.
    plot_key
        Used for the canvas name (and, for the on-disk export, the filename
        stem — see export.py).
    output
        config.OutputSpec. Accepted for interface stability; the on-disk
        naming (outdir/tag/format) is applied by export.dump_tree().
    legend_corner
        'tr' (top-right; default — resolutions sit low) or
        'br' (bottom-right; efficiencies sit near 1).
    ymin, ymax
        Optional y-axis overrides. Defaults pick [0, 1.15*max] for
        non-negative curves and [1.1*min, 1.15*max] otherwise.
    write_to
        Optional TDirectory inside the open output_plots.root. When given,
        the rendered TCanvas is `Write()`ten there under the name `plot_key`,
        so the overlay survives alongside the per-input hists.
    draw_opt
        ROOT draw option. "E1" (default) draws markers with error bars;
        "HIST" draws the bare connected-line histogram with no error bars and
        an unfilled base — used for interval-method resolutions, whose points
        carry no meaningful per-bin error.
    legend_opt
        TLegend entry option. Defaults to "lep" for error-bar styles and "l"
        for line-only styles, so the legend keys match what is drawn (a plain
        line rather than a marker + error bar).

    Images are not written here: export.dump_tree() renders every object in
    the ROOT file, so the output directory mirrors the file's structure.
    """
    if not curves:
        print(f"[overlay] {plot_key}: no curves, skipping")
        return

    c = ROOT.TCanvas(f"c_{plot_key}", plot_key, 700, 600)
    c.SetGrid()
    c.SetLeftMargin(0.15)
    ROOT.gStyle.SetOptStat(0)

    # y-axis range
    auto_max = max(cu.hist.GetMaximum() for cu in curves)
    auto_min = min(cu.hist.GetMinimum() for cu in curves)
    if ymin is None:
        ymin = 0.0 if auto_min >= 0 else 1.1 * auto_min
    if ymax is None:
        ymax = 1.15 * auto_max if auto_max > 0 else 1.0

    curves[0].hist.SetMinimum(ymin)
    curves[0].hist.SetMaximum(ymax)
    curves[0].hist.Draw(draw_opt)
    for cu in curves[1:]:
        cu.hist.Draw(f"{draw_opt} SAME")

    # An "E"-less draw option paints no markers or error bars, so a "lep"
    # legend key would advertise both. Fall back to a plain line key.
    if legend_opt is None:
        legend_opt = "lep" if "E" in draw_opt.upper().replace("HIST", "") else "l"

    # legend placement. Width scales with the longest label so entries like
    # "NEWKF MERGE  nstub == 4" aren't clipped; clamp so it can't grow past
    # the left margin.
    longest = max((len(cu.label) for cu in curves), default=0)
    width = min(0.55, max(0.245, 0.011 * longest))
    x2 = 0.9
    x1 = x2 - width
    if legend_corner == "br":
        y1 = 0.18
        y2 = y1 + 0.05 * len(curves)
    else:  # 'tr' (default)
        y2 = 0.88
        y1 = y2 - 0.05 * len(curves)

    legend = ROOT.TLegend(x1, y1, x2, y2)
    legend.SetBorderSize(1)
    legend.SetFillColor(0)
    legend.SetTextSize(0.03)
    for cu in curves:
        legend.AddEntry(cu.hist, cu.label, legend_opt)
    legend.Draw()

    c.Update()

    if write_to is not None:
        write_to.cd()
        # ROOT key names can't contain '/', so flatten any sub-dir path.
        # kOverwrite replaces the previous key instead of appending a new write
        # cycle, so re-running stage 2 (--no-fill) doesn't grow the file.
        c.Write(plot_key.replace("/", "_"), ROOT.TObject.kOverwrite)
