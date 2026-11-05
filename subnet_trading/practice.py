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
    """One practice session. `chain` provides snapshots (live.Chain, or a fake in tests).

    Rounds follow each other: at each deadline the round in progress is settled, then
    everyone's weights for the next round are taken; they are traded 5 minutes later and
    held until the next deadline.
    """

    def __init__(self, strategy, chain, history, dashboard=None, clock=None, sleep=time.sleep, log=print):
        self.strategy, self.chain, self.history = strategy, chain, history
        self.dashboard, self.log, self.sleep = dashboard, log, sleep
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.board = Leaderboard()
        self.board.accounts = {YOU: Account(), SIMPLE: Account()}
        self.values = {YOU: [], SIMPLE: [], MARKET: []}
        self.rounds = []      # one row per settled round, for the standings
        self.timeline = []    # every round: its times, its status and your result
        self.open = None      # the round in progress
        self.sent = {}

    def wait_until(self, moment):
        while (left := (moment - self.clock()).total_seconds()) > 0:
            self.sleep(min(left, 30))

    def deadline(self, t):
        """At a deadline: settle the round in progress, then take everyone's weights."""
        snap = self.chain.snapshot()
        self.history.add(snap)
        if self.open is not None and self.open.get("trade") is not None:
            self.settle(t, snap)
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
            if weights[name] is not None:
                self.board.submit(name, weights[name], universe)
        self.sent = weights
        number = len(self.timeline) + 1
        trade_at = t + timedelta(minutes=config.HALT_MINUTES)
        result_at = t + timedelta(minutes=config.ROUND_MINUTES)
        self.open = {"number": number, "universe": universe, "trade": None}
        self.timeline.append({"round": number, "deadline": t, "trade": trade_at, "result": result_at,
                              "status": "pause", "you": None})
        if weights[YOU] is not None:
            shown = ", ".join(f"{k}: {v:.2f}" for k, v in sorted(weights[YOU].items()))
            self.log(f"{t:%H:%M} round {number}: your weights {{{shown}}}; "
                     f"traded at {trade_at:%H:%M}, result at {result_at:%H:%M}")
        return universe

    def trade(self, t):
        """Five minutes after the deadline: the round's prices start to count."""
        self.open["trade"] = self.chain.snapshot()
        self.timeline[-1]["status"] = "live"
        self.log(f"{t:%H:%M} round {self.open['number']}: traded, live until "
                 f"{self.timeline[-1]['result']:%H:%M}")

    def settle(self, t, snap):
        """The round's result: returns from its trade to now, with the event's scoring code."""
        before, now = self.open["trade"]["pools"], snap["pools"]
        returns = (now["price"] / before["price"] - 1).where(now["alpha_out"] >= 0.5 * before["alpha_out"])
        start = self.board.accounts[YOU].value
        self.board.run_round(returns.dropna().to_dict(), self.open["universe"])
        self.timeline[-1].update(status="settled", you=self.board.accounts[YOU].value - start)
        self.record(t)
        self.open = None

    def record(self, t):
        values = {name: self.board.accounts[name].value for name in (YOU, SIMPLE)}
        values[MARKET] = config.START_BALANCE
        for name, value in values.items():
            self.values[name].append((t, value))
        self.rounds.append({"settled": t, **values})
        self.log(f"{t:%H:%M} round {self.timeline[-1]['round']} result: you {values[YOU]:,.1f} TAO "
                 f"({self.timeline[-1]['you']:+.1f}), simple strategy {values[SIMPLE]:,.1f}, "
                 f"market {values[MARKET]:,.0f}")

    def play(self, rounds=None):
        """Play `rounds` rounds (None: until stopped). The last one is settled at the next deadline."""
        done = 0
        while rounds is None or done < rounds:
            t = next_deadline(self.clock())
            self.write_dashboard(t)
            self.wait_until(t)
            self.deadline(t)
            trade_at = t + timedelta(minutes=config.HALT_MINUTES)
            self.write_dashboard(trade_at)
            self.wait_until(trade_at)
            self.trade(trade_at)
            done += 1
        t = next_deadline(self.clock())
        self.write_dashboard(t)
        self.wait_until(t)
        snap = self.chain.snapshot()
        self.history.add(snap)
        self.settle(t, snap)
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
