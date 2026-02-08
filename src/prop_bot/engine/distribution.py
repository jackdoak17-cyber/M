from __future__ import annotations

from typing import Dict, List

import numpy as np
from scipy import stats


def fit_player_distribution(values: List[float], adjusted_mean: float) -> Dict:
    if not values:
        return {"distribution": "unknown", "adjusted_mean": adjusted_mean, "probabilities": {}}

    arr = np.array(values, dtype=float)
    sample_mean = float(np.mean(arr))
    sample_var = float(np.var(arr))

    if sample_var > sample_mean * 1.1 and sample_var > 0:
        r = (sample_mean**2) / (sample_var - sample_mean)
        p = sample_mean / sample_var

        dispersion_ratio = sample_var / sample_mean if sample_mean else 1.0
        adjusted_var = adjusted_mean * dispersion_ratio
        if adjusted_var <= adjusted_mean:
            dist = stats.poisson(mu=adjusted_mean)
            distribution = "poisson"
        else:
            r_adj = (adjusted_mean**2) / (adjusted_var - adjusted_mean)
            p_adj = adjusted_mean / adjusted_var
            dist = stats.nbinom(n=r_adj, p=p_adj)
            distribution = "negative_binomial"
    else:
        dist = stats.poisson(mu=adjusted_mean)
        distribution = "poisson"

    probabilities: Dict[str, float] = {}
    for threshold in [1, 2, 3, 4, 5]:
        prob = 1 - dist.cdf(threshold - 1)
        probabilities[f"{threshold}+"] = round(float(prob), 4)

    return {
        "distribution": distribution,
        "adjusted_mean": round(adjusted_mean, 2),
        "probabilities": probabilities,
        "median": int(dist.median()),
        "p10": int(dist.ppf(0.10)),
        "p90": int(dist.ppf(0.90)),
    }
