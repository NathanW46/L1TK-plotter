"""Resolution plots for the L1Track plotter.

Resolution = RMS of (matchtrk_X - tp_X) per bin of some x-axis.

Implements the two-function contract documented in plotter_plan.md:
  * fill(cfg, rdfs, out_dir) — fill per-x-bin RMS TH1s into out_dir.
  * load(cfg, in_dir, labels) — read them back as styled Curves.

See `Plot module interface` in plotter_plan.md for the contract and a
worked example, and ../overlay_res.py for the reference algorithm.
"""

from __future__ import annotations

import math

import ROOT
from config import Config
from overlay import Curve
import style

def clean_label(label):
    return label.replace(" ", "_").replace(".", "p")


def base_cuts(rdf, p):
    """Elementwise baseline TP selection. Cuts should match from 
       L1TrackNtuplePlot.C. tp_lxy and tp_lz are first checked, 
       and excluded if they do not exist."""
    col_names = {str(c) for c in rdf.GetColumnNames()}

    cuts = []
    if "tp_lxy" in col_names:
        cuts.append(f"abs(tp_lxy) <= {p.maxLxy}")
    else:
        print("Warning: no column named 'tp_lxy' exists. Not cutting on Lxy")
    if "tp_lz" in col_names:
        cuts.append(f"abs(tp_lz) <= {p.maxLz}")
    else:
        print("Warning: no column named 'tp_lz' exists. Not cutting on Lz")

    cuts += [
        f"abs(tp_d0) <= {p.maxD0}",
        f"tp_pt >= {p.minPt}",
        f"abs(tp_eta) <= {p.maxEta}",
    ]

    if p.primaryOnly:
        if "tp_eventid" in col_names:
            cuts.append("tp_eventid == 0")
        else:
            print("Warning: no column 'tp_eventid' exists. Ignoring primaryOnly")

    # matched-tracks
    cuts += [
        "tp_nmatch >= 1",
        f"matchtrk_nstub >= {p.minNstub}",
        f"matchtrk_chi2 <= {p.maxChi2}",
        f"matchtrk_chi2_dof <= {p.maxChi2dof}",
    ]

    return " && ".join(cuts)

# pT-band variants. `cfg.ptSplit` selects which keys from this dict to use.
# _PT_BANDS = {
#     "none": [("",     "")],
#     "low":  [("_ptL", "tp_pt <  8.0")],
#     "high": [("_ptH", "tp_pt >= 8.0")],
#     "both": [("",     ""), ("_ptL", "tp_pt < 8.0"), ("_ptH", "tp_pt >= 8.0")],
# }



