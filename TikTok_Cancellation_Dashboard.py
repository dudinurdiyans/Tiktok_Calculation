
import streamlit as st
import pandas as pd
import numpy as np
import re
import plotly.express as px

st.set_page_config(
    page_title="TikTok Cancellation Dashboard",
    page_icon="📦",
    layout="wide"
)

CANCEL_STATUSES = {
    "cancelled",
    "canceled",
    "cancel"
}

REQUIRED_COLUMNS = [
    "Order ID",
    "Order Status",
    "Created Time",
    "SKU Subtotal After Discount",
    "Shipping Provider Name",
    "Cancel Reason"
]

MONEY_COLUMNS = [
    "SKU Unit Original Price",
    "SKU Subtotal Before Discount",
    "SKU Platform Discount",
    "SKU Seller Discount",
    "SKU Subtotal After Discount",
    "Order Refund Amount",
    "Order Amount"
]


def parse_money(x):
    if pd.isna(x):
        return 0
    x = str(x).replace("Rp","").replace(".","").replace(",","").strip()
    try:
        return float(x)
    except:
        return 0


def parse_date(series):
    return pd.to_datetime(
        series,
        errors="coerce",
        dayfirst=True
    )


@st.cache_data
def load_file(file):
    return pd.read_excel(file, dtype=str)


def clean_data(df):
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError("Missing columns: " + ", ".join(missing))

    df = df.copy()

    df["Created Time"] = parse_date(df["Created Time"])

    for c in MONEY_COLUMNS:
        if c in df.columns:
            df[c] = df[c].apply(parse_money)

    df["Status Normal"] = (
        df["Order Status"]
        .astype(str)
        .str.lower()
        .str.strip()
    )

    df["Is Cancel"] = (
        df["Status Normal"]
        .isin(CANCEL_STATUSES)
    )

    df["Month"] = (
        df["Created Time"]
        .dt.to_period("M")
    )

    return df.dropna(subset=["Created Time"])


st.title("📦 TikTok Order Cancellation Dashboard")

file = st.file_uploader(
    "Upload TikTok Order Export (.xlsx)",
    type=["xlsx"]
)

if file:

    try:
        raw = load_file(file)
        df = clean_data(raw)

    except Exception as e:
        st.error(str(e))
        st.stop()

    period = st.sidebar.selectbox(
        "Period",
        [1,2,3,6],
        index=2
    )

    months = sorted(df["Month"].unique())[-period:]

    df = df[df["Month"].isin(months)]

    st.subheader("Summary")

    c1,c2,c3 = st.columns(3)

    c1.metric(
        "Rows",
        f"{len(df):,}"
    )

    c2.metric(
        "Unique Orders",
        f"{df['Order ID'].nunique():,}"
    )

    c3.metric(
        "Period",
        " | ".join([str(x) for x in months])
    )


    st.divider()

    st.header("Task 1 — Shipping Provider Analysis")

    shipping = (
        df.groupby("Shipping Provider Name")
        .agg(
            GMV=("SKU Subtotal After Discount","sum"),
            Cancel_GMV=("SKU Subtotal After Discount",
                        lambda x: x[df.loc[x.index,"Is Cancel"]].sum())
        )
        .reset_index()
    )

    shipping["Cancel Rate"] = (
        shipping["Cancel_GMV"] /
        shipping["GMV"]
    ).replace([np.inf,np.nan],0)

    shipping = shipping.sort_values(
        "GMV",
        ascending=False
    )

    st.dataframe(
        shipping.style.format({
            "GMV":"Rp {:,.0f}",
            "Cancel_GMV":"Rp {:,.0f}",
            "Cancel Rate":"{:.2%}"
        }),
        use_container_width=True
    )


    fig = px.bar(
        shipping,
        x="Shipping Provider Name",
        y="Cancel Rate",
        title="Cancel Rate by Shipping Provider"
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )


    st.divider()

    st.header("Task 2 — Cancellation Analysis")

    total_gmv = df["SKU Subtotal After Discount"].sum()
    cancel_gmv = df.loc[
        df["Is Cancel"],
        "SKU Subtotal After Discount"
    ].sum()

    a,b,c = st.columns(3)

    a.metric("Total GMV", f"Rp {total_gmv:,.0f}")
    b.metric("Cancel GMV", f"Rp {cancel_gmv:,.0f}")
    c.metric(
        "Cancel Rate",
        f"{cancel_gmv/total_gmv:.2%}" if total_gmv else "0%"
    )


    reason = (
        df[df["Is Cancel"]]
        .groupby("Cancel Reason")
        ["SKU Subtotal After Discount"]
        .sum()
        .reset_index()
        .sort_values(
            "SKU Subtotal After Discount",
            ascending=False
        )
    )

    st.subheader("Cancel Reason")

    st.dataframe(
        reason.style.format({
            "SKU Subtotal After Discount":
            "Rp {:,.0f}"
        }),
        use_container_width=True
    )

    fig2 = px.bar(
        reason,
        x="SKU Subtotal After Discount",
        y="Cancel Reason",
        orientation="h",
        title="Cancel GMV by Reason"
    )

    st.plotly_chart(
        fig2,
        use_container_width=True
    )

else:
    st.info("Upload TikTok order file to start.")
