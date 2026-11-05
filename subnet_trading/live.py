"""Live subnet data, read directly from the Bittensor chain (no key needed).

One chain call returns every subnet's pool: TAO in the pool, alpha in the pool, alpha
outside it. The price is TAO in the pool divided by alpha in the pool. Past blocks
are read from the public archive node, so a session can start with recent history.
Holder counts are not on chain: in live mode, `market.holders` is empty.
"""

import time
from datetime import datetime, timezone

import pandas as pd

from .data import Market

ARCHIVE_URL = "wss://archive.chain.opentensor.ai:443"
SECONDS_PER_BLOCK = 12
RAO = 1e9


class Chain:
    """A connection to a Bittensor node, reconnecting when a call fails."""

    def __init__(self, url=ARCHIVE_URL):
        self.url = url
        self._substrate = None

    def _call(self, op, *args, **kwargs):
        last = None
        for attempt in range(4):
            try:
                if self._substrate is None:
                    from async_substrate_interface import SubstrateInterface
                    self._substrate = SubstrateInterface(self.url, max_retries=2, retry_timeout=15.0)
                return getattr(self._substrate, op)(*args, **kwargs)
            except Exception as error:  # noqa: BLE001  a dropped connection or a timeout
                last = error
                self._substrate = None
                time.sleep(2 * (attempt + 1))
        raise last

    def head(self):
        return int(self._call("get_block_number", None))

    def snapshot(self, block=None):
        """Every subnet's pool at `block` (default: the latest block)."""
        block = self.head() if block is None else int(block)
        block_hash = self._call("get_block_hash", block)
        rows = self._call("runtime_call", "SubnetInfoRuntimeApi", "get_all_dynamic_info", [],
                          block_hash=block_hash)
        rows = getattr(rows, "value", rows)
        rows = rows[0] if isinstance(rows, tuple) else rows
        stamp = self._call("query", "Timestamp", "Now", [], block_hash=block_hash)
        stamp = int(getattr(stamp, "value", stamp))
        return snapshot_from_rows(rows, block, stamp)


def snapshot_from_rows(rows, block, timestamp_ms):
    """Turn the chain's pool rows into one snapshot: a time and a table by netuid."""
    pools = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("netuid") in (None, 0):
            continue
        tao_in, alpha_in = int(row.get("tao_in") or 0) / RAO, int(row.get("alpha_in") or 0) / RAO
        if tao_in <= 0 or alpha_in <= 0:
            continue
        pools[int(row["netuid"])] = {"price": tao_in / alpha_in, "tao_in": tao_in, "alpha_in": alpha_in,
                                     "alpha_out": int(row.get("alpha_out") or 0) / RAO}
    time_ = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return {"time": pd.Timestamp(time_), "block": block, "pools": pd.DataFrame.from_dict(pools, orient="index")}


class History:
    """Snapshots collected over a session, turned into a Market for strategies."""

    def __init__(self):
        self.snapshots = []

    def add(self, snapshot):
        if self.snapshots and snapshot["time"] <= self.snapshots[-1]["time"]:
            return
        self.snapshots.append(snapshot)

    def market(self):
        times = [s["time"] for s in self.snapshots]

        def table(field):
            return pd.DataFrame([s["pools"][field] for s in self.snapshots], index=times).sort_index(axis=1)

        alpha_out = table("alpha_out")
        new_life = alpha_out.pct_change(fill_method=None) < -0.5
        return Market(price=table("price"), tao_in=table("tao_in"), alpha_in=table("alpha_in"),
                      alpha_out=alpha_out, holders=alpha_out * float("nan"), life=new_life.cumsum())


def backfill(chain, hours, step_minutes=15, progress=print):
    """Snapshots every `step_minutes` over the last `hours`, oldest first."""
    head = chain.head()
    steps = int(hours * 60 // step_minutes)
    blocks = [head - k * step_minutes * 60 // SECONDS_PER_BLOCK for k in range(steps, 0, -1)]
    snaps = []
    for i, block in enumerate(blocks, 1):
        snaps.append(chain.snapshot(block))
        if i % 12 == 0 or i == len(blocks):
            progress(f"  history: {i}/{len(blocks)} snapshots")
    return snaps
