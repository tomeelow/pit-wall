"""Sampling with nutpie, the convergence diagnostics every fitted model is gated on, and the
parametrisation that keeps grouped deviations off a ridge."""

import arviz as az
import numpy as np
import nutpie
import pymc as pm
import pytensor.tensor as pt
import xarray as xr
from nutpie.sample import CompiledModel
from pydantic import BaseModel
from pytensor.tensor.variable import TensorVariable

from pitwall.config import GateConfig, SamplerConfig


class Diagnostics(BaseModel):
    max_rhat: float
    min_ess_bulk: float
    min_ess_tail: float
    divergences: int

    def __str__(self) -> str:
        return (
            f"max_rhat={self.max_rhat:.3f} ess_bulk={self.min_ess_bulk:.0f} "
            f"ess_tail={self.min_ess_tail:.0f} divergences={self.divergences}"
        )

    def passes(self, gate: GateConfig) -> bool:
        return (
            self.max_rhat <= gate.max_rhat
            and min(self.min_ess_bulk, self.min_ess_tail) >= gate.min_ess
            and self.divergences <= gate.max_divergences
        )


def diagnose(idata: xr.DataTree) -> Diagnostics:
    def values(stat: xr.DataTree) -> np.ndarray:
        return np.concatenate([np.ravel(v.to_numpy()) for v in stat.data_vars.values()])

    return Diagnostics(
        max_rhat=float(np.nanmax(values(az.rhat(idata)))),
        min_ess_bulk=float(np.nanmin(values(az.ess(idata, method="bulk")))),
        min_ess_tail=float(np.nanmin(values(az.ess(idata, method="tail")))),
        divergences=int(idata.children["sample_stats"].dataset["diverging"].to_numpy().sum()),
    )


def sample(compiled: CompiledModel, config: SamplerConfig) -> tuple[xr.Dataset, Diagnostics]:
    """Posterior draws stacked into one `sample` dimension (chains x draws), and diagnostics."""
    idata = nutpie.sample(
        compiled,
        chains=config.chains,
        tune=config.tune,
        draws=config.draws,
        seed=config.seed,
        target_accept=config.target_accept,
        progress_bar=False,
    )
    posterior = idata.children["posterior"].to_dataset().stack(sample=("chain", "draw"))
    posterior = posterior.transpose("sample", ...).drop_vars(["sample", "chain", "draw"])
    return posterior, diagnose(idata)


def zero_sum_deviation(
    name: str, sd: TensorVariable, segment: np.ndarray, segments: int
) -> TensorVariable:
    """Normal deviations with scale `sd` that sum to zero within each segment.

    A segment of k members gets k - 1 free standard normals mapped through a Helmert basis, which
    is distributed exactly as k iid normals minus their mean but leaves no direction that only
    the prior constrains. Without the constraint a parent and the mean of its few children trade
    off along a ridge the sampler crosses slowly (R-hat > 1.01)."""
    rows, cols, values = [], [], []
    free = 0
    for s in range(segments):
        members = np.flatnonzero(segment == s)
        for j in range(1, len(members)):
            scale = 1 / np.sqrt(j * (j + 1))
            rows += list(members[: j + 1])
            cols += [free] * (j + 1)
            values += [scale] * j + [-j * scale]
            free += 1
    if free == 0:  # every segment has a single member: nothing can deviate
        return pt.zeros(len(segment))
    z = pm.Normal(name, 0, 1, shape=free)
    weights = np.array(values)
    return sd * pt.zeros(len(segment))[np.array(rows, dtype=int)].inc(
        weights * z[np.array(cols, dtype=int)]
    )
