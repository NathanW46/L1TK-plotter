"""End-of-run summary printout for the L1Track plotter.

Reproduces the console summary that the reference macro L1TrackNtuplePlot.C
prints at the end of its run: per-input efficiencies (by |eta| and pT bin, with
binomial errors), TP and track rates per event, fake/duplicate track rates, and
the z0 resolution sampled at two rapidity points.

The counting selections mirror the reference exactly (track loop, TP loop, and
the efficiency numerator/denominator definitions). Cut values come from
cfg.cuts. The z0-resolution samples are read back from the resolution histogram
res/<label>/res_z0_vs_eta written in stage 1 (interval method, matching the
reference's h2_resVsEta_z0_68).

`build_summaries` returns the text rather than printing it, so main.py can both
echo it to the terminal and stash one TObjString per input in the ROOT file —
which export.py then mirrors to <outdir>/summary/<label>.txt.
"""

from __future__ import annotations

import ROOT

from config import Config


def clean_label(label):
    """Match the directory naming used by the other plotter modules."""
    return label.replace(" ", "_").replace(".", "p")


class _Sums:
    """Books ROOT::VecOps::Sum(mask)-per-event actions on one RDataFrame and
    sums them across events, so a single event loop yields every counter."""

    def __init__(self, rdf):
        self._rdf = rdf
        self._i = 0

    def add(self, expr):
        """Total over all vector elements and all events of `expr` (an
        elementwise RVec mask or integer expression)."""
        col = f"_sum{self._i}"
        self._i += 1
        self._rdf = self._rdf.Define(col, f"ROOT::VecOps::Sum({expr})")
        return self._rdf.Sum(col)


def _eff_line(name, n_match, n_all):
    """'<name> = eff +- err' with a binomial error, or None if n_all == 0."""
    N = float(n_all)
    if abs(N) <= 0:
        return None
    k = float(n_match)
    eff = k / N * 100.0
    err = 1.0 / N * (k * (1.0 - k / N)) ** 0.5 * 100.0
    return f"{name} = {eff:g} +- {err:g}"


def _z0_res_samples(hist_file_path, label):
    """Read (eta1, z0res1, eta2, z0res2) from res/<label>/res_z0_vs_eta, the
    interval-method z0 resolution vs |eta|. Returns None if unavailable."""
    f = ROOT.TFile.Open(hist_file_path, "READ")
    if not f or f.IsZombie():
        return None
    try:
        h = f.Get(f"res/{clean_label(label)}/res_z0_vs_eta")
        if not h:
            return None
        nb = h.GetNbinsX()
        b2 = max(1, int(0.8 * nb))  # reference: GetBinContent(0.8 * nETARANGE)
        return (h.GetXaxis().GetBinCenter(1), h.GetBinContent(1),
                h.GetXaxis().GetBinCenter(b2), h.GetBinContent(b2))
    finally:
        f.Close()


