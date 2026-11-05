"""An example strategy for your miner and for the practice game:

    python scripts/practice.py --strategy strategies/example_strategy.py

A strategy is a function that receives the market as known at the deadline. It returns
either a signal (one number per subnet: the 10 highest are bought, equal weights) or
weights {netuid: weight}. Test it in the notebook with backtest() before practising.
"""

from subnet_trading import change


def strategy(market):
    return change(market.price, "1h")   # the subnets that rose most over the last hour
