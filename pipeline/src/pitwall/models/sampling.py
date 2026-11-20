"""Sampling with nutpie and the convergence diagnostics every fitted model is gated on."""

import arviz as az
import numpy as np
import nutpie
import xarray as xr
from nutpie.sample import CompiledModel
from pydantic import BaseModel

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
