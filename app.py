
import io, re, hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import numpy as np
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Renewable M&A Tracker v5", page_icon="⚡", layout="wide")
MASTER_FILE="deals_master_2020_2026.csv"
RECENT_FILE="recent_candidates.csv"
APP_TITLE="M&A Renewable Deal Tracker v5 – Deal Selection Focus"

BASE_COLS=["deal_id","announcement_date","year","quarter","deal_status","validation_status","transaction_type","asset_or_company_name","target_type","buyer","buyer_country","buyer_type","seller","seller_country","seller_type","spanish_company_involved","spanish_company_role","description","technology","location_country","location_region","location_province","location_city","capacity_mw","capacity_mwp","storage_mwh","number_of_assets","development_stage","regulated_or_merchant","ppa_status","grid_access_status","environmental_permit_status","deal_value_eur_m","enterprise_value_eur_m","equity_value_eur_m","debt_assumed_eur_m","price_per_mw_eur_m","ownership_stake_acquired_pct","implied_100pct_value_eur_m","source_1","source_2","source_3","source_quality_score","source_type","source_domain","source_url","article_title","article_date","ingestion_date","last_seen_date","extraction_method","extraction_confidence_score","duplicate_group_id","raw_text_excerpt","notes","last_updated"]
NUMERIC=["year","capacity_mw","capacity_mwp","storage_mwh","number_of_assets","deal_value_eur_m","enterprise_value_eur_m","equity_value_eur_m","debt_assumed_eur_m","price_per_mw_eur_m","ownership_stake_acquired_pct","implied_100pct_value_eur_m","source_quality_score","extraction_confidence_score"]
RECENT_QUERIES=["renewable acquisition Spain","solar portfolio sale Spain","wind portfolio acquisition Spain","renovables M&A España","compra cartera renovable España","vende cartera renovable España","Iberdrola renewable acquisition","Acciona Energia renewable sale","Repsol renewable portfolio sale","Naturgy renewable acquisition","EDPR renewable portfolio Spain","Spanish renewable company acquisition"]
TECH_PATTERNS={"solar PV":r"solar|fotovoltaic|fotovoltaica|pv","wind onshore":r"wind|eólic|eolic|onshore","wind offshore":r"offshore","battery storage":r"battery|bess|storage|almacenamiento|bater","biomethane":r"biomethane|biometano","biogas":r"biogas|biogás","hydrogen":r"hydrogen|hidrógeno|hidrogeno","hydro":r"hydro|hidroeléctr"}

