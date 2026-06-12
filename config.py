"""YAML loader for the L1Track plotter.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
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
    outdir:    str = "plots_out"
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

# class Extra_cut(NamedTuple):
#     key:    str
#     cuts:   tuple[tuple[str,...],...]
#

@dataclass(frozen=True)
class EfficiencySpec:
    variables: tuple[EffVariable, ...]


@dataclass(frozen=True)
class ResolutionSpec:
    residuals: tuple[ResResidual, ...]
    x_axes:    tuple[ResXAxis, ...]
    extra_cuts: tuple[str, ...] = ()


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


def load_config(path: str) -> Config:
    """Load and validate a plotter YAML config."""
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    _require(isinstance(raw, dict), "config root must be a mapping")

    cuts = CutParams(**_filter_fields(CutParams, raw.get("cuts") or {}))

    # ptSplit: NOT IMPLEMENTED yet — read but unvalidated for now.
    ptSplit = raw.get("ptSplit", "none")

    raw_inputs = raw.get("inputs") or []
    _require(len(raw_inputs) > 0, "config needs a non-empty 'inputs' list")
    inputs = tuple(InputSpec(file=i["file"], label=i["label"]) for i in raw_inputs)

    output = OutputSpec(**_filter_fields(OutputSpec, raw.get("output") or {}))
    _require(output.format in _VALID_FORMAT,
             f"output.format must be one of {_VALID_FORMAT}, got '{output.format}'")

    eff_raw = raw.get("efficiency") or {}
    efficiency = EfficiencySpec(
        variables=_parse_blocks(eff_raw.get("variables"), EffVariable,
                                "efficiency.variables"),
    )

    res_raw = raw.get("resolution") or {}
    extra_cuts_raw = res_raw.get("extra_cuts") or []
    _require(
        isinstance(extra_cuts_raw, list)
        and all(isinstance(c, str) for c in extra_cuts_raw),
        f"resolution.extra_cuts must be a list of strings; got {extra_cuts_raw!r}",
    )
    resolution = ResolutionSpec(
        residuals=_parse_blocks(res_raw.get("residuals"), ResResidual,
                                "resolution.residuals"),
        x_axes=_parse_blocks(res_raw.get("x_axes"), ResXAxis,
                             "resolution.x_axes"),
        extra_cuts=tuple(extra_cuts_raw),
    )

    return Config(
        cuts=cuts,
        ptSplit=ptSplit,
        inputs=inputs,
        output=output,
        efficiency=efficiency,
        resolution=resolution,
    )
