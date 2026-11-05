import pytest

from subnet_trading import config
from subnet_trading.scoring import Account, Leaderboard, market_return, rebalance_cost, round_gain
from subnet_trading.weights import WeightsError


def test_hand_calculated_round():
    # Subnet 1 rises 2%, subnet 2 falls 1%, subnet 3 is flat: the market (their average) is +0.333%.
    returns = {1: 0.02, 2: -0.01, 3: 0.0}
    market = market_return(returns, [1, 2, 3])
    assert market == pytest.approx(0.01 / 3)
    # Half on subnet 1, a quarter on subnet 2, a quarter left aside:
    # 0.5 * (2% - 0.333%) + 0.25 * (-1% - 0.333%) = 0.5%  ->  x20 x 1,000 TAO = 100 TAO
    gain = round_gain({1: 0.5, 2: 0.25}, returns, market)
    assert gain == pytest.approx(0.005)
    account = Account()
    account.weights = {1: 0.5, 2: 0.25}
    assert account.hold(returns, market) == pytest.approx(0.005 * config.FACTOR * config.START_BALANCE)


def test_worked_example_of_the_rules():
    # docs/RULES.md, "Worked example": fee 1.875 TAO, then a 10% gain on the remaining 998.125 TAO.
    returns = {1: 0.02, 2: -0.01, 3: 0.0}
    account = Account()
    assert account.trade({1: 0.5, 2: 0.25}) == pytest.approx(1.875)
    assert account.hold(returns, market_return(returns, [1, 2, 3])) == pytest.approx(99.8125)
    assert account.value == pytest.approx(1097.9375)


def test_gains_and_losses_carry_over():
    account = Account()
    account.weights = {1: 1.0}
    account.hold({1: 0.01, 2: -0.01}, 0.0)          # +20% of 1,000
    assert account.value == pytest.approx(1200)
    account.hold({1: 0.01, 2: -0.01}, 0.0)          # +20% of 1,200
    assert account.value == pytest.approx(1440)


def test_an_account_cannot_fall_below_zero():
    account = Account()
    account.weights = {1: 1.0}
    account.hold({1: -0.10, 2: 0.0}, 0.0)           # 20 x -10% would be -200%
    assert account.value == 0


def test_fees():
    assert rebalance_cost({}, {1: 0.5, 2: 0.5}) == pytest.approx(config.FEE_RATE * 1.0 * 1000)
    assert rebalance_cost({1: 1.0}, {2: 1.0}) == pytest.approx(config.FEE_RATE * 2.0 * 1000)  # sell, then buy
    assert rebalance_cost({1: 0.5}, {1: 0.5}) == 0


def test_tao_left_aside_and_market_matching_subnets_earn_nothing():
    returns = {1: 0.01, 2: 0.01}
    assert round_gain({1: 0.3}, returns, 0.01) == 0
    assert round_gain({}, returns, 0.01) == 0
    assert round_gain({9: 1.0}, returns, 0.01) == 0  # no return over the round: counts as the market


def test_miner_without_new_weights_keeps_them_and_pays_nothing():
    board = Leaderboard()
    board.submit("alice", {1: 1.0}, universe=[1, 2])
    board.run_round({1: 0.01, 2: 0.0}, universe=[1, 2])
    after_first = board.accounts["alice"].value
    board.run_round({1: 0.01, 2: 0.0}, universe=[1, 2])  # nothing submitted
    assert board.accounts["alice"].value == pytest.approx(after_first * (1 + config.FACTOR * (0.01 - 0.005)))
    assert board.accounts["alice"].weights == {1: 1.0}


def test_invalid_submission_is_refused():
    with pytest.raises(WeightsError):
        Leaderboard().submit("bob", {1: -0.5}, universe=[1, 2])
