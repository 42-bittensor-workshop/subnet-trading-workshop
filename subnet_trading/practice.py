"""A practice game: the real competition, alone, on live data.

Every 15 minutes (at :00, :15, :30 and :45 UTC) your strategy's weights are taken. Five
minutes later the previous round is settled and the new weights are traded, at live
prices, with the event's exact rules and scoring code. A dashboard in your browser shows
your account next to the simple strategy and the market.

Start it with scripts/practice.py.
"""

import json
import runpy
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from . import config
from .backtest import make_weights
from .scoring import Account, Leaderboard
from .signals import change
from .weights import WeightsError

YOU, SIMPLE, MARKET = "you", "simple strategy", "market"


def simple_strategy(market):
    """The reference: the 10 subnets whose price rose most over the last hour."""
    return change(market.price, "1h")


def from_file(path):
    """A hand-picked strategy: the weights in a JSON file, read again at every deadline,
    for example {"64": 0.4, "4": 0.3, "51": 0.3}."""
    path = Path(path)

    def strategy(market):
        return {int(k): float(v) for k, v in json.loads(path.read_text()).items()}

    return strategy


def from_python_file(path):
    """A strategy file defining strategy(market), loaded again at every deadline:
    edits apply from the next round."""
    path = Path(path)

    def strategy(market):
        functions = runpy.run_path(str(path))
        if "strategy" not in functions:
            raise ValueError(f"{path.name} does not define strategy(market)")
        return functions["strategy"](market)

    return strategy


def next_deadline(now):
    """The next :00, :15, :30 or :45 UTC after `now`."""
    base = now.replace(second=0, microsecond=0)
    minutes = config.ROUND_MINUTES - base.minute % config.ROUND_MINUTES
    return base + timedelta(minutes=minutes)


class Practice:
    """One practice session. `chain` provides snapshots (live.Chain, or a fake in tests)."""

    def __init__(self, strategy, chain, history, dashboard=None, clock=None, sleep=time.sleep, log=print):
        self.strategy, self.chain, self.history = strategy, chain, history
        self.dashboard, self.log, self.sleep = dashboard, log, sleep
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.board = Leaderboard()
        self.board.accounts = {YOU: Account(), SIMPLE: Account()}
        self.values = {YOU: [], SIMPLE: [], MARKET: []}
        self.rounds = []
        self.last_trade, self.last_universe, self.sent = None, None, {}

    def wait_until(self, moment):
        while (left := (moment - self.clock()).total_seconds()) > 0:
            self.sleep(min(left, 30))

    def deadline(self, t):
        """At the deadline: a fresh snapshot, then everyone's weights."""
        self.history.add(self.chain.snapshot())
        market = self.history.market()
        universe = market.universe()
        weights = {}
        for name, strategy in ((YOU, self.strategy), (SIMPLE, simple_strategy)):
            try:
                weights[name] = make_weights(strategy, market, market.times[-1], universe)
            except WeightsError as error:
                weights[name] = None
                if name == YOU:
                    self.log(f"{t:%H:%M} your weights were refused, your portfolio stays as it was: {error}")
            except Exception as error:  # noqa: BLE001  a broken strategy file must not stop the game
                weights[name] = None
                if name == YOU:
                    self.log(f"{t:%H:%M} your strategy failed, your portfolio stays as it was: "
                             f"{type(error).__name__}: {error}")
        self.sent = weights
        if weights[YOU] is not None:
            shown = ", ".join(f"{k}: {v:.2f}" for k, v in sorted(weights[YOU].items()))
            self.log(f"{t:%H:%M} deadline: your weights {{{shown}}}")
        return universe

    def trade(self, t, universe):
        """Five minutes later: settle the previous round, then trade the new weights."""
        snap = self.chain.snapshot()
        if self.last_trade is not None:
            before, now = self.last_trade["pools"], snap["pools"]
            returns = (now["price"] / before["price"] - 1).where(now["alpha_out"] >= 0.5 * before["alpha_out"])
            self.board.run_round(returns.dropna().to_dict(), self.last_universe)
            self.record(t)
        for name, weights in self.sent.items():
            if weights is not None:
                self.board.submit(name, weights, universe)
        self.last_trade, self.last_universe = snap, universe

    def settle_last(self):
        """Settle the round still running, without taking new weights."""
        t = next_deadline(self.clock()) + timedelta(minutes=config.HALT_MINUTES)
        self.write_dashboard(t)
        self.wait_until(t)
        self.sent = {}
        self.trade(t, self.last_universe)

    def record(self, t):
        values = {name: self.board.accounts[name].value for name in (YOU, SIMPLE)}
        values[MARKET] = config.START_BALANCE
        for name, value in values.items():
            self.values[name].append((t, value))
        self.rounds.append({"settled": t, **values})
        self.log(f"{t:%H:%M} round settled: you {values[YOU]:,.1f} TAO, "
                 f"simple strategy {values[SIMPLE]:,.1f}, market {values[MARKET]:,.0f}")

    def play(self, rounds=None):
        """Run deadline after deadline; `rounds` = number of deadlines (None: until stopped)."""
        done = 0
        while rounds is None or done < rounds:
            t = next_deadline(self.clock())
            self.write_dashboard(t)
            self.wait_until(t)
            universe = self.deadline(t)
            self.write_dashboard(t + timedelta(minutes=config.HALT_MINUTES))
            self.wait_until(t + timedelta(minutes=config.HALT_MINUTES))
            self.trade(t + timedelta(minutes=config.HALT_MINUTES), universe)
            done += 1
        if self.last_trade is not None:
            self.settle_last()
        self.write_dashboard(None)

    def write_dashboard(self, next_event):
        if self.dashboard:
            from .dashboard import write
            write(self.dashboard, self, next_event)

    def eligible(self):
        """The subnets that can be picked now: the 50 largest pools, largest first."""
        market = self.history.market()
        if not len(market.times):
            return pd.DataFrame()
        universe = market.universe()
        latest = market.times[-1]
        return pd.DataFrame({
            "price": market.price.loc[latest, universe],
            "tao_in": market.tao_in.loc[latest, universe],
            "change_1h": change(market.price, "1h").loc[latest, universe],
        })

    def standings(self):
        return pd.DataFrame(self.rounds).set_index("settled") if self.rounds else pd.DataFrame()