def now_iso(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def clean(x): return "" if pd.isna(x) else re.sub(r"\s+"," ",str(x)).strip()
def ensure_schema(df):
    if df is None or df.empty: df=pd.DataFrame(columns=BASE_COLS)
    for c in BASE_COLS:
        if c not in df.columns: df[c]=np.nan
    return df[BASE_COLS+[c for c in df.columns if c not in BASE_COLS]]
@st.cache_data(show_spinner=False)
def load_csv(path):
    try: return pd.read_csv(path)
    except Exception: return pd.DataFrame(columns=BASE_COLS)

def make_deal_label(r):
    year="n.d." if pd.isna(r.get("year")) else str(int(r.get("year")))
    target=clean(r.get("asset_or_company_name")) or "Unnamed deal"
    buyer=clean(r.get("buyer")) or "Buyer n.d."
    seller=clean(r.get("seller")) or "Seller n.d."
    value="disclosed" if pd.notna(r.get("deal_value_eur_m")) else "undisclosed"
    mw="n.d. MW" if pd.isna(r.get("capacity_mw")) else f"{r.get('capacity_mw'):,.0f} MW"
    return f"{year} | {target} | {buyer} / {seller} | {mw} | {value}"

def normalize(df):
    df=ensure_schema(df).copy()
    for c in NUMERIC: df[c]=pd.to_numeric(df[c],errors="coerce")
    for c in ["announcement_date","article_date","ingestion_date","last_seen_date","last_updated"]: df[c]=pd.to_datetime(df[c],errors="coerce")
    if df.empty:
        for c,v in {"disclosed_value_flag":False,"disclosed_capacity_flag":False,"deal_scope":"Global / unknown","data_completion_pct":np.nan,"suspected_duplicate_flag":False,"deal_label":""}.items(): df[c]=v
        return df
    my=df["year"].isna() & df["announcement_date"].notna(); df.loc[my,"year"]=df.loc[my,"announcement_date"].dt.year
    df["year"]=pd.to_numeric(df["year"],errors="coerce").astype("Int64")
    ev=df["deal_value_eur_m"].combine_first(df["enterprise_value_eur_m"]).combine_first(df["equity_value_eur_m"])
    mw=df["capacity_mw"].combine_first(df["capacity_mwp"])
    df["disclosed_value_flag"]=ev.notna(); df["disclosed_capacity_flag"]=mw.notna()
    df["price_per_mw_eur_m"]=df["price_per_mw_eur_m"].combine_first(pd.Series(np.where((ev.notna())&(mw>0),ev/mw,np.nan),index=df.index))
    stake=df["ownership_stake_acquired_pct"]
    df["implied_100pct_value_eur_m"]=df["implied_100pct_value_eur_m"].combine_first(pd.Series(np.where((ev.notna())&(stake>0),ev/(stake/100),np.nan),index=df.index))
    loc=df["location_country"].fillna("").astype(str).str.lower(); sp=df["spanish_company_involved"].fillna("").astype(str).str.lower()
    df["deal_scope"]=np.select([loc.eq("spain"),sp.eq("yes") & ~loc.eq("spain")],["Spain renewable asset/company","Spanish company abroad"],default="Global / unknown")
    key=df[["asset_or_company_name","buyer","seller","announcement_date"]].fillna("").astype(str).agg("|".join,axis=1).str.lower()
    df["suspected_duplicate_flag"]=key.duplicated(keep=False)
    core=["deal_id","announcement_date","buyer","seller","asset_or_company_name","technology","location_country","capacity_mw","deal_value_eur_m","source_1"]
    df["data_completion_pct"]=df[core].notna().mean(axis=1)*100
    df["deal_label"]=df.apply(make_deal_label,axis=1)
    return df

def fmt_eur(x): return "n.d." if pd.isna(x) else f"€{x:,.1f}m"
def fmt_num(x,suffix=""): return "n.d." if pd.isna(x) else f"{x:,.1f}{suffix}"
def to_xlsx(df):
    out=io.BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as w: df.to_excel(w,index=False,sheet_name="Deals")
    return out.getvalue()

def domain(url):
    try: return urlparse(url).netloc.lower().replace("www.","")
    except Exception: return ""
def stable_id(url,title): return "CAND-"+hashlib.sha1(f"{url}|{title}".lower().encode()).hexdigest()[:12].upper()
def infer_tech(text):
    hits=[k for k,p in TECH_PATTERNS.items() if re.search(p,text.lower())]
    return "hybrid" if len(hits)>1 else (hits[0] if hits else "other")
def infer_country(text):
    t=text.lower()
    if any(x in t for x in ["spain","españa","spanish","iberdrola","acciona","repsol","naturgy","solaria"]): return "Spain"
    if "portugal" in t: return "Portugal"
    for c in ["Italy","France","Germany","United Kingdom","United States","Mexico","Brazil","Chile"]:
        if c.lower() in t: return c
    return ""
def extract_numbers(text):
    t=text.replace(",","."); mw=val=stake=np.nan
    m=re.search(r"(\d+(?:\.\d+)?)\s*(GW|gigawatts?)",t,re.I)
    if m: mw=float(m.group(1))*1000
    else:
        m=re.search(r"(\d+(?:\.\d+)?)\s*(MW|MWp|megawatts?)",t,re.I)
        if m: mw=float(m.group(1))
    m=re.search(r"(?:€|EUR|euros?)\s*(\d+(?:\.\d+)?)\s*(?:m|million|millones|mn|M)?",t,re.I) or re.search(r"(\d+(?:\.\d+)?)\s*(?:m|million|millones|mn|M)\s*(?:€|EUR|euros?)",t,re.I)
    if m: val=float(m.group(1))
    m=re.search(r"(\d+(?:\.\d+)?)\s*%",t)
    if m: stake=float(m.group(1))
    return mw,val,stake

def article_to_candidate(a):
    title=clean(a.get("title")); url=clean(a.get("url")); text=f"{title}. {clean(a.get('seendate') or a.get('description') or '')}"
    date=pd.to_datetime(a.get("seendate"),errors="coerce"); date_str=date.date().isoformat() if pd.notna(date) else ""
    mw,val,stake=extract_numbers(text)
    return {"deal_id":stable_id(url,title),"announcement_date":date_str,"year":date.year if pd.notna(date) else np.nan,"quarter":"","deal_status":"announced","validation_status":"pending_review","transaction_type":"candidate","asset_or_company_name":title[:120],"target_type":"unknown","buyer":"","buyer_country":"","buyer_type":"","seller":"","seller_country":"","seller_type":"","spanish_company_involved":"yes" if re.search(r"spain|españa|spanish|iberdrola|acciona|repsol|naturgy|solaria",text,re.I) else "unknown","spanish_company_role":"unknown","description":text[:600],"technology":infer_tech(text),"location_country":infer_country(text),"location_region":"","location_province":"","location_city":"","capacity_mw":mw,"capacity_mwp":np.nan,"storage_mwh":np.nan,"number_of_assets":np.nan,"development_stage":"unknown","regulated_or_merchant":"unknown","ppa_status":"unknown","grid_access_status":"unknown","environmental_permit_status":"unknown","deal_value_eur_m":val,"enterprise_value_eur_m":val,"equity_value_eur_m":np.nan,"debt_assumed_eur_m":np.nan,"price_per_mw_eur_m":val/mw if pd.notna(val) and pd.notna(mw) and mw>0 else np.nan,"ownership_stake_acquired_pct":stake,"implied_100pct_value_eur_m":val/(stake/100) if pd.notna(val) and pd.notna(stake) and stake>0 else np.nan,"source_1":url,"source_2":"","source_3":"","source_quality_score":2,"source_type":"GDELT recent","source_domain":domain(url),"source_url":url,"article_title":title,"article_date":date_str,"ingestion_date":now_iso(),"last_seen_date":now_iso(),"extraction_method":"gdelt_recent_v5","extraction_confidence_score":50+(20 if pd.notna(mw) else 0)+(10 if pd.notna(val) else 0),"duplicate_group_id":"","raw_text_excerpt":text[:1200],"notes":"Recent candidate detected online; review before adding to master.","last_updated":now_iso(),"candidate_reason":"recent online article"}

@st.cache_data(ttl="2h",show_spinner=False)
def fetch_recent_candidates(days_back=120,max_records=30):
    endpoint="https://api.gdeltproject.org/api/v2/doc/doc"; start=(datetime.now(timezone.utc)-timedelta(days=days_back)).strftime("%Y%m%d%H%M%S"); end=datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rows=[]
    for q in RECENT_QUERIES:
        query=f'({q}) (acquisition OR acquires OR acquired OR buys OR sells OR M&A OR merger OR compra OR adquiere OR vende OR cartera OR portfolio)'
        try:
            r=requests.get(endpoint,params={"query":query,"mode":"ArtList","format":"json","maxrecords":max_records,"sort":"HybridRel","startdatetime":start,"enddatetime":end},timeout=20); r.raise_for_status()
            rows += [article_to_candidate(a) for a in r.json().get("articles",[])]
        except Exception as e: st.session_state.setdefault("source_errors",[]).append(str(e))
    df=pd.DataFrame(rows)
    if df.empty: return ensure_schema(df)
    df=ensure_schema(df).drop_duplicates("deal_id")
    return df[df["raw_text_excerpt"].astype(str).str.lower().str.contains("acqui|sell|sold|buy|merger|m&a|compra|adquiere|vende|portfolio|cartera")]

def deal_sidebar_filter(master):
    st.sidebar.header("Filtro")
    st.sidebar.caption("Único filtro activo: Deal")
    labels=["Todos los deals"]+master.sort_values(["year","asset_or_company_name"],na_position="last")["deal_label"].tolist()
    selected=st.sidebar.selectbox("Deal", labels, key="only_deal_filter_v5")
    return (master.copy(), selected) if selected=="Todos los deals" else (master[master["deal_label"].eq(selected)].copy(), selected)

def kpis(df):
    val=df["deal_value_eur_m"].sum(min_count=1); mw=df["capacity_mw"].sum(min_count=1); mwh=df["storage_mwh"].sum(min_count=1); wavg=val/mw if pd.notna(val) and pd.notna(mw) and mw>0 else np.nan
    c=st.columns(6); c[0].metric("Deals",f"{len(df):,}"); c[1].metric("Deals con importe",f"{int(df['disclosed_value_flag'].sum()) if len(df) else 0:,}"); c[2].metric("Valor divulgado",fmt_eur(val)); c[3].metric("MW",fmt_num(mw," MW")); c[4].metric("MWh",fmt_num(mwh," MWh")); c[5].metric("€/MW ponderado","n.d." if pd.isna(wavg) else f"€{wavg:,.2f}m/MW")

def summary_tables(df):
    st.subheader("Resumen útil de la base")
    c1,c2,c3=st.columns(3)
    with c1:
        st.markdown("**Por año**"); st.dataframe(df.groupby("year",dropna=True).agg(deals=("deal_id","count"),value_eur_m=("deal_value_eur_m","sum"),mw=("capacity_mw","sum")).reset_index().sort_values("year"),use_container_width=True,hide_index=True,key="year_summary_v5")
    with c2:
        st.markdown("**Por tecnología**"); st.dataframe(df.groupby("technology",dropna=False).agg(deals=("deal_id","count"),value_eur_m=("deal_value_eur_m","sum"),mw=("capacity_mw","sum")).reset_index().sort_values("deals",ascending=False),use_container_width=True,hide_index=True,key="tech_summary_v5")
    with c3:
        st.markdown("**Top deals con importe divulgado**"); disclosed=df[df["deal_value_eur_m"].notna()].sort_values("deal_value_eur_m",ascending=False); st.dataframe(disclosed[["announcement_date","asset_or_company_name","buyer","seller","deal_value_eur_m","capacity_mw"]].head(10),use_container_width=True,hide_index=True,key="top_disclosed_v5")

def master_table(df):
    st.subheader("Deals")
    show=["deal_id","validation_status","announcement_date","asset_or_company_name","buyer","seller","technology","location_country","capacity_mw","storage_mwh","deal_value_eur_m","price_per_mw_eur_m","ownership_stake_acquired_pct","deal_status","source_url"]
    view=df[show].copy()
    if "selected_ids" not in st.session_state: st.session_state.selected_ids=[]
    view.insert(0,"select",view["deal_id"].astype(str).isin(st.session_state.selected_ids))
    edited=st.data_editor(view,hide_index=True,height=560,use_container_width=True,disabled=[c for c in view.columns if c!="select"],column_config={"source_url":st.column_config.LinkColumn("source_url")},key="master_table_v5")
    st.session_state.selected_ids=edited.loc[edited["select"],"deal_id"].astype(str).tolist(); st.caption(f"Seleccionadas: {len(st.session_state.selected_ids)}")

def deal_detail(df, selected_label):
    st.subheader("Detalle del deal")
    if df.empty: st.info("No hay operaciones."); return
    if selected_label=="Todos los deals":
        opts=df["deal_label"].tolist(); default=0
        if st.session_state.get("selected_ids"):
            m=df[df["deal_id"].astype(str).eq(st.session_state.selected_ids[0])]
            if not m.empty: default=opts.index(m.iloc[0]["deal_label"])
        r=df[df["deal_label"].eq(st.selectbox("Deal para detalle", opts, index=default, key="detail_deal_select_v5"))].iloc[0]
    else: r=df.iloc[0]
    st.markdown(f"### {clean(r['asset_or_company_name'])}"); st.write(clean(r["description"]) or "Sin descripción.")
    c=st.columns(5); c[0].metric("Comprador",clean(r["buyer"]) or "n.d."); c[1].metric("Vendedor",clean(r["seller"]) or "n.d."); c[2].metric("MW",fmt_num(r["capacity_mw"]," MW")); c[3].metric("Importe",fmt_eur(r["deal_value_eur_m"])); c[4].metric("Stake",fmt_num(r["ownership_stake_acquired_pct"],"%"))
    if clean(r["source_url"]): st.link_button("Abrir fuente", r["source_url"])
    fields=["announcement_date","deal_status","validation_status","transaction_type","target_type","technology","location_country","development_stage","regulated_or_merchant","ppa_status","grid_access_status","environmental_permit_status","price_per_mw_eur_m","implied_100pct_value_eur_m","source_quality_score","notes"]
    st.dataframe(pd.DataFrame({"Campo":fields,"Valor":[str(r[x]) for x in fields]}),use_container_width=True,hide_index=True,key="detail_fields_v5")

def recent_candidates_tab():
    st.subheader("Recent Candidates"); st.write("Los candidatos recientes se mantienen separados de la base maestra hasta revisión.")
    if st.button("Buscar candidatos recientes online",key="btn_recent_v5"):
        with st.spinner("Consultando fuentes recientes..."):
            fetch_recent_candidates.clear(); st.session_state["recent_live"]=normalize(fetch_recent_candidates()); st.session_state["recent_live_time"]=now_iso()
    st.caption(f"Última búsqueda reciente: {st.session_state.get('recent_live_time','no ejecutada')}")
    recent=normalize(pd.concat([normalize(load_csv(RECENT_FILE)), st.session_state.get("recent_live",pd.DataFrame(columns=BASE_COLS))],ignore_index=True))
    if recent.empty: st.info("No hay candidatos recientes. Pulsa el botón superior para buscar online."); return recent
    show=["deal_id","announcement_date","asset_or_company_name","technology","location_country","capacity_mw","deal_value_eur_m","source_domain","source_url","raw_text_excerpt"]
    st.dataframe(recent[show],use_container_width=True,hide_index=True,column_config={"source_url":st.column_config.LinkColumn("source_url")},key="recent_candidates_v5")
    return recent

def data_quality(master):
    st.subheader("Data Quality"); c=st.columns(5); c[0].metric("Deals",len(master)); c[1].metric("Sin importe",int(master["deal_value_eur_m"].isna().sum())); c[2].metric("Sin MW",int(master["capacity_mw"].isna().sum())); c[3].metric("Duplicados potenciales",int(master["suspected_duplicate_flag"].sum())); c[4].metric("Completitud media",f"{master['data_completion_pct'].mean():.1f}%")
    st.dataframe(master[["deal_id","asset_or_company_name","data_completion_pct","source_quality_score","suspected_duplicate_flag","source_url","notes"]],use_container_width=True,hide_index=True,column_config={"source_url":st.column_config.LinkColumn("source_url")},key="dq_v5")

def export_tab(master, filtered, recent):
    st.subheader("Export"); selected=filtered[filtered["deal_id"].astype(str).isin(st.session_state.get("selected_ids",[]))]
    st.download_button("Descargar base maestra completa Excel",to_xlsx(master),"deals_master_2020_2026.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",key="dl_master_xlsx_v5")
    st.download_button("Descargar base filtrada CSV",filtered.to_csv(index=False).encode("utf-8"),"filtered_master_deals.csv","text/csv",key="dl_filtered_csv_v5")
    st.download_button("Descargar deals seleccionados Excel",to_xlsx(selected),"selected_transactions.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",key="dl_selected_xlsx_v5")
    st.download_button("Descargar candidatos recientes CSV",recent.to_csv(index=False).encode("utf-8"),"recent_candidates.csv","text/csv",key="dl_recent_csv_v5")

def main():
    st.title(APP_TITLE); st.caption("Versión simplificada: sin gráficos irrelevantes, sin widgets duplicados y con un único filtro lateral por deal.")
    master=normalize(load_csv(MASTER_FILE))
    if master.empty: st.error("No se ha encontrado o está vacía la base maestra deals_master_2020_2026.csv."); st.stop()
    filtered, selected_label=deal_sidebar_filter(master)
    st.info(f"Base maestra: {len(master):,} registros | Vista actual: {len(filtered):,} registros | El desplegable de la izquierda contiene todos los deals, marcando si el importe está disclosed o undisclosed.")
    tabs=st.tabs(["Dashboard","Deals","Deal Detail","Selected Transactions","Recent Candidates","Data Quality","Export"])
    with tabs[0]: kpis(filtered); summary_tables(filtered)
    with tabs[1]: master_table(filtered)
    with tabs[2]: deal_detail(filtered,selected_label)
    with tabs[3]:
        selected=filtered[filtered["deal_id"].astype(str).isin(st.session_state.get("selected_ids",[]))]
        if selected.empty: st.info("Selecciona deals en la pestaña 'Deals'.")
        else: kpis(selected); st.dataframe(selected,use_container_width=True,hide_index=True,column_config={"source_url":st.column_config.LinkColumn("source_url")},key="selected_v5")
    with tabs[4]: recent=recent_candidates_tab()
    with tabs[5]: data_quality(master)
    with tabs[6]:
        recent=normalize(pd.concat([normalize(load_csv(RECENT_FILE)),st.session_state.get("recent_live",pd.DataFrame(columns=BASE_COLS))],ignore_index=True)); export_tab(master,filtered,recent)
if __name__=="__main__": main()
