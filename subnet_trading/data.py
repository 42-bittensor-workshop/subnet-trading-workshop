"""The market history: one table per field, rows = times, columns = subnets (netuid)."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import config

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HISTORY_FILE = DATA_DIR / "history_15min.csv.gz"
HISTORY_5MIN_FILE = DATA_DIR / "history_5min.csv.gz"
HOLDERS_FILE = DATA_DIR / "holders_daily.csv.gz"
FIELDS = ("price", "tao_in", "alpha_in", "alpha_out", "life")


@dataclass
class Market:
    """What the market looked like at every snapshot.

    price      price of one alpha, in TAO
    tao_in     TAO in the subnet's pool
    alpha_in   alpha in the pool
    alpha_out  alpha outside the pool (held or staked)
    holders    number of holders, from the day before (a day's count is known the next day)
    life       changes when a subnet number is given to a new subnet
    """

    price: pd.DataFrame
    tao_in: pd.DataFrame
    alpha_in: pd.DataFrame
    alpha_out: pd.DataFrame
    holders: pd.DataFrame
    life: pd.DataFrame

    @property
    def times(self):
        return self.price.index

    @property
    def bar_minutes(self):
        """Minutes between two snapshots (15 for the provided history)."""
        return int(round(pd.Series(self.times).diff().median().total_seconds() / 60))

    def universe(self, t=None):
        """The subnets with the most TAO in their pool at time t (default: the latest time)."""
        row = self.tao_in.iloc[-1] if t is None else self.tao_in.loc[t]
        return list(row.dropna().nlargest(config.UNIVERSE_SIZE).index)

    def until(self, t):
        """The market as known at time t: nothing after t."""
        cut = lambda table: table.loc[:t]  # noqa: E731
        return Market(*(cut(getattr(self, name)) for name in
                        ("price", "tao_in", "alpha_in", "alpha_out", "holders", "life")))

    def returns(self, start, end):
        """Each subnet's price change between two times, e.g. 0.01 = +1%.
        Missing when the subnet was not the same subnet at both times."""
        change = self.price.loc[end] / self.price.loc[start] - 1
        return change.where(self.life.loc[end] == self.life.loc[start])


def load(path=HISTORY_FILE, holders_path=HOLDERS_FILE):
    """Load a history: February 2026 every 15 minutes by default, or load(HISTORY_5MIN_FILE),
    every 5 minutes up to the day it was fetched (scripts/fetch_history.py)."""
    daily = pd.read_csv(holders_path, parse_dates=["date"]) if holders_path else None
    return market_from_rows(pd.read_csv(path), daily)


def market_from_rows(rows, daily_holders=None):
    """A Market from one row per time and subnet (time, netuid, price, tao_in, alpha_in,
    alpha_out, life), with holder counts from daily rows (date, netuid, holders) if given."""
    rows = rows.assign(time=pd.to_datetime(rows["time"], utc=True))

    def wide(column):
        return rows.pivot(index="time", columns="netuid", values=column).astype(float)

    price = wide("price")
    holders = price * float("nan")
    if daily_holders is not None:
        daily = daily_holders.pivot(index="date", columns="netuid", values="holders").astype(float)
        known_day = (price.index.tz_convert(None).normalize() - pd.Timedelta(days=1))
        holders = daily.reindex(known_day).reindex(columns=price.columns)
        holders.index = price.index
    return Market(price=price, tao_in=wide("tao_in"), alpha_in=wide("alpha_in"),
                  alpha_out=wide("alpha_out"), holders=holders, life=wide("life"))


def market_rows(market):
    """The other way round: one row per time and subnet that has a price."""
    long = []
    for field in FIELDS:
        table = getattr(market, field).rename_axis(index="time", columns="netuid").reset_index()
        long.append(table.melt(id_vars="time", var_name="netuid", value_name=field).set_index(["time", "netuid"]))
    rows = pd.concat(long, axis=1).reset_index()
    rows = rows[rows["price"].notna()].astype({"netuid": int})
    return rows.sort_values(["time", "netuid"]).reset_index(drop=True)
