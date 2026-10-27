"""Map Instacart products onto real BigBasket SKUs.

1. config/aisle_to_bigbasket.csv maps each Instacart aisle to one BigBasket
   (category, sub_category) and, where the sub-category is broad, a list of
   BigBasket product types (e.g. yogurt -> Dairy: Curd; Yogurt & Shrikhand;
   Buttermilk & Lassi). A blank target drops the aisle (alcohol, for
   example). Aisles with the same target form one pool. The file is
   hand-written and reviewed.
2. Inside each pool, Instacart products are taken in order of how often they
   were ordered. Each takes the free BigBasket SKU whose name shares the most
   words with it (after dropping words like "organic" and plurals), so
   "Bag of Organic Bananas" lands on a banana and "Organic Whole Milk" on a
   milk. With no shared word, it takes the free SKU ranked highest by a
   popularity proxy (BigBasket publishes no sales: rated SKUs first, by
   rating, then cheaper first).
3. Instacart products beyond the depth of their BigBasket pool get no SKU and
   are dropped; the report counts them.
"""
import re

import numpy as np
import pandas as pd

KEY = ["bb_category", "bb_sub_category", "bb_types"]


def load_aisle_map(path) -> pd.DataFrame:
    m = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in KEY:
        m[c] = m[c].str.strip()
    return m


def _types(s: str) -> list:
    return [t.strip() for t in s.split(";") if t.strip()]


def pools(m: pd.DataFrame, bb: pd.DataFrame) -> pd.DataFrame:
    """BigBasket SKUs eligible for each mapping target, with a pool rank."""
    out = []
    for key in m.loc[m["bb_sub_category"] != "", KEY].drop_duplicates().itertuples(index=False):
        cat, sub, types = key
        sel = bb[(bb["category"] == cat) & (bb["sub_category"] == sub)]
        if types:
            sel = sel[sel["type"].isin(_types(types))]
        sel = sel.assign(bb_category=cat, bb_sub_category=sub, bb_types=types)
        out.append(sel)
    p = pd.concat(out, ignore_index=True)
    p["rated"] = p["rating"].notna()
    p = p.sort_values(KEY + ["rated", "rating", "price_inr", "cat_sku"],
                      ascending=[True, True, True, False, False, True, True])
    p["rank"] = p.groupby(KEY).cumcount()
    return p


def validate_map(m: pd.DataFrame, bb: pd.DataFrame) -> list:
    """Problems with the map: unknown targets, unknown types, overlapping pools."""
    problems = []
    have = set(zip(bb["category"], bb["sub_category"]))
    types_in = bb.groupby(["category", "sub_category"])["type"].apply(set).to_dict()
    for r in m.itertuples():
        if not r.bb_sub_category:
            continue
        if (r.bb_category, r.bb_sub_category) not in have:
            problems.append(f"{r.src_aisle}: unknown target {r.bb_category} / {r.bb_sub_category}")
            continue
        for t in _types(r.bb_types):
            if t not in types_in[(r.bb_category, r.bb_sub_category)]:
                problems.append(f"{r.src_aisle}: unknown type {t!r}")
    if not problems:
        p = pools(m, bb)
        dup = p[p.duplicated("cat_sku", keep=False)]
        if len(dup):
            problems.append(f"{dup['cat_sku'].nunique()} BigBasket SKUs sit in two pools: "
                            f"{dup[KEY].drop_duplicates().values.tolist()}")
    return problems


STOP = set("""organic fresh natural naturally the of and with in for a an oz lb ct pack
    pk bag large small mini original classic style flavor flavored free premium select
    whole real pure simply all new family size value fl count gluten non""".split())


# US grocery words -> the word an Indian catalogue uses for the same thing
SYNONYMS = {"cilantro": "coriander", "yogurt": "curd", "half": "cream", "creamer": "cream",
            "garbanzo": "chana", "chickpea": "chana", "lentil": "dal", "scallion": "spring",
            "eggplant": "brinjal", "arugula": "rocket", "bell": "capsicum", "okra": "bhindi",
            "cookie": "biscuit", "cracker": "biscuit", "seltzer": "soda", "lime": "lemon",
            "cottage": "paneer", "chip": "chip", "tortilla": "wrap", "oatmeal": "oat",
            "detergent": "detergent", "tissue": "tissue", "diaper": "diaper"}


