"""DC-to-store replenishment: min/max (s, S) policies and an order-level simulation.

Timeline for one day t:
  1. Orders arrive through the day; each order line takes one unit from the
     shelf if there is stock, otherwise the line is short (lost sale).
  2. End of day: replenishment ordered L days ago is received and put away.
  3. End of day: for every SKU, if inventory position (on hand + on order)
     is at or below the min (reorder point s), order up to the max (S).

With daily review (R = 1) and lead time L = 1, stock ordered tonight is on the
shelf for the day after tomorrow, so the min must cover P = L + R days.
"""
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm


@dataclass
class Policy:
    name: str
    s: np.ndarray   # min / reorder point (units)
    S: np.ndarray   # max / order-up-to level (units)


def min_max_from_demand(mu: np.ndarray, sigma: np.ndarray, service_level: float,
                        lead_time: int, review: int, max_cover_days: float) -> tuple:
    """Reorder point with normal safety stock over the protection period.

    s = mu*P + z*sigma*sqrt(P), P = L + R;  S = s + max(1, mu * cover days).
    Returns integer (s, S).
    """
    p = lead_time + review
    z = norm.ppf(service_level)
    s = np.ceil(mu * p + z * sigma * math.sqrt(p))
    S = s + np.maximum(1, np.ceil(mu * max_cover_days))
    return s.astype(np.int64), S.astype(np.int64)


def reorder_decision(on_hand: np.ndarray, on_order: np.ndarray, s: np.ndarray,
                     S: np.ndarray) -> np.ndarray:
    """Units to order per SKU: up to S when inventory position <= s, else 0."""
    ip = on_hand + on_order
    return np.where(ip <= s, S - ip, 0)


def simulate(policy: Policy, day_lines: list, n_sku: int, lead_time: int,
             keep_log: bool = False) -> dict:
    """Run the policy over a list of days.

    day_lines[t] is a tuple (order_idx, sku_idx) of int arrays: the order lines
    of day t in the sequence they arrive. Returns aggregate metrics and,
    if keep_log, per-line short flags and per-SKU-day inventory.
    """
    on_hand = policy.S.astype(np.int64).copy()
    pipeline = [np.zeros(n_sku, dtype=np.int64) for _ in range(lead_time)]
    tot_lines = tot_short = 0
    stockout_skudays = 0
    inv_sum = np.zeros(n_sku, dtype=np.float64)
    order_lines_sent = 0
    perfect_orders = n_orders = 0
    shorts_log, inv_log = [], []

    for t, (oidx, sku) in enumerate(day_lines):
        start = on_hand.copy()
        # rank of each line among same-SKU lines earlier in the day
        order = np.argsort(sku, kind="stable")
        s_sorted = sku[order]
        first = np.r_[0, np.flatnonzero(np.diff(s_sorted)) + 1]
        run_start = np.repeat(first, np.diff(np.r_[first, len(s_sorted)]))
        rank = np.empty_like(order)
        rank[order] = np.arange(len(order)) - run_start
        short = rank >= start[sku]
        demand = np.bincount(sku, minlength=n_sku)
        served = np.minimum(demand, start)
        on_hand = start - served

        tot_lines += len(sku)
        tot_short += int(short.sum())
        stockout_skudays += int(((demand > served)).sum())
        if len(oidx):
            short_per_order = np.bincount(oidx, weights=short, minlength=oidx.max() + 1)
            present = np.bincount(oidx, minlength=oidx.max() + 1) > 0
            n_orders += int(present.sum())
            perfect_orders += int(((short_per_order == 0) & present).sum())

        # end of day: receive, then review
        if lead_time > 0:
            on_hand = on_hand + pipeline.pop(0)
        on_order = sum(pipeline) if pipeline else np.zeros(n_sku, dtype=np.int64)
        q = reorder_decision(on_hand, on_order, policy.s, policy.S)
        order_lines_sent += int((q > 0).sum())
        if lead_time > 0:
            pipeline.append(q)
        else:
            on_hand = on_hand + q
        inv_sum += (start + on_hand) / 2.0   # average of opening and closing stock

        if keep_log:
            shorts_log.append(short)
            inv_log.append(pd.DataFrame({
                "day": t, "sku_id": np.arange(n_sku), "opening_units": start,
                "demand_units": demand, "served_units": served,
                "closing_units": on_hand, "ordered_units": q}))

    days = len(day_lines)
    out = {
        "policy": policy.name,
        "line_fill_rate": 1 - tot_short / max(tot_lines, 1),
        "perfect_order_rate": perfect_orders / max(n_orders, 1),
        "stockout_skuday_rate": stockout_skudays / (n_sku * days),
        "avg_inventory_units": float(inv_sum.sum() / days),
        "avg_inventory_by_sku": inv_sum / days,
        "replen_lines_per_day": order_lines_sent / days,
    }
    if keep_log:
        out["short_log"] = shorts_log
        out["inventory_log"] = pd.concat(inv_log, ignore_index=True)
    return out
