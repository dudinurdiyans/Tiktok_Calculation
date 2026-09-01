import re
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(
    page_title="TIK Cancellation Dashboard",
    page_icon="📦",
    layout="wide"
)

CANCEL_STATUSES = {"batal", "dibatalkan"}

REQUIRED_COLUMNS = [
    "Order ID",
    "Order Status",
    "Cancel Reason",
    "Delivery Option",
    "Created Time",
    "SKU Subtotal After Discount",
]

MONEY_COLUMNS = [
    "SKU Unit Original Price",
    "SKU Subtotal Before Discount",
    "SKU Platform Discount",
    "SKU Seller Discount",
    "Shipping Fee After Discount",
    "Original Shipping Fee",
    "Shipping Fee Seller Discount",
    "Shipping Fee Platform Discount",
    "Distance Shipping Fee",
    "Distance Fee",
    "Order Refund Amount",
    "Payment platform discount",
    "Buyer Service Fee",
    "Handling Fee",
    "Shipping Insurance",
    "Item Insurance",
    "Order Amount",
    
]


# ============================================================
# HELPERS
# ============================================================

def parse_idr(value):
    if pd.isna(value):
        return np.nan

    value = str(value).strip()

    if value in ["", "-", "nan", "None", "<NA>"]:
        return np.nan

    value = (
        value
        .replace("Rp", "")
        .replace("IDR", "")
        .replace(" ", "")
        .replace("\xa0", "")
    )

    negative = False

    if value.startswith("(") and value.endswith(")"):
        negative = True
        value = value[1:-1]

    if "." in value and "," in value:
        value = value.replace(".", "").replace(",", ".")

    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", value):
        value = value.replace(".", "")

    elif re.fullmatch(r"-?\d{1,3}(,\d{3})+", value):
        value = value.replace(",", "")

    elif "," in value:
        value = value.replace(",", ".")

    try:
        result = float(value)
        return -result if negative else result

    except Exception:
        return np.nan


def idr(value):
    return f"Rp {value:,.0f}"


def pct(value):
    return f"{value:.2%}"


def _parse_candidate(series, dayfirst):
    """
    Parse date candidate without changing already-correct datetime values.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")

    return pd.to_datetime(
        series,
        format="mixed",
        dayfirst=dayfirst,
        errors="coerce"
    )


def _date_score(parsed):
    """
    Lower score = better.

    Strongly penalizes future dates, because an order export should not
    contain order-created timestamps in the future.
    """
    today = pd.Timestamp.today().normalize()
    valid = parsed.dropna()

    if len(valid) == 0:
        return float("inf")

    future_count = (valid > today + pd.Timedelta(days=1)).sum()

    # Implausibly old / future years receive penalty too.
    bad_year_count = (
        (valid.dt.year < 2020)
        | (valid.dt.year > today.year + 1)
    ).sum()

    # Prefer a parse with more valid values.
    invalid_count = parsed.isna().sum()

    return (
        future_count * 100000
        + bad_year_count * 10000
        + invalid_count
    )


def smart_parse_datetime(series, mode="Auto"):
    """
    Auto compares day-first vs month-first and chooses the one that
    produces the fewest impossible future dates.

    This prevents examples such as:
      intended Aug 12 -> wrongly parsed Dec 8
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce"), "Already datetime"

    if mode == "Day-first (DD/MM/YYYY)":
        return _parse_candidate(series, True), "Day-first"

    if mode == "Month-first (MM/DD/YYYY)":
        return _parse_candidate(series, False), "Month-first"

    day_first = _parse_candidate(series, True)
    month_first = _parse_candidate(series, False)

    score_day = _date_score(day_first)
    score_month = _date_score(month_first)

    if score_month < score_day:
        return month_first, "Auto → Month-first"
    else:
        return day_first, "Auto → Day-first"


@st.cache_data(show_spinner=False)
def load_raw(uploaded_file):
    # Keep raw values as text to preserve Indonesian nominal formatting.
    return pd.read_excel(
        uploaded_file,
        engine="openpyxl",
        dtype=str
    )


