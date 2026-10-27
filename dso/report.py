"""Write the results tables into results/summary.md and into README.md
(between the results markers), so the README always shows what the last
`make all` produced."""
import json
import re

import pandas as pd

from .config import CFG, RESULTS, ROOT

START, END = "<!-- results:start -->", "<!-- results:end -->"
LAYOUT_NAME = {"random": "Random placement", "category": "By category (baseline)",
               "abc_velocity": "ABC by velocity", "abc_affinity": "ABC + co-pick affinity"}
DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _j(name):
    return json.loads((RESULTS / f"{name}.json").read_text())


def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |",
           "|" + "|".join("---:" if pd.api.types.is_numeric_dtype(df[c]) else "---" for c in cols) + "|"]
    for r in df.itertuples(index=False):
        out.append("| " + " | ".join(str(v) for v in r) + " |")
    return "\n".join(out)


def pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def build() -> str:
    mp, sl, rp, cp = _j("mapping"), _j("slotting"), _j("replenishment"), _j("capacity")
    st = mp["status"]
    parts = []

    parts.append("### Product mapping (Instacart → BigBasket)\n")
    parts.append(_md(pd.DataFrame([
        ["Instacart aisles mapped to a BigBasket category", f"{mp['aisles_mapped']} of {mp['instacart_aisles']}"],
        ["Instacart departments fully mapped", f"{mp['departments_fully_mapped']} of 21 "
         f"(partly: {', '.join(mp['departments_partly_mapped'])}; dropped: {', '.join(mp['departments_dropped'])})"],
        ["Aisles dropped (no Indian counterpart or unlabelled)", ", ".join(mp["aisles_dropped"])],
        ["Order lines in dropped aisles", pct(st["no_bb_category"]["share_of_lines"])],
        ["Order lines on Instacart products beyond BigBasket's range depth", pct(st["bb_depth_exhausted"]["share_of_lines"])],
        ["Order lines on mapped products outside the 3,000-SKU store range", pct(st["outside_assortment"]["share_of_lines"])],
        ["Order lines the store range covers", pct(st["mapped"]["share_of_lines"])],
        ["Orders with at least one line in the range", f"{mp['store_orders']:,} of {mp['all_orders']:,}"],
        ["BigBasket categories / sub-categories in the store", f"{mp['bigbasket_categories_used']} / {mp['bigbasket_sub_categories_used']}"],
        ["Store SKUs matched to a BigBasket SKU by a shared name word",
         f"{mp['store_skus_name_matched']:,} of {mp['store_skus']:,} ({pct(mp['store_lines_name_matched_share'])} of store picks)"],
    ], columns=["Item", "Value"])))

    lay = sl["layout"]
    parts.append(f"\n\n### 1. Slotting ({sl['eval_orders']:,} held-out orders, "
                 f"{sl['eval_lines_per_order']:.1f} lines each on average)\n")
    rows = []
    for r in sl["results"]:
        base = r["layout"] == "category"
        rows.append([LAYOUT_NAME[r["layout"]], f"{r['walk_m_mean']:.1f}", f"{r['walk_nn_m_mean']:.1f}",
                     f"{r['pick_min_mean']:.2f}", f"{r['aisles_per_order']:.2f}", pct(r["golden_share"], 0),
                     "—" if base else f"{pct(r['walk_reduction_vs_category'])} "
                     f"({pct(r['walk_reduction_ci'][0])} to {pct(r['walk_reduction_ci'][1])})",
                     "—" if base else f"{pct(r['pick_time_reduction_vs_category'])} "
                     f"({pct(r['pick_time_reduction_ci'][0])} to {pct(r['pick_time_reduction_ci'][1])})"])
    parts.append(_md(pd.DataFrame(rows, columns=[
        "Layout", "Walk / order, m (S-shape)", "Walk / order, m (nearest-neighbour)",
        "Pick time / order, min", "Aisles visited / order", "Picks at waist height",
        "Walk cut vs baseline (95% CI)", "Pick-time cut vs baseline (95% CI)"])))
    abc = {r["layout"]: r for r in sl["results"]}["abc_velocity"]
    parts.append(f"\n\nPaired difference, ABC by velocity minus baseline: {abc['walk_diff_vs_category_m']:.1f} m "
                 f"per order (95% CI {abc['walk_diff_ci'][0]:.1f} to {abc['walk_diff_ci'][1]:.1f}). "
                 f"ABC classes: " + ", ".join(f"{a['abc']} = {a['skus']:,} SKUs, {pct(a['share_of_picks'], 0)} of picks"
                                              for a in sl["abc"]) + ".")

    parts.append(f"\n\n### 2. Replenishment ({rp['sim_days']} simulated days after {rp['history_days']} days of "
                 f"history, ~{rp['mean_orders_per_day']:,.0f} orders/day, lead time {rp['lead_time_days']} day, daily review)\n")
    t = pd.DataFrame(rp["table"])
    t["Policy"] = [
        f"Min/max, {r.service_level:.1%} service level".replace(".0%", "%") if r.family == "velocity min/max"
        else (f"Days of cover: min = {r.min_days:g} d" if r.family == "days-of-cover min/max"
              else f"Same for every SKU: min {r.min_units:.0f}, max {2 * r.min_units:.0f}")
        for r in t.itertuples()]
    show = pd.DataFrame({
        "Policy": t["Policy"],
        "Line fill rate": t["line_fill_rate"].map(lambda v: pct(v, 2)),
        "Orders complete": t["perfect_order_rate"].map(lambda v: pct(v, 1)),
        "SKU-days with lost sales": t["stockout_skuday_rate"].map(lambda v: pct(v, 2)),
        "Avg stock, units": t["avg_inventory_units"].map(lambda v: f"{v:,.0f}"),
        "Avg stock, ₹ lakh": (t["avg_inventory_value_inr"] / 1e5).map(lambda v: f"{v:,.1f}"),
        "Days of cover": t["days_of_cover"].map(lambda v: f"{v:.1f}"),
        "DC order lines / day": t["replen_lines_per_day"].map(lambda v: f"{v:,.0f}"),
    })
    parts.append(_md(show))
    ch, cv = rp["chosen"], rp["cover_at_similar_stock"]
    extra = ""
    if rp.get("cover_stock_for_same_fill"):
        extra = (f" To reach the same fill rate, the days-of-cover rule needs about "
                 f"{rp['cover_stock_for_same_fill']:,.0f} units "
                 f"({rp['cover_stock_for_same_fill'] / ch['avg_inventory_units'] - 1:+.0%} stock).")
    parts.append(f"\n\nAt about the same stock, the 95% min/max loses {pct(1 - ch['line_fill_rate'], 2)} of lines "
                 f"against {pct(1 - cv['line_fill_rate'], 2)} for a {cv['min_days']:g}-day cover rule." + extra)

    a, c = cp["abc_velocity"], cp["category"]
    th = cp["throughput"]
    des = cp["des"]
    parts.append(f"\n\n### 3. Capacity ({CFG.store.orders_per_day:,} orders/day, target: "
                 f"{pct(cp['wait_target_share'], 0)} of orders start picking within {cp['wait_target_min']:g} min)\n")
    parts.append(_md(pd.DataFrame([
        ["Peak hour", f"{DOW[a['peak_dow']]} {a['peak_hour']:02d}:00, {a['peak_orders_per_hour']:.0f} orders/hour"],
        ["Mean pick time (ABC layout / baseline layout)", f"{a['mean_pick_min']:.2f} / {c['mean_pick_min']:.2f} min"],
        ["Pickers needed at peak, Erlang C (ABC / baseline)", f"{a['peak_pickers']} / {c['peak_pickers']}"],
        ["Picker-hours per week, Erlang C (ABC / baseline)", f"{a['picker_hours_per_week']:,.0f} / {c['picker_hours_per_week']:,.0f}"],
        ["Orders per picker-hour (ABC / baseline)", f"{a['orders_per_picker_hour']:.1f} / {c['orders_per_picker_hour']:.1f}"],
        ["Picker-hours per week after the SimPy check", f"{des['picker_hours_per_week_final']:,} "
         f"(+{des['picker_hours_per_week_final'] - des['picker_hours_per_week_erlang']} over Erlang C)"],
        ["SimPy: orders starting within target", pct(des["share_within_target"])],
        ["SimPy: mean / 90th percentile wait for a picker", f"{des['mean_wait_min']:.2f} / {des['p90_wait_min']:.2f} min"],
        ["SimPy: mean / 90th percentile order-to-packed time", f"{des['mean_click_to_ready_min']:.1f} / {des['p90_click_to_ready_min']:.1f} min"],
        ["Throughput limit, pickers (max {0} on the floor)".format(th["max_pickers_on_floor"]),
         f"{th['picker_limit_orders_per_hour']:.0f} orders/hour"],
        [f"Throughput limit, pack stations ({CFG.cap.pack_stations} at {CFG.cap.pack_time_s:.0f} s, ≤85% busy)",
         f"{th['pack_limit_orders_per_hour']:.0f} orders/hour"],
        ["Binding limit", f"{th['binding']}: {th['store_limit_orders_per_hour']:.0f} orders/hour"],
        ["Max orders/day with this weekly pattern", f"{th['max_orders_per_day_at_this_profile']:,.0f}"],
    ], columns=["Item", "Value"])))
    g = pd.DataFrame(cp["planning_grid"])
    parts.append("\n\nPlanning grid (peak-day and new-store sizing, ABC layout):\n\n" + _md(pd.DataFrame({
        "Orders/day": g["orders_per_day"].map(lambda v: f"{v:,}"),
        "Peak orders/hour": g["peak_orders_per_hour"].map(lambda v: f"{v:.0f}"),
        "Pickers at peak": g["peak_pickers"],
        "Picker-hours/day": g["picker_hours_per_day"].map(lambda v: f"{v:.0f}"),
        "Fits this store": g["feasible_on_floor"].map({True: "yes", False: "no"}),
    })))

    latest = json.loads((RESULTS / "kpi" / "latest.json").read_text())
    parts.append("\n\n### 4. KPI snapshot (last simulated week, from the SQL views)\n")
    parts.append(_md(pd.DataFrame(list(latest.items()), columns=["KPI", "Value"])))
    return "\n".join(parts) + "\n"


def write() -> None:
    body = build()
    (RESULTS / "summary.md").write_text("# Results\n\n" + body)
    readme = ROOT / "README.md"
    if readme.exists():
        txt = readme.read_text()
        if START in txt and END in txt:
            txt = re.sub(re.escape(START) + ".*?" + re.escape(END),
                         lambda _: f"{START}\n{body}{END}", txt, flags=re.S)
            readme.write_text(txt)
