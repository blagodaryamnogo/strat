"""Test 1: mathematical accuracy on a synthetic curve with a known 20% learning rate."""
import math

import numpy as np
import pytest

from analysis import AnalysisError, fit_experience_curve


def test_known_twenty_percent_curve():
    units = np.array([100, 150, 230, 340, 500, 760, 1100, 1700], dtype=float)
    cum = np.cumsum(units)
    b_true = -math.log2(0.8)
    cost = 1000.0 * cum ** (-b_true)
    reg = fit_experience_curve(cum, cost)
    assert reg.b == pytest.approx(0.32193, abs=1e-5)
    assert reg.learning_rate == pytest.approx(0.20, abs=1e-9)
    assert reg.r2 == pytest.approx(1.0, abs=1e-12)
    assert reg.a == pytest.approx(1000.0, rel=1e-9)
    assert reg.n == 8


def test_negative_learning_rate_is_not_flipped():
    cum = np.cumsum(np.full(6, 100.0))
    cost = 10.0 * cum ** 0.15           # costs rise with volume
    reg = fit_experience_curve(cum, cost)
    assert reg.b == pytest.approx(-0.15)
    assert reg.learning_rate < 0
    assert reg.learning_rate == pytest.approx(1 - 2 ** 0.15)


def test_noisy_fit_has_lower_r2():
    rng = np.random.default_rng(0)
    cum = np.cumsum(np.full(12, 100.0))
    cost = 1000 * cum ** -0.3 * np.exp(rng.normal(0, 0.3, 12))
    assert fit_experience_curve(cum, cost).r2 < 0.9


@pytest.mark.parametrize("cum,cost", [([1, 2], [1, 1]), ([1, 2, 3], [1, 0, 1]), ([1, 2, 3], [1, -1, 1]),
                                      ([5, 5, 5], [1, 2, 3]), ([1, 2, np.nan], [1, 2, 3])])
def test_invalid_regression_inputs_raise(cum, cost):
    with pytest.raises(AnalysisError):
        fit_experience_curve(cum, cost)