def clean_data(raw, date_mode):
    missing = [
        col for col in REQUIRED_COLUMNS
        if col not in raw.columns
    ]

    if missing:
        raise ValueError(
            "Kolom wajib tidak ditemukan: "
            + ", ".join(missing)
        )

    data = raw.copy()

    parsed_dates, parser_used = smart_parse_datetime(
        data["Created Time"],
        mode=date_mode
    )

    data["Created Time"] = parsed_dates

    for col in MONEY_COLUMNS:
        if col in data.columns:
            data[col] = (
                data[col]
                .apply(parse_idr)
                .fillna(0)
            )

    for col in [
        "Order Status",
        "Delivery Option",
        "Cancel Reason",
    ]:
        data[col] = (
            data[col]
            .astype("string")
            .str.strip()
            .replace(
                ["", "nan", "None", "<NA>"],
                pd.NA
            )
        )

    # Remove invalid dates.
    data = data[
        data["Created Time"].notna()
    ].copy()

    # Safety: order-created date cannot be in the future.
    today = pd.Timestamp.today().normalize()

    future_rows = (
        data["Created Time"]
        > today + pd.Timedelta(days=1)
    ).sum()

    data = data[
        data["Created Time"]
        <= today + pd.Timedelta(days=1)
    ].copy()

    data["Bulan"] = (
        data["Created Time"]
        .dt.to_period("M")
    )

    data["Status Norm"] = (
        data["Order Status"]
        .astype("string")
        .str.strip()
        .str.casefold()
    )

    data["Is Dibatalkan"] = (
        data["Status Norm"]
        .isin(CANCEL_STATUSES)
    )

    data["Status Terisi"] = (
        data["Order Status"].notna()
        & data["Order Status"]
        .astype("string")
        .str.strip()
        .ne("")
    )

    return data, parser_used, int(future_rows)


def get_latest_existing_months(data, n_months=3):
    """
    IMPORTANT:
    Use ACTUAL months found in the dataset.
    Do not manufacture Oct/Nov/Dec from an erroneous max date.
    """
    available = sorted(
        data["Bulan"]
        .dropna()
        .unique()
        .tolist()
    )

    if not available:
        return []

    return available[-n_months:]


# ============================================================
# TASK 1
# ============================================================

