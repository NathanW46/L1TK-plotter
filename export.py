"""Mirror the plotter's ROOT file into the output directory.

Stage 3 of the pipeline. Everything the run put into `output.hist_file` —
overlay canvases, per-input histograms, bin-projection canvases, the pie-chart
snapshots, the effective config, and the end-of-run summaries — is walked
recursively and written out as files, so the output directory has exactly the
same shape as the ROOT file:

    plots/
      config.yaml                         <- TObjString, the effective config
      summary/
        NEWKF_Kill.txt                    <- terminal summary, one per input
      overlays/
        eff/eff_eta.pdf                   <- cross-input overlays
        res/res_pt_vs_eta.pdf
        nstub_pies.png
      eff/NEWKF_Kill/eff_eta.pdf          <- per-input source hists
      res/NEWKF_Kill/res_pt_vs_eta.pdf
      res/NEWKF_Kill/Bin_Projections/...
      nstub/NEWKF_Kill/nstub_pie.png

Object -> file mapping:
    TDirectory  -> a sub-directory, recursed into
    TObjString  -> .yaml for the config, .txt otherwise
    TCanvas     -> output.format (pdf/png), redrawn as stored
    TImage      -> .png (TASImage only writes raster formats)
    TH1/TH2/TGraph/TEfficiency -> drawn on a scratch canvas, output.format
"""

from __future__ import annotations

import os

import ROOT


# TASImage (used for the pie snapshots) can only write raster formats, so those
# always land as PNG regardless of the configured output format.
_IMAGE_EXT = "png"

# ROOT key name -> file extension for the text objects we store.
_TEXT_EXT = {"config": "yaml"}


def _safe(name: str) -> str:
    """Make a ROOT key name safe to use as a path component."""
    return "".join(ch if (ch.isalnum() or ch in "_-.+=") else "_" for ch in name)


def _key_names(directory) -> list[str]:
    """Key names in `directory`, de-duplicated across write cycles.

    A TFile opened in UPDATE mode accumulates cycles (`name;1`, `name;2`) for
    objects that were rewritten. `TDirectory.Get(name)` always resolves to the
    highest cycle, so collect each name once and read it back by name.
    """
    names: list[str] = []
    seen: set[str] = set()
    for key in directory.GetListOfKeys():
        n = key.GetName()
        if n and n not in seen:
            seen.add(n)
            names.append(n)
    return names


def _draw_option(obj) -> str:
    """Sensible default draw option for a plain (non-canvas) plot object."""
    if isinstance(obj, ROOT.TH2):
        return "COLZ"
    if isinstance(obj, ROOT.TH1):
        return "HIST"
    return "AP"  # TGraph / TEfficiency / TMultiGraph


def _write_object(obj, name: str, path: str, fmt: str, tag: str,
                  scratch) -> str | None:
    """Write one ROOT object into `path`. Returns the file written, or None.

    `tag` is appended to the file stem (not to directory names), so runs with
    different output.tag values can share an output directory the same way
    they always have.
    """
    stem = os.path.join(path, _safe(name) + tag)

    if isinstance(obj, ROOT.TObjString):
        out = f"{stem}.{_TEXT_EXT.get(name, 'txt')}"
        text = str(obj.GetString())
        with open(out, "w") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")
        return out

    if isinstance(obj, ROOT.TCanvas):
        out = f"{stem}.{fmt}"
        # A canvas read back from a file needs a Draw() to realise its pads
        # before it can be painted into a file in batch mode.
        obj.Draw()
        obj.SaveAs(out)
        return out

    if isinstance(obj, ROOT.TImage):
        out = f"{stem}.{_IMAGE_EXT}"
        obj.WriteImage(out)
        return out

    if isinstance(obj, (ROOT.TH1, ROOT.TGraph, ROOT.TMultiGraph, ROOT.TEfficiency)):
        out = f"{stem}.{fmt}"
        scratch.Clear()
        scratch.cd()
        obj.Draw(_draw_option(obj))
        scratch.Update()
        scratch.SaveAs(out)
        return out

    return None


def _dump_dir(directory, path: str, fmt: str, tag: str, scratch,
              skipped: list[str]) -> int:
    """Recursively write everything under `directory` into `path`."""
    os.makedirs(path, exist_ok=True)
    n = 0
    for name in _key_names(directory):
        obj = directory.Get(name)
        if not obj:
            continue
        if isinstance(obj, ROOT.TDirectory):
            n += _dump_dir(obj, os.path.join(path, _safe(name)), fmt, tag,
                           scratch, skipped)
            continue
        if _write_object(obj, name, path, fmt, tag, scratch) is None:
            skipped.append(f"{directory.GetPath()}/{name} "
                           f"({obj.ClassName()})")
        else:
            n += 1
    return n


def dump_tree(hist_file: str, outdir: str, fmt: str = "pdf",
              tag: str = "") -> int:
    """Mirror `hist_file` into `outdir`. Returns the number of files written.

    Safe to call after either stage: whatever is in the file gets exported, so
    a fill-only run dumps the source hists and a full run dumps the overlays
    alongside them. `tag` (output.tag) is suffixed onto every file stem.
    """
    suffix = f"_{tag}" if tag else ""
    f = ROOT.TFile.Open(hist_file, "READ")
    if not f or f.IsZombie():
        raise RuntimeError(f"could not open {hist_file!r} for export")

    # One scratch canvas for every plain hist/graph, so ROOT doesn't warn
    # about replacing a same-named canvas on each object.
    scratch = ROOT.TCanvas("c_export", "export", 800, 600)
    scratch.SetGrid()
    scratch.SetLeftMargin(0.15)
    skipped: list[str] = []
    try:
        n = _dump_dir(f, outdir, fmt, suffix, scratch, skipped)
    finally:
        scratch.Close()
        f.Close()

    print(f"[export] mirrored {hist_file} -> {outdir}/  ({n} files)")
    if skipped:
        print(f"[export] skipped {len(skipped)} object(s) with no renderer: "
              f"{', '.join(skipped[:5])}"
              f"{' ...' if len(skipped) > 5 else ''}")
    return n
