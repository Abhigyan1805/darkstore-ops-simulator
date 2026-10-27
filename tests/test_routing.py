import numpy as np
import pytest

from dso.config import Layout
from dso.layout import slot_table
from dso.routing import (nearest_neighbour_distance, point_distance,
                         s_shape_batch, s_shape_distance)

DEPTH = 10.0
DEPOT = 5.0


def test_point_distance_same_aisle_is_straight_walk():
    assert point_distance(2, 3, 2, 8, DEPTH) == pytest.approx(5)


def test_point_distance_takes_shorter_cross_aisle():
    # both near the front: go via the front (3 + 2 = 5) plus 4 across
    assert point_distance(0, 3, 4, 2, DEPTH) == pytest.approx(4 + 5)
    # both near the back: via back = (10-9) + (10-8) = 3
    assert point_distance(0, 9, 4, 8, DEPTH) == pytest.approx(4 + 3)


def test_s_shape_single_aisle_is_out_and_back():
    # aisle at x=1, farthest pick at y=6: walk 4 across, 6 in, 6 out, 4 back
    assert s_shape_distance([1, 1], [2, 6], DEPOT, DEPTH) == pytest.approx(4 + 6 + 6 + 4)


def test_s_shape_two_aisles_full_traversal():
    # two aisles at x=1 and x=9: traverse both fully (2 x 10) + horizontal
    # 4 (depot->1) + 8 (1->9) + 4 (9->depot)
    assert s_shape_distance([1, 9], [3, 3], DEPOT, DEPTH) == pytest.approx(20 + 16)


def test_s_shape_three_aisles_returns_in_cheaper_end_aisle():
    # aisles 1, 5, 9; picks at y=8 (aisle 1), y=5 (aisle 5), y=2 (aisle 9)
    # 2 traversals + return in aisle 9 (2*2=4, cheaper than 2*8)
    d = s_shape_distance([1, 5, 9], [8, 5, 2], DEPOT, DEPTH)
    assert d == pytest.approx(2 * DEPTH + 4 + 16)


def test_s_shape_batch_matches_single():
    rng = np.random.default_rng(0)
    oid, xs, ys = [], [], []
    for o in range(50):
        n = rng.integers(1, 12)
        oid += [o] * n
        xs += list(rng.choice([1.0, 3.0, 5.0, 7.0, 9.0], n))
        ys += list(rng.uniform(0.5, 9.5, n))
    batch = s_shape_batch(np.array(oid), np.array(xs), np.array(ys), DEPOT, DEPTH)
    oid = np.array(oid)
    for o in range(50):
        m = oid == o
        assert batch[o] == pytest.approx(
            s_shape_distance(np.array(xs)[m], np.array(ys)[m], DEPOT, DEPTH))


def test_nearest_neighbour_simple_line():
    # one aisle at the depot's x: walk to y=7 and back
    assert nearest_neighbour_distance([5, 5, 5], [2, 4, 7], DEPOT, DEPTH) == pytest.approx(14)


def test_nn_never_beats_lower_bound():
    # any tour must at least reach the farthest point and come back
    x, y = [1, 9, 3], [9, 1, 5]
    lb = 2 * max(abs(xi - DEPOT) + yi for xi, yi in zip(x, y))
    assert nearest_neighbour_distance(x, y, DEPOT, DEPTH) >= lb - 1e-9


def test_slot_table_size_and_coordinates():
    lay = Layout()
    st = slot_table(lay)
    assert len(st) == lay.n_slots == 3600
    assert st["x"].min() == pytest.approx(lay.aisle_pitch / 2)
    assert st["y"].max() < lay.depth
    assert st["slot_id"].is_unique
