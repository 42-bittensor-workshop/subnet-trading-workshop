# Rules

Every value below lives in `subnet_trading/config.py`. The scoring code is
`subnet_trading/scoring.py`, used both by the notebook's backtests and by the event's
validator.

## One round, every 15 minutes

| Time | What happens |
|---|---|
| t | Deadline: your miner's latest weights before t count |
| t → t+5 | Pause: nothing changes |
| t+5 | Your portfolio moves to the new weights at that moment's prices, and the fee is charged |
| t+5 → t+20 | Your gain or loss follows the real subnet prices |
| t+15 | Next deadline, whose weights apply from t+20: rounds follow each other without a gap |

If your miner sends nothing before a deadline, your portfolio keeps its weights and
you pay no fee.

## Your weights

- A dict `{netuid: weight}` with **at most 10 subnets**.
- Only the **50 subnets with the most TAO in their pool** at the deadline.
- No negative weights.
- If the weights add up to less than 1, the rest stays in TAO and earns nothing. If
  they add up to more than 1, they are scaled down to add up to 1.

`check_weights(weights, market.universe())` tells you whether a list is valid, and
why not.

## Scoring

Your account starts at **1,000 TAO** and carries over from round to round. Each
round, its current value V is placed according to your weights.

**The fee**, at t+5: 0.25% of the amount traded to move from your previous weights to
the new ones. Selling one subnet and buying another trades twice.

```
fee = 0.25% × (sum of |new weight − old weight| over all subnets) × V
```

**The gain**, from t+5 to t+20, on the value left after the fee, with r = each
subnet's price change and m = the average price change of the 50 subnets:

```
gain = 20 × (sum over your subnets of weight × (r − m)) × V
```

An account cannot fall below 0. The ranking at the end of the event uses the
account's value.

## Worked example

Three subnets in the market: subnet 1 rises 2%, subnet 2 falls 1%, subnet 3 stays
flat. The average m is +0.333%. Your account holds 1,000 TAO with no position, and you
choose `{1: 0.5, 2: 0.25}`: a quarter of your TAO stays aside.

- Fee: you trade 0.5 + 0.25 = 0.75 of your 1,000 TAO, so 0.25% × 0.75 × 1,000 =
  **1.875 TAO**. 998.125 TAO remain.
- Gain: 0.5 × (2% − 0.333%) + 0.25 × (−1% − 0.333%) = 0.833% − 0.333% = 0.5%, then
  20 × 0.5% = +10% of 998.125 TAO = **99.8125 TAO**.

Your account goes from 1,000 to 1,097.94 TAO, and the next round starts from there.
The same numbers are checked in `tests/test_scoring.py`.

## How the two numbers were set

Both were measured on the February 2026 history, with `scripts/calibrate.py`.
The reference strategy buys the 10 subnets that rose most over the last hour:

- **20:** in a typical round, that strategy ends about 0.045% above or below the
  market. Multiplied by 20, a typical round moves an account by about 1%, so good and
  bad choices show.
- **0.25%:** before fees, random picks earn nothing. At 0.25%, they lose through fees
  about as much as the reference strategy gains after fees. Trading pays only when it
  is based on a real signal.

## Backtests versus the live event

The provided history has one snapshot every 15 minutes, so in backtests the 5-minute
pause is rounded up to 15 minutes: weights decided at a snapshot are traded at the
next one. Live, the pause is exactly 5 minutes.

## For organisers

The rules here are taogalaxy's proposal, implemented and tested. The event's validator
is the final authority, and this repository is kept in step with it.

The validator reference is `Leaderboard` in `subnet_trading/scoring.py`:

1. Before each deadline, `submit(miner, weights, universe)` records each miner's latest
   valid weights. The universe is the 50 largest pools at the deadline.
2. At t+20, `run_round(returns, universe)` charges the fees and applies the returns
   from t+5 to t+20.
3. `standings()` gives the ranking.

The validator needs the price of every subnet at t+5 and t+20, and the TAO in every
pool at t.
