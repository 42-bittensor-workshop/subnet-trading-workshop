"""Charts: how each strategy's account evolves next to the market, and a subnet's candles."""

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter

from . import config

COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300")
INK, MUTED, GRID = "#1a1a19", "#6b6a63", "#e4e3dd"
UP, DOWN = "#1baf7a", "#eb6834"
MAX_CANDLESTICKS = 300


def _tidy(ax):
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=9)


def plot_accounts(results, title="Account value (TAO)"):
    """results: {name: Result} from backtest or compare."""
    fig, ax = plt.subplots(figsize=(9, 3.8))
    for (name, result), color in zip(results.items(), COLORS):
        values = result.rounds["value"]
        ax.plot(values.index, values.values, color=color, linewidth=2, label=name)
    ax.axhline(config.START_BALANCE, color=MUTED, linewidth=1, linestyle="--")
    ax.annotate("the market (1,000)", (ax.get_xlim()[0], config.START_BALANCE), xytext=(4, 4),
                textcoords="offset points", color=MUTED, fontsize=9)
    ax.set_title(title, loc="left", fontsize=12, color=INK)
    _tidy(ax)
    if len(results) > 1:
        ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout()
    return fig


def plot_candles(candles, title="Price (TAO per alpha)"):
    """Candles with columns time, open, high, low, close, volume (taoswap.Taoswap.candles): one
    candlestick each, green when the price rose, up to 300 of them; beyond, the close inside
    its high-low range. The TAO traded is below. Prices that moved tenfold get a log scale."""
    times = candles["time"].dt.tz_convert(None) if candles["time"].dt.tz is not None else candles["time"]
    times = times.to_numpy()
    step = pd.Series(times).diff().median() if len(times) > 1 else pd.NaT
    width = 0.7 * (step if pd.notna(step) else pd.Timedelta(minutes=1)) / pd.Timedelta(days=1)
    colors = [UP if rose else DOWN for rose in (candles["close"] >= candles["open"])]
    fig, (top, bottom) = plt.subplots(2, 1, sharex=True, figsize=(9, 4.8), gridspec_kw={"height_ratios": (3, 1)})
    if len(candles) <= MAX_CANDLESTICKS:
        top.vlines(times, candles["low"], candles["high"], colors=colors, linewidth=0.8)
        span = max(candles["high"].max() - candles["low"].min(), candles["close"].abs().max() * 1e-6)
        body = (candles["close"] - candles["open"]).abs().clip(lower=span * 0.003)
        top.bar(times, body, bottom=candles[["open", "close"]].min(axis=1), width=width, color=colors)
        bottom.bar(times, candles["volume"], width=width, color=colors)
    else:
        top.fill_between(times, candles["low"], candles["high"], color=COLORS[0], alpha=0.15, linewidth=0)
        top.plot(times, candles["close"], color=COLORS[0], linewidth=1)
        bottom.bar(times, candles["volume"], width=width, color=MUTED)
    floor = candles["low"][candles["low"] > 0].min()
    if pd.notna(floor) and candles["high"].max() > 10 * floor:  # a tenfold move would flatten the rest
        top.set_yscale("log")
        top.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
        title += ", log scale"
    top.set_title(title, loc="left", fontsize=12, color=INK)
    bottom.set_ylabel("TAO traded", color=MUTED, fontsize=9)
    bottom.set_xlabel("UTC", color=MUTED, fontsize=9)
    for ax in (top, bottom):
        _tidy(ax)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig
