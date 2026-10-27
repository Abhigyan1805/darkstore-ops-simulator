import numpy as np
import pytest

from dso.replenishment import Policy, min_max_from_demand, reorder_decision, simulate


def test_reorder_only_at_or_below_min_and_up_to_max():
    q = reorder_decision(np.array([5, 3, 0, 10]), np.array([0, 0, 2, 0]),
                         s=np.array([3, 3, 3, 3]), S=np.array([8, 8, 8, 8]))
    assert q.tolist() == [0, 5, 6, 0]


def test_min_max_formula():
    # mu = 10/day, sigma = 3, z(0.95) = 1.645, P = 2:
    # s = ceil(20 + 1.645*3*sqrt(2)) = ceil(26.98) = 27;  S = 27 + 20 = 47
    s, S = min_max_from_demand(np.array([10.0]), np.array([3.0]), 0.95, 1, 1, 2.0)
    assert s[0] == 27 and S[0] == 47


def test_higher_service_level_raises_min():
    mu, sd = np.array([4.0]), np.array([2.0])
    s90, _ = min_max_from_demand(mu, sd, 0.90, 1, 1, 2.0)
    s99, _ = min_max_from_demand(mu, sd, 0.99, 1, 1, 2.0)
    assert s99[0] > s90[0]


def _days(demand_per_day, n_days):
    out = []
    for d in demand_per_day[:n_days]:
        sku = np.array([0] * d, dtype=np.int64)
        out.append((np.arange(d), sku))
    return out


def test_constant_demand_covered_by_protection_period_has_no_shorts():
    # 2 units/day, lead time 1 + review 1 => min must be >= 4
    days = _days([2] * 30, 30)
    res = simulate(Policy("ok", np.array([4]), np.array([8])), days, 1, lead_time=1)
    assert res["line_fill_rate"] == 1.0
    assert res["stockout_skuday_rate"] == 0.0


def test_min_too_low_causes_shorts():
    days = _days([2] * 30, 30)
    res = simulate(Policy("low", np.array([1]), np.array([3])), days, 1, lead_time=1)
    assert res["line_fill_rate"] < 1.0
    assert res["stockout_skuday_rate"] > 0


def test_shorts_hit_the_last_lines_of_the_day():
    # opening stock 2 (S), 3 lines demanded: only the third is short
    days = [(np.array([0, 1, 2]), np.array([0, 0, 0]))]
    res = simulate(Policy("x", np.array([0]), np.array([2])), days, 1, lead_time=1,
                   keep_log=True)
    assert res["short_log"][0].tolist() == [False, False, True]
    assert res["perfect_order_rate"] == pytest.approx(2 / 3)
