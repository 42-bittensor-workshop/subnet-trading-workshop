from datetime import datetime, timedelta, timezone

import pytest

from subnet_trading import config
from subnet_trading.live import History, snapshot_from_rows
from subnet_trading.practice import YOU, Practice, from_file, from_python_file, next_deadline
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
    # round 1: deadline 10:15, trade 10:20, result 10:30 (also round 2's deadline);
    # round 2: trade 10:35, result 10:45. A round is settled before the next one starts.
    assert chain.reads == [at(10, 15), at(10, 20), at(10, 30), at(10, 35), at(10, 45)]
    assert len(practice.rounds) == 2
    assert [r["status"] for r in practice.timeline] == ["settled", "settled"]


def test_accounts_follow_the_scoring_rules():
    practice, _ = session(lambda market: {1: 1.0})
    practice.play(rounds=2)
    universe = list(range(1, 51))
    expected = Account()
    for start, end in ((19, 29), (34, 44)):     # minutes after START: 10:20-10:30, then 10:35-10:45
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
    assert "Practice game" in page and "your account" in page and "the market" in page
    assert "simple strategy" not in page
    assert "your result" in page and "Round 1" in page


def test_strategy_file_is_read_again_at_each_deadline(tmp_path):
    path = tmp_path / "mine.py"
    path.write_text("def strategy(market):\n    return {1: 1.0}\n")
    strategy = from_python_file(path)
    assert strategy(None) == {1: 1.0}
    path.write_text("def strategy(market):\n    return {2: 1.0}\n")
    assert strategy(None) == {2: 1.0}


def test_a_broken_strategy_file_is_reported_and_the_game_goes_on(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text("def strategy(market):\n    return {1: 1.0\n")   # syntax error
    logs = []
    practice, _ = session(from_python_file(path), logs)
    practice.play(rounds=1)
    assert any("your strategy failed" in line for line in logs)
    assert practice.board.accounts[YOU].value == config.START_BALANCE


def test_dashboard_lists_the_subnets_you_can_pick(tmp_path):
    practice, _ = session(lambda market: {1: 1.0})
    practice.dashboard = tmp_path / "practice.html"
    practice.play(rounds=1)
    page = practice.dashboard.read_text()
    assert "The 50 subnets you can pick" in page
    assert page.split("The 50 subnets you can pick")[1].count("<tr><td>") == 50
    assert len(practice.eligible()) == 50


def test_practice_command_line():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "practice_cli", Path(__file__).resolve().parent.parent / "scripts" / "practice.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    args = cli.parse(["--strategy", "strategies/example_strategy.py", "--history-hours", "4", "--rounds", "2"])
    assert (args.strategy, args.history_hours, args.rounds, args.dashboard) == \
        ("strategies/example_strategy.py", 4, 2, "practice.html")
    assert cli.parse(["--weights", "strategies/my_weights.json"]).weights == "strategies/my_weights.json"
    with pytest.raises(SystemExit):
        cli.parse([])                                                      # one of the two is required
    with pytest.raises(SystemExit):
        cli.parse(["--strategy", "strategies/example_strategy.py", "--weights", "strategies/my_weights.json"])


def test_a_round_goes_from_pause_to_live_to_settled():
    practice, chain = session(lambda market: {1: 1.0})
    t = datetime(2026, 11, 20, 10, 15, tzinfo=timezone.utc)
    chain.clock.now = t
    practice.deadline(t)
    assert practice.timeline[-1]["status"] == "pause"
    chain.clock.now = t + timedelta(minutes=5)
    practice.trade(chain.clock.now)
    assert practice.timeline[-1]["status"] == "live"
    chain.clock.now = t + timedelta(minutes=15)
    practice.deadline(chain.clock.now)                  # settles round 1, then opens round 2
    assert [r["status"] for r in practice.timeline] == ["settled", "pause"]
    assert practice.timeline[0]["you"] != 0
