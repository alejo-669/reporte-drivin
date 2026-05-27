"""
Dashboard Operacional Drivin — Bimbo Ideal
==========================================
Multi-page sidebar · Tema claro Bimbo
Zona horaria: America/Santiago · Auto-refresh 10 min
"""
import os, json, sqlite3
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from streamlit_autorefresh import st_autorefresh

# ── Config ──────────────────────────────────────────────────
TZ_CHILE = ZoneInfo("America/Santiago")
NOW_CHILE = datetime.now(TZ_CHILE)
BIMBO_BLUE = "#003087"
BIMBO_CELESTE = "#38bdf8"
BIMBO_GREEN = "#16a34a"
BIMBO_RED = "#dc2626"
DB_PATH = "espera_historica.db"
ALERTA_MIN_SALA = 90   # min en sala para alerta
ALERTA_HR_INICIO = 7   # hora para alerta sin iniciar

st.set_page_config(page_title="Drivin — Bimbo Ideal", page_icon="🚛", layout="wide", initial_sidebar_state="expanded")
st_autorefresh(interval=600_000, key="data_refresh")

# ── Helpers ─────────────────────────────────────────────────
STATUS_MAP = {"approved": "Aprobado", "rejected": "Rechazado", "partial": "Parcial", "pending": "Pendiente"}
def translate_status(v):
    return "-" if pd.isna(v) or v is None or v == "" else STATUS_MAP.get(str(v).lower(), str(v))
def clean_none(v):
    return "-" if pd.isna(v) or v is None or str(v).strip().lower() in ("none","nan","") else v
def fmt_bultos(v):
    try: return int(float(v))
    except: return 0
def parse_hour_chile(dt_str):
    if not dt_str or pd.isna(dt_str): return "-"
    try:
        dt = pd.to_datetime(dt_str)
        if dt.tzinfo is None: dt = dt.tz_localize("UTC")
        return dt.astimezone(TZ_CHILE).strftime("%H:%M")
    except: return "-"

# Color functions
def color_status(v):
    if v=="Aprobado": return "background-color:#dcfce7;color:#166534"
    if v=="Rechazado": return "background-color:#fee2e2;color:#991b1b"
    if v in("Parcial","Pendiente"): return "background-color:#fef9c3;color:#854d0e"
    return ""
def color_estado(v):
    if v=="Finalizada": return "background-color:#dcfce7;color:#166534"
    if v=="En ruta": return "background-color:#dbeafe;color:#1e40af"
    if v=="Sin iniciar": return "background-color:#fee2e2;color:#991b1b"
    return ""
def color_ubicacion(v):
    s=str(v)
    if "Sin iniciar" in s: return "background-color:#fee2e2;color:#991b1b"
    if "En sala" in s: return "background-color:#fef9c3;color:#854d0e"
    if "Pendiente" in s: return "background-color:#dbeafe;color:#1e40af"
    if "Visitada" in s: return "background-color:#e0e7ff;color:#3730a3"
    if "finalizada" in s.lower() or "Entregada" in s: return "background-color:#dcfce7;color:#166534"
    return ""
def color_vuelta(v):
    return "background-color:#fef9c3;color:#854d0e" if v=="Segunda vuelta" else ""
def color_cxs(v):
    try:
        n=float(str(v).replace("%",""))
        if n>10: return "background-color:#fee2e2;color:#991b1b"
        if n>5: return "background-color:#fef9c3;color:#854d0e"
        if n>0: return "background-color:#dcfce7;color:#166534"
    except: pass
    return ""
def color_maxcube(v):
    try:
        n=float(str(v).replace("%",""))
        if n<50: return "background-color:#fee2e2;color:#991b1b"
        if n<75: return "background-color:#fef9c3;color:#854d0e"
        return "background-color:#dcfce7;color:#166534"
    except: pass
    return ""

