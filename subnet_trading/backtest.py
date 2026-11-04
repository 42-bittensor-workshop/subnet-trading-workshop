"""Test a strategy on past data, with the event's exact rules.

A strategy is one of:
    - fixed weights:  {8: 0.5, 64: 0.5}
    - a signal table: change(market.price, "1h")   -> the n highest subnets, equal weights
    - a function:     def my_strategy(market): ... return {netuid: weight}
                      It receives only the data known at the deadline.

Timing, as in the event: the weights decided at a deadline are traded HALT_MINUTES later
and held for ROUND_MINUTES. With 15-minute snapshots, the 5-minute pause is rounded up
to one snapshot: in backtests the trade happens 15 minutes after the deadline.
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config
from .scoring import Account, market_return
from .weights import WeightsError, check_weights, pick_top


def make_weights(strategy, market, t, universe, n=config.MAX_SUBNETS):
    """The weights a strategy sends at deadline t."""
    if isinstance(strategy, dict):
        return check_weights({k: v for k, v in strategy.items() if int(k) in universe}, universe)
    if isinstance(strategy, pd.DataFrame):
        scores = strategy.loc[t].reindex(universe)
        return check_weights(pick_top(scores, n), universe)
    if callable(strategy):
        output = strategy(market.until(t))
        if isinstance(output, pd.DataFrame):  # a signal table: its latest row decides
            output = output.iloc[-1]
        if isinstance(output, pd.Series):     # one score per subnet: the n highest in the universe
            return check_weights(pick_top(output.reindex(universe), n), universe)
        return check_weights(output, universe)
    raise TypeError("a strategy is a dict of weights, a signal table, or a function")


@dataclass
class Result:
    """One backtest: a row per round."""

    rounds: pd.DataFrame

    @property
    def value(self):
        return float(self.rounds["value"].iloc[-1]) if len(self.rounds) else config.START_BALANCE

    def summary(self):
        r = self.rounds
        return pd.Series({
            "final value": round(self.value, 1),
            "gain %": round(100 * (self.value / config.START_BALANCE - 1), 1),
            "rounds": len(r),
            "fees paid": round(r["fee"].sum(), 1),
            "traded per round %": round(100 * r["turnover"].mean(), 1),
            "rounds without valid weights": int((~r["valid"]).sum()),
        })


def backtest(strategy, market, start=None, end=None, n=config.MAX_SUBNETS, factor=None, fee_rate=None):
    """Run a strategy through the history, round after round. Returns a Result."""
    times = market.times
    if start is not None:
        times = times[times >= pd.Timestamp(start, tz="UTC")]
    if end is not None:
        times = times[times <= pd.Timestamp(end, tz="UTC")]
    step = max(1, round(config.ROUND_MINUTES / market.bar_minutes))
    halt = math.ceil(config.HALT_MINUTES / market.bar_minutes)

    account, rows = Account(factor, fee_rate), []
    for i in range(0, len(times) - halt - step, step):
        deadline, trade_at, end_at = times[i], times[i + halt], times[i + halt + step]
        universe = market.universe(deadline)
        try:
            weights, valid = make_weights(strategy, market, deadline, universe, n), True
        except WeightsError:
            weights, valid = account.weights, False  # not sent: the portfolio stays as it was
        old = account.weights
        fee = account.trade(weights)
        returns = market.returns(trade_at, end_at)
        change = account.hold(returns, market_return(returns, universe))
        rows.append({"deadline": deadline, "value": account.value, "change": change, "fee": fee, "valid": valid,
                     "turnover": sum(abs(weights.get(k, 0) - old.get(k, 0)) for k in set(old) | set(weights)),
                     "subnets": ",".join(str(k) for k in sorted(weights))})
    return Result(pd.DataFrame(rows).set_index("deadline") if rows else pd.DataFrame())


def compare(strategies, market, **kwargs):
    """Backtest several strategies; returns (summary table, {name: Result})."""
    results = {name: backtest(s, market, **kwargs) for name, s in strategies.items()}
    table = pd.DataFrame({name: r.summary() for name, r in results.items()}).T
    return table, results


def random_strategy(seed=0, n=config.MAX_SUBNETS):
    """Picks n random subnets every round: the luck baseline."""
    rng = np.random.default_rng(seed)

    def strategy(market):
        universe = market.universe()
        return {int(k): 1 / n for k in rng.choice(universe, size=n, replace=False)}

    return strategy
