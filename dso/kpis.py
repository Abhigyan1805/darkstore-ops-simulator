"""Automated KPI layer: SQL views, CSV/Excel export, and a static HTML dashboard."""
import base64
import html
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from . import charts  # noqa: E402  (sets the shared chart style)
from .config import SQL_DIR  # noqa: E402

EXPORTS = ["kpi_daily", "kpi_weekly", "kpi_hourly", "kpi_category_daily", "kpi_sku_stockouts"]


def create_views(con) -> None:
    con.execute((SQL_DIR / "kpi_views.sql").read_text())


def export(con, out_dir) -> None:
    kdir = out_dir / "kpi"
    kdir.mkdir(parents=True, exist_ok=True)
    frames = {v: con.execute(f"SELECT * FROM {v}").df() for v in EXPORTS}
    for v, df in frames.items():
        df.to_csv(kdir / f"{v}.csv", index=False)
    with pd.ExcelWriter(kdir / "darkstore_kpis.xlsx", engine="openpyxl") as xw:
        for v, df in frames.items():
            d = df.copy()
            for c in d.columns:
                if pd.api.types.is_datetime64_any_dtype(d[c]):
                    d[c] = d[c].dt.date
            d.head(100000).to_excel(xw, sheet_name=v.replace("kpi_", "")[:31], index=False)
            ws = xw.sheets[v.replace("kpi_", "")[:31]]
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in list(col)[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 40)


