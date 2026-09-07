"""YAML loader for the L1Track plotter.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, NamedTuple

import yaml


# ---------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class CutParams:
    minPt:       float = 2.0
    maxEta:      float = 2.4
    minNstub:    int   = 4
    maxD0:       float = 1.0
    maxLxy:      float = 1.0
    maxLz:       float = 30.0
    primaryOnly: bool  = False
    maxChi2:     float = 99999;
    maxChi2dof:  float = 99999.;


@dataclass(frozen=True)
class InputSpec:
    file: str
    label: str


@dataclass(frozen=True)
class OutputSpec:
    hist_file: str = "output_plots.root"
    outdir:    str = "plots"
    tag:       str = ""
    format:    str = "pdf"      # 'pdf' | 'png'


# Positional blocks from the YAML. NamedTuple lets plot modules either
# unpack positionally or use attribute access: `v.branch`, `r.expr`, etc.

class EffVariable(NamedTuple):
    branch: str
    nbins:  int
    lo:    float
    hi:    float
    xlabel: str
    key:   str


class ResResidual(NamedTuple):
    key:       str
    expr:      str
    extra_cut: str
    nbins:     int
    lo:        float
    hi:        float
    ylabel:    str
    title:     str


class ResXAxis(NamedTuple):
    key:    str
    expr:   str
    nbins:  int
    lo:     float
    hi:     float
    xlabel: str

# Extra-cut blocks. Each block makes its own output directory; the cut
# groups inside it are overlaid together. `overlay` says whether to also
# overlay across the input ROOT files (True) or keep one plot per file
# (False). A CutGroup is one legend line: its `cuts` are ANDed onto the
# standard selection.

class CutGroup(NamedTuple):
    key:  str                 # legend label for this line
    cuts: tuple[str, ...]     # extra cut expressions, ANDed in


class ExtraCutBlock(NamedTuple):
    key:     str              # output sub-directory name
    overlay: bool             # overlay across input files too?
    groups:  tuple[CutGroup, ...]


@dataclass(frozen=True)
class EfficiencySpec:
    variables: tuple[EffVariable, ...]


@dataclass(frozen=True)
class ResolutionSpec:
    residuals:  tuple[ResResidual, ...]
    x_axes:     tuple[ResXAxis, ...]
    other_cuts: tuple[ExtraCutBlock, ...] = ()
    # How the per-x-bin resolution is defined:
    #   'interval' — half-width of the window holding a central fraction of
    #                entries. It has no per-bin error, so the overlays are
    #                drawn as connected-line histograms with no error bars.
    #   'rms'      — RMS of the residual projection, drawn with markers and
    #                RMS-error bars.
    method:     str = "interval"


@dataclass(frozen=True)
class Config:
    cuts:       CutParams
    ptSplit:    str             # 'none' | 'low' | 'high' | 'both'
    inputs:     tuple[InputSpec, ...]
    output:     OutputSpec
    efficiency: EfficiencySpec
    resolution: ResolutionSpec


# ---------------------------------------------------------------------
# Loader by Claude
# ---------------------------------------------------------------------

# _VALID_PT_SPLIT = {"none", "low", "high", "both"}
_VALID_FORMAT   = {"pdf", "png"}
_VALID_RES_METHOD = {"interval", "rms"}


class ConfigError(ValueError):
    pass

def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigError(msg)

def _filter_fields(cls, d: dict[str, Any]) -> dict[str, Any]:
    """Drop unknown keys from a dict before passing to a dataclass ctor,
    so a typo'd YAML key is reported by validation rather than swallowed."""
    known = {f.name for f in fields(cls)}
    unknown = set(d) - known
    _require(not unknown, f"unknown key(s) in {cls.__name__}: {sorted(unknown)}")
    return {k: d[k] for k in d if k in known}


def _parse_blocks(blocks, nt_cls, section_name: str):
    """Turn a list of positional YAML lists into a tuple of NamedTuple."""
    out = []
    n_expected = len(nt_cls._fields)
    for i, block in enumerate(blocks or []):
        _require(
            isinstance(block, (list, tuple)) and len(block) == n_expected,
            f"{section_name}[{i}] must be a list of {n_expected} items "
            f"({list(nt_cls._fields)}); got {block!r}",
        )
        out.append(nt_cls(*block))
    return tuple(out)


