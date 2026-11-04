import numpy as np
import pandas as pd

from subnet_trading.data import Market


def make_market(n_times=60, n_subnets=60, seed=0):
    """Synthetic market: random prices every 15 minutes; subnet 1 has the largest pool, then 2..."""
    rng = np.random.default_rng(seed)
    times = pd.date_range("2026-01-01", periods=n_times, freq="15min", tz="UTC")
    netuids = list(range(1, n_subnets + 1))
    shape = (n_times, n_subnets)
    table = lambda values: pd.DataFrame(values, index=times, columns=netuids)  # noqa: E731
    price = table(np.exp(np.cumsum(rng.normal(0, 0.01, shape), axis=0)))
    tao_in = table(np.tile(np.linspace(100_000, 1_000, n_subnets), (n_times, 1)))
    return Market(price=price, tao_in=tao_in, alpha_in=tao_in / price, alpha_out=tao_in / price,
                  holders=table(rng.integers(100, 1000, shape).astype(float)), life=table(np.zeros(shape)))
