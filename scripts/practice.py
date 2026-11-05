"""The practice game: the real competition, alone, on live subnet prices.

    python scripts/practice.py strategies/example_strategy.py       your strategy file
    python scripts/practice.py --weights strategies/my_weights.json  hand-picked weights

A strategy file defines `strategy(market)`, as in the notebook. With --weights, edit the
JSON file whenever you like: it is read again at every deadline (:00, :15, :30, :45 UTC).
A dashboard opens in your browser. Stop with Ctrl+C.

Options:
    --rounds N           stop after N deadlines (default: run until stopped)
    --history-hours H    recent history loaded at start, for your signals (default: 24)
    --dashboard FILE     where to write the dashboard (default: practice.html)
"""

import argparse
import runpy
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from subnet_trading.live import ARCHIVE_URL, Chain, History, backfill  # noqa: E402
from subnet_trading.practice import Practice, from_file  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("strategy_file", nargs="?", help="a Python file defining strategy(market)")
    parser.add_argument("--weights", help="a JSON file of hand-picked weights")
    parser.add_argument("--rounds", type=int)
    parser.add_argument("--history-hours", type=float, default=24)
    parser.add_argument("--dashboard", default="practice.html")
    parser.add_argument("--url", default=ARCHIVE_URL)
    args = parser.parse_args()
    if bool(args.strategy_file) == bool(args.weights):
        parser.error("give either a strategy file or --weights")

    strategy = from_file(args.weights) if args.weights else runpy.run_path(args.strategy_file)["strategy"]
    chain, history = Chain(args.url), History()
    print(f"Loading the last {args.history_hours:g} hours of subnet prices from the chain...")
    for snapshot in backfill(chain, args.history_hours):
        history.add(snapshot)

    dashboard = Path(args.dashboard).resolve()
    practice = Practice(strategy, chain, history, dashboard=dashboard)
    practice.write_dashboard(None)
    webbrowser.open(dashboard.as_uri())
    print(f"Dashboard: {dashboard}. Waiting for the next deadline...")
    try:
        practice.play(args.rounds)
    except KeyboardInterrupt:
        print("\nStopped.")
    print(practice.standings().tail(10).to_string() if practice.rounds else "No round settled yet.")


if __name__ == "__main__":
    main()