def build_shipping_table(
    data_l3m,
    months,
    status_dashboard
):
    status_dashboard_norm = (
        str(status_dashboard)
        .strip()
        .casefold()
    )

    # Formula equivalent:
    # ALL      -> Status Pesanan <> blank
    # Selesai  -> Status Pesanan <> Batal/Dibatalkan
    if status_dashboard_norm == "selesai":
        mask_total = (
            data_l3m["Status Terisi"]
            & ~data_l3m["Is Dibatalkan"]
        )
    else:
        mask_total = data_l3m["Status Terisi"]

    data_formula = data_l3m.loc[
        mask_total
    ].copy()

    total_all = (
        data_formula["SKU Subtotal After Discount"]
        .sum()
    )

    data_all_shipping = data_formula[
        data_formula["Delivery Option"].notna()
    ].copy()

    monthly = (
        data_all_shipping
        .groupby(
            ["Delivery Option", "Bulan"],
            observed=True
        )["SKU Subtotal After Discount"]
        .sum()
        .unstack(fill_value=0)
        .reindex(
            columns=months,
            fill_value=0
        )
    )

    monthly[
        "Total ALL per Pengiriman (L3M)"
    ] = (
        monthly[list(months)]
        .sum(axis=1)
    )

    monthly[
        "% Dari Total Omzet ALL (L3M)"
    ] = np.where(
        total_all != 0,
        monthly[
            "Total ALL per Pengiriman (L3M)"
        ] / total_all,
        0
    )

    # Non-cancel = "Selesai" logic existing dashboard
    mask_selesai = (
        data_l3m["Status Terisi"]
        & ~data_l3m["Is Dibatalkan"]
    )

    data_selesai = data_l3m[
        mask_selesai
        & data_l3m["Delivery Option"].notna()
    ].copy()

    selesai_per_shipping = (
        data_selesai
        .groupby(
            "Delivery Option",
            observed=True
        )["SKU Subtotal After Discount"]
        .sum()
    )

    monthly[
        "Total Selesai per Pengiriman (L3M)"
    ] = (
        selesai_per_shipping
        .reindex(
            monthly.index,
            fill_value=0
        )
    )

    monthly[
        "% Selesai dari Total Omzet ALL (L3M)"
    ] = np.where(
        total_all != 0,
        monthly[
            "Total Selesai per Pengiriman (L3M)"
        ] / total_all,
        0
    )

    # Cancel
    data_batal = data_l3m[
        data_l3m["Is Dibatalkan"]
        & data_l3m["Delivery Option"].notna()
    ].copy()

    batal_per_shipping = (
        data_batal
        .groupby(
            "Delivery Option",
            observed=True
        )["SKU Subtotal After Discount"]
        .sum()
    )

    monthly[
        "Total Batal per Pengiriman (L3M)"
    ] = (
        batal_per_shipping
        .reindex(
            monthly.index,
            fill_value=0
        )
    )

    monthly[
        "% Batal dari Total Omzet ALL (L3M)"
    ] = np.where(
        total_all != 0,
        monthly[
            "Total Batal per Pengiriman (L3M)"
        ] / total_all,
        0
    )

    month_names = {
        month: month.strftime("%b %Y")
        for month in months
    }

    monthly = monthly.rename(
        columns=month_names
    )

    month_cols = [
        month.strftime("%b %Y")
        for month in months
    ]

    monthly = (
        monthly
        .sort_values(
            "Total ALL per Pengiriman (L3M)",
            ascending=False
        )
        .reset_index()
        .rename(
            columns={
                "Delivery Option": "Pengiriman"
            }
        )
    )

    column_order = (
        ["Pengiriman"]
        + month_cols
        + [
            "Total ALL per Pengiriman (L3M)",
            "% Dari Total Omzet ALL (L3M)",
            "Total Selesai per Pengiriman (L3M)",
            "% Selesai dari Total Omzet ALL (L3M)",
            "Total Batal per Pengiriman (L3M)",
            "% Batal dari Total Omzet ALL (L3M)",
        ]
    )

    return (
        total_all,
        monthly[column_order],
        data_formula
    )


# ============================================================
# TASK 2
# ============================================================

