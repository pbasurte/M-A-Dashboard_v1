
import io
import re
import hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="Renewable M&A Tracker v4", page_icon="⚡", layout="wide")

MASTER_FILE = "deals_master_2020_2026.csv"
RECENT_FILE = "recent_candidates.csv"
APP_TITLE = "M&A Renewable Deal Tracker v4 – Master Database + Recent Updates"

COLUMNS = [
    "deal_id","announcement_date","year","quarter","deal_status","validation_status","transaction_type","asset_or_company_name","target_type",
    "buyer","buyer_country","buyer_type","seller","seller_country","seller_type","spanish_company_involved","spanish_company_role",
    "description","technology","location_country","location_region","location_province","location_city","capacity_mw","capacity_mwp","storage_mwh","number_of_assets",
    "development_stage","regulated_or_merchant","ppa_status","grid_access_status","environmental_permit_status","deal_value_eur_m","enterprise_value_eur_m","equity_value_eur_m","debt_assumed_eur_m","price_per_mw_eur_m","ownership_stake_acquired_pct","implied_100pct_value_eur_m",
    "source_1","source_2","source_3","source_quality_score","source_type","source_domain","source_url","article_title","article_date","ingestion_date","last_seen_date","extraction_method","extraction_confidence_score","duplicate_group_id","raw_text_excerpt","notes","last_updated"
]
NUMERIC = ["year","capacity_mw","capacity_mwp","storage_mwh","number_of_assets","deal_value_eur_m","enterprise_value_eur_m","equity_value_eur_m","debt_assumed_eur_m","price_per_mw_eur_m","ownership_stake_acquired_pct","implied_100pct_value_eur_m","source_quality_score","extraction_confidence_score"]

RECENT_QUERIES = [
    "renewable acquisition Spain", "solar portfolio sale Spain", "wind portfolio acquisition Spain",
    "renovables M&A España", "compra cartera renovable España", "vende cartera renovable España",
    "Iberdrola renewable acquisition", "Acciona Energia renewable sale", "Repsol renewable portfolio sale",
    "Naturgy renewable acquisition", "EDPR renewable portfolio Spain", "Spanish renewable company acquisition"
]

TECH_PATTERNS = {
    "solar PV": r"solar|fotovoltaic|fotovoltaica|pv",
    "wind onshore": r"wind|eólic|eolic|onshore",
    "wind offshore": r"offshore",
    "battery storage": r"battery|bess|storage|almacenamiento|bater",
    "biomethane": r"biomethane|biometano",
    "biogas": r"biogas|biogás",
    "hydrogen": r"hydrogen|hidrógeno|hidrogeno",
    "hydro": r"hydro|hidroeléctr",
}

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def clean(x):
    if pd.isna(x): return ""
    return re.sub(r"\s+", " ", str(x)).strip()

def ensure_schema(df):
    if df is None or df.empty:
        df = pd.DataFrame(columns=COLUMNS)
    for c in COLUMNS:
        if c not in df.columns: df[c] = np.nan
    return df[COLUMNS + [c for c in df.columns if c not in COLUMNS]]

def load_csv(path):
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=COLUMNS)

