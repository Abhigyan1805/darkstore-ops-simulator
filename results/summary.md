# Results

### Product mapping (Instacart → BigBasket)

| Item | Value |
|---|---|
| Instacart aisles mapped to a BigBasket category | 125 of 134 |
| Instacart departments fully mapped | 17 of 21 (partly: international; dropped: alcohol, missing, other) |
| Aisles dropped (no Indian counterpart or unlabelled) | beers coolers, kosher foods, latino foods, missing, other, red wines, specialty wines champagnes, spirits, white wines |
| Order lines in dropped aisles | 1.1% |
| Order lines on Instacart products beyond BigBasket's range depth | 17.5% |
| Order lines on mapped products outside the 3,000-SKU store range | 11.2% |
| Order lines the store range covers | 70.2% |
| Orders with at least one line in the range | 3,215,417 of 3,346,083 |
| BigBasket categories / sub-categories in the store | 11 / 60 |
| Store SKUs matched to a BigBasket SKU by a shared name word | 2,153 of 3,000 (74.0% of store picks) |


### 1. Slotting (5,000 held-out orders, 7.5 lines each on average)

| Layout | Walk / order, m (S-shape) | Walk / order, m (nearest-neighbour) | Pick time / order, min | Aisles visited / order | Picks at waist height | Walk cut vs baseline (95% CI) | Pick-time cut vs baseline (95% CI) |
|---|---|---|---|---|---|---|---|
| Random placement | 102.5 | 88.1 | 3.42 | 4.73 | 49% | -23.6% (-24.5% to -22.7%) | -10.7% (-11.2% to -10.3%) |
| By category (baseline) | 82.9 | 72.7 | 3.09 | 3.88 | 51% | — | — |
| ABC by velocity | 65.8 | 58.4 | 2.72 | 3.24 | 67% | 20.6% (19.9% to 21.4%) | 12.0% (11.6% to 12.3%) |
| ABC + co-pick affinity | 63.3 | 56.6 | 2.67 | 3.13 | 69% | 23.7% (23.0% to 24.4%) | 13.6% (13.2% to 13.9%) |


Paired difference, ABC by velocity minus baseline: -17.1 m per order (95% CI -17.8 to -16.3). ABC classes: A = 1,193 SKUs, 80% of picks, B = 1,147 SKUs, 15% of picks, C = 660 SKUs, 5% of picks.


### 2. Replenishment (91 simulated days after 56 days of history, ~1,999 orders/day, lead time 1 day, daily review)

