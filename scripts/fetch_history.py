"""Build data/history_5min.csv.gz from the Taoswap API: every subnet, every 5 minutes, up to now.

    python scripts/fetch_history.py              # the last 30 days: about 260 requests, a few minutes
    python scripts/fetch_history.py --days 90
    python scripts/fetch_history.py --genesis    # since each subnet's first candle: about 20 requests a subnet

The same columns as data/history_15min.csv.gz, so load(HISTORY_5MIN_FILE) reads it: time,
netuid, price, tao_in, alpha_in, alpha_out, life (subnet_trading.taoswap.history_rows says
where each comes from). The holder counts of the days it covers go into
data/holders_daily.csv.gz, next to the ones already there.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from subnet_trading.data import HISTORY_5MIN_FILE, HOLDERS_FILE  # noqa: E402
from subnet_trading.taoswap import Taoswap, history_rows, holder_rows  # noqa: E402


def main(days, genesis, out, holders_path):
    api = Taoswap()
    now = pd.Timestamp.now(tz="UTC").floor("5min")
    start = 0 if genesis else now - pd.Timedelta(days=days)
    subnets = sorted((s for s in api.subnets() if int(s["id"]) != 0), key=lambda s: int(s["id"]))
    histories, holders = [], []
    for i, subnet in enumerate(subnets, 1):
        netuid = int(subnet["id"])
        candles = api.candles(netuid, "5", start=start, end=now)
        first = candles["time"].min() if len(candles) else now
        daily = api.daily(netuid, start=first - pd.Timedelta(days=1), end=now)
        histories.append(history_rows(netuid, candles, daily, subnet.get("registered_at"), now))
        holders.append(holder_rows(netuid, daily))
        if i % 16 == 0 or i == len(subnets):
            print(f"  {i}/{len(subnets)} subnets, {api.requests} requests")

    history = pd.concat([h for h in histories if len(h)], ignore_index=True).sort_values(["time", "netuid"])
    history.to_csv(out, index=False, float_format="%.10g", date_format="%Y-%m-%dT%H:%M:%SZ")
    frames = [h for h in holders if len(h)]
    if Path(holders_path).exists():
        frames.insert(0, pd.read_csv(holders_path, parse_dates=["date"]))
    new = pd.concat(frames, ignore_index=True)
    new["date"] = pd.to_datetime(new["date"])
    new = new.drop_duplicates(["date", "netuid"], keep="last").sort_values(["date", "netuid"])
    new.astype({"netuid": int, "holders": int}).to_csv(holders_path, index=False, date_format="%Y-%m-%d")
    print(f"{out}: {history['time'].nunique():,} times, {history['netuid'].nunique()} subnets, "
          f"{history['time'].min():%Y-%m-%d %H:%M} to {history['time'].max():%Y-%m-%d %H:%M} UTC; "
          f"{holders_path}: {len(new):,} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--days", type=float, default=30, help="days of history up to now (default: 30)")
    window.add_argument("--genesis", action="store_true", help="from each subnet's first candle")
    parser.add_argument("--out", default=str(HISTORY_5MIN_FILE), help="the history file to write")
    parser.add_argument("--holders", default=str(HOLDERS_FILE), help="the holder counts file to complete")
    args = parser.parse_args()
    main(args.days, args.genesis, args.out, args.holders)
