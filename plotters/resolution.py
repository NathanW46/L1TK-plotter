from __future__ import annotations

import math
from array import array

import ROOT
from config import Config
from overlay import Curve
import style

def clean_label(label):
    """Sanitize a label into a safe ROOT directory / object name.

    Directory names must avoid '/' (a ROOT path separator) and other
    operator characters that appear in cut group keys like "chi2/dof < 10"
    or "nstub == 4". Keep the historical "."->"p" so numeric labels such as
    "0.5" stay readable, then map anything that isn't alphanumeric or '_'
    to '_'."""
    s = label.replace(" ", "_").replace(".", "p")
    return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in s)


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
        # f"matchtrk_MVA1 <= 0.3",
    ]

    return " && ".join(cuts)

# pT-band variants. `cfg.ptSplit` selects which keys from this dict to use.
# _PT_BANDS = {
#     "none": [("",     "")],
#     "low":  [("_ptL", "tp_pt <  8.0")],
#     "high": [("_ptH", "tp_pt >= 8.0")],
#     "both": [("",     ""), ("_ptL", "tp_pt < 8.0"), ("_ptH", "tp_pt >= 8.0")],
# }

# Central fraction of entries the interval window should contain.
# For a Gaussian, +-1 sigma holds ~68.3% of the area.
ONE_SIGMA_FRACTION = 0.68
# Skip the quantile calculation below this many entries — a quantile is
# meaningless for a near-empty projection.
MIN_ENTRIES = 10


def abs_residual_hist(proj):
    """Fold a residual projection into a |residual| histogram.

    The window that contains a central fraction of a (roughly zero-centred)
    residual distribution is symmetric about 0, so its half-width is just the
    corresponding quantile of |residual|. Under/overflow entries of `proj`
    have out-of-range centres, so they land in the overflow of the folded
    hist — which is exactly where the quantile helper looks for "the interval
    is really out in the tail" (see _interval_for_fraction)."""
    xax = proj.GetXaxis()
    xmax = max(abs(xax.GetXmin()), abs(xax.GetXmax()))
    nb = proj.GetNbinsX()
    habs = ROOT.TH1F(proj.GetName() + "_abs", "", nb, 0.0, xmax)
    habs.SetDirectory(0)
    for ib in range(0, nb + 2):  # include under(0)/overflow(nb+1)
        c = proj.GetBinContent(ib)
        if c:
            habs.Fill(abs(proj.GetBinCenter(ib)), c)
    return habs


def interval_for_fraction(abs_hist, fraction, min_entries=MIN_ENTRIES):
    """Half-width of the window holding `fraction` of |residual| entries.

    Port of getIntervalContainingFractionOfEntries from the reference
    resolution code: read the quantile of the |residual| distribution.

    Returns None when the window can't be contained — i.e. more than
    (1 - fraction) of the entries fall into the overflow bin (outside the
    booked residual range). The quantile is undeterminable there, so the
    caller drops the point rather than inventing a value."""
    # `total` is the weighted integral == the true number of entries. Don't use
    # GetEntries(): _abs_residual_hist fills this folded hist once per non-empty
    # source bin (Fill bumps the entry counter per call), so GetEntries() counts
    # populated bins, not tracks — a dense-but-narrow projection would then be
    # wrongly rejected as "too few entries".
    total = abs_hist.Integral(0, abs_hist.GetNbinsX() + 1)

    # Guard: if the window would extend into the overflow bin the quantile is
    # undeterminable within the booked range. Signal that with None.
    max_allowed_overflow = total * (1.0 - fraction)
    n_overflow = abs_hist.GetBinContent(abs_hist.GetNbinsX() + 1)
    if n_overflow > max_allowed_overflow:
        return None

    interval = array("d", [0.0])
    quantile = array("d", [fraction])
    if total >= min_entries:
        abs_hist.GetQuantiles(1, interval, quantile)
    else:
        print(f"WARNING: histo {abs_hist.GetName()} empty or with too few "
              f"entries, so can't calc quantiles.")
        interval[0] = 0.0
    return interval[0]


