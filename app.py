
import io
import re
import hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus, urlparse

import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

st.set_page_config(page_title="Renewable M&A Deal Tracker v3", page_icon="⚡", layout="wide")

APP_TITLE = "M&A Renewable Deal Tracker v3 – Historical Database + Incremental Updates"
LOCAL_DB = "deals_database.csv"
REQUEST_TIMEOUT = 20
DEFAULT_START_YEAR = 2020
CURRENT_YEAR = datetime.now().year

COLUMNS = [
    "deal_id", "announcement_date", "year", "quarter", "deal_status", "validation_status",
    "transaction_type", "asset_or_company_name", "target_type", "buyer", "buyer_country", "buyer_type",
    "seller", "seller_country", "seller_type", "spanish_company_involved", "spanish_company_role",
    "description", "technology", "location_country", "location_region", "location_province", "location_city",
    "capacity_mw", "capacity_mwp", "storage_mwh", "number_of_assets", "development_stage",
    "regulated_or_merchant", "ppa_status", "grid_access_status", "environmental_permit_status",
    "deal_value_eur_m", "enterprise_value_eur_m", "equity_value_eur_m", "debt_assumed_eur_m",
    "price_per_mw_eur_m", "ownership_stake_acquired_pct", "implied_100pct_value_eur_m",
    "source_1", "source_2", "source_3", "source_quality_score", "source_type", "source_domain", "source_url",
    "article_title", "article_date", "ingestion_date", "last_seen_date", "extraction_method",
    "extraction_confidence_score", "duplicate_group_id", "raw_text_excerpt", "notes", "last_updated"
]
NUMERIC = ["year", "capacity_mw", "capacity_mwp", "storage_mwh", "number_of_assets", "deal_value_eur_m", "enterprise_value_eur_m", "equity_value_eur_m", "debt_assumed_eur_m", "price_per_mw_eur_m", "ownership_stake_acquired_pct", "implied_100pct_value_eur_m", "source_quality_score", "extraction_confidence_score"]

KEYWORDS = [
    "renewable acquisition Spain", "solar portfolio acquisition Spain", "wind portfolio sale Spain",
    "renewable portfolio sale Spain", "renewables M&A Spain", "M&A renovables España",
    "compra cartera renovable España", "vende cartera renovable España", "adquiere parques solares España",
    "Iberdrola renewable acquisition", "Acciona Energia renewable assets sale", "Repsol renewable portfolio sale",
    "Naturgy renewable acquisition", "EDPR renewable portfolio sale", "Solaria sale portfolio",
    "Sonnedix Spain acquisition", "Qualitas Energy acquisition Spain", "Masdar Spain renewable portfolio",
    "biomethane acquisition Spain", "biometano adquisición España", "battery storage acquisition Spain"
]

TRUSTED_DOMAINS = {
    "pv-magazine.es": 4, "pv-magazine.com": 4, "renewablesnow.com": 4,
    "elperiodicodelaenergia.com": 3, "energias-renovables.com": 3,
    "cnmv.es": 5, "iberdrola.com": 5, "acciona-energia.com": 5, "repsol.com": 5,
    "naturgy.com": 5, "edpr.com": 5, "solariaenergia.com": 5,
}

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

BUYER_TYPE_MAP = {
    "fund": "infrastructure fund", "capital": "private equity", "partners": "private equity",
    "pension": "pension fund", "masdar": "sovereign fund", "utility": "utility", "energy": "utility",
    "energía": "utility", "energia": "utility", "oil": "oil & gas",
}

@st.cache_data(ttl="12h", show_spinner=False)
def cached_historical_fetch(start_year, end_year, max_records_per_window):
    return fetch_historical_gdelt(start_year, end_year, max_records_per_window)

@st.cache_data(ttl="2h", show_spinner=False)
def cached_incremental_fetch(days_back, max_records_per_query):
    return fetch_recent_gdelt(days_back, max_records_per_query)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def clean_text(x):
    if pd.isna(x):
        return ""
    return re.sub(r"\s+", " ", str(x)).strip()