PLOTLY_BASE = dict(template="plotly_white", paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(255,255,255,1)", font=dict(color="#1a1a2e",size=12), margin=dict(l=10,r=10,t=30,b=10))

# ── Snapshot DB ─────────────────────────────────────────────
def init_db():
    conn=sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS espera_snapshots")
    conn.execute("""CREATE TABLE IF NOT EXISTS espera_visitas(
        address_code TEXT, planned_date TEXT, tracked_arrival TEXT,
        tracked_service_time REAL, tracked_leave TEXT, snapshot_at TEXT,
        PRIMARY KEY(address_code,planned_date,tracked_arrival))""")
    conn.commit(); conn.close()

def save_espera_snapshot(records):
    conn=sqlite3.connect(DB_PATH)
    for r in records:
        tst=r.get("tracked_service_time"); ta=r.get("tracked_arrival")
        if tst and tst>0 and ta:
            try:
                ex=conn.execute("SELECT tracked_service_time FROM espera_visitas WHERE address_code=? AND planned_date=? AND tracked_arrival=?",
                    (r.get("address_code"),r.get("planned_date"),ta)).fetchone()
                if ex:
                    if tst>ex[0]:
                        conn.execute("UPDATE espera_visitas SET tracked_service_time=?,tracked_leave=?,snapshot_at=? WHERE address_code=? AND planned_date=? AND tracked_arrival=?",
                            (tst,r.get("tracked_leave"),NOW_CHILE.isoformat(),r.get("address_code"),r.get("planned_date"),ta))
                else:
                    conn.execute("INSERT INTO espera_visitas VALUES(?,?,?,?,?,?)",
                        (r.get("address_code"),r.get("planned_date"),ta,tst,r.get("tracked_leave"),NOW_CHILE.isoformat()))
            except: pass
    conn.commit(); conn.close()

def get_espera_historica(dates):
    conn=sqlite3.connect(DB_PATH); result={}
    try:
        ph=",".join(["?"]*len(dates))
        for row in conn.execute(f"SELECT address_code,planned_date,SUM(tracked_service_time),MAX(tracked_service_time),COUNT(*) FROM espera_visitas WHERE planned_date IN({ph}) GROUP BY address_code,planned_date",dates).fetchall():
            result[(row[0],row[1])]={"total":row[2],"max":row[3],"visitas":row[4]}
    except: pass
    conn.close(); return result

# ── Data Loading ────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_vehicle_info():
    import requests
    api_key=os.environ.get("DRIVIN_API_KEY","")
    if not api_key:
        try: api_key=st.secrets["DRIVIN_API_KEY"]
        except: return {},{}
    try:
        resp=requests.get("https://external.driv.in/api/external/v2/vehicles",headers={"X-API-KEY":api_key,"Content-Type":"application/json"},timeout=30)
        resp.raise_for_status(); vehicles=resp.json().get("response",[])
    except: return {},{}
    fletes,caps={},{}
    for v in vehicles:
        c=v.get("code","")
        if c:
            c3=v.get("capacity_3",0) or 0
            c1=v.get("capacity_1",0) or 0
            if c3>0: fletes[c]=int(c3)
            if c1>0: caps[c]=int(c1)
    return fletes,caps

@st.cache_data(ttl=600)
def load_data(start_date,end_date):
    import requests
    api_key=os.environ.get("DRIVIN_API_KEY","")
    if not api_key:
        try: api_key=st.secrets["DRIVIN_API_KEY"]
        except: return pd.DataFrame()
    try:
        resp=requests.get("https://external.driv.in/api/external/v2/pods",
            headers={"X-API-KEY":api_key,"Content-Type":"application/json"},
            params={"start_date":start_date,"end_date":end_date},timeout=30)
        resp.raise_for_status(); records=resp.json().get("response",[])
    except Exception as e:
        st.error(f"Error API: {e}"); return pd.DataFrame()
    if not records: return pd.DataFrame()
    try: init_db(); save_espera_snapshot(records)
    except: pass
    rows=[]
    for r in records:
        base={"planned_date":r.get("planned_date"),"vehicle_code":r.get("vehicle_code"),
            "schema_name":r.get("schema_name"),"fleet_name":r.get("fleet_name"),
            "route_is_started":r.get("route_is_started"),"route_is_finished":r.get("route_is_finished"),
            "route_started_at":r.get("route_started_at"),"route_finished_at":r.get("route_finished_at"),
            "driver_name":(r.get("driver_name") or "").strip(),"employer_name":r.get("employer_name"),
            "address_name":r.get("address_name"),"address_code":r.get("address_code"),
            "address_city":r.get("address_city"),"tracked_arrival":r.get("tracked_arrival"),
            "tracked_leave":r.get("tracked_leave"),"tracked_service_time":r.get("tracked_service_time"),
            "visit_arrival":r.get("visit_arrival"),"visit_leave":r.get("visit_leave"),
            "trip_number":r.get("trip_number"),"route_code":r.get("route_code"),
            "eta":r.get("eta"),
            "time_window_start":(r.get("time_window") or {}).get("start"),
            "time_window_end":(r.get("time_window") or {}).get("end")}
        for o in r.get("orders",[]):
            rows.append({**base,"order_code":o.get("code"),"status":o.get("status"),
                "reason":o.get("reason"),"otif":o.get("otif"),"near_pod":o.get("near_pod"),
                "units_1":o.get("units_1") or 0,"units_2":o.get("units_2") or 0,
                "units_3":o.get("units_3") or 0,"client_name":o.get("client_name"),
                "tags":json.dumps(o.get("tags",[])),"pod_arrival":o.get("pod_arrival")})
    df=pd.DataFrame(rows)
    df["units_1"]=df["units_1"].apply(fmt_bultos)
    df["units_2"]=df["units_2"].apply(lambda x:int(float(x)) if pd.notna(x) and x!=0 else 0)
    df["units_3"]=df["units_3"].apply(lambda x:int(float(x)) if pd.notna(x) and x!=0 else 0)
    df["status_display"]=df["status"].apply(translate_status)
    df["tipo_viaje"]=df["trip_number"].apply(lambda x:"Primera vuelta" if x==1 else("Segunda vuelta" if x==2 else "-"))
    for col in ["reason","near_pod","client_name","driver_name","address_city","employer_name"]:
        if col in df.columns: df[col]=df[col].apply(clean_none)
    # Espera calculada
    if "tracked_arrival" in df.columns and "tracked_leave" in df.columns:
        df["_a"]=pd.to_datetime(df["tracked_arrival"],errors="coerce")
        df["_l"]=pd.to_datetime(df["tracked_leave"],errors="coerce")
        df["espera_calculada"]=((df["_l"]-df["_a"]).dt.total_seconds()/60).round(0)
        df["espera_calculada"]=df["espera_calculada"].apply(lambda x:int(x) if pd.notna(x) and x>0 else None)
        df.drop(columns=["_a","_l"],inplace=True)
    else: df["espera_calculada"]=None
    df["espera_real"]=df[["tracked_service_time","espera_calculada"]].max(axis=1)
    try:
        dates=df["planned_date"].dropna().unique().tolist()
        if dates:
            h=get_espera_historica(dates)
            df["_ht"]=df.apply(lambda r:(h.get((r["address_code"],r["planned_date"])) or {}).get("total"),axis=1)
            df["_hm"]=df.apply(lambda r:(h.get((r["address_code"],r["planned_date"])) or {}).get("max"),axis=1)
            df["visitas_gps"]=df.apply(lambda r:(h.get((r["address_code"],r["planned_date"])) or {}).get("visitas"),axis=1)
            df["espera_total_sala"]=df["_ht"].combine_first(df["espera_real"])
            df["espera_max_sala"]=df[["espera_real","_hm"]].max(axis=1)
            df["visitas_gps"]=df["visitas_gps"].fillna(1).astype(int)
            df.drop(columns=["_ht","_hm"],inplace=True)
        else: df["espera_total_sala"]=df["espera_real"]; df["espera_max_sala"]=df["espera_real"]; df["visitas_gps"]=1
    except: df["espera_total_sala"]=df["espera_real"]; df["espera_max_sala"]=df["espera_real"]; df["visitas_gps"]=1
    if not df.empty:
        df["espera_max_sala"]=df.groupby(["address_code","planned_date"])["espera_max_sala"].transform("max")
        df["espera_total_sala"]=df.groupby(["address_code","planned_date"])["espera_total_sala"].transform("max")
        df["visitas_gps"]=df.groupby(["address_code","planned_date"])["visitas_gps"].transform("max")
    return df

# ── Ubicacion functions ─────────────────────────────────────
def ubicacion_vehiculos(df):
    ub={}
    for v,g in df.groupby("vehicle_code"):
        r0=g.iloc[0]
        if not r0["route_is_started"] and not r0["route_is_finished"]: ub[v]="🔴 Sin iniciar ruta"; continue
        if r0["route_is_finished"]: ub[v]="✅ Ruta finalizada"; continue
        cand=g[(g["tracked_service_time"].notna())&(g["tracked_service_time"]>0)&(~g["status"].isin(["approved","rejected","partial"]))]
        if not cand.empty: ub[v]=f"📍 En sala {cand.loc[cand['tracked_service_time'].idxmax(),'address_code']}"; continue
        en=g[g["tracked_arrival"].notna()&g["tracked_leave"].isna()]
        if not en.empty: ub[v]=f"📍 En sala {en.iloc[0]['address_code']}"; continue
        pend=g[g["tracked_arrival"].isna()].copy()
        if not pend.empty:
            pend["_e"]=pd.to_datetime(pend["planned_date"]+" "+pend["eta"].fillna("23:59"),errors="coerce")
            pend=pend.sort_values("_e"); ub[v]=f"🚛 En ruta hacia sala {pend.iloc[0]['address_code']}"; continue
        ub[v]="🚛 En ruta (todas las salas visitadas)"
    return ub

def ubicacion_por_sala(df):
    sala_actual={}
    for v,g in df.groupby("vehicle_code"):
        if not g.iloc[0]["route_is_started"] or g.iloc[0]["route_is_finished"]: continue
        c=g[(g["tracked_service_time"].notna())&(g["tracked_service_time"]>0)&(~g["status"].isin(["approved","rejected","partial"]))]
        if not c.empty: sala_actual[v]=c["tracked_service_time"].idxmax()
    def f(row):
        if not row["route_is_started"] and not row["route_is_finished"]: return "🔴 Sin iniciar ruta"
        s=str(row.get("status","")).lower(); reason=str(row.get("reason",""))
        if s in("approved","rejected","partial") or (reason not in("-","","nan","None") and pd.notna(row.get("reason"))): return "✅ Entregada"
        if row["route_is_finished"]: return "✅ Ruta finalizada"
        if row["vehicle_code"] in sala_actual and sala_actual[row["vehicle_code"]]==row.name: return f"📍 En sala {row['address_code']}"
        tst=row.get("tracked_service_time")
        if pd.notna(tst) and tst>0: return "🔵 Visitada (sin status)"
        return "🚛 Pendiente"
    return df.apply(f,axis=1)

# ── CSS ─────────────────────────────────────────────────────
st.markdown("""<style>
.stApp,[data-testid="stAppViewContainer"]{background:#fff!important;color:#1a1a2e!important}
section[data-testid="stSidebar"]{background:linear-gradient(180deg,"""+BIMBO_BLUE+""" 0%,#001a4d 100%)!important}
section[data-testid="stSidebar"] *{color:#e2e8f0!important}
section[data-testid="stSidebar"] .stSelectbox label,section[data-testid="stSidebar"] .stDateInput label,
section[data-testid="stSidebar"] .stRadio label{color:#94a3b8!important;font-size:.82rem!important}
section[data-testid="stSidebar"] [data-baseweb="select"] > div{background:#1e3a6e!important;border-color:#334155!important;color:#e2e8f0!important}
div[data-testid="metric-container"]{background:linear-gradient(135deg,#f7faff,#edf2fa);border:1px solid #cdd9e5;border-radius:12px;padding:14px;box-shadow:0 1px 4px rgba(0,48,135,.06)}
div[data-testid="metric-container"] label{color:#5a6a7e!important;font-size:.78rem!important;font-weight:600!important;text-transform:uppercase}
div[data-testid="metric-container"] [data-testid="stMetricValue"]{font-size:1.6rem!important;font-weight:800!important;color:"""+BIMBO_BLUE+"""!important}
.stDataFrame thead tr th{background:"""+BIMBO_BLUE+"""!important;color:#fff!important;font-weight:700!important}
.alerta-box{background:linear-gradient(135deg,#fff5f5,#fee2e2);border:1px solid #f87171;border-radius:10px;padding:12px 18px;color:#b91c1c;font-weight:600;margin-bottom:.8rem}
.alerta-yellow{background:linear-gradient(135deg,#fffbeb,#fef3c7);border:1px solid #f59e0b;border-radius:10px;padding:12px 18px;color:#92400e;font-weight:600;margin-bottom:.8rem}
.alerta-blue{background:linear-gradient(135deg,#eff6ff,#dbeafe);border:1px solid #3b82f6;border-radius:10px;padding:12px 18px;color:#1e40af;font-weight:600;margin-bottom:.8rem}
.section-title{font-size:1.05rem;font-weight:700;color:"""+BIMBO_BLUE+""";margin-bottom:.5rem;padding-bottom:4px;border-bottom:2px solid """+BIMBO_CELESTE+""";display:inline-block}
.sidebar-title{font-size:1.3rem;font-weight:800;color:#fff;text-align:center;margin-bottom:1.5rem;padding:10px 0;border-bottom:2px solid """+BIMBO_CELESTE+"""}
hr{border-color:#e2e8f0!important}
</style>""",unsafe_allow_html=True)

# ── Sidebar ─────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="sidebar-title">🚛 Drivin Dashboard<br>Bimbo Ideal</div>',unsafe_allow_html=True)
    page=st.radio("📖 Navegación",["🏠 Inicio","🚗 Monitoreo Flota","📦 Status Entregas","🏆 Ranking Salas","📈 Tendencias","💰 CxS por Camión","📊 Rendimiento Operador"],label_visibility="collapsed")
    st.divider()
    st.markdown("**🔍 Filtros**")
    today=NOW_CHILE.date()
    if page=="📈 Tendencias":
        f_dates=st.date_input("📅 Rango de fechas",value=(today-timedelta(days=6),today),max_value=today,min_value=today-timedelta(days=7))
    else:
        f_dates=st.date_input("📅 Fecha",value=(today,today),max_value=today,min_value=today-timedelta(days=7))
    if isinstance(f_dates,tuple) and len(f_dates)==2: start_d,end_d=f_dates
    else: start_d=end_d=today

# Load data
df_all=load_data(start_d.strftime("%Y-%m-%d"),end_d.strftime("%Y-%m-%d"))
if df_all.empty:
    st.warning("⚠️ Sin datos. Verifica API Key en Settings → Secrets."); st.stop()

# Centro de venta filter (global)
with st.sidebar:
    centros=["Todos"]+sorted(df_all["schema_name"].dropna().unique().tolist())
    f_centro=st.selectbox("🏭 Centro de venta",centros)

df=df_all.copy()
if f_centro!="Todos": df=df[df["schema_name"]==f_centro]

# Page-specific filters
with st.sidebar:
    if page=="🚗 Monitoreo Flota":
        ops=["Todos"]+sorted(df["employer_name"].replace("-",pd.NA).dropna().unique().tolist())
        f_op=st.selectbox("🚚 Operador",ops)
        f_estado=st.selectbox("📍 Estado",["Todos","En ruta","Finalizada","Sin iniciar"])
    elif page=="📦 Status Entregas":
        salas_list=["— Todas —"]+sorted(df["address_code"].dropna().unique().tolist())
        f_sala=st.selectbox("🏪 Sala (muestra camión completo)",salas_list)
        vehs=["Todos"]+sorted(df["vehicle_code"].dropna().unique().tolist())
        f_veh=st.selectbox("🚛 Vehículo",vehs)
        ops2=["Todos"]+sorted(df["employer_name"].replace("-",pd.NA).dropna().unique().tolist())
        f_op2=st.selectbox("🚚 Operador",ops2)
        motivos_l=["Todos"]+sorted(df["reason"].replace("-",pd.NA).dropna().unique().tolist())
        f_motivo=st.selectbox("📋 Motivo",motivos_l)
    elif page=="💰 CxS por Camión":
        ops3=["Todos"]+sorted(df["employer_name"].replace("-",pd.NA).dropna().unique().tolist())
        f_op3=st.selectbox("🚚 Operador",ops3)
        f_vuelta=st.selectbox("🔄 Vuelta",["Todas","Primera vuelta","Segunda vuelta"])
    elif page=="📊 Rendimiento Operador":
        ops4=["Todos"]+sorted(df["employer_name"].replace("-",pd.NA).dropna().unique().tolist())
        f_op4=st.selectbox("🚚 Operador",ops4)

    st.divider()
    st.caption(f"Actualizado: {NOW_CHILE.strftime('%d/%m/%Y %H:%M')}")
    st.divider()
    st.markdown('<div style="text-align:center"><img src="https://www.bimbo.cl/sites/default/files/2024-03/osito-bimbo.png" width="120" style="opacity:0.9"></div>',unsafe_allow_html=True)

# ── KPI Calculations ────────────────────────────────────────
total_ent=len(df)
realizadas=((df["status"]=="approved")|(df["status"]=="partial")).sum()
otd=round(realizadas/total_ent*100,1) if total_ent else 0
otif_si=(df["otif"]=="Si").sum()
otif_pct=round(otif_si/total_ent*100,1) if total_ent else 0
rechazos=(df["status"]=="rejected").sum()
parciales=(df["status"]=="partial").sum()
total_bultos=int(df["units_1"].sum())
total_venta=int(df["units_2"].sum())
vehiculos_u=df.drop_duplicates("vehicle_code")
sin_iniciar=((vehiculos_u["route_is_started"]==False)&(vehiculos_u["route_is_finished"]==False)).sum()
started=df.dropna(subset=["route_started_at"]).drop_duplicates("vehicle_code")
if not started.empty:
    def _tcm(s):
        try:
            dt=pd.to_datetime(s);
            if dt.tzinfo is None: dt=dt.tz_localize("UTC")
            c=dt.astimezone(TZ_CHILE); return c.hour*60+c.minute
        except: return None
    mins=started["route_started_at"].apply(_tcm).dropna()
    hr_prom=f"{int(mins.mean())//60:02d}:{int(mins.mean())%60:02d}" if not mins.empty else "-"
else: hr_prom="-"

# ════════════════════════════════════════════════════════════
# PAGE: INICIO
# ════════════════════════════════════════════════════════════
if page=="🏠 Inicio":
    st.markdown(f'<h2 style="color:{BIMBO_BLUE}">🏠 Dashboard Operacional — {start_d.strftime("%d/%m/%Y")}</h2>',unsafe_allow_html=True)
    k1,k2,k3,k4=st.columns(4)
    k1.metric("📦 Entregas",f"{total_ent:,}")
    k2.metric("🚚 OTD",f"{otd}%")
    k3.metric("✅ OTIF",f"{otif_pct}%")
    k4.metric("🕐 Hr Prom. Inicio",hr_prom)
    k5,k6,k7,k8=st.columns(4)
    k5.metric("❌ Rechazos",rechazos)
    k6.metric("⚠️ Parciales",parciales)
    k7.metric("📦 Bultos",f"{total_bultos:,}")
    k8.metric("💰 Venta Total",f"${total_venta:,}")

    st.divider()
    st.markdown(f'<div class="section-title">🔔 Alertas del Día</div>',unsafe_allow_html=True)

    # Alerta: rutas sin iniciar pasadas las 7AM
    if NOW_CHILE.hour>=ALERTA_HR_INICIO and sin_iniciar>0:
        st.markdown(f'<div class="alerta-box">🔴 {sin_iniciar} ruta(s) sin iniciar (ya pasaron las {ALERTA_HR_INICIO}:00 AM) de {len(vehiculos_u)} vehículos</div>',unsafe_allow_html=True)
    elif sin_iniciar>0:
        st.markdown(f'<div class="alerta-yellow">⚠️ {sin_iniciar} ruta(s) sin iniciar de {len(vehiculos_u)} vehículos</div>',unsafe_allow_html=True)

    # Alerta: camiones con más de 90 min en sala
    en_sala_larga=df[(df["tracked_service_time"].notna())&(df["tracked_service_time"]>ALERTA_MIN_SALA)&(~df["status"].isin(["approved","rejected","partial"]))].drop_duplicates(["vehicle_code","address_code"])
    if not en_sala_larga.empty:
        st.markdown(f'<div class="alerta-box">⏱️ {len(en_sala_larga)} camión(es) con más de {ALERTA_MIN_SALA} min en sala:</div>',unsafe_allow_html=True)
        for _,r in en_sala_larga.iterrows():
            st.markdown(f"&nbsp;&nbsp;&nbsp;🚛 **{r['vehicle_code']}** → Sala {r['address_code']} ({r['address_name'][:25]}) — **{int(r['tracked_service_time'])} min**")

    # Alerta: salas con rechazos
    rech_df=df[df["status"]=="rejected"]
    if not rech_df.empty:
        st.markdown(f'<div class="alerta-yellow">❌ {len(rech_df)} rechazo(s) del día:</div>',unsafe_allow_html=True)
        for _,r in rech_df.iterrows():
            st.markdown(f"&nbsp;&nbsp;&nbsp;Sala {r['address_code']} ({r['address_name'][:25]}) — Motivo: {r['reason']}")

    # Alerta: segunda vuelta con Max Cube < 50%
    fletes,caps=load_vehicle_info()
    df_2da=df[df["trip_number"]==2].copy()
    if not df_2da.empty:
        v2=df_2da.groupby("vehicle_code").agg(bultos=("units_1","sum")).reset_index()
        v2["cap"]=v2["vehicle_code"].map(caps).fillna(0)
        v2["mc"]=v2.apply(lambda r:round(r["bultos"]/r["cap"]*100) if r["cap"]>0 else 0,axis=1)
        low_mc=v2[v2["mc"]<50]
        if not low_mc.empty:
            st.markdown(f'<div class="alerta-yellow">📦 {len(low_mc)} segunda(s) vuelta con Max Cube &lt; 50%:</div>',unsafe_allow_html=True)
            for _,r in low_mc.iterrows():
                st.markdown(f"&nbsp;&nbsp;&nbsp;🚛 **{r['vehicle_code']}** — {r['bultos']} bultos / {int(r['cap'])} cap. = **{r['mc']}%**")

    # Alerta: operadores con CxS sobre promedio
    if fletes:
        df_cxs_a=df.copy(); df_cxs_a["flete"]=df_cxs_a["vehicle_code"].map(fletes).fillna(0)
        op_a=df_cxs_a.groupby("employer_name").agg(v=("units_2","sum"),f=("flete","sum")).reset_index()
        op_a=op_a[op_a["employer_name"]!="-"]
        op_a["cxs"]=op_a.apply(lambda r:round(r["f"]/r["v"]*100,2) if r["v"]>0 else 0,axis=1)
        avg_cxs=op_a["cxs"].mean()
        high_cxs=op_a[op_a["cxs"]>avg_cxs*1.2]  # 20% above average
        if not high_cxs.empty and avg_cxs>0:
            st.markdown(f'<div class="alerta-blue">💰 Operadores con CxS sobre promedio ({round(avg_cxs,2)}%):</div>',unsafe_allow_html=True)
            for _,r in high_cxs.iterrows():
                st.markdown(f"&nbsp;&nbsp;&nbsp;**{r['employer_name']}** — CxS: **{r['cxs']}%**")

    if sin_iniciar==0 and en_sala_larga.empty and rech_df.empty:
        st.success("✅ Sin alertas por el momento")

# ════════════════════════════════════════════════════════════
# PAGE: MONITOREO FLOTA
# ════════════════════════════════════════════════════════════
elif page=="🚗 Monitoreo Flota":
    st.markdown(f'<h2 style="color:{BIMBO_BLUE}">🚗 Monitoreo de Flota</h2>',unsafe_allow_html=True)
    ub=ubicacion_vehiculos(df)
    dv=df.drop_duplicates("vehicle_code").copy()
    dv["estado"]=dv.apply(lambda r:"Finalizada" if r["route_is_finished"] else("En ruta" if r["route_is_started"] else "Sin iniciar"),axis=1)
    dv["ubicacion"]=dv["vehicle_code"].map(ub).fillna("-")
    dv["hr_inicio"]=dv["route_started_at"].apply(parse_hour_chile)
    dv["hr_fin"]=dv["route_finished_at"].apply(parse_hour_chile)
    # Filters
    if f_op!="Todos": dv=dv[dv["employer_name"]==f_op]
    if f_estado!="Todos": dv=dv[dv["estado"]==f_estado]
    # KPIs
    c1,c2,c3,c4=st.columns(4)
    c1.metric("🚛 Vehículos",len(dv))
    c2.metric("✅ Finalizadas",(dv["estado"]=="Finalizada").sum())
    c3.metric("🔵 En ruta",(dv["estado"]=="En ruta").sum())
    c4.metric("🔴 Sin iniciar",(dv["estado"]=="Sin iniciar").sum())
    ds=dv[["vehicle_code","driver_name","employer_name","schema_name","estado","ubicacion","hr_inicio","hr_fin"]].copy()
    ds.columns=["Vehículo","Conductor","Operador","Centro","Estado","Ubicación Actual","Inicio","Fin"]
    st.dataframe(ds.sort_values("Estado").style.map(color_estado,subset=["Estado"]).map(color_ubicacion,subset=["Ubicación Actual"]),use_container_width=True,hide_index=True,height=600)

# ════════════════════════════════════════════════════════════
# PAGE: STATUS ENTREGAS
# ════════════════════════════════════════════════════════════
elif page=="📦 Status Entregas":
    st.markdown(f'<h2 style="color:{BIMBO_BLUE}">📦 Status de Entregas</h2>',unsafe_allow_html=True)
    df_e=df.copy()
    # Smart sala filter: show sala + all salas from same vehicle
    if f_sala!="— Todas —":
        vehs_sala=df_e[df_e["address_code"]==f_sala]["vehicle_code"].unique()
        df_e=df_e[df_e["vehicle_code"].isin(vehs_sala)]
        st.info(f"Mostrando sala {f_sala} + todas las salas de su(s) camión(es): {', '.join(vehs_sala)}")
    if f_veh!="Todos": df_e=df_e[df_e["vehicle_code"]==f_veh]
    if f_op2!="Todos": df_e=df_e[df_e["employer_name"]==f_op2]
    if f_motivo!="Todos": df_e=df_e[df_e["reason"]==f_motivo]
    df_e["ubicacion"]=ubicacion_por_sala(df_e)
    # KPIs
    c1,c2,c3,c4=st.columns(4)
    c1.metric("📦 Entregas",len(df_e))
    otd_e=round(((df_e["status"]=="approved")|(df_e["status"]=="partial")).sum()/len(df_e)*100,1) if len(df_e) else 0
    c2.metric("🚚 OTD",f"{otd_e}%")
    c3.metric("📦 Bultos",f"{int(df_e['units_1'].sum()):,}")
    c4.metric("💰 Venta",f"${int(df_e['units_2'].sum()):,}")
    ds=df_e[["address_code","address_name","vehicle_code","driver_name","employer_name","ubicacion","tipo_viaje","units_1","units_2","status_display","reason","otif","near_pod","tracked_service_time","espera_total_sala","visitas_gps"]].copy()
    ds.columns=["Código","Sala","Vehículo","Conductor","Operador","Ubicación","Viaje","Bultos","Venta Total","Status","Motivo","OTIF","Near POD","Espera Última","Espera Total","Pasadas"]
    for c in ["Espera Última","Espera Total"]: ds[c]=ds[c].apply(lambda x:int(x) if pd.notna(x) and str(x) not in("-","") else "-")
    ds["Pasadas"]=ds["Pasadas"].apply(lambda x:int(x) if pd.notna(x) and str(x) not in("-","") else 1)
    ds["Venta Total"]=ds["Venta Total"].apply(lambda x:f"${x:,}" if x>0 else "-")
    ds=ds.fillna("-")
    st.dataframe(ds.style.map(color_status,subset=["Status"]).map(color_ubicacion,subset=["Ubicación"]).map(color_vuelta,subset=["Viaje"]),use_container_width=True,hide_index=True,height=600)
    # Motivos chart
    rd=df_e[df_e["reason"]!="-"]["reason"].value_counts().reset_index(); rd.columns=["Motivo","Cantidad"]
    if not rd.empty:
        st.markdown('<div class="section-title">📊 Distribución de motivos</div>',unsafe_allow_html=True)
        fig=px.bar(rd,x="Cantidad",y="Motivo",orientation="h",text="Cantidad",color="Cantidad",color_continuous_scale=[[0,BIMBO_CELESTE],[1,BIMBO_BLUE]])
        fig.update_layout(**PLOTLY_BASE,height=300,showlegend=False); fig.update_traces(textposition="outside"); fig.update_coloraxes(showscale=False)
        st.plotly_chart(fig,use_container_width=True)

# ════════════════════════════════════════════════════════════
# PAGE: RANKING SALAS
# ════════════════════════════════════════════════════════════
elif page=="🏆 Ranking Salas":
    st.markdown(f'<h2 style="color:{BIMBO_BLUE}">🏆 Ranking Salas — Tiempo de Espera GPS</h2>',unsafe_allow_html=True)
    dt=df[df["espera_total_sala"].notna()&(df["espera_total_sala"]>0)].copy()
    if dt.empty: st.info("Sin datos de espera GPS.")
    else:
        dd=dt.drop_duplicates(["address_code","planned_date"])[["address_code","address_name","planned_date","espera_max_sala","espera_total_sala","visitas_gps"]]
        sa=dd.groupby(["address_code","address_name"]).agg(total=("espera_total_sala","max"),mayor=("espera_max_sala","max"),pasadas=("visitas_gps","max")).reset_index().sort_values("total",ascending=False).head(15)
        sa["total"]=sa["total"].astype(int); sa["mayor"]=sa["mayor"].astype(int); sa["pasadas"]=sa["pasadas"].astype(int)
        fig=px.bar(sa,x="total",y="address_name",orientation="h",text="total",color="total",color_continuous_scale=[[0,BIMBO_CELESTE],[.5,BIMBO_BLUE],[1,BIMBO_RED]],labels={"total":"Espera Total (min)","address_name":"Sala"})
        fig.update_layout(**PLOTLY_BASE,height=450,showlegend=False,yaxis=dict(autorange="reversed")); fig.update_traces(textposition="outside"); fig.update_coloraxes(showscale=False)
        st.plotly_chart(fig,use_container_width=True)
        ss=sa[["address_code","address_name","total","mayor","pasadas"]].copy(); ss.columns=["Código","Sala","Espera Total","Espera Mayor","Pasadas GPS"]
        st.dataframe(ss,use_container_width=True,hide_index=True)

# ════════════════════════════════════════════════════════════
# PAGE: TENDENCIAS
# ════════════════════════════════════════════════════════════
elif page=="📈 Tendencias":
    st.markdown(f'<h2 style="color:{BIMBO_BLUE}">📈 Tendencias</h2>',unsafe_allow_html=True)
    dt=df.copy(); dt["fecha"]=pd.to_datetime(dt["planned_date"])
    bd=dt.groupby("fecha")["units_1"].sum().reset_index(); bd.columns=["Fecha","Bultos"]
    od=dt.groupby("fecha").apply(lambda x:round((x["otif"]=="Si").sum()/len(x)*100,1) if len(x) else 0).reset_index(); od.columns=["Fecha","OTIF %"]
    td=dt.groupby("fecha").apply(lambda x:round(((x["status"]=="approved")|(x["status"]=="partial")).sum()/len(x)*100,1) if len(x) else 0).reset_index(); td.columns=["Fecha","OTD %"]
    fig=go.Figure(data=[
        go.Scatter(x=bd["Fecha"],y=bd["Bultos"],name="Bultos",mode="lines+markers",line=dict(color=BIMBO_CELESTE,width=3),marker=dict(size=8)),
        go.Scatter(x=td["Fecha"],y=td["OTD %"],name="OTD %",mode="lines+markers",line=dict(color=BIMBO_BLUE,width=3),marker=dict(size=8),yaxis="y2"),
        go.Scatter(x=od["Fecha"],y=od["OTIF %"],name="OTIF %",mode="lines+markers",line=dict(color=BIMBO_GREEN,width=3),marker=dict(size=8),yaxis="y2"),
    ])
    fig.update_layout(template="plotly_white",paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(255,255,255,1)",
        font=dict(color="#1a1a2e",size=12),height=400,margin=dict(l=60,r=60,t=30,b=40),
        xaxis=dict(dtick="D1",tickformat="%d/%m/%Y"),
        legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1))
    fig.update_layout(yaxis=dict(title=dict(text="Bultos",font=dict(color=BIMBO_CELESTE)),tickfont=dict(color=BIMBO_CELESTE),side="left"))
    fig.update_layout(yaxis2=dict(title=dict(text="OTD / OTIF %",font=dict(color=BIMBO_BLUE)),tickfont=dict(color=BIMBO_BLUE),side="right",overlaying="y",range=[0,100]))
    st.plotly_chart(fig,use_container_width=True)
    st.markdown('<div class="section-title">🏭 Entregas por Centro</div>',unsafe_allow_html=True)
    ec=df.groupby("schema_name").agg(ent=("order_code","count"),otd=("status",lambda x:round(((x=="approved")|(x=="partial")).sum()/len(x)*100,1)),otif=("otif",lambda x:round((x=="Si").sum()/len(x)*100,1)),bul=("units_1","sum"),ven=("units_2","sum")).reset_index().sort_values("ent",ascending=False)
    ec["bul"]=ec["bul"].astype(int); ec["ven"]=ec["ven"].apply(lambda x:f"${int(x):,}")
    ec.columns=["Centro","Entregas","OTD %","OTIF %","Bultos","Venta"]
    st.dataframe(ec,use_container_width=True,hide_index=True)

