"""Slot grid of the modelled dark store."""
import numpy as np
import pandas as pd

from .config import Layout


def slot_table(lay: Layout) -> pd.DataFrame:
    """One row per storage slot with its pick-face coordinates.

    x is the centreline of the aisle the picker stands in; y is the distance
    from the front cross-aisle centreline to the bay centre. The picker picks
    from both rack faces of an aisle, so the side does not change x.
    """
    a, s, b, lv, p = np.meshgrid(
        np.arange(lay.n_aisles), np.arange(2), np.arange(lay.bays_per_side),
        np.arange(1, lay.levels + 1), np.arange(lay.slots_per_bay_level), indexing="ij")
    df = pd.DataFrame({
        "aisle": a.ravel(), "side": s.ravel(), "bay": b.ravel(),
        "level": lv.ravel(), "pos": p.ravel()})
    df["x"] = (df["aisle"] + 0.5) * lay.aisle_pitch
    df["y"] = lay.cross_aisle_width / 2 + (df["bay"] + 0.5) * lay.bay_width
    df["golden"] = df["level"].isin(lay.golden_levels)
    # one-way walk from the pack station to the slot, used to rank slots
    df["depot_dist"] = (df["x"] - lay.depot_x).abs() + df["y"]
    df.insert(0, "slot_id", np.arange(len(df)))
    return df
