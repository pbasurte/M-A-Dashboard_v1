
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

st.set_page_config(page_title="M&A Renewable Deal Tracker v2", page_icon="⚡", layout="wide")

APP_TITLE = "M&A Renewable Deal Tracker v2 – Auto-fed Open Sources"
LOCAL_DB = "deals_database.csv"
REQUEST_TIMEOUT = 15

REQUIRED_COLUMNS = [
    "deal_id", "announcement_date", "closing_date", "year", "quarter", "deal_status",
    "transaction_type", "asset_or_company_name", "target_type", "buyer", "buyer_country", "buyer_type",
    "seller", "seller_country", "seller_type", "spanish_company_involved", "spanish_company_role",
    "description", "technology", "location_country", "location_region", "location_province", "location_city",
    "latitude", "longitude", "capacity_mw", "capacity_mwp", "storage_mwh", "number_of_assets",
    "development_stage", "cod_date", "regulated_or_merchant", "ppa_status", "ppa_counterparty",
    "remuneration_scheme", "grid_access_status", "environmental_permit_status", "deal_value_eur_m",
    "enterprise_value_eur_m", "equity_value_eur_m", "debt_assumed_eur_m", "price_per_mw_eur_m",
    "price_per_mwp_eur_m", "ownership_stake_acquired_pct", "implied_100pct_value_eur_m", "ev_ebitda",
    "revenue_eur_m", "ebitda_eur_m", "net_debt_eur_m", "advisors_buyer", "advisors_seller",
    "legal_advisor_buyer", "legal_advisor_seller", "financial_advisor_buyer", "financial_advisor_seller",
    "source_1", "source_2", "source_3", "source_quality_score", "notes", "last_updated",
    # v2 ingestion fields
    "source_type", "source_domain", "source_url", "article_title", "article_date", "ingestion_date",
    "extraction_method", "extraction_confidence_score", "validation_status", "duplicate_group_id",
    "raw_text_excerpt"
]

NUMERIC_COLUMNS = [
    "year", "latitude", "longitude", "capacity_mw", "capacity_mwp", "storage_mwh", "number_of_assets",
    "deal_value_eur_m", "enterprise_value_eur_m", "equity_value_eur_m", "debt_assumed_eur_m",
    "price_per_mw_eur_m", "price_per_mwp_eur_m", "ownership_stake_acquired_pct", "implied_100pct_value_eur_m",
    "ev_ebitda", "revenue_eur_m", "ebitda_eur_m", "net_debt_eur_m", "source_quality_score",
    "extraction_confidence_score"
]

