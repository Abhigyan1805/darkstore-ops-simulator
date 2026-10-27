"""Static charts for the README and dashboard (matplotlib, PNG)."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"     # categorical slot 1
ORANGE = "#eb6834"   # slot 2
AQUA = "#1baf7a"     # slot 3
GREY = "#9a9893"
DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
LAYOUT_LABEL = {"random": "Random", "category": "By category\n(baseline)",
                "abc_velocity": "ABC by\nvelocity", "abc_affinity": "ABC +\nco-pick affinity"}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
})


def _save(fig, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def walk_before_after(per: dict, path) -> None:
    order = ["random", "category", "abc_velocity", "abc_affinity"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1, 1.3]})
    rng = np.random.default_rng(0)
    means, errs = [], []
    for k in order:
        w = per[k]["walk_m"].to_numpy()
        boot = w[rng.integers(0, len(w), (1000, len(w)))].mean(axis=1)
        lo, hi = np.quantile(boot, [0.025, 0.975])
        means.append(w.mean())
        errs.append([w.mean() - lo, hi - w.mean()])
    colors = [GREY, GREY, BLUE, AQUA]
    xs = np.arange(len(order))
    ax1.bar(xs, means, color=colors, width=0.6, yerr=np.array(errs).T, capsize=4,
            error_kw={"ecolor": INK2, "elinewidth": 1})
    for x, m in zip(xs, means):
        ax1.text(x, m * 1.03 + 2, f"{m:.0f} m", ha="center", va="bottom", color=INK, fontsize=9)
    ax1.set_ylim(0, max(means) * 1.18)
    ax1.set_xticks(xs, [LAYOUT_LABEL[k] for k in order])
    ax1.set_ylabel("walk per order, metres (S-shape route)")
    ax1.set_title("Mean walk per order, 95% CI")
    ax1.grid(axis="x", visible=False)

    bins = np.linspace(0, np.quantile(per["random"]["walk_m"], 0.99), 40)
    ax2.hist(per["category"]["walk_m"], bins=bins, color=GREY, alpha=0.75, label="By category (baseline)")
    ax2.hist(per["abc_velocity"]["walk_m"], bins=bins, color=BLUE, alpha=0.75, label="ABC by velocity")
    ax2.set_xlabel("walk per order, metres")
    ax2.set_ylabel("orders")
    ax2.set_title("Distribution over held-out orders")
    ax2.legend(frameon=False)
    _save(fig, path)


def layout_heatmaps(slots, placements, v, lay, path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 5), sharey=True)
    ppd = v["picks_per_day"].to_numpy()
    vmax = None
    grids = {}
    for k in ("category", "abc_velocity"):
        p = placements[k]
        s = slots.set_index("slot_id").loc[p]
        g = pd.DataFrame({"aisle": s["aisle"].to_numpy(), "bay": s["bay"].to_numpy(), "ppd": ppd})
        grids[k] = g.pivot_table(index="bay", columns="aisle", values="ppd", aggfunc="sum",
                                 fill_value=0).reindex(index=range(lay.bays_per_side),
                                                       columns=range(lay.n_aisles), fill_value=0)
        vmax = max(vmax or 0, grids[k].to_numpy().max())
    for ax, k in zip(axes, ("category", "abc_velocity")):
        im = ax.imshow(grids[k].to_numpy(), origin="lower", cmap="Blues", vmin=0, vmax=vmax,
                       aspect="auto")
        ax.set_title(LAYOUT_LABEL[k].replace("\n", " "))
        ax.set_xlabel("aisle (pack station at the front, centre)")
        ax.set_xticks(range(lay.n_aisles), range(1, lay.n_aisles + 1))
        ax.grid(False)
        ax.plot([(lay.n_aisles - 1) / 2], [-1.2], marker="s", ms=12, color=ORANGE, clip_on=False)
        ax.text((lay.n_aisles - 1) / 2 + 0.5, -1.25, "pack", color=INK2, va="center", fontsize=9,
                clip_on=False)
    axes[0].set_ylabel("bay, front (0) to back")
    cb = fig.colorbar(im, ax=axes, shrink=0.85)
    cb.set_label("picks per day in the bay (all levels)")
    fig.suptitle("Where the picks happen: one cell = one bay pair across an aisle", x=0.02, ha="left",
                 fontweight="bold")
    _save(fig, path)


def tradeoff_curve(tbl: pd.DataFrame, path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for fam, color, mk in (("velocity min/max", BLUE, "o"), ("days-of-cover min/max", AQUA, "D"),
                           ("naive fixed min/max", ORANGE, "s")):
        d = tbl[tbl["family"] == fam].sort_values("avg_inventory_value_inr")
        x = d["avg_inventory_value_inr"] / 1e5
        y = (1 - d["line_fill_rate"]) * 100
        ax.plot(x, y, color=color, lw=2, marker=mk, ms=7, label=fam,
                markeredgecolor=SURFACE, markeredgewidth=1.5)
        for xi, yi, r in zip(x, y, d.itertuples()):
            if fam.startswith("velocity"):
                lab = f"{r.service_level:.1%}".replace(".0%", "%")
            elif fam.startswith("days"):
                lab = f"{r.min_days:g} d"
            else:
                lab = f"min {int(r.min_units)}"
            off = (-30, -12) if fam.startswith("days") else (6, 4)
            ax.annotate(lab, (xi, yi), textcoords="offset points", xytext=off, fontsize=8, color=INK2)
    ax.set_xlabel("average stock held, ₹ lakh at BigBasket selling price")
    ax.set_ylabel("order lines short (lost), %")
    ax.set_title("Stock-outs vs stock held, 13 simulated weeks")
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax.legend(frameon=False)
    _save(fig, path)


def hourly_staffing(plan: pd.DataFrame, path) -> None:
    peak_dow = int(plan.loc[plan["orders_per_hour"].idxmax(), "dow"])
    low_dow = int(plan.groupby("dow")["orders_per_hour"].sum().idxmin())
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True,
                                   gridspec_kw={"height_ratios": [1.2, 1]})
    for d, color in ((peak_dow, BLUE), (low_dow, AQUA)):
        p = plan[plan["dow"] == d]
        ax1.plot(p["hour"], p["orders_per_hour"], color=color, lw=2, label=f"{DOW[d]} (busiest day)"
                 if d == peak_dow else f"{DOW[d]} (quietest day)")
        ax2.step(p["hour"], p["pickers"], where="mid", color=color, lw=2)
    ax1.set_ylabel("orders per hour")
    ax1.set_title("Hourly load and the pickers needed to start 90% of orders within 2 minutes")
    ax1.legend(frameon=False)
    ax2.set_ylabel("pickers on shift")
    ax2.set_xlabel("hour of day")
    ax2.set_xticks(range(0, 24, 2))
    ax2.yaxis.get_major_locator().set_params(integer=True)
    _save(fig, path)


def dow_hour_heatmap(prof: pd.DataFrame, orders_per_day: float, path) -> None:
    g = prof.assign(oph=prof["share_of_week"] * orders_per_day * 7).pivot(
        index="dow", columns="hour", values="oph")
    fig, ax = plt.subplots(figsize=(10, 3.4))
    im = ax.imshow(g.to_numpy(), cmap="Blues", aspect="auto")
    ax.set_yticks(range(7), DOW)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel("hour of day")
    ax.grid(False)
    ax.set_title(f"Orders per hour at {orders_per_day:,} orders/day (Instacart weekly pattern)")
    fig.colorbar(im, ax=ax, label="orders per hour")
    _save(fig, path)
