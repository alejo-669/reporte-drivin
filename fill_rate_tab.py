"""
fill_rate_tab.py  —  versión Streamlit Cloud (botón de subida, sin base de datos)
=================================================================================
Pestaña "Fill Rate & Distribución" (solo canal AASS).

Cómo funciona:
- El usuario SUBE el Excel del PB con un botón (st.file_uploader).
- Se procesa en memoria (no se guarda en disco -> compatible con Streamlit Cloud).
- El cruce con Drivin usa la data que la app ya cargó en vivo desde la API
  (se pasa como argumento a render), no una base de datos.

Integración en app.py:
    elif page == "📥 Fill Rate":
        import fill_rate_tab
        fill_rate_tab.render(df)        # df = data de Drivin ya cargada

Archivo único y autocontenido: no depende de otros módulos nuevos.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

UMBRAL = 0.95  # objetivo de fill rate

# Mapeo de columnas del Excel del PB -> nombres internos
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
# Lectura del Excel (en memoria)
# ---------------------------------------------------------------------------
def leer_excel(file) -> pd.DataFrame:
    """Lee el Excel subido, filtra AASS y agrega al grano sala x sku x día."""
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
    # sumar los múltiples clientes que comparten una ruta_id
    return df.groupby(GRAIN, as_index=False)[MEASURES].sum()


def _fr(pedido: float, despacho: float) -> float:
    return (despacho / pedido) if pedido else 0.0


# ---------------------------------------------------------------------------
# Cruce con Drivin (desde la data en vivo, no desde base de datos)
# ---------------------------------------------------------------------------
def _rutas_programadas(df_drivin, fecha: str) -> set:
    """ruta_id que estaban en Drivin esa fecha = rutas intermedia programadas."""
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


def _drivin_por_ruta(df_drivin, fecha: str) -> pd.DataFrame:
    """Agrega OTIF / rechazos / bultos por ruta desde la data en vivo de Drivin."""
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
# Bloque 1 — Semáforo
# ---------------------------------------------------------------------------
def _bloque_semaforo(d: pd.DataFrame) -> None:
    ped = d["pedido_cajas"].sum()
    des = d["despacho_cajas"].sum()
    rec = d["recorte_cajas"].sum()
    rec_pesos = d["recorte_pesos"].sum()
    fr = _fr(ped, des)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fill Rate AASS", f"{fr:.1%}", f"{fr - UMBRAL:+.1%} vs {UMBRAL:.0%}",
              delta_color="normal" if fr >= UMBRAL else "inverse")
    c2.metric("Cajas validadas", f"{ped:,.0f}")
    c3.metric("Cajas despachadas", f"{des:,.0f}", f"-{rec:,.0f} recorte", delta_color="inverse")
    c4.metric("Recorte en $", f"${rec_pesos:,.0f}")

    if fr < UMBRAL:
        st.warning(f"Bajo el umbral del {UMBRAL:.0%}: faltaron {rec:,.0f} cajas "
                   f"(${rec_pesos:,.0f}) por despachar.")
    else:
        st.success(f"Sobre el umbral del {UMBRAL:.0%}.")


# ---------------------------------------------------------------------------
# Bloque 2 — Paretos
# ---------------------------------------------------------------------------
def _pareto(df: pd.DataFrame, etq: str, val: str, titulo: str) -> go.Figure:
    df = df.sort_values(val, ascending=False).head(20).reset_index(drop=True)
    df["acum"] = df[val].cumsum() / df[val].sum()
    fig = go.Figure()
    fig.add_bar(x=df[etq], y=df[val], name=titulo, marker_color="#C8102E")
    fig.add_scatter(x=df[etq], y=df["acum"], name="% acum", yaxis="y2",
                    mode="lines+markers", line=dict(color="#1f3a5f"))
    fig.add_hline(y=0.8, line_dash="dot", line_color="gray", yref="y2")
    fig.update_layout(title=titulo, height=380, margin=dict(t=40, b=90),
                      yaxis=dict(title="Recorte"),
                      yaxis2=dict(overlaying="y", side="right", range=[0, 1.05],
                                  tickformat=".0%"),
                      xaxis=dict(tickangle=-45),
                      legend=dict(orientation="h", y=1.12))
    return fig


def _bloque_paretos(d: pd.DataFrame) -> None:
    st.subheader("¿Dónde se concentra el recorte?")
    st.caption("Tres ángulos por igual. La línea punteada marca el 80% acumulado.")

    sku = d.groupby(["codigo", "descripcion"], as_index=False).agg(recorte=("recorte_cajas", "sum"))
    sku["etq"] = sku["descripcion"].str.slice(0, 28)
    st.plotly_chart(_pareto(sku, "etq", "recorte", "Recorte por producto (cajas)"),
                    use_container_width=True)

    ca, cb = st.columns(2)
    sala = d.groupby("ruta_id", as_index=False).agg(recorte=("recorte_cajas", "sum"))
    sala["etq"] = sala["ruta_id"].astype(str)
    with ca:
        st.plotly_chart(_pareto(sala, "etq", "recorte", "Recorte por sala (ruta_id)"),
                        use_container_width=True)
    skup = d.groupby(["codigo", "descripcion"], as_index=False).agg(recorte=("recorte_pesos", "sum"))
    skup["etq"] = skup["descripcion"].str.slice(0, 28)
    with cb:
        st.plotly_chart(_pareto(skup, "etq", "recorte", "Recorte por producto ($)"),
                        use_container_width=True)


# ---------------------------------------------------------------------------
# Bloque 3 — Diagnóstico (stock vs calle)
# ---------------------------------------------------------------------------
def _bloque_diagnostico(d: pd.DataFrame, df_drivin, fecha: str, hay_drivin: bool) -> None:
    st.subheader("Diagnóstico: ¿recorte de stock o rechazo en la calle?")

    fr_sala = d.groupby("ruta_id", as_index=False).agg(
        pedido=("pedido_cajas", "sum"), despacho=("despacho_cajas", "sum"),
        recorte=("recorte_cajas", "sum"))
    fr_sala["fill_rate"] = (fr_sala["despacho"] / fr_sala["pedido"] * 100).round(1)

    drivin = _drivin_por_ruta(df_drivin, fecha)
    if drivin.empty:
        if not hay_drivin:
            st.info("Para cruzar con Drivin, elige en el filtro de **fecha** del "
                    "sidebar el mismo día que estás analizando. Por ahora se muestra "
                    "solo el fill rate por sala.")
        st.dataframe(fr_sala.sort_values("fill_rate").head(30),
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
    st.dataframe(cruce.sort_values("fill_rate").head(30),
                 use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Bloque 4 — Tendencia (del archivo cargado)
# ---------------------------------------------------------------------------
def _bloque_tendencia(df: pd.DataFrame) -> None:
    st.subheader("Tendencia (del archivo cargado)")
    diario = df.groupby("fecha", as_index=False).agg(
        pedido=("pedido_cajas", "sum"), despacho=("despacho_cajas", "sum"))
    diario["fill_rate"] = (diario["despacho"] / diario["pedido"])

    if len(diario) < 2:
        st.info("Este archivo tiene un solo día. Si subes un Excel con varias fechas, "
                "aquí verás la curva. El histórico mensual permanente llega cuando "
                "conectemos una base de datos externa (siguiente paso).")
        return
    fig = go.Figure()
    fig.add_scatter(x=diario["fecha"], y=diario["fill_rate"], mode="lines+markers",
                    line=dict(color="#C8102E"), name="Fill rate")
    fig.add_hline(y=UMBRAL, line_dash="dot", line_color="green",
                  annotation_text=f"Umbral {UMBRAL:.0%}")
    fig.update_layout(height=320, yaxis=dict(tickformat=".0%"), margin=dict(t=20))
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Render principal
# ---------------------------------------------------------------------------
def render(df_drivin=None) -> None:
    st.markdown('<h2 style="color:#003087">📥 Fill Rate & Distribución — AASS</h2>',
                unsafe_allow_html=True)

    file = st.file_uploader("Sube el Excel del PB (consolidado nacional)",
                            type=["xlsx", "xls"])
    if file is None:
        st.info("Sube el archivo de distribución del PB para ver el análisis. "
                "Se procesa al momento (no se guarda), filtra solo AASS y cruza "
                "con las rutas que programaste en Drivin.")
        return

    try:
        df = leer_excel(file)
    except Exception as e:
        st.error(f"No pude leer el archivo: {e}")
        return

    # Filtros
    fechas = sorted(df["fecha"].unique(), reverse=True)
    ceves = ["(Todas)"] + sorted(df["ceve"].dropna().unique())
    c1, c2, c3 = st.columns([1, 2, 1])
    fecha_sel = c1.selectbox("Fecha de despacho", fechas)
    ceve_sel = c2.selectbox("CEVE", ceves)
    solo_prog = c3.toggle("Solo rutas programadas", value=True,
                          help="Filtra a las rutas intermedia que programaste "
                               "(las que están en Drivin ese día).")

    d = df[df["fecha"] == fecha_sel]
    if ceve_sel != "(Todas)":
        d = d[d["ceve"] == ceve_sel]

    hay_drivin = False
    if solo_prog:
        prog = _rutas_programadas(df_drivin, fecha_sel)
        if prog:
            hay_drivin = True
            antes = d["ruta_id"].nunique()
            d = d[d["ruta_id"].isin(prog)]
            st.caption(f"Mostrando **{d['ruta_id'].nunique()} rutas programadas** "
                       f"(de {antes} rutas AASS del día). Las de piso quedan fuera.")
        else:
            st.warning("No hay data de Drivin para esta fecha en la sesión actual. "
                       "Elige en el sidebar (filtro de fecha) el mismo día que estás "
                       "analizando para activar el filtro. Por ahora se muestran todas "
                       "las rutas AASS.")

    if d.empty:
        st.error("No quedaron rutas tras aplicar los filtros.")
        return

    _bloque_semaforo(d)
    st.divider()
    _bloque_paretos(d)
    st.divider()
    _bloque_diagnostico(d, df_drivin, fecha_sel, hay_drivin)
    st.divider()
    _bloque_tendencia(df)