def proj_2dhist_interval(h2, r, x, name_tag, res_dir, proj_dir, label, uniq=""):
    """Project the 2d hist onto the Y-axis, then add the interval of the resolution
       histogram."""

    hres = ROOT.TH1F(f"res_{name_tag}", f";{x.xlabel};{r.ylabel}",
                     x.nbins, x.lo, x.hi)

    ncols = math.ceil(math.sqrt(x.nbins))
    nrows = math.ceil(x.nbins / ncols)
    canvas = ROOT.TCanvas(f"proj_{clean_label(label)}_{name_tag}{uniq}",
                          f"projections {name_tag}",
                          300 * ncols, 250 * nrows)
    canvas.Divide(ncols, nrows)
    xax = h2.GetXaxis()
    projs = []    # keep projections alive until canvas.Write()
    markers = []  # keep window lines alive until canvas.Write()

    for ib in range(1, x.nbins + 1):
        canvas.cd(ib)
        proj = h2.ProjectionY(f"px_{name_tag}{uniq}_bin{ib}", ib, ib)
        proj.SetDirectory(0)
        lo_edge = xax.GetBinLowEdge(ib)
        hi_edge = xax.GetBinUpEdge(ib)
        proj.SetTitle(
            f"{x.xlabel} #in [{lo_edge:.3g}, {hi_edge:.3g}];"
            f"{r.key} residual;Entries"
        )
        proj.SetFillColor(ROOT.kAzure + 1)
        proj.SetLineColor(ROOT.kAzure + 1)
        proj.SetFillStyle(1001) # solid fill

        new_lines = 0
        if proj.GetEntries() < 1:
            hres.SetBinContent(ib, 0.0)
            hres.SetBinError(ib, 0.0)
        else:
            habs = abs_residual_hist(proj)
            half = interval_for_fraction(habs, ONE_SIGMA_FRACTION)
            habs.Delete()

            drew_window = half is not None and half > 0.0
            # The plotted value is the interval half-width; it has no
            # per-point error, so pin the error to zero. When the window
            # can't be contained (half is None) the value is undeterminable, so
            # store NaN: ROOT skips NaN bins when drawing (leaving a gap) and
            # GetMaximum/GetMinimum ignore them, so the y-range stays intact.
            if half is None:
                hres.SetBinContent(ib, float("nan"))
            else:
                hres.SetBinContent(ib, half if drew_window else 0.0)
            hres.SetBinError(ib, 0.0)

            # Draw the window edges so the excluded tails are visible.
            if drew_window:
                ymax = proj.GetMaximum() * 1.05
                for xline in (-half, half):
                    ln = ROOT.TLine(xline, 0.0, xline, ymax)
                    ln.SetLineColor(ROOT.kRed + 1)
                    ln.SetLineStyle(2)
                    markers.append(ln)
                new_lines = 2
            else:
                new_lines = 0

        proj.Draw("HIST")
        for ln in markers[len(markers) - new_lines:] if new_lines else ():
            ln.Draw("SAME")
        projs.append(proj)

    if proj_dir:
        proj_dir.cd()
        canvas.Write()
    canvas.Close()   # drop from gROOT canvas list to free it

    res_dir.cd()
    hres.Write()
    hres.SetDirectory(0)  # detach so f.Write() won't re-write a 2nd cycle

