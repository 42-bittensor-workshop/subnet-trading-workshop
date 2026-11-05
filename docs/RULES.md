# Rules

Every value below lives in `subnet_trading/config.py`. The scoring code is
`subnet_trading/scoring.py`, used both by the notebook's backtests and by the event's
validator.

## One round, every 15 minutes

| Time | What happens |
|---|---|
| t | Deadline: your miner's latest weights before t count |
| t → t+5 | Pause: your account is frozen |
| t+5 | Your portfolio moves to the new weights at that moment's prices, and the fee is charged |
| t+5 → t+15 | Live: your gain or loss follows the real subnet prices |
| t+15 | The round's result, and the next round's deadline |

Rounds follow each other: a round is settled before the next one starts.

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

**The gain**, from t+5 to t+15, on the value left after the fee, with r = each
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

## Ranking

- Every miner starts with 1,000 TAO at the first scored deadline. A miner that joins
  later starts with 1,000 TAO at its first deadline.
- At any moment, miners are ranked by their account value after the last settled
  round.
- After each settled round, the validator sets each miner's on-chain weight to the
  number of other miners it beats (a tie counts half), as a share of the total. First
  place gets the most, last place 0, and miners with equal values get equal weights.
  Only the order counts, so there is always a winner, even if every account is below
  1,000 TAO.
- The prizes follow the ranking at the last deadline of the event. Miners with exactly
  the same value share their place.

## How the two numbers were set

Both were measured on the February 2026 history, with `scripts/calibrate.py`.
The reference strategy buys the 10 subnets that rose most over the last hour:

- **20:** in a typical round, that strategy ends about 0.043% above or below the
  market. Multiplied by 20, a typical round moves an account by roughly 1%, so good
  and bad choices show.
- **0.25%:** before fees, random picks earn nothing. At about 0.25%, they lose through
  fees as much as the reference strategy gains after fees. Trading pays only when it
  is based on a real signal.

These were measured on 15-minute moves, the resolution of the history. At the event,
the live part of a round lasts 10 minutes, so moves will be a little smaller. Both
numbers should be checked again on 5-minute data.

## Backtests versus the live event

The provided history has one snapshot every 15 minutes, so backtests round the pause
and the live part up to one snapshot each: a backtest round lasts 30 minutes (15 of
pause, 15 live). With 5-minute data, backtests match the event exactly. In the practice
game (`scripts/practice.py`) and at the event, a round is 5 minutes of pause and 10
live.

## For organisers

The rules here are taogalaxy's proposal, implemented and tested. The event's validator
is the final authority, and this repository is kept in step with it.

The validator reference is `Leaderboard` in `subnet_trading/scoring.py`:

1. At the first scored deadline, `register(miners)` gives every registered miner
   1,000 TAO.
2. Before each deadline, `submit(miner, weights, universe)` records each miner's latest
   valid weights. The universe is the 50 largest pools at the deadline.
3. At t+15, `run_round(returns, universe)` charges the fees and applies the returns
   from t+5 to t+15. Then the next round's weights are submitted.
4. `standings()` gives the ranking, and `weights()` the weights to set on chain.

The validator needs the price of every subnet at t+5 and t+15, and the TAO in every
pool at t. Bittensor limits how often a validator can set weights: on the testnet
subnet, allow it every 75 blocks (15 minutes) to set them after every round, or set
them every other round.