KEYWORDS = [
    'renewable acquisition Spain', 'solar portfolio acquisition Spain', 'wind portfolio sale Spain',
    'renovables compra cartera España', 'M&A renovables España', 'biometano adquisición España',
    'Iberdrola acquires renewable assets', 'Acciona Energía sale renewable assets', 'Repsol renewable portfolio sale',
    'Naturgy renewable acquisition', 'EDPR sells renewable portfolio', 'Sonnedix Spain acquisition',
    'Qualitas Energy renewable acquisition Spain', 'Masdar Spain renewable portfolio',
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

BUYER_TYPES = {
    "fund": "infrastructure fund", "capital": "private equity", "partners": "private equity", "pension": "pension fund",
    "utility": "utility", "energy": "utility", "energía": "utility", "energia": "utility", "oil": "oil & gas",
}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_get(url, params=None, headers=None):
    headers = headers or {"User-Agent": "Mozilla/5.0 renewable-ma-tracker/2.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r
    except Exception as e:
        st.session_state.setdefault("source_errors", []).append(f"{url}: {e}")
        return None


def domain_from_url(url):
    try:
        d = urlparse(url).netloc.lower().replace("www.", "")
        return d
    except Exception:
        return ""


def stable_id(*parts):
    raw = "|".join([str(p or "").strip().lower() for p in parts])
    return "AUTO-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12].upper()


def clean_text(x):
    if pd.isna(x):
        return ""
    return re.sub(r"\s+", " ", str(x)).strip()


def infer_technology(text):
    t = text.lower()
    hits = [tech for tech, pat in TECH_PATTERNS.items() if re.search(pat, t)]
    if len(hits) >= 2:
        return "hybrid"
    return hits[0] if hits else "other"


def infer_country_region(text):
    t = text.lower()
    if any(k in t for k in ["spain", "españa", "península ibérica", "iberia", "spanish"]):
        return "Spain"
    if "portugal" in t or "portuguese" in t:
        return "Portugal"
    for country in ["Italy", "France", "Germany", "United Kingdom", "United States", "Mexico", "Brazil", "Chile", "Australia"]:
        if country.lower() in t:
            return country
    return ""


def infer_buyer_seller(text):
    # Heurística simple; deja pending_review para validación manual.
    patterns = [
        r"(?P<buyer>[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÜÑáéíóúüñ&\.\- ]{2,80})\s+(?:acquires|buys|purchases|takes over|adquiere|compra)\s+(?:a |an |the |una |un |el |la )?(?P<target>[A-ZÁÉÍÓÚÑ0-9][\wÁÉÍÓÚÜÑáéíóúüñ&\.\- ]{2,100})",
        r"(?P<seller>[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÜÑáéíóúüñ&\.\- ]{2,80})\s+(?:sells|vende)\s+(?:a |an |the |una |un |el |la )?(?P<target>[A-ZÁÉÍÓÚÑ0-9][\wÁÉÍÓÚÜÑáéíóúüñ&\.\- ]{2,100})\s+(?:to|a)\s+(?P<buyer>[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÜÑáéíóúüñ&\.\- ]{2,80})",
        r"(?P<buyer>[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÜÑáéíóúüñ&\.\- ]{2,80})\s+(?:entra en|invests in|invierte en)\s+(?P<target>[A-ZÁÉÍÓÚÑ0-9][\wÁÉÍÓÚÜÑáéíóúüñ&\.\- ]{2,100})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return clean_text(m.groupdict().get("buyer", "")), clean_text(m.groupdict().get("seller", "")), clean_text(m.groupdict().get("target", ""))
    return "", "", ""


def extract_numbers(text):
    t = text.replace(",", ".")
    mw = np.nan
    val = np.nan
    stake = np.nan
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:GW|gigawatts?)", t, re.I)
    if m:
        mw = float(m.group(1)) * 1000
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:MW|MWp|megawatts?)", t, re.I)
        if m:
            mw = float(m.group(1))
    m = re.search(r"(?:€|EUR|euros?)\s*(\d+(?:\.\d+)?)\s*(?:m|million|millones|mn|M)\b", t, re.I)
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
    if "joint venture" in t or " jv " in t:
        return "JV"
    if "minority" in t or "minoritaria" in t:
        return "minority stake"
    if "majority" in t or "mayoritaria" in t:
        return "majority stake"
    if "platform" in t or "plataforma" in t:
        return "platform acquisition"
    if "portfolio" in t or "cartera" in t:
        return "portfolio sale"
    if "pipeline" in t:
        return "development pipeline"
    if "merger" in t or "fusion" in t or "fusión" in t:
        return "merger"
    return "asset deal"


def infer_buyer_type(buyer):
    b = buyer.lower()
    for k, v in BUYER_TYPES.items():
        if k in b:
            return v
    return "other" if buyer else ""


def article_to_deal(article, source_type):
    title = clean_text(article.get("title"))
    desc = clean_text(article.get("description") or article.get("seendate") or "")
    url = clean_text(article.get("url"))
    published = clean_text(article.get("publishedAt") or article.get("seendate") or article.get("datetime") or "")
    text = f"{title}. {desc}"
    buyer, seller, target = infer_buyer_seller(text)
    mw, val, stake = extract_numbers(text)
    domain = domain_from_url(url)
    qscore = TRUSTED_DOMAINS.get(domain, 2)
    confidence = 30
    confidence += 20 if buyer or seller else 0
    confidence += 20 if not pd.isna(mw) else 0
    confidence += 10 if not pd.isna(val) else 0
    confidence += 10 if domain in TRUSTED_DOMAINS else 0
    confidence += 10 if any(w in text.lower() for w in ["acquires", "buys", "sells", "adquiere", "compra", "vende", "m&a", "merger", "acquisition"]) else 0
    confidence = min(confidence, 95)

    try:
        adate = pd.to_datetime(published, errors="coerce", utc=True)
        adate_str = adate.date().isoformat() if pd.notna(adate) else ""
    except Exception:
        adate_str = ""

    fallback_target = title[:90] if title else "Auto-detected renewable M&A candidate"
    country = infer_country_region(text)
    spanish = "yes" if any(x in text.lower() for x in ["spain", "españa", "spanish", "iberdrola", "acciona", "repsol", "naturgy", "edpr", "solaria"]) else "unknown"

    return {
        "deal_id": stable_id(url, title),
        "announcement_date": adate_str,
        "closing_date": "",
        "year": pd.to_datetime(adate_str, errors="coerce").year if adate_str else np.nan,
        "quarter": f"Q{pd.to_datetime(adate_str, errors='coerce').quarter}" if adate_str else "",
        "deal_status": "announced",
        "transaction_type": classify_transaction(text),
        "asset_or_company_name": target or fallback_target,
        "target_type": "portfolio" if "portfolio" in text.lower() or "cartera" in text.lower() else "asset/company",
        "buyer": buyer,
        "buyer_country": "",
        "buyer_type": infer_buyer_type(buyer),
        "seller": seller,
        "seller_country": "",
        "seller_type": "",
        "spanish_company_involved": spanish,
        "spanish_company_role": "unknown",
        "description": text[:500],
        "technology": infer_technology(text),
        "location_country": country,
        "location_region": "",
        "location_province": "",
        "location_city": "",
        "latitude": np.nan,
        "longitude": np.nan,
        "capacity_mw": mw,
        "capacity_mwp": np.nan,
        "storage_mwh": np.nan,
        "number_of_assets": np.nan,
        "development_stage": "unknown",
        "cod_date": "",
        "regulated_or_merchant": "unknown",
        "ppa_status": "unknown",
        "ppa_counterparty": "",
        "remuneration_scheme": "",
        "grid_access_status": "unknown",
        "environmental_permit_status": "unknown",
        "deal_value_eur_m": val,
        "enterprise_value_eur_m": val,
        "equity_value_eur_m": np.nan,
        "debt_assumed_eur_m": np.nan,
        "price_per_mw_eur_m": val / mw if pd.notna(val) and pd.notna(mw) and mw > 0 else np.nan,
        "price_per_mwp_eur_m": np.nan,
        "ownership_stake_acquired_pct": stake,
        "implied_100pct_value_eur_m": val / (stake/100) if pd.notna(val) and pd.notna(stake) and stake > 0 else np.nan,
        "ev_ebitda": np.nan,
        "revenue_eur_m": np.nan,
        "ebitda_eur_m": np.nan,
        "net_debt_eur_m": np.nan,
        "advisors_buyer": "",
        "advisors_seller": "",
        "legal_advisor_buyer": "",
        "legal_advisor_seller": "",
        "financial_advisor_buyer": "",
        "financial_advisor_seller": "",
        "source_1": url,
        "source_2": "",
        "source_3": "",
        "source_quality_score": qscore,
        "notes": "auto-detected from open online source; requires manual validation",
        "last_updated": now_iso(),
        "source_type": source_type,
        "source_domain": domain,
        "source_url": url,
        "article_title": title,
        "article_date": adate_str,
        "ingestion_date": now_iso(),
        "extraction_method": "regex_heuristic_v2",
        "extraction_confidence_score": confidence,
        "validation_status": "pending_review",
        "duplicate_group_id": "",
        "raw_text_excerpt": text[:1000]
    }


def fetch_gdelt(max_records_per_query=25, days_back=90):
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"
    rows = []
    start = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y%m%d%H%M%S")
    for q in KEYWORDS:
        query = f'({q}) (acquires OR acquisition OR buys OR sells OR compra OR adquiere OR vende OR M&A OR merger) sourcelang:English OR sourcelang:Spanish'
        params = {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": max_records_per_query,
            "sort": "HybridRel",
            "startdatetime": start,
        }
        r = safe_get(endpoint, params=params)
        if not r:
            continue
        try:
            data = r.json()
            for a in data.get("articles", []):
                rows.append(article_to_deal(a, "GDELT"))
        except Exception as e:
            st.session_state.setdefault("source_errors", []).append(f"GDELT parse error: {e}")
    return rows


def fetch_newsapi(api_key, max_records=50):
    if not api_key:
        return []
    url = "https://newsapi.org/v2/everything"
    q = '(renewable OR solar OR wind OR battery OR biomethane) AND (acquires OR acquisition OR sells OR buys OR merger OR M&A) AND (Spain OR Spanish OR Iberdrola OR Acciona OR Repsol OR Naturgy OR EDPR)'
    params = {"q": q, "language": "en", "sortBy": "publishedAt", "pageSize": max_records, "apiKey": api_key}
    r = safe_get(url, params=params)
    if not r:
        return []
    try:
        return [article_to_deal(a, "NewsAPI") for a in r.json().get("articles", [])]
    except Exception as e:
        st.session_state.setdefault("source_errors", []).append(f"NewsAPI parse error: {e}")
        return []


def fetch_gnews(api_key, max_records=50):
    if not api_key:
        return []
    url = "https://gnews.io/api/v4/search"
    q = '(renewable acquisition Spain) OR (solar portfolio Spain acquisition) OR (wind portfolio sale Spain)'
    params = {"q": q, "lang": "en", "max": max_records, "apikey": api_key}
    r = safe_get(url, params=params)
    if not r:
        return []
    try:
        articles = []
        for a in r.json().get("articles", []):
            articles.append({"title": a.get("title"), "description": a.get("description"), "url": a.get("url"), "publishedAt": a.get("publishedAt")})
        return [article_to_deal(a, "GNews") for a in articles]
    except Exception as e:
        st.session_state.setdefault("source_errors", []).append(f"GNews parse error: {e}")
        return []


def fetch_pv_magazine_search(max_pages=2):
    # Scraping ligero de páginas públicas de búsqueda. Si el sitio cambia, la app simplemente degradará a GDELT/NewsAPI.
    rows = []
    if BeautifulSoup is None:
        return rows
    queries = ["M&A renovables España", "adquiere cartera renovable", "vende cartera renovable", "compra parques solares"]
    for q in queries:
        url = f"https://www.pv-magazine.es/?s={quote_plus(q)}"
        r = safe_get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for item in soup.find_all(["article", "div"], limit=80):
            a = item.find("a", href=True)
            if not a:
                continue
            title = clean_text(a.get_text(" "))
            href = a["href"]
            if not title or "pv-magazine" not in href:
                continue
            desc = clean_text(item.get_text(" "))[:500]
            rows.append(article_to_deal({"title": title, "description": desc, "url": href, "publishedAt": ""}, "pv_magazine_search"))
    return rows


def ensure_schema(df):
    df = df.copy()
    for c in REQUIRED_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    return df[REQUIRED_COLUMNS + [c for c in df.columns if c not in REQUIRED_COLUMNS]]


def convert_types(df):
    df = ensure_schema(df)
    for c in NUMERIC_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["announcement_date", "closing_date", "cod_date", "last_updated", "article_date", "ingestion_date"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def enrich_calculated(df):
    df = convert_types(df)
    # Crear columnas calculadas incluso si no hay datos, para que la UI no falle.
    for calc_col, default in {
        "disclosed_value_flag": False,
        "disclosed_capacity_flag": False,
        "data_completion_pct": np.nan,
        "suspected_duplicate_flag": False,
        "deal_scope": "Global / unknown",
    }.items():
        if calc_col not in df.columns:
            df[calc_col] = default
    if df.empty:
        return df
    missing_year = df["year"].isna() & df["announcement_date"].notna()
    df.loc[missing_year, "year"] = df.loc[missing_year, "announcement_date"].dt.year
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    missing_q = (df["quarter"].isna() | df["quarter"].astype(str).isin(["", "nan", "NaT"])) & df["announcement_date"].notna()
    df.loc[missing_q, "quarter"] = "Q" + df.loc[missing_q, "announcement_date"].dt.quarter.astype(str)
    ev = df["deal_value_eur_m"].combine_first(df["enterprise_value_eur_m"]).combine_first(df["equity_value_eur_m"])
    mw = df["capacity_mw"].combine_first(df["capacity_mwp"])
    df["disclosed_value_flag"] = ev.notna()
    df["disclosed_capacity_flag"] = mw.notna()
    calc = np.where((ev.notna()) & (mw > 0), ev / mw, np.nan)
    df["price_per_mw_eur_m"] = df["price_per_mw_eur_m"].combine_first(pd.Series(calc, index=df.index))
    stake = df["ownership_stake_acquired_pct"]
    implied = np.where((ev.notna()) & (stake > 0), ev / (stake / 100), np.nan)
    df["implied_100pct_value_eur_m"] = df["implied_100pct_value_eur_m"].combine_first(pd.Series(implied, index=df.index))
    df["data_completion_pct"] = df[["deal_id", "announcement_date", "buyer", "seller", "asset_or_company_name", "technology", "location_country", "capacity_mw", "deal_value_eur_m", "source_1"]].notna().mean(axis=1) * 100
    dup_key = df[["asset_or_company_name", "buyer", "seller", "source_domain"]].fillna("").agg("|".join, axis=1).str.lower()
    df["suspected_duplicate_flag"] = dup_key.duplicated(keep=False)
    loc_country = df["location_country"].fillna("").astype(str).str.lower()
    spanish_flag = df["spanish_company_involved"].fillna("").astype(str).str.lower()
    df["deal_scope"] = np.select(
        [loc_country.eq("spain"), spanish_flag.eq("yes") & ~loc_country.eq("spain")],
        ["Spain renewable asset/company", "Spanish company abroad"],
        default="Global / unknown"
    )
    return df


def read_local_db():
    try:
        return pd.read_csv(LOCAL_DB)
    except Exception:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)


def fetch_online_sources():
    st.session_state["source_errors"] = []
    newsapi_key = st.secrets.get("NEWSAPI_KEY", "") if hasattr(st, "secrets") else ""
    gnews_key = st.secrets.get("GNEWS_API_KEY", "") if hasattr(st, "secrets") else ""
    rows = []
    rows.extend(fetch_gdelt())
    rows.extend(fetch_pv_magazine_search())
    rows.extend(fetch_newsapi(newsapi_key))
    rows.extend(fetch_gnews(gnews_key))
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    df = ensure_schema(df)
    df = df.drop_duplicates(subset=["deal_id"], keep="first")
    # Filtrar ruido: mantener artículos con señales transaccionales o fuentes fiables.
    signal = df["raw_text_excerpt"].str.lower().str.contains("acquire|acquisition|buy|sell|merger|m&a|adquiere|compra|vende|fusión|fusion|cartera|portfolio", na=False)
    df = df[signal | (df["source_quality_score"] >= 4)]
    return df


def merge_sources(local_df, online_df):
    combined = pd.concat([local_df, online_df], ignore_index=True)
    if combined.empty:
        return ensure_schema(combined)
    combined = ensure_schema(combined)
    # Preferir registros ya validados frente a auto-detectados
    combined["_rank"] = combined["validation_status"].map({"validated": 0, "pending_review": 1, "auto_detected": 2}).fillna(3)
    combined = combined.sort_values(["deal_id", "_rank"]).drop_duplicates("deal_id", keep="first").drop(columns="_rank")
    return enrich_calculated(combined)


def to_excel_bytes(df, sheet_name="Deals"):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    return out.getvalue()


def fmt_eur(x):
    return "n.d." if pd.isna(x) else f"€{x:,.1f}m"


def fmt_num(x, suf=""):
    return "n.d." if pd.isna(x) else f"{x:,.1f}{suf}"


def sidebar_filters(df):
    st.sidebar.header("Filtros")
    f = df.copy()
    min_conf = st.sidebar.slider("Confianza mínima extracción", 0, 100, 0)
    f = f[(f["extraction_confidence_score"].isna()) | (f["extraction_confidence_score"] >= min_conf)]
    statuses = sorted([x for x in f["validation_status"].dropna().astype(str).unique() if x])
    sel = st.sidebar.multiselect("Validation status", statuses, default=statuses)
    if sel:
        f = f[f["validation_status"].astype(str).isin(sel)]
    for col, label in [("technology", "Tecnología"), ("location_country", "País"), ("source_domain", "Fuente"), ("buyer", "Comprador"), ("seller", "Vendedor"), ("transaction_type", "Tipo transacción")]:
        vals = sorted([x for x in f[col].dropna().astype(str).unique() if x])
        picked = st.sidebar.multiselect(label, vals)
        if picked:
            f = f[f[col].astype(str).isin(picked)]
    only_spain = st.sidebar.checkbox("Solo España / compañías españolas", value=True)
    if only_spain:
        f = f[(f["location_country"].fillna("").astype(str).str.lower().eq("spain")) | (f["spanish_company_involved"].fillna("").astype(str).str.lower().eq("yes"))]
    disclosed = st.sidebar.radio("Importe", ["Todos", "Solo divulgado", "Solo no divulgado"], horizontal=True)
    if disclosed == "Solo divulgado":
        f = f[f["disclosed_value_flag"]]
    elif disclosed == "Solo no divulgado":
        f = f[~f["disclosed_value_flag"]]
    return f


def kpis(df):
    val = df["deal_value_eur_m"].sum(min_count=1)
    mw = df["capacity_mw"].sum(min_count=1)
    wavg = val / mw if pd.notna(val) and pd.notna(mw) and mw > 0 else np.nan
    c = st.columns(6)
    c[0].metric("Deals", f"{len(df):,}")
    c[1].metric("Valor divulgado", fmt_eur(val))
    c[2].metric("MW", fmt_num(mw, " MW"))
    c[3].metric("€/MW ponderado", fmt_eur(wavg))
    c[4].metric("Pending review", int((df["validation_status"] == "pending_review").sum()))
    c[5].metric("Fuentes", df["source_domain"].nunique())


def screener(df):
    cols = ["deal_id", "validation_status", "extraction_confidence_score", "announcement_date", "asset_or_company_name", "buyer", "seller", "technology", "location_country", "capacity_mw", "deal_value_eur_m", "price_per_mw_eur_m", "ownership_stake_acquired_pct", "source_domain", "article_title", "source_url"]
    view = df[cols].copy()
    if "selected_ids" not in st.session_state:
        st.session_state.selected_ids = []
    view.insert(0, "select", view["deal_id"].astype(str).isin(st.session_state.selected_ids))
    edited = st.data_editor(view, use_container_width=True, hide_index=True, height=540, disabled=[c for c in view.columns if c != "select"], column_config={"source_url": st.column_config.LinkColumn("source_url")})
    st.session_state.selected_ids = edited.loc[edited["select"], "deal_id"].astype(str).tolist()
    st.caption(f"Seleccionadas: {len(st.session_state.selected_ids)}")


def charts(df):
    c1, c2 = st.columns(2)
    with c1:
        if df["year"].notna().any():
            annual = df.groupby("year").agg(deals=("deal_id", "count"), value=("deal_value_eur_m", "sum"), mw=("capacity_mw", "sum")).reset_index()
            st.plotly_chart(px.bar(annual, x="year", y="deals", title="Deals por año"), use_container_width=True)
            st.plotly_chart(px.bar(annual, x="year", y="value", title="Valor divulgado por año EURm"), use_container_width=True)
        tech = df.groupby("technology").size().reset_index(name="deals")
        st.plotly_chart(px.bar(tech, x="technology", y="deals", title="Deals por tecnología"), use_container_width=True)
    with c2:
        sources = df.groupby("source_domain").size().reset_index(name="articles").sort_values("articles", ascending=False).head(15)
        st.plotly_chart(px.bar(sources, x="articles", y="source_domain", orientation="h", title="Fuentes más frecuentes"), use_container_width=True)
        if df["capacity_mw"].notna().any() and df["deal_value_eur_m"].notna().any():
            st.plotly_chart(px.scatter(df, x="capacity_mw", y="deal_value_eur_m", color="technology", hover_name="asset_or_company_name", title="MW vs Deal Value"), use_container_width=True)
        val = df[df["price_per_mw_eur_m"].notna()]
        if not val.empty:
            st.plotly_chart(px.box(val, x="technology", y="price_per_mw_eur_m", title="Benchmark €/MW"), use_container_width=True)


def deal_detail(df):
    if df.empty:
        st.info("No hay deals con los filtros actuales.")
        return
    options = df["deal_id"].astype(str).tolist()
    default = 0
    if st.session_state.get("selected_ids"):
        sid = st.session_state.selected_ids[0]
        if sid in options:
            default = options.index(sid)
    deal_id = st.selectbox("Deal", options, index=default)
    r = df[df["deal_id"].astype(str) == deal_id].iloc[0]
    st.subheader(r["asset_or_company_name"])
    st.write(r["description"])
    c = st.columns(5)
    c[0].metric("Comprador", clean_text(r["buyer"]) or "n.d.")
    c[1].metric("Vendedor", clean_text(r["seller"]) or "n.d.")
    c[2].metric("MW", fmt_num(r["capacity_mw"], " MW"))
    c[3].metric("Importe", fmt_eur(r["deal_value_eur_m"]))
    c[4].metric("Confianza", fmt_num(r["extraction_confidence_score"], "%"))
    source_link = clean_text(r["source_url"]) or clean_text(r["source_1"])
    if source_link:
        st.link_button("Abrir fuente", source_link)
    else:
        st.caption("Fuente no disponible")
    st.json({k: str(r[k]) for k in ["validation_status", "transaction_type", "technology", "location_country", "ownership_stake_acquired_pct", "price_per_mw_eur_m", "source_domain", "article_title", "raw_text_excerpt", "notes"]}, expanded=False)


def validation_workspace(df):
    st.subheader("Pending Validation")
    pending = df[df["validation_status"].astype(str).isin(["pending_review", "auto_detected", ""])]
    st.info("La extracción automática es heurística. Usa esta pestaña para revisar candidatos, exportarlos y mantener solo los deals válidos en tu base maestra.")
    cols = ["deal_id", "extraction_confidence_score", "asset_or_company_name", "buyer", "seller", "capacity_mw", "deal_value_eur_m", "technology", "location_country", "source_domain", "source_url", "raw_text_excerpt"]
    st.dataframe(pending[cols], use_container_width=True, hide_index=True, column_config={"source_url": st.column_config.LinkColumn("source_url")})


def export_tab(full_df, filtered_df):
    st.download_button("Descargar base completa CSV", full_df.to_csv(index=False).encode("utf-8"), "deals_database_auto.csv", "text/csv")
    st.download_button("Descargar base filtrada Excel", to_excel_bytes(filtered_df), "filtered_auto_deals.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    selected = filtered_df[filtered_df["deal_id"].astype(str).isin(st.session_state.get("selected_ids", []))]
    st.download_button("Descargar seleccionadas Excel", to_excel_bytes(selected, "Selected"), "selected_deals.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.markdown("### Errores / avisos de fuentes")
    errs = st.session_state.get("source_errors", [])
    if errs:
        st.write(errs[:30])
    else:
        st.success("Sin errores de fuente en la última ingesta.")


def main():
    st.title(APP_TITLE)
    st.caption("Autoalimentación con fuentes abiertas: GDELT sin API key, scraping ligero de pv magazine España y APIs opcionales NewsAPI/GNews si configuras secrets.")

    refresh = st.sidebar.button("🔄 Refrescar fuentes online ahora")
    if "online_df" not in st.session_state or refresh:
        with st.spinner("Consultando fuentes online y extrayendo candidatos de M&A renovable..."):
            st.session_state.online_df = fetch_online_sources()
            st.session_state.last_refresh = now_iso()

    local_df = read_local_db()
    full_df = merge_sources(local_df, st.session_state.online_df)
    filtered = sidebar_filters(full_df)

    st.info(f"Última actualización online de esta sesión: {st.session_state.get('last_refresh', 'n.d.')} | Deals online detectados: {len(st.session_state.online_df):,} | Base total combinada: {len(full_df):,}")

    tabs = st.tabs(["Executive Dashboard", "Live Deal Feed", "Deal Detail", "Comparable Transactions", "Market Analytics", "Valuation Benchmarking", "Strategic Insights", "Pending Validation", "Export"])
    with tabs[0]:
        kpis(filtered)
        charts(filtered)
    with tabs[1]:
        screener(filtered)
    with tabs[2]:
        deal_detail(filtered)
    with tabs[3]:
        selected = filtered[filtered["deal_id"].astype(str).isin(st.session_state.get("selected_ids", []))]
        st.dataframe(selected, use_container_width=True, hide_index=True)
        if not selected.empty:
            kpis(selected)
    with tabs[4]:
        charts(filtered)
    with tabs[5]:
        valid = filtered[filtered["price_per_mw_eur_m"].notna()].copy()
        if valid.empty:
            st.info("No hay suficientes deals con importe y MW para benchmarking.")
        else:
            q1, q3 = valid["price_per_mw_eur_m"].quantile([0.25, 0.75]); iqr = q3-q1
            valid = valid[(valid["price_per_mw_eur_m"] >= q1-1.5*iqr) & (valid["price_per_mw_eur_m"] <= q3+1.5*iqr)]
            bench = valid.groupby(["technology", "location_country"])["price_per_mw_eur_m"].agg(deals="count", min="min", p25=lambda x: x.quantile(.25), median="median", p75=lambda x: x.quantile(.75), max="max").reset_index()
            st.dataframe(bench, use_container_width=True, hide_index=True)
    with tabs[6]:
        c1, c2 = st.columns(2)
        buyers = filtered["buyer"].replace("", np.nan).dropna().value_counts().head(15).rename_axis("buyer").reset_index(name="deals")
        sellers = filtered["seller"].replace("", np.nan).dropna().value_counts().head(15).rename_axis("seller").reset_index(name="deals")
        c1.dataframe(buyers, use_container_width=True, hide_index=True)
        c2.dataframe(sellers, use_container_width=True, hide_index=True)
        trend = filtered[filtered["price_per_mw_eur_m"].notna()].groupby(["year", "technology"])["price_per_mw_eur_m"].median().reset_index()
        if not trend.empty:
            st.plotly_chart(px.line(trend, x="year", y="price_per_mw_eur_m", color="technology", markers=True, title="Tendencia mediana €/MW"), use_container_width=True)
    with tabs[7]:
        validation_workspace(filtered)
    with tabs[8]:
        export_tab(full_df, filtered)

if __name__ == "__main__":
    main()
