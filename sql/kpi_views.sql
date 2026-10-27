-- Daily ops KPIs over the simulated operations log.
-- Inputs (written by the pipeline):
--   sim_orders(day, order_seq, date, hour, minute_of_day, lines, walk_m, pick_s, src_order_id)
--   sim_lines(day, order_seq, sku_id, short)
--   sim_inventory(day, sku_id, opening_units, demand_units, served_units, closing_units, ordered_units)
--   sku(sku_id, sku_name, category, sub_category, price_inr, ...)
-- In a live store the same views would sit on the WMS order, pick and stock tables.

CREATE OR REPLACE VIEW order_facts AS
SELECT o.date, o.day, o.order_seq, o.hour, o.lines, o.walk_m, o.pick_s,
       COALESCE(s.short_lines, 0) AS short_lines,
       COALESCE(s.short_lines, 0) = 0 AS perfect_order
FROM sim_orders o
LEFT JOIN (SELECT day, order_seq, SUM(short::INT) AS short_lines
           FROM sim_lines GROUP BY 1, 2) s USING (day, order_seq);

CREATE OR REPLACE VIEW kpi_hourly AS
SELECT date, hour, COUNT(*) AS orders,
       ROUND(AVG(pick_s) / 60, 2) AS avg_pick_min,
       ROUND(AVG(walk_m), 1) AS avg_walk_m
FROM order_facts GROUP BY 1, 2;

CREATE OR REPLACE VIEW kpi_daily AS
WITH o AS (
    SELECT date, day, COUNT(*) AS orders, SUM(lines) AS lines,
           SUM(short_lines) AS short_lines,
           AVG(perfect_order::INT) AS perfect_order_rate,
           AVG(pick_s) / 60 AS avg_pick_min,
           quantile_cont(pick_s, 0.9) / 60 AS p90_pick_min,
           AVG(walk_m) AS avg_walk_m
    FROM order_facts GROUP BY 1, 2),
h AS (SELECT date, MAX(orders) AS peak_orders_per_hour FROM kpi_hourly GROUP BY 1),
i AS (
    SELECT inv.day,
           SUM((inv.demand_units > inv.served_units)::INT) AS skus_with_lost_sales,
           SUM((inv.closing_units = 0)::INT) AS skus_zero_at_close,
           SUM(inv.closing_units * k.price_inr) AS closing_stock_value_inr,
           SUM((inv.ordered_units > 0)::INT) AS replen_lines_to_dc,
           SUM(inv.ordered_units) AS replen_units_to_dc
    FROM sim_inventory inv JOIN sku k USING (sku_id) GROUP BY 1)
SELECT o.date, strftime(o.date, '%a') AS weekday, o.orders, o.lines,
       ROUND(o.lines / o.orders, 2) AS lines_per_order,
       h.peak_orders_per_hour,
       ROUND(o.avg_pick_min, 2) AS avg_pick_min,
       ROUND(o.p90_pick_min, 2) AS p90_pick_min,
       ROUND(o.avg_walk_m, 1) AS avg_walk_m,
       ROUND(1 - o.short_lines / o.lines, 4) AS line_fill_rate,
       ROUND(o.perfect_order_rate, 4) AS perfect_order_rate,
       i.skus_with_lost_sales, i.skus_zero_at_close,
       ROUND(i.closing_stock_value_inr) AS closing_stock_value_inr,
       i.replen_lines_to_dc, i.replen_units_to_dc
FROM o JOIN h USING (date) JOIN i USING (day)
ORDER BY o.date;

CREATE OR REPLACE VIEW kpi_category_daily AS
SELECT o.date, k.category, COUNT(*) AS lines, SUM(l.short::INT) AS short_lines,
       ROUND(1 - SUM(l.short::INT) / COUNT(*), 4) AS line_fill_rate
FROM sim_lines l
JOIN sim_orders o USING (day, order_seq)
JOIN sku k USING (sku_id)
GROUP BY 1, 2 ORDER BY 1, 2;

CREATE OR REPLACE VIEW kpi_sku_stockouts AS
SELECT k.sku_id, k.sku_name, k.category, k.sub_category, k.price_inr,
       SUM((inv.demand_units > inv.served_units)::INT) AS days_with_lost_sales,
       SUM(inv.demand_units - inv.served_units) AS lost_units,
       ROUND(SUM((inv.demand_units - inv.served_units) * k.price_inr)) AS lost_sales_inr,
       ROUND(AVG(inv.demand_units), 2) AS avg_daily_demand
FROM sim_inventory inv JOIN sku k USING (sku_id)
GROUP BY 1, 2, 3, 4, 5
HAVING SUM(inv.demand_units - inv.served_units) > 0
ORDER BY lost_sales_inr DESC, sku_id;

CREATE OR REPLACE VIEW kpi_weekly AS
SELECT CAST(date_trunc('week', date + 1) AS DATE) - 1 AS week_starting_sun,
       SUM(orders) AS orders, MAX(peak_orders_per_hour) AS peak_orders_per_hour,
       ROUND(SUM(avg_pick_min * orders) / SUM(orders), 2) AS avg_pick_min,
       ROUND(SUM(avg_walk_m * orders) / SUM(orders), 1) AS avg_walk_m,
       ROUND(SUM(line_fill_rate * lines) / SUM(lines), 4) AS line_fill_rate,
       ROUND(SUM(perfect_order_rate * orders) / SUM(orders), 4) AS perfect_order_rate,
       SUM(skus_with_lost_sales) AS sku_days_with_lost_sales
FROM kpi_daily GROUP BY 1 ORDER BY 1;
