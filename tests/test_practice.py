from datetime import datetime, timedelta, timezone

import pytest

from subnet_trading import config
from subnet_trading.live import History, snapshot_from_rows
from subnet_trading.practice import SIMPLE, YOU, Practice, from_file, next_deadline
from subnet_trading.scoring import Account, market_return

START = datetime(2026, 11, 20, 10, 1, tzinfo=timezone.utc)
NETUIDS = range(1, 61)


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
        rows = [{"netuid": 0, "tao_in": 1, "alpha_in": 1, "alpha_out": 1}]
        for n in NETUIDS:
            tao = (100_000 - 1_000 * n) * 1e9
            rows.append({"netuid": n, "tao_in": int(tao), "alpha_in": int(tao / price(n, minutes)),
                         "alpha_out": int(5e14)})
        return snapshot_from_rows(rows, block=int(minutes), timestamp_ms=int(t.timestamp() * 1000))


def session(strategy, logs=None):
    clock = FakeClock(START - timedelta(hours=2))
    chain, history = FakeChain(clock), History()
    while clock() < START:                       # two hours of history, every 15 minutes
        history.add(chain.snapshot())
        clock.sleep(15 * 60)
    clock.now, chain.reads = START, []
    practice = Practice(strategy, chain, history, clock=clock, sleep=clock.sleep,
                        log=(logs.append if logs is not None else lambda _: None))
    return practice, chain


def returns_between(a, b):
    return {n: price(n, b) / price(n, a) - 1 for n in NETUIDS}


def test_the_chain_is_read_at_each_deadline_and_five_minutes_later():
    practice, chain = session(lambda market: {1: 1.0})
    practice.play(rounds=2)
    at = lambda h, m: datetime(2026, 11, 20, h, m, tzinfo=timezone.utc)  # noqa: E731
    # deadlines 10:15 and 10:30, trades 10:20 and 10:35, the last round settled at 10:50
    assert chain.reads == [at(10, 15), at(10, 20), at(10, 30), at(10, 35), at(10, 50)]
    assert len(practice.rounds) == 2


def test_accounts_follow_the_scoring_rules():
    practice, _ = session(lambda market: {1: 1.0})
    practice.play(rounds=2)
    universe = list(range(1, 51))
    expected = Account()
    for start, end in ((19, 34), (34, 49)):     # minutes after START: 10:20-10:35, then 10:35-10:50
        returns = returns_between(start, end)
        expected.trade({1: 1.0})                 # a fee only the first time
        expected.hold(returns, market_return(returns, universe))
    assert practice.board.accounts[YOU].value == pytest.approx(expected.value)
    assert practice.rounds[-1][YOU] == pytest.approx(expected.value)


def test_refused_weights_keep_the_portfolio_and_are_reported():
    logs = []
    practice, _ = session(lambda market: {99: 1.0}, logs)
    practice.play(rounds=1)
    assert practice.board.accounts[YOU].value == config.START_BALANCE
    assert any("refused" in line for line in logs)
    assert practice.board.accounts[SIMPLE].value != config.START_BALANCE  # the reference still plays


def test_weights_file_is_read_at_each_deadline(tmp_path):
    path = tmp_path / "w.json"
    path.write_text('{"64": 0.4, "4": 0.6}')
    strategy = from_file(path)
    assert strategy(None) == {64: 0.4, 4: 0.6}
    path.write_text('{"8": 1}')
    assert strategy(None) == {8: 1.0}


def test_next_deadline():
    assert next_deadline(datetime(2026, 11, 20, 10, 1, tzinfo=timezone.utc)).minute == 15
    assert next_deadline(datetime(2026, 11, 20, 10, 15, tzinfo=timezone.utc)).minute == 30


def test_chain_rows_are_converted():
    snap = snapshot_from_rows([{"netuid": 0, "tao_in": 5, "alpha_in": 5, "alpha_out": 0},
                               {"netuid": 7, "tao_in": 2_000 * 10**9, "alpha_in": 40_000 * 10**9,
                                "alpha_out": 10_000 * 10**9}], block=1, timestamp_ms=1_793_850_000_000)
    assert list(snap["pools"].index) == [7]          # root is dropped
    assert snap["pools"].loc[7, "price"] == pytest.approx(0.05)
    assert snap["pools"].loc[7, "tao_in"] == pytest.approx(2_000)


def test_dashboard_is_written(tmp_path):
    practice, _ = session(lambda market: {1: 1.0})
    practice.dashboard = tmp_path / "practice.html"
    practice.play(rounds=1)
    page = practice.dashboard.read_text()
    assert "Practice game" in page and "simple strategy" in page and "TAO" in page
