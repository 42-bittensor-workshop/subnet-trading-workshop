"""Run your miner at the event.

    pip install -e ".[miner]"
    python scripts/miner.py --validator http://VALIDATOR:8000 --wallet me --strategy strategies/example_strategy.py
    python scripts/miner.py --validator http://VALIDATOR:8000 --wallet me --weights strategies/my_weights.json

30 seconds before each deadline (:00, :15, :30 and :45 UTC), it reads the market from the
validator, runs your strategy and sends the weights, signed with your hotkey. The strategy
file is read again at every deadline, so your edits apply from the next round. Stop with
Ctrl+C.
"""

import argparse
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from subnet_trading.event import connect  # noqa: E402
from subnet_trading.miner import run  # noqa: E402
from subnet_trading.practice import from_file, from_python_file  # noqa: E402


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--validator", required=True, metavar="URL", help="the validator's address, given by the organisers")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--strategy", metavar="FILE", help="a Python file defining strategy(market)")
    source.add_argument("--weights", metavar="FILE", help="a JSON file of hand-picked weights")
    parser.add_argument("--wallet", default="default", help="your wallet's name (default: default)")
    parser.add_argument("--hotkey", default="default", help="your hotkey's name (default: default)")
    parser.add_argument("--wallet-path", help="wallets folder (default: ~/.bittensor/wallets)")
    parser.add_argument("--hours", type=float, default=24, help="hours of market your strategy receives (default: 24)")
    parser.add_argument("--rounds", type=int, metavar="N", help="stop after N deadlines (default: run until Ctrl+C)")
    args = parser.parse_args(argv)
    if args.strategy and "strategy" not in runpy.run_path(args.strategy):  # fail now, not at the first deadline
        parser.error(f"{args.strategy} must define a function strategy(market)")
    return args


def main():
    args = parse()
    strategy = from_file(args.weights) if args.weights else from_python_file(args.strategy)
    get_market, send = connect(args.validator, args.wallet, args.hotkey, args.wallet_path, hours=args.hours)
    market = get_market()
    print(f"Miner {send.hotkey}: the validator answers, {len(market.times)} snapshots up to "
          f"{market.times[-1]:%H:%M} UTC. Weights go 30 seconds before every deadline. Stop with Ctrl+C.")
    try:
        run(strategy, get_market, send, rounds=args.rounds)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
