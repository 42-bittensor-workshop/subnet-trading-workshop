"""Run the event's validator (subnet_trading/validator.py explains each step).

    pip install -e ".[validator]"
    python scripts/validator.py --wallet owner --hotkey validator --netuid NETUID
    python scripts/validator.py --netuid NETUID --off-chain --anyone    # a rehearsal: nothing set on chain

Prices: every subnet's pool on Bittensor's main chain, read at each step. At start, the
market served to miners is filled with the last hours of Taoswap's 5-minute candles (with
today's pools for those hours). Weights go on chain on the testnet subnet every other round:
a subnet allows them once every 100 blocks (20 minutes) and only root can lower that. The
validator's hotkey must be registered on the subnet, with some stake, or its weights count
for nothing.
"""

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from subnet_trading.live import Chain  # noqa: E402
from subnet_trading.taoswap import Taoswap, backfill_snapshots  # noqa: E402
from subnet_trading.validator import Validator, serve  # noqa: E402

FINNEY_URL = "wss://entrypoint-finney.opentensor.ai:443"


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--netuid", type=int, required=True, help="the event's subnet")
    parser.add_argument("--network", default="test", help="where the subnet lives (default: test)")
    parser.add_argument("--wallet", default="default", help="wallet name (default: default)")
    parser.add_argument("--hotkey", default="default", help="the validator's hotkey (default: default)")
    parser.add_argument("--wallet-path", help="wallets folder (default: ~/.bittensor/wallets)")
    parser.add_argument("--exclude", nargs="*", default=[], metavar="HOTKEY",
                        help="registered hotkeys that do not play, e.g. the subnet owner's (the validator's own is left out)")
    parser.add_argument("--port", type=int, default=8000, help="the port miners call (default: 8000)")
    parser.add_argument("--state", default="validator_state.json", help="accounts, saved after every round")
    parser.add_argument("--weights-every", type=int, default=2, metavar="N",
                        help="set the ranking on chain every N rounds (default: 2, every 30 minutes)")
    parser.add_argument("--backfill-hours", type=float, default=24, metavar="H",
                        help="hours of 5-minute prices from Taoswap at start (default: 24, 0 for none)")
    parser.add_argument("--prices-url", default=FINNEY_URL, help=f"main chain node for prices (default: {FINNEY_URL})")
    parser.add_argument("--off-chain", action="store_true", help="score and serve, but set nothing on chain")
    parser.add_argument("--anyone", action="store_true", help="accept any hotkey, registered or not (rehearsals)")
    return parser.parse_args(argv)


def main():
    args = parse()
    from bittensor_wallet import Keypair

    def verify(hotkey, data, signature):
        try:
            return Keypair(ss58_address=hotkey).verify(data, bytes.fromhex(signature.removeprefix("0x")))
        except Exception:  # noqa: BLE001  a malformed address or signature is a bad signature
            return False

    registered, set_weights = None, None
    if not (args.anyone and args.off_chain):
        import bittensor as bt
        from bittensor_wallet import Wallet

        wallet = Wallet(name=args.wallet, hotkey=args.hotkey, path=args.wallet_path)
        excluded = {wallet.hotkey.ss58_address, *args.exclude}
        reader, writer = bt.Subtensor(network=args.network), bt.Subtensor(network=args.network)  # one connection per thread
        hotkeys = list(reader.metagraph(args.netuid).hotkeys)
        if wallet.hotkey.ss58_address not in hotkeys:
            print(f"warning: {wallet.hotkey.ss58_address} is not registered on subnet {args.netuid}: "
                  f"weights cannot be set on chain")

        def refresh():
            nonlocal hotkeys
            while True:
                time.sleep(300)
                try:
                    hotkeys = list(reader.metagraph(args.netuid).hotkeys)
                except Exception as error:  # noqa: BLE001  keep the last list until the chain answers
                    print(f"metagraph not refreshed: {error}")

        threading.Thread(target=refresh, daemon=True).start()
        if not args.anyone:
            registered = lambda: set(hotkeys) - excluded  # noqa: E731

        def put_on_chain(weights):
            uid_of = {hotkey: uid for uid, hotkey in enumerate(hotkeys)}
            pairs = [(uid_of[h], w) for h, w in weights.items() if h in uid_of]
            if not pairs:
                return
            response = writer.set_weights(wallet=wallet, netuid=args.netuid, uids=[u for u, _ in pairs],
                                          weights=[w for _, w in pairs], mev_protection=False,
                                          wait_for_inclusion=True, wait_for_finalization=False)
            if not response[0]:
                raise RuntimeError(response[1])

        if not args.off_chain:
            set_weights = put_on_chain

    chain = Chain(args.prices_url)
    validator = Validator(chain, set_weights=set_weights, registered=registered, state=args.state,
                          weights_every=args.weights_every)
    first = chain.snapshot()
    if args.backfill_hours > 0:
        print(f"Loading the last {args.backfill_hours:g} hours of 5-minute prices from Taoswap...")
        validator.preload(backfill_snapshots(Taoswap(), first["pools"], hours=args.backfill_hours))
    validator.preload([first])

    serve(validator, verify, port=args.port)
    print(f"Validator on port {args.port}: {len(validator.board.accounts)} accounts, "
          f"{'off chain' if set_weights is None else f'weights on subnet {args.netuid} ({args.network})'}. "
          f"Stop with Ctrl+C.")
    try:
        validator.play()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