def normalize(df):
    df = ensure_schema(df).copy()
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["announcement_date","article_date","ingestion_date","last_seen_date","last_updated"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    if df.empty:
        df["disclosed_value_flag"] = False
        df["disclosed_capacity_flag"] = False
        df["deal_scope"] = "Global / unknown"
        df["data_completion_pct"] = np.nan
        df["suspected_duplicate_flag"] = False
        return df
    missing_year = df["year"].isna() & df["announcement_date"].notna()
    df.loc[missing_year,"year"] = df.loc[missing_year,"announcement_date"].dt.year
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    missing_q = (df["quarter"].isna() | df["quarter"].astype(str).isin(["", "nan", "NaT"])) & df["announcement_date"].notna()
    df.loc[missing_q,"quarter"] = "Q" + df.loc[missing_q,"announcement_date"].dt.quarter.astype(str)
    ev = df["deal_value_eur_m"].combine_first(df["enterprise_value_eur_m"]).combine_first(df["equity_value_eur_m"])
    mw = df["capacity_mw"].combine_first(df["capacity_mwp"])
    df["disclosed_value_flag"] = ev.notna()
    df["disclosed_capacity_flag"] = mw.notna()
    calc_ppmw = np.where((ev.notna()) & (mw > 0), ev / mw, np.nan)
    df["price_per_mw_eur_m"] = df["price_per_mw_eur_m"].combine_first(pd.Series(calc_ppmw, index=df.index))
    stake = df["ownership_stake_acquired_pct"]
    implied = np.where((ev.notna()) & (stake > 0), ev/(stake/100), np.nan)
    df["implied_100pct_value_eur_m"] = df["implied_100pct_value_eur_m"].combine_first(pd.Series(implied, index=df.index))
    loc = df["location_country"].fillna("").astype(str).str.lower()
    sp = df["spanish_company_involved"].fillna("").astype(str).str.lower()
    df["deal_scope"] = np.select([loc.eq("spain"), sp.eq("yes") & ~loc.eq("spain")], ["Spain renewable asset/company", "Spanish company abroad"], default="Global / unknown")
    key = df[["asset_or_company_name","buyer","seller","announcement_date"]].fillna("").astype(str).agg("|".join, axis=1).str.lower()
    df["suspected_duplicate_flag"] = key.duplicated(keep=False)
    core = ["deal_id","announcement_date","buyer","seller","asset_or_company_name","technology","location_country","capacity_mw","deal_value_eur_m","source_1"]
    df["data_completion_pct"] = df[core].notna().mean(axis=1) * 100
    return df

def domain(url):
    try: return urlparse(url).netloc.lower().replace("www.", "")
    except Exception: return ""

def stable_id(url, title):
    raw = f"{url}|{title}".lower().encode("utf-8")
    return "CAND-" + hashlib.sha1(raw).hexdigest()[:12].upper()

def infer_tech(text):
    t = text.lower()
    hits = [k for k,p in TECH_PATTERNS.items() if re.search(p,t)]
    return "hybrid" if len(hits) > 1 else (hits[0] if hits else "other")

def infer_country(text):
    t = text.lower()
    if any(x in t for x in ["spain","españa","spanish","iberdrola","acciona","repsol","naturgy","solaria"]): return "Spain"
    if "portugal" in t: return "Portugal"
    for c in ["Italy","France","Germany","United Kingdom","United States","Mexico","Brazil","Chile"]:
        if c.lower() in t: return c
    return ""

def extract_numbers(text):
    t = text.replace(",", ".")
    mw = val = stake = np.nan
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GW|gigawatts?)", t, re.I)
    if m: mw = float(m.group(1))*1000
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(MW|MWp|megawatts?)", t, re.I)
        if m: mw = float(m.group(1))
    m = re.search(r"(?:€|EUR|euros?)\s*(\d+(?:\.\d+)?)\s*(?:m|million|millones|mn|M)?", t, re.I)
    if not m: m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|million|millones|mn|M)\s*(?:€|EUR|euros?)", t, re.I)
    if m: val = float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", t)
    if m: stake = float(m.group(1))
    return mw, val, stake

def article_to_candidate(a):
    title = clean(a.get("title"))
    desc = clean(a.get("seendate") or a.get("description") or "")
    url = clean(a.get("url"))
    text = f"{title}. {desc}"
    date = pd.to_datetime(a.get("seendate"), errors="coerce")
    date_str = date.date().isoformat() if pd.notna(date) else ""
    mw, val, stake = extract_numbers(text)
    return {
        "deal_id": stable_id(url, title), "announcement_date": date_str, "year": date.year if pd.notna(date) else np.nan, "quarter":"", "deal_status":"announced", "validation_status":"pending_review",
        "transaction_type":"candidate", "asset_or_company_name": title[:120], "target_type":"unknown", "buyer":"", "buyer_country":"", "buyer_type":"", "seller":"", "seller_country":"", "seller_type":"",
        "spanish_company_involved":"yes" if re.search(r"spain|españa|spanish|iberdrola|acciona|repsol|naturgy|solaria", text, re.I) else "unknown", "spanish_company_role":"unknown",
        "description": text[:600], "technology": infer_tech(text), "location_country": infer_country(text), "location_region":"", "location_province":"", "location_city":"",
        "capacity_mw": mw, "capacity_mwp": np.nan, "storage_mwh":np.nan, "number_of_assets":np.nan, "development_stage":"unknown", "regulated_or_merchant":"unknown", "ppa_status":"unknown", "grid_access_status":"unknown", "environmental_permit_status":"unknown",
        "deal_value_eur_m": val, "enterprise_value_eur_m":val, "equity_value_eur_m":np.nan, "debt_assumed_eur_m":np.nan, "price_per_mw_eur_m": val/mw if pd.notna(val) and pd.notna(mw) and mw>0 else np.nan, "ownership_stake_acquired_pct": stake, "implied_100pct_value_eur_m": val/(stake/100) if pd.notna(val) and pd.notna(stake) and stake>0 else np.nan,
        "source_1":url, "source_2":"", "source_3":"", "source_quality_score":2, "source_type":"GDELT recent", "source_domain":domain(url), "source_url":url, "article_title":title, "article_date":date_str, "ingestion_date":now_iso(), "last_seen_date":now_iso(), "extraction_method":"gdelt_recent_v4", "extraction_confidence_score":50 + (20 if pd.notna(mw) else 0) + (10 if pd.notna(val) else 0), "duplicate_group_id":"", "raw_text_excerpt":text[:1200], "notes":"Recent candidate detected online; review before adding to master.", "last_updated":now_iso(), "candidate_reason":"recent online article"
    }

