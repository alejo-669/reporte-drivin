"""
carga_3d.py — Pestaña "🚛 Carga 3D" · Proyecto Carga T2
=======================================================
Muestra cómo va cargado cada camión: pallets por sala, apilados según la
secuencia de entrega (el último en entregar al fondo, junto a la cabina).

Fuentes (todo desde Drivin, sin datos ni credenciales extra en el repo):
  · Ruta, secuencia y cupo  -> endpoint /pods (vehicle_code, position, eta,
                               vehicle_capacity_1)
  · Composición de la carga -> custom_1 de cada pedido, calculado en el PC
                               con datos de MC1 + WMS (proyecto Carga T2)

Integración en app.py:
  · Sidebar:  ...,"⚖️ Plan 48h vs 24h","🚛 Carga 3D"]
  · Bloque (antes de "# Load data"):
        if page=="🚛 Carga 3D":
            import carga_3d
            carga_3d.render()
            st.stop()
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from carga3d import ajustes
from carga3d.formato_composicion import decodificar
from carga3d.motor import armar_pallets, resumir_rutas
from carga3d.visual import dibujar_camion

TZ_CHILE = ZoneInfo("America/Santiago")
BIMBO_BLUE = "#003087"
URL_PODS = "https://external.driv.in/api/external/v2/pods"


# ── 1. Datos ───────────────────────────────────────────────────
def _api_key() -> str:
    key = os.environ.get("DRIVIN_API_KEY", "")
    if not key:
        try:
            key = st.secrets["DRIVIN_API_KEY"]
        except Exception:
            key = ""
    return key


@st.cache_data(ttl=300, show_spinner="Leyendo rutas de Drivin...")
def cargar_paradas(fecha_iso: str) -> pd.DataFrame:
    """Una fila por pedido de cada parada, con lo necesario para la carga."""
    resp = requests.get(URL_PODS, timeout=60,
                        headers={"X-API-KEY": _api_key(), "Content-Type": "application/json"},
                        params={"start_date": fecha_iso, "end_date": fecha_iso})
    resp.raise_for_status()
    filas = []
    for r in resp.json().get("response", []) or []:
        for o in r.get("orders", []) or []:
            filas.append({
                "centro": r.get("schema_name"),
                "vehiculo": r.get("vehicle_code"),
                "vuelta": r.get("trip_number") or 1,
                "sala": str(r.get("address_code") or ""),
                "nombre_sala": (r.get("address_name") or "").strip(),
                "posicion": r.get("position"),
                "eta": r.get("eta"),
                "cupo_bandejas": r.get("vehicle_capacity_1") or 0,
                "pedido": o.get("code"),
                "envases_drivin": o.get("units_1") or 0,
                "composicion": o.get("custom_1"),
            })
    return pd.DataFrame(filas)


def _orden_visita(paradas: pd.DataFrame) -> pd.Series:
    """Orden de entrega dentro del camión: 'position' de Drivin; si falta, por ETA."""
    clave = pd.to_numeric(paradas["posicion"], errors="coerce")
    respaldo = pd.to_datetime(paradas["eta"], errors="coerce").rank(method="dense")
    clave = clave.fillna(respaldo)
    return clave.rank(method="dense").astype(int)


def construir_lineas(paradas: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Decodifica custom_1 al formato del motor. Devuelve (lineas, salas_sin_composicion)."""
    p = paradas.copy()
    p["camion"] = p["vehiculo"].astype(str) + " · V" + p["vuelta"].astype(str)
    p["orden_visita"] = p.groupby("camion", group_keys=False).apply(_orden_visita)
    p["cliente"] = (p["sala"] + " " + p["nombre_sala"]).str.strip().str[:40]

    filas, sin_comp = [], []
    for _, r in p.iterrows():
        tramos = decodificar(r["composicion"])
        if not tramos:
            sin_comp.append(r)
            continue
        for t in tramos:
            filas.append({
                "ruta": r["camion"], "cliente": r["cliente"], "orden_visita": r["orden_visita"],
                "codigo": t["tipo_envase"] if t["n_codigos"] == 1 else f"SURTIDO-{t['tipo_envase']}",
                "descripcion": f"{t['n_codigos']} códigos en {t['tipo_envase']}",
                "n_codigos": t["n_codigos"], "familia": t["familia"],
                "tipo_envase": t["tipo_envase"], "envases": t["envases"],
                "cupo_pallet": t["cupo_pallet"], "alto_pallet_full_m": t["alto_pallet_full_m"],
                "fraccion_pallet": t["envases"] / t["cupo_pallet"],
            })
    return pd.DataFrame(filas), pd.DataFrame(sin_comp)


def posiciones_por_camion(paradas: pd.DataFrame) -> dict:
    """Cupo Drivin (bandejas) / 72 = posiciones de pallet; sin cupo -> default."""
    p = paradas.assign(camion=paradas["vehiculo"].astype(str) + " · V" + paradas["vuelta"].astype(str))
    cupo = p.groupby("camion")["cupo_bandejas"].max()
    pos = (cupo / ajustes.BANDEJAS_POR_PALLET_REF).round().astype(int)
    return pos.where(pos > 0, ajustes.POSICIONES_PALLET_DEFAULT).to_dict()


# ── 2. Pantalla ────────────────────────────────────────────────
def _kpi(col, titulo, valor, ayuda=None):
    col.metric(titulo, valor, help=ayuda)


