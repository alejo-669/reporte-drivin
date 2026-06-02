"""
fill_rate_tab.py  —  versión Streamlit Cloud (botón de subida, estilo Bimbo)
============================================================================
Pestaña "Fill Rate & Distribución" (solo canal AASS).

- Usa la FECHA del sidebar (un solo control, como las otras pestañas).
- Estilo y colores Bimbo, tablas con semáforo, Paretos arreglados.
- El cruce con Drivin usa la data en vivo que la app ya cargó (se pasa a render).

Integración en app.py:
    elif page=="📥 Fill Rate":
        import fill_rate_tab
        fill_rate_tab.render(df, start_d.strftime("%Y-%m-%d"))
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# Paleta Bimbo (igual que app.py)
BIMBO_BLUE = "#003087"
BIMBO_CELESTE = "#38bdf8"
BIMBO_RED = "#dc2626"
BIMBO_GREEN = "#16a34a"
PLOTLY_BASE = dict(template="plotly_white", paper_bgcolor="rgba(0,0,0,0)",
                   plot_bgcolor="rgba(255,255,255,1)",
                   font=dict(color="#1a1a2e", size=12))
UMBRAL = 0.95

COLMAP = {
    "ceve_id": "ceve_id", "Ceves": "ceve", "Fecha": "fecha",
    "GERENCIA": "gerencia", "ruta_id": "ruta_id",
    "Código": "codigo", "Descripción": "descripcion",
    "Pedido": "pedido_cajas", "Despacho": "despacho_cajas", "Recorte": "recorte_cajas",
    "Pedido $": "pedido_pesos", "Despacho $": "despacho_pesos", "Recortes $": "recorte_pesos",
    "Pedido Piezas": "pedido_piezas", "Despacho Piezas": "despacho_piezas",
}
GRAIN = ["fecha", "ceve_id", "ceve", "ruta_id", "codigo", "descripcion"]
MEASURES = ["pedido_cajas", "despacho_cajas", "recorte_cajas",
            "pedido_pesos", "despacho_pesos", "recorte_pesos",
            "pedido_piezas", "despacho_piezas"]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _titulo(txt: str) -> None:
    st.markdown(f'<div class="section-title">{txt}</div>', unsafe_allow_html=True)


def _fr(pedido: float, despacho: float) -> float:
    return (despacho / pedido) if pedido else 0.0


def _color_fr(v):
    """Semáforo para fill rate (valor en %)."""
    try:
        n = float(str(v).replace("%", ""))
    except (TypeError, ValueError):
        return ""
    if n < 90: return "background-color:#fee2e2;color:#991b1b"
    if n < 95: return "background-color:#fef9c3;color:#854d0e"
    return "background-color:#dcfce7;color:#166534"


def _color_diag(v):
    s = str(v)
    if s == "Recorte + rechazo": return "background-color:#fee2e2;color:#991b1b"
    if s == "Solo recorte (stock)": return "background-color:#fef9c3;color:#854d0e"
    if s == "Solo rechazo (calle)": return "background-color:#dbeafe;color:#1e40af"
    if s == "OK": return "background-color:#dcfce7;color:#166534"
    return ""


# ---------------------------------------------------------------------------
# Lectura del Excel + cruce con Drivin (en vivo)
# ---------------------------------------------------------------------------
def leer_excel(file) -> pd.DataFrame:
    df = pd.read_excel(file)
    faltantes = [c for c in COLMAP if c not in df.columns]
    if faltantes:
        raise ValueError(f"Faltan columnas en el archivo: {faltantes}")
    df = df[df["GERENCIA"] == "AUTOSERVICIOS"].copy()
    if df.empty:
        raise ValueError("No hay filas de AUTOSERVICIOS en el archivo.")
    df = df[list(COLMAP.keys())].rename(columns=COLMAP)
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.strftime("%Y-%m-%d")
    for m in MEASURES:
        df[m] = pd.to_numeric(df[m], errors="coerce").fillna(0)
    df = df.drop(columns=["gerencia"], errors="ignore")
    return df.groupby(GRAIN, as_index=False)[MEASURES].sum()


def _rutas_programadas(df_drivin, fecha):
    if df_drivin is None or len(df_drivin) == 0:
        return set()
    sub = df_drivin[df_drivin["planned_date"].astype(str).str.startswith(fecha)]
    out = set()
    for c in sub["address_code"].dropna().unique():
        try:
            out.add(int(str(c).strip()))
        except (TypeError, ValueError):
            continue
    return out


def _drivin_por_ruta(df_drivin, fecha):
    if df_drivin is None or len(df_drivin) == 0:
        return pd.DataFrame()
    sub = df_drivin[df_drivin["planned_date"].astype(str).str.startswith(fecha)].copy()
    if sub.empty:
        return pd.DataFrame()
    g = sub.groupby("address_code").agg(
        otif=("otif", lambda x: (x == "Si").mean() * 100),
        rechazos=("status", lambda x: (x == "rejected").sum()),
        bultos_drivin=("units_1", "sum"),
    ).reset_index()
    g["ruta_id"] = pd.to_numeric(g["address_code"], errors="coerce")
    g = g.dropna(subset=["ruta_id"])
    g["ruta_id"] = g["ruta_id"].astype(int)
    g["otif"] = g["otif"].round(1)
    return g[["ruta_id", "otif", "rechazos", "bultos_drivin"]]


# ---------------------------------------------------------------------------
# Bloques
# ---------------------------------------------------------------------------
def _bloque_semaforo(d):
    ped, des = d["pedido_cajas"].sum(), d["despacho_cajas"].sum()
    rec, rec_pesos = d["recorte_cajas"].sum(), d["recorte_pesos"].sum()
    fr = _fr(ped, des)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📊 Fill Rate AASS", f"{fr:.1%}", f"{fr - UMBRAL:+.1%} vs {UMBRAL:.0%}",
              delta_color="normal" if fr >= UMBRAL else "inverse")
    c2.metric("✅ Cajas validadas", f"{ped:,.0f}")
    c3.metric("📦 Cajas despachadas", f"{des:,.0f}", f"-{rec:,.0f} recorte", delta_color="inverse")
    c4.metric("💰 Recorte en $", f"${rec_pesos:,.0f}")
    if fr < UMBRAL:
        st.markdown(f'<div class="alerta-yellow">⚠️ Bajo el umbral del {UMBRAL:.0%}: '
                    f'faltaron {rec:,.0f} cajas (${rec_pesos:,.0f}) por despachar.</div>',
                    unsafe_allow_html=True)
    else:
        st.success(f"✅ Sobre el umbral del {UMBRAL:.0%}.")


def _pareto(df, etq, val, titulo):
    df = df.sort_values(val, ascending=False).head(20).reset_index(drop=True)
    total = df[val].sum()
    df["acum"] = df[val].cumsum() / total if total else 0
    orden = df[etq].tolist()
    fig = go.Figure()
    fig.add_bar(x=df[etq], y=df[val], name="Recorte", marker_color=BIMBO_RED)
    fig.add_scatter(x=df[etq], y=df["acum"], name="% acum", yaxis="y2",
                    mode="lines+markers", line=dict(color=BIMBO_BLUE, width=2),
                    marker=dict(size=5))
    fig.add_hline(y=0.8, line_dash="dot", line_color="gray", yref="y2")
    fig.update_layout(**PLOTLY_BASE, height=360, margin=dict(l=10, r=50, t=10, b=110),
                      yaxis=dict(title="Recorte"),
                      yaxis2=dict(overlaying="y", side="right", range=[0, 1.05],
                                  tickformat=".0%", showgrid=False),
                      xaxis=dict(type="category", categoryorder="array",
                                 categoryarray=orden, tickangle=-45),
                      legend=dict(orientation="h", y=1.12, x=1, xanchor="right"))
    return fig


def _bloque_paretos(d):
    _titulo("📊 ¿Dónde se concentra el recorte?")
    st.caption("Tres ángulos por igual. La línea punteada marca el 80% acumulado.")

    sku = d.groupby(["codigo", "descripcion"], as_index=False).agg(recorte=("recorte_cajas", "sum"))
    sku["etq"] = sku["descripcion"].str.slice(0, 24)
    st.plotly_chart(_pareto(sku, "etq", "recorte", "producto cajas"),
                    use_container_width=True, key="p_sku_cajas")

    ca, cb = st.columns(2)
    with ca:
        st.markdown("**Por sala (ruta_id)**")
        sala = d.groupby("ruta_id", as_index=False).agg(recorte=("recorte_cajas", "sum"))
        sala["etq"] = "R" + sala["ruta_id"].astype(str)
        st.plotly_chart(_pareto(sala, "etq", "recorte", "sala"),
                        use_container_width=True, key="p_sala")
    with cb:
        st.markdown("**Por producto ($)**")
        skup = d.groupby(["codigo", "descripcion"], as_index=False).agg(recorte=("recorte_pesos", "sum"))
        skup["etq"] = skup["descripcion"].str.slice(0, 24)
        st.plotly_chart(_pareto(skup, "etq", "recorte", "producto pesos"),
                        use_container_width=True, key="p_sku_pesos")


def _bloque_diagnostico(d, df_drivin, fecha, hay_drivin):
    _titulo("🔍 Diagnóstico: ¿recorte de stock o rechazo en la calle?")
    fr_sala = d.groupby("ruta_id", as_index=False).agg(
        pedido=("pedido_cajas", "sum"), despacho=("despacho_cajas", "sum"),
        recorte=("recorte_cajas", "sum"))
    fr_sala["fill_rate"] = (fr_sala["despacho"] / fr_sala["pedido"] * 100).round(1)
    drivin = _drivin_por_ruta(df_drivin, fecha)

    if drivin.empty:
        if not hay_drivin:
            st.markdown('<div class="alerta-blue">ℹ️ Para cruzar con Drivin, elige en el '
                        'sidebar la misma fecha del archivo. Por ahora se muestra solo el '
                        'fill rate por sala.</div>', unsafe_allow_html=True)
        t = fr_sala.sort_values("fill_rate").head(30).copy()
        t.columns = ["Sala", "Validado", "Despachado", "Recorte", "Fill Rate %"]
        st.dataframe(t.style.map(_color_fr, subset=["Fill Rate %"]),
                     use_container_width=True, hide_index=True)
        return

    cruce = fr_sala.merge(drivin, on="ruta_id", how="left")
    cruce["rechazos"] = cruce["rechazos"].fillna(0)

    def diag(r):
        bajo = r["fill_rate"] < UMBRAL * 100
        rech = r["rechazos"] > 0
        if bajo and rech: return "Recorte + rechazo"
        if bajo: return "Solo recorte (stock)"
        if rech: return "Solo rechazo (calle)"
        return "OK"

    cruce["diagnostico"] = cruce.apply(diag, axis=1)
    t = cruce.sort_values("fill_rate").head(30)[
        ["ruta_id", "pedido", "despacho", "recorte", "fill_rate",
         "otif", "rechazos", "diagnostico"]].copy()
    t.columns = ["Sala", "Validado", "Despachado", "Recorte", "Fill Rate %",
                 "OTIF %", "Rechazos", "Diagnóstico"]
    t["Rechazos"] = t["Rechazos"].astype(int)
    st.dataframe(
        t.style.map(_color_fr, subset=["Fill Rate %"]).map(_color_diag, subset=["Diagnóstico"]),
        use_container_width=True, hide_index=True, height=500)


def _bloque_tendencia(df):
    _titulo("📈 Tendencia (del archivo cargado)")
    diario = df.groupby("fecha", as_index=False).agg(
        pedido=("pedido_cajas", "sum"), despacho=("despacho_cajas", "sum"))
    diario["fill_rate"] = diario["despacho"] / diario["pedido"]
    if len(diario) < 2:
        st.markdown('<div class="alerta-blue">ℹ️ Este archivo tiene un solo día. El histórico '
                    'mensual permanente llega cuando conectemos una base de datos externa '
                    '(siguiente paso).</div>', unsafe_allow_html=True)
        return
    fig = go.Figure()
    fig.add_scatter(x=diario["fecha"], y=diario["fill_rate"], mode="lines+markers",
                    line=dict(color=BIMBO_RED, width=3), marker=dict(size=8), name="Fill rate")
    fig.add_hline(y=UMBRAL, line_dash="dot", line_color=BIMBO_GREEN,
                  annotation_text=f"Umbral {UMBRAL:.0%}")
    fig.update_layout(**PLOTLY_BASE, height=320, yaxis=dict(tickformat=".0%"),
                      margin=dict(t=20))
    st.plotly_chart(fig, use_container_width=True, key="tendencia")


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def render(df_drivin=None, fecha_sidebar=None):
    st.markdown(f'<h2 style="color:{BIMBO_BLUE}">📥 Fill Rate &amp; Distribución — AASS</h2>',
                unsafe_allow_html=True)

    file = st.file_uploader("Sube el Excel del PB (consolidado nacional)", type=["xlsx", "xls"])
    if file is None:
        st.markdown('<div class="alerta-blue">ℹ️ Sube el archivo de distribución del PB. Se '
                    'procesa al momento (no se guarda), filtra solo AASS y cruza con las rutas '
                    'que programaste en Drivin para la fecha del sidebar.</div>',
                    unsafe_allow_html=True)
        return

    try:
        df = leer_excel(file)
    except Exception as e:
        st.error(f"No pude leer el archivo: {e}")
        return

    # Fecha: viene del sidebar. Si el Excel no la tiene, avisar.
    fechas_excel = sorted(df["fecha"].unique(), reverse=True)
    fecha = fecha_sidebar if fecha_sidebar in fechas_excel else fechas_excel[0]
    if fecha_sidebar and fecha_sidebar not in fechas_excel:
        st.markdown(f'<div class="alerta-yellow">⚠️ El archivo no tiene datos para '
                    f'<b>{fecha_sidebar}</b> (fecha del sidebar). Mostrando <b>{fecha}</b>. '
                    f'Para que el cruce con Drivin calce, elige en el sidebar una fecha que '
                    f'esté en el archivo: {", ".join(fechas_excel)}.</div>',
                    unsafe_allow_html=True)

    # CEVE (en hoja, porque depende del archivo) + toggle de rutas programadas
    c1, c2 = st.columns([2, 1])
    ceves = ["(Todas)"] + sorted(df["ceve"].dropna().unique())
    ceve_sel = c1.selectbox("CEVE", ceves)
    solo_prog = c2.toggle("Solo rutas programadas", value=True,
                          help="Filtra a las rutas intermedia que programaste (las que están "
                               "en Drivin ese día).")

    d = df[df["fecha"] == fecha]
    if ceve_sel != "(Todas)":
        d = d[d["ceve"] == ceve_sel]

    hay_drivin = False
    if solo_prog:
        prog = _rutas_programadas(df_drivin, fecha)
        if prog:
            hay_drivin = True
            antes = d["ruta_id"].nunique()
            d = d[d["ruta_id"].isin(prog)]
            st.caption(f"Mostrando **{d['ruta_id'].nunique()} rutas programadas** "
                       f"(de {antes} rutas AASS del día). Las de piso quedan fuera.")
        else:
            st.markdown('<div class="alerta-yellow">⚠️ No hay data de Drivin para esta fecha en '
                        'la sesión. Elige en el sidebar la misma fecha del archivo para activar '
                        'el filtro. Por ahora se muestran todas las rutas AASS.</div>',
                        unsafe_allow_html=True)

    if d.empty:
        st.error("No quedaron rutas tras aplicar los filtros.")
        return

    _bloque_semaforo(d)
    st.divider()
    _bloque_paretos(d)
    st.divider()
    _bloque_diagnostico(d, df_drivin, fecha, hay_drivin)
    st.divider()
    _bloque_tendencia(df)
