"""
app.py - Streamlit Presentation Layer
Retail Sales ETL & Analytics Platform — HCLTech Hackathon
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import pandas as pd
import plotly.express as px

from config import DATABASE_URL, setup_logging
from database.db_connection import get_engine, test_connection
from database.models import create_all_tables, truncate_all_tables
from ingestion.ingest_api import (
    fetch_from_api, load_from_csv, load_from_json,
    filter_to_required_schema, load_raw_to_db
)
from transformation.transform import transform
from aggregation.aggregate import aggregate

logger = setup_logging("app")

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Retail Sales ETL Platform",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.stApp { background: linear-gradient(135deg, #0f0c29, #302b63, #24243e); }

section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
    border-right: 1px solid #e94560;
}

.kpi-card {
    background: linear-gradient(135deg, #1a1a2e, #16213e);
    border: 1px solid #e94560;
    border-radius: 16px;
    padding: 22px 18px;
    text-align: center;
    margin-bottom: 8px;
    box-shadow: 0 4px 20px rgba(233,69,96,0.15);
    transition: transform 0.2s;
}
.kpi-card:hover { transform: translateY(-4px); }
.kpi-title { color: #a0aec0; font-size: 13px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; }
.kpi-value { color: #e94560; font-size: 34px; font-weight: 700; margin: 8px 0 4px; }
.kpi-sub   { color: #718096; font-size: 12px; }

.section-header {
    background: linear-gradient(90deg, #e94560, #0f3460);
    border-radius: 10px;
    padding: 10px 20px;
    color: white;
    font-size: 16px;
    font-weight: 700;
    margin: 18px 0 10px;
}

.badge-ok  { background:#1a472a; color:#68d391; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:600; }
.badge-err { background:#742a2a; color:#fc8181; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:600; }

div.stButton > button {
    background: linear-gradient(135deg, #e94560, #0f3460);
    color: white;
    border: none;
    border-radius: 10px;
    padding: 10px 28px;
    font-weight: 700;
    font-size: 14px;
    width: 100%;
    transition: opacity 0.2s;
}
div.stButton > button:hover { opacity: 0.85; }
</style>
""", unsafe_allow_html=True)

PLOT_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e2e8f0", family="Inter"),
    margin=dict(l=20, r=20, t=40, b=20),
)
COLOR_SEQ = ["#e94560","#0f3460","#533483","#e2b714","#06d6a0","#118ab2","#ffd166"]


# ── Engine & session state ─────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def get_db_engine():
    return get_engine()

engine = get_db_engine()

