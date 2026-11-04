"""Your miner: every 15 minutes it turns your strategy into weights and sends them.

The event provides two things, plugged in when you start the miner:
    get_market()   the live market, in the same format as load() (a Market)
    send(weights)  delivers the weights to the validator

Your strategy is exactly what you tested in the backtest: fixed weights, a signal
function, or your own function. Example:

    from subnet_trading import *

    def my_signal(market):
        return change(market.price, "1h")

    run(my_signal, get_market, send)
"""

import time
from datetime import datetime, timezone

from . import config
from .backtest import make_weights


def next_weights(strategy, market, n=config.MAX_SUBNETS):
    """The weights your strategy sends now: the same rule as in the backtest."""
    return make_weights(strategy, market, market.times[-1], market.universe(), n)


def print_weights(weights):
    """A stand-in for `send`: prints what would be sent."""
    shown = ", ".join(f"{k}: {v:.2f}" for k, v in sorted(weights.items()))
    print(f"{datetime.now(timezone.utc):%H:%M:%S} UTC  would send {{{shown}}}")


def seconds_to_next_deadline(now=None, round_minutes=config.ROUND_MINUTES, margin=30):
    """Seconds until `margin` seconds before the next 15-minute deadline."""
    now = now or datetime.now(timezone.utc)
    passed = (now.minute % round_minutes) * 60 + now.second
    return max(0, round_minutes * 60 - passed - margin)


def run(strategy, get_market, send=print_weights, n=config.MAX_SUBNETS, rounds=None):
    """Send weights before every deadline, `rounds` times (None: until stopped)."""
    done = 0
    while rounds is None or done < rounds:
        time.sleep(seconds_to_next_deadline())
        try:
            send(next_weights(strategy, get_market(), n))
        except Exception as error:  # noqa: BLE001  a bad round must not stop the miner
            print(f"no weights sent this round: {error}")
        done += 1
        time.sleep(60)
