"""
Dashboard Operacional Drivin — Bimbo Ideal
==========================================
Visualiza entregas, KPIs, tiempos de espera por sala,
conductores y tendencias. Auto-refresh cada 10 minutos.

Para correr localmente:
  streamlit run app.py

Variables de entorno necesarias (en Streamlit Cloud van en Secrets):
  DRIVIN_API_KEY = "tu_api_key_aquí"
"""

import os
import json
import sqlite3
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh

# ── Page Config ─────────────────────────────────────────────
st.set_page_config(
    page_title="Drivin Dashboard — Bimbo Ideal",
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Auto-refresh cada 10 minutos (600,000 ms)
st_autorefresh(interval=600_000, key="data_refresh")

# ── Estilos CSS ─────────────────────────────────────────────
st.markdown("""
<style>
    /* KPI cards */
    div[data-testid="metric-container"] {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 16px;
    }
    div[data-testid="metric-container"] label {
        color: #94a3b8 !important;
        font-size: 0.85rem !important;
    }
    div[data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
        font-weight: 700 !important;
    }
    /* Header */
    .main-header {
        font-size: 1.6rem;
        font-weight: 700;
        color: #e2e8f0;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 0.9rem;
        color: #64748b;
        margin-bottom: 1.5rem;
    }
    /* Alerta */
    .alerta-box {
        background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%);
        border: 1px solid #dc2626;
        border-radius: 10px;
        padding: 12px 18px;
        color: #fecaca;
        font-weight: 600;
        margin-bottom: 1rem;
    }
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)


# ── Data Loading ────────────────────────────────────────────
@st.cache_data(ttl=600)
def load_data_from_api(start_date: str, end_date: str) -> pd.DataFrame:
    """Carga datos directo de la API de Drivin."""
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
                "client_name": o.get("client_name"),
                "tags": json.dumps(o.get("tags", [])),
                "pod_arrival": o.get("pod_arrival"),
            })

    return pd.DataFrame(rows)


# ── Header ──────────────────────────────────────────────────
st.markdown('<div class="main-header">🚛 Dashboard Operacional Drivin — Bimbo Ideal</div>', unsafe_allow_html=True)
st.markdown(f'<div class="sub-header">Auto-refresh cada 10 min · Última actualización: {datetime.now().strftime("%d/%m/%Y %H:%M")}</div>', unsafe_allow_html=True)

# ── Filtros ─────────────────────────────────────────────────
col_f1, col_f2, col_f3 = st.columns([1, 1, 1])

with col_f1:
    # Rango de fechas (máx 7 días por limitación API)
    today = datetime.now().date()
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

# Cargar datos
df = load_data_from_api(start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))

if df.empty:
    st.warning("⚠️ No hay datos disponibles. Verifica tu API Key en Secrets de Streamlit Cloud.")
    st.info("Ve a Settings → Secrets y agrega:\n```\nDRIVIN_API_KEY = \"tu_api_key\"\n```")
    st.stop()

with col_f2:
    centros = ["Todos"] + sorted(df["schema_name"].dropna().unique().tolist())
    centro_sel = st.selectbox("🏭 Centro de venta", centros)

with col_f3:
    codigos_sala = ["— Sin filtro —"] + sorted(df["address_code"].dropna().unique().tolist())
    sala_sel = st.selectbox("🏪 Código sala (zoom detalle)", codigos_sala)

# Aplicar filtro de centro
if centro_sel != "Todos":
    df = df[df["schema_name"] == centro_sel]

# ── KPIs ────────────────────────────────────────────────────
total_entregas = len(df)
otif_si = (df["otif"] == "Si").sum()
otif_pct = round(otif_si / total_entregas * 100, 1) if total_entregas else 0
rechazos = (df["status"] == "rejected").sum()
parciales = (df["status"] == "partial").sum()
total_bultos = int(df["units_1"].sum())

# Vehículos únicos y sin iniciar
vehiculos = df.drop_duplicates(subset=["vehicle_code"])
sin_iniciar = (vehiculos["route_is_started"] == False).sum()

# Hora promedio inicio
started_times = df.dropna(subset=["route_started_at"]).drop_duplicates("vehicle_code")
if not started_times.empty:
    hrs = pd.to_datetime(started_times["route_started_at"]).dt.hour * 60 + \
          pd.to_datetime(started_times["route_started_at"]).dt.minute
    avg_min = int(hrs.mean())
    hr_prom = f"{avg_min // 60:02d}:{avg_min % 60:02d}"
else:
    hr_prom = "—"

# Mostrar KPIs
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("📦 Total Entregas", f"{total_entregas:,}")
k2.metric("✅ OTIF", f"{otif_pct}%")
k3.metric("❌ Rechazos", rechazos)
k4.metric("⚠️ Parciales", parciales)
k5.metric("📦 Bultos", f"{total_bultos:,}")
k6.metric("🕐 Hr Prom. Inicio", hr_prom)

# Alerta rutas sin iniciar
if sin_iniciar > 0:
    st.markdown(
        f'<div class="alerta-box">⚠️ {sin_iniciar} ruta(s) sin iniciar de {len(vehiculos)} vehículos</div>',
        unsafe_allow_html=True,
    )

st.divider()

# ── Vista condicional: sala seleccionada o vista general ────
if sala_sel != "— Sin filtro —":
    # ════════════════════════════════════════════════════════
    # FICHA DETALLE DE SALA
    # ════════════════════════════════════════════════════════
    df_sala = df[df["address_code"] == sala_sel]

    if df_sala.empty:
        st.warning(f"No hay datos para la sala {sala_sel} en este rango de fechas.")
    else:
        nombre_sala = df_sala["address_name"].iloc[0]
        ciudad = df_sala["address_city"].iloc[0] if "address_city" in df_sala.columns else ""

        st.subheader(f"🏪 Detalle Sala: {sala_sel} — {nombre_sala}")
        if ciudad:
            st.caption(f"📍 {ciudad}")

        # Mini KPIs de la sala
        s1, s2, s3, s4, s5 = st.columns(5)
        total_sala = len(df_sala)
        otif_sala = (df_sala["otif"] == "Si").sum()
        otif_pct_sala = round(otif_sala / total_sala * 100, 1) if total_sala else 0
        rechazos_sala = (df_sala["status"] == "rejected").sum()
        bultos_sala = int(df_sala["units_1"].sum())
        tiempos = df_sala["tracked_service_time"].dropna()
        avg_espera = round(tiempos.mean(), 1) if not tiempos.empty else 0

        s1.metric("Visitas", total_sala)
        s2.metric("OTIF", f"{otif_pct_sala}%")
        s3.metric("Rechazos", rechazos_sala)
        s4.metric("Bultos", f"{bultos_sala:,}")
        s5.metric("Espera Prom. (min)", f"{avg_espera}")

        st.markdown("##### 📋 Historial de visitas")

        # Tabla de detalle
        cols_show = ["planned_date", "driver_name", "vehicle_code", "units_1",
                     "status", "reason", "otif", "near_pod", "tracked_service_time"]
        df_show = df_sala[cols_show].copy()
        df_show.columns = ["Fecha", "Conductor", "Vehículo", "Bultos",
                           "Status", "Motivo", "OTIF", "Near POD", "Espera GPS (min)"]

        # Colorear status
        def color_status(val):
            if val == "approved":
                return "background-color: #166534; color: #bbf7d0"
            elif val == "rejected":
                return "background-color: #7f1d1d; color: #fecaca"
            elif val == "partial":
                return "background-color: #78350f; color: #fde68a"
            return ""

        st.dataframe(
            df_show.style.map(color_status, subset=["Status"]),
            use_container_width=True,
            hide_index=True,
            height=400,
        )

        # Gráfico de tiempo de espera por visita
        if not tiempos.empty:
            st.markdown("##### ⏱️ Tiempo de espera GPS por visita")
            df_chart = df_sala[["planned_date", "tracked_service_time", "driver_name"]].dropna(subset=["tracked_service_time"])
            fig = px.bar(
                df_chart,
                x="planned_date",
                y="tracked_service_time",
                color="driver_name",
                labels={"tracked_service_time": "Minutos", "planned_date": "Fecha", "driver_name": "Conductor"},
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                height=350,
                margin=dict(l=0, r=0, t=30, b=0),
            )
            st.plotly_chart(fig, use_container_width=True)

else:
    # ════════════════════════════════════════════════════════
    # VISTA GENERAL (sin sala seleccionada)
    # ════════════════════════════════════════════════════════

    tab1, tab2, tab3, tab4 = st.tabs([
        "🚗 Vehículos", "📦 Status Entregas", "🏆 Ranking Salas", "📈 Tendencias"
    ])

    # ── TAB 1: Vehículos ──────────────────────────────────
    with tab1:
        st.markdown("##### Estado de sesión por vehículo")
        df_veh = df.drop_duplicates(subset=["vehicle_code"]).copy()
        df_veh["estado"] = df_veh.apply(
            lambda r: "Finalizada" if r["route_is_finished"]
            else ("En ruta" if r["route_is_started"] else "Sin iniciar"),
            axis=1,
        )
        # Extraer hora
        df_veh["hr_inicio"] = pd.to_datetime(df_veh["route_started_at"], errors="coerce").dt.strftime("%H:%M").fillna("—")
        df_veh["hr_fin"] = pd.to_datetime(df_veh["route_finished_at"], errors="coerce").dt.strftime("%H:%M").fillna("—")

        cols_veh = ["vehicle_code", "driver_name", "schema_name", "estado", "hr_inicio", "hr_fin"]
        df_veh_show = df_veh[cols_veh].copy()
        df_veh_show.columns = ["Vehículo", "Conductor", "Centro", "Estado", "Inicio", "Fin"]

        def color_estado(val):
            if val == "Finalizada":
                return "background-color: #166534; color: #bbf7d0"
            elif val == "En ruta":
                return "background-color: #1e40af; color: #bfdbfe"
            elif val == "Sin iniciar":
                return "background-color: #7f1d1d; color: #fecaca"
            return ""

        st.dataframe(
            df_veh_show.sort_values("Estado").style.map(color_estado, subset=["Estado"]),
            use_container_width=True,
            hide_index=True,
            height=500,
        )

    # ── TAB 2: Status Entregas ────────────────────────────
    with tab2:
        st.markdown("##### Detalle de entregas por sala")

        # Filtro de motivo
        motivos = ["Todos"] + sorted(df["reason"].dropna().unique().tolist())
        motivo_sel = st.selectbox("Filtrar por motivo", motivos)

        df_ent = df.copy()
        if motivo_sel != "Todos":
            df_ent = df_ent[df_ent["reason"] == motivo_sel]

        cols_ent = ["address_code", "address_name", "vehicle_code", "driver_name",
                    "units_1", "status", "reason", "otif", "near_pod", "tracked_service_time"]
        df_ent_show = df_ent[cols_ent].copy()
        df_ent_show.columns = ["Código", "Sala", "Vehículo", "Conductor",
                               "Bultos", "Status", "Motivo", "OTIF", "Near POD", "Espera GPS"]

        def color_status_ent(val):
            if val == "approved":
                return "background-color: #166534; color: #bbf7d0"
            elif val == "rejected":
                return "background-color: #7f1d1d; color: #fecaca"
            elif val == "partial":
                return "background-color: #78350f; color: #fde68a"
            return ""

        st.dataframe(
            df_ent_show.style.map(color_status_ent, subset=["Status"]),
            use_container_width=True,
            hide_index=True,
            height=500,
        )

        # Resumen de motivos
        st.markdown("##### Distribución de motivos")
        reason_counts = df["reason"].value_counts().reset_index()
        reason_counts.columns = ["Motivo", "Cantidad"]
        fig_reasons = px.bar(
            reason_counts,
            x="Cantidad",
            y="Motivo",
            orientation="h",
            color="Cantidad",
            color_continuous_scale=["#1e40af", "#22d3ee"],
        )
        fig_reasons.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=300,
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False,
        )
        st.plotly_chart(fig_reasons, use_container_width=True)

    # ── TAB 3: Ranking Salas ──────────────────────────────
    with tab3:
        st.markdown("##### 🏆 Top 10 Salas con Mayor Tiempo de Espera GPS")

        df_times = df[df["tracked_service_time"].notna() & (df["tracked_service_time"] > 0)].copy()

        if df_times.empty:
            st.info("No hay datos de tiempo de espera GPS para este rango.")
        else:
            sala_agg = df_times.groupby(["address_code", "address_name"]).agg(
                max_espera=("tracked_service_time", "max"),
                avg_espera=("tracked_service_time", "mean"),
                visitas=("tracked_service_time", "count"),
            ).reset_index().sort_values("max_espera", ascending=False).head(10)
            sala_agg["avg_espera"] = sala_agg["avg_espera"].round(1)

            fig_top = px.bar(
                sala_agg,
                x="max_espera",
                y="address_name",
                orientation="h",
                text="max_espera",
                color="max_espera",
                color_continuous_scale=["#22d3ee", "#dc2626"],
                labels={"max_espera": "Max Espera (min)", "address_name": "Sala"},
            )
            fig_top.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                height=400,
                margin=dict(l=0, r=0, t=10, b=0),
                showlegend=False,
                yaxis=dict(autorange="reversed"),
            )
            fig_top.update_traces(textposition="outside")
            st.plotly_chart(fig_top, use_container_width=True)

            # Tabla complementaria
            sala_agg_show = sala_agg.copy()
            sala_agg_show.columns = ["Código", "Sala", "Max Espera (min)", "Prom Espera (min)", "Visitas"]
            st.dataframe(sala_agg_show, use_container_width=True, hide_index=True)

    # ── TAB 4: Tendencias ─────────────────────────────────
    with tab4:
        st.markdown("##### 📈 Tendencia de Bultos y OTIF por Día")

        df_trend = df.copy()
        df_trend["fecha"] = pd.to_datetime(df_trend["planned_date"])

        # Bultos por día
        bultos_dia = df_trend.groupby("fecha")["units_1"].sum().reset_index()
        bultos_dia.columns = ["Fecha", "Bultos"]

        # OTIF por día
        otif_dia = df_trend.groupby("fecha").apply(
            lambda x: round((x["otif"] == "Si").sum() / len(x) * 100, 1) if len(x) > 0 else 0
        ).reset_index()
        otif_dia.columns = ["Fecha", "OTIF %"]

        fig_trend = go.Figure()
        fig_trend.add_trace(go.Bar(
            x=bultos_dia["Fecha"],
            y=bultos_dia["Bultos"],
            name="Bultos",
            marker_color="#22d3ee",
            yaxis="y",
        ))
        fig_trend.add_trace(go.Scatter(
            x=otif_dia["Fecha"],
            y=otif_dia["OTIF %"],
            name="OTIF %",
            mode="lines+markers",
            line=dict(color="#10b981", width=3),
            marker=dict(size=8),
            yaxis="y2",
        ))
        fig_trend.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=400,
            margin=dict(l=0, r=50, t=10, b=0),
            yaxis=dict(title="Bultos", side="left"),
            yaxis2=dict(title="OTIF %", side="right", overlaying="y", range=[0, 100]),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_trend, use_container_width=True)

        # Entregas por centro
        st.markdown("##### 🏭 Entregas por Centro de Venta")
        ent_cv = df.groupby("schema_name").agg(
            entregas=("order_code", "count"),
            otif_pct=("otif", lambda x: round((x == "Si").sum() / len(x) * 100, 1)),
            bultos=("units_1", "sum"),
        ).reset_index().sort_values("entregas", ascending=False)
        ent_cv.columns = ["Centro", "Entregas", "OTIF %", "Bultos"]
        st.dataframe(ent_cv, use_container_width=True, hide_index=True)


# ── Footer ──────────────────────────────────────────────────
st.divider()
st.caption(f"Dashboard Drivin · Datos del {start_date.strftime('%d/%m/%Y')} al {end_date.strftime('%d/%m/%Y')} · {total_entregas} entregas procesadas")
