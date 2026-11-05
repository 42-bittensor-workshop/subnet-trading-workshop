import gzip
import json
import urllib.error
import urllib.parse

import pandas as pd
import pytest

from subnet_trading import config
from subnet_trading.data import HISTORY_5MIN_FILE, load
from subnet_trading.taoswap import Taoswap, TaoswapError, backfill_snapshots, history_rows, holder_rows

DAY = 86400
T0 = int(pd.Timestamp("2026-11-03", tz="UTC").timestamp())  # the subnet's first candle


def close(t):
    return 1 + (t - T0) / 60 / 1e4


class Answer:
    def __init__(self, payload):
        self.body, self.headers = gzip.compress(json.dumps(payload).encode()), {"Content-Encoding": "gzip"}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeAPI:
    """Serves 5-minute candles from T0 for one day, as /subnet-price-history/ does."""

    def __init__(self, refuse=0, status=429):
        self.urls, self.refuse, self.status = [], refuse, status

    def __call__(self, request, timeout=None):
        self.urls.append(request.full_url)
        if self.refuse:
            self.refuse -= 1
            raise urllib.error.HTTPError(request.full_url, self.status, "refused", {"Retry-After": "7"}, None)
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(request.full_url).query))
        times = [t for t in range(T0, T0 + DAY, 300) if t <= int(query.get("to", 10**10))]
        limit = int(query["limit"])
        picked = [t for t in times if t >= int(query["from"])][:limit] if "from" in query else times[-limit:]
        return Answer({"results": [{"time": t, "open": close(t), "high": close(t), "low": close(t),
                                    "close": close(t), "volume": 1.0} for t in picked]})


def froms(api):
    return [int(dict(urllib.parse.parse_qsl(urllib.parse.urlparse(u).query))["from"]) for u in api.urls]


def test_candles_since_genesis_come_page_after_page():
    fake = FakeAPI()
    candles = Taoswap(urlopen=fake, sleep=lambda _: None).candles(64, "5", start=0, page=100)
    assert len(candles) == 288 and candles["time"].is_monotonic_increasing
    assert candles["time"].iloc[0] == pd.Timestamp(T0, unit="s", tz="UTC")
    assert froms(fake) == [0, T0 + 100 * 300, T0 + 200 * 300]


def test_newest_candles_without_a_start():
    candles = Taoswap(urlopen=FakeAPI(), sleep=lambda _: None).recent(64, "5", count=3)
    assert list(candles["close"]) == pytest.approx([close(T0 + DAY - k * 300) for k in (3, 2, 1)])


def test_a_refused_request_waits_as_long_as_the_api_asks():
    waits = []
    api = Taoswap(urlopen=FakeAPI(refuse=1), sleep=waits.append, clock=lambda: 0.0)
    assert len(api.recent(64, "5", count=2)) == 2
    assert 7 in waits and api.requests == 2


def test_a_wrong_request_is_not_retried():
    api = Taoswap(urlopen=FakeAPI(refuse=1, status=400), sleep=lambda _: None)
    with pytest.raises(TaoswapError, match="HTTP 400"):
        api.recent(64, "5")
    assert api.requests == 1


def candles_from(start, count):
    times = pd.date_range(start, periods=count, freq="5min", tz="UTC")
    return pd.DataFrame({"time": times, "open": 1.0, "high": 1.0, "low": 1.0,
                         "close": [1 + k / 100 for k in range(count)], "volume": 0.0})


DAILY = pd.DataFrame({"date": pd.to_datetime(["2026-11-02", "2026-11-03", "2026-11-04"]),
                      "tao_in_pool": [100.0, 200.0, 300.0], "alpha_in_pool": [10.0, 20.0, 30.0],
                      "alpha_stake": [1.0, 2.0, 3.0], "holders_count": [5, 6, 7]})


def test_history_rows_hold_nothing_from_their_future():
    candles = candles_from("2026-11-03 23:50", 4)          # opens 23:50, 23:55, 00:00, 00:05
    rows = history_rows(64, candles, DAILY, now="2026-11-04 00:10")
    assert list(rows["time"]) == list(candles["time"][:4] + pd.Timedelta(minutes=5))
    assert list(rows["price"]) == list(candles["close"])
    # a candle that opens on November 3 gets the pool of November 2, one that opens on the 4th that of the 3rd
    assert list(rows["tao_in"]) == [100.0, 100.0, 200.0, 200.0]
    assert list(rows["alpha_out"]) == [1.0, 1.0, 2.0, 2.0]
    assert (rows["netuid"] == 64).all() and (rows["life"] == 0).all()


def test_a_forming_candle_is_left_out():
    rows = history_rows(64, candles_from("2026-11-04 00:00", 3), DAILY, now="2026-11-04 00:12")
    assert len(rows) == 2


def test_a_new_registration_starts_a_new_life():
    rows = history_rows(64, candles_from("2026-11-04 00:00", 4), DAILY, "2026-11-04T00:10:00Z", now="2026-11-05")
    assert list(rows["life"]) == [0, 0, 1, 1]


def test_holder_rows():
    rows = holder_rows(64, DAILY)
    assert list(rows["holders"]) == [5, 6, 7] and (rows["netuid"] == 64).all()


def test_backfill_snapshots_use_candle_prices_and_todays_pools():
    pools = pd.DataFrame({"price": [9.0, 9.0], "tao_in": [500.0, 400.0], "alpha_in": [50.0, 40.0],
                          "alpha_out": [5.0, 4.0]}, index=[64, 8])
    end = pd.Timestamp(T0 + 2 * 3600, unit="s", tz="UTC")
    snapshots = backfill_snapshots(Taoswap(urlopen=FakeAPI(), sleep=lambda _: None), pools, hours=1, end=end)
    assert [s["time"] for s in snapshots] == list(pd.date_range(end - pd.Timedelta(minutes=55), end, freq="5min"))
    last = snapshots[-1]["pools"]
    assert last.loc[64, "price"] == pytest.approx(close(T0 + 2 * 3600 - 300))
    assert last.loc[8, "tao_in"] == 400.0


@pytest.mark.skipif(not HISTORY_5MIN_FILE.exists(), reason="data/history_5min.csv.gz not fetched yet")
def test_the_5_minute_history_loads():
    market = load(HISTORY_5MIN_FILE)
    assert market.bar_minutes == 5
    assert len(market.universe()) == config.UNIVERSE_SIZE
