"""The event's validator: miners' weights in, a round every 15 minutes, the ranking on chain.

    python scripts/validator.py --wallet owner --hotkey validator --netuid NETUID

One round, as in docs/RULES.md, with t = :00, :15, :30 or :45 UTC:
    t     the round in progress is settled at the prices of t, then each miner's latest
          weights received before t are checked against the 50 largest pools at t
    t+5   the new round's starting prices; every `weights_every` settled rounds, the
          ranking (Leaderboard.weights) is set on chain
    t+10  one more snapshot, so the market served to miners has one every 5 minutes

Miners push their weights, so laptops behind a NAT can play (no axon), and read the
market from here, so each one sees the prices it is scored on:
    POST /weights    {"hotkey", "timestamp", "weights", "signature"}: event.message(), signed by the hotkey
    GET  /market     the last `hours` hours of snapshots (at most 24), gzipped JSON
    GET  /standings  the ranking after the last settled round, for a leaderboard screen
    GET  /health     the next deadline

The accounts are saved after every round (`state`), so a restart keeps them; the round in
progress at a restart is dropped. A step that cannot read the prices is logged and the
event goes on: weights not taken at a deadline count at the next one.
"""

import gzip
import json
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

from . import config
from .data import FIELDS, Market
from .event import market_payload, message
from .live import History, round_returns
from .practice import next_deadline
from .scoring import Account, Leaderboard, market_return
from .weights import WeightsError, check_weights

SNAPSHOT_MINUTES = 5
MAX_HOURS = 24
KEEP = MAX_HOURS * 60 // SNAPSHOT_MINUTES


def universe_of(snapshot):
    """The 50 largest pools of a snapshot."""
    return [int(n) for n in snapshot["pools"]["tao_in"].dropna().nlargest(config.UNIVERSE_SIZE).index]