def safe_get(url, params=None):
    try:
        r = requests.get(url, params=params, headers={"User-Agent":"Mozilla/5.0 renewable-ma-tracker/3.0"}, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r
    except Exception as e:
        st.session_state.setdefault("source_errors", []).append(f"{url}: {e}")
        return None

def domain_from_url(url):
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""

def stable_id(*parts):
    raw = "|".join([str(p or "").strip().lower() for p in parts])
    return "AUTO-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12].upper()

def infer_technology(text):
    t = text.lower()
    hits = [tech for tech, pat in TECH_PATTERNS.items() if re.search(pat, t)]
    if len(hits) >= 2:
        return "hybrid"
    return hits[0] if hits else "other"

def infer_country(text):
    t = text.lower()
    if any(k in t for k in ["spain", "españa", "spanish", "ibérica", "iberia"]):
        return "Spain"
    if "portugal" in t or "portuguese" in t:
        return "Portugal"
    for c in ["Italy", "France", "Germany", "United Kingdom", "United States", "Mexico", "Brazil", "Chile", "Australia", "Poland", "Romania"]:
        if c.lower() in t:
            return c
    return ""

def infer_buyer_seller_target(text):
    patterns = [
        r"(?P<seller>[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÜÑáéíóúüñ&\.\- ]{2,80})\s+(?:sells|sold|vende|vendió|ha vendido)\s+(?P<target>.{3,140}?)(?:\s+to\s+|\s+a\s+)(?P<buyer>[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÜÑáéíóúüñ&\.\- ]{2,80})",
        r"(?P<buyer>[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÜÑáéíóúüñ&\.\- ]{2,80})\s+(?:acquires|acquired|buys|bought|adquiere|compró|compra|ha comprado)\s+(?P<target>.{3,140}?)(?:\s+from\s+|\s+de\s+)(?P<seller>[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÜÑáéíóúüñ&\.\- ]{2,80})",
        r"(?P<buyer>[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÜÑáéíóúüñ&\.\- ]{2,80})\s+(?:acquires|acquired|buys|adquiere|compra)\s+(?P<target>[A-ZÁÉÍÓÚÑ0-9][\wÁÉÍÓÚÜÑáéíóúüñ&\.\- ]{2,120})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            gd = m.groupdict()
            return clean_text(gd.get("buyer","")), clean_text(gd.get("seller","")), clean_text(gd.get("target",""))
    return "", "", ""

def extract_numbers(text):
    t = text.replace(",", ".")
    mw = val = stake = np.nan
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GW|gigawatts?)", t, re.I)
    if m:
        mw = float(m.group(1)) * 1000
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(MW|MWp|megawatts?)", t, re.I)
        if m:
            mw = float(m.group(1))
    m = re.search(r"(?:€|EUR|euros?)\s*(\d+(?:\.\d+)?)\s*(?:m|million|millones|mn|M|bn|billion|billones)?", t, re.I)
    if not m:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|million|millones|mn|M)\s*(?:€|EUR|euros?)", t, re.I)
    if m:
        val = float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", t)
    if m:
        stake = float(m.group(1))
    return mw, val, stake

def classify_transaction(text):
    t = text.lower()
    if "joint venture" in t or " jv " in t: return "JV"
    if "minority" in t or "minoritaria" in t: return "minority stake"
    if "majority" in t or "mayoritaria" in t: return "majority stake"
    if "platform" in t or "plataforma" in t: return "platform acquisition"
    if "portfolio" in t or "cartera" in t: return "portfolio sale"
    if "pipeline" in t or "development" in t: return "development pipeline"
    if "merger" in t or "fusión" in t or "fusion" in t: return "merger"
    return "asset deal"

def infer_buyer_type(buyer):
    b = buyer.lower()
    for k, v in BUYER_TYPE_MAP.items():
        if k in b: return v
    return "other" if buyer else ""

