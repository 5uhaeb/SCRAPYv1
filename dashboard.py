import asyncio
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

BACKEND_DIR = Path(__file__).parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from scrapers.registry import SCRAPERS, get_scraper  # noqa: E402
from supabase_db import upsert_products  # noqa: E402

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="E-commerce Scraper Dashboard", layout="wide")
st.title("E-commerce Scraper Dashboard")


@st.cache_data(ttl=60)
def load_products():
    res = supabase.table("products").select("*").execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return df
    if "platform" in df.columns and "source_platform" not in df.columns:
        df["source_platform"] = df["platform"]
    if "scraped_at" in df.columns:
        df["scraped_at"] = pd.to_datetime(df["scraped_at"], errors="coerce")
    if "price" in df.columns:
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
    return df


@st.cache_data(ttl=60)
def load_history(product_hash: str | None = None):
    query = supabase.table("price_history").select("*").order("scraped_at")
    if product_hash:
        query = query.eq("product_hash", product_hash)
    df = pd.DataFrame(query.execute().data or [])
    if df.empty:
        return df
    df["scraped_at"] = pd.to_datetime(df["scraped_at"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    return df


def refresh_data():
    load_products.clear()
    load_history.clear()


async def run_scrapers(sites: list[str], keywords: list[str], pages: int):
    scrapers = [get_scraper(site) for site in sites]
    results = await asyncio.gather(
        *(scraper.run(keywords, pages=pages) for scraper in scrapers),
        return_exceptions=True,
    )
    items = []
    errors = []
    for site, result in zip(sites, results):
        if isinstance(result, Exception):
            errors.append(f"{site}: {result}")
        else:
            items.extend(result)
    saved = upsert_products(items)
    return saved, len(items), errors


st.sidebar.header("Run Scraper")

available_sites = sorted(SCRAPERS)
selected_sites = st.sidebar.multiselect("Sites", available_sites, default=["vijaysales"] if "vijaysales" in available_sites else available_sites[:1])
keywords_in = st.sidebar.text_input("Keywords (comma separated)", value="iphone 15")
pages = st.sidebar.number_input("Pages", min_value=1, max_value=10, value=2, step=1)

if st.sidebar.button("Run Scraper"):
    keywords = [keyword.strip() for keyword in keywords_in.split(",") if keyword.strip()]
    if not selected_sites:
        st.sidebar.error("Select at least one site.")
    elif not keywords:
        st.sidebar.error("Enter at least one keyword.")
    else:
        try:
            with st.spinner("Running selected scrapers..."):
                saved, scraped, errors = asyncio.run(run_scrapers(selected_sites, keywords, pages))
            refresh_data()
            if errors:
                st.sidebar.warning("; ".join(errors))
            st.sidebar.success(f"Scraped {scraped} rows, saved {saved}.")
            st.rerun()
        except Exception as exc:
            st.sidebar.error(f"Scraper failed: {exc}")

if st.sidebar.button("Refresh Dashboard"):
    refresh_data()
    st.rerun()

df = load_products()

if df.empty:
    st.warning("No data in DB yet. Run scraper first.")
    st.stop()

st.sidebar.header("Filters")

platforms = sorted(df["source_platform"].dropna().unique().tolist()) if "source_platform" in df.columns else []
keywords = sorted(df["keyword"].dropna().unique().tolist()) if "keyword" in df.columns else []

sel_platforms = st.sidebar.multiselect("Platform Filter", platforms, default=platforms)
sel_keywords = st.sidebar.multiselect("Keyword Filter", keywords, default=keywords)

df_f = df.copy()

if sel_platforms and "source_platform" in df_f.columns:
    df_f = df_f[df_f["source_platform"].isin(sel_platforms)]

if sel_keywords and "keyword" in df_f.columns:
    df_f = df_f[df_f["keyword"].isin(sel_keywords)]

if "price" in df_f.columns and df_f["price"].notna().any():
    pmin = int(df_f["price"].dropna().min())
    pmax = int(df_f["price"].dropna().max())
    price_range = st.sidebar.slider("Price range", pmin, pmax, (pmin, pmax))
    df_f = df_f[df_f["price"].isna() | ((df_f["price"] >= price_range[0]) & (df_f["price"] <= price_range[1]))]

overview_tab, history_tab, compare_tab = st.tabs(["Overview", "Price History", "Cross-platform Comparison"])

with overview_tab:
    st.subheader("Latest rows")
    sort_col = "scraped_at" if "scraped_at" in df_f.columns else None
    display = df_f.sort_values(sort_col, ascending=False).head(50) if sort_col else df_f.head(50)
    st.dataframe(display, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Items count by platform")
        if "source_platform" in df_f.columns and not df_f.empty:
            count_df = df_f.groupby("source_platform", as_index=False).size().rename(columns={"size": "count"})
            st.plotly_chart(px.bar(count_df, x="source_platform", y="count"), use_container_width=True)
        else:
            st.info("No platform data available.")

    with c2:
        st.subheader("Price distribution")
        price_df = df_f.dropna(subset=["price"]) if "price" in df_f.columns else pd.DataFrame()
        if price_df.empty:
            st.info("No price data available for selected filters.")
        else:
            st.plotly_chart(px.histogram(price_df, x="price", nbins=25, color="source_platform"), use_container_width=True)

    st.subheader("Average price by keyword")
    avg_df = df_f.dropna(subset=["price"]) if "price" in df_f.columns else pd.DataFrame()
    if avg_df.empty:
        st.info("No price data to compute averages.")
    else:
        avg = avg_df.groupby("keyword", as_index=False)["price"].mean()
        st.plotly_chart(px.bar(avg, x="keyword", y="price"), use_container_width=True)

with history_tab:
    st.subheader("Price History")
    product_options = (
        df_f.dropna(subset=["product_hash"])
        .sort_values("title")
        .assign(label=lambda frame: frame["title"].fillna("Untitled") + " - " + frame["source_platform"].fillna(""))
    )
    if product_options.empty:
        st.info("No products with product_hash available.")
    else:
        selected_label = st.selectbox("Product", product_options["label"].tolist())
        product_hash = product_options.loc[product_options["label"] == selected_label, "product_hash"].iloc[0]
        hist = load_history(product_hash)
        if hist.empty:
            st.info("No history for this product yet.")
        else:
            fig = px.line(hist, x="scraped_at", y="price", color="source_platform", markers=True)
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(hist.sort_values("scraped_at", ascending=False), use_container_width=True)

with compare_tab:
    st.subheader("Cheapest per keyword across all sites")
    price_df = df_f.dropna(subset=["price"]) if "price" in df_f.columns else pd.DataFrame()
    if price_df.empty:
        st.info("No price data available.")
    else:
        cheapest = price_df.sort_values("price").groupby("keyword", as_index=False).first()
        cols = ["keyword", "title", "source_platform", "price", "product_url"]
        st.dataframe(
            cheapest[[col for col in cols if col in cheapest.columns]],
            column_config={"product_url": st.column_config.LinkColumn("Product Link")},
            use_container_width=True,
        )

        st.subheader("Platform spread by keyword")
        spread = (
            price_df.groupby(["keyword", "source_platform"], as_index=False)["price"]
            .min()
            .sort_values(["keyword", "price"])
        )
        fig = px.bar(spread, x="keyword", y="price", color="source_platform", barmode="group")
        st.plotly_chart(fig, use_container_width=True)
