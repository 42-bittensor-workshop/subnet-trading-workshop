import pytest

from subnet_trading.weights import WeightsError, check_weights, pick_top

UNIVERSE = list(range(1, 51))


def test_valid_weights_pass_unchanged():
    assert check_weights({8: 0.3, 4: 0.5}, UNIVERSE) == {8: 0.3, 4: 0.5}


@pytest.mark.parametrize("weights, reason", [
    ({n: 0.05 for n in range(1, 12)}, "at most"),
    ({8: -0.1}, "0 or more"),
    ({99: 0.5}, "not among"),
    ([8, 4], "must be a dict"),
    ({"x": 0.5}, "not a subnet id"),
])
def test_invalid_weights_are_refused(weights, reason):
    with pytest.raises(WeightsError, match=reason):
        check_weights(weights, UNIVERSE)


def test_weights_above_one_are_scaled_down_and_zeros_dropped():
    assert check_weights({1: 1.0, 2: 1.0, 3: 0.0}, UNIVERSE) == {1: 0.5, 2: 0.5}


def test_pick_top():
    scores = {1: 0.1, 2: 0.5, 3: 0.3, 4: -0.2}
    assert pick_top(scores, 2) == {2: 0.5, 3: 0.5}
    assert pick_top(scores, 3, how="score") == pytest.approx({2: 0.5 / 0.9, 3: 0.3 / 0.9, 1: 0.1 / 0.9})
