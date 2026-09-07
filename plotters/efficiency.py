"""Efficiency plots for the L1Track plotter.

Implements the two-function contract documented in plotter_plan.md:
  * fill(cfg, rdfs, out_dir) — fill histograms into out_dir.
  * load(cfg, in_dir, labels) — read them back as styled Curves.

See `Plot module interface` in plotter_plan.md for the contract and a
worked example.
"""

from __future__ import annotations

from array import array

from config import Config
from overlay import Curve
import style

import ROOT
ROOT.EnableImplicitMT()


def _model(name, title, x):
    """TH1DModel for one efficiency variable, uniform or variable-width."""
    if x.edges:
        return ROOT.RDF.TH1DModel(name, title, len(x.edges) - 1,
                                  array("d", x.edges))
    return ROOT.RDF.TH1DModel(name, title, x.nbins, x.lo, x.hi)


def clean_label(label):
    """replace spaces with _ and . with p to the labels play nice with root"""
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
        "tp_pt >= 0.2",
        f"abs(tp_eta) <= {p.maxEta}",
    ]

    if p.primaryOnly:
        if "tp_eventid" in col_names:
            cuts.append("tp_eventid == 0")
        else:
            print("Warning: no column 'tp_eventid' exists. Ignoring primaryOnly")

    return " && ".join(cuts)

def fill(cfg: Config, rdfs, out_dir) -> None:
    """Stage 1. Fill num/den/eff TH1s for each VARIABLES entry × input.

    Parameters
    ----------
    cfg     : config.Config
    rdfs    : list[tuple[ROOT.RDataFrame, str]]
    out_dir : ROOT.TDirectory  (e.g. f.mkdir("eff") from main.py)
    """
    
    p = cfg.cuts
    for rdf, label in rdfs:
        print(f"[fill] Making efficiency plots for {label}")
        # base cuts
        rf = rdf.Define("tp_base", base_cuts(rdf, p))

        # remove events with no selected TPs
        rf = rf.Filter("ROOT::VecOps::Sum(tp_base) > 0")
        
        # kinematic cuts
        rf = rf.Define("tp_kin", f"tp_base && tp_pt > {p.minPt}")

        # tps with matched trks
        rf = rf.Define("tp_match",
                       f"tp_nmatch >= 1"
                       f" && matchtrk_nstub >= {p.minNstub}"
                       f" && matchtrk_chi2 <= {p.maxChi2}"
                       f" && matchtrk_chi2_dof <= {p.maxChi2dof}")


        sub = out_dir.mkdir(clean_label(label))
        sub.cd()
        
        for x in cfg.efficiency.variables:
            den_mask = "tp_base" if x.branch == "tp_pt" else "tp_kin"
            rfx = (rf.Define(f"den_{x.key}", f"{x.branch}[{den_mask}]")
                     .Define(f"num_{x.key}", f"{x.branch}[{den_mask} && tp_match]"))

            model_num = _model(f"h_matched_{x.key}",
                               f";matched {x.key};counts", x)
            h_num = rfx.Histo1D(model_num, f"num_{x.key}").GetValue()

            model_den = _model(f"h_tp_{x.key}", f";{x.xlabel};counts", x)
            h_den = rfx.Histo1D(model_den, f"den_{x.key}").GetValue()

            h_num.Sumw2()
            h_den.Sumw2()

            h_num.Write()
            h_den.Write()

            # Efficiency as a TEfficiency rather than a hand-rolled ratio: it
            # keeps the (passed, total) pair and derives the uncertainty from
            # them with Clopper-Pearson intervals, which stay inside [0, 1] and
            # remain meaningful at 0% / 100% where the naive binomial error
            # collapses to zero. Errors are asymmetric, so stage 2 draws it as
            # a graph rather than a histogram.
            if not ROOT.TEfficiency.CheckConsistency(h_num, h_den):
                print(f"[fill] {label}: passed/total inconsistent for "
                      f"{x.key!r}, skipping efficiency")
                continue

            h_eff = ROOT.TEfficiency(h_num, h_den)
            h_eff.SetName(f"eff_{x.key}")
            h_eff.SetTitle(f";{x.xlabel};Efficiency")
            # ROOT's defaults, set explicitly so the interval is on the record.
            h_eff.SetStatisticOption(ROOT.TEfficiency.kFCP)  # Clopper-Pearson
            h_eff.SetConfidenceLevel(0.682689492137)         # 1 sigma
            h_eff.Write()
            h_eff.SetDirectory(0)  # don't let f.Write() add a second cycle


                

def load(cfg: Config, in_dir, labels: list[str]) -> dict[str, list[Curve]]:
    """Stage 2. Read the filled TEfficiencies, style them, package as Curves.

    Assumes fill() wrote, for each input label:
        in_dir/<clean_label(label)>/eff_<v.key>     TEfficiency

    Returns dict[plot_key -> list[Curve]] keyed by 'eff_<v.key>' —
    overlay.draw_overlay draws those as points with asymmetric error bars.
    """
    result: dict[str, list[Curve]] = {}

    for v in cfg.efficiency.variables:
        plot_key = f"eff_{v.key}"

        curves: list[Curve] = []
        for i, label in enumerate(labels):
            sub = in_dir.GetDirectory(clean_label(label))
            if not sub:
                print(f"[load] missing dir for {label!r} in {in_dir.GetName()}")
                continue
            h = sub.Get(f"eff_{v.key}")
            if not h:
                print(f"[load] missing eff_{v.key} in {label!r}")
                continue

            # Detach so the object survives the TFile close in main.py
            h.SetDirectory(0)
            style.style_eff(h, i, v.xlabel, "Efficiency",
                            f"Efficiency vs {v.key}")
            curves.append(Curve(label=label, hist=h))

        if curves:
            result[plot_key] = curves

    return result
