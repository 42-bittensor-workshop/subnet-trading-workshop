"""Build data/ from raw pool snapshots and daily holder counts.

    python scripts/build_data.py --pools RAW_POOLS_15MIN.csv.gz --daily-panel DAILY_PANEL.csv

--pools: one row per subnet per snapshot, with the columns netuid, timestamp,
block_number, price, total_tao, alpha_in_pool, alpha_staked (TaoStats pool history:
amounts in rao, price in TAO). --daily-panel: one row per subnet per day with holders_count.

Writes:
    data/history_15min.csv.gz  time, netuid, price, tao_in, alpha_in, alpha_out, life
    data/holders_daily.csv.gz  date, netuid, holders

Cleaning rules (data/README.md):
    1. Root (netuid 0) is dropped. Amounts are converted from rao to TAO or alpha.
    2. A subnet number given to a new subnet starts a new `life`: the snapshot where
       its alpha outside the pool falls by more than half. Price moves across two
       lives are never used.
    3. Nothing is filled in.
"""

import argparse
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
RAO = 1e9


def build_history(raw):
    raw = raw[raw["netuid"] != 0].copy()
    if raw.duplicated(["block_number", "netuid"]).any():
        raise SystemExit("two rows for the same subnet and block")
    per_block = raw.groupby("block_number")["netuid"].nunique()
    if per_block.nunique() != 1:
        raise SystemExit(f"blocks hold different numbers of subnets: {per_block.value_counts().to_dict()}")

    block_time = pd.to_datetime(raw.groupby("block_number")["timestamp"].first(), utc=True)
    out = pd.DataFrame({
        "time": raw["block_number"].map(block_time),
        "netuid": raw["netuid"],
        "price": raw["price"],
        "tao_in": raw["total_tao"] / RAO,
        "alpha_in": raw["alpha_in_pool"] / RAO,
        "alpha_out": raw["alpha_staked"] / RAO,
    }).sort_values(["netuid", "time"]).reset_index(drop=True)

    falls = out.groupby("netuid")["alpha_out"].pct_change(fill_method=None) < -0.5
    out["life"] = falls.astype(int).groupby(out["netuid"]).cumsum()
    if (out["price"] <= 0).any():
        raise SystemExit("a price at or below zero")
    return out, int(falls.sum())


def build_holders(panel, start, end):
    days = panel[(panel["date"] >= start) & (panel["date"] <= end) & (panel["netuid"] != 0)]
    return days.rename(columns={"holders_count": "holders"})[["date", "netuid", "holders"]].dropna()


def main(raw_path, panel_path):
    history, lives = build_history(pd.read_csv(raw_path))
    first, last = history["time"].min(), history["time"].max()
    panel = pd.read_csv(panel_path, usecols=["date", "netuid", "holders_count"], parse_dates=["date"])
    holders = build_holders(panel, (first - pd.Timedelta(days=1)).strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d"))

    (REPO / "data").mkdir(exist_ok=True)
    history.to_csv(REPO / "data" / "history_15min.csv.gz", index=False, float_format="%.10g",
                   date_format="%Y-%m-%dT%H:%M:%SZ")
    holders.to_csv(REPO / "data" / "holders_daily.csv.gz", index=False, date_format="%Y-%m-%d")
    print(f"history: {history['time'].nunique()} snapshots, {history['netuid'].nunique()} subnets, "
          f"{first} to {last}; {lives} new lives")
    print(f"holders: {len(holders)} rows, {holders['date'].nunique()} days")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pools", required=True, metavar="FILE", help="raw pool snapshots, every 15 minutes")
    parser.add_argument("--daily-panel", required=True, metavar="FILE", help="daily rows with holders_count")
    args = parser.parse_args()
    main(args.pools, args.daily_panel)