# ════════════════════════════════════════════════════════════
# PAGE: CxS POR CAMIÓN
# ════════════════════════════════════════════════════════════
elif page=="💰 CxS por Camión":
    st.markdown(f'<h2 style="color:{BIMBO_BLUE}">💰 Costo por Servir (CxS)</h2>',unsafe_allow_html=True)
    fletes,caps=load_vehicle_info()
    dc=df.copy(); dc["flete"]=dc["vehicle_code"].map(fletes).fillna(0).astype(int); dc["capacidad"]=dc["vehicle_code"].map(caps).fillna(0).astype(int)
    va=dc.groupby(["vehicle_code","trip_number"]).agg(conductor=("driver_name","first"),operador=("employer_name","first"),centro=("schema_name","first"),salas=("address_code","nunique"),bultos=("units_1","sum"),venta=("units_2","sum"),flete=("flete","max"),capacidad=("capacidad","max")).reset_index()
    va["tipo_viaje"]=va["trip_number"].apply(lambda x:"Primera vuelta" if x==1 else "Segunda vuelta")
    va["max_cube"]=va.apply(lambda r:round(r["bultos"]/r["capacidad"]*100) if r["capacidad"]>0 else 0,axis=1)
    va["cxs_pct"]=va.apply(lambda r:round(r["flete"]/r["venta"]*100,2) if r["venta"]>0 else 0,axis=1)
    # Filters
    if f_op3!="Todos": va=va[va["operador"]==f_op3]
    if f_vuelta!="Todas": va=va[va["tipo_viaje"]==f_vuelta]
    va=va.sort_values("cxs_pct",ascending=False)
    tf=int(va["flete"].sum()); tv=int(va["venta"].sum())
    cg=round(tf/tv*100,2) if tv else 0; amc=round(va["max_cube"].mean()) if not va.empty else 0
    c1,c2,c3,c4,c5,c6=st.columns(6)
    c1.metric("💰 CxS Global",f"{cg}%"); c2.metric("📦 Max Cube Prom.",f"{amc}%"); c3.metric("🚛 Camiones",va["vehicle_code"].nunique())
    c4.metric("🔄 Viajes",len(va)); c5.metric("⚠️ 2das Vueltas",int((va["trip_number"]==2).sum())); c6.metric("📦 Flete Total",f"${tf:,}")
    sf=(va["flete"]==0).sum()
    if sf>0: st.markdown(f'<div class="alerta-yellow">⚠️ {sf} viaje(s) sin flete configurado</div>',unsafe_allow_html=True)
    st.divider()
    vs=va[["vehicle_code","conductor","operador","centro","tipo_viaje","salas","bultos","max_cube","venta","flete","cxs_pct"]].copy()
    vs["bultos"]=vs["bultos"].astype(int); vs["max_cube"]=vs["max_cube"].apply(lambda x:f"{x}%"); vs["venta"]=vs["venta"].apply(lambda x:f"${int(x):,}")
    vs["flete"]=vs["flete"].apply(lambda x:f"${int(x):,}" if x>0 else "Sin flete"); vs["cxs_pct"]=vs["cxs_pct"].apply(lambda x:f"{x}%")
    vs.columns=["Vehículo","Conductor","Operador","Centro","Vuelta","Salas","Bultos","Max Cube","Venta","Flete","CxS %"]
    st.dataframe(vs.style.map(color_vuelta,subset=["Vuelta"]).map(color_cxs,subset=["CxS %"]).map(color_maxcube,subset=["Max Cube"]),use_container_width=True,hide_index=True,height=600)
    st.divider()
    st.markdown('<div class="section-title">📊 Resumen del Día</div>',unsafe_allow_html=True)
    r1,r2,r3=st.columns(3); r1.metric("Venta Total",f"${tv:,}"); r2.metric("Flete Total",f"${tf:,}"); r3.metric("CxS Total",f"{cg}%")
    st.markdown('<div class="section-title">🏭 CxS por Operador</div>',unsafe_allow_html=True)
    oa=va.groupby("operador").agg(cam=("vehicle_code","nunique"),viajes=("vehicle_code","count"),venta=("venta","sum"),flete=("flete","sum")).reset_index()
    oa["cxs"]=oa.apply(lambda r:round(r["flete"]/r["venta"]*100,2) if r["venta"]>0 else 0,axis=1)
    oa["venta"]=oa["venta"].apply(lambda x:f"${int(x):,}"); oa["flete"]=oa["flete"].apply(lambda x:f"${int(x):,}"); oa["cxs"]=oa["cxs"].apply(lambda x:f"{x}%")
    oa.columns=["Operador","Camiones","Viajes","Venta","Flete","CxS %"]
    st.dataframe(oa,use_container_width=True,hide_index=True)

