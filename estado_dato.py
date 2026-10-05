"""
estado_dato.py — ¿Con qué dato está calculado el CxS?
=====================================================
Una sala pasó por el botón 3 del bot DRIVIN cuando su orden trae custom_3
("v1|o1=..|o2=..|e=.."). En ese caso units_1 / units_2 ya son lo DISTRIBUIDO;
si no, siguen siendo lo PROGRAMADO (botón 1).

Uso en app.py:
  · load_data:   "dato_dist": estado_dato.es_distribuido(o)   (por orden)
  · CxS:         estado_dato.panel(df)                        (franja por CV)
                 estado_dato.etiqueta / estado_dato.color     (columna "Dato" por viaje)
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

MARCA = "v1|o1="      # inicio de custom_3 que escribe el botón 3

# Colores (mismos tonos que el resto de la app)
VERDE = ("#dcfce7", "#166534")
AMARILLO = ("#fef9c3", "#854d0e")
GRIS = ("#f1f5f9", "#475569")


# ── 1. Marca por orden ─────────────────────────────────────────
def es_distribuido(orden: dict) -> bool:
    """True si la orden ya fue actualizada con la distribución (botón 3)."""
    return str(orden.get("custom_3") or "").startswith(MARCA)


# ── 2. Etiqueta por viaje (fracción de salas actualizadas) ─────
def etiqueta(fraccion) -> str:
    if pd.isna(fraccion):
        return "Programado"
    if fraccion >= 0.999:
        return "Distribuido"
    if fraccion <= 0.001:
        return "Programado"
    return "Mixto"


def color(v) -> str:
    fondo, texto = {"Distribuido": VERDE, "Mixto": AMARILLO}.get(str(v), GRIS)
    return f"background-color:{fondo};color:{texto};font-weight:600"


# ── 3. Resumen por CV ──────────────────────────────────────────
def resumen_cv(df: pd.DataFrame) -> pd.DataFrame:
    """Una fila por CV: salas, salas actualizadas, % de la venta con dato distribuido."""
    if df.empty or "dato_dist" not in df:
        return pd.DataFrame(columns=["centro", "salas", "salas_dist", "pct_venta", "estado"])
    d = df.assign(venta_dist=df["units_2"].where(df["dato_dist"], 0))
    r = (d.groupby("schema_name", as_index=False)
         .agg(salas=("address_code", "nunique"),
              salas_dist=("dato_dist", "sum"),
              venta=("units_2", "sum"), venta_dist=("venta_dist", "sum"))
         .rename(columns={"schema_name": "centro"}))
    r["pct_venta"] = (r["venta_dist"] / r["venta"].where(r["venta"] > 0) * 100).fillna(0)
    r["estado"] = r["pct_venta"].map(lambda p: etiqueta(p / 100))
    return r.sort_values(["estado", "centro"])


def panel(df: pd.DataFrame):
    """Franja arriba del CxS: estado de cada CV y % de la venta con dato distribuido."""
    r = resumen_cv(df)
    if r.empty:
        return
    total = r["venta"].sum()
    pct = r["venta_dist"].sum() / total * 100 if total else 0
    completos = int((r["estado"] == "Distribuido").sum())

    # Conclusión primero
    if completos == len(r):
        st.success(f"✅ CxS definitivo: los {len(r)} CV están actualizados con lo distribuido.")
    else:
        faltan = ", ".join(r.loc[r["estado"] != "Distribuido", "centro"].str.replace("CV ", "", regex=False))
        st.markdown(f'<div class="alerta-yellow">⏳ CxS preliminar: <b>{pct:.0f}%</b> de la venta ya tiene dato '
                    f'distribuido · {completos} de {len(r)} CV completos. Falta botón 3 en: {faltan}</div>',
                    unsafe_allow_html=True)

    # Un chip por CV
    iconos = {"Distribuido": "✅", "Mixto": "🟡", "Programado": "⏳"}
    chips = []
    for f in r.itertuples():
        fondo, texto = {"Distribuido": VERDE, "Mixto": AMARILLO}.get(f.estado, GRIS)
        detalle = "distribuido" if f.estado == "Distribuido" else (
            f"{int(f.salas_dist)}/{f.salas} salas" if f.estado == "Mixto" else "programado")
        chips.append(f'<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 10px;border-radius:999px;'
                     f'background:{fondo};color:{texto};font-size:.8rem;font-weight:600">'
                     f'{iconos[f.estado]} {f.centro.replace("CV ", "")} · {detalle}</span>')
    st.markdown("".join(chips), unsafe_allow_html=True)