# words that mark a processed or unusual form; on a tie the plain product wins
QUALIFIERS = {"flower", "raw", "diced", "chopped", "cut", "peeled", "grated", "sliced",
              "dried", "powder", "baby", "mix", "combo"}


def tokens(name: str, synonyms: bool = False) -> set:
    out = set()
    for w in re.findall(r"[a-z]+", str(name).lower()):
        if len(w) < 3 or w in STOP:
            continue
        if w.endswith("ies") and len(w) > 4:
            w = w[:-3] + "y"
        elif w.endswith("oes") and len(w) > 4:
            w = w[:-2]
        elif w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
        if synonyms and w in SYNONYMS:
            out.add(SYNONYMS[w])
    return out


def _match_pool(ic: pd.DataFrame, bbp: pd.DataFrame) -> np.ndarray:
    """Greedy name match for one pool. ic is sorted by popularity, bbp by proxy rank.
    Returns, for each Instacart row, the index into bbp it takes, or -1."""
    vocab = {}
    def vec(names):
        rows = []
        for n in names:
            rows.append([vocab.setdefault(t, len(vocab)) for t in tokens(n)])
        return rows
    ic_t = [[vocab.setdefault(t, len(vocab)) for t in tokens(n, synonyms=True)]
            for n in ic["product_name"]]
    bb_t = vec(bbp["name"])
    m = np.zeros((len(bb_t), max(len(vocab), 1)), dtype=np.float32)
    for i, r in enumerate(bb_t):
        m[i, r] = 1.0
    bb_len = np.maximum(m.sum(axis=1), 1)
    qual = np.array([len(tokens(n) & QUALIFIERS) for n in bbp["name"]], dtype=np.float32)
    free = np.ones(len(bb_t), dtype=bool)
    proxy = np.arange(len(bb_t))  # bbp is already in proxy order
    out = np.full(len(ic_t), -1)
    for k, r in enumerate(ic_t):
        if not free.any():
            break
        score = m[:, r].sum(axis=1) / np.sqrt(bb_len * max(len(r), 1)) if r else np.zeros(len(bb_t))
        score = np.where(score > 0, score - 0.001 * qual, score)
        score = np.where(free, score, -1.0)
        best = score.max()
        if best > 0:
            cand = np.flatnonzero(score == best)
            j = cand[np.argmin(proxy[cand])]
        else:
            j = int(np.flatnonzero(free)[0])
        out[k] = j
        free[j] = False
    return out


def assign(products: pd.DataFrame, aisle_map: pd.DataFrame, bb: pd.DataFrame) -> pd.DataFrame:
    """products: product_id, product_name, src_aisle, src_department, picks.

    Returns one row per Instacart product with its BigBasket SKU (or NaN) and
    a status: mapped / no_bb_category / bb_depth_exhausted.
    """
    p = products.merge(aisle_map[["src_aisle"] + KEY], on="src_aisle", how="left")
    for c in KEY:
        p[c] = p[c].fillna("")
    p = p.sort_values(KEY + ["picks", "product_id"], ascending=[True, True, True, False, True])
    pl = pools(aisle_map, bb)
    bb_cols = [c for c in pl.columns if c not in KEY + ["rank", "rated"]]
    parts = []
    for key, ic in p.groupby(KEY, sort=False):
        ic = ic.reset_index(drop=True)
        if key[1] == "":
            parts.append(ic)
            continue
        bbp = pl[(pl["bb_category"] == key[0]) & (pl["bb_sub_category"] == key[1])
                 & (pl["bb_types"] == key[2])].reset_index(drop=True)
        j = _match_pool(ic, bbp)
        took = j >= 0
        ic.loc[took, bb_cols] = bbp.loc[j[took], bb_cols].to_numpy()
        ic["name_match"] = False
        ic.loc[took, "name_match"] = [bool(tokens(a, synonyms=True) & tokens(b)) for a, b in
                                      zip(ic.loc[took, "product_name"], bbp.loc[j[took], "name"])]
        parts.append(ic)
    out = pd.concat(parts, ignore_index=True)
    out["status"] = "mapped"
    out.loc[out["bb_sub_category"] == "", "status"] = "no_bb_category"
    out.loc[(out["status"] == "mapped") & out["cat_sku"].isna(), "status"] = "bb_depth_exhausted"
    return out
