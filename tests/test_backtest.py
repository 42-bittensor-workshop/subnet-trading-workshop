import numpy as np
import pandas as pd
import pytest

from conftest import make_market
from subnet_trading import backtest, config, random_strategy


def future_return(market, start, end):
    """A cheating signal: each subnet's return between `start` and `end` snapshots ahead."""
    return market.price.shift(-end) / market.price.shift(-start) - 1


def test_trade_happens_after_the_pause():
    market = make_market(n_times=200)
    # Knowing the move during the pause (deadline to trade) is worth nothing...
    during_pause = backtest(future_return(market, 0, 1), market, fee_rate=0)
    # ...knowing the move during the holding period is worth a lot: that is the move scored.
    during_holding = backtest(future_return(market, 1, 2), market, fee_rate=0)
    assert during_holding.value > config.START_BALANCE * 2
    assert abs(during_pause.value - config.START_BALANCE) < abs(during_holding.value - config.START_BALANCE) / 5


def test_a_strategy_function_sees_only_the_past():
    market = make_market()
    seen = []

    def strategy(known):
        seen.append(known.times[-1])
        return {1: 1.0}

    result = backtest(strategy, market)
    assert seen == list(result.rounds.index)


def test_fixed_weights_outside_the_universe_are_dropped():
    market = make_market()  # subnets 51 to 60 are outside the top 50
    result = backtest({1: 0.5, 55: 0.5}, market)
    assert set(result.rounds["subnets"]) == {"1"}


def test_invalid_weights_leave_the_portfolio_unchanged():
    market = make_market()
    calls = []

    def strategy(known):
        calls.append(1)
        return {1: 1.0} if len(calls) == 1 else {1: -1.0}

    result = backtest(strategy, market)
    assert (result.rounds["subnets"] == "1").all()
    assert result.rounds["fee"].iloc[1:].sum() == 0


def test_random_picks_ten_subnets_from_the_universe():
    market = make_market()
    weights = random_strategy(seed=1)(market)
    assert len(weights) == 10 and set(weights) <= set(market.universe())
    assert sum(weights.values()) == pytest.approx(1)


def test_a_function_can_return_a_signal_table():
    market = make_market()
    table_result = backtest(lambda known: known.price / known.price.shift(4) - 1, market)
    signal_result = backtest(market.price / market.price.shift(4) - 1, market)
    assert table_result.value == pytest.approx(signal_result.value)
    assert table_result.summary()["rounds without valid weights"] == 0


def test_rounds_without_valid_weights_are_counted():
    market = make_market()
    result = backtest(lambda known: {99: 1.0}, market)  # subnet 99 does not exist
    assert result.summary()["rounds without valid weights"] == len(result.rounds)