def parse_article(article, source_type):
    title = clean_text(article.get("title"))
    desc = clean_text(article.get("description") or article.get("snippet") or "")
    url = clean_text(article.get("url"))
    published = clean_text(article.get("publishedAt") or article.get("seendate") or article.get("date") or "")
    text = f"{title}. {desc}"
    buyer, seller, target = infer_buyer_seller_target(text)
    mw, val, stake = extract_numbers(text)
    domain = domain_from_url(url)
    adate = pd.to_datetime(published, errors="coerce", utc=True)
    adate_str = adate.date().isoformat() if pd.notna(adate) else ""
    if not adate_str:
        # Try to recover year from text/title as fallback
        ym = re.search(r"\b(20\d{2})\b", text)
        adate_str = f"{ym.group(1)}-01-01" if ym else ""
    confidence = 25
    confidence += 20 if buyer or seller else 0
    confidence += 20 if pd.notna(mw) else 0
    confidence += 10 if pd.notna(val) else 0
    confidence += 10 if domain in TRUSTED_DOMAINS else 0
    confidence += 15 if re.search(r"acquir|buy|sell|merger|m&a|compra|adquiere|vende|cartera|portfolio", text, re.I) else 0
    confidence = min(confidence, 95)
    spanish = "yes" if re.search(r"spain|españa|spanish|iberdrola|acciona|repsol|naturgy|edpr|solaria|qualitas", text, re.I) else "unknown"
    country = infer_country(text)
    return {
        "deal_id": stable_id(url, title),
        "announcement_date": adate_str,
        "year": pd.to_datetime(adate_str, errors="coerce").year if adate_str else np.nan,
        "quarter": f"Q{pd.to_datetime(adate_str, errors='coerce').quarter}" if adate_str else "",
        "deal_status": "announced",
        "validation_status": "pending_review",
        "transaction_type": classify_transaction(text),
        "asset_or_company_name": target[:120] if target else title[:120],
        "target_type": "portfolio" if re.search(r"portfolio|cartera", text, re.I) else "asset/company",
        "buyer": buyer,
        "buyer_country": "",
        "buyer_type": infer_buyer_type(buyer),
        "seller": seller,
        "seller_country": "",
        "seller_type": "",
        "spanish_company_involved": spanish,
        "spanish_company_role": "unknown",
        "description": text[:600],
        "technology": infer_technology(text),
        "location_country": country,
        "location_region": "", "location_province": "", "location_city": "",
        "capacity_mw": mw, "capacity_mwp": np.nan, "storage_mwh": np.nan, "number_of_assets": np.nan,
        "development_stage": "unknown", "regulated_or_merchant": "unknown", "ppa_status": "unknown",
        "grid_access_status": "unknown", "environmental_permit_status": "unknown",
        "deal_value_eur_m": val, "enterprise_value_eur_m": val, "equity_value_eur_m": np.nan, "debt_assumed_eur_m": np.nan,
        "price_per_mw_eur_m": val / mw if pd.notna(val) and pd.notna(mw) and mw > 0 else np.nan,
        "ownership_stake_acquired_pct": stake,
        "implied_100pct_value_eur_m": val/(stake/100) if pd.notna(val) and pd.notna(stake) and stake > 0 else np.nan,
        "source_1": url, "source_2": "", "source_3": "",
        "source_quality_score": TRUSTED_DOMAINS.get(domain, 2),
        "source_type": source_type, "source_domain": domain, "source_url": url,
        "article_title": title, "article_date": adate_str,
        "ingestion_date": now_iso(), "last_seen_date": now_iso(),
        "extraction_method": "historical_gdelt_regex_v3",
        "extraction_confidence_score": confidence,
        "duplicate_group_id": "",
        "raw_text_excerpt": text[:1200],
        "notes": "auto-detected historical/open-source candidate; requires manual validation",
        "last_updated": now_iso(),
    }

