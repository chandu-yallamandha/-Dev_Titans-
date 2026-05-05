"""
ingestion/ingest_api.py - Data Source + Ingestion Layer

API Structure (fake-store-api.mock.beeceptor.com):
  GET /api/orders   → list of orders with nested "items" (product_id + quantity)
  GET /api/products → list of products (product_id + category + price)

ETL steps:
  1. Fetch orders  → explode nested items → one row per order-item
  2. Fetch products → join on product_id
  3. Rename to required schema columns
  4. Drop all non-required columns (strict 7-column schema)

Also supports CSV / JSON file upload as alternative sources.
"""

import uuid
import random
import requests
import pandas as pd
from datetime import datetime, timedelta

from config import (
    API_ORDERS_ENDPOINT, API_PRODUCTS_ENDPOINT,
    FALLBACK_API_URL, API_TIMEOUT,
    REQUIRED_COLUMNS, setup_logging
)

logger = setup_logging("ingest_api")

_CATEGORIES = ["Electronics", "Clothing", "Groceries", "Home & Garden",
               "Sports", "Books", "Toys", "Beauty"]
_STORE_IDS  = [f"STORE_{i:03d}" for i in range(1, 11)]


# ──────────────────────────────────────────────────────────────────────────────
# Helper: single GET request
# ──────────────────────────────────────────────────────────────────────────────

def _get_json(url: str) -> list:
    """GET a URL and return parsed JSON list. Raises on error or non-JSON."""
    resp = requests.get(url, timeout=API_TIMEOUT)
    resp.raise_for_status()

    raw = resp.text.strip()
    if not raw:
        raise ValueError(f"Empty response from {url}")

    data = resp.json()                      # raises ValueError if not JSON

    # Beeceptor "nothing configured" text comes back as a string, not a list
    if isinstance(data, str):
        raise ValueError(f"Unexpected string response from {url}: {data[:120]}")

    if isinstance(data, dict):
        data = data.get("data", data.get("results", [data]))

    if not isinstance(data, list) or len(data) == 0:
        raise ValueError(f"No records returned from {url}")

    return data


