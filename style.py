"""Histogram styling for the L1Track plotter.
Color palette + matching marker shapes for overlaying plots."""

import ROOT


COLORS = [
    ROOT.kBlue + 1,
    ROOT.kRed + 1,
    ROOT.kGreen + 2,
    ROOT.kMagenta + 1,
    ROOT.kOrange + 7,
    ROOT.kCyan + 2,
    ROOT.kViolet + 1,
    ROOT.kAzure + 2,
]
MARKERS = [20, 21, 22, 23, 33, 34, 29, 24]


def _apply_attrs(o, i):
    """Apply the i-th colour / marker of the palette to any TAttLine +
    TAttMarker object (TH1, TEfficiency, TGraph, ...)."""
    c = COLORS[i % len(COLORS)]
    o.SetLineColor(c)
    o.SetMarkerColor(c)
    o.SetMarkerStyle(MARKERS[i % len(MARKERS)])
    o.SetMarkerSize(0.72)
    o.SetLineWidth(2)
    # Hollow base: overlays read as outlines, so nothing should paint a solid
    # block under the curve when it is drawn with "HIST".
    o.SetFillStyle(0)


def style_hist(h, i, xlabel, ylabel, title):
    """Apply i-th color/marker to `h` and set the labels + title."""
    _apply_attrs(h, i)
    h.GetXaxis().SetTitle(xlabel)
    h.GetYaxis().SetTitle(ylabel)
    h.GetYaxis().SetTitleOffset(1.8)
    h.SetTitle(title)


def style_eff(e, i, xlabel, ylabel, title):
    """Apply i-th color/marker to a TEfficiency and set the labels + title.

    A TEfficiency owns no axes of its own — it paints a TGraphAsymmErrors at
    draw time — so the labels go through SetTitle("title;xlabel;ylabel"), which
    ROOT splits out onto the underlying passed/total histograms."""
    _apply_attrs(e, i)
    e.SetTitle(f"{title};{xlabel};{ylabel}")