def _parse_other_cuts(blocks, section_name: str):
    """Parse resolution.other_cuts into a tuple of ExtraCutBlock.

    Each block is  [key, overlay_bool, [[group_key, cut, cut, ...], ...]].
    """
    out = []
    for i, block in enumerate(blocks or []):
        _require(
            isinstance(block, (list, tuple)) and len(block) == 3,
            f"{section_name}[{i}] must be [key, overlay_bool, groups]; got {block!r}",
        )
        key, overlay, groups_raw = block
        _require(isinstance(key, str), f"{section_name}[{i}] key must be a string")
        _require(isinstance(overlay, bool),
                 f"{section_name}[{i}] overlay flag must be true/false")
        _require(isinstance(groups_raw, (list, tuple)) and len(groups_raw) > 0,
                 f"{section_name}[{i}] groups must be a non-empty list")

        groups = []
        for j, g in enumerate(groups_raw):
            _require(
                isinstance(g, (list, tuple)) and len(g) >= 1
                and all(isinstance(s, str) for s in g),
                f"{section_name}[{i}].groups[{j}] must be "
                f"[group_key, cut, ...] of strings; got {g!r}",
            )
            groups.append(CutGroup(key=g[0], cuts=tuple(g[1:])))
        out.append(ExtraCutBlock(key=key, overlay=overlay, groups=tuple(groups)))
    return tuple(out)


def load_config(path: str) -> Config:
    """Load and validate a plotter YAML config."""
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    _require(isinstance(raw, dict), "config root must be a mapping")

    cuts = CutParams(**_filter_fields(CutParams, raw.get("cuts") or {}))

    # ptSplit: NOT IMPLEMENTED yet — read but unvalidated for now.
    ptSplit = raw.get("ptSplit", "none")

    # `inputs` may be either:
    #   - a plain list of input entries (legacy), or
    #   - a mapping {base_path: <str>, files: [<entry>, ...]} where the optional
    #     `base_path` is prepended to every entry's `file`.
    raw_inputs = raw.get("inputs") or []
    if isinstance(raw_inputs, dict):
        unknown = set(raw_inputs) - {"base_path", "files"}
        _require(not unknown, f"unknown key(s) in inputs: {sorted(unknown)}")
        base_path = raw_inputs.get("base_path", "")
        input_entries = raw_inputs.get("files") or []
    else:
        base_path = ""
        input_entries = raw_inputs
    _require(isinstance(base_path, str),
             f"inputs.base_path must be a string, got {base_path!r}")

    _require(len(input_entries) > 0, "config needs a non-empty 'inputs' list")
    inputs = []
    for inp in input_entries:
        file = os.path.join(base_path, inp["file"]) if base_path else inp["file"]
        inputs.append(InputSpec(file=file, label=inp["label"]))
    inputs = tuple(inputs)

    output = OutputSpec(**_filter_fields(OutputSpec, raw.get("output") or {}))
    _require(output.format in _VALID_FORMAT,
             f"output.format must be one of {_VALID_FORMAT}, got '{output.format}'")

    eff_raw = raw.get("efficiency") or {}
    efficiency = EfficiencySpec(
        variables=_parse_blocks(eff_raw.get("variables"), EffVariable,
                                "efficiency.variables"),
    )

    res_raw = raw.get("resolution") or {}
    res_method = res_raw.get("method", "interval")
    _require(res_method in _VALID_RES_METHOD,
             f"resolution.method must be one of {_VALID_RES_METHOD}, "
             f"got '{res_method}'")
    resolution = ResolutionSpec(
        residuals=_parse_blocks(res_raw.get("residuals"), ResResidual,
                                "resolution.residuals"),
        x_axes=_parse_blocks(res_raw.get("x_axes"), ResXAxis,
                             "resolution.x_axes"),
        other_cuts=_parse_other_cuts(res_raw.get("other_cuts"),
                                     "resolution.other_cuts"),
        method=res_method,
    )

    return Config(
        cuts=cuts,
        ptSplit=ptSplit,
        inputs=inputs,
        output=output,
        efficiency=efficiency,
        resolution=resolution,
    )


# ---------------------------------------------------------------------
# Serialization (for recording the effective config into the output file)
# ---------------------------------------------------------------------

def _to_plain(obj: Any):
    """Recursively convert a Config (dataclasses + NamedTuples) into plain
    dict/list/scalars that yaml.safe_dump can handle.

    dataclasses.asdict() can't be used here: it calls type(obj)(gen) on nested
    NamedTuples (EffVariable, ResResidual, ...), which raises because a
    NamedTuple can't be built from a single generator. NamedTuples are emitted
    as *named* mappings (via ._asdict()) so each positional block shows its
    field names (branch/nbins/lo/... ) instead of a bare list of values."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_plain(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, tuple) and hasattr(obj, "_fields"):  # NamedTuple
        return {k: _to_plain(v) for k, v in obj._asdict().items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    return obj


def to_yaml(cfg: Config) -> str:
    """Serialize the effective Config to YAML text (post CLI overrides).

    Intended for stashing the run's setup parameters into the output ROOT
    file so a plot can be traced back to the config that produced it.

    default_flow_style=None keeps the outer structure in block style but
    collapses each leaf block (a single variable/residual/x-axis) onto one
    compact `{branch: tp_eta, nbins: 50, ...}` line, so the blocks read
    clearly and stay grouped one-per-line."""
    return yaml.safe_dump(_to_plain(cfg), sort_keys=False,
                          default_flow_style=None, width=1000)