# ──────────────────────────────────────────────────────────────────────────────
# 1. Primary API  (Beeceptor: orders + products join)
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_beeceptor() -> pd.DataFrame:
    """
    Fetch from Beeceptor mock API:
      /api/orders   → nested items → explode → one row per order-item
      /api/products → join on product_id → add price + category
    """
    logger.info("🌐 Fetching orders: %s", API_ORDERS_ENDPOINT)
    orders_raw = _get_json(API_ORDERS_ENDPOINT)
    orders_df  = pd.DataFrame(orders_raw)
    logger.info("   Orders fetched: %d", len(orders_df))

    logger.info("🌐 Fetching products: %s", API_PRODUCTS_ENDPOINT)
    products_raw = _get_json(API_PRODUCTS_ENDPOINT)
    products_df  = pd.DataFrame(products_raw)
    logger.info("   Products fetched: %d", len(products_df))

    # ── Explode nested items list → one row per order-item ────────────────────
    if "items" not in orders_df.columns:
        raise ValueError("Orders payload missing 'items' column — unexpected API schema.")

    orders_expanded = orders_df.explode("items").reset_index(drop=True)
    items_df        = pd.json_normalize(orders_expanded["items"]).reset_index(drop=True)
    orders_flat     = pd.concat(
        [orders_expanded.drop(columns=["items"]), items_df],
        axis=1
    )
    logger.info("   Exploded order-items: %d rows", len(orders_flat))

    # ── Add order_date (API doesn't provide one → use now) ────────────────────
    if "order_date" not in orders_flat.columns:
        orders_flat["order_date"] = pd.Timestamp.now().strftime("%Y-%m-%d")

    # ── Join with products on product_id ──────────────────────────────────────
    # Normalise the product_id column name in products if needed
    if "product_id" not in products_df.columns and "id" in products_df.columns:
        products_df = products_df.rename(columns={"id": "product_id"})

    df = pd.merge(orders_flat, products_df, on="product_id", how="left")

    # ── Rename to required schema ──────────────────────────────────────────────
    rename_map = {
        "user_id":   "store_id",
        "quantity":  "quantity_sold",
        "price":     "unit_price",
        "category":  "product_category",
        # handle variants
        "qty":       "quantity_sold",
        "amount":    "unit_price",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # ── Deduplicate column names (safety) ─────────────────────────────────────
    df = df.loc[:, ~df.columns.duplicated(keep="first")]

    return df


# ──────────────────────────────────────────────────────────────────────────────
# 2. Fallback API  (fakestoreapi.com /products)
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_fakestoreapi() -> pd.DataFrame:
    """Fetch product list from fakestoreapi.com and map to required schema."""
    logger.info("🌐 Fallback API: %s", FALLBACK_API_URL)
    data = _get_json(FALLBACK_API_URL)
    df   = pd.DataFrame(data)

    # Map fakestoreapi columns
    rename_map = {
        "id":       "product_id",
        "category": "product_category",
        "price":    "unit_price",
        "title":    "_title",       # drop later
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    df = df.loc[:, ~df.columns.duplicated(keep="first")]
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 3. Schema Filter  (shared by all sources)
# ──────────────────────────────────────────────────────────────────────────────

def filter_to_required_schema(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure all 7 required columns exist (synthesise any that are missing),
    then keep ONLY those 7 columns.
    Required: order_id, order_date, store_id, product_id,
              product_category, quantity_sold, unit_price
    """
    logger.info("🔧 Filtering to required schema …")

    n         = len(df)
    base_date = datetime(2024, 1, 1)

    if "order_id" not in df.columns:
        df["order_id"] = [f"ORD-{uuid.uuid4().hex[:8].upper()}" for _ in range(n)]

    if "order_date" not in df.columns:
        df["order_date"] = [
            (base_date + timedelta(days=random.randint(0, 364))).strftime("%Y-%m-%d")
            for _ in range(n)
        ]

    if "store_id" not in df.columns:
        df["store_id"] = [random.choice(_STORE_IDS) for _ in range(n)]

    if "product_id" not in df.columns:
        df["product_id"] = [f"PROD-{i+1}" for i in range(n)]

    if "product_category" not in df.columns:
        df["product_category"] = [random.choice(_CATEGORIES) for _ in range(n)]

    if "quantity_sold" not in df.columns:
        df["quantity_sold"] = [random.randint(1, 20) for _ in range(n)]

    if "unit_price" not in df.columns:
        df["unit_price"] = [round(random.uniform(5.0, 300.0), 2) for _ in range(n)]

    # Keep ONLY the 7 required columns — drop everything else
    df = df[[col for col in REQUIRED_COLUMNS if col in df.columns]].copy()
    logger.info("✅ Schema ready — %d rows | columns: %s", len(df), list(df.columns))
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 4. File upload sources
# ──────────────────────────────────────────────────────────────────────────────

def load_from_csv(file_obj) -> pd.DataFrame:
    df = pd.read_csv(file_obj)
    logger.info("📂 CSV loaded: %d rows | columns: %s", len(df), list(df.columns))
    return df


def load_from_json(file_obj) -> pd.DataFrame:
    df = pd.read_json(file_obj)
    logger.info("📂 JSON loaded: %d rows | columns: %s", len(df), list(df.columns))
    return df


# ──────────────────────────────────────────────────────────────────────────────
# 5. Public entry point  (Streamlit calls this for API mode)
# ──────────────────────────────────────────────────────────────────────────────

def fetch_from_api() -> tuple[pd.DataFrame, str]:
    """
    Try Beeceptor (orders + products join) first.
    Fall back to fakestoreapi.com if Beeceptor is unavailable.
    Returns (raw_DataFrame, source_label).
    """
    sources = [
        (_fetch_beeceptor,     "Beeceptor Mock API"),
        (_fetch_fakestoreapi,  "FakeStoreAPI (fallback)"),
    ]
    for fn, label in sources:
        try:
            df = fn()
            logger.info("✅ [%s] %d rows fetched", label, len(df))
            return df, label
        except Exception as exc:
            logger.warning("⚠️  [%s] failed: %s — trying next source.", label, exc)
            continue

    raise RuntimeError("All API sources failed. Check your internet connection.")


# ──────────────────────────────────────────────────────────────────────────────
# 6. DB loader
# ──────────────────────────────────────────────────────────────────────────────

def load_raw_to_db(df: pd.DataFrame, engine) -> None:
    """Write filtered data into raw_sales (replaces table each run)."""
    df.to_sql("raw_sales", con=engine, if_exists="replace", index=False,
              method="multi", chunksize=500)
    logger.info("✅ raw_sales updated — %d rows", len(df))


# ──────────────────────────────────────────────────────────────────────────────
# 7. CLI entry point  (main.py uses this)
# ──────────────────────────────────────────────────────────────────────────────

def ingest(engine) -> pd.DataFrame:
    """CLI path: fetch → filter → load raw_sales."""
    raw_df, _label = fetch_from_api()
    filtered = filter_to_required_schema(raw_df)
    load_raw_to_db(filtered, engine)
    return filtered
