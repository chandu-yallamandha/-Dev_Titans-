"""
transformation/transform.py - Layer 4 & 5: Transformation + Processed Layer

Reads from raw_sales, applies cleaning & derivation rules,
writes to transformed_sales.
"""

import pandas as pd
from config import setup_logging

logger = setup_logging("transform")


def transform(engine) -> pd.DataFrame:
    """
    Full transformation pipeline:
    1. Load raw_sales
    2. Clean & validate
    3. Derive fields
    4. Write transformed_sales
    Returns the transformed DataFrame.
    """
    raw_df = _load_raw(engine)
    if raw_df.empty:
        logger.warning("⚠️  raw_sales is empty — nothing to transform.")
        return pd.DataFrame()

    cleaned_df     = _clean(raw_df)
    transformed_df = _derive_fields(cleaned_df)
    _save_transformed(transformed_df, engine)

    total  = len(raw_df)
    passed = len(transformed_df)
    score  = round((passed / total) * 100, 1) if total > 0 else 0
    logger.info("📊 Quality Score: %.1f%% (%d/%d passed)", score, passed, total)
    return transformed_df


def _load_raw(engine) -> pd.DataFrame:
    """Read all rows from raw_sales."""
    try:
        df = pd.read_sql("SELECT * FROM raw_sales", con=engine)
        logger.info("📥 Loaded %d rows from raw_sales.", len(df))
        return df
    except Exception as exc:
        logger.error("❌ Could not read raw_sales: %s", exc)
        return pd.DataFrame()


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """
    Data-quality rules:
      1. Drop duplicate order_id rows
      2. Drop rows with null order_id
      3. Fill non-critical nulls
      4. Parse order_date
      5. Remove rows with quantity_sold <= 0 or unit_price <= 0
    """
    before = len(df)
    df = df.drop_duplicates(subset=["order_id"], keep="first")
    logger.info("🧹 Duplicates removed: %d", before - len(df))

    df = df[df["order_id"].notna()]

    df["store_id"]         = df["store_id"].fillna("UNKNOWN_STORE")
    df["product_id"]       = df["product_id"].fillna("UNKNOWN_PROD")
    df["product_category"] = df["product_category"].fillna("Unknown")
    df["quantity_sold"]    = pd.to_numeric(df["quantity_sold"], errors="coerce")
    df["unit_price"]       = pd.to_numeric(df["unit_price"],    errors="coerce")

    df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")

    # Remove invalid numeric rows
    mask_invalid = (
        df["quantity_sold"].isna() | (df["quantity_sold"] <= 0) |
        df["unit_price"].isna()    | (df["unit_price"]    <= 0)
    )
    removed = mask_invalid.sum()
    if removed:
        logger.info("⚠️  Removed %d rows with invalid quantity/price.", removed)
    df = df[~mask_invalid]

    logger.info("✅ Clean records: %d", len(df))
    return df.reset_index(drop=True)


def _derive_fields(df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive:
      total_sales = quantity_sold × unit_price
      order_month = YYYY-MM string
      order_day   = day name (Monday … Sunday)
    """
    df = df.copy()
    df["total_sales"] = (df["quantity_sold"] * df["unit_price"]).round(2)
    df["order_month"] = df["order_date"].dt.to_period("M").astype(str)
    df["order_day"]   = df["order_date"].dt.day_name()
    df["order_date"]  = df["order_date"].dt.date

    cols = [
        "order_id", "order_date", "store_id", "product_id",
        "product_category", "quantity_sold", "unit_price",
        "total_sales", "order_month", "order_day",
    ]
    df = df[[c for c in cols if c in df.columns]]
    logger.info("✅ Derived: total_sales, order_month, order_day")
    return df


def _save_transformed(df: pd.DataFrame, engine) -> None:
    """Write transformed data into transformed_sales (replace)."""
    df.to_sql("transformed_sales", con=engine, if_exists="replace",
              index=False, method="multi", chunksize=500)
    logger.info("✅ Saved %d rows → transformed_sales", len(df))