class Validator:
    """Rounds on a clock. `source.snapshot()` reads every pool (live.Chain, or a fake in tests);
    `set_weights({hotkey: weight})` puts the ranking on chain; `registered()` gives the hotkeys
    allowed to play (None: anyone)."""

    def __init__(self, source, set_weights=None, registered=None, state=None, weights_every=2,
                 clock=None, sleep=time.sleep, log=print):
        self.source, self.set_weights, self.registered = source, set_weights, registered
        self.state = Path(state) if state else None
        self.weights_every = weights_every
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep, self.log = sleep, log
        self.board = Leaderboard()
        self.lock = threading.Lock()
        self.snapshots = []      # every 5 minutes, the last 24 hours
        self.inbox = {}          # hotkey -> (received at, weights), for the coming deadline
        self.open = None         # the round in progress
        self.rounds = []         # one row per settled round
        self.started = False     # the first scored deadline has passed
        self.pushed_after = 0    # settled rounds when the ranking last went on chain
        self._served = (None, None)
        self.restore()

    # --- what miners call, from the server's threads ---

    def receive(self, hotkey, weights):
        """A miner's weights for the next deadline, checked against the latest pools. Returns the
        weights as they would count now, and the deadline they count for."""
        if self.registered is not None and hotkey not in self.registered():
            raise PermissionError("this hotkey is not registered on the subnet")
        with self.lock:
            latest = self.snapshots[-1] if self.snapshots else None
        if latest is None:
            raise WeightsError("the validator has no prices yet: try again in a minute")
        clean = check_weights(weights, universe_of(latest))
        now = self.clock()
        with self.lock:
            self.inbox[hotkey] = (now, clean)
        return clean, next_deadline(now)

    def market(self, hours=MAX_HOURS):
        """The last `hours` hours of snapshots, as a Market."""
        with self.lock:
            history = History()
            history.snapshots = list(self.snapshots)
        market = history.market()
        since = market.times[-1] - pd.Timedelta(hours=hours)
        return Market(**{name: getattr(market, name).loc[since:] for name in (*FIELDS, "holders")})

    def market_bytes(self, hours=MAX_HOURS):
        """The market for miners, gzipped JSON, built again only when a snapshot arrives."""
        with self.lock:
            key = (len(self.snapshots), self.snapshots[-1]["time"] if self.snapshots else None, hours)
        if self._served[0] != key:
            payload = market_payload(self.market(hours)) if key[1] is not None else {
                "columns": ["time", "netuid", *FIELDS], "data": []}
            self._served = (key, gzip.compress(json.dumps(payload).encode()))
        return self._served[1]

    def standings(self):
        """The ranking after the last settled round, with each miner's on-chain weight."""
        board = Leaderboard()
        board.accounts = dict(self.board.accounts)   # a copy: the rounds go on in another thread
        values, chain = board.standings(), board.weights()
        miners = [{"rank": rank, "hotkey": hotkey, "value": round(float(value), 4),
                   "weight": round(chain.get(hotkey, 0.0), 6),
                   "weights": {str(k): w for k, w in board.accounts[hotkey].weights.items()}}
                  for rank, (hotkey, value) in enumerate(values.items(), 1)]
        return {"rounds": len(self.rounds), "next_deadline": next_deadline(self.clock()).isoformat(), "miners": miners}

    # --- the rounds ---

    def preload(self, snapshots):
        """Earlier snapshots (a backfill), oldest first, before the first round."""
        for snap in snapshots:
            self._keep(snap)

    def _keep(self, snap):
        with self.lock:
            if not self.snapshots or snap["time"] > self.snapshots[-1]["time"]:
                self.snapshots.append(snap)
            del self.snapshots[:-KEEP]

    def snapshot(self):
        snap = self.source.snapshot()
        self._keep(snap)
        return snap

    def deadline(self, t):
        """Settle the round in progress at the prices of t, then take the weights sent before t."""
        snap = self.snapshot()
        if self.open is not None and self.open["trade"] is not None:
            self.settle(t, snap)
        if not self.started:
            if self.registered is not None:
                self.board.register(sorted(self.registered()))
            self.started = True
        with self.lock:
            taken = {hotkey: w for hotkey, (at, w) in self.inbox.items() if at < t}
            self.inbox = {hotkey: sent for hotkey, sent in self.inbox.items() if sent[0] >= t}
        universe, refused = universe_of(snap), {}
        for hotkey, weights in sorted(taken.items()):
            try:
                self.board.submit(hotkey, weights, universe)
            except WeightsError as error:
                refused[hotkey] = str(error)
        self.open = {"number": len(self.rounds) + 1, "deadline": t, "universe": universe, "trade": None}
        self.log(f"{t:%H:%M} deadline: weights from {len(taken)} miners"
                 + (f", {len(refused)} refused ({', '.join(f'{h[:8]}: {e}' for h, e in refused.items())})" if refused else ""))

    def trade(self, t):
        """The new round's starting prices; then, every `weights_every` rounds, the ranking on chain."""
        if self.open is None:
            return
        self.open["trade"] = self.snapshot()
        self.log(f"{t:%H:%M} round {self.open['number']}: traded, result at "
                 f"{self.open['deadline'] + timedelta(minutes=config.ROUND_MINUTES):%H:%M}")
        settled = len(self.rounds)
        if self.set_weights is not None and settled and settled % self.weights_every == 0 and settled != self.pushed_after:
            self.push_weights()

    def tick(self, t):
        """One more snapshot for the market served to miners."""
        self.snapshot()

    def settle(self, t, snap):
        """The round's result, with the event's scoring code."""
        returns = round_returns(self.open["trade"], snap)
        universe = self.open["universe"]
        self.board.run_round(returns, universe)
        market = market_return(returns, universe)
        standings = self.board.standings()
        self.rounds.append({"round": self.open["number"], "deadline": self.open["deadline"].isoformat(),
                            "settled": t.isoformat(), "market": None if math.isnan(market) else market,
                            "miners": len(standings), "leader": standings.index[0] if len(standings) else None})
        self.log(f"{t:%H:%M} round {self.open['number']} settled: market {market:+.3%}, "
                 f"{len(standings)} miners" + (f", leader {standings.index[0][:8]} at {standings.iloc[0]:,.1f} TAO"
                                               if len(standings) else ""))
        self.open = None
        self.save()

    def push_weights(self):
        weights = self.board.weights()
        self.pushed_after = len(self.rounds)
        if not weights:
            return
        try:
            self.set_weights(weights)
            self.log(f"ranking set on chain for {len(weights)} miners")
        except Exception as error:  # noqa: BLE001  the next attempt comes `weights_every` rounds later
            self.log(f"ranking not set on chain: {type(error).__name__}: {error}")

    def run(self, step, at, attempts=1):
        """One step; a failure is logged and retried, never fatal. True when it went through."""
        for attempt in range(attempts):
            try:
                step(at)
                return True
            except Exception as error:  # noqa: BLE001  a chain read can fail: the event goes on
                self.log(f"{at:%H:%M} {step.__name__} failed: {type(error).__name__}: {error}")
                if attempt + 1 < attempts:
                    self.sleep(20)
        return False

    def wait_until(self, moment):
        while (left := (moment - self.clock()).total_seconds()) > 0:
            self.sleep(min(left, 30))

    def play(self, rounds=None):
        """Round after round until stopped (or for `rounds` deadlines)."""
        done = 0
        while rounds is None or done < rounds:
            t = next_deadline(self.clock())
            self.wait_until(t)
            done += 1
            if not self.run(self.deadline, t, attempts=3):
                continue
            for minutes in range(config.HALT_MINUTES, config.ROUND_MINUTES, SNAPSHOT_MINUTES):
                at = t + timedelta(minutes=minutes)
                self.wait_until(at)
                if minutes > config.HALT_MINUTES:
                    self.run(self.tick, at)
                elif not self.run(self.trade, at, attempts=3):
                    self.open = None
                    self.board.pending.clear()
                    self.log(f"{at:%H:%M} round dropped: no prices to trade at, portfolios stay as they were")

    # --- a restart keeps the accounts ---

    def save(self):
        if self.state is None:
            return
        accounts = {miner: {"value": a.value, "weights": {str(k): w for k, w in a.weights.items()}}
                    for miner, a in self.board.accounts.items()}
        payload = {"saved": self.clock().isoformat(), "started": self.started, "pushed_after": self.pushed_after,
                   "accounts": accounts, "rounds": self.rounds}
        temporary = self.state.with_name(self.state.name + ".tmp")
        temporary.write_text(json.dumps(payload, indent=1))
        temporary.replace(self.state)

    def restore(self):
        if self.state is None or not self.state.exists():
            return
        payload = json.loads(self.state.read_text())
        for miner, saved in payload["accounts"].items():
            account = Account()
            account.value = float(saved["value"])
            account.weights = {int(k): float(w) for k, w in saved["weights"].items()}
            self.board.accounts[miner] = account
        self.rounds = payload.get("rounds", [])
        self.started = payload.get("started", bool(self.board.accounts))
        self.pushed_after = payload.get("pushed_after", len(self.rounds))


