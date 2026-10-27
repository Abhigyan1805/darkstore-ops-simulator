import numpy as np
import pandas as pd
import pytest

from dso.config import Layout, PickTimes
from dso.layout import slot_table
from dso.mapping import assign, tokens, validate_map
from dso.slotting import (abc_classes, order_metrics, paired_ci, place_abc,
                          place_affinity, place_category)

LAY = Layout(n_aisles=4, bays_per_side=5, levels=3, slots_per_bay_level=1, golden_levels=(2,))


def test_abc_classes_split_by_cumulative_share():
    picks = np.array([50, 30, 10, 5, 3, 2], float)
    assert abc_classes(picks).tolist() == ["A", "A", "B", "B", "C", "C"]


def test_abc_puts_fastest_sku_in_best_slot():
    slots = slot_table(LAY)
    picks = np.array([1, 100, 5, 50], float)
    p = place_abc(picks, slots)
    s = slots.set_index("slot_id")
    best = s.loc[p[1]]
    # a central aisle, waist height, front bay
    assert best["aisle"] in (1, 2) and best["golden"] and best["bay"] == 0
    assert len(set(p)) == len(p)


def test_category_layout_keeps_categories_contiguous():
    slots = slot_table(LAY)
    skus = pd.DataFrame({"sku_id": range(6), "category": list("BABABA"),
                         "sub_category": "x", "sku_name": [f"n{i}" for i in range(6)]})
    p = place_category(skus, slots)
    walk = {sid: i for i, sid in enumerate(slots.sort_values(
        ["aisle", "side", "bay", "level", "pos"])["slot_id"])}
    rank = [walk[x] for x in p]
    a = sorted(rank[i] for i in (1, 3, 5))
    b = sorted(rank[i] for i in (0, 2, 4))
    assert a == [0, 1, 2] and b == [3, 4, 5]


def test_affinity_layout_pulls_copicked_pair_into_same_aisle():
    lay = Layout(n_aisles=2, bays_per_side=1, levels=1, slots_per_bay_level=1, golden_levels=(1,))
    slots = slot_table(lay)  # 2 slots per aisle, 4 slots total
    v = np.array([10.0, 9.0, 8.0, 1.0])
    cop = np.zeros((4, 4))
    cop[0, 3] = cop[3, 0] = 20.0          # SKU 3 is slow but always bought with SKU 0
    p = place_affinity(v, cop, slots, weight=1.0)
    aisle = slots.set_index("slot_id")["aisle"]
    assert aisle[p[0]] == aisle[p[3]]


def test_order_metrics_single_line_matches_hand_calculation():
    lay = Layout()
    slots = slot_table(lay)
    pt = PickTimes()
    sid = int(slots[(slots.aisle == 0) & (slots.bay == 0) & (slots.level == 3)
                    & (slots.side == 0) & (slots.pos == 0)]["slot_id"].iloc[0])
    m = order_metrics(np.array([7]), np.array([0]), np.array([sid]), slots, lay, pt)
    x, y = lay.aisle_pitch / 2, lay.cross_aisle_width / 2 + 0.5
    walk = 2 * (lay.depot_x - x) + 2 * y
    assert m.loc[7, "walk_m"] == pytest.approx(walk)
    expect = walk / pt.walk_speed_mps + pt.order_setup_s + pt.order_dropoff_s + pt.line_pick_golden_s
    assert m.loc[7, "pick_s"] == pytest.approx(expect)


def test_paired_ci_brackets_the_mean():
    rng = np.random.default_rng(0)
    d = rng.normal(-5, 2, 500)
    m, lo, hi = paired_ci(d, rng, 500)
    assert lo < m < hi and hi < 0


def test_tokens_drop_noise_and_plurals():
    assert tokens("Bag of Organic Bananas") == {"banana"}
    assert "coriander" in tokens("Organic Cilantro", synonyms=True)


def _bb():
    return pd.DataFrame({
        "cat_sku": ["B1", "B2", "B3", "B4"],
        "name": ["Banana - Robusta", "Apple - Shimla", "Mango", "Curd"],
        "category": ["F&V", "F&V", "F&V", "Dairy"],
        "sub_category": ["Fruit", "Fruit", "Fruit", "Dairy"],
        "type": ["t", "t", "t", "Curd"],
        "brand": "x", "price_inr": [20, 100, 50, 30], "market_price": 0,
        "rating": [np.nan, 4.0, 4.5, np.nan]})


def test_mapping_matches_names_then_falls_back_and_reports_depth():
    amap = pd.DataFrame({"src_aisle": ["fruit", "yogurt", "wine"],
                         "bb_category": ["F&V", "Dairy", ""],
                         "bb_sub_category": ["Fruit", "Dairy", ""],
                         "bb_types": ["", "Curd", ""]})
    prods = pd.DataFrame({
        "product_id": [1, 2, 3, 4, 5, 6],
        "product_name": ["Organic Bananas", "Apples", "Kiwi", "Grapes", "Greek Yogurt", "Red Wine"],
        "src_aisle": ["fruit", "fruit", "fruit", "fruit", "yogurt", "wine"],
        "src_department": "d", "picks": [100, 90, 80, 70, 60, 50]})
    assert validate_map(amap, _bb()) == []
    m = assign(prods, amap, _bb()).set_index("product_id")
    assert m.loc[1, "cat_sku"] == "B1"          # banana by name
    assert m.loc[2, "cat_sku"] == "B2"          # apple by name
    assert m.loc[3, "cat_sku"] == "B3"          # no name match: best remaining proxy rank
    assert m.loc[4, "status"] == "bb_depth_exhausted"
    assert m.loc[5, "cat_sku"] == "B4"          # yogurt -> curd via synonym and type filter
    assert m.loc[6, "status"] == "no_bb_category"


def test_validate_map_flags_unknown_targets():
    amap = pd.DataFrame({"src_aisle": ["x"], "bb_category": ["F&V"],
                         "bb_sub_category": ["Nope"], "bb_types": [""]})
    assert validate_map(amap, _bb())
