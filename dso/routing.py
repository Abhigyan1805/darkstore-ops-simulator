"""Picker routing in a parallel-aisle store with front and back cross aisles.

Two standard heuristics:
- S-shape (traversal): enter every aisle that holds a pick and walk it end to
  end; if the count of such aisles is odd, the last one is entered and left
  from the front. This is what most stores teach pickers.
- Nearest neighbour: always walk to the closest remaining pick.

Coordinates: x is the aisle centreline, y is measured from the front
cross-aisle centreline (y = 0) towards the back one (y = depth). The pack
station (depot) is on the front cross aisle at (depot_x, 0).
"""
import numpy as np
import pandas as pd


def point_distance(x1, y1, x2, y2, depth):
    """Shortest walk between two pick faces (vectorised).

    Same aisle: walk along it. Different aisles: leave by the front or the back
    cross aisle, whichever is shorter.
    """
    x1, y1, x2, y2 = map(np.asarray, (x1, y1, x2, y2))
    same = np.isclose(x1, x2)
    via = np.minimum(y1 + y2, 2 * depth - y1 - y2)
    return np.where(same, np.abs(y1 - y2), np.abs(x1 - x2) + via)


def s_shape_distance(x, y, depot_x, depth):
    """S-shape route length for one order's pick locations."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size == 0:
        return 0.0
    aisles = np.unique(x)
    k = aisles.size
    xl, xr = aisles[0], aisles[-1]
    horizontal = abs(depot_x - xl) + (xr - xl) + abs(xr - depot_x)
    if k % 2 == 0:
        vertical = k * depth
    else:
        # the return aisle can be the leftmost or rightmost; take the cheaper
        far_l = y[x == xl].max()
        far_r = y[x == xr].max()
        vertical = (k - 1) * depth + 2 * min(far_l, far_r)
    return float(horizontal + vertical)


def s_shape_batch(order_id, x, y, depot_x, depth) -> pd.Series:
    """S-shape distance for many orders at once (same logic as above)."""
    df = pd.DataFrame({"o": order_id, "x": x, "y": y})
    per_aisle = df.groupby(["o", "x"], sort=True)["y"].max().reset_index()
    g = per_aisle.groupby("o")
    k = g["x"].size()
    xl = g["x"].min()
    xr = g["x"].max()
    far_l = g["y"].first()   # sorted by x, so first row = leftmost aisle
    far_r = g["y"].last()
    horizontal = (depot_x - xl).abs() + (xr - xl) + (xr - depot_x).abs()
    odd = (k % 2 == 1)
    vertical = np.where(odd, (k - 1) * depth + 2 * np.minimum(far_l, far_r), k * depth)
    return pd.Series(horizontal.to_numpy() + vertical, index=k.index, name="s_shape_m")


def nearest_neighbour_distance(x, y, depot_x, depth):
    """Greedy nearest-neighbour tour from the depot and back."""
    x = list(map(float, x))
    y = list(map(float, y))
    cx, cy = depot_x, 0.0
    total = 0.0
    remaining = list(range(len(x)))
    while remaining:
        xs = np.array([x[i] for i in remaining])
        ys = np.array([y[i] for i in remaining])
        d = point_distance(cx, cy, xs, ys, depth)
        j = int(np.argmin(d))
        total += float(d[j])
        i = remaining.pop(j)
        cx, cy = x[i], y[i]
    total += float(point_distance(cx, cy, depot_x, 0.0, depth))
    return total