@st.cache_data(ttl="2h", show_spinner=False)
def fetch_recent_candidates(days_back=120, max_records=30):
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"
    start = (datetime.now(timezone.utc)-timedelta(days=days_back)).strftime("%Y%m%d%H%M%S")
    end = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rows = []
    for q in RECENT_QUERIES:
        query = f'({q}) (acquisition OR acquires OR acquired OR buys OR sells OR M&A OR merger OR compra OR adquiere OR vende OR cartera OR portfolio)'
        params = {"query":query, "mode":"ArtList", "format":"json", "maxrecords":max_records, "sort":"HybridRel", "startdatetime":start, "enddatetime":end}
        try:
            r = requests.get(endpoint, params=params, timeout=20)
            r.raise_for_status()
            for a in r.json().get("articles", []): rows.append(article_to_candidate(a))
        except Exception as e:
            st.session_state.setdefault("source_errors", []).append(str(e))
    df = pd.DataFrame(rows)
    if df.empty: return ensure_schema(df)
    df = ensure_schema(df).drop_duplicates("deal_id")
    signal = df["raw_text_excerpt"].astype(str).str.lower().str.contains("acqui|sell|sold|buy|merger|m&a|compra|adquiere|vende|portfolio|cartera")
    return df[signal]

def to_xlsx(df):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Deals")
    return out.getvalue()

def sidebar_filters(df):
    st.sidebar.header("Filtros")
    f = df.copy()
    years = sorted([int(x) for x in f["year"].dropna().unique()])
    if years:
        yr = st.sidebar.slider("Año", min(years), max(years), (min(years), max(years)), key="filter_year")
        f = f[f["year"].isna() | f["year"].between(yr[0], yr[1])]
    for col, label in [("deal_status","Estado"),("validation_status","Validación"),("technology","Tecnología"),("location_country","País"),("buyer","Comprador"),("seller","Vendedor"),("transaction_type","Tipo")]:
        vals = sorted([x for x in f[col].dropna().astype(str).unique() if x and x != "nan"])
        picked = st.sidebar.multiselect(label, vals, key=f"filter_{col}")
        if picked: f = f[f[col].astype(str).isin(picked)]
    scope = st.sidebar.radio("Ámbito", ["Todos", "España", "Compañía española fuera"], key="filter_scope")
    if scope == "España": f = f[f["deal_scope"].eq("Spain renewable asset/company")]
    elif scope == "Compañía española fuera": f = f[f["deal_scope"].eq("Spanish company abroad")]
    value = st.sidebar.radio("Importe", ["Todos", "Con importe", "Sin importe"], horizontal=True, key="filter_value")
    if value == "Con importe": f = f[f["disclosed_value_flag"]]
    elif value == "Sin importe": f = f[~f["disclosed_value_flag"]]
    return f