def build_instant_analysis(
    data_l3m,
    months,
    selected_instant_options
):
    if not selected_instant_options:
        return None

    instant = data_l3m[
        data_l3m["Status Terisi"]
        & data_l3m["Delivery Option"]
        .isin(selected_instant_options)
    ].copy()

    if instant.empty:
        return None

    total_omzet = (
        instant["SKU Subtotal After Discount"]
        .sum()
    )

    omzet_batal = (
        instant.loc[
            instant["Is Dibatalkan"],
            "SKU Subtotal After Discount"
        ]
        .sum()
    )

    omzet_tidak_batal = (
        instant.loc[
            ~instant["Is Dibatalkan"],
            "SKU Subtotal After Discount"
        ]
        .sum()
    )

    cancel_rate = (
        omzet_batal / total_omzet
        if total_omzet
        else 0
    )

    total_order = (
        instant["Order ID"]
        .nunique()
    )

    order_batal = (
        instant.loc[
            instant["Is Dibatalkan"],
            "Order ID"
        ]
        .nunique()
    )

    cancel_rate_order = (
        order_batal / total_order
        if total_order
        else 0
    )

    monthly_total = (
        instant
        .groupby(
            "Bulan",
            observed=True
        )["SKU Subtotal After Discount"]
        .sum()
        .reindex(
            months,
            fill_value=0
        )
    )

    monthly_cancel = (
        instant[
            instant["Is Dibatalkan"]
        ]
        .groupby(
            "Bulan",
            observed=True
        )["Subtotal Pesanan"]
        .sum()
        .reindex(
            months,
            fill_value=0
        )
    )

    trend = pd.DataFrame({
        "Bulan": [
            m.strftime("%b %Y")
            for m in months
        ],
        "Total Omzet Instan":
            monthly_total.values,
        "Omzet Batal":
            monthly_cancel.values,
    })

    trend[
        "Omzet Tidak Batal"
    ] = (
        trend["Total Omzet Instan"]
        - trend["Omzet Batal"]
    )

    trend["Cancel Rate"] = np.where(
        trend["Total Omzet Instan"] != 0,
        trend["Omzet Batal"]
        / trend["Total Omzet Instan"],
        0
    )

    cancel_data = instant[
        instant["Is Batal"]
    ].copy()

    cancel_data[
        "Cancel Reason"
    ] = (
        cancel_data["Cancel Reason"]
        .astype("string")
        .str.strip()
        .replace(
            ["", "nan", "None", "<NA>"],
            "Tidak Ada Keterangan"
        )
        .fillna(
            "Tidak Ada Keterangan"
        )
    )

    reason_table = (
        cancel_data
        .groupby(
            "Cancel Reason",
            observed=True
        )
        .agg(
            Omzet_Batal=(
                "SKU Subtotal After Discount",
                "sum"
            ),
            Jumlah_Order_Batal=(
                "Order ID",
                "nunique"
            ),
        )
        .reset_index()
        .sort_values(
            "Omzet_Batal",
            ascending=False
        )
    )

    reason_table[
        "% dari Omzet Batal Instan"
    ] = np.where(
        omzet_batal != 0,
        reason_table["Omzet_Batal"]
        / omzet_batal,
        0
    )

    shipping_base = data_l3m[
        data_l3m["Status Terisi"]
        & data_l3m["Delivery Option"].notna()
    ].copy()

    shipping_total = (
        shipping_base
        .groupby(
            "Delivery Option",
            observed=True
        )["SKU Subtotal After Discount"]
        .sum()
    )

    shipping_cancel = (
        shipping_base[
            shipping_base["Is Dibatalkan"]
        ]
        .groupby(
            "Delivery Option",
            observed=True
        )["SKU Subtotal After Discount"]
        .sum()
    )

    shipping_compare = pd.DataFrame({
        "Total Omzet": shipping_total,
        "Omzet Batal": shipping_cancel,
    }).fillna(0)

    shipping_compare[
        "Omzet Tidak Batal"
    ] = (
        shipping_compare["Total Omzet"]
        - shipping_compare["Omzet Batal"]
    )

    shipping_compare[
        "Cancel Rate"
    ] = np.where(
        shipping_compare["Total Omzet"] != 0,
        shipping_compare["Omzet Batal"]
        / shipping_compare["Total Omzet"],
        0
    )

    shipping_compare = (
        shipping_compare
        .sort_values(
            "Cancel Rate",
            ascending=False
        )
        .reset_index()
    )

    return {
        "instant": instant,
        "total_omzet": total_omzet,
        "omzet_batal": omzet_batal,
        "omzet_tidak_batal": omzet_tidak_batal,
        "cancel_rate": cancel_rate,
        "total_order": total_order,
        "order_batal": order_batal,
        "cancel_rate_order": cancel_rate_order,
        "trend": trend,
        "reason_table": reason_table,
        "shipping_compare": shipping_compare,
    }


# ============================================================
# UI
# ============================================================

st.title(
    "📦 TIK — Analisis Pengiriman & Pembatalan Instan"
)

uploaded_file = st.file_uploader(
    "Upload raw file pesanan TikTok (.xlsx)",
    type=["xlsx"]
)

if uploaded_file is None:
    st.info(
        "Upload file .xlsx untuk memulai."
    )
    st.stop()

raw = load_raw(uploaded_file)

# ------------------------------------------------------------
# DATE PARSER SETTING
# ------------------------------------------------------------

st.sidebar.header("Filter")

date_mode = st.sidebar.selectbox(
    "Format tanggal",
    [
        "Auto",
        "Day-first (DD/MM/YYYY)",
        "Month-first (MM/DD/YYYY)",
    ],
    index=0
)

