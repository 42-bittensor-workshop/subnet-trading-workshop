import hashlib
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from subnet_trading import config
from subnet_trading.event import connect, market_from_payload, market_payload, message, request
from subnet_trading.live import History, round_returns, snapshot_from_rows
from subnet_trading.scoring import Account, market_return
from subnet_trading.validator import Validator, serve
from subnet_trading.weights import WeightsError

START = datetime(2026, 11, 20, 10, 1, tzinfo=timezone.utc)
NETUIDS = range(1, 61)
PLAYERS = {"alice", "bob", "carol"}


def at(hour, minute):
    return datetime(2026, 11, 20, hour, minute, tzinfo=timezone.utc)


def price(netuid, minutes):
    """Subnet n's price grows by n x 0.01% every minute."""
    return (1 + 0.0001 * netuid) ** minutes


class FakeClock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


class FakeChain:
    """60 subnets; subnet 1 has the largest pool. Records when it was read."""

    def __init__(self, clock):
        self.clock, self.reads = clock, []

    def snapshot(self, block=None):
        t = self.clock()
        self.reads.append(t)
        minutes = (t - START).total_seconds() / 60
        rows = [{"netuid": n, "tao_in": int((100_000 - 1_000 * n) * 1e9),
                 "alpha_in": int((100_000 - 1_000 * n) * 1e9 / price(n, minutes)), "alpha_out": int(5e14)}
                for n in NETUIDS]
        return snapshot_from_rows(rows, block=int(minutes), timestamp_ms=int(t.timestamp() * 1000))


def make_validator(registered=lambda: PLAYERS, **kwargs):
    clock = FakeClock(START)
    chain = FakeChain(clock)
    validator = Validator(chain, registered=registered, clock=clock, sleep=clock.sleep, log=lambda _: None, **kwargs)
    validator.preload([chain.snapshot()])
    return validator, chain, clock


def test_rounds_follow_the_rules_and_the_ranking_goes_on_chain_every_other_round():
    pushed = []
    validator, chain, _ = make_validator(set_weights=pushed.append)
    validator.receive("alice", {50: 1.0})
    validator.play(rounds=3)
    # deadlines 10:15, 10:30, 10:45; trades 5 minutes later; one more snapshot 10 minutes after each deadline
    assert chain.reads == [START] + [at(10, m) for m in (15, 20, 25, 30, 35, 40, 45, 50, 55)]
    universe, expected = list(range(1, 51)), Account()
    for start, end in ((19, 29), (34, 44)):     # minutes after START: 10:20-10:30, then 10:35-10:45
        returns = {n: price(n, end) / price(n, start) - 1 for n in NETUIDS}
        expected.trade({50: 1.0})                # a fee only the first time
        expected.hold(returns, market_return(returns, universe))
    assert validator.board.accounts["alice"].value == pytest.approx(expected.value)
    assert validator.board.accounts["bob"].value == config.START_BALANCE   # registered, never played
    assert len(validator.rounds) == 2
    assert len(pushed) == 1                       # after round 2, at 10:50
    assert pushed[0] == pytest.approx({"alice": 2 / 3, "bob": 1 / 6, "carol": 1 / 6})


def test_weights_count_only_if_received_before_the_deadline():
    validator, _, clock = make_validator()
    clock.now = at(10, 15)
    _, deadline = validator.receive("alice", {1: 1.0})          # exactly at 10:15: too late for 10:15
    assert deadline == at(10, 30)
    validator.deadline(at(10, 15))
    assert "alice" not in validator.board.pending
    validator.deadline(at(10, 30))
    assert validator.board.pending == {"alice": {1: 1.0}}


def test_weights_are_checked_when_received():
    validator, _, _ = make_validator()
    with pytest.raises(PermissionError):
        validator.receive("mallory", {1: 1.0})
    with pytest.raises(WeightsError):
        validator.receive("bob", {55: 1.0})                      # not among the 50 largest pools
    clean, _ = validator.receive("bob", {1: 2.0, 2: 2.0})
    assert clean == {1: 0.5, 2: 0.5}                             # scaled down to add up to 1