def proj_2dhist_rms(h2, r, x, name_tag, res_dir, proj_dir, label, uniq=""):
    """Project the 2d hist onto the Y-axis, then add the Rms +- Rmse
       to the resolution histogram."""

    # Project onto x axis and take the rms +- rmse per x-bin.
    hres = ROOT.TH1F(f"res_{name_tag}", f";{x.xlabel};{r.ylabel}",
                     x.nbins, x.lo, x.hi)

    ncols = math.ceil(math.sqrt(x.nbins))
    nrows = math.ceil(x.nbins / ncols)
    canvas = ROOT.TCanvas(f"proj_{clean_label(label)}_{name_tag}{uniq}",
                          f"projections {name_tag}",
                          300 * ncols, 250 * nrows)
    canvas.Divide(ncols, nrows)
    xax = h2.GetXaxis()
    projs = []  # keep alive until canvas.Write()

    for ib in range(1, x.nbins + 1):
        canvas.cd(ib)
        proj = h2.ProjectionY(f"px_{name_tag}{uniq}_bin{ib}", ib, ib)
        proj.SetDirectory(0)
        lo_edge = xax.GetBinLowEdge(ib)
        hi_edge = xax.GetBinUpEdge(ib)
        proj.SetTitle(
            f"{x.xlabel} #in [{lo_edge:.3g}, {hi_edge:.3g}];"
            f"{r.ylabel};Entries"
        )
        proj.SetFillColor(ROOT.kAzure + 1)
        proj.SetLineColor(ROOT.kAzure + 1)
        proj.SetFillStyle(1001) # solid fill

        # write chi2 in stats box
        proj.Draw("HIST")
        projs.append(proj)

        if proj.GetEntries() < 1:
            hres.SetBinContent(ib, 0.0)
            hres.SetBinError(ib, 0.0)
        else:
            hres.SetBinContent(ib, proj.GetRMS())
            hres.SetBinError(ib, proj.GetRMSError())

    if proj_dir:
        proj_dir.cd()
        canvas.Write()
    canvas.Close()   # drop from gROOT canvas list to free it

    res_dir.cd()
    hres.Write()
    hres.SetDirectory(0)  # detach so f.Write() won't re-write a 2nd cycle


def plot_res_set(rdf, cfg, other_cuts, dir, label, save_proj_bool, tag=""):
    """Make 25 res plots (5x5 parameters) with optional extra cuts.
       Other_cuts is only ONE group of cuts from the config. Make sure all
       labels are unique as to not have overlapping names."""
    baseCuts = base_cuts(rdf, cfg.cuts)
    otherCuts = " && ".join(c for c in other_cuts if c)
    # `tag` distinguishes this call's RDF columns / transient objects from
    # other plot_res_set calls on the SAME rdf (e.g. the nstub bands). It is
    # NOT part of the stored histogram name — the enclosing TDirectory already
    # makes those unique, and load() looks them up by the plain name_tag.
    # RDF column names must be valid C++ identifiers, so keep only [A-Za-z0-9_].
    safe_tag = "".join(ch if ch.isalnum() else "_" for ch in tag)
    suffix = ("_" + safe_tag) if safe_tag else ""

    if save_proj_bool:
        proj_dir = dir.mkdir("Bin_Projections")
    else:
        proj_dir = ""

    res_2d_hists = []
    for r in cfg.resolution.residuals:
        cut_terms = [baseCuts]
        if r.extra_cut:
            cut_terms.append(r.extra_cut)
        if otherCuts:
            cut_terms.append(otherCuts)
        # extra cut?
        cut_mask = " && ".join(f"({t})" for t in cut_terms)

        # create an elementwise mask and find residuals
        rf_r = rdf.Define(f"sel_{r.key}{suffix}", cut_mask) \
                  .Define(f"res_{r.key}{suffix}", r.expr) \
                  .Define(f"res_sel_{r.key}{suffix}",
                          f"res_{r.key}{suffix}[sel_{r.key}{suffix}]")

        for x in cfg.resolution.x_axes:
            name_tag = f"{r.key}_vs_{x.key}"   # stored hist name (no suffix)
            col = f"{name_tag}{suffix}"        # unique RDF column / object tag
            rf2 = rf_r.Define(f"xax_{x.key}{suffix}", x.expr) \
                      .Define(f"xax_sel_{col}",
                              f"xax_{x.key}{suffix}[sel_{r.key}{suffix}]")

            model = ROOT.RDF.TH2DModel(
                f"h2_{col}", "",
                x.nbins, x.lo, x.hi,
                r.nbins, r.lo, r.hi,
            )
            h2_ptr = rf2.Histo2D(model, f"xax_sel_{col}",
                                 f"res_sel_{r.key}{suffix}")
            # store 2d hists
            res_2d_hists.append((r, x, name_tag, h2_ptr))

    for r, x, name_tag, h2_ptr in res_2d_hists:
        h2 = h2_ptr.GetValue()
        if cfg.resolution.method == "interval":
            proj_2dhist_interval(h2, r, x, name_tag, dir, proj_dir, label, uniq=suffix)
        elif cfg.resolution.method == "rms":
            proj_2dhist_rms(h2, r, x, name_tag, dir, proj_dir, label, uniq=suffix)
        h2.Delete()