try:
    data, parser_used, future_rows_removed = (
        clean_data(
            raw,
            date_mode=date_mode
        )
    )

except Exception as exc:
    st.error(
        f"Gagal membaca file: {exc}"
    )
    st.stop()

if data.empty:
    st.error(
        "Tidak ada tanggal valid setelah proses cleaning."
    )
    st.stop()

# ------------------------------------------------------------
# PERIOD FILTER
# ------------------------------------------------------------

n_months = st.sidebar.selectbox(
    "Periode",
    [1, 2, 3, 4, 5, 6],
    index=2,
    format_func=lambda value: f"L{value}M"
)

status_dashboard = st.sidebar.selectbox(
    "Status Dashboard Task 1",
    ["ALL", "Selesai"]
)

months = get_latest_existing_months(
    data,
    n_months=n_months
)

if not months:
    st.error(
        "Tidak ada periode yang dapat dianalisis."
    )
    st.stop()

data_l3m = data[
    data["Bulan"].isin(months)
].copy()

period_label = " | ".join(
    month.strftime("%b %Y")
    for month in months
)

# ------------------------------------------------------------
# INSTANT OPTIONS
# ------------------------------------------------------------

all_shipping_options = (
    data_l3m["Delivery Option"]
    .dropna()
    .drop_duplicates()
    .tolist()
)

instant_candidates = [
    option
    for option in all_shipping_options
    if re.search(
        r"instan|instant",
        str(option),
        flags=re.IGNORECASE
    )
]

if "Instan" in instant_candidates:
    instant_default = ["Instan"]
else:
    instant_default = instant_candidates

selected_instant_options = (
    st.sidebar.multiselect(
        "Opsi yang dianggap Pengiriman Instan",
        options=all_shipping_options,
        default=instant_default
    )
)

# ------------------------------------------------------------
# DATE DEBUG
# ------------------------------------------------------------

with st.expander(
    "Validasi Parsing Tanggal",
    expanded=True
):
    st.write(
        f"Parser yang digunakan: **{parser_used}**"
    )

    st.write(
        "Tanggal minimum:",
        data["Created Time"].min()
    )

    st.write(
        "Tanggal maksimum:",
        data["Created Time"].max()
    )

    st.write(
        f"Row future yang dibuang: "
        f"**{future_rows_removed:,}**"
    )

    month_check = (
        data
        .groupby(
            "Bulan",
            observed=True
        )
        .agg(
            Jumlah_Row=(
                "Order ID",
                "size"
            ),
            Omzet=(
                "SKU Subtotal After Discount",
                "sum"
            )
        )
        .reset_index()
    )

    month_check["Bulan"] = (
        month_check["Bulan"]
        .astype(str)
    )

    # Pastikan kolom Omzet benar-benar numerik
month_check["Omzet"] = pd.to_numeric(
    month_check["Omzet"],
    errors="coerce"
).fillna(0)

st.dataframe(
    month_check.style.format({
        "Omzet": "Rp {:,.0f}"
    }),
    use_container_width=True,
    hide_index=True
)

# ============================================================
# RINGKASAN
# ============================================================

st.subheader("Ringkasan Data")

r1, r2, r3 = st.columns(3)

r1.metric(
    "Jumlah Row",
    f"{len(data_l3m):,}"
)

r2.metric(
    "Order Unik",
    f"{data_l3m['Order ID'].nunique():,}"
)

r3.metric(
    "Periode",
    period_label
)


# ============================================================
# TASK 1
# ============================================================

st.divider()
st.header(
    "Task 1 — Analisis Pengiriman"
)

total_all, monthly, data_formula = (
    build_shipping_table(
        data_l3m,
        months,
        status_dashboard
    )
)

st.metric(
    f"Total Omzet ALL (L{n_months}M)",
    idr(total_all)
)

format_map = {
    month.strftime("%b %Y"):
        "Rp {:,.0f}"
    for month in months
}

