
import io
import re
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

try:
    import pydeck as pdk
except Exception:
    pdk = None

st.set_page_config(
    page_title="M&A Renewable Deal Tracker",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_TITLE = "M&A Renewable Deal Tracker – Spain & Spanish Companies Abroad"
SAMPLE_FILE = "sample_deals.csv"

REQUIRED_COLUMNS = [
    "deal_id", "announcement_date", "closing_date", "year", "quarter", "deal_status",
    "transaction_type", "asset_or_company_name", "target_type", "buyer", "buyer_country",
    "buyer_type", "seller", "seller_country", "seller_type", "spanish_company_involved",
    "spanish_company_role", "description", "technology", "location_country", "location_region",
    "location_province", "location_city", "latitude", "longitude", "capacity_mw", "capacity_mwp",
    "storage_mwh", "number_of_assets", "development_stage", "cod_date", "regulated_or_merchant",
    "ppa_status", "ppa_counterparty", "remuneration_scheme", "grid_access_status",
    "environmental_permit_status", "deal_value_eur_m", "enterprise_value_eur_m", "equity_value_eur_m",
    "debt_assumed_eur_m", "price_per_mw_eur_m", "price_per_mwp_eur_m", "ownership_stake_acquired_pct",
    "implied_100pct_value_eur_m", "ev_ebitda", "revenue_eur_m", "ebitda_eur_m", "net_debt_eur_m",
    "advisors_buyer", "advisors_seller", "legal_advisor_buyer", "legal_advisor_seller",
    "financial_advisor_buyer", "financial_advisor_seller", "source_1", "source_2", "source_3",
    "source_quality_score", "notes", "last_updated",
]

NUMERIC_COLUMNS = [
    "year", "latitude", "longitude", "capacity_mw", "capacity_mwp", "storage_mwh", "number_of_assets",
    "deal_value_eur_m", "enterprise_value_eur_m", "equity_value_eur_m", "debt_assumed_eur_m",
    "price_per_mw_eur_m", "price_per_mwp_eur_m", "ownership_stake_acquired_pct",
    "implied_100pct_value_eur_m", "ev_ebitda", "revenue_eur_m", "ebitda_eur_m", "net_debt_eur_m",
    "source_quality_score",
]

STRATEGIC_BUYER_TYPES = {"utility", "oil & gas", "developer", "IPP", "corporate"}
FINANCIAL_BUYER_TYPES = {"infrastructure fund", "pension fund", "private equity", "sovereign fund", "family office"}


def fmt_eur_m(x):
    if pd.isna(x):
        return "n.d."
    return f"€{x:,.1f}m"


def fmt_num(x, suffix=""):
    if pd.isna(x):
        return "n.d."
    return f"{x:,.1f}{suffix}"


def clean_string(value):
    if pd.isna(value):
        return ""
    value = str(value).strip()
    value = re.sub(r"\s+", " ", value)
    return value


def normalize_technology(value):
    v = clean_string(value).lower()
    mapping = {
        "solar": "solar PV", "solar pv": "solar PV", "pv": "solar PV", "fotovoltaica": "solar PV",
        "onshore wind": "wind onshore", "wind": "wind onshore", "eólica": "wind onshore", "eolica": "wind onshore",
        "offshore wind": "wind offshore", "battery": "battery storage", "bess": "battery storage",
        "storage": "battery storage", "biomethane": "biomethane", "biometano": "biomethane",
        "biogas": "biogas", "hydrogen": "hydrogen", "hidrogeno": "hydrogen", "hydro": "hydro",
        "hybrid": "hybrid", "híbrido": "hybrid", "hibrido": "hybrid",
    }
    return mapping.get(v, clean_string(value) or "other")


def normalize_yes_no(value):
    v = clean_string(value).lower()
    if v in {"yes", "y", "true", "1", "si", "sí"}:
        return "yes"
    if v in {"no", "n", "false", "0"}:
        return "no"
    return "unknown"


def ensure_schema(df):
    df = df.copy()
    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    df = df[REQUIRED_COLUMNS + [c for c in df.columns if c not in REQUIRED_COLUMNS]]
    return df


def convert_types(df):
    df = df.copy()
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["announcement_date", "closing_date", "cod_date", "last_updated"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def add_calculated_fields(df):
    df = ensure_schema(convert_types(df))
    df = df.copy()

    for col in ["buyer", "seller", "asset_or_company_name", "location_country", "location_region", "location_province"]:
        df[col] = df[col].apply(clean_string)
    df["technology"] = df["technology"].apply(normalize_technology)
    df["spanish_company_involved"] = df["spanish_company_involved"].apply(normalize_yes_no)

    missing_year = df["year"].isna() & df["announcement_date"].notna()
    df.loc[missing_year, "year"] = df.loc[missing_year, "announcement_date"].dt.year
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")

    missing_q = (df["quarter"].isna() | (df["quarter"].astype(str).str.lower().isin(["nan", "", "none"]))) & df["announcement_date"].notna()
    df.loc[missing_q, "quarter"] = "Q" + df.loc[missing_q, "announcement_date"].dt.quarter.astype(str)

    df["disclosed_value_flag"] = df["deal_value_eur_m"].notna() | df["enterprise_value_eur_m"].notna() | df["equity_value_eur_m"].notna()
    df["disclosed_capacity_flag"] = df["capacity_mw"].notna() | df["capacity_mwp"].notna()

    effective_value = df["deal_value_eur_m"].combine_first(df["enterprise_value_eur_m"]).combine_first(df["equity_value_eur_m"])
    effective_mw = df["capacity_mw"].combine_first(df["capacity_mwp"])
    df["calculated_price_per_mw"] = np.where((effective_value.notna()) & (effective_mw > 0), effective_value / effective_mw, np.nan)
    df["price_per_mw_eur_m"] = df["price_per_mw_eur_m"].combine_first(df["calculated_price_per_mw"])

    stake = pd.to_numeric(df["ownership_stake_acquired_pct"], errors="coerce")
    df["implied_100pct_value"] = np.where((effective_value.notna()) & (stake > 0), effective_value / (stake / 100), np.nan)
    df["implied_100pct_value_eur_m"] = df["implied_100pct_value_eur_m"].combine_first(df["implied_100pct_value"])

    scope_conditions = [
        df["location_country"].str.lower().eq("spain"),
        df["spanish_company_involved"].eq("yes") & ~df["location_country"].str.lower().eq("spain"),
        df["location_country"].str.lower().isin(["spain", "portugal"]),
    ]
    scope_values = ["Spain renewable asset/company", "Spanish company abroad", "Iberia"]
    df["deal_scope"] = np.select(scope_conditions, scope_values, default="Global renewable platform")

    core_cols = ["deal_id", "announcement_date", "deal_status", "transaction_type", "asset_or_company_name", "buyer", "seller", "description", "technology", "location_country", "capacity_mw", "deal_value_eur_m", "source_1"]
    df["data_completion_pct"] = df[core_cols].notna().mean(axis=1) * 100

    dup_subset = ["announcement_date", "asset_or_company_name", "buyer", "seller", "technology", "location_country"]
    df["suspected_duplicate_flag"] = df.duplicated(subset=dup_subset, keep=False)
    df["strategic_buyer_flag"] = df["buyer_type"].str.lower().isin({x.lower() for x in STRATEGIC_BUYER_TYPES})
    df["financial_buyer_flag"] = df["buyer_type"].str.lower().isin({x.lower() for x in FINANCIAL_BUYER_TYPES})
    df["operational_asset_flag"] = df["development_stage"].str.lower().eq("operational")
    df["development_pipeline_flag"] = df["development_stage"].str.lower().isin(["development", "early stage", "ready-to-build", "under construction"])

    return df


@st.cache_data(show_spinner=False)
def load_sample_data():
    return pd.read_csv(SAMPLE_FILE)


def load_uploaded_file(uploaded_file):
    if uploaded_file is None:
        return load_sample_data(), "sample_deals.csv"
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file), uploaded_file.name
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded_file, engine="openpyxl" if name.endswith(".xlsx") else None), uploaded_file.name
    st.error("Formato no soportado. Sube un CSV o Excel.")
    st.stop()


