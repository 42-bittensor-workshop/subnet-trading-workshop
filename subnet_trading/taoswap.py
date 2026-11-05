"""Subnet prices from the Taoswap API (https://api.taoswap.org): public, no key needed.

    from subnet_trading.taoswap import Taoswap

    api = Taoswap()
    api.candles(64, "5", start="2026-11-01")   # subnet 64, 5-minute candles since November 1st
    api.candles(64, "60", start=0)             # every hourly candle since the subnet's first one
    api.recent(64, "1", 60)                    # the last 60 one-minute candles, the newest still forming
    api.subnets()                              # every subnet now: price, pool, registration
    api.daily(64, "2026-10-01")                # one row a day: pool, holders...

Limits apply per IP address: about 10 requests a second, and a few hundred refused
requests within ten minutes ban the address for an hour. This client spaces its requests
and waits as long as the API asks when one is refused. A classroom shares one address,
so students read prices from the validator, never all from the API.
"""

import gzip
import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

BASE_URL = "https://api.taoswap.org"
RESOLUTIONS = {"1": 60, "5": 300, "15": 900, "30": 1800, "60": 3600, "240": 14400, "D": 86400, "W": 604800}
MAX_LIMIT = 10_000
CANDLE_COLUMNS = ["time", "open", "high", "low", "close", "volume"]
HISTORY_COLUMNS = ["time", "netuid", "price", "tao_in", "alpha_in", "alpha_out", "life"]
FIVE_MINUTES = pd.Timedelta(minutes=5)


class TaoswapError(RuntimeError):
    pass


def utc(value):
    """A UTC timestamp from a date or time string, a datetime, or UNIX seconds."""
    if isinstance(value, (int, float)):
        return pd.Timestamp(value, unit="s", tz="UTC")
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def epoch_seconds(value):
    return None if value is None else int(utc(value).timestamp())


def _retry_after(error):
    try:
        return max(1, int(float(error.headers.get("Retry-After"))))
    except (AttributeError, TypeError, ValueError):
        return None


class Taoswap:
    """GET requests to the API, spaced by `min_interval` seconds, retried when it is busy."""

    def __init__(self, base_url=BASE_URL, min_interval=0.25, timeout=30, retries=5,
                 urlopen=urllib.request.urlopen, sleep=time.sleep, clock=time.monotonic):
        self.base_url = base_url.rstrip("/")
        self.min_interval, self.timeout, self.retries = min_interval, timeout, retries
        self.urlopen, self.sleep, self.clock = urlopen, sleep, clock
        self.requests = 0
        self._last = None

    def _pace(self):
        if self._last is not None:
            wait = self.min_interval - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()

    def get(self, path, **params):
        """One GET, decoded from JSON; parameters set to None are left out."""
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(url, headers={
            "Accept": "application/json", "Accept-Encoding": "gzip", "User-Agent": "subnet-trading-workshop"})
        for attempt in range(self.retries + 1):
            self._pace()
            self.requests += 1
            try:
                with self.urlopen(request, timeout=self.timeout) as response:
                    body = response.read()
                    if (response.headers.get("Content-Encoding") or "").lower() == "gzip":
                        body = gzip.decompress(body)
                    return json.loads(body)
            except urllib.error.HTTPError as error:
                # 429: the API says how long to wait; the proxy in front of it does not, so back off.
                if (error.code != 429 and error.code < 500) or attempt == self.retries:
                    raise TaoswapError(f"GET {url}: HTTP {error.code}") from None
                self.sleep(_retry_after(error) or min(120, 5 * 2 ** attempt))
            except (OSError, http.client.HTTPException) as error:  # no answer, a timeout, a cut connection
                if attempt == self.retries:
                    raise TaoswapError(f"GET {url}: {error}") from None
                self.sleep(min(120, 5 * 2 ** attempt))
        raise TaoswapError(f"GET {url}: no answer")

    def subnets(self):
        """Every subnet now, root included: price, alpha_in_pool, alpha_stake, registered_at..."""
        return self.get("/v2/subnets/")["results"]

    def candles(self, netuid, resolution="5", start=None, end=None, page=MAX_LIMIT):
        """One subnet's candles, oldest first: `time` (UTC) opens each candle, prices are in TAO
        per alpha and `volume` is the TAO swapped. start=0 reads from the subnet's first candle;
        without `start`, the newest `page` candles up to `end` (default: now). The newest candle
        may still be forming."""
        if resolution not in RESOLUTIONS:
            raise ValueError(f"resolution must be one of {', '.join(RESOLUTIONS)}")
        step, lo, hi = RESOLUTIONS[resolution], epoch_seconds(start), epoch_seconds(end)
        params = {"netuid": int(netuid), "resolution": resolution, "to": hi, "limit": page}
        if lo is None:
            return candle_frame(self.get("/subnet-price-history/", **params)["results"])
        rows = []
        while hi is None or lo <= hi:
            batch = self.get("/subnet-price-history/", **params, **{"from": lo})["results"]
            rows += batch
            if len(batch) < page:
                break
            lo = int(batch[-1]["time"]) + step
        return candle_frame(rows)

    def recent(self, netuid, resolution="1", count=60):
        """The newest `count` candles of one subnet; the last one is still forming."""
        return self.candles(netuid, resolution, page=count)

    def daily(self, netuid, start=None, end=None):
        """One subnet's history, a row a day since its current registration: tao_in_pool,
        alpha_in_pool, alpha_stake, holders_count... Today's row covers the day so far."""
        day = lambda value: None if value is None else f"{utc(value):%Y-%m-%d}"  # noqa: E731
        params = {"date_from": day(start), "date_to": day(end)} if start is not None or end is not None else {"days": "all"}
        frame = pd.DataFrame(self.get(f"/v2/subnets/{int(netuid)}/history/", **params)["results"])
        if len(frame):
            frame["date"] = pd.to_datetime(frame["date"])
        return frame


