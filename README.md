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

Your account starts at 1,000 TAO and **carries over**: each round plays with the TAO
you have. Each round, two things happen:

1. **The fee:** 0.25% of the amount you trade to move to your new weights. Keeping the
   same weights costs nothing.
2. **The gain:** for each subnet, its weight × (its price change − the average price
   change of the 50 subnets) × 20, applied to your account.

Example: your account holds 1,000 TAO, and you put half of it on a subnet that rose
2% while the average rose 0.3%. You gain 0.5 × 1.7% × 20 × 1,000 = **170 TAO** on that
subnet. The next round, you play with your new balance.

All the rules, with the exact timing: [docs/RULES.md](docs/RULES.md).

## Why the game works this way

This is a very simplified version of intraday trading. Real traders work around the
clock, with real money and real costs. Here you have two or three hours, a handful of
rounds and nothing at risk. So we kept the spirit of trading and chose rules that make
sure something actually happens on the screen.

Subnet prices barely move in 15 minutes, often by a few hundredths of a percent. On
their own, those moves would hardly change your account, so we multiply them by 20, a
bit like trading with leverage. A good round shows, and so does a bad one.

We also compare you with the average subnet instead of counting your raw gains. When
the whole market goes up or down, that's not your doing, and it would decide the
ranking more than your choices would. Measured against the average, only your choices
count: if you hold the market, you neither win nor lose.

Trading is never free, so every trade costs a small fee. It is set so that shuffling
your picks at random every 15 minutes loses money, while a sensible strategy can still
come out ahead. The 5-minute pause between the deadline and the trade locks your
weights before the prices that count start to move. And we stick to the 50 largest
subnets, which trade the most and are hard to push around.

Real trading has more to it: large orders that move prices, risk limits, the stress
of real money. We left that out on purpose. The point is to give you a feel for what
it's like to look for a signal, test it, and see whether it holds up live.

## Three tools

You will use three things during the workshop, and the same strategy works in all of
them:

1. **The notebook** (`notebooks/start_here.ipynb`) is your lab. You try ideas on past
   data, test them with the game's rules and look at the results. This is where you
   learn what makes a strategy better, and what to watch out for.
2. **The practice game** (`scripts/practice.py`) is the real competition, just for you.
   It reads live subnet prices from the chain, takes your weights every 15 minutes,
   trades 5 minutes later, and shows how you're doing on a dashboard in your browser.
3. **Your miner** is what you run during the event. It sends your weights to the
   validator.

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

## 1. Research in the notebook

The notebook takes about 30 minutes. It walks you from a hand-picked portfolio to a
signal you can test, and shows how fees and luck change the result. The core of it
fits in three lines:

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

## 2. Practise live

```bash
python scripts/practice.py strategies/example_strategy.py
```

It loads the last 24 hours of prices from the chain (about 2 minutes) and opens the
dashboard in your browser. Then it plays round after round: it takes your weights at
:00, :15, :30 and :45 UTC, trades 5 minutes later, and shows your account next to a
simple strategy and the market. Stop it with Ctrl+C.

Your strategy goes in a small Python file with one function, `strategy(market)`;
`strategies/example_strategy.py` is a starting point. To pick by hand instead, edit
`strategies/my_weights.json` whenever you like and run:

```bash
python scripts/practice.py --weights strategies/my_weights.json
```

The file is read again at every deadline. Holder counts aren't available live yet:
they come from TaoSwap, not from the chain.

## 3. The event: your miner

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

---

Designed by taogalaxy, a quantitative investment firm building systematic strategies
on Bittensor.