for key in ["raw_df", "transformed_df", "aggregated_df", "data_loaded"]:
    if key not in st.session_state:
        st.session_state[key] = None if key.endswith("_df") else False


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 🛒 Retail ETL Platform")
    st.markdown("**HCLTech · Data Engineering**")
    st.markdown("---")

    # DB connection status
    ok = test_connection(engine)
    badge = '<span class="badge-ok">● Connected</span>' if ok else '<span class="badge-err">● Disconnected</span>'
    st.markdown(f"**Database:** {badge}", unsafe_allow_html=True)
    st.caption(DATABASE_URL.split("@")[-1])
    st.markdown("---")

    # ── Data Source Selection ──────────────────────────────────────────────────
    st.markdown("### 📥 Data Source")
    source = st.radio(
        "Choose data source:",
        ["🌐 Fetch from API", "📄 Upload CSV", "📋 Upload JSON"],
        label_visibility="collapsed"
    )

    uploaded_file = None

    if source == "📄 Upload CSV":
        uploaded_file = st.file_uploader("Upload CSV file", type=["csv"])
    elif source == "📋 Upload JSON":
        uploaded_file = st.file_uploader("Upload JSON file", type=["json"])

    st.markdown("---")

    # ── Load Data Button ───────────────────────────────────────────────────────
    st.markdown("### ⚙️ Pipeline Controls")

    if st.button("📡 Load Data", key="btn_load"):
        create_all_tables(engine)
        try:
            with st.spinner("Loading data …"):
                if source == "🌐 Fetch from API":
                    raw = fetch_from_api()
                elif source == "📄 Upload CSV":
                    if uploaded_file is None:
                        st.warning("⚠️ Please upload a CSV file first.")
                        st.stop()
                    raw = load_from_csv(uploaded_file)
                else:  # JSON
                    if uploaded_file is None:
                        st.warning("⚠️ Please upload a JSON file first.")
                        st.stop()
                    raw = load_from_json(uploaded_file)

                filtered = filter_to_required_schema(raw)
                load_raw_to_db(filtered, engine)
                st.session_state.raw_df     = filtered
                st.session_state.data_loaded = True
                # reset downstream
                st.session_state.transformed_df  = None
                st.session_state.aggregated_df   = None

        except Exception as e:
            st.error(f"❌ Data load failed: {e}")

    # ── Run ETL Button ─────────────────────────────────────────────────────────
    if st.button("⚡ Run ETL Pipeline", key="btn_etl"):
        if not st.session_state.data_loaded:
            st.warning("⚠️ Load data first.")
        else:
            bar = st.progress(0, text="Transforming …")
            try:
                t_df = transform(engine)
                st.session_state.transformed_df = t_df
                bar.progress(60, text="Aggregating …")

                a_df = aggregate(engine)
                st.session_state.aggregated_df = a_df
                bar.progress(100, text="Done ✅")
            except Exception as e:
                st.error(f"❌ ETL failed: {e}")

    # ── Reset Database ─────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🗑️ Reset Database")
    confirm = st.checkbox(
        "I confirm — this will erase all data in all tables.",
        key="confirm_reset"
    )
    if st.button("🗑️ Reset All Tables", key="btn_reset", disabled=not confirm):
        try:
            truncate_all_tables(engine)
            # clear session state too
            for k in ["raw_df", "transformed_df", "aggregated_df"]:
                st.session_state[k] = None
            st.session_state.data_loaded = False
            st.success("✅ All tables truncated — raw_sales, transformed_sales, aggregated_sales are now empty.")
        except Exception as e:
            st.error(f"❌ Reset failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN AREA
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("# 🛒 Retail Sales ETL & Analytics Platform")
st.markdown("**End-to-end pipeline: Data Source → PostgreSQL → Insights**")
st.markdown("---")

tab_raw, tab_transform, tab_analytics = st.tabs([
    "📥 Raw Data", "🔄 Transformed Data", "📊 Analytics"
])


# ──────────────────────────────────────────────────────────────────────────────
# TAB 1 – Raw Data
# ──────────────────────────────────────────────────────────────────────────────
with tab_raw:
    st.markdown('<div class="section-header">📥 Raw Data — raw_sales</div>', unsafe_allow_html=True)

    raw = st.session_state.raw_df
    if raw is not None and not raw.empty:
        c1, c2, c3 = st.columns(3)
        c1.markdown(f'<div class="kpi-card"><div class="kpi-title">Records</div><div class="kpi-value">{len(raw):,}</div><div class="kpi-sub">from source</div></div>', unsafe_allow_html=True)
        c2.markdown(f'<div class="kpi-card"><div class="kpi-title">Columns</div><div class="kpi-value">{len(raw.columns)}</div><div class="kpi-sub">required schema</div></div>', unsafe_allow_html=True)
        c3.markdown(f'<div class="kpi-card"><div class="kpi-title">Null Values</div><div class="kpi-value">{int(raw.isnull().sum().sum())}</div><div class="kpi-sub">before cleaning</div></div>', unsafe_allow_html=True)

        st.markdown("#### Raw Records")
        st.dataframe(raw, use_container_width=True, height=380)

        st.markdown("#### Data Issues Found")
        issues = {
            "Missing order_date":    int(raw["order_date"].isna().sum()),
            "Missing unit_price":    int(raw["unit_price"].isna().sum()),
            "Missing quantity_sold": int(raw["quantity_sold"].isna().sum()),
        }
        st.table(pd.DataFrame(issues.items(), columns=["Issue", "Count"]))
    else:
        st.info("👈 Select a data source and click **Load Data** in the sidebar.")


# ──────────────────────────────────────────────────────────────────────────────
# TAB 2 – Transformed Data
# ──────────────────────────────────────────────────────────────────────────────
with tab_transform:
    st.markdown('<div class="section-header">🔄 Transformed Data — transformed_sales</div>', unsafe_allow_html=True)

    t_df = st.session_state.transformed_df
    raw  = st.session_state.raw_df

    if t_df is not None and not t_df.empty:
        removed = (len(raw) - len(t_df)) if raw is not None else 0
        score   = round((len(t_df) / len(raw)) * 100, 1) if raw is not None and len(raw) > 0 else 100

        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f'<div class="kpi-card"><div class="kpi-title">Clean Records</div><div class="kpi-value">{len(t_df):,}</div><div class="kpi-sub">passed validation</div></div>', unsafe_allow_html=True)
        c2.markdown(f'<div class="kpi-card"><div class="kpi-title">Removed</div><div class="kpi-value">{removed}</div><div class="kpi-sub">invalid / duplicate</div></div>', unsafe_allow_html=True)
        c3.markdown(f'<div class="kpi-card"><div class="kpi-title">Quality Score</div><div class="kpi-value">{score}%</div><div class="kpi-sub">pass rate</div></div>', unsafe_allow_html=True)
        c4.markdown(f'<div class="kpi-card"><div class="kpi-title">Total Sales</div><div class="kpi-value">₹{t_df["total_sales"].sum():,.0f}</div><div class="kpi-sub">derived field</div></div>', unsafe_allow_html=True)

        st.markdown("#### Transformation Rules Applied")
        rules = [
            ["Remove duplicates",        "drop_duplicates(subset=['order_id'])",  "✅"],
            ["Handle nulls",             "fillna store / product / category",     "✅"],
            ["Parse dates",              "pd.to_datetime(errors='coerce')",        "✅"],
            ["Remove invalid qty/price", "quantity_sold > 0 AND unit_price > 0",  "✅"],
            ["total_sales (derived)",    "quantity_sold × unit_price",            "✅"],
            ["order_month (derived)",    "YYYY-MM period string",                 "✅"],
            ["order_day (derived)",      "Day name e.g. Monday",                  "✅"],
        ]
        st.table(pd.DataFrame(rules, columns=["Rule", "Logic", "Status"]))

        st.markdown("#### Transformed Records")
        st.dataframe(t_df, use_container_width=True, height=380)
    else:
        st.info("👈 Click **Run ETL Pipeline** in the sidebar.")


