"""Stub-count pie charts for the L1Track plotter.

Implements the two-function plotter contract used by the rest of the package:
  * fill(cfg, rdfs, out_dir)  — tally matchtrk_nstub and store a TPie per input.
  * load(cfg, in_dir, labels, write_to=) — save one image per input, and tile
    all the pies onto a single combined canvas written into `write_to`.

`matchtrk_nstub` is a per-tracking-particle array filled with a sentinel (< 0)
when the TP has no matched track; the baseline selection (which requires
tp_nmatch >= 1) drops those before tallying, so each remaining entry is the stub
count of a matched track.

Unlike the efficiency/resolution modules, a pie chart can't be overlaid across
inputs, so instead of one-curve-per-input overlays the pies are tiled (one pad
each) onto a combined canvas. `load` saves the images and writes that canvas
itself, returning an empty dict — there is nothing for overlay.draw_overlay to
handle.
"""

from __future__ import annotations

import math
import os

import ROOT

from config import Config
from overlay import Curve
from array import array
import style


# matchtrk_nstub is a small non-negative integer. Book one bin per integer in
# [0, MAX_NSTUB] so bin centres land exactly on the stub counts.
MAX_NSTUB = 20

# Slice colours, cycled across stub-count entries (blue / orange / green / ...).
_PALETTE = [
    ROOT.kAzure + 1, ROOT.kOrange + 1, ROOT.kGreen + 2, ROOT.kRed + 1,
    ROOT.kMagenta + 1, ROOT.kCyan + 1, ROOT.kYellow + 2, ROOT.kGray + 1,
]


def clean_label(label):
    """Sanitize a label into a safe ROOT directory / object name (matches the
    other plotter modules: spaces -> '_', '.' -> 'p')."""
    return label.replace(" ", "_").replace(".", "p")


def base_cuts(rdf, p):
    """Elementwise baseline selection of matched tracks. Mirrors the cuts in
    plotters/resolution.py so the pie tally uses the same population as the
    resolution/efficiency plots. tp_lxy and tp_lz are skipped if absent."""
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

    # matched-tracks (tp_nmatch >= 1 drops the unmatched-track sentinel)
    cuts += [
        "tp_nmatch >= 1",
        f"matchtrk_nstub >= {p.minNstub}",
        f"matchtrk_chi2 <= {p.maxChi2}",
        f"matchtrk_chi2_dof <= {p.maxChi2dof}",
    ]

    return " && ".join(cuts)


def fill(cfg: Config, rdfs, out_dir) -> None:
    """Stage 1. Tally matchtrk_nstub over selected matched tracks per input.

    Parameters
    ----------
    cfg     : config.Config
    rdfs    : list[tuple[ROOT.RDataFrame, str]]
    out_dir : ROOT.TDirectory  (e.g. f.mkdir("nstub") from main.py)

    Writes, for each input label, out_dir/<clean_label(label)>/nstub_pie — a
    TCanvas holding a TPie of the stub-count breakdown.
    """
    p = cfg.cuts
    for rdf, label in rdfs:
        print(f"[fill] Making nstub pie for {label}")
        rf = (rdf.Define("nstub_sel_mask", base_cuts(rdf, p))
                 .Define("nstub_sel", "matchtrk_nstub[nstub_sel_mask]"))

        # Tally into a transient histogram just to get per-integer counts; it is
        # detached (SetDirectory(0)) so only the pie gets persisted, not a hist.
        model = ROOT.RDF.TH1DModel(
            "_nstub_tally", "", MAX_NSTUB + 1, -0.5, MAX_NSTUB + 0.5)
        h = rf.Histo1D(model, "nstub_sel").GetValue()
        h.SetDirectory(0)
        counts = _counts_from_hist(h)

        sub = out_dir.mkdir(clean_label(label))
        sub.cd()
        if not counts:
            print(f"[fill] no matched tracks for {label!r}, skipping pie")
            continue
        canvas = _build_pie_canvas(counts, label)
        canvas.Write("nstub_pie")
        canvas.Close()



def _counts_from_hist(h) -> list:
    """Map stub count -> number of matched tracks, dropping empty bins."""
    counts = []
    for ib in range(1, h.GetNbinsX() + 1):
        c = h.GetBinContent(ib)
        if c > 0:
            counts.append([int(round(h.GetBinCenter(ib))), c])
    return counts


