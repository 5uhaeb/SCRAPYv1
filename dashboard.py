import os
import pandas as pd
import streamlit as st
import plotly.express as px
from dotenv import load_dotenv
from supabase import create_client

from scraper_common import run_scrape
from scrape_vijaysales import run as run_vijaysales
from scrape_webscraper_ecom import run as run_webscraper

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="E-commerce Scraper Dashboard", layout="wide")
st.title("E-commerce Scraper Dashboard")


@st.cache_data(ttl=60)
def load_data():
    res = supabase.table("products").select("*").execute()
    data = res.data or []
    df = pd.DataFrame(data)
    if not df.empty and "scraped_at" in df.columns:
        df["scraped_at"] = pd.to_datetime(df["scraped_at"], errors="coerce")
    return df


def refresh_data():
    load_data.clear()


st.sidebar.header("Run Scraper")

site = st.sidebar.selectbox("Site", ["vijaysales", "gsmarena", "webscraper"])
keywords_in = st.sidebar.text_input("Keywords (comma separated)", value="iphone")
gsmarena_url = ""

if site == "gsmarena":
    gsmarena_url = st.sidebar.text_input(
        "GSMArena URL",
        value="https://www.gsmarena.com/samsung-phones-9.php"
    )

pages = st.sidebar.number_input("Pages", min_value=1, max_value=10, value=2, step=1)

if st.sidebar.button("Run Scraper"):
    keywords = [k.strip() for k in keywords_in.split(",") if k.strip()]

    if not keywords:
        st.sidebar.error("Enter at least one keyword.")
    else:
        try:
            with st.spinner("Running scraper..."):
                if site == "vijaysales":
                    run_vijaysales(keywords, pages=pages, json_out="vijaysales_mobiles.json")

                elif site == "gsmarena":
                    if not gsmarena_url.strip():
                        st.sidebar.error("Enter GSMArena URL.")
                    else:
                        run_scrape("gsmarena", gsmarena_url.strip(), keywords, json_out="scraped.json")

                elif site == "webscraper":
                    run_webscraper(keywords, pages_per_cat=pages)

            refresh_data()
            st.sidebar.success("Scraping complete.")
            st.rerun()

        except Exception as e:
            st.sidebar.error(f"Scraper failed: {e}")

if st.sidebar.button("Refresh Dashboard"):
    refresh_data()
    st.rerun()

df = load_data()

if df.empty:
    st.warning("No data in DB yet. Run scraper first.")
    st.stop()

st.sidebar.header("Filters")

platforms = sorted(df["platform"].dropna().unique().tolist()) if "platform" in df.columns else []
keywords = sorted(df["keyword"].dropna().unique().tolist()) if "keyword" in df.columns else []

sel_platform = st.sidebar.multiselect("Platform Filter", platforms, default=platforms)
sel_keyword = st.sidebar.multiselect("Keyword Filter", keywords, default=keywords)

df_f = df.copy()

if sel_platform and "platform" in df_f.columns:
    df_f = df_f[df_f["platform"].isin(sel_platform)]

if sel_keyword and "keyword" in df_f.columns:
    df_f = df_f[df_f["keyword"].isin(sel_keyword)]

if "price" in df_f.columns and df_f["price"].notna().any():
    pmin = int(df_f["price"].dropna().min())
    pmax = int(df_f["price"].dropna().max())
    pr = st.sidebar.slider("Price range", pmin, pmax, (pmin, pmax))
    df_f = df_f[df_f["price"].isna() | ((df_f["price"] >= pr[0]) & (df_f["price"] <= pr[1]))]

st.subheader("Latest rows")
sort_col = "scraped_at" if "scraped_at" in df_f.columns else None

if sort_col:
    st.dataframe(df_f.sort_values(sort_col, ascending=False).head(50), use_container_width=True)
else:
    st.dataframe(df_f.head(50), use_container_width=True)

c1, c2 = st.columns(2)

with c1:
    st.subheader("Items count by Platform")
    if "platform" in df_f.columns and not df_f.empty:
        cnt = df_f.groupby("platform", as_index=False).size().rename(columns={"size": "count"})
        fig = px.bar(cnt, x="platform", y="count")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No platform data available.")

with c2:
    st.subheader("Price Distribution")
    d2 = df_f.dropna(subset=["price"]) if "price" in df_f.columns else pd.DataFrame()
    if d2.empty:
        st.info("No price data available for selected filters.")
    else:
        fig = px.histogram(d2, x="price", nbins=25, color="platform")
        st.plotly_chart(fig, use_container_width=True)

st.subheader("Top 10 expensive items")
d3 = df_f.dropna(subset=["price"]).sort_values("price", ascending=False).head(10) if "price" in df_f.columns else pd.DataFrame()

if d3.empty:
    st.info("No price data to rank.")
else:
    fig = px.bar(
        d3,
        x="price",
        y="title",
        orientation="h",
        color="platform",
        hover_data=["product_url", "keyword"]
    )
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Average price by Keyword")
d4 = df_f.dropna(subset=["price"]) if "price" in df_f.columns else pd.DataFrame()

if d4.empty:
    st.info("No price data to compute averages.")
else:
    avg = d4.groupby("keyword", as_index=False)["price"].mean()
    fig = px.bar(avg, x="keyword", y="price")
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Cheapest product per keyword")
d5 = df_f.dropna(subset=["price"]) if "price" in df_f.columns else pd.DataFrame()

if d5.empty:
    st.info("No price data available.")
else:
    cheapest = d5.sort_values("price").groupby("keyword").first().reset_index()
    st.dataframe(
        cheapest[["keyword", "title", "platform", "price", "product_url"]],
        column_config={
            "product_url": st.column_config.LinkColumn("Product Link")
        },
        use_container_width=True
    )