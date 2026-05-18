"""
Dashboard Operacional Drivin — Bimbo Ideal
==========================================
Tema claro · Paleta Bimbo (azul/celeste/blanco)
Zona horaria: America/Santiago
Auto-refresh cada 10 minutos
"""

import os
import json
import sqlite3
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from streamlit_autorefresh import st_autorefresh
from pathlib import Path

# ── Zona horaria Chile ──────────────────────────────────────
TZ_CHILE = ZoneInfo("America/Santiago")
NOW_CHILE = datetime.now(TZ_CHILE)

# ── Page Config ─────────────────────────────────────────────
st.set_page_config(
    page_title="Drivin Dashboard — Bimbo Ideal",
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Auto-refresh cada 10 minutos
st_autorefresh(interval=600_000, key="data_refresh")

# ── Traducciones y mapeos ───────────────────────────────────
STATUS_MAP = {
    "approved": "Aprobado",
    "rejected": "Rechazado",
    "partial": "Parcial",
    "pending": "Pendiente",
}

def translate_status(val):
    if pd.isna(val) or val is None or val == "":
        return "-"
    return STATUS_MAP.get(str(val).lower(), str(val))

def clean_none(val):
    if pd.isna(val) or val is None or str(val).strip().lower() in ("none", "nan", ""):
        return "-"
    return val

def format_bultos(val):
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0

# ── Estilos CSS — Tema Claro Bimbo ──────────────────────────
st.markdown("""
<style>
    .stApp, .main, [data-testid="stAppViewContainer"] {
        background-color: #ffffff !important;
        color: #1a1a2e !important;
    }
    section[data-testid="stSidebar"] {
        background-color: #f0f4f8 !important;
    }
    .main-header {
        font-size: 1.7rem;
        font-weight: 800;
        color: #003087;
        margin-bottom: 2px;
        letter-spacing: -0.3px;
    }
    .sub-header {
        font-size: 0.88rem;
        color: #5a6a7e;
        margin-bottom: 1.2rem;
    }
    div[data-testid="metric-container"] {
        background: linear-gradient(135deg, #f7faff 0%, #edf2fa 100%);
        border: 1px solid #cdd9e5;
        border-radius: 12px;
        padding: 16px 18px;
        box-shadow: 0 1px 4px rgba(0,48,135,0.06);
    }
    div[data-testid="metric-container"] label {
        color: #5a6a7e !important;
        font-size: 0.82rem !important;
        font-weight: 600 !important;
        text-transform: uppercase;
        letter-spacing: 0.4px;
    }
    div[data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
        font-weight: 800 !important;
        color: #003087 !important;
    }
    .alerta-box {
        background: linear-gradient(135deg, #fff5f5 0%, #fee2e2 100%);
        border: 1px solid #f87171;
        border-radius: 10px;
        padding: 12px 18px;
        color: #b91c1c;
        font-weight: 600;
        margin-bottom: 1rem;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
        border-bottom: 2px solid #e2e8f0;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        color: #5a6a7e;
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        color: #003087 !important;
        border-bottom: 3px solid #003087 !important;
    }
    .stDataFrame thead tr th {
        background-color: #003087 !important;
        color: #ffffff !important;
        font-weight: 700 !important;
        text-align: center !important;
    }
    .stDataFrame tbody tr:nth-child(even) {
        background-color: #f7faff;
    }
    div[data-baseweb="select"] > div {
        border-color: #cdd9e5 !important;
        background-color: #f7faff !important;
        color: #1a1a2e !important;
    }
    hr {
        border-color: #e2e8f0 !important;
    }
    .section-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #003087;
        margin-bottom: 0.5rem;
        padding-bottom: 4px;
        border-bottom: 2px solid #38bdf8;
        display: inline-block;
    }
</style>
""", unsafe_allow_html=True)


# ── Plotly theme ────────────────────────────────────────────
PLOTLY_LAYOUT = dict(
    template="plotly_white",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(255,255,255,1)",
    font=dict(color="#1a1a2e", size=12),
    margin=dict(l=10, r=10, t=30, b=10),
    colorway=["#003087", "#38bdf8", "#0ea5e9", "#7dd3fc", "#0369a1", "#bae6fd"],
)

BIMBO_BLUE = "#003087"
BIMBO_CELESTE = "#38bdf8"
BIMBO_GREEN = "#16a34a"
BIMBO_RED = "#dc2626"


# ── Snapshot system for GPS wait times ──────────────────────
DB_PATH = "espera_historica.db"


def init_db():
    """Inicializa SQLite para guardar histórico de esperas GPS."""
    conn = sqlite3.connect(DB_PATH)
    # Eliminar tabla vieja con estructura incorrecta (si existe)
    conn.execute("DROP TABLE IF EXISTS espera_snapshots")
    # Crear tabla con estructura correcta
    conn.execute("""
        CREATE TABLE IF NOT EXISTS espera_visitas (
            address_code TEXT,
            planned_date TEXT,
            tracked_arrival TEXT,
            tracked_service_time REAL,
            tracked_leave TEXT,
            snapshot_at TEXT,
            PRIMARY KEY (address_code, planned_date, tracked_arrival)
        )
    """)
    conn.commit()
    conn.close()


def save_espera_snapshot(records: list):
    """Guarda snapshot usando tracked_arrival como ID de visita.
    
    Lógica:
    - Mismo tracked_arrival = misma visita → actualiza con MAX(tracked_service_time)
    - Diferente tracked_arrival = nueva visita → inserta nuevo registro
    """
    conn = sqlite3.connect(DB_PATH)
    for r in records:
        tst = r.get("tracked_service_time")
        ta = r.get("tracked_arrival")
        if tst and tst > 0 and ta:
            try:
                # Verificar si ya existe esta visita
                existing = conn.execute("""
                    SELECT tracked_service_time FROM espera_visitas
                    WHERE address_code = ? AND planned_date = ? AND tracked_arrival = ?
                """, (r.get("address_code"), r.get("planned_date"), ta)).fetchone()

                if existing:
                    # Misma visita: actualizar solo si el nuevo tst es mayor
                    if tst > existing[0]:
                        conn.execute("""
                            UPDATE espera_visitas
                            SET tracked_service_time = ?, tracked_leave = ?, snapshot_at = ?
                            WHERE address_code = ? AND planned_date = ? AND tracked_arrival = ?
                        """, (tst, r.get("tracked_leave"),
                              datetime.now(TZ_CHILE).isoformat(),
                              r.get("address_code"), r.get("planned_date"), ta))
                else:
                    # Nueva visita (tracked_arrival distinto)
                    conn.execute("""
                        INSERT INTO espera_visitas
                        (address_code, planned_date, tracked_arrival, tracked_service_time, tracked_leave, snapshot_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (r.get("address_code"), r.get("planned_date"), ta,
                          tst, r.get("tracked_leave"),
                          datetime.now(TZ_CHILE).isoformat()))
            except Exception:
                pass
    conn.commit()
    conn.close()


def get_espera_historica(planned_dates: list) -> dict:
    """Obtiene por sala+día: suma de max por visita, max individual, y cantidad de visitas."""
    conn = sqlite3.connect(DB_PATH)
    result = {}
    try:
        placeholders = ",".join(["?"] * len(planned_dates))
        rows = conn.execute(f"""
            SELECT address_code, planned_date,
                   SUM(tracked_service_time) as total_espera,
                   MAX(tracked_service_time) as max_espera,
                   COUNT(*) as n_visitas
            FROM espera_visitas
            WHERE planned_date IN ({placeholders})
            GROUP BY address_code, planned_date
        """, planned_dates).fetchall()
        for row in rows:
            result[(row[0], row[1])] = {
                "total": row[2],
                "max": row[3],
                "visitas": row[4],
            }
    except Exception:
        pass
    conn.close()
    return result


# ── Data Loading ────────────────────────────────────────────
@st.cache_data(ttl=600)
def load_data_from_api(start_date: str, end_date: str) -> pd.DataFrame:
    import requests

    api_key = os.environ.get("DRIVIN_API_KEY", "")
    if not api_key:
        try:
            api_key = st.secrets["DRIVIN_API_KEY"]
        except Exception:
            return pd.DataFrame()

    url = "https://external.driv.in/api/external/v2/pods"
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    params = {"start_date": start_date, "end_date": end_date}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        records = resp.json().get("response", [])
    except Exception as e:
        st.error(f"Error al consultar API: {e}")
        return pd.DataFrame()

    if not records:
        return pd.DataFrame()

    # Guardar snapshot de esperas GPS (preserva valores antes de sobreescritura)
    try:
        init_db()
        save_espera_snapshot(records)
    except Exception:
        pass

    rows = []
    for r in records:
        base = {
            "planned_date": r.get("planned_date"),
            "vehicle_code": r.get("vehicle_code"),
            "schema_name": r.get("schema_name"),
            "fleet_name": r.get("fleet_name"),
            "route_is_started": r.get("route_is_started"),
            "route_is_finished": r.get("route_is_finished"),
            "route_started_at": r.get("route_started_at"),
            "route_finished_at": r.get("route_finished_at"),
            "driver_name": (r.get("driver_name") or "").strip(),
            "employer_name": r.get("employer_name"),
            "address_name": r.get("address_name"),
            "address_code": r.get("address_code"),
            "address_city": r.get("address_city"),
            "tracked_arrival": r.get("tracked_arrival"),
            "tracked_leave": r.get("tracked_leave"),
            "tracked_service_time": r.get("tracked_service_time"),
            "visit_arrival": r.get("visit_arrival"),
            "visit_leave": r.get("visit_leave"),
            "trip_number": r.get("trip_number"),
            "route_code": r.get("route_code"),
            "time_window_start": (r.get("time_window") or {}).get("start"),
            "time_window_end": (r.get("time_window") or {}).get("end"),
        }
        for o in r.get("orders", []):
            rows.append({
                **base,
                "order_code": o.get("code"),
                "status": o.get("status"),
                "reason": o.get("reason"),
                "otif": o.get("otif"),
                "near_pod": o.get("near_pod"),
                "units_1": o.get("units_1") or 0,
                "units_2": o.get("units_2") or 0,
                "client_name": o.get("client_name"),
                "tags": json.dumps(o.get("tags", [])),
                "pod_arrival": o.get("pod_arrival"),
            })

    df = pd.DataFrame(rows)
    df["units_1"] = df["units_1"].apply(format_bultos)
    df["units_2"] = df["units_2"].apply(lambda x: int(float(x)) if pd.notna(x) and x != 0 else 0)
    df["status_display"] = df["status"].apply(translate_status)
    df["tipo_viaje"] = df["trip_number"].apply(
        lambda x: "Primera vuelta" if x == 1 else ("Segunda vuelta" if x == 2 else "-"))
    for col in ["reason", "near_pod", "client_name", "driver_name", "address_city", "employer_name"]:
        if col in df.columns:
            df[col] = df[col].apply(clean_none)

    # Calcular tiempo de servicio propio desde tracked_arrival/leave (respaldo)
    if "tracked_arrival" in df.columns and "tracked_leave" in df.columns:
        df["_arrival"] = pd.to_datetime(df["tracked_arrival"], errors="coerce")
        df["_leave"] = pd.to_datetime(df["tracked_leave"], errors="coerce")
        df["espera_calculada"] = ((df["_leave"] - df["_arrival"]).dt.total_seconds() / 60).round(0)
        df["espera_calculada"] = df["espera_calculada"].apply(
            lambda x: int(x) if pd.notna(x) and x > 0 else None)
        df.drop(columns=["_arrival", "_leave"], inplace=True)
    else:
        df["espera_calculada"] = None

    # Usar el mayor entre tracked_service_time y espera_calculada por fila
    df["espera_real"] = df[["tracked_service_time", "espera_calculada"]].max(axis=1)

    # Consultar histórico de esperas (captura visitas antes de sobreescritura API)
    try:
        planned_dates = df["planned_date"].dropna().unique().tolist()
        if planned_dates:
            historico = get_espera_historica(planned_dates)

            def get_hist_field(row, field):
                h = historico.get((row["address_code"], row["planned_date"]))
                return h[field] if h else None

            df["espera_hist_total"] = df.apply(lambda r: get_hist_field(r, "total"), axis=1)
            df["espera_hist_max"] = df.apply(lambda r: get_hist_field(r, "max"), axis=1)
            df["visitas_gps"] = df.apply(lambda r: get_hist_field(r, "visitas"), axis=1)

            # Espera total = suma de todas las visitas distintas (desde histórico)
            # Si no hay histórico, usar espera_real actual
            df["espera_total_sala"] = df["espera_hist_total"].combine_first(df["espera_real"])

            # Espera máxima = la visita individual más larga
            df["espera_max_sala"] = df[["espera_real", "espera_hist_max"]].max(axis=1)

            # Visitas: mínimo 1
            df["visitas_gps"] = df["visitas_gps"].fillna(1).astype(int)
        else:
            df["espera_total_sala"] = df["espera_real"]
            df["espera_max_sala"] = df["espera_real"]
            df["visitas_gps"] = 1
    except Exception:
        df["espera_total_sala"] = df["espera_real"]
        df["espera_max_sala"] = df["espera_real"]
        df["visitas_gps"] = 1

    # Aplicar max/sum por sala+día por si hay múltiples filas en el DataFrame
    if not df.empty:
        df["espera_max_sala"] = df.groupby(["address_code", "planned_date"])["espera_max_sala"].transform("max")
        df["espera_total_sala"] = df.groupby(["address_code", "planned_date"])["espera_total_sala"].transform("max")
        df["visitas_gps"] = df.groupby(["address_code", "planned_date"])["visitas_gps"].transform("max")

    return df


def parse_hour_chile(dt_str):
    if not dt_str or pd.isna(dt_str):
        return "-"
    try:
        dt = pd.to_datetime(dt_str)
        if dt.tzinfo is None:
            dt = dt.tz_localize("UTC")
        return dt.astimezone(TZ_CHILE).strftime("%H:%M")
    except Exception:
        return "-"


def color_status_light(val):
    if val == "Aprobado":
        return "background-color: #dcfce7; color: #166534"
    elif val == "Rechazado":
        return "background-color: #fee2e2; color: #991b1b"
    elif val in ("Parcial", "Pendiente"):
        return "background-color: #fef9c3; color: #854d0e"
    return ""


def color_tipo_viaje(val):
    if val == "Segunda vuelta":
        return "background-color: #fef9c3; color: #854d0e"
    return ""


# ── Header ──────────────────────────────────────────────────
hora_chile = NOW_CHILE.strftime("%d/%m/%Y %H:%M")
st.markdown('<div class="main-header">🚛 Dashboard Operacional Drivin — Bimbo Ideal</div>', unsafe_allow_html=True)
st.markdown(f'<div class="sub-header">Auto-refresh cada 10 min · Última actualización: {hora_chile}</div>', unsafe_allow_html=True)

# ── Filtros ─────────────────────────────────────────────────
col_f1, col_f2, col_f3 = st.columns([1, 1, 1])

with col_f1:
    today = NOW_CHILE.date()
    date_range = st.date_input(
        "📅 Rango de fechas",
        value=(today, today),
        max_value=today,
        min_value=today - timedelta(days=7),
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = end_date = today

df = load_data_from_api(start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))

if df.empty:
    st.warning("⚠️ No hay datos disponibles. Verifica tu API Key en Secrets de Streamlit Cloud.")
    st.info('Ve a **Settings → Secrets** y agrega:\n```\nDRIVIN_API_KEY = "tu_api_key"\n```')
    st.stop()

with col_f2:
    centros = ["Todos"] + sorted(df["schema_name"].dropna().unique().tolist())
    centro_sel = st.selectbox("🏭 Centro de venta", centros)

with col_f3:
    codigos_sala = ["— Sin filtro —"] + sorted(df["address_code"].dropna().unique().tolist())
    sala_sel = st.selectbox("🏪 Código sala (zoom detalle)", codigos_sala)

if centro_sel != "Todos":
    df = df[df["schema_name"] == centro_sel]

# ── KPIs ────────────────────────────────────────────────────
total_entregas = len(df)
entregas_realizadas = ((df["status"] == "approved") | (df["status"] == "partial")).sum()
otd_pct = round(entregas_realizadas / total_entregas * 100, 1) if total_entregas else 0
otif_si = (df["otif"] == "Si").sum()
otif_pct = round(otif_si / total_entregas * 100, 1) if total_entregas else 0
rechazos = (df["status"] == "rejected").sum()
parciales = (df["status"] == "partial").sum()
total_bultos = int(df["units_1"].sum())
total_venta = int(df["units_2"].sum())

vehiculos = df.drop_duplicates(subset=["vehicle_code"])
sin_iniciar = ((vehiculos["route_is_started"] == False) & (vehiculos["route_is_finished"] == False)).sum()

started_times = df.dropna(subset=["route_started_at"]).drop_duplicates("vehicle_code")
if not started_times.empty:
    def to_chile_minutes(dt_str):
        try:
            dt = pd.to_datetime(dt_str)
            if dt.tzinfo is None:
                dt = dt.tz_localize("UTC")
            dt_chile = dt.astimezone(TZ_CHILE)
            return dt_chile.hour * 60 + dt_chile.minute
        except Exception:
            return None
    mins = started_times["route_started_at"].apply(to_chile_minutes).dropna()
    if not mins.empty:
        avg_min = int(mins.mean())
        hr_prom = f"{avg_min // 60:02d}:{avg_min % 60:02d}"
    else:
        hr_prom = "-"
else:
    hr_prom = "-"

k1, k2, k3, k4, k5, k6, k7, k8 = st.columns(8)
k1.metric("📦 Entregas", f"{total_entregas:,}")
k2.metric("🚚 OTD", f"{otd_pct}%")
k3.metric("✅ OTIF", f"{otif_pct}%")
k4.metric("❌ Rechazos", rechazos)
k5.metric("⚠️ Parciales", parciales)
k6.metric("📦 Bultos", f"{total_bultos:,}")
k7.metric("💰 Venta Total", f"${total_venta:,}")
k8.metric("🕐 Hr Inicio", hr_prom)

if sin_iniciar > 0:
    st.markdown(
        f'<div class="alerta-box">⚠️ {sin_iniciar} ruta(s) sin iniciar de {len(vehiculos)} vehículos</div>',
        unsafe_allow_html=True,
    )

st.divider()

# ── Vista condicional ───────────────────────────────────────
if sala_sel != "— Sin filtro —":
    df_sala = df[df["address_code"] == sala_sel]

    if df_sala.empty:
        st.warning(f"No hay datos para la sala {sala_sel} en este rango de fechas.")
    else:
        nombre_sala = df_sala["address_name"].iloc[0]
        ciudad = df_sala["address_city"].iloc[0] if "address_city" in df_sala.columns else "-"

        st.markdown(f'<div class="section-title">🏪 Detalle Sala: {sala_sel} — {nombre_sala}</div>', unsafe_allow_html=True)
        if ciudad and ciudad != "-":
            st.caption(f"📍 {ciudad}")

        s1, s2, s3, s4, s5, s6, s7 = st.columns(7)
        total_sala = len(df_sala)
        realizadas_sala = ((df_sala["status"] == "approved") | (df_sala["status"] == "partial")).sum()
        otd_sala = round(realizadas_sala / total_sala * 100, 1) if total_sala else 0
        otif_sala = (df_sala["otif"] == "Si").sum()
        otif_pct_sala = round(otif_sala / total_sala * 100, 1) if total_sala else 0
        rechazos_sala = (df_sala["status"] == "rejected").sum()
        bultos_sala = int(df_sala["units_1"].sum())
        venta_sala = int(df_sala["units_2"].sum())
        espera_max_vals = df_sala["espera_max_sala"].dropna()
        espera_total_vals = df_sala["espera_total_sala"].dropna()
        max_espera_sala = int(espera_max_vals.max()) if not espera_max_vals.empty else 0
        total_espera_sala = int(espera_total_vals.max()) if not espera_total_vals.empty else 0

        s1.metric("Visitas", total_sala)
        s2.metric("OTD", f"{otd_sala}%")
        s3.metric("OTIF", f"{otif_pct_sala}%")
        s4.metric("Bultos", f"{bultos_sala:,}")
        s5.metric("Venta", f"${venta_sala:,}")
        s6.metric("Espera Mayor (min)", f"{max_espera_sala}")
        s7.metric("Espera Total (min)", f"{total_espera_sala}")

        st.markdown('<div class="section-title">📋 Historial de visitas</div>', unsafe_allow_html=True)

        df_show = df_sala[["planned_date", "driver_name", "employer_name", "vehicle_code", "tipo_viaje", "units_1",
                           "units_2", "status_display", "reason", "otif", "near_pod",
                           "tracked_service_time", "espera_max_sala", "espera_total_sala", "visitas_gps"]].copy()
        df_show.columns = ["Fecha", "Conductor", "Operador Logístico", "Vehículo", "Tipo Viaje", "Bultos",
                           "Venta Total", "Status", "Motivo", "OTIF", "Near POD",
                           "Espera Actual (min)", "Espera Mayor (min)", "Espera Total (min)", "Pasadas GPS"]
        for col_esp in ["Espera Actual (min)", "Espera Mayor (min)", "Espera Total (min)"]:
            df_show[col_esp] = df_show[col_esp].apply(
                lambda x: int(x) if pd.notna(x) and str(x) not in ("-", "") else "-")
        df_show["Pasadas GPS"] = df_show["Pasadas GPS"].apply(
            lambda x: int(x) if pd.notna(x) and str(x) not in ("-", "") else 1)
        df_show["Venta Total"] = df_show["Venta Total"].apply(lambda x: f"${x:,}" if x > 0 else "-")
        df_show = df_show.fillna("-")

        st.dataframe(
            df_show.style.map(color_status_light, subset=["Status"])
                         .map(color_tipo_viaje, subset=["Tipo Viaje"]),
            use_container_width=True,
            hide_index=True,
            height=400,
        )

        if not tiempos.empty:
            st.markdown('<div class="section-title">⏱️ Tiempo de espera GPS por visita</div>', unsafe_allow_html=True)
            df_chart = df_sala[["planned_date", "tracked_service_time", "driver_name"]].dropna(subset=["tracked_service_time"])
            fig = px.bar(
                df_chart, x="planned_date", y="tracked_service_time", color="driver_name",
                labels={"tracked_service_time": "Minutos", "planned_date": "Fecha", "driver_name": "Conductor"},
                color_discrete_sequence=[BIMBO_BLUE, BIMBO_CELESTE, "#0ea5e9", "#7dd3fc"],
            )
            fig.update_layout(**PLOTLY_LAYOUT, height=350)
            fig.update_xaxes(dtick="D1", tickformat="%d/%m")
            st.plotly_chart(fig, use_container_width=True)

else:
    tab1, tab2, tab3, tab4 = st.tabs([
        "🚗 Vehículos", "📦 Status Entregas", "🏆 Ranking Salas", "📈 Tendencias"
    ])

    with tab1:
        st.markdown('<div class="section-title">🚗 Estado de sesión por vehículo</div>', unsafe_allow_html=True)
        df_veh = df.drop_duplicates(subset=["vehicle_code"]).copy()
        df_veh["estado"] = df_veh.apply(
            lambda r: "Finalizada" if r["route_is_finished"]
            else ("En ruta" if r["route_is_started"] else "Sin iniciar"),
            axis=1,
        )
        df_veh["hr_inicio"] = df_veh["route_started_at"].apply(parse_hour_chile)
        df_veh["hr_fin"] = df_veh["route_finished_at"].apply(parse_hour_chile)

        df_veh_show = df_veh[["vehicle_code", "driver_name", "employer_name", "schema_name", "estado", "hr_inicio", "hr_fin"]].copy()
        df_veh_show.columns = ["Vehículo", "Conductor", "Operador Logístico", "Centro", "Estado", "Inicio", "Fin"]
        df_veh_show = df_veh_show.fillna("-")

        def color_estado_light(val):
            if val == "Finalizada":
                return "background-color: #dcfce7; color: #166534"
            elif val == "En ruta":
                return "background-color: #dbeafe; color: #1e40af"
            elif val == "Sin iniciar":
                return "background-color: #fee2e2; color: #991b1b"
            return ""

        st.dataframe(
            df_veh_show.sort_values("Estado").style.map(color_estado_light, subset=["Estado"]),
            use_container_width=True,
            hide_index=True,
            height=500,
        )

    with tab2:
        st.markdown('<div class="section-title">📦 Detalle de entregas por sala</div>', unsafe_allow_html=True)

        motivos_list = df["reason"].replace("-", pd.NA).dropna().unique().tolist()
        motivos = ["Todos"] + sorted(motivos_list)
        motivo_sel = st.selectbox("Filtrar por motivo", motivos)

        df_ent = df.copy()
        if motivo_sel != "Todos":
            df_ent = df_ent[df_ent["reason"] == motivo_sel]

        df_ent_show = df_ent[["address_code", "address_name", "vehicle_code", "driver_name",
                              "employer_name", "tipo_viaje", "units_1", "units_2", "status_display", "reason",
                              "otif", "near_pod", "tracked_service_time", "espera_max_sala",
                              "espera_total_sala", "visitas_gps"]].copy()
        df_ent_show.columns = ["Código", "Sala", "Vehículo", "Conductor",
                               "Operador Logístico", "Tipo Viaje", "Bultos", "Venta Total", "Status", "Motivo",
                               "OTIF", "Near POD", "Espera Actual", "Espera Mayor",
                               "Espera Total", "Pasadas GPS"]
        for col_esp in ["Espera Actual", "Espera Mayor", "Espera Total"]:
            df_ent_show[col_esp] = df_ent_show[col_esp].apply(
                lambda x: int(x) if pd.notna(x) and str(x) not in ("-", "") else "-")
        df_ent_show["Pasadas GPS"] = df_ent_show["Pasadas GPS"].apply(
            lambda x: int(x) if pd.notna(x) and str(x) not in ("-", "") else 1)
        df_ent_show["Venta Total"] = df_ent_show["Venta Total"].apply(lambda x: f"${x:,}" if x > 0 else "-")
        df_ent_show = df_ent_show.fillna("-")

        st.dataframe(
            df_ent_show.style.map(color_status_light, subset=["Status"])
                             .map(color_tipo_viaje, subset=["Tipo Viaje"]),
            use_container_width=True,
            hide_index=True,
            height=500,
        )

        st.markdown('<div class="section-title">📊 Distribución de motivos</div>', unsafe_allow_html=True)
        reason_data = df[df["reason"] != "-"]["reason"].value_counts().reset_index()
        reason_data.columns = ["Motivo", "Cantidad"]
        if not reason_data.empty:
            fig_reasons = px.bar(
                reason_data, x="Cantidad", y="Motivo", orientation="h",
                color="Cantidad", color_continuous_scale=[[0, BIMBO_CELESTE], [1, BIMBO_BLUE]],
                text="Cantidad",
            )
            fig_reasons.update_layout(**PLOTLY_LAYOUT, height=300, showlegend=False)
            fig_reasons.update_traces(textposition="outside")
            fig_reasons.update_coloraxes(showscale=False)
            st.plotly_chart(fig_reasons, use_container_width=True)

    with tab3:
        st.markdown('<div class="section-title">🏆 Top 10 Salas con Mayor Tiempo de Espera GPS</div>', unsafe_allow_html=True)
        st.caption("Espera Total = suma de todas las pasadas capturadas · Espera Mayor = visita individual más larga")

        df_times = df[df["espera_total_sala"].notna() & (df["espera_total_sala"] > 0)].copy()

        if df_times.empty:
            st.info("No hay datos de tiempo de espera GPS para este rango.")
        else:
            df_sala_dia = df_times.drop_duplicates(subset=["address_code", "planned_date"])[
                ["address_code", "address_name", "planned_date", "espera_max_sala",
                 "espera_total_sala", "visitas_gps"]
            ]
            sala_agg = df_sala_dia.groupby(["address_code", "address_name"]).agg(
                espera_total=("espera_total_sala", "max"),
                espera_mayor=("espera_max_sala", "max"),
                pasadas=("visitas_gps", "max"),
                dias=("planned_date", "count"),
            ).reset_index().sort_values("espera_total", ascending=False).head(10)
            sala_agg["espera_total"] = sala_agg["espera_total"].astype(int)
            sala_agg["espera_mayor"] = sala_agg["espera_mayor"].astype(int)
            sala_agg["pasadas"] = sala_agg["pasadas"].astype(int)

            fig_top = px.bar(
                sala_agg, x="espera_total", y="address_name", orientation="h",
                text="espera_total", color="espera_total",
                color_continuous_scale=[[0, BIMBO_CELESTE], [0.5, BIMBO_BLUE], [1, BIMBO_RED]],
                labels={"espera_total": "Espera Total (min)", "address_name": "Sala"},
            )
            fig_top.update_layout(**PLOTLY_LAYOUT, height=420, showlegend=False, yaxis=dict(autorange="reversed"))
            fig_top.update_traces(textposition="outside")
            fig_top.update_coloraxes(showscale=False)
            st.plotly_chart(fig_top, use_container_width=True)

            sala_show = sala_agg[["address_code", "address_name", "espera_total", "espera_mayor", "pasadas"]].copy()
            sala_show.columns = ["Código", "Sala", "Espera Total (min)", "Espera Mayor (min)", "Pasadas GPS"]
            st.dataframe(sala_show, use_container_width=True, hide_index=True)

    with tab4:
        st.markdown('<div class="section-title">📈 Tendencia de Bultos, OTD y OTIF por Día</div>', unsafe_allow_html=True)

        df_trend = df.copy()
        df_trend["fecha"] = pd.to_datetime(df_trend["planned_date"])

        bultos_dia = df_trend.groupby("fecha")["units_1"].sum().reset_index()
        bultos_dia.columns = ["Fecha", "Bultos"]

        otif_dia = df_trend.groupby("fecha").apply(
            lambda x: round((x["otif"] == "Si").sum() / len(x) * 100, 1) if len(x) > 0 else 0
        ).reset_index()
        otif_dia.columns = ["Fecha", "OTIF %"]

        otd_dia = df_trend.groupby("fecha").apply(
            lambda x: round(((x["status"] == "approved") | (x["status"] == "partial")).sum() / len(x) * 100, 1) if len(x) > 0 else 0
        ).reset_index()
        otd_dia.columns = ["Fecha", "OTD %"]

        BIMBO_ORANGE = "#f59e0b"

        fig_trend = go.Figure(
            data=[
                go.Scatter(
                    x=bultos_dia["Fecha"], y=bultos_dia["Bultos"],
                    name="Bultos", mode="lines+markers",
                    line=dict(color=BIMBO_CELESTE, width=3),
                    marker=dict(size=8, color=BIMBO_CELESTE),
                ),
                go.Scatter(
                    x=otd_dia["Fecha"], y=otd_dia["OTD %"],
                    name="OTD %", mode="lines+markers",
                    line=dict(color=BIMBO_BLUE, width=3),
                    marker=dict(size=8, color=BIMBO_BLUE),
                    yaxis="y2",
                ),
                go.Scatter(
                    x=otif_dia["Fecha"], y=otif_dia["OTIF %"],
                    name="OTIF %", mode="lines+markers",
                    line=dict(color=BIMBO_GREEN, width=3),
                    marker=dict(size=8, color=BIMBO_GREEN),
                    yaxis="y2",
                ),
            ],
            layout=go.Layout(
                template="plotly_white",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(255,255,255,1)",
                font=dict(color="#1a1a2e", size=12),
                margin=dict(l=60, r=60, t=30, b=40),
                height=400,
                xaxis=dict(dtick="D1", tickformat="%d/%m/%Y"),
                yaxis=dict(title=dict(text="Bultos", font=dict(color=BIMBO_CELESTE)),
                           tickfont=dict(color=BIMBO_CELESTE), side="left"),
                yaxis2=dict(title=dict(text="OTD / OTIF %", font=dict(color=BIMBO_BLUE)),
                            tickfont=dict(color=BIMBO_BLUE), side="right",
                            overlaying="y", range=[0, 100]),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            ),
        )
        st.plotly_chart(fig_trend, use_container_width=True)

        st.markdown('<div class="section-title">🏭 Entregas por Centro de Venta</div>', unsafe_allow_html=True)
        ent_cv = df.groupby("schema_name").agg(
            entregas=("order_code", "count"),
            realizadas=("status", lambda x: ((x == "approved") | (x == "partial")).sum()),
            otif_pct=("otif", lambda x: round((x == "Si").sum() / len(x) * 100, 1)),
            bultos=("units_1", "sum"),
            venta=("units_2", "sum"),
        ).reset_index().sort_values("entregas", ascending=False)
        ent_cv["otd_pct"] = (ent_cv["realizadas"] / ent_cv["entregas"] * 100).round(1)
        ent_cv["bultos"] = ent_cv["bultos"].astype(int)
        ent_cv["venta"] = ent_cv["venta"].apply(lambda x: f"${int(x):,}")
        ent_cv = ent_cv[["schema_name", "entregas", "otd_pct", "otif_pct", "bultos", "venta"]]
        ent_cv.columns = ["Centro", "Entregas", "OTD %", "OTIF %", "Bultos", "Venta Total"]
        st.dataframe(ent_cv, use_container_width=True, hide_index=True)


# ── Footer ──────────────────────────────────────────────────
st.divider()
st.caption(f"Dashboard Drivin · Datos del {start_date.strftime('%d/%m/%Y')} al {end_date.strftime('%d/%m/%Y')} · {total_entregas} entregas procesadas")