def build_summaries(cfg: Config, rdfs, hist_file_path: str) -> list:
    """Build the reference-style run summary for every input.

    Returns [(label, text), ...] — one block of text per input file.
    """
    p = cfg.cuts
    minpt2 = max(p.minPt, 2.0)     # reference std::max(TP_minPt, 2.0f)
    maxeta25 = min(p.maxEta, 2.5)  # reference std::min(TP_maxEta, 2.5f)
    # The text files are named by label, so record which file each came from.
    file_of = {i.label: i.file for i in cfg.inputs}

    summaries = []
    for rdf, label in rdfs:
        cols = {str(c) for c in rdf.GetColumnNames()}
        has_genuine = "trk_genuine" in cols

        # --- reconstructed-track selection (reference track loop) ---
        trk_base = (f"(trk_chi2 <= {p.maxChi2}) && (trk_chi2_dof <= {p.maxChi2dof})"
                    f" && (trk_nstub >= {p.minNstub})")
        trk_kin = (f"({trk_base}) && (abs(trk_eta) <= {p.maxEta})"
                   f" && (trk_pt >= {p.minPt})")

        # --- tracking-particle kinematic selection (reference TP loop) ---
        tp_terms = []
        if "tp_lxy" in cols:
            tp_terms.append(f"(abs(tp_lxy) <= {p.maxLxy})")
        if "tp_lz" in cols:
            tp_terms.append(f"(abs(tp_lz) <= {p.maxLz})")
        tp_terms += [f"(abs(tp_d0) <= {p.maxD0})", "(tp_pt >= 0.2)",
                     f"(abs(tp_eta) <= {p.maxEta})"]
        tp_kin = " && ".join(tp_terms)

        # eventid cut only when primaryOnly (reference TP_select_eventid == 0)
        eventid = (" && (tp_eventid == 0)"
                   if p.primaryOnly and "tp_eventid" in cols else "")
        tp_eff = f"({tp_kin}) && (tp_pt > {p.minPt}){eventid}"
        tp_match = (f"({tp_eff}) && (tp_nmatch >= 1)"
                    f" && (matchtrk_nstub >= {p.minNstub})"
                    f" && (matchtrk_chi2 <= {p.maxChi2})"
                    f" && (matchtrk_chi2_dof <= {p.maxChi2dof})")

        s = _Sums(rdf)
        nevt = rdf.Count()

        # track counters
        ntrk = s.add(trk_base)
        ntrk_genuine = s.add(f"({trk_base}) && (trk_genuine == 1)") if has_genuine else None
        ntrk_pt2 = s.add(f"({trk_kin}) && (trk_pt > 2.0)")
        ntrk_pt3 = s.add(f"({trk_kin}) && (trk_pt > 3.0)")
        ntrk_pt10 = s.add(f"({trk_kin}) && (trk_pt > 10.0)")

        # TP rates (counted before the eventid cut, like the reference)
        ntp_pt2 = s.add(f"({tp_kin}) && (tp_pt > {p.minPt}) && (tp_pt > 2.0)")
        ntp_pt3 = s.add(f"({tp_kin}) && (tp_pt > {p.minPt}) && (tp_pt > 3.0)")
        ntp_pt10 = s.add(f"({tp_kin}) && (tp_pt > {p.minPt}) && (tp_pt > 10.0)")

        # efficiency denominators / numerators, by |eta| and pT bin
        def eta_pt_counts(sel):
            return {
                "eta1p0": s.add(f"({sel}) && (abs(tp_eta) < 1.0)"),
                "eta1p75": s.add(f"({sel}) && (abs(tp_eta) >= 1.0) && (abs(tp_eta) < 1.75)"),
                "eta2p5": s.add(f"({sel}) && (abs(tp_eta) >= 1.75)"),
                "ptg2": s.add(f"({sel}) && (abs(tp_pt) > 2.0)"),
                "pt2to8": s.add(f"({sel}) && (abs(tp_pt) > 2.0) && (abs(tp_pt) < 8.0)"),
                "ptg8": s.add(f"({sel}) && (abs(tp_pt) > 8.0)"),
                "ptg40": s.add(f"({sel}) && (abs(tp_pt) > 40.0)"),
            }
        n_all = eta_pt_counts(tp_eff)
        n_match = eta_pt_counts(tp_match)

        # duplicate matches: sum (tp_nmatch - 1) over multiply-matched TPs whose
        # matched track passes the chi2/nstub cuts (reference, before kin cuts)
        ntp_ndupmatch = s.add(
            f"((tp_nmatch > 1) && (matchtrk_chi2 <= {p.maxChi2})"
            f" && (matchtrk_chi2_dof <= {p.maxChi2dof})"
            f" && (matchtrk_nstub >= {p.minNstub})) * (tp_nmatch - 1)")

        # --- trigger the single event loop and collect values ---
        nevt = float(nevt.GetValue())

        def V(x):
            return float(x.GetValue()) if x is not None else None

        ntrk_v = V(ntrk)
        ntrk_gen_v = V(ntrk_genuine)
        ntrk_pt2_v, ntrk_pt3_v, ntrk_pt10_v = V(ntrk_pt2), V(ntrk_pt3), V(ntrk_pt10)
        ntp_pt2_v, ntp_pt3_v, ntp_pt10_v = V(ntp_pt2), V(ntp_pt3), V(ntp_pt10)
        na = {k: V(v) for k, v in n_all.items()}
        nm = {k: V(v) for k, v in n_match.items()}
        ndup_v = V(ntp_ndupmatch)

        # ---------------------------------------------------------------
        # assemble the text, mirroring L1TrackNtuplePlot.C
        # ---------------------------------------------------------------
        lines: list[str] = []
        emit = lines.append

        emit(f"===== summary: {label} =====")
        emit(f"input file: {file_of.get(label, '')}")
        emit(f"Number of events = {int(nevt)}")
        emit(f"All performance results include cuts pt > {p.minPt:g} & "
             f"|eta| < {p.maxEta:g} unless 'no pt or eta cuts' stated.")
        emit("Only TP with stubs in at least 4 tracker layers considered")

        emit("")
        for line in (
            _eff_line("efficiency for |eta| < 1.0", nm["eta1p0"], na["eta1p0"]),
            _eff_line("efficiency for 1.0 < |eta| < 1.75", nm["eta1p75"], na["eta1p75"]),
            _eff_line(f"efficiency for 1.75 < |eta| < {maxeta25:g}",
                      nm["eta2p5"], na["eta2p5"]),
        ):
            if line:
                emit(line)
        N_comb = na["eta1p0"] + na["eta1p75"] + na["eta2p5"]
        k_comb = nm["eta1p0"] + nm["eta1p75"] + nm["eta2p5"]
        comb = _eff_line(f"combined efficiency for |eta| < {maxeta25:g}", k_comb, N_comb)
        if comb:
            emit(f"{comb} = {int(k_comb)}/{int(N_comb)}")

        emit("")
        for line in (
            _eff_line(f"efficiency for pt > {minpt2:g}", nm["ptg2"], na["ptg2"]),
            _eff_line(f"efficiency for {minpt2:g} < pt < 8.0", nm["pt2to8"], na["pt2to8"]),
            _eff_line("efficiency for pt > 8.0", nm["ptg8"], na["ptg8"]),
            _eff_line("efficiency for pt > 40.0", nm["ptg40"], na["ptg40"]),
        ):
            if line:
                emit(line)

        emit("")
        if nevt > 0:
            emit(f"# TP/event (pt > {minpt2:g}) = {ntp_pt2_v / nevt:g}")
            emit(f"# TP/event (pt > 3.0) = {ntp_pt3_v / nevt:g}")
            emit(f"# TP/event (pt > 10.0) = {ntp_pt10_v / nevt:g}")
            emit(f"# tracks/event (no pt or eta cuts) = {ntrk_v / nevt:g}")
            emit(f"# tracks/event (pt > {minpt2:g}) = {ntrk_pt2_v / nevt:g}")
            emit(f"# tracks/event (pt > 3.0) = {ntrk_pt3_v / nevt:g}")
            emit(f"# tracks/event (pt > 10.0) = {ntrk_pt10_v / nevt:g}")

        emit("")
        if has_genuine and ntrk_gen_v and ntrk_gen_v > 0:
            fake = 100.0 * (1.0 - ntrk_gen_v / ntrk_v) if ntrk_v > 0 else 0.0
            emit(f"Percentage fake tracks (no pt or eta cuts) = {fake:g}% "
                 f"{int(ntrk_gen_v)} {int(ntrk_v)}")
            dup = 100.0 * ndup_v / ntrk_v if ntrk_v > 0 else 0.0
            emit(f"Percentage duplicate tracks (no pt or eta cuts) = {dup:g}% "
                 f"{int(ndup_v)} {int(ntrk_v)}")

        emit("")
        z0 = _z0_res_samples(hist_file_path, label)
        if z0:
            eta1, res1, eta2, res2 = z0
            emit(f"z0 resolution = {res1:g}cm at |eta| = {eta1:g}")
            emit(f"z0 resolution = {res2:g}cm at |eta| = {eta2:g}")

        summaries.append((label, "\n".join(lines)))

    return summaries


def print_summary(cfg: Config, rdfs, hist_file_path: str) -> list:
    """Build the per-input summaries and echo them to the terminal."""
    summaries = build_summaries(cfg, rdfs, hist_file_path)
    for _, text in summaries:
        print()
        print(text)
    return summaries
