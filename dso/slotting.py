"""Slotting: where each SKU lives, and what that does to picker walking.

Placements compared:
- random: every SKU in a random slot (a store that was never planned).
- category (baseline): SKUs grouped by category and sub-category, the groups
  laid out aisle after aisle from the left wall, as a store is often set up
  on opening day. No use of sales data.
- abc_velocity: fastest SKUs in the aisles nearest the pack station, at waist
  height first. Each aisle is filled before the next ("within-aisle" storage),
  which suits S-shape routing because the route length depends mostly on how
  many aisles an order touches.
- abc_affinity: same aisle order, but each aisle is filled greedily with the
  SKU that adds the most picks per day *plus* the most co-picks with the SKUs
  already in that aisle, so items bought together share an aisle.
"""
import numpy as np
import pandas as pd

from .config import Layout, PickTimes
from .routing import nearest_neighbour_distance, s_shape_batch


def abc_classes(picks: np.ndarray, a_share: float = 0.8, b_share: float = 0.95) -> np.ndarray:
    """A = SKUs making up the first 80% of picks, B = next 15%, C = rest."""
    order = np.argsort(-picks, kind="stable")
    cum = np.cumsum(picks[order]) / picks.sum()
    cls = np.where(cum <= a_share, "A", np.where(cum <= b_share, "B", "C"))
    # the SKU that crosses the boundary belongs to the lower class
    out = np.empty(len(picks), dtype="<U1")
    out[order] = cls
    return out


def walk_order_slots(slots: pd.DataFrame) -> np.ndarray:
    """Slot ids in the order a store fitter fills shelves: aisle by aisle from
    the left wall, each aisle front to back, left face then right face."""
    return slots.sort_values(["aisle", "side", "bay", "level", "pos"])["slot_id"].to_numpy()


def nearness_order_slots(slots: pd.DataFrame) -> np.ndarray:
    """Slot ids best-first: aisles nearest the pack station first; inside an
    aisle, waist-height levels first, then front to back."""
    s = slots.copy()
    s["aisle_dist"] = (s["x"] - s["x"].mean()).abs()
    s["not_golden"] = ~s["golden"]
    return s.sort_values(["aisle_dist", "aisle", "not_golden", "bay", "level", "side", "pos"]
                         )["slot_id"].to_numpy()


def place_random(n_sku: int, slots: pd.DataFrame, rng) -> np.ndarray:
    return rng.permutation(slots["slot_id"].to_numpy())[:n_sku]


def place_category(skus: pd.DataFrame, slots: pd.DataFrame) -> np.ndarray:
    seq = skus.sort_values(["category", "sub_category", "sku_name", "sku_id"])["sku_id"].to_numpy()
    out = np.empty(len(skus), dtype=np.int64)
    out[seq] = walk_order_slots(slots)[:len(skus)]
    return out


def place_abc(picks: np.ndarray, slots: pd.DataFrame) -> np.ndarray:
    seq = np.argsort(-picks, kind="stable")
    out = np.empty(len(picks), dtype=np.int64)
    out[seq] = nearness_order_slots(slots)[:len(picks)]
    return out


def place_affinity(picks_per_day: np.ndarray, copick_per_day: np.ndarray,
                   slots: pd.DataFrame, weight: float = 1.0) -> np.ndarray:
    """Greedy aisle filling by velocity + weight x co-picks with the aisle so far.

    Aisles are filled nearest-first; within an aisle the chosen SKUs then take
    that aisle's slots fastest-first (golden levels first).
    """
    n = len(picks_per_day)
    ordered = nearness_order_slots(slots)
    aisle_of = slots.set_index("slot_id")["aisle"]
    unplaced = np.ones(n, dtype=bool)
    out = np.empty(n, dtype=np.int64)
    pos = 0
    for aisle in pd.unique(aisle_of.loc[ordered].to_numpy()):
        aisle_slots = [s for s in ordered if aisle_of[s] == aisle]
        cap = min(len(aisle_slots), int(unplaced.sum()))
        if cap == 0:
            break
        bond = np.zeros(n, dtype=np.float64)
        members = []
        for _ in range(cap):
            score = np.where(unplaced, picks_per_day + weight * bond, -np.inf)
            j = int(np.argmax(score))
            members.append(j)
            unplaced[j] = False
            bond += copick_per_day[j]
        members.sort(key=lambda j: -picks_per_day[j])
        for j, s in zip(members, aisle_slots):
            out[j] = s
        pos += cap
    return out


def order_metrics(order_id: np.ndarray, sku_id: np.ndarray, slot_of_sku: np.ndarray,
                  slots: pd.DataFrame, lay: Layout, pt: PickTimes,
                  with_nn: bool = False) -> pd.DataFrame:
    """Walk distance and standard pick time for each order under one placement."""
    sl = slots.set_index("slot_id")
    slot = slot_of_sku[sku_id]
    x = sl["x"].to_numpy()[slot]
    y = sl["y"].to_numpy()[slot]
    golden = sl["golden"].to_numpy()[slot]
    dist = s_shape_batch(order_id, x, y, lay.depot_x, lay.depth)
    df = pd.DataFrame({"o": order_id, "golden": golden})
    g = df.groupby("o")
    lines = g.size()
    n_golden = g["golden"].sum()
    handling = (pt.order_setup_s + pt.order_dropoff_s
                + n_golden * pt.line_pick_golden_s
                + (lines - n_golden) * pt.line_pick_other_s)
    out = pd.DataFrame({"lines": lines, "walk_m": dist,
                        "handling_s": handling.astype(float)})
    out["pick_s"] = out["walk_m"] / pt.walk_speed_mps + out["handling_s"]
    if with_nn:
        tmp = pd.DataFrame({"o": order_id, "x": x, "y": y})
        out["walk_nn_m"] = tmp.groupby("o").apply(
            lambda d: nearest_neighbour_distance(d["x"], d["y"], lay.depot_x, lay.depth),
            include_groups=False)
    return out


def paired_ci(diff: np.ndarray, rng, n_boot: int = 2000, level: float = 0.95) -> tuple:
    """Mean of paired differences with a percentile bootstrap CI."""
    diff = np.asarray(diff, dtype=float)
    idx = rng.integers(0, len(diff), size=(n_boot, len(diff)))
    means = diff[idx].mean(axis=1)
    lo, hi = np.quantile(means, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(diff.mean()), float(lo), float(hi)


def ratio_ci(before: np.ndarray, after: np.ndarray, rng, n_boot: int = 2000,
             level: float = 0.95) -> tuple:
    """Percent reduction of the mean (1 - mean(after)/mean(before)) with bootstrap CI."""
    before = np.asarray(before, float)
    after = np.asarray(after, float)
    idx = rng.integers(0, len(before), size=(n_boot, len(before)))
    r = 1 - after[idx].mean(axis=1) / before[idx].mean(axis=1)
    lo, hi = np.quantile(r, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(1 - after.mean() / before.mean()), float(lo), float(hi)