def gdelt_query(query, start_dt, end_dt, max_records):
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max_records,
        "sort": "HybridRel",
        "startdatetime": start_dt,
        "enddatetime": end_dt,
    }
    r = safe_get(endpoint, params=params)
    if not r:
        return []
    try:
        return r.json().get("articles", [])
    except Exception:
        return []

def build_gdelt_query(keyword):
    return f'({keyword}) (acquires OR acquired OR acquisition OR buys OR bought OR sells OR sold OR compra OR adquiere OR vende OR M&A OR merger OR portfolio OR cartera)'

def fetch_historical_gdelt(start_year, end_year, max_records_per_window=35):
    rows = []
    for year in range(int(start_year), int(end_year) + 1):
        # Windows trimestrales para recuperar histórico sin saturar.
        windows = [(1,3), (4,6), (7,9), (10,12)]
        for m1, m2 in windows:
            start_dt = f"{year}{m1:02d}01000000"
            end_day = "31" if m2 in [3,12] else "30"
            end_dt = f"{year}{m2:02d}{end_day}235959"
            for kw in KEYWORDS:
                arts = gdelt_query(build_gdelt_query(kw), start_dt, end_dt, max_records_per_window)
                rows.extend([parse_article(a, "GDELT historical") for a in arts])
    return pd.DataFrame(rows)

def fetch_recent_gdelt(days_back=60, max_records_per_query=50):
    start = (datetime.now(timezone.utc) - timedelta(days=int(days_back))).strftime("%Y%m%d%H%M%S")
    end = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rows = []
    for kw in KEYWORDS:
        arts = gdelt_query(build_gdelt_query(kw), start, end, max_records_per_query)
        rows.extend([parse_article(a, "GDELT incremental") for a in arts])
    return pd.DataFrame(rows)

def fetch_pv_magazine_index():
    rows = []
    if BeautifulSoup is None:
        return pd.DataFrame(rows)
    queries = ["M&A renovables España", "listado nuevas M&A renovables España", "compra cartera renovable", "vende cartera renovable"]
    for q in queries:
        r = safe_get(f"https://www.pv-magazine.es/?s={quote_plus(q)}")
        if not r: continue
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a", href=True):
            title = clean_text(a.get_text(" "))
            href = a["href"]
            if len(title) > 20 and "pv-magazine.es" in href and re.search(r"M&A|renovable|cartera|adquiere|compra|vende", title, re.I):
                rows.append(parse_article({"title": title, "description": title, "url": href, "publishedAt":""}, "pv magazine index"))
    return pd.DataFrame(rows)

def ensure_schema(df):
    if df is None or df.empty:
        df = pd.DataFrame(columns=COLUMNS)
    for c in COLUMNS:
        if c not in df.columns: df[c] = np.nan
    return df[COLUMNS + [c for c in df.columns if c not in COLUMNS]]

def read_local_db():
    try: return pd.read_csv(LOCAL_DB)
    except Exception: return pd.DataFrame(columns=COLUMNS)

