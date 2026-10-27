"""End-to-end pipeline: `python -m dso.pipeline [build|slotting|replenishment|capacity|kpis|all]`.

Each stage reads what the previous stage wrote (DuckDB tables in
data/work/darkstore.duckdb, small files in results/) so stages can be re-run
on their own.
"""
import json
import sys
import time

import duckdb
import numpy as np
import pandas as pd

from . import capacity as capm
from . import charts, kpis, mapping, slotting
from .config import CFG, CONFIG_DIR, DB_PATH, IMG, RESULTS, SEED, WORK
from .layout import slot_table
from .replenishment import Policy, min_max_from_demand, simulate
from .sources import BigBasketCatalogue, InstacartOrders

CAL_START = pd.Timestamp("2026-01-04")  # a Sunday: Instacart dow 0 is read as Sunday


def connect() -> duckdb.DuckDBPyConnection:
    WORK.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute("SET memory_limit='1500MB'")
    con.execute("SET threads=4")
    con.execute(f"SET temp_directory='{WORK / 'tmp'}'")
    con.execute("SET preserve_insertion_order=false")
    return con


def save_json(name: str, obj) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{name}.json").write_text(json.dumps(obj, indent=2, default=float))


def load_json(name: str):
    return json.loads((RESULTS / f"{name}.json").read_text())


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------- build
def stage_build() -> None:
    con = connect()
    src = InstacartOrders()
    src.register(con)
    log("orders")
    con.execute("CREATE OR REPLACE TABLE orders AS SELECT order_id, split, dow, hour FROM src_orders")
    log("product popularity (prior orders)")
    products = con.execute("""
        SELECT p.product_id, p.product_name, p.src_aisle, p.src_department,
               COALESCE(c.picks, 0) AS picks
        FROM src_products p
        LEFT JOIN (SELECT l.product_id, COUNT(*) AS picks
                   FROM src_lines l JOIN orders o USING (order_id)
                   WHERE o.split = 'prior' GROUP BY 1) c USING (product_id)""").df()

    bb = BigBasketCatalogue().load()
    amap = mapping.load_aisle_map(CONFIG_DIR / "aisle_to_bigbasket.csv")
    bad = mapping.validate_map(amap, bb)
    if bad:
        raise SystemExit(f"aisle map points at unknown BigBasket sub-categories: {bad}")
    missing = set(products["src_aisle"]) - set(amap["src_aisle"])
    if missing:
        raise SystemExit(f"aisles missing from the map: {sorted(missing)}")
    m = mapping.assign(products, amap, bb)

    # assortment: the most-ordered mapped products, capped at the store's range
    mapped = m[m["status"] == "mapped"].sort_values(["picks", "product_id"], ascending=[False, True])
    n_keep = min(CFG.store.assortment_max_skus, CFG.layout.n_slots)
    m["in_assortment"] = m["product_id"].isin(mapped["product_id"].head(n_keep))
    m.loc[(m["status"] == "mapped") & ~m["in_assortment"], "status"] = "outside_assortment"
    sku = m[m["in_assortment"]].sort_values(["picks", "product_id"], ascending=[False, True]).copy()
    sku["sku_id"] = np.arange(len(sku))
    sku = sku[["sku_id", "product_id", "product_name", "src_aisle", "src_department",
               "cat_sku", "name", "bb_category", "bb_sub_category", "type", "brand",
               "price_inr", "picks"]].rename(columns={
                   "name": "sku_name", "bb_category": "category", "bb_sub_category": "sub_category",
                   "product_name": "instacart_product"})
    con.register("sku_df", sku)
    con.execute("CREATE OR REPLACE TABLE sku AS SELECT * FROM sku_df")
    con.register("map_df", m[["product_id", "src_aisle", "src_department", "bb_category",
                              "bb_sub_category", "cat_sku", "picks", "status"]])
    con.execute("CREATE OR REPLACE TABLE product_map AS SELECT * FROM map_df")
    log("order lines restricted to the store range")
    con.execute("""
        CREATE OR REPLACE TABLE lines AS
        SELECT l.order_id, s.sku_id::SMALLINT AS sku_id, l.seq::SMALLINT AS seq
        FROM src_lines l JOIN sku s USING (product_id)""")
    con.execute("""
        CREATE OR REPLACE TABLE store_orders AS
        SELECT o.order_id, o.split, o.dow, o.hour, n.lines
        FROM orders o JOIN (SELECT order_id, COUNT(*) AS lines FROM lines GROUP BY 1) n
        USING (order_id)""")

    # mapping report
    total_lines = int(products["picks"].sum())
    by_status = m.groupby("status").agg(products=("product_id", "size"), lines=("picks", "sum"))
    by_status["share_of_lines"] = by_status["lines"] / total_lines
    aisle_rep = (m.groupby(["src_department", "src_aisle", "bb_category", "bb_sub_category"])
                 .agg(products=("product_id", "size"), lines=("picks", "sum"),
                      lines_in_store=("picks", lambda s: s[m.loc[s.index, "in_assortment"]].sum()))
                 .reset_index())
    aisle_rep["share_in_store"] = aisle_rep["lines_in_store"] / aisle_rep["lines"].clip(lower=1)
    aisle_rep.to_csv(RESULTS / "mapping_by_aisle.csv", index=False)
    n_aisles = amap["src_aisle"].nunique()
    n_mapped_aisles = int((amap["bb_sub_category"] != "").sum())
    dept = (m.assign(mapped=m["bb_sub_category"] != "")
            .groupby("src_department")["mapped"].mean())
    rep = {
        "instacart_products": int(len(products)),
        "instacart_aisles": int(n_aisles),
        "aisles_mapped": n_mapped_aisles,
        "aisles_dropped": sorted(amap.loc[amap["bb_sub_category"] == "", "src_aisle"].tolist()),
        "departments_fully_mapped": int((dept == 1).sum()),
        "departments_partly_mapped": sorted(dept[(dept > 0) & (dept < 1)].index.tolist()),
        "departments_dropped": sorted(dept[dept == 0].index.tolist()),
        "bigbasket_skus_in_catalogue": int(len(bb)),
        "bigbasket_sub_categories_used": int(sku["sub_category"].nunique()),
        "bigbasket_categories_used": int(sku["category"].nunique()),
        "store_skus": int(len(sku)),
        "store_skus_name_matched": int(m.loc[m["in_assortment"], "name_match"].fillna(False).astype(bool).sum()),
        "store_lines_name_matched_share": float(
            (m.loc[m["in_assortment"], "picks"] * m.loc[m["in_assortment"], "name_match"].fillna(False).astype(bool)).sum()
            / m.loc[m["in_assortment"], "picks"].sum()),
        "status": {k: {"products": int(v.products), "lines": int(v.lines),
                       "share_of_lines": float(v.share_of_lines)}
                   for k, v in by_status.iterrows()},
        "store_orders": int(con.execute("SELECT COUNT(*) FROM store_orders").fetchone()[0]),
        "all_orders": int(con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]),
        "store_lines": int(con.execute("SELECT COUNT(*) FROM lines").fetchone()[0]),
    }
    save_json("mapping", rep)
    log(f"mapping: {json.dumps(rep['status'])}")
    con.close()


