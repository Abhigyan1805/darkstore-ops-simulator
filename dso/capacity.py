"""Picker staffing: Erlang C (M/M/c) sizing plus a SimPy check.

Erlang C assumes Poisson arrivals and exponential pick times. Real pick times
vary less than exponential ones, so Erlang C is on the safe side; the SimPy
model replays the real hourly arrival profile with pick times drawn from the
routing simulation to confirm the staffing plan.
"""
import math

import numpy as np
import pandas as pd
import simpy


def erlang_c(c: int, a: float) -> float:
    """Probability an arriving job waits, for c servers and offered load a (Erlangs)."""
    if c <= 0:
        return 1.0
    if a >= c:
        return 1.0
    b = 1.0  # Erlang B by recursion, stable for large c
    for k in range(1, c + 1):
        b = a * b / (k + a * b)
    return c * b / (c - a * (1 - b))


def mmc_metrics(lam: float, mu: float, c: int) -> dict:
    """Rates per minute. Returns utilisation, P(wait), mean wait (min)."""
    a = lam / mu
    if c * mu <= lam:
        return {"rho": a / c if c else math.inf, "p_wait": 1.0, "wq_min": math.inf}
    pc = erlang_c(c, a)
    return {"rho": a / c, "p_wait": pc, "wq_min": pc / (c * mu - lam)}


def p_wait_longer(lam: float, mu: float, c: int, t: float) -> float:
    """P(wait > t) for M/M/c, t in the same time unit as the rates."""
    if c * mu <= lam:
        return 1.0
    return erlang_c(c, lam / mu) * math.exp(-(c * mu - lam) * t)


def pickers_needed(lam: float, mu: float, t_target: float, share: float, c_max: int = 200) -> int:
    """Smallest c with P(wait > t_target) <= 1 - share."""
    if lam <= 0:
        return 0
    c = max(1, math.floor(lam / mu))
    while c <= c_max:
        if p_wait_longer(lam, mu, c, t_target) <= 1 - share:
            return c
        c += 1
    return c_max + 1


def max_rate_for(c: int, mu: float, t_target: float, share: float) -> float:
    """Largest arrival rate c servers can take while meeting the wait target (bisection)."""
    lo, hi = 0.0, c * mu
    for _ in range(60):
        mid = (lo + hi) / 2
        if p_wait_longer(mid, mu, c, t_target) <= 1 - share:
            lo = mid
        else:
            hi = mid
    return lo


def hourly_profile(orders: pd.DataFrame) -> pd.DataFrame:
    """Share of the week's orders in each (day-of-week, hour) cell."""
    t = orders.groupby(["dow", "hour"]).size().rename("n").reset_index()
    full = pd.MultiIndex.from_product([range(7), range(24)], names=["dow", "hour"])
    t = t.set_index(["dow", "hour"]).reindex(full, fill_value=0).reset_index()
    t["share_of_week"] = t["n"] / t["n"].sum()
    return t


def staffing_plan(profile: pd.DataFrame, orders_per_day: float, mean_pick_min: float,
                  t_target: float, share: float) -> pd.DataFrame:
    df = profile.copy()
    df["orders_per_hour"] = df["share_of_week"] * orders_per_day * 7
    mu = 1.0 / mean_pick_min
    lam_min = df["orders_per_hour"] / 60
    df["pickers"] = [pickers_needed(l, mu, t_target, share) for l in lam_min]
    m = [mmc_metrics(l, mu, c) if c else {"rho": 0, "p_wait": 0, "wq_min": 0}
         for l, c in zip(lam_min, df["pickers"])]
    df["utilisation"] = [x["rho"] for x in m]
    df["mean_wait_min"] = [x["wq_min"] for x in m]
    df["p_wait_gt_target"] = [p_wait_longer(l, mu, c, t_target) if c else 0
                              for l, c in zip(lam_min, df["pickers"])]
    return df


def simulate_week(plan: pd.DataFrame, pick_minutes: np.ndarray, pack_min: float,
                  pack_stations: int, days: int, seed: int) -> pd.DataFrame:
    """Discrete-event simulation of a picker pool and pack stations.

    Orders arrive as a Poisson process whose rate changes every hour (from the
    plan). Picker count changes every hour too: off-shift pickers are modelled
    as high-priority 'blocker' jobs that hold a picker slot, so a picker going
    off shift finishes the order in hand first.
    """
    rng = np.random.default_rng(seed)
    env = simpy.Environment()
    c_max = int(plan["pickers"].max())
    pickers = simpy.PriorityResource(env, capacity=c_max)
    packers = simpy.Resource(env, capacity=pack_stations)
    rate = plan.set_index(["dow", "hour"])["orders_per_hour"]
    staff = plan.set_index(["dow", "hour"])["pickers"]
    log = []
    blockers = []

    def blocker(release_evt):
        with pickers.request(priority=-1) as req:
            yield req
            yield release_evt

    def shift_manager():
        for day in range(days):
            for hour in range(24):
                dow = day % 7
                want = int(staff[(dow, hour)])
                need_block = c_max - want
                while len(blockers) < need_block:
                    evt = env.event()
                    blockers.append(evt)
                    env.process(blocker(evt))
                while len(blockers) > need_block:
                    blockers.pop().succeed()
                yield env.timeout(60)

    def order(t_arr, dow, hour):
        with pickers.request(priority=0) as req:
            yield req
            t_start = env.now
            yield env.timeout(float(rng.choice(pick_minutes)))
        with packers.request() as preq:
            yield preq
            yield env.timeout(pack_min)
        log.append((dow, hour, t_arr, t_start - t_arr, env.now - t_arr))

    def arrivals():
        for day in range(days):
            for hour in range(24):
                dow = day % 7
                lam = rate[(dow, hour)] / 60.0
                t0 = (day * 24 + hour) * 60.0
                t = t0
                while lam > 0:
                    t += rng.exponential(1 / lam)
                    if t >= t0 + 60:
                        break
                    yield env.timeout(t - env.now)
                    env.process(order(t, dow, hour))
                yield env.timeout(max(0.0, t0 + 60 - env.now))

    env.process(shift_manager())
    env.process(arrivals())
    env.run(until=days * 24 * 60 + 240)
    return pd.DataFrame(log, columns=["dow", "hour", "t_arrival", "wait_min", "ready_min"])
