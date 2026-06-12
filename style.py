"""Histogram styling for the L1Track plotter.

Eight-color palette + matching marker shapes, cycled by index so the i-th
overlaid curve always lands on COLORS[i] and MARKERS[i]. Identical to the
palette used by ../overlay_eff.py:28-38 and ../overlay_res.py:36-46.
"""

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
    """Apply the i-th color/marker to `h` and set its axis labels + title."""
    c = COLORS[i % len(COLORS)]
    h.SetLineColor(c)
    h.SetMarkerColor(c)
    h.SetMarkerStyle(MARKERS[i % len(MARKERS)])
    h.SetMarkerSize(0.9)
    h.SetLineWidth(2)
    h.GetXaxis().SetTitle(xlabel)
    h.GetYaxis().SetTitle(ylabel)
    h.GetYaxis().SetTitleOffset(1.8)
    h.SetTitle(title)
