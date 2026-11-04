# Ideas for signals

A signal gives every subnet a number; your miner buys the 10 highest. Each idea below
is one line. Test it with `backtest(signal, market, start=..., end=...)` on several
days before you trust it.

## What the market does

| Idea | Signal |
|---|---|
| Subnets that rose recently keep rising | `change(market.price, "1h")` |
| The same over a longer window: changes picks less often, so fewer fees | `change(market.price, "4h")` |
| Subnets that just fell bounce back | `-change(market.price, "15m")` |
| Money flowing into the pool | `change(market.tao_in, "1h")` |
| Calm subnets rather than wild ones | `-std(change(market.price, "15m"), "4h")` |
| A move that is unusual for this subnet | `zscore(market.price, "1d")` |

## What the subnet is

| Idea | Signal |
|---|---|
| More holders than yesterday | `change(market.holders, "1d")` |
| Large pools: harder to move | `market.tao_in` |
| Many holders for the size of the pool | `market.holders / market.tao_in` |

`holders` is a daily count, known from the next day on. It changes once a day, so a
signal built on it trades rarely.

## Combining ideas

`rank` turns any signal into positions from 0 (lowest) to 1 (highest), so signals of
different sizes can be added:

```python
rank(change(market.price, "1h")) + rank(change(market.holders, "1d"))
```

## Your own function

For full control, write a function that receives the market as known at the
deadline and returns weights:

```python
def my_strategy(market):
    rising = change(market.price, "1h").iloc[-1]    # the latest value for every subnet
    rising = rising.reindex(market.universe())       # only the 50 largest pools
    return pick_top(rising, n=5)                     # the 5 highest, equal weights
```

`pick_top(scores, n, how="score")` weights the subnets by their score instead of
equally. A function can also return a signal table: the miner then buys the 10 highest
of its latest row, as with a signal. If `backtest(...).summary()` shows rounds without
valid weights, your function returned weights the rules refuse; check them with
`check_weights(weights, market.universe())`.

## What makes a good strategy

- **It beats random picks on most days,** not just one.
- **Its gains cover its fees.** Compare the *fees paid* column with your gain.
- **You can say why it should work.** An idea found by trying everything until
  something fits usually stops working live.
