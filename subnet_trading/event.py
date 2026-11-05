"""Your miner at the event: the market the validator scores with, and your weights, sent to it.

    from subnet_trading import run
    from subnet_trading.event import connect

    get_market, send = connect("http://VALIDATOR:8000", wallet="me", hotkey="default")
    run(my_strategy, get_market, send)

Or simply scripts/miner.py. `send` signs the weights with your hotkey (pip install -e
".[miner]"), so nobody can send weights in your name, and the validator answers at once
whether they are valid. Weights count for the next deadline if they arrive before it.
"""

import gzip
import json
import time
import urllib.error
import urllib.request

import pandas as pd

from .data import FIELDS, market_from_rows, market_rows

EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def message(hotkey, timestamp, weights):
    """The exact bytes a miner signs: its hotkey, the time and the weights, in one fixed form."""
    clean = {str(int(k)): float(v) for k, v in weights.items()}
    return f"{hotkey}|{int(timestamp)}|{json.dumps(clean, sort_keys=True, separators=(',', ':'))}".encode()


def market_payload(market):
    """A Market as JSON-ready columns: one row per time (UNIX seconds) and subnet."""
    rows = market_rows(market)
    rows["time"] = (rows["time"] - EPOCH) // pd.Timedelta(seconds=1)
    data = rows.astype(object).where(rows.notna(), None).to_numpy().tolist()
    return {"columns": list(rows.columns), "data": data}


def market_from_payload(payload):
    """The Market sent by the validator."""
    rows = pd.DataFrame(payload["data"], columns=payload["columns"])
    rows["time"] = pd.to_datetime(rows["time"], unit="s", utc=True)
    for field in FIELDS:
        rows[field] = pd.to_numeric(rows[field])
    return market_from_rows(rows)


def request(url, body=None, timeout=30):
    """GET `url`, or POST `body` as JSON, and decode the answer; a refusal raises its reason."""
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept-Encoding": "gzip", "Content-Type": "application/json", "User-Agent": "subnet-trading-miner"}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as answer:
            raw = answer.read()
            if (answer.headers.get("Content-Encoding") or "").lower() == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw)
    except urllib.error.HTTPError as error:
        try:
            reason = json.loads(error.read()).get("error")
        except (ValueError, AttributeError, OSError):
            reason = None
        raise RuntimeError(f"the validator refused: {reason or f'HTTP {error.code}'}") from None


def connect(url, wallet="default", hotkey="default", path=None, hours=24, timeout=30, keypair=None, log=print):
    """get_market() and send(weights) for run(), talking to the validator at `url`. The hotkey
    comes from your Bittensor wallet (`path` defaults to ~/.bittensor/wallets)."""
    if keypair is None:
        from bittensor_wallet import Wallet
        keypair = Wallet(name=wallet, hotkey=hotkey, path=path).hotkey
    base = url.rstrip("/")

    def get_market():
        return market_from_payload(request(f"{base}/market?hours={hours:g}", timeout=timeout))

    def send(weights):
        stamp = int(time.time())
        body = {"hotkey": keypair.ss58_address, "timestamp": stamp,
                "weights": {str(int(k)): float(v) for k, v in weights.items()},
                "signature": "0x" + keypair.sign(message(keypair.ss58_address, stamp, weights)).hex()}
        answer = request(f"{base}/weights", body, timeout)
        shown = ", ".join(f"{k}: {v:.2f}" for k, v in sorted(answer["weights"].items(), key=lambda kv: int(kv[0])))
        log(f"{time.strftime('%H:%M:%S', time.gmtime())} UTC  sent {{{shown}}}, for the {answer['deadline'][11:16]} deadline")
        return answer

    send.hotkey = keypair.ss58_address
    return get_market, send