format_map.update({
    "Total ALL per Pengiriman (L3M)":
        "Rp {:,.0f}",
    "% Dari Total Omzet ALL (L3M)":
        "{:.2%}",
    "Total Selesai per Pengiriman (L3M)":
        "Rp {:,.0f}",
    "% Selesai dari Total Omzet ALL (L3M)":
        "{:.2%}",
    "Total Batal per Pengiriman (L3M)":
        "Rp {:,.0f}",
    "% Batal dari Total Omzet ALL (L3M)":
        "{:.2%}",
})

st.dataframe(
    monthly.style.format(
        format_map
    ),
    use_container_width=True,
    hide_index=True
)

with st.expander(
    "Validasi Task 1",
    expanded=True
):
    st.write(
        f"Total Omzet ALL: **{idr(total_all)}**"
    )

    st.write(
        f"Jumlah row status terisi: "
        f"**{data_l3m['Status Terisi'].sum():,}**"
    )

    st.write(
        f"Jumlah row Batal: "
        f"**{data_l3m['Is Dibatalkan'].sum():,}**"
    )

    st.write(
        f"Omzet semua row L{n_months}M: "
        f"**{idr(data_l3m['SKU Subtotal After Discount'].sum())}**"
    )

    st.write(
        f"Omzet status terisi: "
        f"**{idr(data_l3m.loc[data_l3m['Status Terisi'], 'SKU Subtotal After Discount'].sum())}**"
    )

    st.write(
        f"Omzet Batal: "
        f"**{idr(data_l3m.loc[data_l3m['Is Dibatalkan'], 'SKU Subtotal After Discount'].sum())}**"
    )


# ============================================================
# TASK 2
# ============================================================

st.divider()
st.header(
    "Task 2 — Analisa Pembatalan Pengiriman Instan"
)

if not selected_instant_options:
    st.warning(
        "Pilih minimal satu opsi Pengiriman Instan "
        "di sidebar."
    )
    st.stop()

st.caption(
    "Opsi yang dianalisis: "
    + ", ".join(selected_instant_options)
)

inst = build_instant_analysis(
    data_l3m,
    months,
    selected_instant_options
)

if inst is None:
    st.warning(
        "Tidak ada data untuk opsi Instan yang dipilih."
    )
    st.stop()

k1, k2, k3, k4 = st.columns(4)

k1.metric(
    "Total Omzet Instan",
    idr(inst["total_omzet"])
)

k2.metric(
    "Omzet Batal Instan",
    idr(inst["omzet_batal"])
)

k3.metric(
    "Cancel Rate Instan",
    pct(inst["cancel_rate"])
)

k4.metric(
    "Order Batal Instan",
    f"{inst['order_batal']:,}"
)

# ------------------------------------------------------------
# RECONCILE TASK 1 VS TASK 2
# ------------------------------------------------------------

with st.expander(
    "Validasi Task 2 terhadap Task 1",
    expanded=True
):
    task1_instant_rows = monthly[
        monthly["Pengiriman"]
        .isin(selected_instant_options)
    ]

    task1_instant_total = (
        task1_instant_rows[
            "Total ALL per Pengiriman (L3M)"
        ]
        .sum()
    )

    task1_instant_batal = (
        task1_instant_rows[
            "Total Batal per Pengiriman (L3M)"
        ]
        .sum()
    )

    check_df = pd.DataFrame({
        "Validasi": [
            "Total Omzet Instan",
            "Omzet Batal Instan"
        ],
        "Task 1": [
            task1_instant_total,
            task1_instant_batal
        ],
        "Task 2": [
            inst["total_omzet"],
            inst["omzet_batal"]
        ]
    })

    check_df["Selisih"] = (
        check_df["Task 2"]
        - check_df["Task 1"]
    )

    st.dataframe(
        check_df.style.format({
            "Task 1": "Rp {:,.0f}",
            "Task 2": "Rp {:,.0f}",
            "Selisih": "Rp {:,.0f}",
        }),
        use_container_width=True,
        hide_index=True
    )

# ------------------------------------------------------------
# DONUT + TREND
# ------------------------------------------------------------

left, right = st.columns(2)