def to_excel_bytes(df, sheet_name="Deals"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    return output.getvalue()


def build_markdown_summary(df):
    effective_value = df["deal_value_eur_m"].sum(min_count=1)
    effective_mw = df["capacity_mw"].sum(min_count=1)
    weighted = effective_value / effective_mw if pd.notna(effective_value) and pd.notna(effective_mw) and effective_mw > 0 else np.nan
    lines = [
        "# Executive Summary - Selected Renewable M&A Deals",
        f"- Number of selected deals: {len(df)}",
        f"- Total disclosed deal value: {fmt_eur_m(effective_value)}",
        f"- Total capacity: {fmt_num(effective_mw, ' MW')}",
        f"- Weighted average price: {fmt_eur_m(weighted)} / MW",
        "",
        "## Selected deals",
    ]
    for _, r in df.iterrows():
        lines.append(f"- **{r.get('asset_or_company_name','')}**: {r.get('buyer','')} acquiring from {r.get('seller','')} ({r.get('technology','')}, {r.get('location_country','')}, {fmt_num(r.get('capacity_mw'), ' MW')}, {fmt_eur_m(r.get('deal_value_eur_m'))}).")
    return "\n".join(lines)


def sidebar_filters(df):
    st.sidebar.header("Filtros")
    filtered = df.copy()

    years = sorted([int(x) for x in filtered["year"].dropna().unique()])
    if years:
        min_y, max_y = min(years), max(years)
        year_range = st.sidebar.slider("Año", min_y, max_y, (min_y, max_y))
        filtered = filtered[(filtered["year"].isna()) | ((filtered["year"] >= year_range[0]) & (filtered["year"] <= year_range[1]))]

    def multi_filter(col, label):
        nonlocal filtered
        vals = sorted([x for x in filtered[col].dropna().unique() if str(x).strip()])
        selected = st.sidebar.multiselect(label, vals)
        if selected:
            filtered = filtered[filtered[col].isin(selected)]

    for col, label in [
        ("deal_status", "Estado"), ("technology", "Tecnología"), ("location_country", "País del activo"),
        ("location_region", "Región"), ("location_province", "Provincia"), ("buyer", "Comprador"),
        ("seller", "Vendedor"), ("buyer_type", "Tipo comprador"), ("seller_type", "Tipo vendedor"),
        ("transaction_type", "Tipo transacción"), ("development_stage", "Fase del activo"),
        ("regulated_or_merchant", "Regulado/PPA/Merchant"),
    ]:
        multi_filter(col, label)

    if st.sidebar.checkbox("Solo activos/compañías en España"):
        filtered = filtered[filtered["deal_scope"].eq("Spain renewable asset/company")]
    if st.sidebar.checkbox("Solo internacionales con compañía española"):
        filtered = filtered[filtered["deal_scope"].eq("Spanish company abroad")]

    if filtered["capacity_mw"].notna().any():
        max_mw = float(np.nanmax(filtered["capacity_mw"].fillna(0)))
        mw_range = st.sidebar.slider("Rango MW", 0.0, max(max_mw, 1.0), (0.0, max(max_mw, 1.0)))
        filtered = filtered[(filtered["capacity_mw"].isna()) | (filtered["capacity_mw"].between(mw_range[0], mw_range[1]))]

    if filtered["deal_value_eur_m"].notna().any():
        max_val = float(np.nanmax(filtered["deal_value_eur_m"].fillna(0)))
        val_range = st.sidebar.slider("Rango importe EURm", 0.0, max(max_val, 1.0), (0.0, max(max_val, 1.0)))
        filtered = filtered[(filtered["deal_value_eur_m"].isna()) | (filtered["deal_value_eur_m"].between(val_range[0], val_range[1]))]

    value_filter = st.sidebar.radio("Importe divulgado", ["Todos", "Solo divulgado", "Solo no divulgado"], horizontal=False)
    if value_filter == "Solo divulgado":
        filtered = filtered[filtered["disclosed_value_flag"]]
    elif value_filter == "Solo no divulgado":
        filtered = filtered[~filtered["disclosed_value_flag"]]

    min_quality = st.sidebar.slider("Calidad mínima fuente", 1, 5, 1)
    filtered = filtered[(filtered["source_quality_score"].isna()) | (filtered["source_quality_score"] >= min_quality)]
    return filtered


def show_kpis(df):
    value = df["deal_value_eur_m"].sum(min_count=1)
    mw = df["capacity_mw"].sum(min_count=1)
    avg_price = value / mw if pd.notna(value) and pd.notna(mw) and mw > 0 else np.nan
    closed = df["deal_status"].str.lower().eq("closed").sum()
    pending = df["deal_status"].str.lower().isin(["announced", "pending"]).sum()
    top_buyer = df["buyer"].replace("", np.nan).dropna().mode().iat[0] if not df["buyer"].replace("", np.nan).dropna().empty else "n.d."
    top_seller = df["seller"].replace("", np.nan).dropna().mode().iat[0] if not df["seller"].replace("", np.nan).dropna().empty else "n.d."
    top_tech = df.groupby("technology")["deal_value_eur_m"].sum().sort_values(ascending=False).index[0] if df["deal_value_eur_m"].notna().any() else "n.d."
    top_year = df.groupby("year")["deal_value_eur_m"].sum().sort_values(ascending=False).index[0] if df["deal_value_eur_m"].notna().any() else "n.d."
    spanish_pct = (df["spanish_company_involved"].eq("yes").mean() * 100) if len(df) else 0
    price_pct = (df["disclosed_value_flag"].mean() * 100) if len(df) else 0

    rows = [
        [("Deals", f"{len(df):,}"), ("Valor anunciado", fmt_eur_m(value)), ("Capacidad", fmt_num(mw, " MW")), ("Valor medio/MW", fmt_eur_m(avg_price))],
        [("Cerradas", f"{closed:,}"), ("Announced/Pending", f"{pending:,}"), ("Top comprador", top_buyer), ("Top vendedor", top_seller)],
        [("Top tecnología", top_tech), ("Año top volumen", str(top_year)), ("% compañía española", f"{spanish_pct:.1f}%"), ("% precio divulgado", f"{price_pct:.1f}%")],
    ]
    for row in rows:
        cols = st.columns(4)
        for c, (label, val) in zip(cols, row):
            c.metric(label, val)


def charts_basic(df):
    c1, c2 = st.columns(2)
    with c1:
        annual = df.groupby("year", dropna=False).agg(deals=("deal_id", "count"), value=("deal_value_eur_m", "sum"), mw=("capacity_mw", "sum")).reset_index()
        st.plotly_chart(px.bar(annual, x="year", y="deals", title="Evolución anual del número de deals"), use_container_width=True)
        st.plotly_chart(px.bar(annual, x="year", y="mw", title="Capacidad MW transaccionada por año"), use_container_width=True)
    with c2:
        st.plotly_chart(px.bar(annual, x="year", y="value", title="Volumen transaccionado anual (EURm)"), use_container_width=True)
        tech = df.groupby("technology").agg(deals=("deal_id", "count"), value=("deal_value_eur_m", "sum")).reset_index()
        st.plotly_chart(px.pie(tech, names="technology", values="deals", title="Deals por tecnología"), use_container_width=True)


def show_screener(df):
    display_cols = ["deal_id", "announcement_date", "asset_or_company_name", "buyer", "seller", "technology", "location_country", "location_region", "capacity_mw", "deal_value_eur_m", "price_per_mw_eur_m", "ownership_stake_acquired_pct", "deal_status", "description", "source_1"]
    work = df[display_cols].copy()
    if "selected_deal_ids" not in st.session_state:
        st.session_state.selected_deal_ids = []
    work.insert(0, "select", work["deal_id"].isin(st.session_state.selected_deal_ids))
    edited = st.data_editor(work, hide_index=True, use_container_width=True, height=520, disabled=[c for c in work.columns if c != "select"])
    selected = edited.loc[edited["select"], "deal_id"].tolist()
    st.session_state.selected_deal_ids = selected
    st.caption(f"Operaciones seleccionadas: {len(selected)}")
    return selected


def show_detail(df):
    if df.empty:
        st.info("No hay operaciones en el filtro actual.")
        return
    selected_default = st.session_state.get("selected_deal_ids", [])
    options = df["deal_id"].astype(str).tolist()
    idx = options.index(str(selected_default[0])) if selected_default and str(selected_default[0]) in options else 0
    deal = st.selectbox("Selecciona operación", options, index=idx)
    r = df[df["deal_id"].astype(str).eq(str(deal))].iloc[0]
    st.subheader(r["asset_or_company_name"])
    st.write(r["description"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Comprador", r["buyer"] or "n.d.")
    c2.metric("Vendedor", r["seller"] or "n.d.")
    c3.metric("Capacidad", fmt_num(r["capacity_mw"], " MW"))
    c4.metric("Importe", fmt_eur_m(r["deal_value_eur_m"]))
    st.markdown("#### Ficha del deal")
    detail = {
        "Estructura": r["transaction_type"], "Estado": r["deal_status"], "Stake adquirido": fmt_num(r["ownership_stake_acquired_pct"], "%"),
        "Tecnología": r["technology"], "Localización": f"{r['location_city']}, {r['location_province']}, {r['location_region']}, {r['location_country']}",
        "Fase": r["development_stage"], "COD": r["cod_date"], "PPA/Merchant/Regulado": r["regulated_or_merchant"],
        "Grid access": r["grid_access_status"], "Environmental permit": r["environmental_permit_status"],
        "€/MW": fmt_eur_m(r["price_per_mw_eur_m"]), "Valor implícito 100%": fmt_eur_m(r["implied_100pct_value_eur_m"]),
        "Advisor comprador": r["advisors_buyer"], "Advisor vendedor": r["advisors_seller"],
        "Fuentes": " | ".join([clean_string(r.get(c, "")) for c in ["source_1", "source_2", "source_3"] if clean_string(r.get(c, ""))]),
        "Notas": r["notes"],
    }
    st.json(detail, expanded=False)


def comparable_transactions(df):
    selected = st.session_state.get("selected_deal_ids", [])
    comp = df[df["deal_id"].astype(str).isin([str(x) for x in selected])].copy()
    if comp.empty:
        st.info("Selecciona operaciones en la pestaña Deal Screener para compararlas.")
        return comp
    cols = ["asset_or_company_name", "deal_value_eur_m", "capacity_mw", "price_per_mw_eur_m", "technology", "location_country", "development_stage", "ownership_stake_acquired_pct", "buyer_type", "seller_type", "year", "deal_status", "regulated_or_merchant", "notes"]
    st.dataframe(comp[cols], use_container_width=True, hide_index=True)
    val = comp["deal_value_eur_m"].sum(min_count=1)
    mw = comp["capacity_mw"].sum(min_count=1)
    simple = comp["price_per_mw_eur_m"].mean()
    weighted = val / mw if pd.notna(val) and pd.notna(mw) and mw > 0 else np.nan
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Deals", len(comp)); c2.metric("Valor total", fmt_eur_m(val)); c3.metric("MW totales", fmt_num(mw, " MW")); c4.metric("€/MW simple", fmt_eur_m(simple)); c5.metric("€/MW ponderado", fmt_eur_m(weighted))
    c1, c2, c3 = st.columns(3)
    c1.plotly_chart(px.pie(comp, names="technology", title="Distribución por tecnología"), use_container_width=True)
    c2.plotly_chart(px.pie(comp, names="development_stage", title="Distribución por fase"), use_container_width=True)
    c3.plotly_chart(px.pie(comp, names="location_country", title="Distribución por país"), use_container_width=True)
    return comp


def market_analytics(df):
    c1, c2 = st.columns(2)
    with c1:
        tech_value = df.groupby("technology")["deal_value_eur_m"].sum().sort_values(ascending=False).reset_index()
        st.plotly_chart(px.bar(tech_value, x="technology", y="deal_value_eur_m", title="Deal value por tecnología"), use_container_width=True)
        top_buyers = df["buyer"].value_counts().head(10).reset_index(); top_buyers.columns = ["buyer", "deals"]
        st.plotly_chart(px.bar(top_buyers, x="deals", y="buyer", orientation="h", title="Top 10 compradores"), use_container_width=True)
        if df["price_per_mw_eur_m"].notna().any():
            st.plotly_chart(px.box(df, x="technology", y="price_per_mw_eur_m", color="development_stage", title="Boxplot €/MW por tecnología y fase"), use_container_width=True)
    with c2:
        top_sellers = df["seller"].value_counts().head(10).reset_index(); top_sellers.columns = ["seller", "deals"]
        st.plotly_chart(px.bar(top_sellers, x="deals", y="seller", orientation="h", title="Top 10 vendedores"), use_container_width=True)
        top_deals = df.sort_values("deal_value_eur_m", ascending=False).head(10)
        st.plotly_chart(px.bar(top_deals, x="deal_value_eur_m", y="asset_or_company_name", orientation="h", title="Top 10 deals por importe"), use_container_width=True)
        if df["capacity_mw"].notna().any() and df["deal_value_eur_m"].notna().any():
            st.plotly_chart(px.scatter(df, x="capacity_mw", y="deal_value_eur_m", color="technology", hover_name="asset_or_company_name", title="MW vs Deal Value"), use_container_width=True)
    heat = df.pivot_table(index="technology", columns="year", values="deal_id", aggfunc="count", fill_value=0)
    if not heat.empty:
        st.plotly_chart(px.imshow(heat, text_auto=True, title="Heatmap año vs tecnología"), use_container_width=True)
    scope = df["deal_scope"].value_counts().reset_index(); scope.columns = ["scope", "deals"]
    st.plotly_chart(px.bar(scope, x="scope", y="deals", title="España vs internacionales con compañía española"), use_container_width=True)


def valuation_benchmarking(df):
    st.subheader("Valuation Benchmarking")
    valid = df[df["price_per_mw_eur_m"].notna() & df["disclosed_value_flag"] & df["disclosed_capacity_flag"]].copy()
    if valid.empty:
        st.info("No hay suficientes operaciones con precio y capacidad divulgados.")
        return
    q1, q3 = valid["price_per_mw_eur_m"].quantile([0.25, 0.75])
    iqr = q3 - q1
    valid = valid[(valid["price_per_mw_eur_m"] >= q1 - 1.5 * iqr) & (valid["price_per_mw_eur_m"] <= q3 + 1.5 * iqr)]
    group_cols = st.multiselect("Agrupar por", ["technology", "development_stage", "location_country"], default=["technology", "development_stage"])
    if not group_cols:
        group_cols = ["technology"]
    bench = valid.groupby(group_cols)["price_per_mw_eur_m"].agg(
        deals="count", min="min", p25=lambda x: x.quantile(0.25), median="median", p75=lambda x: x.quantile(0.75), max="max"
    ).reset_index()
    st.dataframe(bench, use_container_width=True, hide_index=True)
    st.plotly_chart(px.bar(bench, x=group_cols[0], y="median", color=group_cols[1] if len(group_cols) > 1 else None, title="Mediana €/MW por benchmark"), use_container_width=True)


def strategic_insights(df):
    st.subheader("Strategic Insights")
    c1, c2 = st.columns(2)
    active_buyers = df["buyer"].value_counts().head(10).reset_index(); active_buyers.columns = ["buyer", "deals"]
    recurring_sellers = df["seller"].value_counts().head(10).reset_index(); recurring_sellers.columns = ["seller", "deals"]
    c1.dataframe(active_buyers, use_container_width=True, hide_index=True)
    c2.dataframe(recurring_sellers, use_container_width=True, hide_index=True)

    tech_liq = df.groupby("technology").agg(deals=("deal_id", "count"), value=("deal_value_eur_m", "sum"), mw=("capacity_mw", "sum")).sort_values("deals", ascending=False).reset_index()
    regions = df.groupby(["location_country", "location_region"]).agg(deals=("deal_id", "count"), value=("deal_value_eur_m", "sum")).sort_values("deals", ascending=False).reset_index().head(15)
    c1, c2 = st.columns(2)
    c1.plotly_chart(px.bar(tech_liq, x="technology", y="deals", title="Tecnologías con mayor liquidez"), use_container_width=True)
    c2.plotly_chart(px.bar(regions, x="deals", y="location_region", color="location_country", orientation="h", title="Regiones con más operaciones"), use_container_width=True)

    distressed = df[df["transaction_type"].str.lower().str.contains("distressed", na=False) | df["notes"].str.lower().str.contains("distressed|refinancing|restructur", na=False)]
    st.markdown("##### Activos distressed potenciales")
    st.dataframe(distressed[["deal_id", "asset_or_company_name", "buyer", "seller", "technology", "deal_value_eur_m", "notes"]], use_container_width=True, hide_index=True)

    trend = df[df["price_per_mw_eur_m"].notna()].groupby(["year", "technology"])["price_per_mw_eur_m"].median().reset_index()
    if not trend.empty:
        st.plotly_chart(px.line(trend, x="year", y="price_per_mw_eur_m", color="technology", markers=True, title="Cambio de tendencia en precios €/MW"), use_container_width=True)


def data_quality(df):
    st.subheader("Data Quality")
    missing_value = df[df["deal_value_eur_m"].isna()]
    missing_mw = df[df["capacity_mw"].isna()]
    missing_source = df[df["source_1"].isna() | df["source_1"].astype(str).str.strip().eq("")]
    ambiguous_status = df[~df["deal_status"].str.lower().isin(["announced", "closed", "pending", "cancelled", "rumoured"])]
    price = df["price_per_mw_eur_m"]
    if price.notna().sum() > 3:
        q1, q3 = price.quantile([0.25, 0.75]); iqr = q3 - q1
        anomalies = df[(price < q1 - 1.5 * iqr) | (price > q3 + 1.5 * iqr)]
    else:
        anomalies = pd.DataFrame(columns=df.columns)
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Sin importe", len(missing_value)); c2.metric("Sin MW", len(missing_mw)); c3.metric("Sin fuente", len(missing_source)); c4.metric("€/MW anómalo", len(anomalies)); c5.metric("Duplicados", int(df["suspected_duplicate_flag"].sum())); c6.metric("Status ambiguo", len(ambiguous_status))
    completion = (df.notna().mean() * 100).sort_values().reset_index(); completion.columns = ["field", "completion_pct"]
    st.plotly_chart(px.bar(completion.head(30), x="completion_pct", y="field", orientation="h", title="Campos menos completos (%)"), use_container_width=True)
    st.dataframe(df[["deal_id", "asset_or_company_name", "data_completion_pct", "source_quality_score", "suspected_duplicate_flag", "disclosed_value_flag", "disclosed_capacity_flag"]], use_container_width=True, hide_index=True)


def map_tab(df):
    geo = df[df["latitude"].notna() & df["longitude"].notna()].copy()
    if geo.empty:
        st.info("No hay coordenadas disponibles para mostrar mapa.")
        return
    if pdk is not None:
        layer = pdk.Layer(
            "ScatterplotLayer", data=geo, get_position="[longitude, latitude]", get_radius=5000,
            get_fill_color=[30, 144, 255, 160], pickable=True,
        )
        view = pdk.ViewState(latitude=float(geo["latitude"].mean()), longitude=float(geo["longitude"].mean()), zoom=4)
        st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, tooltip={"text": "{asset_or_company_name}\n{technology}\n{capacity_mw} MW"}))
    else:
        st.map(geo.rename(columns={"latitude": "lat", "longitude": "lon"})[["lat", "lon"]])


def main():
    st.title(APP_TITLE)
    st.caption("Herramienta financiera para screening, comparables, valoración y calidad de datos de M&A renovable. Los datos de ejemplo son ficticios.")

    st.sidebar.header("Carga de datos")
    uploaded = st.sidebar.file_uploader(
        "Subir CSV/Excel",
        type=["csv", "xlsx", "xls"],
        help="Si no subes archivo, se usa sample_deals.csv con datos ficticios.",
    )
    raw, source_name = load_uploaded_file(uploaded)
    df = add_calculated_fields(raw)
    filtered = sidebar_filters(df)

    if source_name == SAMPLE_FILE or df["notes"].astype(str).str.contains("sample data", case=False, na=False).any():
        st.warning("Estás usando datos ficticios de ejemplo marcados como sample data. Sustituye el CSV por una base real verificada para análisis profesional.")

    missing_cols = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing_cols:
        st.info(f"Se han creado columnas vacías para campos ausentes: {', '.join(missing_cols[:12])}{'...' if len(missing_cols) > 12 else ''}")

    tabs = st.tabs([
        "Executive Dashboard", "Deal Screener", "Deal Detail", "Comparable Transactions", "Market Analytics",
        "Map", "Valuation Benchmarking", "Strategic Insights", "Data Quality", "Upload & Export",
    ])

    with tabs[0]:
        show_kpis(filtered)
        charts_basic(filtered)
    with tabs[1]:
        show_screener(filtered)
    with tabs[2]:
        show_detail(filtered)
    with tabs[3]:
        comp = comparable_transactions(filtered)
    with tabs[4]:
        market_analytics(filtered)
    with tabs[5]:
        map_tab(filtered)
    with tabs[6]:
        valuation_benchmarking(filtered)
    with tabs[7]:
        strategic_insights(filtered)
    with tabs[8]:
        data_quality(filtered)
    with tabs[9]:
        st.subheader("Upload & Export")
        st.write(f"Fuente cargada: **{source_name}**")
        st.download_button("Descargar dataset filtrado CSV", filtered.to_csv(index=False).encode("utf-8"), "filtered_deals.csv", "text/csv")
        st.download_button("Descargar dataset filtrado Excel", to_excel_bytes(filtered), "filtered_deals.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        selected = filtered[filtered["deal_id"].astype(str).isin([str(x) for x in st.session_state.get("selected_deal_ids", [])])]
        st.download_button("Descargar operaciones seleccionadas Excel", to_excel_bytes(selected, "Selected"), "selected_deals.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        md = build_markdown_summary(selected) if not selected.empty else "# Executive Summary\nNo selected deals."
        st.download_button("Descargar resumen ejecutivo Markdown", md.encode("utf-8"), "executive_summary.md", "text/markdown")
        st.markdown("##### Plantilla de columnas")
        st.dataframe(pd.DataFrame({"column": REQUIRED_COLUMNS}), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
