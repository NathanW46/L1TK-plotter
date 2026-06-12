"""ROOT I/O helpers for the L1Track plotter.

RDataFrame-based: every input file becomes an RDataFrame over
L1TrackNtuple/eventTree. Also provides context managers for opening the
intermediate histograms.root file in write / read mode.

Named `rdfio.py` (not `io.py`) to avoid shadowing Python's stdlib `io`
module — `from io import ...` would otherwise resolve to stdlib first
since it's loaded into sys.modules at interpreter startup.
"""

from __future__ import annotations

from contextlib import contextmanager

import ROOT


TREE_PATH = "L1TrackNtuple/eventTree"


def open_rdf(file_path: str, tree_path: str = TREE_PATH) -> "ROOT.RDataFrame":
    """Return an RDataFrame over `tree_path` inside `file_path`.

    RDataFrame manages its own file handle, so there's no GC quirk to work
    around (unlike the bare TTree case where the TFile needs to stay alive).
    """
    rdf = ROOT.RDataFrame(tree_path, file_path)
    if rdf.Count().GetValue() == 0:
        # Cheap sanity check: missing file / wrong tree path yields 0 rows.
        # GetColumnNames returns an empty vector if the tree didn't open.
        cols = list(rdf.GetColumnNames())
        if not cols:
            raise RuntimeError(
                f"could not open '{tree_path}' in {file_path!r}"
            )
    return rdf


def has_column(rdf: "ROOT.RDataFrame", name: str) -> bool:
    """True if `name` is a column on this RDataFrame."""
    return name in {str(c) for c in rdf.GetColumnNames()}


@contextmanager
def hist_file_writer(path: str):
    """Open `path` in RECREATE mode for writing histograms.

    Caller is expected to `f.cd()` into subdirectories before writing, or
    call `h.Write()` with an explicit name. The file is closed on exit.
    """
    f = ROOT.TFile.Open(path, "RECREATE")
    if not f or f.IsZombie():
        raise RuntimeError(f"could not create {path!r}")
    try:
        yield f
    finally:
        f.Write()
        f.Close()


@contextmanager
def hist_file_reader(path: str):
    """Open `path` in READ mode."""
    f = ROOT.TFile.Open(path, "READ")
    if not f or f.IsZombie():
        raise RuntimeError(f"could not open {path!r} for reading")
    try:
        yield f
    finally:
        f.Close()


@contextmanager
def hist_file_updater(path: str):
    """Open `path` in UPDATE mode (read existing + append new objects).

    Use this when stage 2 wants to both *read* the histograms that stage 1
    wrote AND *write* new things (like overlay TCanvases) into the same
    file.
    """
    f = ROOT.TFile.Open(path, "UPDATE")
    if not f or f.IsZombie():
        raise RuntimeError(f"could not open {path!r} in UPDATE mode")
    try:
        yield f
    finally:
        f.Write()
        f.Close()


def ensure_dir(parent: "ROOT.TDirectory", name: str) -> "ROOT.TDirectory":
    """Get-or-create a subdirectory under `parent`. Safe to call repeatedly."""
    d = parent.GetDirectory(name)
    if not d:
        d = parent.mkdir(name)
    return d