def kpis(df):
    val = df["deal_value_eur_m"].sum(min_count=1); mw = df["capacity_mw"].sum(min_count=1); mwh = df["storage_mwh"].sum(min_count=1)
    wavg = val/mw if pd.notna(val) and pd.notna(mw) and mw>0 else np.nan
    cols = st.columns(6)
    cols[0].metric("Deals", f"{len(df):,}")
    cols[1].metric("Valor divulgado", "n.d." if pd.isna(val) else f"€{val:,.1f}m")
    cols[2].metric("MW", "n.d." if pd.isna(mw) else f"{mw:,.1f}")
    cols[3].metric("MWh", "n.d." if pd.isna(mwh) else f"{mwh:,.1f}")
    cols[4].metric("€/MW ponderado", "n.d." if pd.isna(wavg) else f"€{wavg:,.2f}m/MW")
    cols[5].metric("% con valor", f"{df['disclosed_value_flag'].mean()*100:.1f}%" if len(df) else "n.d.")

def charts(df):
    c1,c2 = st.columns(2)
    with c1:
        annual = df.groupby("year", dropna=True).agg(deals=("deal_id","count"), value=("deal_value_eur_m","sum"), mw=("capacity_mw","sum")).reset_index()
        if not annual.empty:
            st.plotly_chart(px.bar(annual, x="year", y="deals", title="Número de deals por año"), use_container_width=True)
            st.plotly_chart(px.bar(annual, x="year", y="value", title="Valor divulgado por año (€m)"), use_container_width=True)
        tech = df.groupby("technology").size().reset_index(name="deals").sort_values("deals", ascending=False)
        st.plotly_chart(px.bar(tech, x="technology", y="deals", title="Deals por tecnología"), use_container_width=True)
    with c2:
        buyers = df["buyer"].replace("", np.nan).dropna().value_counts().head(10).rename_axis("buyer").reset_index(name="deals")
        sellers = df["seller"].replace("", np.nan).dropna().value_counts().head(10).rename_axis("seller").reset_index(name="deals")
        st.plotly_chart(px.bar(buyers, x="deals", y="buyer", orientation="h", title="Top compradores"), use_container_width=True)
        st.plotly_chart(px.bar(sellers, x="deals", y="seller", orientation="h", title="Top vendedores"), use_container_width=True)
        valid = df[df["price_per_mw_eur_m"].notna()]
        if not valid.empty:
            st.plotly_chart(px.box(valid, x="technology", y="price_per_mw_eur_m", title="€/MW por tecnología"), use_container_width=True)

def screener(df):
    show = ["deal_id","validation_status","announcement_date","asset_or_company_name","buyer","seller","technology","location_country","capacity_mw","storage_mwh","deal_value_eur_m","price_per_mw_eur_m","ownership_stake_acquired_pct","deal_status","source_url"]
    view = df[show].copy()
    if "selected_ids" not in st.session_state: st.session_state.selected_ids=[]
    view.insert(0, "select", view["deal_id"].astype(str).isin(st.session_state.selected_ids))
    edited = st.data_editor(view, hide_index=True, height=560, use_container_width=True, disabled=[c for c in view.columns if c!="select"], column_config={"source_url": st.column_config.LinkColumn("source_url")}, key="master_screener")
    st.session_state.selected_ids = edited.loc[edited["select"], "deal_id"].astype(str).tolist()
    st.caption(f"Seleccionadas: {len(st.session_state.selected_ids)}")

def detail(df):
    if df.empty: st.info("No hay operaciones."); return
    opts = df["deal_id"].astype(str).tolist()
    idx = 0
    if st.session_state.get("selected_ids") and st.session_state.selected_ids[0] in opts: idx = opts.index(st.session_state.selected_ids[0])
    did = st.selectbox("Selecciona deal", opts, index=idx, key="detail_select")
    r = df[df["deal_id"].astype(str).eq(did)].iloc[0]
    st.subheader(r["asset_or_company_name"])
    st.write(r["description"])
    c = st.columns(5)
    c[0].metric("Comprador", clean(r["buyer"]) or "n.d.")
    c[1].metric("Vendedor", clean(r["seller"]) or "n.d.")
    c[2].metric("MW", "n.d." if pd.isna(r["capacity_mw"]) else f"{r['capacity_mw']:,.1f}")
    c[3].metric("Importe", "n.d." if pd.isna(r["deal_value_eur_m"]) else f"€{r['deal_value_eur_m']:,.1f}m")
    c[4].metric("Stake", "n.d." if pd.isna(r["ownership_stake_acquired_pct"]) else f"{r['ownership_stake_acquired_pct']:,.1f}%")
    if clean(r["source_url"]): st.link_button("Abrir fuente", r["source_url"])
    st.json({k: str(r[k]) for k in ["deal_status","validation_status","transaction_type","target_type","technology","location_country","development_stage","source_quality_score","notes"]}, expanded=False)