# --------------------------------------------------------------------------- shared loaders
def load_skus(con) -> pd.DataFrame:
    return con.execute("SELECT * FROM sku ORDER BY sku_id").df()


def velocity(con, skus: pd.DataFrame) -> pd.DataFrame:
    n_prior = con.execute("SELECT COUNT(*) FROM store_orders WHERE split='prior'").fetchone()[0]
    v = skus[["sku_id", "sku_name", "category", "sub_category", "price_inr", "picks"]].copy()
    v["picks_per_day"] = v["picks"] / n_prior * CFG.store.orders_per_day
    v["abc"] = slotting.abc_classes(v["picks"].to_numpy().astype(float))
    return v


def copick_matrix(con, n_sku: int, n_orders: int) -> np.ndarray:
    """Co-picks per pair of SKUs, scaled to per store-day."""
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE aff_orders AS
        SELECT order_id FROM store_orders WHERE split='prior' AND lines > 1
        ORDER BY hash(order_id + {SEED}) LIMIT {n_orders}""")
    pairs = con.execute("""
        WITH l AS (SELECT order_id, sku_id FROM lines SEMI JOIN aff_orders USING (order_id))
        SELECT a.sku_id AS i, b.sku_id AS j, COUNT(*) AS n
        FROM l a JOIN l b ON a.order_id = b.order_id AND a.sku_id < b.sku_id
        GROUP BY 1, 2""").df()
    mat = np.zeros((n_sku, n_sku), dtype=np.float32)
    scale = CFG.store.orders_per_day / n_orders
    mat[pairs["i"], pairs["j"]] = pairs["n"] * scale
    mat[pairs["j"], pairs["i"]] = pairs["n"] * scale
    return mat


# --------------------------------------------------------------------------- slotting
def stage_slotting() -> None:
    con = connect()
    rng = np.random.default_rng(SEED)
    lay, pt = CFG.layout, CFG.pick
    skus = load_skus(con)
    v = velocity(con, skus)
    slots = slot_table(lay)
    log("co-pick counts")
    cop = copick_matrix(con, len(skus), CFG.slot.affinity_orders)

    placements = {
        "random": slotting.place_random(len(skus), slots, rng),
        "category": slotting.place_category(skus, slots),
        "abc_velocity": slotting.place_abc(v["picks"].to_numpy().astype(float), slots),
        "abc_affinity": slotting.place_affinity(v["picks_per_day"].to_numpy(), cop, slots),
    }
    for name, p in placements.items():
        assert len(np.unique(p)) == len(p), name

    # held-out orders: Instacart's 'train' split was not used for velocity or co-picks
    ev = con.execute(f"""
        SELECT l.order_id, l.sku_id FROM lines l
        JOIN (SELECT order_id FROM store_orders WHERE split='train'
              ORDER BY hash(order_id + {SEED}) LIMIT {CFG.slot.eval_orders}) o USING (order_id)
        ORDER BY l.order_id, l.seq""").df()
    oid = ev["order_id"].to_numpy()
    sid = ev["sku_id"].to_numpy().astype(np.int64)
    log(f"routing {ev['order_id'].nunique()} held-out orders x {len(placements)} layouts")
    per = {name: slotting.order_metrics(oid, sid, p, slots, lay, pt, with_nn=True)
           for name, p in placements.items()}

    base = per["category"]
    rows = []
    for name, df in per.items():
        r = {"layout": name,
             "walk_m_mean": df["walk_m"].mean(), "walk_m_median": df["walk_m"].median(),
             "walk_nn_m_mean": df["walk_nn_m"].mean(),
             "pick_s_mean": df["pick_s"].mean(), "pick_min_mean": df["pick_s"].mean() / 60,
             "golden_share": None}
        d_mean, d_lo, d_hi = slotting.paired_ci(df["walk_m"] - base["walk_m"], rng, CFG.slot.bootstrap)
        red, red_lo, red_hi = slotting.ratio_ci(base["walk_m"], df["walk_m"], rng, CFG.slot.bootstrap)
        t_red, t_lo, t_hi = slotting.ratio_ci(base["pick_s"], df["pick_s"], rng, CFG.slot.bootstrap)
        r.update({"walk_diff_vs_category_m": d_mean, "walk_diff_ci": [d_lo, d_hi],
                  "walk_reduction_vs_category": red, "walk_reduction_ci": [red_lo, red_hi],
                  "pick_time_reduction_vs_category": t_red, "pick_time_reduction_ci": [t_lo, t_hi]})
        rows.append(r)
    sl = slots.set_index("slot_id")
    picks = v["picks"].to_numpy().astype(float)
    for r in rows:
        p = placements[r["layout"]]
        r["golden_share"] = float((sl["golden"].to_numpy()[p] * picks).sum() / picks.sum())
        r["aisles_per_order"] = float(pd.DataFrame({"o": oid, "a": sl["aisle"].to_numpy()[p[sid]]})
                                      .groupby("o")["a"].nunique().mean())

    res = {"eval_orders": int(ev["order_id"].nunique()),
           "eval_lines_per_order": float(len(ev) / ev["order_id"].nunique()),
           "layout": {"n_aisles": lay.n_aisles, "aisle_length_m": lay.aisle_length,
                      "aisle_pitch_m": lay.aisle_pitch, "width_m": lay.width,
                      "depth_m": lay.depth, "floor_area_m2": lay.floor_area_m2,
                      "slots": lay.n_slots, "skus": len(skus)},
           "abc": v.groupby("abc").agg(skus=("sku_id", "size"), picks=("picks", "sum"))
                   .assign(share_of_picks=lambda d: d["picks"] / d["picks"].sum())
                   .reset_index().to_dict(orient="records"),
           "results": rows}
    save_json("slotting", res)

    # persist for later stages
    pl = pd.DataFrame({"sku_id": np.arange(len(skus)), **{k: v_ for k, v_ in placements.items()}})
    con.register("pl_df", pl)
    con.execute("CREATE OR REPLACE TABLE placement AS SELECT * FROM pl_df")
    con.register("v_df", v)
    con.execute("CREATE OR REPLACE TABLE velocity AS SELECT * FROM v_df")
    eval_long = pd.concat([d.assign(layout=k).reset_index(names="order_id") for k, d in per.items()])
    con.register("e_df", eval_long)
    con.execute("CREATE OR REPLACE TABLE slotting_eval AS SELECT * FROM e_df")
    top = (v.assign(instacart_product=skus["instacart_product"])
           .sort_values("picks", ascending=False).head(15)
           [["sku_name", "sub_category", "price_inr", "instacart_product", "picks_per_day", "abc"]])
    top.to_csv(RESULTS / "top_skus.csv", index=False)
    # top co-picked pairs, for the README
    iu = np.triu_indices(len(skus), 1)
    vals = cop[iu]
    best = np.argsort(-vals)[:10]
    names = skus["sku_name"].to_numpy()
    pd.DataFrame({"sku_a": names[iu[0][best]], "sku_b": names[iu[1][best]],
                  "copicks_per_day": vals[best]}).to_csv(RESULTS / "top_copick_pairs.csv", index=False)

    charts.walk_before_after(per, IMG / "walk_distance.png")
    charts.layout_heatmaps(slots, placements, v, lay, IMG / "layout_heatmap.png")
    log(json.dumps([{k: r[k] for k in ("layout", "walk_m_mean", "pick_s_mean",
                                        "walk_reduction_vs_category")} for r in rows]))
    con.close()


# --------------------------------------------------------------------------- demand calendar
def demand_calendar(con, n_days: int, rng) -> tuple:
    """Synthetic store calendar built from real Instacart baskets.

    Instacart orders carry day-of-week and hour but no date. For each
    calendar day we draw the day's order count from a Poisson distribution
    whose mean is the store volume times that weekday's share of Instacart
    orders, then draw that many real orders (with their basket and hour) from
    the Instacart orders placed on the same weekday.
    """
    pool = con.execute(f"""
        SELECT order_id, dow, hour FROM store_orders WHERE split='prior'
        ORDER BY hash(order_id + {SEED + 1}) LIMIT 600000""").df()
    lines = con.execute("""
        SELECT l.order_id, l.sku_id FROM lines l
        JOIN (SELECT order_id FROM store_orders WHERE split='prior'
              ORDER BY hash(order_id + {s}) LIMIT 600000) p USING (order_id)
        ORDER BY l.order_id, l.seq""".format(s=SEED + 1)).df()
    pool = pool.sort_values("order_id").reset_index(drop=True)
    starts = np.searchsorted(lines["order_id"].to_numpy(), pool["order_id"].to_numpy())
    ends = np.r_[starts[1:], len(lines)]
    sku_arr = lines["sku_id"].to_numpy().astype(np.int64)
    dow_share = con.execute("SELECT dow, COUNT(*) FROM store_orders GROUP BY 1 ORDER BY 1").fetchall()
    share = np.array([c for _, c in dow_share], float)
    share /= share.sum()
    by_dow = {d: np.flatnonzero(pool["dow"].to_numpy() == d) for d in range(7)}
    hours = pool["hour"].to_numpy()

    days, headers = [], []
    for t in range(n_days):
        d = t % 7
        n = rng.poisson(CFG.store.orders_per_day * 7 * share[d])
        pick = rng.choice(by_dow[d], size=n, replace=True)
        minute = hours[pick] * 60 + rng.uniform(0, 60, n)
        seq = np.argsort(minute)
        pick, minute = pick[seq], minute[seq]
        lens = ends[pick] - starts[pick]
        idx = np.concatenate([np.arange(starts[i], ends[i]) for i in pick]) if n else np.array([], int)
        oidx = np.repeat(np.arange(n), lens)
        days.append((oidx, sku_arr[idx]))
        headers.append(pd.DataFrame({"day": t, "order_seq": np.arange(n),
                                     "src_order_id": pool["order_id"].to_numpy()[pick],
                                     "minute_of_day": minute, "lines": lens}))
    return days, pd.concat(headers, ignore_index=True)


# --------------------------------------------------------------------------- replenishment
def stage_replenishment() -> None:
    con = connect()
    rng = np.random.default_rng(SEED)
    rc = CFG.repl
    skus = load_skus(con)
    n = len(skus)
    price = skus["price_inr"].to_numpy()
    log("demand calendar")
    days, headers = demand_calendar(con, rc.history_days + rc.sim_days, rng)
    hist = np.stack([np.bincount(s, minlength=n) for _, s in days[:rc.history_days]])
    mu, sd = hist.mean(axis=0), hist.std(axis=0, ddof=1)
    sim_days = days[rc.history_days:]

    rows, keep = [], None
    for sl_ in rc.service_levels:
        s, S = min_max_from_demand(mu, sd, sl_, rc.lead_time_days, rc.review_period_days,
                                   rc.max_cover_days)
        is_chosen = np.isclose(sl_, rc.chosen_service_level)
        r = simulate(Policy(f"minmax_{sl_:.3f}", s, S), sim_days, n, rc.lead_time_days,
                     keep_log=is_chosen)
        r.update(family="velocity min/max", service_level=sl_)
        if is_chosen:
            keep = (r["policy"], r.pop("short_log"), r.pop("inventory_log"), s, S)
        rows.append(r)
    for k in rc.naive_min_units:
        s = np.full(n, k)
        S = np.full(n, 2 * k)
        r = simulate(Policy(f"naive_{k}", s, S), sim_days, n, rc.lead_time_days)
        r.update(family="naive fixed min/max", service_level=None, min_units=k)
        rows.append(r)
    for k in rc.cover_min_days:
        s = np.ceil(mu * k).astype(np.int64)
        S = s + np.maximum(1, np.ceil(mu * rc.max_cover_days)).astype(np.int64)
        r = simulate(Policy(f"cover_{k:g}d", s, S), sim_days, n, rc.lead_time_days)
        r.update(family="days-of-cover min/max", service_level=None, min_days=k)
        rows.append(r)
    sim_dem = sum(np.bincount(s_, minlength=n) for _, s_ in sim_days) / len(sim_days)
    for r in rows:
        inv = r.pop("avg_inventory_by_sku")
        r["avg_inventory_value_inr"] = float((inv * price).sum())
        r["days_of_cover"] = float(inv.sum() / sim_dem.sum())
    tbl = pd.DataFrame(rows)
    tbl.to_csv(RESULTS / "replenishment_tradeoff.csv", index=False)

    chosen_name, short_log, inv_log, s, S = keep
    # policy parameters for the chosen service level
    params = skus[["sku_id", "sku_name", "category", "sub_category", "price_inr"]].copy()
    params["mean_daily_demand"] = mu
    params["sd_daily_demand"] = sd
    params["min_units"] = s
    params["max_units"] = S
    params.to_csv(RESULTS / "minmax_parameters.csv", index=False)

    # operations log for the KPI stage
    hdr = headers[headers["day"] >= rc.history_days].copy()
    hdr["day"] -= rc.history_days
    line_rows = []
    for t, ((oidx, sku), short) in enumerate(zip(sim_days, short_log)):
        line_rows.append(pd.DataFrame({"day": t, "order_seq": oidx, "sku_id": sku, "short": short}))
    lines_log = pd.concat(line_rows, ignore_index=True)
    con.register("h_df", hdr)
    con.execute("CREATE OR REPLACE TABLE sim_orders AS SELECT * FROM h_df")
    con.register("l_df", lines_log)
    con.execute("CREATE OR REPLACE TABLE sim_lines AS SELECT * FROM l_df")
    con.register("i_df", inv_log)
    con.execute("CREATE OR REPLACE TABLE sim_inventory AS SELECT * FROM i_df")

    chosen = tbl[tbl["policy"] == chosen_name].iloc[0].to_dict()
    def nearest(fam):
        # the baseline policy that holds about the same stock as the chosen one
        d = tbl[tbl["family"] == fam]
        return d.iloc[(d["avg_inventory_units"] - chosen["avg_inventory_units"]).abs().argsort()].iloc[0].to_dict()

    def stock_for_fill(fam, fill):
        # stock a baseline needs to reach the chosen policy's fill rate (linear interpolation)
        d = tbl[tbl["family"] == fam].sort_values("avg_inventory_units")
        if d["line_fill_rate"].max() < fill:
            return None
        return float(np.interp(fill, d["line_fill_rate"], d["avg_inventory_units"]))
    save_json("replenishment", {
        "history_days": rc.history_days, "sim_days": rc.sim_days,
        "lead_time_days": rc.lead_time_days, "review_period_days": rc.review_period_days,
        "mean_orders_per_day": float(hdr.groupby("day").size().mean()),
        "chosen": chosen,
        "naive_at_similar_stock": nearest("naive fixed min/max"),
        "cover_at_similar_stock": nearest("days-of-cover min/max"),
        "cover_stock_for_same_fill": stock_for_fill("days-of-cover min/max", chosen["line_fill_rate"]),
        "naive_stock_for_same_fill": stock_for_fill("naive fixed min/max", chosen["line_fill_rate"]),
        "table": tbl.to_dict(orient="records")})
    charts.tradeoff_curve(tbl, IMG / "inventory_tradeoff.png")
    log(tbl[["policy", "line_fill_rate", "stockout_skuday_rate", "avg_inventory_units",
             "avg_inventory_value_inr"]].to_string())
    con.close()


# --------------------------------------------------------------------------- capacity
def stage_capacity() -> None:
    con = connect()
    cc = CFG.cap
    orders = con.execute("SELECT dow, hour FROM store_orders").df()
    prof = capm.hourly_profile(orders)
    ev = con.execute("SELECT * FROM slotting_eval").df()
    picks_min = {k: (d["pick_s"] / 60).to_numpy() for k, d in ev.groupby("layout")}
    out = {"wait_target_min": cc.wait_target_min, "wait_target_share": cc.wait_target_share}
    plans = {}
    for layout in ("category", "abc_velocity"):
        mean_pick = float(picks_min[layout].mean())
        plan = capm.staffing_plan(prof, CFG.store.orders_per_day, mean_pick,
                                  cc.wait_target_min, cc.wait_target_share)
        plans[layout] = plan
        peak = plan.loc[plan["orders_per_hour"].idxmax()]
        out[layout] = {
            "mean_pick_min": mean_pick,
            "cv_pick": float(picks_min[layout].std() / mean_pick),
            "peak_dow": int(peak["dow"]), "peak_hour": int(peak["hour"]),
            "peak_orders_per_hour": float(peak["orders_per_hour"]),
            "peak_pickers": int(peak["pickers"]),
            "picker_hours_per_week": float(plan["pickers"].sum()),
            "orders_per_picker_hour": float(plan["orders_per_hour"].sum() / plan["pickers"].sum()),
            "max_orders_per_hour_pickers": capm.max_rate_for(
                cc.max_pickers_on_floor, 1 / mean_pick, cc.wait_target_min, cc.wait_target_share) * 60,
        }
    pack_cap = cc.pack_stations * 60 / (cc.pack_time_s / 60) * 0.85  # keep stations <= 85% busy
    peak_share = prof["share_of_week"].max() * 7  # peak hour as a share of an average day
    abc = out["abc_velocity"]
    limit = min(abc["max_orders_per_hour_pickers"], pack_cap)
    out["throughput"] = {
        "max_pickers_on_floor": cc.max_pickers_on_floor,
        "picker_limit_orders_per_hour": abc["max_orders_per_hour_pickers"],
        "pack_limit_orders_per_hour": pack_cap,
        "binding": "pickers" if abc["max_orders_per_hour_pickers"] < pack_cap else "pack stations",
        "store_limit_orders_per_hour": limit,
        "peak_hour_share_of_day": peak_share,
        "max_orders_per_day_at_this_profile": limit / peak_share,
    }
    # new-store / peak-day planning grid
    grid = []
    for vol in (1000, 1500, 2000, 2500, 3000, 4000, 5000):
        p = capm.staffing_plan(prof, vol, abc["mean_pick_min"], cc.wait_target_min, cc.wait_target_share)
        grid.append({"orders_per_day": vol, "peak_orders_per_hour": float(p["orders_per_hour"].max()),
                     "peak_pickers": int(p["pickers"].max()),
                     "picker_hours_per_day": float(p["pickers"].sum() / 7),
                     "feasible_on_floor": bool(p["pickers"].max() <= cc.max_pickers_on_floor)
                     and float(p["orders_per_hour"].max()) <= pack_cap})
    out["planning_grid"] = grid
    pd.DataFrame(grid).to_csv(RESULTS / "capacity_planning_grid.csv", index=False)

    log("SimPy check of the staffing plan")
    # Erlang C is a steady-state formula; when load climbs hour to hour the
    # queue lags behind. Replay the plan in SimPy and add a picker to any busy
    # hour that misses the target, then re-check.
    plan = plans["abc_velocity"].copy()
    plan["pickers_erlang"] = plan["pickers"]
    rounds = []
    for rnd in range(cc.des_rounds + 1):
        sim = capm.simulate_week(plan, picks_min["abc_velocity"], cc.pack_time_s / 60,
                                 cc.pack_stations, cc.des_days, SEED)  # same random stream each round
        hourly = sim.groupby(["dow", "hour"]).agg(
            orders=("wait_min", "size"),
            share_within=("wait_min", lambda w: float((w <= cc.wait_target_min).mean())))
        busy = hourly[hourly["orders"] >= 20 * cc.des_days / 7]
        fail = busy[busy["share_within"] < cc.wait_target_share].index
        rounds.append({"round": rnd, "picker_hours_per_week": int(plan["pickers"].sum()),
                       "share_within_target": float((sim["wait_min"] <= cc.wait_target_min).mean()),
                       "worst_busy_hour_share_within": float(busy["share_within"].min()),
                       "busy_hours_failing": int(len(fail))})
        if len(fail) == 0 or rnd == cc.des_rounds:
            break
        idx = plan.set_index(["dow", "hour"]).index.isin(fail)
        plan.loc[idx, "pickers"] += 1
    plans["abc_velocity"] = plan
    out["des"] = {
        "weeks": cc.des_days / 7, "orders": int(len(sim)), "rounds": rounds,
        "share_within_target": float((sim["wait_min"] <= cc.wait_target_min).mean()),
        "mean_wait_min": float(sim["wait_min"].mean()),
        "p90_wait_min": float(sim["wait_min"].quantile(0.9)),
        "p90_click_to_ready_min": float(sim["ready_min"].quantile(0.9)),
        "mean_click_to_ready_min": float(sim["ready_min"].mean()),
        "picker_hours_per_week_erlang": int(plan["pickers_erlang"].sum()),
        "picker_hours_per_week_final": int(plan["pickers"].sum()),
        "peak_pickers_final": int(plan["pickers"].max()),
    }
    plan.to_csv(RESULTS / "staffing_plan_by_hour.csv", index=False)
    save_json("capacity", out)
    charts.hourly_staffing(plans["abc_velocity"], IMG / "hourly_load_staffing.png")
    charts.dow_hour_heatmap(prof, CFG.store.orders_per_day, IMG / "orders_heatmap.png")
    log(json.dumps(out["throughput"]))
    log(json.dumps(out["des"]))
    con.close()


# --------------------------------------------------------------------------- KPIs
def stage_kpis() -> None:
    con = connect()
    lay, pt = CFG.layout, CFG.pick
    slots = slot_table(lay)
    place = con.execute("SELECT abc_velocity FROM placement ORDER BY sku_id").df()["abc_velocity"].to_numpy()
    sl = con.execute("SELECT day, order_seq, sku_id FROM sim_lines ORDER BY day, order_seq").df()
    key = sl["day"].to_numpy().astype(np.int64) * 100000 + sl["order_seq"].to_numpy()
    m = slotting.order_metrics(key, sl["sku_id"].to_numpy().astype(np.int64), place, slots, lay, pt)
    m = m.reset_index(names="key")
    m["day"] = m["key"] // 100000
    m["order_seq"] = m["key"] % 100000
    con.register("m_df", m[["day", "order_seq", "walk_m", "pick_s"]])
    con.execute("""
        CREATE OR REPLACE TABLE sim_orders AS
        SELECT o.*, m.walk_m, m.pick_s,
               DATE '{d}' + o.day::INTEGER AS date,
               (o.minute_of_day // 60)::INTEGER AS hour
        FROM sim_orders o JOIN m_df m USING (day, order_seq)""".format(d=CAL_START.date()))
    kpis.create_views(con)
    kpis.export(con, RESULTS)
    kpis.dashboard(con, RESULTS / "dashboard.html", IMG)
    con.close()


STAGES = {"build": stage_build, "slotting": stage_slotting,
          "replenishment": stage_replenishment, "capacity": stage_capacity, "kpis": stage_kpis}


def main(argv) -> None:
    names = argv[1:] or ["all"]
    if names == ["all"]:
        names = list(STAGES)
    RESULTS.mkdir(parents=True, exist_ok=True)
    IMG.mkdir(parents=True, exist_ok=True)
    for n in names:
        log(f"== {n}")
        STAGES[n]()


if __name__ == "__main__":
    main(sys.argv)