def test_a_failed_chain_read_loses_no_weights():
    validator, chain, _ = make_validator()
    validator.receive("alice", {1: 1.0})
    working, failures = chain.snapshot, []

    def flaky(block=None):
        if len(failures) < 3:
            failures.append(1)
            raise ConnectionError("node down")
        return working()

    chain.snapshot = flaky
    validator.play(rounds=1)                                      # 10:15: three reads fail
    assert validator.open is None and "alice" in validator.inbox
    validator.play(rounds=1)                                      # 10:30: the weights count, traded at 10:35
    assert validator.board.pending == {"alice": {1: 1.0}}
    assert validator.open["deadline"] == at(10, 30) and validator.open["trade"] is not None


def test_accounts_survive_a_restart(tmp_path):
    state = tmp_path / "state.json"
    validator, chain, clock = make_validator(state=state)
    validator.receive("alice", {50: 1.0})
    validator.play(rounds=2)                                      # round 1 settled at 10:30
    again = Validator(chain, registered=lambda: PLAYERS, state=state, clock=clock, log=lambda _: None)
    assert again.board.accounts["alice"].value == pytest.approx(validator.board.accounts["alice"].value)
    assert again.board.accounts["alice"].weights == {50: 1.0}
    assert again.started and len(again.rounds) == 1


def test_the_market_goes_to_miners_unchanged():
    clock = FakeClock(START)
    chain, history = FakeChain(clock), History()
    for _ in range(4):
        history.add(chain.snapshot())
        clock.sleep(300)
    market = history.market()
    back = market_from_payload(json.loads(json.dumps(market_payload(market))))
    assert list(back.times) == list(market.times)
    for field in ("price", "tao_in", "alpha_out", "life"):
        assert np.allclose(getattr(back, field).to_numpy(), getattr(market, field).to_numpy())


def test_a_subnet_missing_from_a_snapshot_has_no_return():
    clock = FakeClock(START)
    chain = FakeChain(clock)
    start = chain.snapshot()
    clock.sleep(600)
    end = chain.snapshot()
    end["pools"] = end["pools"].drop(index=7)
    returns = round_returns(start, end)
    assert 7 not in returns and returns[8] == pytest.approx(price(8, 10) - 1)


def test_the_signed_message_does_not_depend_on_how_weights_are_written():
    assert message("5Hk", 1, {7: 0.6, 3: 0.4}) == message("5Hk", 1, {"3": 0.4, "7": 0.6})
    assert message("5Hk", 1, {7: 0.6}) != message("5Hk", 2, {7: 0.6})


class FakeKeypair:
    """Signs as the miner's hotkey would; `secret` stands for its private key."""

    def __init__(self, address="5Miner", secret=b"miner"):
        self.ss58_address, self.secret = address, secret

    def sign(self, data):
        return hashlib.sha256(self.secret + data).digest()


def verify(hotkey, data, signature):
    return signature == "0x" + hashlib.sha256(b"miner" + data).hexdigest()


def test_a_miner_sends_signed_weights_and_reads_the_market_over_http():
    chain = FakeChain(FakeClock(START))
    validator = Validator(chain, registered=lambda: {"5Miner"}, log=lambda _: None)
    validator.preload([chain.snapshot()])
    server = serve(validator, verify, host="127.0.0.1", port=0)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        get_market, send = connect(url, keypair=FakeKeypair(), log=lambda _: None)
        assert send({7: 0.6, 3: 0.4})["weights"] == {"7": 0.6, "3": 0.4}
        assert validator.inbox["5Miner"][1] == {7: 0.6, 3: 0.4}
        assert get_market().price.iloc[-1].tolist() == pytest.approx([1.0] * len(NETUIDS))
        assert request(f"{url}/standings")["miners"] == []
        with pytest.raises(RuntimeError, match="not among the 50"):
            send({55: 1.0})
        with pytest.raises(RuntimeError, match="bad signature"):
            connect(url, keypair=FakeKeypair(secret=b"impostor"), log=lambda _: None)[1]({7: 1.0})
        with pytest.raises(RuntimeError, match="not registered"):
            connect(url, keypair=FakeKeypair("5Other"), log=lambda _: None)[1]({7: 1.0})
    finally:
        server.shutdown()
        server.server_close()
