"""Subnet candles from the Taoswap API: live as they form, or every one since the subnet's first.

    python examples/taoswap_candles.py 64                                     # subnet 64, 1-minute candles, live
    python examples/taoswap_candles.py 64 --plot sn64.png                     # the same, and a chart redrawn at each read
    python examples/taoswap_candles.py 64 --resolution 60 --genesis --plot sn64_hourly.png --out sn64_hourly.csv

No key needed. Candles are cached 15 seconds on the API's side, so reading more often
brings nothing new, and one address may send about 10 requests a second. Resolutions: 1, 5,
15, 30, 60 and 240 minutes, D (a day) or W (a week, from Monday). A chart shows one
candlestick per candle up to 300 of them, and beyond that the close inside its high-low range.
"""

import argparse
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # charts go to files, no window needed
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from subnet_trading.plots import plot_candles  # noqa: E402
from subnet_trading.taoswap import RESOLUTIONS, Taoswap  # noqa: E402

WIDTHS = {"1": "1-minute", "5": "5-minute", "15": "15-minute", "30": "30-minute", "60": "hourly",
          "240": "4-hour", "D": "daily", "W": "weekly"}


def show(candle, forming=False):
    print(f"{candle['time']:%Y-%m-%d %H:%M} UTC  open {candle['open']:.6f}  high {candle['high']:.6f}  "
          f"low {candle['low']:.6f}  close {candle['close']:.6f}  volume {candle['volume']:,.2f} TAO"
          + ("  (forming)" if forming else ""))


def chart(candles, netuid, resolution, path):
    fig = plot_candles(candles, f"Subnet {netuid}, {WIDTHS[resolution]} candles, price in TAO per alpha")
    fig.savefig(path, dpi=150)
    plt.close(fig)


def live(api, netuid, resolution, every, plot=None):
    """The last candles, then the forming one each time it moves, and each one as it closes;
    with `plot`, a chart of the last 120 redrawn at each read."""
    printed = {}
    while True:
        candles = api.recent(netuid, resolution, count=120 if plot else 10)
        latest = candles.tail(10).to_dict("records")
        for i, candle in enumerate(latest):
            forming = i == len(latest) - 1
            if printed.get(candle["time"]) != (candle["close"], forming):
                show(candle, forming)
                printed[candle["time"]] = (candle["close"], forming)
        for old in sorted(printed)[:-20]:
            del printed[old]
        if plot:
            chart(candles, netuid, resolution, plot)
        time.sleep(every)


def since_genesis(api, netuid, resolution, out=None, plot=None):
    """Every candle since the subnet's first one: start=0, then as many requests as needed."""
    candles = api.candles(netuid, resolution, start=0)
    print(f"subnet {netuid}: {len(candles):,} candles of {resolution}, from {candles['time'].iloc[0]:%Y-%m-%d %H:%M} "
          f"to {candles['time'].iloc[-1]:%Y-%m-%d %H:%M} UTC, in {api.requests} requests")
    if out:
        candles.to_csv(out, index=False)
        print(f"written to {out}")
    if plot:
        chart(candles, netuid, resolution, plot)
        print(f"chart in {plot}")
    if not (out or plot):
        print(candles.tail(5).to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("netuid", type=int)
    parser.add_argument("--resolution", default="1", choices=list(RESOLUTIONS), help="candle width (default: 1 minute)")
    parser.add_argument("--genesis", action="store_true", help="every candle since the subnet's first, then stop")
    parser.add_argument("--out", help="with --genesis: a CSV file to write")
    parser.add_argument("--plot", metavar="PNG", help="draw the candles in this image file")
    parser.add_argument("--every", type=float, default=15, help="seconds between two reads, live (default: 15)")
    args = parser.parse_args()
    api = Taoswap()
    if args.genesis:
        since_genesis(api, args.netuid, args.resolution, args.out, args.plot)
    else:
        try:
            live(api, args.netuid, args.resolution, args.every, args.plot)
        except KeyboardInterrupt:
            pass