class Handler(BaseHTTPRequestHandler):
    """The routes; `validator`, `verify` and `max_skew` are set by serve()."""

    validator = verify = None
    max_skew = 120

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/market":
            try:
                hours = min(float(parse_qs(url.query).get("hours", [MAX_HOURS])[0]), MAX_HOURS)
            except ValueError:
                return self.reply(400, {"error": "hours must be a number"})
            return self.send_body(200, self.validator.market_bytes(hours), gzipped=True)
        if url.path == "/standings":
            return self.reply(200, self.validator.standings())
        if url.path in ("/", "/health"):
            return self.reply(200, {"ok": True, "next_deadline": next_deadline(self.validator.clock()).isoformat(),
                                    "rounds": len(self.validator.rounds)})
        self.reply(404, {"error": "unknown route"})

    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path != "/weights":
            return self.reply(404, {"error": "unknown route"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= 65536:
                raise ValueError("the body is missing or too large")
            sent = json.loads(self.rfile.read(length))
            hotkey, stamp, weights, signature = sent["hotkey"], int(sent["timestamp"]), sent["weights"], sent["signature"]
            if not (isinstance(hotkey, str) and isinstance(weights, dict) and isinstance(signature, str)):
                raise ValueError("hotkey and signature must be strings, weights a dict")
            signed = message(hotkey, stamp, weights)
        except (ValueError, KeyError, TypeError) as error:
            return self.reply(400, {"error": f"bad request: {error}"})
        if abs(self.validator.clock().timestamp() - stamp) > self.max_skew:
            return self.reply(400, {"error": "timestamp too far from the validator's clock: set your computer's time"})
        if not self.verify(hotkey, signed, signature):
            return self.reply(401, {"error": "bad signature: weights must be signed by the hotkey they name"})
        try:
            clean, deadline = self.validator.receive(hotkey, weights)
        except PermissionError as error:
            return self.reply(403, {"error": str(error)})
        except WeightsError as error:
            return self.reply(400, {"error": str(error)})
        self.reply(200, {"ok": True, "weights": {str(k): w for k, w in clean.items()}, "deadline": deadline.isoformat()})

    def reply(self, status, payload):
        self.send_body(status, json.dumps(payload).encode())

    def send_body(self, status, body, gzipped=False):
        if gzipped and "gzip" not in (self.headers.get("Accept-Encoding") or ""):
            body, gzipped = gzip.decompress(body), False
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        if gzipped:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002  quiet: the validator logs the rounds
        pass


def serve(validator, verify, host="0.0.0.0", port=8000, max_skew=120):
    """Serve the routes from a background thread; returns the server (port 0: any free port).
    `verify(hotkey, data, signature)` checks a signature (scripts/validator.py: the hotkey's key)."""
    routes = type("Routes", (Handler,), {"validator": validator, "verify": staticmethod(verify), "max_skew": max_skew})
    server = ThreadingHTTPServer((host, port), routes)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
