"""Choose FACTOR and FEE_RATE from the history (docs/RULES.md, "How the two numbers were set").

    python scripts/calibrate.py

FACTOR:   a typical round moves the account of the reference strategy by about 1%.
FEE_RATE: random picks lose, through fees, as much as the reference strategy gains after
          fees. Before fees, random picks gain nothing.
Reference strategy: the 10 subnets with the largest price rise over the last hour.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from subnet_trading import backtest, change, config, load, random_strategy  # noqa: E402


def raw_rounds(strategy, market):
    """Per round: the gain over the market before FACTOR and fees, and the share traded."""
    r = backtest(strategy, market, factor=1, fee_rate=0).rounds
    return (r["change"] / config.START_BALANCE).to_numpy(), r["turnover"].to_numpy()


market = load()
reference = change(market.price, "1h")
gain, traded = raw_rounds(reference, market)
factor = 0.01 / np.median(np.abs(gain))
random_traded = np.mean([raw_rounds(random_strategy(seed), market)[1].mean() for seed in range(3)])
fee = config.FACTOR * gain.mean() / (traded.mean() + random_traded)

print(f"reference strategy, {len(gain)} rounds: mean gain over the market {gain.mean():.5%} per round, "
      f"median size {np.median(np.abs(gain)):.5%}, traded {traded.mean():.0%} of the portfolio per round")
print(f"FACTOR for ~1% typical moves: {factor:.1f} (config: {config.FACTOR})")
print(f"random picks trade {random_traded:.0%} of the portfolio per round")
print(f"FEE_RATE where random picks lose what the reference gains, at FACTOR {config.FACTOR}: {fee:.3%} "
      f"(config: {config.FEE_RATE:.3%})")
