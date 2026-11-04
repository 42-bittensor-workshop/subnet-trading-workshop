"""Weights: what a miner sends. A dict {netuid: weight}, for example {8: 0.3, 64: 0.2, 4: 0.5}."""

import math

import pandas as pd

from . import config


class WeightsError(ValueError):
    pass


def check_weights(weights, universe):
    """The weights as the validator will use them, or WeightsError with the reason.

    At most MAX_SUBNETS subnets, all in the universe, no negative weight. If the weights
    add up to more than 1 they are scaled down to 1; if less, the rest stays in TAO.
    """
    if not isinstance(weights, dict):
        raise WeightsError("weights must be a dict {netuid: weight}")
    clean = {}
    for netuid, weight in weights.items():
        try:
            netuid, weight = int(netuid), float(weight)
        except (TypeError, ValueError):
            raise WeightsError(f"not a subnet id and a number: {netuid!r}: {weight!r}") from None
        if not math.isfinite(weight) or weight < 0:
            raise WeightsError(f"subnet {netuid}: weights must be 0 or more")
        if weight > 0:
            clean[netuid] = clean.get(netuid, 0.0) + weight
    if len(clean) > config.MAX_SUBNETS:
        raise WeightsError(f"{len(clean)} subnets; at most {config.MAX_SUBNETS}")
    outside = sorted(set(clean) - set(universe))
    if outside:
        raise WeightsError(f"not among the {config.UNIVERSE_SIZE} largest subnets: {outside}")
    total = sum(clean.values())
    if total > 1:
        clean = {netuid: weight / total for netuid, weight in clean.items()}
    return clean


def pick_top(scores, n=config.MAX_SUBNETS, how="equal"):
    """Weights for the n subnets with the highest scores.

    how="equal": the same weight for each (1/n).
    how="score": in proportion to the score (only subnets with a positive score).
    """
    scores = pd.Series(scores, dtype=float).dropna()
    if how == "score":
        scores = scores[scores > 0]
    best = scores.nlargest(n)
    if best.empty:
        return {}
    if how == "equal":
        return {int(netuid): 1 / len(best) for netuid in best.index}
    if how == "score":
        return {int(netuid): float(v / best.sum()) for netuid, v in best.items()}
    raise ValueError("how must be 'equal' or 'score'")