| Policy | Line fill rate | Orders complete | SKU-days with lost sales | Avg stock, units | Avg stock, ₹ lakh | Days of cover | DC order lines / day |
|---|---|---|---|---|---|---|---|
| Min/max, 80% service level | 98.98% | 94.0% | 1.86% | 44,856 | 57.3 | 3.0 | 1,081 |
| Min/max, 85% service level | 99.28% | 95.5% | 1.39% | 46,744 | 60.0 | 3.2 | 1,085 |
| Min/max, 90% service level | 99.56% | 97.1% | 0.92% | 49,141 | 63.2 | 3.3 | 1,088 |
| Min/max, 95% service level | 99.79% | 98.5% | 0.49% | 52,643 | 68.0 | 3.6 | 1,091 |
| Min/max, 97% service level | 99.87% | 99.1% | 0.32% | 54,960 | 71.1 | 3.7 | 1,092 |
| Min/max, 99% service level | 99.95% | 99.6% | 0.14% | 59,276 | 77.0 | 4.0 | 1,093 |
| Min/max, 99.5% service level | 99.97% | 99.8% | 0.08% | 61,718 | 80.3 | 4.2 | 1,093 |
| Same for every SKU: min 2, max 4 | 29.89% | 6.9% | 44.83% | 6,981 | 11.4 | 0.5 | 1,576 |
| Same for every SKU: min 3, max 6 | 38.44% | 10.1% | 33.66% | 10,735 | 17.5 | 0.7 | 1,351 |
| Same for every SKU: min 4, max 8 | 44.84% | 12.8% | 26.24% | 14,642 | 23.9 | 1.0 | 1,192 |
| Same for every SKU: min 6, max 12 | 53.77% | 17.6% | 17.33% | 22,788 | 37.2 | 1.5 | 969 |
| Same for every SKU: min 8, max 16 | 59.91% | 21.8% | 12.57% | 31,219 | 51.0 | 2.1 | 828 |
| Same for every SKU: min 12, max 24 | 68.04% | 28.1% | 7.68% | 48,513 | 79.2 | 3.3 | 646 |
| Same for every SKU: min 20, max 40 | 76.90% | 37.4% | 3.92% | 83,965 | 136.6 | 5.7 | 452 |
| Days of cover: min = 1 d | 82.48% | 44.4% | 18.38% | 25,426 | 32.3 | 1.7 | 926 |
| Days of cover: min = 1.5 d | 90.87% | 65.7% | 11.23% | 30,733 | 38.9 | 2.1 | 994 |
| Days of cover: min = 2 d | 96.18% | 82.0% | 6.05% | 36,948 | 46.6 | 2.5 | 1,041 |
| Days of cover: min = 2.5 d | 98.75% | 92.3% | 2.84% | 44,019 | 55.2 | 3.0 | 1,070 |
| Days of cover: min = 3 d | 99.53% | 96.8% | 1.32% | 51,302 | 64.0 | 3.5 | 1,084 |
| Days of cover: min = 4 d | 99.90% | 99.3% | 0.31% | 65,867 | 81.8 | 4.5 | 1,092 |


At about the same stock, the 95% min/max loses 0.21% of lines against 0.47% for a 3-day cover rule. To reach the same fill rate, the days-of-cover rule needs about 61,439 units (+17% stock).


### 3. Capacity (2,000 orders/day, target: 90% of orders start picking within 2 min)

| Item | Value |
|---|---|
| Peak hour | Mon 10:00, 230 orders/hour |
| Mean pick time (ABC layout / baseline layout) | 2.72 / 3.09 min |
| Pickers needed at peak, Erlang C (ABC / baseline) | 13 / 15 |
| Picker-hours per week, Erlang C (ABC / baseline) | 974 / 1,085 |
| Orders per picker-hour (ABC / baseline) | 14.4 / 12.9 |
| Picker-hours per week after the SimPy check | 979 (+5 over Erlang C) |
| SimPy: orders starting within target | 98.3% |
| SimPy: mean / 90th percentile wait for a picker | 0.21 / 0.82 min |
| SimPy: mean / 90th percentile order-to-packed time | 3.9 / 5.8 min |
| Throughput limit, pickers (max 16 on the floor) | 306 orders/hour |
| Throughput limit, pack stations (6 at 60 s, ≤85% busy) | 306 orders/hour |
| Binding limit | pickers: 306 orders/hour |
| Max orders/day with this weekly pattern | 2,657 |


Planning grid (peak-day and new-store sizing, ABC layout):

| Orders/day | Peak orders/hour | Pickers at peak | Picker-hours/day | Fits this store |
|---|---|---:|---|---|
| 1,000 | 115 | 8 | 87 | yes |
| 1,500 | 173 | 10 | 113 | yes |
| 2,000 | 230 | 13 | 139 | yes |
| 2,500 | 288 | 16 | 163 | yes |
| 3,000 | 345 | 18 | 188 | no |
| 4,000 | 460 | 24 | 235 | no |
| 5,000 | 575 | 29 | 281 | no |


### 4. KPI snapshot (last simulated week, from the SQL views)

| KPI | Value |
|---|---|
| Orders / day | 1,992 |
| Peak orders / hour | 237 |
| Avg pick time | 2.69 min |
| Avg walk | 65 m |
| Line fill rate | 99.81% |
| Perfect orders | 98.7% |
| SKUs with lost sales | 14 / day |
| Stock on hand | ₹68.5 lakh |