def _build_pie_canvas(counts: list, label: str) -> "ROOT.TCanvas":
    """Build a TCanvas holding a TPie of the stub-count breakdown."""
    nstubs = [x[0] for x in counts]
    nstub_vals = array("d", [x[1] for x in counts])
    total = sum(nstub_vals)

    # Square canvas + fixed 1:1 aspect ratio: TPie draws its circle in pad NDC,
    # so it only stays circular while the pad is square. SetFixedAspectRatio
    # keeps it square when the stored canvas is later viewed/resized (e.g. in a
    # TBrowser), otherwise the live pad stretches the circle into an ellipse.
    canvas = ROOT.TCanvas(f"nstub_pie_{clean_label(label)}",
                          f"nstub pie {label}", 800, 800)
    canvas.SetFixedAspectRatio(True)
    title = (f"Number of stubs on matched tracks - {label} "
             f"({int(total)} matched tracks)")

    # A single 100% slice has identical start/end angles, which TPie renders as
    # a degenerate line. Draw a plain filled circle for the one-category case.
    if len(counts) == 1:
        n, val = counts[0]
        canvas.cd()
        canvas.Range(0, 0, 1, 1)  # so the TEllipse user coords match NDC
        circ = ROOT.TEllipse(0.5, 0.47, 0.32, 0.32)
        circ.SetFillColor(_PALETTE[0])
        circ.SetLineColor(_PALETTE[0])
        circ.Draw()
        lbl = ROOT.TLatex(0.5, 0.47,
                          f"#splitline{{{n} stubs ({int(val)})}}{{100.0 %}}")
        lbl.SetTextAlign(22)
        lbl.SetTextSize(0.035)
        lbl.Draw()
        ttl = ROOT.TLatex(0.5, 0.92, title)
        ttl.SetTextAlign(23)
        ttl.SetTextSize(0.03)
        ttl.Draw()
        canvas._keep = [circ, lbl, ttl]  # keep drawn objects alive
        return canvas

    # Values are set via the constructor; labels/colours/format must still be
    # set per-entry afterwards or the pie shows default "Slice0" grey wedges.
    pie = ROOT.TPie(f"pie_{clean_label(label)}", title,
                    len(nstubs), nstub_vals)
    for i, (n, val) in enumerate(counts):
        # Counts are integers; bake them into the label with int() rather than
        # relying on TPie's %val format (which can render "1560.00").
        pie.SetEntryLabel(i, f"{n} stubs ({int(val)})")
        pie.SetEntryFillColor(i, _PALETTE[i % len(_PALETTE)])

    pie.SetLabelFormat("#splitline{%txt}{%perc}")
    pie.SetPercentFormat("%.1f")
    pie.SetLabelsOffset(0.02)
    pie.SetRadius(0.32)
    pie.SetTextSize(0.03)
    pie.SetCircle(0.5, 0.47, 0.32)

    canvas.cd()
    pie.Draw("nol")
    canvas._pie = pie  # keep the drawn TPie alive past this function
    return canvas


def _store_snapshot(pad, directory, name):
    """Replace `directory/name` with a fixed TImage bitmap of `pad`.

    TPie/TEllipse are drawn in pad NDC, so a stored TCanvas re-renders to fill
    whatever window shape the viewer uses and the circle stretches into an
    ellipse (ROOT marks the fixed-aspect-ratio flag transient, so it isn't
    saved). A TImage is a fixed bitmap and always displays circular."""
    img = ROOT.TImage.Create()
    img.FromPad(pad)
    directory.cd()
    directory.Delete(f"{name};*")  # drop the distortable TCanvas, if any
    img.Write(name)


def load(cfg: Config, in_dir, labels: list[str], write_to=None
         ) -> dict[str, list[Curve]]:
    """Stage 2. Save one pie image per input, and tile all pies onto a single
    combined canvas written into `write_to` (e.g. the overlays/ directory).

    Vector images (the configured filetype) are written under <outdir>/nstub/.
    In the ROOT file the pies are stored as fixed TImage bitmaps (see
    _store_snapshot) so they render circular regardless of the viewer window.

    A pie chart isn't an overlay, so this saves the images itself and writes the
    combined snapshot directly, returning {} — nothing for draw_overlay to do.
    """
    out = cfg.output
    tag = f"_{out.tag}" if out.tag else ""
    nstub_outdir = os.path.join(out.outdir, "nstub")
    os.makedirs(nstub_outdir, exist_ok=True)

    srcs = []  # (label, sub-dir, stored TCanvas) for the combined canvas
    for label in labels:
        sub = in_dir.GetDirectory(clean_label(label))
        if not sub:
            print(f"[load] missing dir for {label!r} in {in_dir.GetName()}")
            continue
        canvas = sub.Get("nstub_pie")
        if not canvas:
            print(f"[load] missing nstub_pie in {label!r}")
            continue

        out_path = os.path.join(
            nstub_outdir, f"nstub_piechart_{clean_label(label)}{tag}.{out.format}")
        canvas.SaveAs(out_path)  # vector, rendered at the square canvas -> circular
        print(f"[nstub] wrote {out_path}")
        srcs.append((label, sub, canvas))

    # Combined canvas: one pad per input, tiled into a roughly-square grid. Each
    # stored canvas holds either a TPie or (single-category) a TEllipse + labels,
    # so clone whatever primitives it has rather than assuming a TPie.
    if write_to is not None and srcs:
        n = len(srcs)
        ncols = math.ceil(math.sqrt(n))
        nrows = math.ceil(n / ncols)
        combined = ROOT.TCanvas("nstub_pies", "nstub pies",
                                500 * ncols, 500 * nrows)
        combined.Divide(ncols, nrows)
        drawn = []  # keep clones alive until SaveAs
        for i, (label, sub, src) in enumerate(srcs):
            pad = combined.cd(i + 1)
            pad.SetFixedAspectRatio(True)  # keep each pie circular when resized
            pad.Range(0, 0, 1, 1)          # match the TEllipse user coords
            keep = []
            for obj in src.GetListOfPrimitives():
                clone = obj.Clone()
                opt = obj.GetDrawOption()
                if isinstance(obj, ROOT.TPie) and "nol" not in opt.lower():
                    opt = "nol"
                clone.Draw(opt)
                keep.append(clone)
            drawn.append(keep)
        combined._keep = drawn

        combo_path = os.path.join(
            nstub_outdir, f"nstub_piechart_all{tag}.{out.format}")
        combined.SaveAs(combo_path)  # vector combined
        _store_snapshot(combined, write_to, "nstub_pies")  # circular in ROOT file
        print(f"[nstub] wrote {combo_path}  (combined, {n} inputs)")

    # Replace each per-input canvas in the ROOT file with a circular bitmap.
    # Done after the combined build, which needed the canvases' primitives.
    for label, sub, canvas in srcs:
        _store_snapshot(canvas, sub, "nstub_pie")

    return {}
