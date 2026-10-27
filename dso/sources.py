"""Data adapters.

The rest of the code never reads raw files. It sees two things:

- an order source: order headers (order_id, dow, hour, split) and order lines
  (order_id, product_id, seq), plus the source's product list with the
  category labels the mapping keys on;
- a product catalogue: the SKUs the store sells (name, category,
  sub-category, brand, price in rupees, a popularity proxy).

Instacart is the order source and BigBasket the catalogue. Swapping either one
means writing one new class with the same methods.
"""
from pathlib import Path

import duckdb
import pandas as pd

from .config import RAW


class InstacartOrders:
    """Instacart Market Basket Analysis (Kaggle), ~3.4M orders, 2017."""

    name = "Instacart Market Basket Analysis"

    def __init__(self, root: Path = RAW / "instacart"):
        self.root = Path(root)

    def _f(self, stem: str) -> str:
        hits = sorted(self.root.rglob(f"{stem}.csv"))
        if not hits:
            raise FileNotFoundError(f"{stem}.csv not found under {self.root}; run `make data`")
        return str(hits[0])

    def register(self, con: duckdb.DuckDBPyConnection) -> None:
        """Create src_orders, src_lines and src_products views."""
        con.execute(f"""
            CREATE OR REPLACE VIEW src_orders AS
            SELECT order_id::INTEGER AS order_id, user_id::INTEGER AS user_id,
                   eval_set AS split, order_number::INTEGER AS order_number,
                   order_dow::INTEGER AS dow, order_hour_of_day::INTEGER AS hour,
                   days_since_prior_order::DOUBLE AS days_since_prior
            FROM read_csv_auto('{self._f("orders")}')
            WHERE eval_set IN ('prior', 'train')""")
        con.execute(f"""
            CREATE OR REPLACE VIEW src_lines AS
            SELECT order_id::INTEGER AS order_id, product_id::INTEGER AS product_id,
                   add_to_cart_order::INTEGER AS seq
            FROM read_csv_auto('{self._f("order_products__prior")}')
            UNION ALL
            SELECT order_id::INTEGER, product_id::INTEGER, add_to_cart_order::INTEGER
            FROM read_csv_auto('{self._f("order_products__train")}')""")
        con.execute(f"""
            CREATE OR REPLACE VIEW src_products AS
            SELECT p.product_id::INTEGER AS product_id, p.product_name AS product_name,
                   a.aisle AS src_aisle, d.department AS src_department
            FROM read_csv_auto('{self._f("products")}') p
            JOIN read_csv_auto('{self._f("aisles")}') a USING (aisle_id)
            JOIN read_csv_auto('{self._f("departments")}') d USING (department_id)""")


class BigBasketCatalogue:
    """BigBasket entire product list (Kaggle, surajjha101), ~28k SKUs, CC BY-NC-SA 4.0."""

    name = "BigBasket Entire Product List"
    licence = "CC BY-NC-SA 4.0"

    def __init__(self, root: Path = RAW / "bigbasket"):
        self.root = Path(root)

    def load(self) -> pd.DataFrame:
        hits = sorted(self.root.rglob("*.csv"))
        if not hits:
            raise FileNotFoundError(f"no BigBasket CSV under {self.root}; run `make data`")
        df = pd.read_csv(hits[0])
        df = df.rename(columns={"product": "name", "sale_price": "price_inr"})
        df = df.dropna(subset=["name", "category", "sub_category"])
        # the list repeats some products (same name, brand, pack); keep one
        df = df.drop_duplicates(subset=["name", "brand", "sub_category"])
        df = df[df["price_inr"] > 0].reset_index(drop=True)
        df["cat_sku"] = "BB" + df["index"].astype(str)
        return df[["cat_sku", "name", "category", "sub_category", "type", "brand",
                   "price_inr", "market_price", "rating"]]
