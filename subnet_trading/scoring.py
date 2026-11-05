"""How an account is scored. The notebook's tests and the event's validator use this same code.

The account starts at START_BALANCE (1,000 TAO) and carries over from round to round:
each round places the account's current value according to the weights.
    1. Trade: moving from the previous weights to the new ones costs FEE_RATE times the
       amount traded (selling one subnet and buying another trades twice).
    2. Hold: every TAO placed in a subnet earns how much that subnet beat the market (the
       average of the universe) over the round, multiplied by FACTOR. TAO left aside earns 0.
An account cannot fall below 0.
"""

import pandas as pd

from . import config


def turnover(old, new):
    """Share of the portfolio traded to go from `old` to `new` weights (sales plus purchases)."""
    return sum(abs(new.get(n, 0.0) - old.get(n, 0.0)) for n in set(old) | set(new))


def rebalance_cost(old, new, value=config.START_BALANCE, fee_rate=None):
    """Fee, in TAO, to go from `old` to `new` weights on a portfolio worth `value` TAO."""
    fee_rate = config.FEE_RATE if fee_rate is None else fee_rate
    return fee_rate * turnover(old, new) * value


def market_return(returns, universe):
    """The market's move over a round: the average return of the universe."""
    return float(pd.Series(returns).reindex(universe).mean())


def round_gain(weights, returns, market):
    """How much the weighted subnets beat the market over the round (before FACTOR).
    A subnet without a return over the round counts as matching the market."""
    returns = pd.Series(returns)
    return sum(w * (returns.get(n, float("nan")) - market) for n, w in weights.items()
               if pd.notna(returns.get(n, float("nan"))))


class Account:
    """One student's virtual account."""

    def __init__(self, factor=None, fee_rate=None):
        self.value = config.START_BALANCE
        self.weights = {}
        self.factor = config.FACTOR if factor is None else factor
        self.fee_rate = config.FEE_RATE if fee_rate is None else fee_rate

    def trade(self, new_weights):
        """Move to new weights; returns the fee paid in TAO."""
        fee = rebalance_cost(self.weights, new_weights, self.value, self.fee_rate)
        self.value -= fee
        self.weights = dict(new_weights)
        return fee

    def hold(self, returns, market):
        """Apply one round of prices to the current value; returns the gain (or loss) in TAO."""
        before = self.value
        self.value = max(0.0, before * (1 + self.factor * round_gain(self.weights, returns, market)))
        return self.value - before


class Leaderboard:
    """Reference for the validator: every miner's account, round after round.

    Before each deadline, `submit` records a miner's latest valid weights. At the end of
    the round, `run_round` trades the new weights at the start of the holding period, then
    applies the round's returns (from the trade to the end of the round). A miner who sent
    nothing keeps its previous weights and pays no fee.
    """

    def __init__(self):
        self.accounts = {}
        self.pending = {}

    def submit(self, miner, weights, universe):
        from .weights import check_weights
        self.pending[miner] = check_weights(weights, universe)
        self.accounts.setdefault(miner, Account())

    def run_round(self, returns, universe):
        market = market_return(returns, universe)
        for miner, account in self.accounts.items():
            if miner in self.pending:
                account.trade(self.pending.pop(miner))
            account.hold(returns, market)

    def standings(self):
        table = pd.Series({m: a.value for m, a in self.accounts.items()}, name="value")
        return table.sort_values(ascending=False)