with left:
    donut_data = pd.DataFrame({
        "Status": [
            "Tidak Batal",
            "Batal"
        ],
        "Omzet": [
            inst["omzet_tidak_batal"],
            inst["omzet_batal"]
        ]
    })

    fig_donut = px.pie(
        donut_data,
        names="Status",
        values="Omzet",
        hole=0.55,
        title=(
            "Batal vs Tidak Batal — Omzet Instan"
        )
    )

    fig_donut.update_traces(
        textinfo="percent+label"
    )

    st.plotly_chart(
        fig_donut,
        use_container_width=True
    )

with right:
    trend_plot = inst[
        "trend"
    ].copy()

    trend_plot[
        "Cancel Rate (%)"
    ] = (
        trend_plot["Cancel Rate"]
        * 100
    )

    fig_trend = px.line(
        trend_plot,
        x="Bulan",
        y="Cancel Rate (%)",
        markers=True,
        title=(
            "Trend Cancel Rate Pengiriman Instan"
        )
    )

    fig_trend.update_yaxes(
        ticksuffix="%"
    )

    st.plotly_chart(
        fig_trend,
        use_container_width=True
    )

# ------------------------------------------------------------
# TREND TABLE
# ------------------------------------------------------------

st.subheader(
    "Trend Bulanan"
)

trend_display = inst[
    "trend"
].copy()

st.dataframe(
    trend_display.style.format({
        "Total Omzet Instan":
            "Rp {:,.0f}",
        "Omzet Batal":
            "Rp {:,.0f}",
        "Omzet Tidak Batal":
            "Rp {:,.0f}",
        "Cancel Rate":
            "{:.2%}",
    }),
    use_container_width=True,
    hide_index=True
)

# ------------------------------------------------------------
# CANCEL REASONS
# ------------------------------------------------------------

st.subheader(
    "Alasan Pembatalan Pengiriman Instan"
)

reason_display = inst[
    "reason_table"
].copy()

if reason_display.empty:
    st.info(
        "Tidak ada transaksi Instan berstatus Batal."
    )

else:
    reason_plot = reason_display.sort_values(
        "Omzet_Batal",
        ascending=True
    )

    fig_reason = px.bar(
        reason_plot,
        x="Omzet_Batal",
        y="Cancel Reason",
        orientation="h",
        title=(
            "Omzet Batal berdasarkan "
            "Cancel Reason"
        )
    )

    st.plotly_chart(
        fig_reason,
        use_container_width=True
    )

    st.dataframe(
        reason_display.style.format({
            "Omzet_Batal":
                "Rp {:,.0f}",
            "Jumlah_Order_Batal":
                "{:,.0f}",
            "% dari Omzet Batal Instan":
                "{:.2%}",
        }),
        use_container_width=True,
        hide_index=True
    )

# ------------------------------------------------------------
# SHIPPING BENCHMARK
# ------------------------------------------------------------

st.subheader(
    "Benchmark Cancel Rate per Opsi Pengiriman"
)

shipping_compare = inst[
    "shipping_compare"
].copy()

shipping_plot = (
    shipping_compare.copy()
)

shipping_plot[
    "Cancel Rate (%)"
] = (
    shipping_plot["Cancel Rate"]
    * 100
)

shipping_plot = (
    shipping_plot
    .sort_values(
        "Cancel Rate (%)",
        ascending=True
    )
)

fig_shipping = px.bar(
    shipping_plot,
    x="Cancel Rate (%)",
    y="Delivery Option",
    orientation="h",
    title=(
        "Perbandingan Cancel Rate "
        "antar Opsi Pengiriman"
    )
)

fig_shipping.update_xaxes(
    ticksuffix="%"
)

st.plotly_chart(
    fig_shipping,
    use_container_width=True
)

st.dataframe(
    shipping_compare.style.format({
        "Total Omzet":
            "Rp {:,.0f}",
        "Omzet Batal":
            "Rp {:,.0f}",
        "Omzet Tidak Batal":
            "Rp {:,.0f}",
        "Cancel Rate":
            "{:.2%}",
    }),
    use_container_width=True,
    hide_index=True
)
