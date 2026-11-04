import numpy as np
import pandas as pd
import pytest

from conftest import make_market
from subnet_trading import change, config, delay, load, mean, rank, std, zscore
from subnet_trading.miner import next_weights, seconds_to_next_deadline


@pytest.fixture(scope="module")
def market():
    return load()


def test_history_loads(market):
    assert market.price.shape[1] == 128
    assert market.times.is_monotonic_increasing
    assert market.bar_minutes == 15
    assert all(len(market.universe(t)) == config.UNIVERSE_SIZE for t in market.times[::200])


def test_holders_are_from_the_day_before(market):
    daily = pd.read_csv("data/holders_daily.csv.gz", parse_dates=["date"])
    t = market.times[500]
    netuid = int(market.holders.loc[t].dropna().index[0])
    day_before = t.tz_convert(None).normalize() - pd.Timedelta(days=1)
    expected = daily[(daily["date"] == day_before) & (daily["netuid"] == netuid)]["holders"].iloc[0]
    assert market.holders.loc[t, netuid] == expected


def test_no_return_across_a_new_life(market):
    changed = market.life.diff().fillna(0) != 0
    t_index, netuid = np.argwhere(changed.to_numpy())[0]
    before, after = market.times[t_index - 1], market.times[t_index]
    assert np.isnan(market.returns(before, after).iloc[netuid])


@pytest.mark.parametrize("signal", [
    lambda x: change(x, "1h"), lambda x: delay(x, "1h"), lambda x: mean(x, "1h"),
    lambda x: std(x, "1h"), lambda x: zscore(x, "1h"), lambda x: rank(x),
])
def test_signals_never_use_the_future(signal):
    market = make_market()
    cut = market.times[30]
    changed = market.price.copy()
    changed.loc[changed.index > cut] *= 3
    pd.testing.assert_frame_equal(signal(market.price).loc[:cut], signal(changed).loc[:cut])


def test_windows_are_counted_in_time():
    market = make_market()
    pd.testing.assert_frame_equal(change(market.price, "1h"), change(market.price, 4))


def test_miner_sends_the_same_weights_as_the_backtest_would():
    market = make_market()
    weights = next_weights(lambda m: change(m.price, "1h"), market)
    latest = change(market.price, "1h").iloc[-1].reindex(market.universe()).nlargest(10)
    assert set(weights) == set(int(k) for k in latest.index)
    assert next_weights({1: 0.5, 2: 0.5}, market) == {1: 0.5, 2: 0.5}


def test_deadline_timer():
    from datetime import datetime, timezone
    now = datetime(2026, 11, 20, 10, 7, 0, tzinfo=timezone.utc)  # 8 minutes before 10:15
    assert seconds_to_next_deadline(now) == 8 * 60 - 30
