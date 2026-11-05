"""The practice game: the real competition, alone, on live subnet prices.

    python scripts/practice.py --strategy strategies/example_strategy.py
    python scripts/practice.py --weights strategies/my_weights.json

--strategy takes a Python file defining strategy(market), as in the notebook. --weights
takes a JSON file of hand-picked weights. Both files are read again at every deadline
(:00, :15, :30, :45 UTC), so you can edit them while the game runs: changes apply from
the next round. A dashboard opens in your browser, with the 50 subnets you can pick.
Stop with Ctrl+C.
"""

import argparse
import runpy
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from subnet_trading.live import ARCHIVE_URL, Chain, History, backfill  # noqa: E402
from subnet_trading.practice import Practice, from_file, from_python_file  # noqa: E402


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--strategy", metavar="FILE", help="a Python file defining strategy(market)")
    source.add_argument("--weights", metavar="FILE", help="a JSON file of hand-picked weights")
    parser.add_argument("--history-hours", type=float, default=24, metavar="H",
                        help="hours of recent prices loaded at start, for your signals (default: 24)")
    parser.add_argument("--rounds", type=int, metavar="N", help="stop after N deadlines (default: run until Ctrl+C)")
    parser.add_argument("--dashboard", default="practice.html", metavar="FILE",
                        help="where to write the dashboard (default: practice.html)")
    parser.add_argument("--url", default=ARCHIVE_URL, help=f"the chain node to read (default: {ARCHIVE_URL})")
    args = parser.parse_args(argv)
    if args.strategy and "strategy" not in runpy.run_path(args.strategy):  # fail now, not at the first deadline
        parser.error(f"{args.strategy} must define a function strategy(market)")
    return args


def main():
    args = parse()
    strategy = from_file(args.weights) if args.weights else from_python_file(args.strategy)
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
