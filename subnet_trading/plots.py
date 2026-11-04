"""One chart: how each strategy's account evolves, next to the market."""

import matplotlib.pyplot as plt

from . import config

COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300")
INK, MUTED, GRID = "#1a1a19", "#6b6a63", "#e4e3dd"


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
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=9)
    if len(results) > 1:
        ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout()
    return fig