# ════════════════════════════════════════════════════════════
# PAGE: RENDIMIENTO OPERADOR
# ════════════════════════════════════════════════════════════
elif page=="📊 Rendimiento Operador":
    st.markdown(f'<h2 style="color:{BIMBO_BLUE}">📊 Rendimiento por Operador Logístico</h2>',unsafe_allow_html=True)
    fletes,caps=load_vehicle_info()
    dr=df.copy(); dr["flete"]=dr["vehicle_code"].map(fletes).fillna(0).astype(int); dr["capacidad"]=dr["vehicle_code"].map(caps).fillna(0).astype(int)
    if f_op4!="Todos": dr=dr[dr["employer_name"]==f_op4]
    ops=dr[dr["employer_name"]!="-"].groupby("employer_name")
    rows=[]
    for op,g in ops:
        n_cam=g["vehicle_code"].nunique(); n_ent=len(g); n_bul=int(g["units_1"].sum()); n_ven=int(g["units_2"].sum())
        n_rech=(g["status"]=="rejected").sum()
        otd_o=round(((g["status"]=="approved")|(g["status"]=="partial")).sum()/n_ent*100,1) if n_ent else 0
        otif_o=round((g["otif"]=="Si").sum()/n_ent*100,1) if n_ent else 0
        flete_t=int(g.drop_duplicates(["vehicle_code","trip_number"])["flete"].sum())
        cxs_o=round(flete_t/n_ven*100,2) if n_ven else 0
        vg=g.groupby(["vehicle_code","trip_number"]).agg(bul=("units_1","sum"),cap=("capacidad","max")).reset_index()
        vg["mc"]=vg.apply(lambda r:round(r["bul"]/r["cap"]*100) if r["cap"]>0 else 0,axis=1)
        mc_avg=round(vg["mc"].mean()) if not vg.empty else 0
        rows.append({"Operador":op,"Camiones":n_cam,"Entregas":n_ent,"OTD %":otd_o,"OTIF %":otif_o,"Rechazos":n_rech,"Bultos":n_bul,"Venta":n_ven,"Flete":flete_t,"CxS %":cxs_o,"Max Cube %":mc_avg})
    if rows:
        ro=pd.DataFrame(rows).sort_values("CxS %",ascending=False)
        # KPIs
        c1,c2,c3,c4=st.columns(4)
        c1.metric("🚚 Operadores",len(ro)); c2.metric("🚛 Camiones Total",int(ro["Camiones"].sum()))
        c3.metric("📦 Entregas Total",int(ro["Entregas"].sum())); c4.metric("❌ Rechazos Total",int(ro["Rechazos"].sum()))
        st.divider()
        # Format
        ro_d=ro.copy(); ro_d["Venta"]=ro_d["Venta"].apply(lambda x:f"${x:,}"); ro_d["Flete"]=ro_d["Flete"].apply(lambda x:f"${x:,}")
        ro_d["OTD %"]=ro_d["OTD %"].apply(lambda x:f"{x}%"); ro_d["OTIF %"]=ro_d["OTIF %"].apply(lambda x:f"{x}%")
        ro_d["CxS %"]=ro_d["CxS %"].apply(lambda x:f"{x}%"); ro_d["Max Cube %"]=ro_d["Max Cube %"].apply(lambda x:f"{x}%")
        st.dataframe(ro_d.style.map(color_cxs,subset=["CxS %"]).map(color_maxcube,subset=["Max Cube %"]),use_container_width=True,hide_index=True)
        # Charts
        st.markdown('<div class="section-title">📊 Comparativa OTD / OTIF</div>',unsafe_allow_html=True)
        fig=go.Figure(data=[
            go.Bar(name="OTD %",x=ro["Operador"],y=ro["OTD %"],marker_color=BIMBO_BLUE,text=ro["OTD %"],textposition="outside"),
            go.Bar(name="OTIF %",x=ro["Operador"],y=ro["OTIF %"],marker_color=BIMBO_CELESTE,text=ro["OTIF %"],textposition="outside"),
        ])
        fig.update_layout(**PLOTLY_BASE,height=350,barmode="group",legend=dict(orientation="h",yanchor="bottom",y=1.02))
        st.plotly_chart(fig,use_container_width=True)
    else: st.info("Sin datos de operadores.")

# ── Footer ──────────────────────────────────────────────────
st.divider()
st.caption(f"Dashboard Drivin · {start_d.strftime('%d/%m/%Y')} al {end_d.strftime('%d/%m/%Y')} · {total_ent} entregas")