def candle_frame(rows):
    """Candles as a table, one row per candle, oldest first, `time` as UTC timestamps."""
    frame = pd.DataFrame(rows, columns=CANDLE_COLUMNS)
    frame["time"] = pd.to_datetime(frame["time"].astype("int64"), unit="s", utc=True)
    return frame.drop_duplicates("time", keep="last").sort_values("time").reset_index(drop=True)


def history_rows(netuid, candles, daily, registered_at=None, now=None):
    """One subnet's rows for a history file, in the columns load() reads.

    - time: the end of each complete 5-minute candle; price: its close, the price at that time.
    - tao_in, alpha_in, alpha_out: the pool on the day before the candle's (from `daily`), so
      no row holds anything from its future. A daily pool is enough to pick the 50 largest.
    - life: 1 from the subnet's current registration on when it falls inside the rows, else 0.
    """
    now = pd.Timestamp.now(tz="UTC") if now is None else utc(now)
    opens = candles["time"]
    rows = pd.DataFrame({"time": opens + FIVE_MINUTES, "netuid": int(netuid),
                         "price": candles["close"].astype(float)})
    keep = (rows["time"] <= now) & (rows["price"] > 0)
    rows, opens = rows[keep].reset_index(drop=True), opens[keep].reset_index(drop=True)

    columns = ["tao_in_pool", "alpha_in_pool", "alpha_stake"]
    pools = pd.DataFrame(columns=columns, index=pd.DatetimeIndex([]), dtype=float)
    if len(daily):
        pools = daily.drop_duplicates("date", keep="last").set_index("date").reindex(columns=columns).astype(float)
    pools.index = pd.DatetimeIndex(pools.index).as_unit("ns")
    day_before = pd.DatetimeIndex(opens.dt.tz_convert(None).dt.normalize() - pd.Timedelta(days=1)).as_unit("ns")
    known = pools.reindex(day_before)
    rows["tao_in"] = known["tao_in_pool"].to_numpy()
    rows["alpha_in"] = known["alpha_in_pool"].to_numpy()
    rows["alpha_out"] = known["alpha_stake"].to_numpy()

    rows["life"] = 0
    if registered_at is not None and len(opens) and opens.iloc[0] < utc(registered_at):
        rows["life"] = (opens >= utc(registered_at)).astype(int).to_numpy()
    return rows[HISTORY_COLUMNS]


def holder_rows(netuid, daily):
    """One subnet's holder counts, a row a day (date, netuid, holders)."""
    if not len(daily) or "holders_count" not in daily:
        return pd.DataFrame(columns=["date", "netuid", "holders"])
    rows = pd.DataFrame({"date": daily["date"], "netuid": int(netuid), "holders": daily["holders_count"]})
    return rows.dropna()


def backfill_snapshots(api, pools, hours=24, end=None):
    """Snapshots every 5 minutes over the last `hours` hours for the subnets of `pools` (a live
    snapshot's table): prices from the 5-minute candles, pools as they are now."""
    end = pd.Timestamp.now(tz="UTC").floor("5min") if end is None else utc(end)
    start = end - pd.Timedelta(hours=hours)
    closes = {}
    for netuid in pools.index:
        frame = api.candles(int(netuid), "5", start=start, end=end)
        frame = frame[frame["time"] + FIVE_MINUTES <= end]
        closes[int(netuid)] = pd.Series(frame["close"].astype(float).to_numpy(), index=frame["time"] + FIVE_MINUTES)
    prices = pd.DataFrame(closes).sort_index()
    snapshots = []
    for t, row in prices.iterrows():
        table = pools[["tao_in", "alpha_in", "alpha_out"]].copy()
        table.insert(0, "price", row.reindex(table.index).to_numpy())
        snapshots.append({"time": t, "block": None, "pools": table.dropna(subset=["price"])})
    return snapshots
