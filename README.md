# subnet-trading-workshop

Run your first Bittensor miner, and get a taste of quantitative trading: build a
strategy that picks subnets, test it on real past data, then let your miner trade it
live against everyone else.

## The game

- You start with **1,000 TAO** (virtual money).
- Every **15 minutes**, your miner sends a list of **up to 10 subnets with weights**,
  for example `{64: 0.5, 4: 0.3, 51: 0.2}`.
- After a **5-minute pause**, your TAO is placed that way for the next 15 minutes.
- You **gain** when your subnets do better than the average subnet, and **lose** when
  they do worse. Every trade costs a small **fee**.
- Only the **50 subnets with the most TAO in their pool** can be picked.
- Whoever has the most TAO at the end wins.

## How you are scored

Each round, two things happen to your account:

1. **The fee:** 0.25% of the amount you trade to move to your new weights. Keeping the
   same weights costs nothing.
2. **The gain:** for each subnet, its weight × (its price change − the average price
   change of the 50 subnets), multiplied by 20 and by 1,000 TAO.

Example: you put half your weight on a subnet that rose 2% while the average rose
0.3%. You gain 0.5 × 1.7% × 20 × 1,000 = **170 TAO** on that subnet.

All the rules, with the exact timing: [docs/RULES.md](docs/RULES.md).

## Get started

On Google Colab: open `notebooks/start_here.ipynb` from GitHub and run the cells in
order.

On your laptop, with Python 3.10 or later:

```bash
git clone https://github.com/42-bittensor-workshop/subnet-trading-workshop.git
cd subnet-trading-workshop
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" notebook
jupyter notebook notebooks/start_here.ipynb
```

The notebook takes about 30 minutes. It walks you from a hand-picked portfolio to a
signal you can test, and shows how fees and luck change the result.

## Your strategy in three lines

```python
from subnet_trading import *

market = load()                                  # February 2026, every 15 minutes
rising = change(market.price, "1h")              # a signal: the price change over the last hour
backtest(rising, market, start="2026-02-20", end="2026-02-21").summary()
```

A strategy can be:
- **a signal:** your miner buys the 10 subnets with the highest values;
- **fixed weights** that you choose, like `{64: 0.5, 4: 0.5}`;
- **your own function** that receives the market and returns weights.

## Your miner

Your miner sends one thing every 15 minutes: a dict of subnet ids and weights. During
the event you start it with your strategy:

```python
run(my_strategy, get_market, send)
```

The organisers give you `get_market` (the live market) and `send` (delivery to the
validator). `next_weights(my_strategy, market)` shows what it would send right now.

## More

- [docs/RULES.md](docs/RULES.md): every rule, the timing, and a worked example.
- [docs/IDEAS.md](docs/IDEAS.md): ideas for signals, one line of code each.
- [data/README.md](data/README.md): what is in the data.
