import streamlit as st
import sqlite3
import pandas as pd
import altair as alt
from datetime import datetime
from pathlib import Path

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Inventory Alert System", page_icon="📦", layout="wide")

# ── Database setup (file-based so it persists) ─────────────────────────────────
DB_PATH = Path(__file__).parent / "inventory.db"

@st.cache_resource
def get_connection():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT    NOT NULL,
            quantity  INTEGER NOT NULL DEFAULT 0,
            threshold INTEGER NOT NULL DEFAULT 10
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS restock_orders (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            quantity   INTEGER NOT NULL,
            timestamp  TEXT    NOT NULL
        )
    """)
    # Seed sample data if empty
    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        sample = [
            ("Laptop",       45, 20),
            ("Mouse",         8, 15),
            ("Keyboard",     12, 10),
            ("Monitor",       3, 5),
            ("USB Hub",      22, 10),
            ("Webcam",        6, 8),
            ("Headset",      18, 10),
            ("Desk Chair",    2, 5),
        ]
        cur.executemany("INSERT INTO products (name, quantity, threshold) VALUES (?,?,?)", sample)
        conn.commit()
    return conn

conn = get_connection()

# ── Helper functions ───────────────────────────────────────────────────────────
def get_products():
    return pd.read_sql("SELECT * FROM products ORDER BY name", conn)

def get_restock_orders():
    return pd.read_sql("""
        SELECT r.id, p.name AS product, r.quantity, r.timestamp
        FROM restock_orders r
        LEFT JOIN products p ON p.id = r.product_id
        ORDER BY r.timestamp DESC
    """, conn)

def update_quantity(product_id: int, new_qty: int):
    conn.execute("UPDATE products SET quantity=? WHERE id=?", (new_qty, product_id))
    conn.commit()

def add_product(name: str, qty: int, threshold: int):
    conn.execute("INSERT INTO products (name, quantity, threshold) VALUES (?,?,?)",
                 (name, qty, threshold))
    conn.commit()

def generate_restock(product_id: int, qty: int):
    conn.execute(
        "INSERT INTO restock_orders (product_id, quantity, timestamp) VALUES (?,?,?)",
        (product_id, qty, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()

# ── Main UI ────────────────────────────────────────────────────────────────────
st.title("📦 Inventory Alert System")

products_df = get_products()
low_stock   = products_df[products_df["quantity"] <= products_df["threshold"]]

# ── Alert banner ──────────────────────────────────────────────────────────────
if not low_stock.empty:
    st.error(f"🚨 **{len(low_stock)} item(s) below restock threshold!**  "
             + "  |  ".join(f"{r['name']} ({r['quantity']} left)" for _, r in low_stock.iterrows()))

# ── KPI strip ─────────────────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Products",    len(products_df))
k2.metric("Low Stock Items",   len(low_stock),   delta=f"-{len(low_stock)}" if len(low_stock) else None)
k3.metric("Total Units",       int(products_df["quantity"].sum()))
k4.metric("Avg Stock Level",   round(products_df["quantity"].mean(), 1))

st.divider()

# ── Stock levels chart ────────────────────────────────────────────────────────
st.subheader("📊 Current Stock Levels")
chart_data = products_df.copy()
chart_data["status"] = chart_data.apply(
    lambda r: "Low" if r["quantity"] <= r["threshold"] else "OK", axis=1
)
bar = (
    alt.Chart(chart_data)
    .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
    .encode(
        x=alt.X("name:N", sort="-y", title="Product"),
        y=alt.Y("quantity:Q", title="Qty in Stock"),
        color=alt.Color("status:N",
                        scale=alt.Scale(domain=["OK","Low"],
                                        range=["#4f46e5","#ef4444"])),
        tooltip=["name", "quantity", "threshold", "status"],
    )
    .properties(height=300)
)
thresh_line = (
    alt.Chart(chart_data)
    .mark_rule(strokeDash=[4,4], color="#f97316", strokeWidth=2)
    .encode(y="threshold:Q")
)
st.altair_chart(bar + thresh_line, use_container_width=True)

st.divider()

# ── Data table ────────────────────────────────────────────────────────────────
col_table, col_actions = st.columns([3, 2])

with col_table:
    st.subheader("📋 All Products")
    display_df = products_df[["id","name","quantity","threshold"]].copy()
    display_df["status"] = display_df.apply(
        lambda r: "⚠️ Low" if r["quantity"] <= r["threshold"] else "✅ OK", axis=1
    )
    st.dataframe(display_df, use_container_width=True, hide_index=True)

with col_actions:
    st.subheader("⚙️ Actions")

    with st.expander("📝 Update Stock Quantity", expanded=True):
        prod_names  = products_df["name"].tolist()
        sel_update  = st.selectbox("Product", prod_names, key="upd_sel")
        sel_row     = products_df[products_df["name"] == sel_update].iloc[0]
        new_qty     = st.number_input("New quantity", min_value=0,
                                      value=int(sel_row["quantity"]), key="upd_qty")
        if st.button("✅ Update", use_container_width=True, type="primary"):
            update_quantity(int(sel_row["id"]), new_qty)
            st.success(f"✅ {sel_update} updated to {new_qty} units")
            st.rerun()

    with st.expander("🔁 Generate Restock Order"):
        sel_restock = st.selectbox("Product", prod_names, key="rst_sel")
        rst_row     = products_df[products_df["name"] == sel_restock].iloc[0]
        rst_qty     = st.number_input("Order quantity", min_value=1, value=20, key="rst_qty")
        if st.button("📦 Place Restock Order", use_container_width=True):
            generate_restock(int(rst_row["id"]), rst_qty)
            st.success(f"✅ Restock order placed: {rst_qty} × {sel_restock}")
            st.rerun()

    with st.expander("➕ Add New Product"):
        new_name  = st.text_input("Product name", key="new_name")
        new_stock = st.number_input("Initial stock", min_value=0, value=50, key="new_stock")
        new_thr   = st.number_input("Restock threshold", min_value=1, value=10, key="new_thr")
        if st.button("➕ Add Product", use_container_width=True):
            if new_name.strip():
                add_product(new_name.strip(), new_stock, new_thr)
                st.success(f"✅ Added '{new_name}'")
                st.rerun()
            else:
                st.warning("Enter a product name first.")

st.divider()

# ── Restock order history ─────────────────────────────────────────────────────
st.subheader("🕐 Restock Order History")
orders_df = get_restock_orders()
if orders_df.empty:
    st.info("No restock orders yet. Use the **Generate Restock Order** panel above.")
else:
    st.dataframe(orders_df, use_container_width=True, hide_index=True)