def normalize(df):
    df = ensure_schema(df).copy()
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["announcement_date", "article_date", "ingestion_date", "last_seen_date", "last_updated"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    if df.empty:
        df["disclosed_value_flag"] = False; df["disclosed_capacity_flag"] = False; df["deal_scope"] = "Global / unknown"; df["suspected_duplicate_flag"] = False; df["data_completion_pct"] = np.nan
        return df
    missing_year = df["year"].isna() & df["announcement_date"].notna()
    df.loc[missing_year, "year"] = df.loc[missing_year, "announcement_date"].dt.year
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    ev = df["deal_value_eur_m"].combine_first(df["enterprise_value_eur_m"]).combine_first(df["equity_value_eur_m"])
    mw = df["capacity_mw"].combine_first(df["capacity_mwp"])
    df["disclosed_value_flag"] = ev.notna(); df["disclosed_capacity_flag"] = mw.notna()
    df["price_per_mw_eur_m"] = df["price_per_mw_eur_m"].combine_first(pd.Series(np.where((ev.notna()) & (mw > 0), ev/mw, np.nan), index=df.index))
    key = df[["asset_or_company_name", "buyer", "seller"]].fillna("").astype(str).agg("|".join, axis=1).str.lower()
    df["suspected_duplicate_flag"] = key.duplicated(keep=False)
    df["data_completion_pct"] = df[["deal_id", "announcement_date", "buyer", "seller", "asset_or_company_name", "technology", "location_country", "capacity_mw", "deal_value_eur_m", "source_1"]].notna().mean(axis=1)*100
    loc = df["location_country"].fillna("").astype(str).str.lower(); sp = df["spanish_company_involved"].fillna("").astype(str).str.lower()
    df["deal_scope"] = np.select([loc.eq("spain"), sp.eq("yes") & ~loc.eq("spain")], ["Spain renewable asset/company", "Spanish company abroad"], default="Global / unknown")
    return df

def dedupe_merge(*frames):
    combined = pd.concat([ensure_schema(f) for f in frames if f is not None], ignore_index=True)
    if combined.empty: return normalize(combined)
    combined = ensure_schema(combined)
    signal = combined["raw_text_excerpt"].fillna("").astype(str).str.lower().str.contains("acquir|acquisition|buy|sell|sold|merger|m&a|compra|adquiere|vende|cartera|portfolio|farm-down|stake", regex=True)
    combined = combined[signal | combined["source_quality_score"].fillna(0).ge(4) | combined["validation_status"].eq("validated")]
    combined["_rank"] = combined["validation_status"].map({"validated":0,"pending_review":1}).fillna(2)
    combined = combined.sort_values(["deal_id", "_rank"]).drop_duplicates("deal_id", keep="first").drop(columns="_rank")
    return normalize(combined)

def sidebar_filters(df):
    st.sidebar.header("Base histórica + actualización")
    start_year = st.sidebar.number_input("Año inicial histórico", min_value=2010, max_value=CURRENT_YEAR, value=DEFAULT_START_YEAR, step=1)
    end_year = st.sidebar.number_input("Año final histórico", min_value=int(start_year), max_value=CURRENT_YEAR, value=CURRENT_YEAR, step=1)
    max_rec = st.sidebar.slider("Profundidad histórica por ventana", 10, 100, 25, help="Más alto = más cobertura, pero más lento.")
    run_backfill = st.sidebar.button("Construir/actualizar histórico desde fuentes abiertas")
    refresh_recent = st.sidebar.button("Actualizar últimos 90 días")
    st.sidebar.divider()
    st.sidebar.header("Filtros")
    min_conf = st.sidebar.slider("Confianza mínima", 0, 100, 0)
    f = df[(df["extraction_confidence_score"].isna()) | (df["extraction_confidence_score"] >= min_conf)].copy()
    for col, label in [("year","Año"),("validation_status","Validación"),("technology","Tecnología"),("location_country","País"),("source_domain","Fuente"),("buyer","Comprador"),("seller","Vendedor")]:
        vals = sorted([x for x in f[col].dropna().astype(str).unique() if x])
        pick = st.sidebar.multiselect(label, vals)
        if pick: f = f[f[col].astype(str).isin(pick)]
    only_spain = st.sidebar.checkbox("Solo España / compañía española", value=True)
    if only_spain:
        f = f[(f["location_country"].fillna("").astype(str).str.lower().eq("spain")) | (f["spanish_company_involved"].fillna("").astype(str).str.lower().eq("yes"))]
    return f, run_backfill, refresh_recent, int(start_year), int(end_year), int(max_rec)

def kpis(df):
    val = df["deal_value_eur_m"].sum(min_count=1); mw = df["capacity_mw"].sum(min_count=1); wavg = val/mw if pd.notna(val) and pd.notna(mw) and mw>0 else np.nan
    cols = st.columns(6)
    cols[0].metric("Deals", f"{len(df):,}")
    cols[1].metric("Desde", int(df["year"].min()) if df["year"].notna().any() else "n.d.")
    cols[2].metric("Hasta", int(df["year"].max()) if df["year"].notna().any() else "n.d.")
    cols[3].metric("Valor divulgado", "n.d." if pd.isna(val) else f"€{val:,.1f}m")
    cols[4].metric("MW", "n.d." if pd.isna(mw) else f"{mw:,.1f} MW")
    cols[5].metric("€/MW", "n.d." if pd.isna(wavg) else f"€{wavg:,.2f}m/MW")

def screener(df):
    cols = ["deal_id","select","validation_status","extraction_confidence_score","announcement_date","asset_or_company_name","buyer","seller","technology","location_country","capacity_mw","deal_value_eur_m","price_per_mw_eur_m","source_domain","source_url"]
    view = df[[c for c in cols if c != "select"]].copy()
    if "selected_ids" not in st.session_state: st.session_state.selected_ids=[]
    view.insert(1, "select", view["deal_id"].astype(str).isin(st.session_state.selected_ids))
    edited = st.data_editor(view, height=560, hide_index=True, use_container_width=True, disabled=[c for c in view.columns if c!="select"], column_config={"source_url": st.column_config.LinkColumn("source_url")})
    st.session_state.selected_ids = edited.loc[edited["select"], "deal_id"].astype(str).tolist()
    st.caption(f"Seleccionadas: {len(st.session_state.selected_ids)}")

def charts(df):
    c1,c2 = st.columns(2)
    with c1:
        if df["year"].notna().any():
            annual = df.groupby("year").agg(deals=("deal_id","count"), value=("deal_value_eur_m","sum"), mw=("capacity_mw","sum")).reset_index()
            st.plotly_chart(px.bar(annual,x="year",y="deals",title="Deals históricos por año"),use_container_width=True)
            st.plotly_chart(px.bar(annual,x="year",y="value",title="Valor divulgado por año EURm"),use_container_width=True)
    with c2:
        tech = df.groupby("technology").size().reset_index(name="deals").sort_values("deals",ascending=False)
        st.plotly_chart(px.bar(tech,x="technology",y="deals",title="Deals por tecnología"),use_container_width=True)
        src = df.groupby("source_domain").size().reset_index(name="deals").sort_values("deals",ascending=False).head(15)
        st.plotly_chart(px.bar(src,x="deals",y="source_domain",orientation="h",title="Fuentes"),use_container_width=True)
    if df["price_per_mw_eur_m"].notna().any():
        st.plotly_chart(px.box(df[df["price_per_mw_eur_m"].notna()],x="technology",y="price_per_mw_eur_m",title="Benchmark €/MW por tecnología"),use_container_width=True)

def detail(df):
    if df.empty: st.info("No hay operaciones con los filtros actuales."); return
    opts = df["deal_id"].astype(str).tolist(); default=0
    if st.session_state.get("selected_ids") and st.session_state.selected_ids[0] in opts: default=opts.index(st.session_state.selected_ids[0])
    did = st.selectbox("Deal", opts, index=default)
    r = df[df["deal_id"].astype(str).eq(did)].iloc[0]
    st.subheader(r["asset_or_company_name"])
    st.write(r["description"])
    c=st.columns(5)
    c[0].metric("Buyer", clean_text(r["buyer"]) or "n.d."); c[1].metric("Seller", clean_text(r["seller"]) or "n.d.")
    c[2].metric("MW", "n.d." if pd.isna(r["capacity_mw"]) else f"{r['capacity_mw']:,.1f}")
    c[3].metric("Value", "n.d." if pd.isna(r["deal_value_eur_m"]) else f"€{r['deal_value_eur_m']:,.1f}m")
    c[4].metric("Confidence", "n.d." if pd.isna(r["extraction_confidence_score"]) else f"{r['extraction_confidence_score']:.0f}%")
    if clean_text(r["source_url"]): st.link_button("Abrir fuente", r["source_url"])
    st.json({k:str(r[k]) for k in ["validation_status","transaction_type","technology","location_country","ownership_stake_acquired_pct","source_domain","article_title","raw_text_excerpt","notes"]}, expanded=False)

def export_buttons(full, filtered):
    def to_xlsx(df):
        out=io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as w: df.to_excel(w,index=False,sheet_name="Deals")
        return out.getvalue()
    st.download_button("Descargar base completa CSV", full.to_csv(index=False).encode("utf-8"), "deals_database_v3.csv", "text/csv")
    st.download_button("Descargar filtrado Excel", to_xlsx(filtered), "filtered_deals_v3.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    sel = filtered[filtered["deal_id"].astype(str).isin(st.session_state.get("selected_ids",[]))]
    st.download_button("Descargar seleccionadas Excel", to_xlsx(sel), "selected_deals_v3.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

def main():
    st.title(APP_TITLE)
    st.caption("Combina una base histórica desde 2020 con actualizaciones incrementales al abrir/refrescar la app. Todos los candidatos online quedan como pending_review hasta validación manual.")
    local = read_local_db()
    if "recent_df" not in st.session_state:
        with st.spinner("Actualizando últimos 90 días..."):
            st.session_state.recent_df = cached_incremental_fetch(90, 50)
            st.session_state.last_recent = now_iso()
    if "historical_df" not in st.session_state:
        st.session_state.historical_df = pd.DataFrame(columns=COLUMNS)
    full_pre = dedupe_merge(local, st.session_state.historical_df, st.session_state.recent_df)
    filtered_pre, run_backfill, refresh_recent, start_year, end_year, max_rec = sidebar_filters(full_pre)
    if refresh_recent:
        with st.spinner("Consultando fuentes online recientes..."):
            cached_incremental_fetch.clear()
            st.session_state.recent_df = cached_incremental_fetch(90, 50)
            st.session_state.last_recent = now_iso()
    if run_backfill:
        with st.spinner(f"Construyendo histórico {start_year}-{end_year}. Puede tardar varios minutos la primera vez..."):
            st.session_state.historical_df = cached_historical_fetch(start_year, end_year, max_rec)
            pv = fetch_pv_magazine_index()
            st.session_state.historical_df = dedupe_merge(st.session_state.historical_df, pv)
            st.session_state.last_backfill = now_iso()
    full = dedupe_merge(local, st.session_state.historical_df, st.session_state.recent_df)
    filtered, _, _, _, _, _ = sidebar_filters(full)
    st.info(f"Base combinada: {len(full):,} candidatos | Filtrados: {len(filtered):,} | Última actualización reciente: {st.session_state.get('last_recent','n.d.')} | Último backfill: {st.session_state.get('last_backfill','no ejecutado en esta sesión')}")
    tabs=st.tabs(["Dashboard", "Deal Screener", "Deal Detail", "Comparables seleccionados", "Analytics", "Data Quality", "Export"])
    with tabs[0]: kpis(filtered); charts(filtered)
    with tabs[1]: screener(filtered)
    with tabs[2]: detail(filtered)
    with tabs[3]:
        sel=filtered[filtered["deal_id"].astype(str).isin(st.session_state.get("selected_ids",[]))]
        st.dataframe(sel,use_container_width=True,hide_index=True); kpis(sel) if not sel.empty else st.info("Selecciona operaciones en Deal Screener.")
    with tabs[4]: charts(filtered)
    with tabs[5]:
        st.metric("Pendientes revisión", int((filtered["validation_status"]=="pending_review").sum()))
        st.metric("Posibles duplicados", int(filtered["suspected_duplicate_flag"].sum()))
        st.dataframe(filtered[["deal_id","asset_or_company_name","data_completion_pct","extraction_confidence_score","source_quality_score","suspected_duplicate_flag","source_url"]], use_container_width=True, hide_index=True, column_config={"source_url": st.column_config.LinkColumn("source_url")})
    with tabs[6]: export_buttons(full, filtered); st.write(st.session_state.get("source_errors",[])[:25])

if __name__ == "__main__":
    main()
