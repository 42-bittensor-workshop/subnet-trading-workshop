"""Write and run notebooks/start_here.ipynb, so it ships with its outputs.

    python scripts/build_notebook.py

Needs the dev dependencies: pip install -e ".[dev]"
"""

from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient

REPO = Path(__file__).resolve().parent.parent
md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell

CELLS = [
    md("""# Start here

Build a trading strategy for Bittensor subnets, test it on real past data, then let your miner run it live. About 30 minutes.

Run the cells in order (Shift + Enter). The first one prepares Google Colab; on a laptop it does nothing."""),
    code("""# On Google Colab, this cell downloads the workshop. On your laptop, it does nothing.
import os, subprocess, sys
if "google.colab" in sys.modules and not os.path.exists("subnet_trading"):
    if not os.path.exists("subnet-trading-workshop"):
        subprocess.run(["git", "clone", "-q", "https://github.com/42-bittensor-workshop/subnet-trading-workshop.git"], check=True)
    os.chdir("subnet-trading-workshop")
    sys.path.insert(0, os.getcwd())"""),
    code("""import pandas as pd
from subnet_trading import *

pd.set_option("display.float_format", "{:.4f}".format)"""),

    md("""## 1. The game

- You start with **1,000 TAO** (virtual).
- Every **15 minutes**, your miner sends a list of **up to 10 subnets with weights**, for example `{64: 0.5, 4: 0.3, 51: 0.2}`.
- After a 5-minute pause, your TAO is placed that way for 15 minutes.
- You **gain** when your subnets do better than the average subnet, and **lose** when they do worse. Every trade costs a small **fee**.
- Your account **carries over**: each round plays with the TAO you have.
- Whoever has the most TAO at the end wins.

Only the 50 subnets with the most TAO in their pool count."""),

    md("## 2. Look at the market"),
    code("""market = load()   # February 2026, one snapshot every 15 minutes
print(f"{len(market.times)} snapshots, from {market.times[0]:%Y-%m-%d} to {market.times[-1]:%Y-%m-%d}")

now = market.times[-1]
biggest = market.universe(now)[:10]
pd.DataFrame({
    "price (TAO)": market.price.loc[now, biggest],
    "TAO in pool": market.tao_in.loc[now, biggest].round(0),
    "change over the last hour (%)": (100 * change(market.price, "1h").loc[now, biggest]).round(3),
})"""),
    md("""Each subnet has a price in TAO that moves all the time. `market.price` holds every price at every snapshot: one row per time, one column per subnet (its number, the *netuid*)."""),

    md("""## 3. Your first strategy: pick by hand

Choose a few subnets and weights, then **backtest**: replay a past day with the real rules (pause, fees, everything) and see what would have happened."""),
    code("""my_pick = {64: 0.4, 4: 0.3, 51: 0.3}

day = dict(start="2026-02-20", end="2026-02-21")
result = backtest(my_pick, market, **day)
result.summary()"""),
    md("""Holding the same subnets all day costs a fee only once, at the start. The gain comes from whether those subnets beat the average."""),

    md("""## 4. A signal: let the data choose

A **signal** gives every subnet a number; your miner buys the 10 highest. A simple idea: subnets that rose in the last hour may keep rising."""),
    code("""rising = change(market.price, "1h")     # price change over the last hour, for every subnet and time

table, results = compare({
    "by hand": my_pick,
    "rose in the last hour": rising,
    "random picks": random_strategy(seed=0),
}, market, **day)
table"""),
    code("""plot_accounts(results);"""),

    md("""## 5. Fees

Every time you change your weights, you pay 0.25% of the amount you trade. Selling one subnet to buy another trades twice. `rebalance_cost` tells you the fee in advance, here for an account of 1,000 TAO:"""),
    code("""print("start with 2 subnets:      ", rebalance_cost({}, {64: 0.5, 4: 0.5}), "TAO")
print("swap one subnet for another:", rebalance_cost({64: 0.5, 4: 0.5}, {64: 0.5, 8: 0.5}), "TAO")
print("change nothing:             ", rebalance_cost({64: 0.5, 4: 0.5}, {64: 0.5, 4: 0.5}), "TAO")"""),
    md("""Look at the *fees paid* column in the table above. Random picks change everything every 15 minutes and pay a lot. A good signal must gain more than it pays."""),

    md("""## 6. Skill or luck?

One good day proves little. Test the same strategy on a whole week, day by day, next to random picks."""),
    code("""rows = {}
for d in pd.date_range("2026-02-15", "2026-02-21"):
    window = dict(start=d, end=d + pd.Timedelta(days=1))
    rows[f"{d:%a %d}"] = {
        "rose in the last hour": backtest(rising, market, **window).value,
        "random picks": backtest(random_strategy(seed=d.day), market, **window).value,
    }
pd.DataFrame(rows).T.round(0)"""),
    md("""A strategy you can trust wins on most days, not just one. That is what professional traders look for: an edge that repeats."""),

    md("""## 7. Your turn: try ideas

`docs/IDEAS.md` lists ideas with the line of code for each. Four to start:"""),
    code("""ideas = {
    "rose in the last hour": change(market.price, "1h"),
    "TAO flowing into the pool": change(market.tao_in, "1h"),
    "fell in the last 15 minutes": -change(market.price, "15m"),
    "more holders than yesterday": change(market.holders, "1d"),
}
table, results = compare(ideas, market, **day)
table"""),
    md("""Two ideas can be the same idea in disguise. A subnet's price is the TAO in its pool divided by the alpha in its pool, so when TAO flows in, the price rises: the first two ideas pick almost the same subnets.

Change a window (`"1h"` to `"4h"`), combine two signals (`rank(a) + rank(b)`), or write your own. Then test it on several days, as in step 6, before trusting it."""),

    md("""## 8. Your miner

Your miner runs your strategy every 15 minutes and sends the result. This is exactly what it would send right now:"""),
    code("""def my_strategy(market):
    return change(market.price, "1h")

next_weights(my_strategy, market)"""),
    md("""During the event, you start your miner with `run(my_strategy, get_market, send)`. The organisers give you `get_market` (the live market) and `send` (delivery to the validator). Your strategy can be a signal like this one, your own function, or fixed weights such as `{64: 0.5, 4: 0.5}`.

Before the event, try your strategy live with the practice game. Save it in a file with a `strategy(market)` function, like `strategies/example_strategy.py`, then run in a terminal:

```bash
python scripts/practice.py strategies/example_strategy.py
```

It plays the real rules on live prices and shows your account on a dashboard. **One last thing:** what worked in the past may not work next. Live, you will find out!"""),
]


def main():
    nb = nbf.v4.new_notebook()
    nb["cells"] = CELLS
    nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    out = REPO / "notebooks" / "start_here.ipynb"
    NotebookClient(nb, timeout=900, kernel_name="python3",
                   resources={"metadata": {"path": str(out.parent)}}).execute()
    nbf.write(nb, out)
    print(f"written {out}")


if __name__ == "__main__":
    main()
