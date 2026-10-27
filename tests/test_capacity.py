import math

import pandas as pd
import pytest

from dso.capacity import (erlang_c, max_rate_for, mmc_metrics, p_wait_longer,
                          pickers_needed, simulate_week)


def test_mm1_matches_textbook():
    lam, mu = 0.8, 1.0
    m = mmc_metrics(lam, mu, 1)
    assert m["p_wait"] == pytest.approx(0.8)
    assert m["wq_min"] == pytest.approx(lam / (mu * (mu - lam)))  # 4.0


def test_mm2_known_case():
    # lambda = mu = 1, c = 2: P(wait) = 1/3, Wq = 1/3
    m = mmc_metrics(1.0, 1.0, 2)
    assert m["p_wait"] == pytest.approx(1 / 3)
    assert m["wq_min"] == pytest.approx(1 / 3)


def test_erlang_c_large_c_is_stable():
    # 100 servers at 90% load: well-known value about 0.2 (no overflow)
    pc = erlang_c(100, 90.0)
    assert 0.1 < pc < 0.3


def test_overloaded_queue_always_waits():
    assert mmc_metrics(3.0, 1.0, 2)["wq_min"] == math.inf
    assert p_wait_longer(3.0, 1.0, 2, 1.0) == 1.0


def test_pickers_needed_meets_target_and_is_minimal():
    lam, mu, t, share = 3.0, 0.25, 2.0, 0.9   # 3 orders/min, 4 min per pick
    c = pickers_needed(lam, mu, t, share)
    assert p_wait_longer(lam, mu, c, t) <= 1 - share
    assert p_wait_longer(lam, mu, c - 1, t) > 1 - share


def test_max_rate_inverts_pickers_needed():
    mu, t, share = 0.25, 2.0, 0.9
    r = max_rate_for(10, mu, t, share)
    assert pickers_needed(r * 0.999, mu, t, share) <= 10
    assert pickers_needed(r * 1.01, mu, t, share) > 10


def test_des_agrees_with_erlang_c_for_exponential_service():
    # constant load, 3 pickers, exponential pick times mean 4 min, 0.6 orders/min
    import numpy as np
    rng = np.random.default_rng(1)
    picks = rng.exponential(4.0, 20000)
    plan = pd.DataFrame([(d, h, 36.0, 3) for d in range(7) for h in range(24)],
                        columns=["dow", "hour", "orders_per_hour", "pickers"])
    log = simulate_week(plan, picks, pack_min=0.01, pack_stations=50, days=7, seed=3)
    expected = mmc_metrics(0.6, 0.25, 3)["wq_min"]
    assert log["wait_min"].mean() == pytest.approx(expected, rel=0.2)
