"""Generic overlay rendering for the L1Track plotter.

Stage 2 of the pipeline: the plot modules in plots/ load curves out of the
intermediate output_plots.root file and hand them here as Curve objects.
`draw_overlay()` then handles the canvas / legend / SaveAs.
"""

from __future__ import annotations

import os
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
) -> None:
    """Draw `curves` on one canvas, save to disk, optionally save to a TFile.

    Parameters
    ----------
    curves
        One styled Curve per input file (and optionally per pT band, for
        resolutions). Drawn in order, first with "E1", rest with "E1 SAME".
    plot_key
        Used for the canvas name and as the output filename stem.
    output
        config.OutputSpec — provides outdir, tag, format.
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

    Output path:  <outdir>/<plot_key>[_<tag>].<format>
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
    curves[0].hist.Draw("E1")
    for cu in curves[1:]:
        cu.hist.Draw("E1 SAME")

    # legend placement
    if legend_corner == "br":
        x1, x2 = 0.655, 0.9
        y1 = 0.18
        y2 = y1 + 0.05 * len(curves)
    else:  # 'tr' (default)
        x1, x2 = 0.655, 0.9
        y2 = 0.88
        y1 = y2 - 0.05 * len(curves)

    legend = ROOT.TLegend(x1, y1, x2, y2)
    legend.SetBorderSize(1)
    legend.SetFillColor(0)
    legend.SetTextSize(0.03)
    for cu in curves:
        legend.AddEntry(cu.hist, cu.label, "lep")
    legend.Draw()

    c.Update()

    os.makedirs(output.outdir, exist_ok=True)
    tag = f"_{output.tag}" if output.tag else ""
    out_path = os.path.join(output.outdir, f"{plot_key}{tag}.{output.format}")
    c.SaveAs(out_path)
    print(f"[overlay] wrote {out_path}")

    if write_to is not None:
        write_to.cd()
        c.Write(plot_key)
