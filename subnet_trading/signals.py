"""Building blocks for signals. A signal gives every subnet a number at every time;
a higher number means "I expect this subnet to do better than the others".

Every function looks only backwards: the value at time t uses data up to t.
Windows are written as text ("15m", "1h", "4h", "1d", "1w") or as a number of snapshots.
"""

import numpy as np
import pandas as pd

_MINUTES = {"m": 1, "h": 60, "d": 1440, "w": 10080}


def _steps(table, window):
    if isinstance(window, (int, np.integer)):
        return int(window)
    minutes = int(window[:-1]) * _MINUTES[window[-1]]
    spacing = pd.Series(table.index).diff().median().total_seconds() / 60
    return max(1, int(round(minutes / spacing)))


def _clean(table):
    return table.replace([np.inf, -np.inf], np.nan)


def change(x, window):
    """Relative change over the window: 0.02 means +2%."""
    return _clean(x / x.shift(_steps(x, window)) - 1)


def delay(x, window):
    """The value one window ago."""
    return x.shift(_steps(x, window))


def mean(x, window):
    """Average over the window."""
    n = _steps(x, window)
    return x.rolling(n, min_periods=n).mean()


def std(x, window):
    """How much x moved around over the window (standard deviation)."""
    n = _steps(x, window)
    return x.rolling(n, min_periods=n).std()


def zscore(x, window):
    """How unusual the latest value is compared with the window, in standard deviations."""
    s = std(x, window)
    return _clean((x - mean(x, window)) / s.where(s > 0))


def rank(x):
    """Each subnet's position at each time, from 0 (lowest) to 1 (highest)."""
    return x.rank(axis=1, pct=True)