def render():
    st.markdown(f'<h2 style="color:{BIMBO_BLUE}">🚛 Carga 3D por camión</h2>', unsafe_allow_html=True)
    st.caption("Pallets por sala según la secuencia de Drivin. Composición calculada con "
               "pedidos MC1 + catálogo WMS (bandejas abajo, cajas arriba).")

    if not _api_key():
        st.warning("⚠️ Sin API Key. Verifica Settings → Secrets (DRIVIN_API_KEY).")
        return

    hoy = datetime.now(TZ_CHILE).date()
    c1, c2 = st.columns([1, 2])
    fecha = c1.date_input("📅 Fecha de entrega", value=hoy, key="c3d_fecha",
                          min_value=hoy - timedelta(days=14), max_value=hoy + timedelta(days=14))

    try:
        paradas = cargar_paradas(fecha.strftime("%Y-%m-%d"))
    except Exception as e:
        st.error(f"Error al leer Drivin: {e}")
        return
    if paradas.empty:
        st.info("Sin rutas para esa fecha. Las rutas aparecen cuando el plan está aprobado en Drivin.")
        return

    centros = sorted(paradas["centro"].dropna().unique())
    defecto = next((i for i, c in enumerate(centros) if "ESPEJO" in str(c).upper()), 0)
    centro = c2.selectbox("🏭 Centro", centros, index=defecto, key="c3d_centro")
    paradas = paradas[paradas["centro"] == centro]

    lineas, sin_comp = construir_lineas(paradas)
    if lineas.empty:
        st.warning("Ninguna sala de este centro trae composición en custom_1. "
                   "Revisa que se haya corrido el paso de composición antes de subir a Drivin.")
        return

    posiciones = posiciones_por_camion(paradas)
    detalle, pallets = armar_pallets(lineas)
    resumen = resumir_rutas(pallets, detalle, posiciones).rename(columns={"ruta": "camion"})

    # ── Resumen de la flota
    st.markdown("#### Flota del día")
    k = st.columns(4)
    _kpi(k[0], "Camiones", len(resumen))
    _kpi(k[1], "Pallets usados", int(resumen["pallets"].sum()),
         "Pallets físicos: cada sala grande lleva los suyos; las chicas comparten")
    _kpi(k[2], "Pallets equivalentes", f"{resumen['pallets_equivalentes'].sum():.1f}",
         "Carga real si todos los pallets fueran full")
    _kpi(k[3], "Camiones sobre cupo", int(resumen["sobre_cupo"].sum()))

    tabla = resumen.sort_values("uso_camion_pct", ascending=False)[
        ["camion", "clientes", "pallets", "posiciones", "uso_camion_pct",
         "pallets_equivalentes", "compartidos", "sobre_cupo"]]
    st.dataframe(tabla.rename(columns={
        "camion": "Camión", "clientes": "Salas", "pallets": "Pallets", "posiciones": "Posiciones",
        "uso_camion_pct": "Uso %", "pallets_equivalentes": "Pallets eq.",
        "compartidos": "Compartidos", "sobre_cupo": "Sobre cupo"}),
        hide_index=True, use_container_width=True)

    if not sin_comp.empty:
        st.markdown(f'<div class="alerta-yellow">⚠️ {sin_comp["sala"].nunique()} salas sin '
                    'composición (no se dibujan): ' + ", ".join(sorted(sin_comp["sala"].unique())[:15])
                    + "</div>", unsafe_allow_html=True)

    # ── Detalle de un camión
    st.markdown("#### Vista 3D")
    c1, c2 = st.columns([2, 1])
    camion = c1.selectbox("🚚 Camión", tabla["camion"].tolist(), key="c3d_camion")
    modo = c2.radio("Color por", ["cliente", "familia"], horizontal=True, key="c3d_modo",
                    format_func=lambda m: "Sala (secuencia)" if m == "cliente" else "Envase")

    fila = resumen[resumen["camion"] == camion].iloc[0]
    k = st.columns(4)
    _kpi(k[0], "Salas", int(fila["clientes"]))
    _kpi(k[1], "Pallets / posiciones", f"{int(fila['pallets'])} / {int(fila['posiciones'])}")
    _kpi(k[2], "Uso del camión", f"{fila['uso_camion_pct']:.0f}%")
    _kpi(k[3], "Ocupación media pallet", f"{fila['ocupacion_media_pct']:.0f}%",
         "Qué tan llenos van los pallets en promedio")

    p_cam, d_cam = pallets[pallets["ruta"] == camion], detalle[detalle["ruta"] == camion]
    fig = dibujar_camion(p_cam, d_cam, posiciones=int(fila["posiciones"]),
                         color_por=modo, titulo=f"{camion} · {centro}")
    st.plotly_chart(fig, use_container_width=True)

    # ── Secuencia de entrega del camión
    seq = (d_cam.groupby(["orden_visita", "cliente"], as_index=False)
           .agg(envases=("envases", "sum"), pallets_eq=("fraccion_pallet", "sum"),
                pallets=("pallet_id", lambda s: ", ".join(sorted(s.unique())))))
    seq["pallets_eq"] = seq["pallets_eq"].round(2)
    st.dataframe(seq.rename(columns={"orden_visita": "Orden", "cliente": "Sala",
                                     "envases": "Envases", "pallets_eq": "Pallets eq.",
                                     "pallets": "Va en"}),
                 hide_index=True, use_container_width=True)