def _img(path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def _table(df: pd.DataFrame, fmt: dict = None) -> str:
    fmt = fmt or {}
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    rows = []
    for r in df.itertuples(index=False):
        cells = []
        for c, v in zip(df.columns, r):
            f = fmt.get(c)
            s = f(v) if f else (f"{v:,.2f}" if isinstance(v, float) else str(v))
            num = isinstance(v, (int, float)) and not isinstance(v, bool)
            cells.append(f"<td class='{'num' if num else ''}'>{html.escape(s)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _daily_chart(daily: pd.DataFrame, path) -> None:
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(10, 7), sharex=True)
    a1.plot(daily["date"], daily["orders"], color=charts.BLUE, lw=2)
    a1.set_ylabel("orders")
    a1.set_title("Daily orders, pick time and line fill rate (simulated 13 weeks)")
    a2.plot(daily["date"], daily["avg_pick_min"], color=charts.BLUE, lw=2)
    a2.set_ylabel("avg pick, min")
    a3.plot(daily["date"], daily["line_fill_rate"] * 100, color=charts.BLUE, lw=2)
    a3.set_ylabel("line fill, %")
    fig.autofmt_xdate()
    charts._save(fig, path)


def dashboard(con, out_path, img_dir) -> None:
    daily = con.execute("SELECT * FROM kpi_daily").df()
    weekly = con.execute("SELECT * FROM kpi_weekly").df()
    worst = con.execute("SELECT * FROM kpi_sku_stockouts LIMIT 15").df()
    cat = con.execute("""SELECT category, SUM(lines) AS lines, SUM(short_lines) AS short_lines,
                         ROUND(1 - SUM(short_lines) / SUM(lines), 4) AS line_fill_rate
                         FROM kpi_category_daily GROUP BY 1 ORDER BY line_fill_rate""").df()
    _daily_chart(daily, img_dir / "kpi_daily.png")
    last = daily.tail(7)
    tiles = [
        ("Orders / day", f"{last['orders'].mean():,.0f}", "last 7 days, mean"),
        ("Peak orders / hour", f"{last['peak_orders_per_hour'].max():,.0f}", "last 7 days, max"),
        ("Avg pick time", f"{(last['avg_pick_min'] * last['orders']).sum() / last['orders'].sum():.2f} min",
         "per order, pick list to pack station"),
        ("Avg walk", f"{(last['avg_walk_m'] * last['orders']).sum() / last['orders'].sum():.0f} m",
         "per order, S-shape route"),
        ("Line fill rate", f"{(last['line_fill_rate'] * last['lines']).sum() / last['lines'].sum():.2%}",
         "lines picked / lines ordered"),
        ("Perfect orders", f"{(last['perfect_order_rate'] * last['orders']).sum() / last['orders'].sum():.1%}",
         "orders with no missing line"),
        ("SKUs with lost sales", f"{last['skus_with_lost_sales'].mean():.0f} / day",
         "of the store range, last 7 days"),
        ("Stock on hand", f"₹{last['closing_stock_value_inr'].iloc[-1] / 1e5:.1f} lakh",
         "at selling price, last close"),
    ]
    tiles_html = "".join(f"<div class='tile'><div class='lab'>{html.escape(a)}</div>"
                         f"<div class='val'>{html.escape(b)}</div><div class='sub'>{html.escape(c)}</div></div>"
                         for a, b, c in tiles)
    pct = lambda v: f"{v:.2%}"  # noqa: E731
    d_show = daily.tail(14).copy()
    d_show["date"] = d_show["date"].dt.strftime("%Y-%m-%d")
    w_show = weekly.copy()
    w_show["week_starting_sun"] = pd.to_datetime(w_show["week_starting_sun"]).dt.strftime("%Y-%m-%d")
    imgs = [("kpi_daily.png", "Daily trend"), ("walk_distance.png", "Slotting: walk per order"),
            ("layout_heatmap.png", "Slotting: where picks happen"),
            ("inventory_tradeoff.png", "Replenishment trade-off"),
            ("hourly_load_staffing.png", "Capacity: load vs pickers"),
            ("orders_heatmap.png", "Capacity: weekly load pattern")]
    figs = "".join(f"<figure><img alt='{html.escape(t)}' src='{_img(img_dir / f)}'>"
                   f"<figcaption>{html.escape(t)}</figcaption></figure>"
                   for f, t in imgs if (img_dir / f).exists())
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dark Store KPIs</title>
<style>
:root {{ --surface:#fcfcfb; --panel:#ffffff; --ink:#0b0b0b; --ink2:#52514e; --line:#e4e3df; --accent:#2a78d6; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --surface:#1a1a19; --panel:#232322; --ink:#ffffff; --ink2:#c3c2b7; --line:#3a3a38; --accent:#3987e5; }} }}
:root[data-theme="dark"] {{ --surface:#1a1a19; --panel:#232322; --ink:#ffffff; --ink2:#c3c2b7; --line:#3a3a38; --accent:#3987e5; }}
body {{ margin:0; background:var(--surface); color:var(--ink);
  font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:16px; margin:32px 0 10px; }}
.note {{ color:var(--ink2); margin:0 0 18px; }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:10px; }}
.tile {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px 14px; }}
.lab {{ color:var(--ink2); font-size:12px; }} .val {{ font-size:22px; font-weight:650; margin:2px 0; }}
.sub {{ color:var(--ink2); font-size:11px; }}
.scroll {{ overflow-x:auto; border:1px solid var(--line); border-radius:8px; background:var(--panel); }}
table {{ border-collapse:collapse; width:100%; font-size:12.5px; }}
th, td {{ padding:6px 10px; border-bottom:1px solid var(--line); white-space:nowrap; text-align:left; }}
th {{ color:var(--ink2); font-weight:600; position:sticky; top:0; background:var(--panel); }}
td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
figure {{ margin:0 0 18px; background:#fcfcfb; border:1px solid var(--line); border-radius:8px; padding:8px; }}
figure img {{ width:100%; height:auto; display:block; }}
figcaption {{ color:#52514e; font-size:12px; padding-top:4px; }}
</style></head>
<body><main>
<h1>Dark store daily KPIs</h1>
<p class="note">Simulated store: BigBasket product range, Instacart order behaviour, modelled layout.
Generated by <code>make all</code>; the same numbers are in <code>results/kpi/*.csv</code> and
<code>darkstore_kpis.xlsx</code> for Google Sheets.</p>
<div class="tiles">{tiles_html}</div>
<h2>Last 14 days</h2><div class="scroll">{_table(d_show, {"line_fill_rate": pct, "perfect_order_rate": pct})}</div>
<h2>Weekly</h2><div class="scroll">{_table(w_show, {"line_fill_rate": pct, "perfect_order_rate": pct})}</div>
<h2>Fill rate by category (13 weeks)</h2><div class="scroll">{_table(cat, {"line_fill_rate": pct})}</div>
<h2>SKUs losing the most sales</h2><div class="scroll">{_table(worst)}</div>
<h2>Charts</h2>{figs}
</main></body></html>"""
    out_path.write_text(page)
    (out_path.parent / "kpi" / "latest.json").write_text(json.dumps(
        {t[0]: t[1] for t in tiles}, ensure_ascii=False, indent=2))