def fill(cfg: Config, rdfs, out_dir) -> None:
    """Stage 1. Fill per-x-bin interval TH1s for each RESIDUAL * XAXIS * band * input.

    Parameters
    ----------
    cfg     : config.Config
    rdfs    : list[tuple[ROOT.RDataFrame, str]]
    out_dir : ROOT.TDirectory  (e.g. f.mkdir("res") from main.py)
    """
        
    for rdf, label in rdfs:
        print(f"[fill] Making resolution plots for {label}")
        # directory for each input file
        sub_dir = out_dir.mkdir(clean_label(label))
        plot_res_set(rdf, cfg, [], sub_dir, label, True)

        # extra-cut blocks: one sub-dir per block, one per group inside it
        for block in cfg.resolution.other_cuts:
            block_dir = sub_dir.mkdir(clean_label(block.key))
            for g in block.groups:
                g_dir = block_dir.mkdir(clean_label(g.key))
                plot_res_set(rdf, cfg, list(g.cuts), g_dir, label, True,
                             tag=f"{clean_label(block.key)}_{clean_label(g.key)}")









    


def load(cfg: Config, in_dir, labels: list[str]) -> dict[str, list[Curve]]:
    """Stage 2. Read filled TH1s, style them, package as Curves.

    Plot keys (become output filename stems, '/' -> sub-directories):
        res_<tag>                          standard, one curve per input
        <block>/res_<tag>                  block, overlay=true  (file x group)
        <block>/<label>/res_<tag>          block, overlay=false (groups only)
    """
    result: dict[str, list[Curve]] = {}
    res = cfg.resolution

    label_dirs = {lbl: in_dir.GetDirectory(clean_label(lbl)) for lbl in labels}

    for r in res.residuals:
        for x in res.x_axes:
            name_tag = f"{r.key}_vs_{x.key}"

            # --- standard: one curve per input file ---
            curves = []
            for i, label in enumerate(labels):
                h = _read_res(label_dirs[label], name_tag)
                if not h:
                    print(f"[load] missing res_{name_tag} for {label!r}")
                    continue
                style.style_hist(h, i, x.xlabel, r.ylabel, r.title)
                curves.append(Curve(label=label, hist=h))
            if curves:
                result[f"res_{name_tag}"] = curves

            # --- extra-cut blocks ---
            for block in res.other_cuts:
                if block.overlay:
                    # one plot: every (file, group) combo overlaid
                    curves = []
                    ci = 0
                    for label in labels:
                        bdir = label_dirs[label]
                        bdir = bdir.GetDirectory(clean_label(block.key)) if bdir else None
                        for g in block.groups:
                            gdir = bdir.GetDirectory(clean_label(g.key)) if bdir else None
                            h = _read_res(gdir, name_tag)
                            if not h:
                                continue
                            style.style_hist(h, ci, x.xlabel, r.ylabel, r.title)
                            curves.append(Curve(label=f"{label}  {g.key}", hist=h))
                            ci += 1
                    if curves:
                        result[f"{clean_label(block.key)}/res_{name_tag}"] = curves
                else:
                    # one plot per input file: the groups overlaid
                    for label in labels:
                        bdir = label_dirs[label]
                        bdir = bdir.GetDirectory(clean_label(block.key)) if bdir else None
                        curves = []
                        for gi, g in enumerate(block.groups):
                            gdir = bdir.GetDirectory(clean_label(g.key)) if bdir else None
                            h = _read_res(gdir, name_tag)
                            if not h:
                                continue
                            style.style_hist(h, gi, x.xlabel, r.ylabel, r.title)
                            curves.append(Curve(label=g.key, hist=h))
                        if curves:
                            # The drawn pad title is the first curve's title;
                            # tag it with the input label so per-file plots are
                            # distinguishable.
                            curves[0].hist.SetTitle(f"{r.title}  ({label})")
                            key = f"{clean_label(block.key)}/{clean_label(label)}/res_{name_tag}"
                            result[key] = curves

    return result


def _read_res(directory, name_tag):
    """Get res_<name_tag> from a TDirectory, detached, or None."""
    if not directory:
        return None
    h = directory.Get(f"res_{name_tag}")
    if not h:
        return None
    h.SetDirectory(0)
    return h