def fill(cfg: Config, rdfs, out_dir) -> None:
    """Stage 1. Fill per-x-bin RMS TH1s for each RESIDUAL × XAXIS × band × input.

    Parameters
    ----------
    cfg     : config.Config
    rdfs    : list[tuple[ROOT.RDataFrame, str]]
    out_dir : ROOT.TDirectory  (e.g. f.mkdir("res") from main.py)
    """
    
    p = cfg.cuts


    for rdf, label in rdfs:
        print(f"[fill] Making resolution plots for {label}")

        # base cuts
        rf = rdf.Define("tp_matched", base_cuts(rdf, p))

        # remove events with no selected TPs
        rf = rf.Filter("ROOT::VecOps::Sum(tp_matched) > 0")

        # for cut in cfg.resolution.extra_cuts:
        #     rf = rf.Filter(f"ROOT::VecOps::All({cut})")

        sub = out_dir.mkdir(clean_label(label))
        sub.cd()
        proj_dir = sub.mkdir("Bin_Projections")

        res_2d_plots = []
        for r in cfg.resolution.residuals:
            # extra cut?
            if r.extra_cut:
                rf = rf.Redefine(f"tp_matched", r.extra_cut) \

            # find residuals
            rf_r = rf.Define(f"res_{r.key}", r.expr)

            for x in cfg.resolution.x_axes:
                name_tag = f"{r.key}_vs_{x.key}"
                rf_r = rf_r.Define(f"xax_{x.key}", x.expr)

                model = ROOT.RDF.TH2DModel(
                    f"h2_{name_tag}", "",
                    x.nbins, x.lo, x.hi,
                    r.nbins, r.lo, r.hi,
                )
                h2_ptr = rf_r.Histo2D(model, f"xax_{x.key}", f"res_{r.key}")
                res_2d_plots.append((r, x, name_tag, h2_ptr))

        for r, x, name_tag, h2_ptr in res_2d_plots:
            h2 = h2_ptr.GetValue()

            # Project onto x axis and take the rms +- rmse per x-bin.
            hres = ROOT.TH1F(f"res_{name_tag}", f";{x.xlabel};{r.ylabel}",
                             x.nbins, x.lo, x.hi)

            ncols = math.ceil(math.sqrt(x.nbins))
            nrows = math.ceil(x.nbins / ncols)
            canvas = ROOT.TCanvas(f"proj_{clean_label(label)}_{name_tag}",
                                  f"projections {name_tag}",
                                  300 * ncols, 250 * nrows)
            canvas.Divide(ncols, nrows)
            xax = h2.GetXaxis()
            projs = []  # keep alive until canvas.Write()
            for ib in range(1, x.nbins + 1):
                canvas.cd(ib)
                proj = h2.ProjectionY(f"px_{name_tag}_bin{ib}", ib, ib)
                proj.SetDirectory(0)
                lo_edge = xax.GetBinLowEdge(ib)
                hi_edge = xax.GetBinUpEdge(ib)
                proj.SetTitle(
                    f"{x.xlabel} #in [{lo_edge:.3g}, {hi_edge:.3g}];"
                    f"{r.ylabel};Entries"
                )
                proj.SetFillColor(ROOT.kAzure + 1)
                proj.SetLineColor(ROOT.kAzure + 1)
                proj.SetFillStyle(1001)        # 1001 = solid fill
                proj.Draw("HIST")
                projs.append(proj)

                if proj.GetEntries() < 1:
                    hres.SetBinContent(ib, 0.0)
                    hres.SetBinError(ib, 0.0)
                else:
                    hres.SetBinContent(ib, proj.GetRMS())
                    hres.SetBinError(ib, proj.GetRMSError())

            proj_dir.cd()
            canvas.Write()
            canvas.Close()   # drop from gROOT canvas list to free it

            sub.cd()
            hres.Write()
            hres.SetDirectory(0)  # detach so f.Write() won't re-write a 2nd cycle
            h2.Delete()


    


def load(cfg: Config, in_dir, labels: list[str]) -> dict[str, list[Curve]]:
    """Stage 2. Read filled TH1s, style them, package as Curves.

    For each (residual, x-axis) pair, looks up the matching `res_<key>`
    histogram inside every per-label subdirectory written by fill() and
    bundles them as a list of Curves (one per input, in `labels` order).

    Returns dict[plot_key -> list[Curve]] where plot_key is
    'res_<r.key>_vs_<x.key>' — overlay.draw_overlay turns that into
    plots_out/res_<r.key>_vs_<x.key>.<format>.
    """
    result: dict[str, list[Curve]] = {}

    for r in cfg.resolution.residuals:
        for x in cfg.resolution.x_axes:
            name_tag = f"{r.key}_vs_{x.key}"
            plot_key = f"res_{name_tag}"

            curves: list[Curve] = []
            for i, label in enumerate(labels):
                sub = in_dir.GetDirectory(clean_label(label))
                if not sub:
                    print(f"[load] missing dir for {label!r} in {in_dir.GetName()}")
                    continue
                h = sub.Get(f"res_{name_tag}")
                if not h:
                    print(f"[load] missing res_{name_tag} in {label!r}")
                    continue

                # Detach so the hist survives the TFile close in main.py
                h.SetDirectory(0)
                style.style_hist(h, i, x.xlabel, r.ylabel, r.title)
                curves.append(Curve(label=label, hist=h))

            if curves:
                result[plot_key] = curves

    return result
