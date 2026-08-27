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


def style_hist(h, i, xlabel, ylabel, title):
    """Apply i-th color/marker to `h` and set the labels + title."""
    c = COLORS[i % len(COLORS)]
    h.SetLineColor(c)
    h.SetMarkerColor(c)
    h.SetMarkerStyle(MARKERS[i % len(MARKERS)])
    h.SetMarkerSize(0.72)
    h.SetLineWidth(2)
    h.GetXaxis().SetTitle(xlabel)
    h.GetYaxis().SetTitle(ylabel)
    h.GetYaxis().SetTitleOffset(1.8)
    h.SetTitle(title)