def main():
    st.title(APP_TITLE)
    st.caption("Base maestra 2020-2026 precargada + módulo independiente para detectar candidatos recientes. No reconstruye el histórico en runtime.")

    master = normalize(load_csv(MASTER_FILE))
    recent_static = normalize(load_csv(RECENT_FILE))

    with st.sidebar:
        st.header("Actualización reciente")
        if st.button("Buscar candidatos recientes online", key="btn_recent"):
            with st.spinner("Consultando fuentes recientes..."):
                fetch_recent_candidates.clear()
                st.session_state["recent_live"] = normalize(fetch_recent_candidates())
                st.session_state["recent_live_time"] = now_iso()
        st.caption(f"Última búsqueda reciente: {st.session_state.get('recent_live_time','no ejecutada')}")

    recent_live = st.session_state.get("recent_live", pd.DataFrame(columns=COLUMNS))
    recent = normalize(pd.concat([recent_static, recent_live], ignore_index=True))
    filtered = sidebar_filters(master)

    st.info(f"Base maestra cargada: {len(master):,} transacciones/candidatos históricos | Candidatos recientes detectados: {len(recent):,}. Nota: la base incluida es un public seed; para exhaustividad completa debe sustituirse/enriquecerse con una base validada/licenciada.")

    tabs = st.tabs(["Executive Dashboard", "Historical Deal Screener", "Deal Detail", "Selected Transactions", "Valuation & Analytics", "Recent Candidates", "Data Quality", "Export"])
    with tabs[0]: kpis(filtered); charts(filtered)
    with tabs[1]: screener(filtered)
    with tabs[2]: detail(filtered)
    with tabs[3]:
        sel = filtered[filtered["deal_id"].astype(str).isin(st.session_state.get("selected_ids", []))]
        if sel.empty: st.info("Selecciona operaciones en Historical Deal Screener.")
        else: kpis(sel); st.dataframe(sel, use_container_width=True, hide_index=True)
    with tabs[4]: charts(filtered)
    with tabs[5]:
        st.subheader("Recent Candidates - pending review")
        if recent.empty: st.info("Pulsa 'Buscar candidatos recientes online' para traer candidatos recientes.")
        else: st.dataframe(recent[["deal_id","announcement_date","asset_or_company_name","technology","location_country","capacity_mw","deal_value_eur_m","source_domain","source_url","raw_text_excerpt"]], use_container_width=True, hide_index=True, column_config={"source_url": st.column_config.LinkColumn("source_url")})
    with tabs[6]:
        c=st.columns(4); c[0].metric("Sin importe", int(master["deal_value_eur_m"].isna().sum())); c[1].metric("Sin MW", int(master["capacity_mw"].isna().sum())); c[2].metric("Duplicados", int(master["suspected_duplicate_flag"].sum())); c[3].metric("Completitud media", f"{master['data_completion_pct'].mean():.1f}%")
        st.dataframe(master[["deal_id","asset_or_company_name","data_completion_pct","source_quality_score","suspected_duplicate_flag","source_url","notes"]], use_container_width=True, hide_index=True, column_config={"source_url": st.column_config.LinkColumn("source_url")})
    with tabs[7]:
        st.download_button("Descargar base maestra filtrada CSV", filtered.to_csv(index=False).encode("utf-8"), "filtered_master_deals.csv", "text/csv")
        st.download_button("Descargar base maestra completa Excel", to_xlsx(master), "deals_master_2020_2026.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.download_button("Descargar candidatos recientes CSV", recent.to_csv(index=False).encode("utf-8"), "recent_candidates.csv", "text/csv")
        selected = filtered[filtered["deal_id"].astype(str).isin(st.session_state.get("selected_ids", []))]
        st.download_button("Descargar seleccionadas Excel", to_xlsx(selected), "selected_transactions.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

if __name__ == "__main__":
    main()