# ──────────────────────────────────────────────────────────────────────────────
# TAB 3 – Analytics
# ──────────────────────────────────────────────────────────────────────────────
with tab_analytics:
    st.markdown('<div class="section-header">📊 Analytics — aggregated_sales</div>', unsafe_allow_html=True)

    agg = st.session_state.aggregated_df
    if agg is not None and not agg.empty:
        total_rev = agg["total_sales"].sum()
        total_qty = agg["total_quantity"].sum()
        total_ord = agg["total_orders"].sum()
        avg_order = total_rev / total_ord if total_ord else 0

        k1, k2, k3, k4 = st.columns(4)
        k1.markdown(f'<div class="kpi-card"><div class="kpi-title">💰 Total Revenue</div><div class="kpi-value">₹{total_rev:,.0f}</div><div class="kpi-sub">all stores, all months</div></div>', unsafe_allow_html=True)
        k2.markdown(f'<div class="kpi-card"><div class="kpi-title">📦 Units Sold</div><div class="kpi-value">{total_qty:,}</div><div class="kpi-sub">total quantity</div></div>', unsafe_allow_html=True)
        k3.markdown(f'<div class="kpi-card"><div class="kpi-title">🧾 Total Orders</div><div class="kpi-value">{total_ord:,}</div><div class="kpi-sub">across all stores</div></div>', unsafe_allow_html=True)
        k4.markdown(f'<div class="kpi-card"><div class="kpi-title">📈 Avg Order Value</div><div class="kpi-value">₹{avg_order:,.0f}</div><div class="kpi-sub">revenue / orders</div></div>', unsafe_allow_html=True)

        st.markdown("---")
        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("#### 🏷️ Sales by Category")
            cat_df = (agg.groupby("product_category", as_index=False)["total_sales"]
                      .sum().sort_values("total_sales", ascending=True))
            fig = px.bar(cat_df, x="total_sales", y="product_category", orientation="h",
                         color="product_category", color_discrete_sequence=COLOR_SEQ,
                         labels={"total_sales": "Revenue (₹)", "product_category": "Category"})
            fig.update_layout(**PLOT_LAYOUT, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        with col_b:
            st.markdown("#### 🏪 Sales by Store")
            store_df = (agg.groupby("store_id", as_index=False)["total_sales"]
                        .sum().sort_values("total_sales", ascending=False).head(10))
            fig2 = px.bar(store_df, x="store_id", y="total_sales",
                          color="total_sales", color_continuous_scale=["#0f3460", "#e94560"],
                          labels={"total_sales": "Revenue (₹)", "store_id": "Store"})
            fig2.update_layout(**PLOT_LAYOUT, coloraxis_showscale=False)
            st.plotly_chart(fig2, use_container_width=True)

        st.markdown("#### 📅 Monthly Revenue Trend")
        mon_df = (agg.groupby("order_month", as_index=False)["total_sales"]
                  .sum().sort_values("order_month"))
        fig3 = px.area(mon_df, x="order_month", y="total_sales",
                       color_discrete_sequence=["#e94560"],
                       labels={"total_sales": "Revenue (₹)", "order_month": "Month"})
        fig3.update_traces(fill="tozeroy", line=dict(width=2.5))
        fig3.update_layout(**PLOT_LAYOUT)
        st.plotly_chart(fig3, use_container_width=True)

        col_c, col_d = st.columns(2)
        with col_c:
            st.markdown("#### 🥧 Revenue Share by Category")
            fig4 = px.pie(cat_df, names="product_category", values="total_sales",
                          color_discrete_sequence=COLOR_SEQ, hole=0.45)
            fig4.update_layout(**PLOT_LAYOUT)
            st.plotly_chart(fig4, use_container_width=True)

        with col_d:
            st.markdown("#### 📋 Aggregated Summary")
            st.dataframe(agg.sort_values("total_sales", ascending=False),
                         use_container_width=True, height=320)
    else:
        st.info("👈 Run the ETL pipeline to generate analytics.")


# (Database Engineer tab removed — SQL reference available in main.py / models.py)
if False:
    st.markdown('<div class="section-header">🗄️ Database Engineer — Table Creation, Inserts & Queries</div>', unsafe_allow_html=True)

    st.markdown("### 1️⃣ Table Creation DDL")
    st.code("""
-- Layer 3: Raw Data (no transformation)
CREATE TABLE IF NOT EXISTS raw_sales (
    id               SERIAL PRIMARY KEY,
    order_id         VARCHAR,
    order_date       VARCHAR,
    store_id         VARCHAR,
    product_id       VARCHAR,
    product_category VARCHAR,
    quantity_sold    INTEGER,
    unit_price       FLOAT,
    ingested_at      TIMESTAMP DEFAULT NOW()
);

-- Layer 5: Transformed / Cleaned Data
CREATE TABLE IF NOT EXISTS transformed_sales (
    id               SERIAL PRIMARY KEY,
    order_id         VARCHAR,
    order_date       DATE,
    store_id         VARCHAR,
    product_id       VARCHAR,
    product_category VARCHAR,
    quantity_sold    INTEGER,
    unit_price       FLOAT,
    total_sales      FLOAT,
    order_month      VARCHAR,
    order_day        VARCHAR,
    transformed_at   TIMESTAMP DEFAULT NOW()
);

-- Layer 7: Aggregated (GROUP BY — no order_id)
CREATE TABLE IF NOT EXISTS aggregated_sales (
    id               SERIAL PRIMARY KEY,
    store_id         VARCHAR   NOT NULL,
    product_category VARCHAR   NOT NULL,
    order_month      VARCHAR   NOT NULL,
    total_sales      FLOAT,
    total_quantity   INTEGER,
    total_orders     INTEGER,
    aggregated_at    TIMESTAMP DEFAULT NOW()
);

-- Error tracking
CREATE TABLE IF NOT EXISTS error_records (
    id           SERIAL PRIMARY KEY,
    source_table VARCHAR,
    order_id     VARCHAR,
    error_type   VARCHAR,
    error_detail TEXT,
    logged_at    TIMESTAMP DEFAULT NOW()
);
""", language="sql")

    st.markdown("### 2️⃣ Sample INSERT Statements")
    st.code("""
-- raw_sales
INSERT INTO raw_sales (order_id, order_date, store_id, product_id,
                       product_category, quantity_sold, unit_price)
VALUES ('ORD-A1B2C3D4', '2024-03-15', 'STORE_001', 'PROD-1042',
        'Electronics', 12, 199.99);

-- transformed_sales
INSERT INTO transformed_sales (order_id, order_date, store_id, product_id,
    product_category, quantity_sold, unit_price, total_sales, order_month, order_day)
VALUES ('ORD-A1B2C3D4', '2024-03-15', 'STORE_001', 'PROD-1042',
        'Electronics', 12, 199.99, 2399.88, '2024-03', 'Friday');
""", language="sql")

    st.markdown("### 3️⃣ Aggregation Query")
    st.code("""
-- GROUP BY aggregation
INSERT INTO aggregated_sales
    (store_id, product_category, order_month, total_sales, total_quantity, total_orders)
SELECT
    store_id,
    product_category,
    order_month,
    SUM(total_sales)   AS total_sales,
    SUM(quantity_sold) AS total_quantity,
    COUNT(order_id)    AS total_orders
FROM transformed_sales
GROUP BY store_id, product_category, order_month
ORDER BY order_month, store_id;
""", language="sql")

    st.markdown("### 4️⃣ Query Aggregated Data")
    st.code("""
-- Top store-category combos by revenue
SELECT store_id, product_category,
       SUM(total_sales)    AS revenue,
       SUM(total_quantity) AS units,
       SUM(total_orders)   AS orders
FROM aggregated_sales
GROUP BY store_id, product_category
ORDER BY revenue DESC
LIMIT 10;

-- Monthly revenue trend
SELECT order_month, SUM(total_sales) AS monthly_revenue
FROM aggregated_sales
GROUP BY order_month
ORDER BY order_month;
""", language="sql")

    st.markdown("### 5️⃣ Data Consistency Checks")
    st.code("""
-- Row counts across layers
SELECT 'raw_sales'         AS layer, COUNT(*) FROM raw_sales
UNION ALL
SELECT 'transformed_sales',           COUNT(*) FROM transformed_sales
UNION ALL
SELECT 'aggregated_sales',            COUNT(*) FROM aggregated_sales;

-- Revenue reconciliation (transformed vs aggregated must match)
SELECT
    ROUND(SUM(total_sales)::numeric, 2) AS transformed_total
FROM transformed_sales;

SELECT
    ROUND(SUM(total_sales)::numeric, 2) AS aggregated_total
FROM aggregated_sales;

-- Duplicate order_ids in transformed
SELECT order_id, COUNT(*) AS cnt
FROM transformed_sales
GROUP BY order_id
HAVING COUNT(*) > 1;
""", language="sql")

    st.markdown("### 6️⃣ Live Row Counts")
    if test_connection(engine):
        rows = []
        for tbl, layer in [
            ("raw_sales",         "Layer 3 – Raw"),
            ("transformed_sales", "Layer 5 – Transformed"),
            ("aggregated_sales",  "Layer 7 – Aggregated"),
        ]:
            try:
                n = pd.read_sql(f"SELECT COUNT(*) AS n FROM {tbl}", engine)["n"].iloc[0]
            except Exception:
                n = "—"
            rows.append({"Table": tbl, "Row Count": n, "Layer": layer})
        st.table(pd.DataFrame(rows))
    else:
        st.warning("Database not connected.")
